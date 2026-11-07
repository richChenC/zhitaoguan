from __future__ import annotations

import csv
import base64
from copy import copy, deepcopy
import hashlib
import html
import getpass
import io
import json
import logging
import mimetypes
import os
import re
import shutil
import uuid
import zlib
import sqlite3
import sys
import tempfile
import threading
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from contextlib import nullcontext
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse
from zipfile import BadZipFile

try:
    from . import local_security, schema_migrations, backup_service, local_storage, state_preferences
    from . import analysis_reporting, import_audit, cross_group_review, inspection_states, state_recognition, data_source, artifact_naming, task_progress, tube_lifecycle
except ImportError:
    import local_security
    import schema_migrations
    import backup_service
    import local_storage
    import state_preferences
    import analysis_reporting
    import import_audit
    import cross_group_review
    import inspection_states
    import state_recognition
    import data_source
    import artifact_naming
    import task_progress
    import tube_lifecycle

_BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "_MEIPASS", "") else None
ROOT = _BUNDLE_ROOT or Path(__file__).resolve().parents[2]
VENDOR_DIR = ROOT / ".vendor"
if VENDOR_DIR.is_dir():
    sys.path.insert(0, str(VENDOR_DIR))

# Only the Electron desktop renderer is served. This project has no
# separately supported web product.
STATIC = ROOT / "src" / "desktop-ui"
DATA_DIR = Path(os.environ.get("THIMBLE_DATA_DIR", str(local_storage.user_root() / "data"))).expanduser().resolve()
DB_PATH = Path(os.environ.get("THIMBLE_DB_PATH", str(DATA_DIR / "thimble.db"))).expanduser().resolve()
EXCEL_DIR = Path(os.environ.get("THIMBLE_OUTPUT_DIR", str(local_storage.user_root() / "output" / "excel"))).expanduser().resolve()
REPORT_DIR = Path(os.environ.get("THIMBLE_REPORT_DIR", str(local_storage.user_root() / "output" / "reports"))).expanduser().resolve()
LOG_PATH = Path(os.environ.get("THIMBLE_LOG_PATH", str(DATA_DIR / "thimble.log"))).expanduser().resolve()
SERVICE_VERSION = "2026.10.26.1"
try:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=LOG_PATH, level=logging.INFO, encoding="utf-8", format="%(asctime)s %(levelname)s %(message)s")
except OSError:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOGGER = logging.getLogger("thimble")

# Directory scans intentionally run more than once during the import wizard:
# the first pass previews RPT candidates, the second validates the selected
# files, and the final pass writes the records.  Keep a small stat-keyed cache
# so an unchanged source is parsed once per process.  A changed file naturally
# gets a new key and the old entry is evicted when the cache reaches its bound.
_IMPORT_CACHE_LIMIT = 512
_IMPORT_CACHE_LOCK = threading.RLock()
_ECT_HEADER_CACHE: dict[tuple, dict] = {}
_REPORT_CACHE: dict[tuple, list] = {}
_FILE_HASH_CACHE: dict[tuple, str] = {}


def _source_cache_key(path: Path) -> tuple:
    resolved = path.expanduser().resolve()
    stat = resolved.stat()
    return str(resolved).casefold(), int(stat.st_mtime_ns), int(stat.st_size)


def _cache_get(cache: dict, key):
    with _IMPORT_CACHE_LOCK:
        value = cache.get(key)
        return None if value is None else deepcopy(value)


def _cache_put(cache: dict, key, value):
    with _IMPORT_CACHE_LOCK:
        if key in cache:
            cache.pop(key, None)
        cache[key] = deepcopy(value)
        while len(cache) > _IMPORT_CACHE_LIMIT:
            cache.pop(next(iter(cache)))
    return value


def _cached_sha256(path: Path) -> str:
    key = _source_cache_key(path)
    cached = _cache_get(_FILE_HASH_CACHE, key)
    if cached is not None:
        return cached
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return _cache_put(_FILE_HASH_CACHE, key, digest.hexdigest())

PLAIN_EXCEL_FONT = "宋体"


def _excel_factory(name):
    """Load the heavy Excel stack only when an Excel operation is requested."""
    from openpyxl import Workbook as _Workbook
    from openpyxl.packaging.custom import StringProperty as _StringProperty
    from openpyxl.styles import Alignment as _Alignment
    from openpyxl.styles import Border as _Border
    from openpyxl.styles import Font as _Font
    from openpyxl.styles import PatternFill as _PatternFill
    from openpyxl.styles import Side as _Side
    from openpyxl.utils import get_column_letter as _get_column_letter
    values = {
        "Workbook": _Workbook,
        "StringProperty": _StringProperty,
        "Alignment": _Alignment,
        "Border": _Border,
        "Font": _Font,
        "PatternFill": _PatternFill,
        "Side": _Side,
        "get_column_letter": _get_column_letter,
    }
    return values[name]


def Workbook(*args, **kwargs):
    return _excel_factory("Workbook")(*args, **kwargs)


def StringProperty(*args, **kwargs):
    return _excel_factory("StringProperty")(*args, **kwargs)


def Alignment(*args, **kwargs):
    return _excel_factory("Alignment")(*args, **kwargs)


def Border(*args, **kwargs):
    return _excel_factory("Border")(*args, **kwargs)


def Font(*args, **kwargs):
    return _excel_factory("Font")(*args, **kwargs)


def PatternFill(*args, **kwargs):
    return _excel_factory("PatternFill")(*args, **kwargs)


def Side(*args, **kwargs):
    return _excel_factory("Side")(*args, **kwargs)


def get_column_letter(*args, **kwargs):
    return _excel_factory("get_column_letter")(*args, **kwargs)


def apply_plain_excel_table(sheet, header_rows=(1,), data_start=None, end_row=None):
    """Use the user's plain white, black-grid Excel table style."""
    plain_side = Side(style="thin", color="000000")
    plain_border = Border(left=plain_side, right=plain_side,
                          top=plain_side, bottom=plain_side)
    header_rows = set(header_rows)
    first_data = data_start or (max(header_rows) + 1 if header_rows else 1)
    last_data = min(end_row or sheet.max_row, sheet.max_row)
    for row in sheet.iter_rows():
        row_number = row[0].row if row else 0
        if row_number not in header_rows and not first_data <= row_number <= last_data:
            continue
        for cell in row:
            if cell.value is None and not cell.has_style:
                continue
            font = copy(cell.font)
            font.name = PLAIN_EXCEL_FONT
            font.sz = 10
            font.color = "000000"
            if row_number in header_rows:
                font.bold = False
                cell.fill = PatternFill(fill_type=None)
            cell.font = font
            cell.border = plain_border
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def recent_service_log(limit: int = 120) -> dict:
    """Return a bounded tail of the local service log for operator diagnostics."""
    limit = max(1, min(int(limit or 120), 500))
    try:
        with LOG_PATH.open("rb") as stream:
            start = max(0, stream.seek(0, 2) - 128 * 1024)
            stream.seek(start)
            if start:
                stream.readline()
            lines = stream.read(128 * 1024).decode("utf-8", errors="replace").splitlines()
    except OSError as exc:
        return {"path": str(LOG_PATH), "lines": [], "error": str(exc)}
    return {"path": str(LOG_PATH), "lines": lines[-limit:]}


def require_import_space(target=None) -> None:
    """Check capacity before backup or import writes, including a new directory."""
    destination = Path(target or DB_PATH).resolve()
    folder = destination.parent
    while not folder.exists() and folder != folder.parent:
        folder = folder.parent
    database_size = DB_PATH.stat().st_size if DB_PATH.is_file() else 0
    required = max(64 * 1024 * 1024, database_size * 2)
    available = shutil.disk_usage(folder).free
    if available < required:
        raise ValueError(
            f"磁盘空间不足，无法导入。存储位置：{destination}；"
            f"可用 {available / 1024 / 1024:.1f} MB，至少需要 {required / 1024 / 1024:.1f} MB。"
            "请释放空间后点击“重试未完成文件”，已生成的 Excel 可以继续使用。"
        )


def import_error_response(path: str, error: Exception) -> dict:
    context = {"batch_id": error.import_batch_id} if getattr(error, "import_batch_id", None) else {}
    batch = context.get("batch_id")
    detail = str(error).strip() or type(error).__name__
    if "database or disk is full" in detail.lower() or getattr(error, "errno", None) == 28:
        detail = "磁盘空间不足，数据库无法写入；请释放数据库所在磁盘的空间后重试"
    elif "database is locked" in detail.lower():
        detail = "数据库正被其他操作占用，请等待当前操作完成后重试"
    message = f"导入处理失败：{detail}"
    if batch:
        message = f"导入处理失败（批次 #{batch}）：{detail}"
    return {
        "error": message,
        "message": message,
        "log_path": str(LOG_PATH),
        "details_url": f"/api/data-quality?batch_id={batch}" if batch else "/api/logs/recent",
        **context,
    }

# Official plate confirmed by the user on 2026-10-20: N5 = odd 15 / even 42.
ODD_POSITIONS = "L11 G14 N7 H13 J12 R8 N12 N10 L14 J15 H11 F13 J7 L5 N5 L8 N8 L6 J10 L9 F9 C12 G7 L4 J5 M3 G9 E11 F11 D12 F6 B10 D7 E5 H3 J3 H6 H4 F8 D10 B7 B5 D3 D5 F2 H1 B8 F4 C8 A9".split()
EVEN_POSITIONS = "B5 C8 E11 D10 D12 C12 B10 B7 A9 B8 D5 D3 F6 H13 F9 G14 F13 E5 F11 D7 G7 F2 H6 H11 J10 J12 J15 G9 F8 F4 H3 H1 J3 N12 L9 L11 L14 J5 J7 H4 M3 N5 R8 N7 N8 N10 L5 L8 L6 L4".split()

DATA_GROUP_NAME = re.compile(r"^TH\d+I\d+CAL\d+$", re.I)
IGNORED_SCAN_DIRECTORIES = {
    "整合一起看", "临时输出", "临时文件", "输出", "output", "excel", "tmp", "temp",
    "人工汇总", "人工汇总表", "汇总表", "辅助目录",
}
SITE_NAMES = {
    "LHNP": "红沿河", "CNPS": "大亚湾", "LNPS": "岭澳", "NDNP": "宁德",
    "YJNP": "阳江", "BLNP": "防城港", "TSNP": "台山", "HENP": "惠州",
    "CNMP": "苍南", "LFNP": "陆丰",
}

STANDARD_EXCEL_FIELDS = [
    "电站名称", "大修号", "机组号", "安全级别", "设备名称", "被检部位", "通道编号",
    "在堆芯内的位置", "幅值", "相位", "磨损深度", "三字码", "测量通道",
    "磨损位置", "探头类型", "分析人员", "数据", "数据组", "备注", "堵管移位信息"
]
# 电站代号必须全局唯一：陆丰取 LF，与前端地图 SITE_GEO.apiCode 定案一致，
# 避免与岭澳 L 撞码导致串站；太平岭（惠州）台账用 P、地图显示用 HZ，由前端桥接。
STATION_CODES = {
    "大亚湾": "D", "岭澳": "L", "宁德": "N", "红沿河": "H", "阳江": "Y",
    "防城港": "F", "台山": "T", "惠州": "P", "苍南": "C", "陆丰": "LF",
}
STATION_PROJECT_HINTS = (
    ("大亚湾", ("CNPS",)),
    ("岭澳", ("LNPS",)),
    ("红沿河", ("红沿河项目", "LHNP")),
    ("宁德", ("宁德项目", "NDNP")),
    ("阳江", ("阳江项目", "YJNP")),
    ("防城港", ("防城港项目", "BLNP")),
    ("台山", ("台山项目", "TSNP")),
    ("惠州", ("太平岭", "惠州", "HENP")),
    ("苍南", ("苍南项目", "CNMP")),
    ("陆丰", ("陆丰项目", "LFNP")),
    ("外部市场", ("外部市场",)),
)


def outage_code(outage: str) -> str:
    """取大修号开头的电站代号；第二位是字母则取两位（LF 先于 L，避免陆丰误判成岭澳）。"""
    return analysis_reporting.site_of_outage(outage)


@dataclass
class Finding:
    outage: str
    unit_id: int
    thimble_id: int
    position: str
    entry_no: int | None
    volts: float | None
    degrees: float | None
    indication: str
    percent: float | None
    channel: str
    location: str
    datapoint: int | None
    liss_region_size: int | None
    analyst: str
    analysis: str
    filepath: str
    filename: str
    calgroup: str
    report_path: str
    site_code: str = ""
    site_owner: str = ""
    component: str = ""
    tester: str = ""
    probe: str = ""
    column_no: int | None = None
    channel_id: str = ""
    measurement_type: str = ""
    uid: str = ""
    distance: str = ""
    extent: str = ""
    length: str = ""
    width: str = ""
    comment: str = ""
    maintenance_text: str = ""
    source_key: str = ""
    business_key: str = ""
    source_indication: str = ""
    indication_resolution: str = "source"
    report_unit_raw: str = ""


BUSINESS_KEY_FIELDS = (
    "outage", "unit_id", "thimble_id", "position", "entry_no", "volts", "degrees",
    "indication", "percent", "channel", "location", "datapoint", "liss_region_size",
    "analyst", "analysis", "filename", "calgroup", "site_code", "site_owner", "component",
    "tester", "probe", "column_no", "channel_id", "measurement_type", "uid", "distance",
    "extent", "length", "width", "comment", "maintenance_text",
)


def finding_business_key(values) -> str:
    """Identity of one report record, excluding import time and machine paths."""
    def read(name):
        value_ = values.get(name) if isinstance(values, dict) else getattr(values, name, None)
        return "" if value_ is None else str(value_).strip().casefold()
    payload = "\x1f".join(read(name) for name in BUSINESS_KEY_FIELDS)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def audit_duplicate(db: sqlite3.Connection, values: dict, action: str = "skipped") -> None:
    business_key = values.get("business_key") or finding_business_key(values)
    kept = db.execute("SELECT id FROM findings WHERE business_key=? ORDER BY id LIMIT 1", (business_key,)).fetchone()
    if not kept and values.get("source_key"):
        kept = db.execute("SELECT id FROM findings WHERE source_key=? ORDER BY id LIMIT 1", (values["source_key"],)).fetchone()
    db.execute("""INSERT INTO duplicate_records(
        detected_at,kept_finding_id,duplicate_source_key,business_key,reason,source_path,payload_json,action
    ) VALUES(?,?,?,?,?,?,?,?)""", (
        datetime.now().isoformat(timespec="seconds"), kept["id"] if kept else None,
        values.get("source_key", ""), business_key, "完全相同的检测记录",
        values.get("report_path") or values.get("filepath") or "",
        json.dumps(values, ensure_ascii=False, default=str), action,
    ))


def duplicate_summary(limit: int = 100) -> dict:
    with connect() as db:
        total = db.execute("SELECT COUNT(*) FROM findings").fetchone()[0]
        duplicate_count = db.execute("SELECT COUNT(*) FROM duplicate_records").fetchone()[0]
        rows = db.execute("""SELECT id,detected_at,kept_finding_id,reason,source_path,payload_json,action
            FROM duplicate_records ORDER BY id DESC LIMIT ?""", (max(1, min(limit, 500)),)).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            kept = db.execute("SELECT * FROM findings WHERE id=?", (item["kept_finding_id"],)).fetchone()
            item["kept_payload_json"] = json.dumps(dict(kept), ensure_ascii=False, default=str) if kept else "{}"
            items.append(item)
        current_duplicates = sum(
            count - 1 for count in Counter(
                finding_business_key(dict(row)) for row in db.execute("SELECT * FROM findings")
            ).values() if count > 1
        )
    return {"findings": total, "duplicates": duplicate_count, "current_duplicates": current_duplicates, "items": items}


def deduplicate_database() -> dict:
    _auto_backup("deduplicate")
    with connect() as db:
        rows = [dict(row) for row in db.execute("SELECT * FROM findings ORDER BY id")]
        groups: dict[str, list[dict]] = {}
        for row in rows:
            groups.setdefault(finding_business_key(row), []).append(row)
        duplicate_groups = [group for group in groups.values() if len(group) > 1]
        removed = sum(len(group) - 1 for group in duplicate_groups)
        backup_path = ""
        if removed:
            backup_dir = DB_PATH.parent / "backups"; backup_dir.mkdir(parents=True, exist_ok=True)
            backup = backup_dir / artifact_naming.filename("去重前备份", "业务数据库", "db")
            backup_db = sqlite3.connect(backup)
            try:
                db.backup(backup_db)
            finally:
                backup_db.close()
            backup_path = str(backup)
            db.execute("DROP INDEX IF EXISTS idx_findings_business_key")
            for business_key, group in groups.items():
                kept = group[0]
                db.execute("UPDATE findings SET business_key=? WHERE id=?", (business_key, kept["id"]))
                for duplicate in group[1:]:
                    db.execute("""INSERT INTO duplicate_records(
                        detected_at,kept_finding_id,duplicate_source_key,business_key,reason,source_path,payload_json,action
                    ) VALUES(?,?,?,?,?,?,?,?)""", (
                        datetime.now().isoformat(timespec="seconds"), kept["id"], duplicate.get("source_key", ""),
                        business_key, "业务字段完全相同", duplicate.get("report_path") or duplicate.get("filepath") or "",
                        json.dumps(duplicate, ensure_ascii=False, default=str), "removed",
                    ))
                    db.execute("DELETE FROM findings WHERE id=?", (duplicate["id"],))
            db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_findings_business_key ON findings(business_key)
                WHERE business_key IS NOT NULL AND business_key<>''""")
    result = duplicate_summary()
    result.update({"removed": removed, "backup_path": backup_path, "before": len(rows), "after": len(rows) - removed})
    return result


# Tables that represent imported acquisition data or derived report state.
# Keep this allow-list explicit: account, security, configuration and recovery
# records must survive a business-data reset.
CLEAR_DATABASE_TABLES = (
    "import_batch_reports", "import_batch_artifacts", "import_finding_changes",
    "import_finding_sources", "import_state_changes", "inspection_state_candidates",
    "validation_issues", "file_artifacts", "import_excel_mappings", "import_batches",
    "cross_group_exclusions", "cross_group_reviews", "core_mapping_corrections",
    "finding_edit_history", "tube_repairs", "tube_state_history", "tube_states",
    "tube_state_scopes", "indication_resolution_audit", "duplicate_records", "findings",
    "report_versions", "report_exports", "delete_batches",
)

PRESERVED_DATABASE_TABLES = (
    "analysis_rules", "backup_policy", "grid_positions", "ledger_identity",
    "operation_logs", "restore_points", "state_preferences", "schema_migrations",
    *local_security.IDENTITY_TABLES,
)


def clear_database() -> dict:
    backup = create_database_backup(
        note="清空检测数据前自动创建，包含清空前完整数据库",
        kind="pre_clear",
    )
    backup["verification"] = validate_backup_file(backup["path"])
    tables = CLEAR_DATABASE_TABLES
    with connect() as db:
        present = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in tables if table in present}
        db.execute("BEGIN IMMEDIATE")
        try:
            for table in tables:
                if table in present:
                    db.execute(f"DELETE FROM {table}")
            db.execute("UPDATE ledger_identity SET token=? WHERE id=1", (uuid.uuid4().hex,))
        except Exception:
            db.rollback()
            raise
        removed = sum(counts.values())
        _log_operation("clear_database", "all", "清空业务数据；保留账户、安全审计、操作日志与恢复点", removed,
                       backup_file=backup["path"], connection=db)
    preserved = sorted(set(PRESERVED_DATABASE_TABLES) & present)
    return {"ok": True, "cleared": counts, "backup": backup, "preserved": preserved}


@dataclass(frozen=True)
class DataGroupContext:
    path: Path
    calgroup: str
    site_owner: str = ""
    site_code: str = ""
    unit_id: int = 0
    component: str = ""
    outage: str = ""
    probe_model: str = ""
    tester: str = ""
    sum_path: str = ""
    warning: str = ""


def value(node: ET.Element, name: str, *, strip: bool = True) -> str:
    child = node.find(name)
    raw = (child.text or "") if child is not None else ""
    return raw.strip() if strip else raw


def number(text: str, cast):
    try:
        return cast(text)
    except (TypeError, ValueError):
        return None


def infer_outage(path: Path) -> str:
    for part in reversed(path.parts):
        match = re.search(r"(?<![A-Z0-9])([A-Z]{1,2}\d{3})(?![A-Z0-9])", part.upper())
        if match:
            return match.group(1)
    directory = path if path.is_dir() else path.parent
    try:
        summaries = [candidate for candidate in directory.iterdir() if candidate.is_file() and candidate.suffix.lower() == ".sum"]
    except (OSError, PermissionError):
        summaries = []
    for summary in summaries:
        try:
            site_node = ET.parse(summary).getroot().find("Site")
            outage = value(site_node, "Outage").upper() if site_node is not None else ""
            if re.fullmatch(r"[A-Z]{1,2}\d{3}", outage):
                return outage
        except (ET.ParseError, OSError):
            continue
    return "UNKNOWN"


def infer_unit(outage: str, report_id: str) -> int:
    match = re.search(r"[A-Z]{1,2}(\d)", str(outage or "").upper())
    return int(match.group(1)) if match else (number(report_id, int) or 0)


def infer_station(path: Path, outage: str = "") -> tuple[str, str]:
    context = "|".join(path.parts).upper()
    for station, hints in STATION_PROJECT_HINTS:
        if any(hint.upper() in context for hint in hints):
            return station, STATION_CODES.get(station, outage_code(outage))
    code = outage_code(outage)
    # 大亚湾项目是项目级目录，内部仍需按 D/L 区分大亚湾与岭澳电站。
    if "大亚湾项目" in context:
        station = {"D": "大亚湾", "L": "岭澳"}.get(code, "大亚湾")
        return station, code or STATION_CODES[station]
    station = next((name for name, station_code in STATION_CODES.items() if station_code == code), code or "未知基地")
    return station, code


def position_for(unit_id: int, thimble_id: int) -> str:
    positions = ODD_POSITIONS if unit_id % 2 else EVEN_POSITIONS
    return positions[thimble_id - 1] if 1 <= thimble_id <= len(positions) else ""


def split_location(location: str) -> tuple[str, float | None]:
    parsed = analysis_reporting.parse_location(location)
    return parsed if parsed else (str(location or "").strip(), None)


def format_location(location: str) -> str:
    zone, offset = split_location(location)
    if not zone:
        return "-"
    if not re.fullmatch(r"P[1-6]", zone, re.I):
        return zone
    value = 0 if offset is None else offset
    rendered = str(int(value)) if float(value).is_integer() else f"{value:g}"
    return f"{zone.upper()} + {rendered} mm"


def normalize_header(value_) -> str:
    return re.sub(r"[\s()（）%％/\\_-]+", "", str(value_ or "")).lower()


def outage_from_standard_row(row: dict, source: Path, outage_hint: str = "") -> str:
    explicit = str(row.get("大修号") or row.get("大修") or "").strip().upper()
    if re.fullmatch(r"[A-Z]{1,2}\d{3}", explicit):
        return explicit
    hinted = str(outage_hint or "").strip().upper()
    if re.fullmatch(r"[A-Z]{1,2}\d{3}", hinted):
        return hinted
    group = str(row.get("数据组") or "").strip().upper()
    match = re.search(r"TH(\d)I(\d{2})", group)
    station = str(row.get("电站名称") or "").strip()
    code = next((value_ for name, value_ in STATION_CODES.items() if name in station), "")
    if not code and "太平岭" in station:
        code = "P"
    if match and code:
        return f"{code}{match.group(1)}{match.group(2)}"
    inferred = infer_outage(source)
    return inferred if inferred != "UNKNOWN" else ""


ECT_NAME = re.compile(r"^DIR(\d{3})C(\d{3})I(\d{3})\.ECT$", re.I)


def discover_data_groups(directory: str | Path, ignored_directories: set[str] | None = None) -> list[Path]:
    base = Path(directory).expanduser().resolve()
    if not base.is_dir():
        raise ValueError("所选路径不是有效文件夹")
    ignored = {name.casefold() for name in (ignored_directories or set()) | IGNORED_SCAN_DIRECTORIES}
    groups: list[Path] = []
    for current, directories, _ in os.walk(base):
        directories[:] = [name for name in directories if name.casefold() not in ignored]
        path = Path(current)
        if DATA_GROUP_NAME.fullmatch(path.name):
            groups.append(path)
            directories[:] = []
    return sorted(groups, key=lambda path: str(path).casefold())


def parse_sum(group_dir: Path) -> DataGroupContext:
    summaries = sorted(path for path in group_dir.iterdir() if path.is_file() and path.suffix.casefold() == ".sum")
    if not summaries:
        return DataGroupContext(group_dir, group_dir.name, warning="缺少 SUM 文件，机组号和堆芯位置留空")
    warnings = []
    if len(summaries) > 1:
        warnings.append(f"发现 {len(summaries)} 个 SUM，使用 {summaries[0].name}")
    try:
        root = ET.parse(summaries[0]).getroot()
        site = root.find("Site"); site = site if site is not None else root
        probe = root.find("Probe"); probe = probe if probe is not None else root
        equipment = root.find("Equipment"); equipment = equipment if equipment is not None else root
        unit_id = number(value(site, "Unit"), int) or 0
        if unit_id <= 0:
            warnings.append("SUM Unit 缺失或无法解析，堆芯位置留空")
        component = value(site, "Component")
        if component and component.upper() != "TH":
            warnings.append(f"SUM Component={component}，不是 TH")
        outage = value(site, "Outage").upper()
        return DataGroupContext(
            path=group_dir, calgroup=group_dir.name, site_owner=value(site, "Owner"),
            site_code=value(site, "SiteCode") or outage_code(outage), unit_id=unit_id, component=component,
            outage=outage, probe_model=value(probe, "Model"),
            tester=value(equipment, "Tester"), sum_path=str(summaries[0]), warning="；".join(warnings),
        )
    except (ET.ParseError, OSError) as exc:
        return DataGroupContext(group_dir, group_dir.name, sum_path=str(summaries[0]), warning=f"SUM 解析失败：{exc}")


def parse_ect_header(path: Path) -> dict:
    path = path.expanduser().resolve()
    cache_key = _source_cache_key(path)
    cached = _cache_get(_ECT_HEADER_CACHE, cache_key)
    if cached is not None:
        return cached
    match = ECT_NAME.match(path.name)
    if not match:
        raise ValueError("ECT文件名不符合 DIRrrrCcccIeee.ECT")
    name_row, name_col, name_entry = map(int, match.groups())
    payload = path.read_bytes()
    raw = payload[:131072].decode("utf-8", errors="ignore")
    xml_match = re.search(r"<HeaderTube\b.*?</HeaderTube>", raw, re.S)
    if not xml_match:
        raise ValueError("ECT中未找到HeaderTube XML")
    header = ET.fromstring(xml_match.group(0))
    row, col, entry = number(value(header, "Row"), int), number(value(header, "Col"), int), number(value(header, "Entry"), int)
    result = {
        "path": str(path), "filename": path.name, "calgroup": path.parent.name,
        "name_row": name_row, "name_col": name_col, "name_entry": name_entry,
        "row": row, "col": col, "entry": entry, "datetime": value(header, "DateTime"),
        "calibration": name_row == 999 or row == 999,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    return _cache_put(_ECT_HEADER_CACHE, cache_key, result)


def scan_thimble_directory(directory: str) -> dict:
    base = Path(directory).expanduser().resolve()
    if not base.is_dir():
        raise ValueError("所选路径不是有效文件夹")
    ect_rows, errors = [], []
    paths = [path for group in discover_data_groups(base) for path in group.iterdir() if path.is_file() and path.suffix.casefold() == ".ect"]
    for path in sorted(paths):
        try:
            item = parse_ect_header(path)
            status = []
            if (item["name_row"], item["name_col"], item["name_entry"]) != (item["row"], item["col"], item["entry"]):
                status.append("文件名与HeaderTube不一致")
            if not item["calibration"] and not 1 <= (item["row"] or 0) <= 50:
                status.append("管号超出1-50")
            item["validation"] = "通过" if not status else "；".join(status)
            ect_rows.append(item)
            if status:
                errors.append({"file": str(path), "type": "ECT校验", "message": item["validation"]})
        except Exception as exc:
            errors.append({"file": str(path), "type": "ECT解析", "message": str(exc)})
    normal = [item for item in ect_rows if not item["calibration"] and item["validation"] == "通过"]
    unique_tubes = sorted({item["row"] for item in normal})
    return {
        "ect": ect_rows, "errors": errors, "unique_tubes": unique_tubes,
        "missing_tubes": sorted(set(range(1, 51)) - set(unique_tubes)),
        "calibration_count": sum(item["calibration"] for item in ect_rows),
    }


def parse_report(path: Path, context: DataGroupContext | None = None) -> list[Finding]:
    path = path.expanduser().resolve()
    context = context or parse_sum(path.parent)
    try:
        cache_key = (*_source_cache_key(path), context.site_code, context.unit_id,
                     context.component, context.outage, context.calgroup,
                     context.probe_model, context.site_owner)
    except OSError:
        cache_key = (str(path).casefold(), "missing", context.site_code, context.unit_id,
                     context.component, context.outage, context.calgroup)
    cached = _cache_get(_REPORT_CACHE, cache_key)
    if cached is not None:
        return cached
    root = ET.fromstring(path.read_bytes())
    findings: list[Finding] = []
    for item in root.findall("ReportEntry"):
        thimble_id = number(value(item, "Row"), int) or 0
        uid = value(item, "Uid")
        filename = value(item, "Filename")
        calgroup = value(item, "Calgroup") or context.calgroup
        findings.append(Finding(
            outage=context.outage, unit_id=context.unit_id, thimble_id=thimble_id,
            position=position_for(context.unit_id, thimble_id) if context.unit_id else "",
            entry_no=number(value(item, "Entry"), int),
            volts=number(value(item, "Volts"), float),
            degrees=number(value(item, "Degrees"), float),
            indication=value(item, "Indication"), percent=number(value(item, "Percent"), float),
            channel=value(item, "Channel"), location=value(item, "Location"),
            datapoint=number(value(item, "Datapoint"), int),
            liss_region_size=number(value(item, "LissRegionSize"), int),
            analyst=value(item, "Analyst"), analysis=value(item, "Analysis", strip=False),
            filepath=value(item, "Filepath"), filename=filename,
            calgroup=calgroup, report_path=str(path), site_code=context.site_code,
            site_owner=context.site_owner, component=context.component, tester=context.tester,
            probe=value(item, "Probe") or context.probe_model,
            column_no=number(value(item, "Column"), int), channel_id=value(item, "ChannelID"),
            measurement_type=value(item, "MeasurementType"), uid=uid,
            distance=value(item, "Distance"), extent=value(item, "Extent"),
            length=value(item, "Length"), width=value(item, "Width"), comment=value(item, "Comment", strip=False),
            report_unit_raw=value(item, "Id"),
        ))
        findings[-1].source_key = finding_business_key(findings[-1])
    return _cache_put(_REPORT_CACHE, cache_key, findings)


ClosingConnection = data_source.ClosingConnection


def connect() -> sqlite3.Connection:
    return data_source.SQLiteProvider(DB_PATH).connect(cross_group_review.attach_view)


def _legacy_init_db(db_path) -> None:
    db_path = Path(db_path)
    def connect():
        return data_source.SQLiteProvider(db_path).connect(cross_group_review.attach_view)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        # WAL keeps the desktop UI responsive while an import or export is running.
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS findings (
          id INTEGER PRIMARY KEY, outage TEXT NOT NULL, unit_id INTEGER NOT NULL,
          thimble_id INTEGER NOT NULL, position TEXT, entry_no INTEGER, volts REAL,
          degrees REAL, indication TEXT, percent REAL, channel TEXT, location TEXT,
          datapoint INTEGER, liss_region_size INTEGER, analyst TEXT, analysis TEXT,
          filepath TEXT, filename TEXT, calgroup TEXT, report_path TEXT,
          site_code TEXT DEFAULT '', site_owner TEXT DEFAULT '', component TEXT DEFAULT '',
          tester TEXT DEFAULT '', probe TEXT DEFAULT '', column_no INTEGER, channel_id TEXT DEFAULT '',
          measurement_type TEXT DEFAULT '', uid TEXT DEFAULT '', distance TEXT DEFAULT '', extent TEXT DEFAULT '',
          length TEXT DEFAULT '', width TEXT DEFAULT '', comment TEXT DEFAULT '',
          maintenance_text TEXT DEFAULT '', source_key TEXT,
          business_key TEXT, source_indication TEXT DEFAULT '', indication_resolution TEXT DEFAULT 'source',
          imported_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tube_states (
          outage TEXT NOT NULL, unit_id INTEGER NOT NULL, thimble_id INTEGER NOT NULL,
          state TEXT NOT NULL DEFAULT 'normal', offset_mm REAL NOT NULL DEFAULT 0,
          note TEXT NOT NULL DEFAULT '', PRIMARY KEY(outage, unit_id, thimble_id)
        );
        CREATE TABLE IF NOT EXISTS tube_state_scopes (
          outage TEXT NOT NULL, unit_id INTEGER NOT NULL, created_at TEXT NOT NULL,
          PRIMARY KEY(outage, unit_id)
        );
        CREATE TABLE IF NOT EXISTS duplicate_records (
          id INTEGER PRIMARY KEY, detected_at TEXT NOT NULL, kept_finding_id INTEGER,
          duplicate_source_key TEXT, business_key TEXT NOT NULL, reason TEXT NOT NULL,
          source_path TEXT DEFAULT '', payload_json TEXT NOT NULL, action TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS finding_edit_history (
          id INTEGER PRIMARY KEY, finding_id INTEGER NOT NULL, field_name TEXT NOT NULL,
          before_json TEXT NOT NULL, after_json TEXT NOT NULL, operator TEXT NOT NULL,
          edited_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ledger_identity (
          id INTEGER PRIMARY KEY CHECK(id=1), token TEXT NOT NULL
        );
        INSERT OR IGNORE INTO ledger_identity(id,token) VALUES(1,lower(hex(randomblob(16))));
        CREATE TABLE IF NOT EXISTS indication_resolution_audit (
          id INTEGER PRIMARY KEY, finding_id INTEGER NOT NULL, changed_at TEXT NOT NULL,
          source_indication TEXT DEFAULT '', resolved_indication TEXT NOT NULL,
          action TEXT NOT NULL, source_path TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS import_batches (
          id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
          source_path TEXT NOT NULL, import_kind TEXT NOT NULL, operator TEXT DEFAULT '',
          parser_version TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'running',
          files_seen INTEGER NOT NULL DEFAULT 0, rows_parsed INTEGER NOT NULL DEFAULT 0,
          rows_inserted INTEGER NOT NULL DEFAULT 0, rows_skipped INTEGER NOT NULL DEFAULT 0,
          error_count INTEGER NOT NULL DEFAULT 0, rollback_at TEXT, note TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS file_artifacts (
          id INTEGER PRIMARY KEY, batch_id INTEGER, path TEXT NOT NULL, filename TEXT NOT NULL,
          extension TEXT NOT NULL, sha256 TEXT NOT NULL, file_size INTEGER NOT NULL DEFAULT 0,
          modified_at TEXT, file_kind TEXT DEFAULT '', parse_status TEXT DEFAULT 'pending',
          error_message TEXT DEFAULT '', UNIQUE(path, sha256)
        );
        CREATE TABLE IF NOT EXISTS validation_issues (
          id INTEGER PRIMARY KEY, batch_id INTEGER, created_at TEXT NOT NULL,
          severity TEXT NOT NULL DEFAULT 'error', code TEXT NOT NULL, message TEXT NOT NULL,
          source_path TEXT DEFAULT '', sheet_name TEXT DEFAULT '', row_number INTEGER,
          field_name TEXT DEFAULT '', payload_json TEXT DEFAULT '{}', resolved_at TEXT,
          UNIQUE(batch_id, code, source_path, sheet_name, row_number, field_name, message)
        );
        CREATE TABLE IF NOT EXISTS report_versions (
          id INTEGER PRIMARY KEY, outage TEXT NOT NULL, unit_id INTEGER NOT NULL,
          calgroup TEXT NOT NULL, filename TEXT NOT NULL, source_path TEXT NOT NULL,
          version_label TEXT DEFAULT '', selected INTEGER NOT NULL DEFAULT 0,
          selected_at TEXT, selected_by TEXT DEFAULT '', sha256 TEXT DEFAULT '',
          UNIQUE(outage, unit_id, calgroup, filename, source_path)
        );
        CREATE TABLE IF NOT EXISTS tube_repairs (
          id INTEGER PRIMARY KEY, outage TEXT NOT NULL, unit_id INTEGER NOT NULL,
          thimble_id INTEGER NOT NULL, repair_type TEXT NOT NULL, offset_mm REAL NOT NULL DEFAULT 0,
          offset_unit TEXT NOT NULL DEFAULT 'mm', direction TEXT NOT NULL DEFAULT 'positive',
          note TEXT DEFAULT '', effective_at TEXT, created_at TEXT NOT NULL,
          UNIQUE(outage, unit_id, thimble_id)
        );
        CREATE TABLE IF NOT EXISTS grid_positions (
          unit_parity TEXT NOT NULL, thimble_id INTEGER NOT NULL, position TEXT NOT NULL,
          source TEXT DEFAULT '', verified INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(unit_parity, thimble_id), UNIQUE(unit_parity, position)
        );
        CREATE TABLE IF NOT EXISTS report_exports (
          id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, export_kind TEXT NOT NULL,
          outage TEXT DEFAULT '', old_outage TEXT DEFAULT '', new_outage TEXT DEFAULT '',
          unit_id INTEGER, path TEXT NOT NULL, metadata_json TEXT DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS tube_state_history (
          id INTEGER PRIMARY KEY, outage TEXT NOT NULL, unit_id INTEGER NOT NULL,
          thimble_id INTEGER NOT NULL, action TEXT NOT NULL, before_json TEXT,
          after_json TEXT, operator TEXT NOT NULL, created_at TEXT NOT NULL,
          effective_timing TEXT NOT NULL DEFAULT 'after_inspection'
        );
        CREATE TABLE IF NOT EXISTS analysis_rules (
          id INTEGER PRIMARY KEY, version INTEGER NOT NULL UNIQUE,
          name TEXT NOT NULL, match_tolerance_mm REAL NOT NULL,
          note TEXT DEFAULT '', created_by TEXT NOT NULL, created_at TEXT NOT NULL,
          is_active INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS restore_points (
          id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, path TEXT NOT NULL,
          sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL,
          operator TEXT NOT NULL, note TEXT DEFAULT '',
          kind TEXT NOT NULL DEFAULT 'manual'
        );
        """)
        # 对比规则种子：历史库升级后自动建立 v1，容差与此前硬编码的 0.01 mm 一致，行为不回退。
        if not db.execute("SELECT 1 FROM analysis_rules LIMIT 1").fetchone():
            db.execute("""INSERT INTO analysis_rules(version,name,match_tolerance_mm,note,created_by,created_at,is_active)
                          VALUES(1,'初始匹配规则',?,?,?,?,1)""",
                       (analysis_reporting.DEFAULT_RULES["match_tolerance_mm"],
                        "由历史版本升级自动建立，与此前固定容差一致",
                        local_security.actor(), datetime.now().isoformat(timespec="seconds")))
        columns = {row[1] for row in db.execute("PRAGMA table_info(findings)")}
        if "source_key" not in columns:
            db.executescript("""
            ALTER TABLE findings RENAME TO findings_legacy;
            CREATE TABLE findings (
              id INTEGER PRIMARY KEY, outage TEXT NOT NULL, unit_id INTEGER NOT NULL,
              thimble_id INTEGER NOT NULL, position TEXT, entry_no INTEGER, volts REAL,
              degrees REAL, indication TEXT, percent REAL, channel TEXT, location TEXT,
              datapoint INTEGER, liss_region_size INTEGER, analyst TEXT, analysis TEXT,
              filepath TEXT, filename TEXT, calgroup TEXT, report_path TEXT,
              site_code TEXT DEFAULT '', site_owner TEXT DEFAULT '', component TEXT DEFAULT '',
              tester TEXT DEFAULT '', probe TEXT DEFAULT '', column_no INTEGER, channel_id TEXT DEFAULT '',
              measurement_type TEXT DEFAULT '', uid TEXT DEFAULT '', distance TEXT DEFAULT '', extent TEXT DEFAULT '',
              length TEXT DEFAULT '', width TEXT DEFAULT '', comment TEXT DEFAULT '', source_key TEXT,
              business_key TEXT, source_indication TEXT DEFAULT '', indication_resolution TEXT DEFAULT 'source',
              imported_at TEXT NOT NULL
            );
            INSERT INTO findings (
              id,outage,unit_id,thimble_id,position,entry_no,volts,degrees,indication,percent,
              channel,location,datapoint,liss_region_size,analyst,analysis,filepath,filename,
              calgroup,report_path,imported_at
            ) SELECT id,outage,unit_id,thimble_id,position,entry_no,volts,degrees,indication,percent,
              channel,location,datapoint,liss_region_size,analyst,analysis,filepath,filename,
              calgroup,report_path,imported_at FROM findings_legacy;
            DROP TABLE findings_legacy;
            """)
        columns = {row[1] for row in db.execute("PRAGMA table_info(findings)")}
        if "business_key" not in columns:
            db.execute("ALTER TABLE findings ADD COLUMN business_key TEXT")
        columns = {row[1] for row in db.execute("PRAGMA table_info(findings)")}
        if "maintenance_text" not in columns:
            db.execute("ALTER TABLE findings ADD COLUMN maintenance_text TEXT DEFAULT ''")
        columns = {row[1] for row in db.execute("PRAGMA table_info(findings)")}
        if "source_indication" not in columns:
            db.execute("ALTER TABLE findings ADD COLUMN source_indication TEXT DEFAULT ''")
            db.execute("UPDATE findings SET source_indication=COALESCE(indication,'')")
        if "indication_resolution" not in columns:
            db.execute("ALTER TABLE findings ADD COLUMN indication_resolution TEXT DEFAULT 'source'")
            db.execute("""UPDATE findings SET indication_resolution='unreviewed'
                WHERE TRIM(COALESCE(indication,''))='' AND
                (TRIM(COALESCE(location,''))<>'' OR UPPER(TRIM(COALESCE(measurement_type,''))) NOT IN ('','NONE'))""")
        db.execute("DROP INDEX IF EXISTS idx_findings_business_key")
        db.execute(f"UPDATE findings SET site_code={analysis_reporting.site_prefix_sql()} WHERE TRIM(COALESCE(site_code,''))='' AND outage IS NOT NULL")
        db.execute("""CREATE TABLE IF NOT EXISTS core_mapping_corrections (
            id INTEGER PRIMARY KEY, finding_id INTEGER NOT NULL,
            before_json TEXT NOT NULL, after_json TEXT NOT NULL,
            reason TEXT NOT NULL, corrected_at TEXT NOT NULL)""")
        # Preserve source/audit snapshots; repair only the two known legacy mappings.
        legacy_rows = db.execute("""SELECT * FROM findings WHERE UPPER(TRIM(position))='M5'
            AND ((unit_id>0 AND unit_id%2=1 AND thimble_id=15)
              OR (unit_id>0 AND unit_id%2=0 AND thimble_id=42))""").fetchall()
        for legacy in legacy_rows:
            before = dict(legacy)
            after = {**before, "position": "N5"}
            after["business_key"] = finding_business_key(after)
            db.execute("INSERT INTO core_mapping_corrections(finding_id,before_json,after_json,reason,corrected_at) VALUES(?,?,?,?,?)",
                       (before["id"], json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False),
                        "2026-10-20 用户确认官方管板：奇数15/偶数42=N5，纠正旧软件M5映射", datetime.now().isoformat(timespec="seconds")))
            db.execute("UPDATE findings SET position=?,business_key=? WHERE id=?",
                       (after["position"], after["business_key"], before["id"]))
        rows = db.execute("SELECT * FROM findings WHERE business_key IS NULL OR business_key='' ORDER BY id").fetchall()
        for row in rows:
            db.execute("UPDATE findings SET business_key=? WHERE id=?", (finding_business_key(dict(row)), row["id"]))
        duplicates = db.execute("""SELECT business_key, MIN(id) kept_id, GROUP_CONCAT(id) ids
            FROM findings WHERE business_key IS NOT NULL AND business_key<>''
            GROUP BY business_key HAVING COUNT(*)>1""").fetchall()
        for duplicate in duplicates:
            for duplicate_id in (int(value_) for value_ in duplicate["ids"].split(",")):
                if duplicate_id == duplicate["kept_id"]: continue
                row = db.execute("SELECT * FROM findings WHERE id=?", (duplicate_id,)).fetchone()
                db.execute("""INSERT INTO duplicate_records(
                    detected_at,kept_finding_id,duplicate_source_key,business_key,reason,source_path,payload_json,action
                ) VALUES(?,?,?,?,?,?,?,?)""", (datetime.now().isoformat(timespec="seconds"), duplicate["kept_id"],
                    row["source_key"], duplicate["business_key"], "完全相同的检测记录", row["report_path"] or row["filepath"] or "",
                    json.dumps(dict(row), ensure_ascii=False, default=str), "removed"))
                db.execute("DELETE FROM findings WHERE id=?", (duplicate_id,))
        db.execute("DELETE FROM findings WHERE thimble_id NOT BETWEEN 1 AND 50")
        # Query paths are consistently scoped by outage, unit and tube; keep these
        # indexes local to SQLite so imports remain portable and fast.
        db.executescript("""
        CREATE INDEX IF NOT EXISTS idx_findings_scope ON findings(outage, unit_id, thimble_id);
        CREATE INDEX IF NOT EXISTS idx_findings_unit_tube ON findings(unit_id, thimble_id, outage);
        CREATE INDEX IF NOT EXISTS idx_findings_location ON findings(unit_id, thimble_id, location);
        DROP INDEX IF EXISTS idx_findings_source_key;
        CREATE UNIQUE INDEX idx_findings_source_key ON findings(source_key) WHERE source_key IS NOT NULL AND source_key<>'';
        CREATE UNIQUE INDEX IF NOT EXISTS idx_findings_business_key ON findings(business_key) WHERE business_key IS NOT NULL AND business_key<>'';
        CREATE INDEX IF NOT EXISTS idx_duplicate_records_detected ON duplicate_records(detected_at DESC);
        CREATE INDEX IF NOT EXISTS idx_indication_resolution_audit_finding ON indication_resolution_audit(finding_id,changed_at DESC);
        CREATE INDEX IF NOT EXISTS idx_findings_site_scope ON findings(site_code, unit_id, outage, thimble_id);
        CREATE INDEX IF NOT EXISTS idx_tube_states_scope ON tube_states(outage, unit_id, thimble_id);
        CREATE INDEX IF NOT EXISTS idx_validation_issues_batch ON validation_issues(batch_id, severity, resolved_at);
        CREATE INDEX IF NOT EXISTS idx_file_artifacts_hash ON file_artifacts(sha256);
        CREATE INDEX IF NOT EXISTS idx_report_versions_scope ON report_versions(outage, unit_id, selected);
        CREATE INDEX IF NOT EXISTS idx_tube_repairs_scope ON tube_repairs(unit_id, thimble_id, outage);
        """)
        # Backfill older Excel imports so the UI site filter and history scope
        # use the same stable key as newly parsed reports.
        db.execute(f"UPDATE findings SET site_code={analysis_reporting.site_prefix_sql()} WHERE TRIM(COALESCE(site_code,''))='' AND outage IS NOT NULL")
        # ========== 软删除 / 回收站 / 操作日志 扩展 ==========
        # 用 TRY/CATCH 方式安全地加字段（字段已存在会报错）
        def _add_column(tbl, col, definition):
            cols = {row[1] for row in db.execute(f"PRAGMA table_info({tbl})")}
            if col not in cols:
                db.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {definition}")

        _add_column("findings", "is_deleted", "INTEGER DEFAULT 0")
        _add_column("findings", "deleted_at", "TEXT")
        _add_column("findings", "deleted_by", "TEXT DEFAULT ''")
        _add_column("findings", "delete_batch_id", "TEXT")
        _add_column("findings", "import_batch_id", "INTEGER")
        _add_column("findings", "report_unit_raw", "TEXT DEFAULT ''")
        _add_column("import_batches", "selection_json", "TEXT DEFAULT '{}'")
        _add_column("file_artifacts", "parsed_json", "TEXT DEFAULT '{}'")

        _add_column("tube_states", "is_deleted", "INTEGER DEFAULT 0")
        _add_column("tube_states", "deleted_at", "TEXT")
        _add_column("tube_states", "delete_batch_id", "TEXT")
        _add_column("tube_states", "updated_at", "TEXT DEFAULT ''")
        _add_column("tube_states", "source", "TEXT DEFAULT ''")
        _add_column("tube_states", "offset_confirmed", "INTEGER NOT NULL DEFAULT 1")
        _add_column("tube_states", "unsigned_offset_mm", "REAL")
        _add_column("tube_states", "events_json", "TEXT")
        _add_column("tube_states", "replacement_stage", "TEXT NOT NULL DEFAULT 'unknown'")
        try:
            from . import inspection_states
        except ImportError:
            import inspection_states
        inspection_states.init_schema(db)

        _add_column("import_batches", "is_deleted", "INTEGER DEFAULT 0")
        _add_column("import_batches", "outage", "TEXT DEFAULT ''")
        _add_column("import_batches", "deleted_at", "TEXT")
        _add_column("import_batches", "delete_batch_id", "TEXT")

        _add_column("validation_issues", "is_deleted", "INTEGER DEFAULT 0")
        _add_column("validation_issues", "deleted_at", "TEXT")

        db.executescript("""
        CREATE TABLE IF NOT EXISTS import_batch_artifacts (
          batch_id INTEGER NOT NULL, artifact_id INTEGER NOT NULL,
          PRIMARY KEY(batch_id, artifact_id)
        );
        CREATE TABLE IF NOT EXISTS import_batch_reports (
          batch_id INTEGER NOT NULL, version_id INTEGER NOT NULL, selected INTEGER NOT NULL,
          PRIMARY KEY(batch_id, version_id)
        );
        CREATE TABLE IF NOT EXISTS import_finding_changes (
          batch_id INTEGER NOT NULL, finding_id INTEGER NOT NULL,
          before_json TEXT, after_json TEXT NOT NULL,
          PRIMARY KEY(batch_id, finding_id)
        );
        CREATE TABLE IF NOT EXISTS import_finding_sources (
          id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL, finding_id INTEGER,
          source_path TEXT NOT NULL, sheet_name TEXT DEFAULT '', row_number INTEGER,
          raw_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS import_excel_mappings (
          id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL, source_path TEXT NOT NULL,
          sheet_name TEXT NOT NULL, header_row INTEGER NOT NULL,
          mapping_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_import_excel_mappings_batch ON import_excel_mappings(batch_id);
        CREATE INDEX IF NOT EXISTS idx_findings_import_batch ON findings(import_batch_id);
        CREATE TABLE IF NOT EXISTS operation_logs (
          id INTEGER PRIMARY KEY, operation_type TEXT NOT NULL, scope TEXT NOT NULL,
          scope_detail TEXT, record_count INTEGER NOT NULL DEFAULT 0,
          operator TEXT NOT NULL DEFAULT 'local', created_at TEXT NOT NULL,
          delete_batch_id TEXT, backup_file TEXT, note TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS delete_batches (
          id TEXT PRIMARY KEY, scope TEXT NOT NULL, scope_label TEXT,
          detail_json TEXT DEFAULT '{}', record_count INTEGER NOT NULL DEFAULT 0,
          deleted_at TEXT NOT NULL, deleted_by TEXT NOT NULL DEFAULT 'local',
          restored_at TEXT, is_restored INTEGER NOT NULL DEFAULT 0, backup_file TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_findings_deleted ON findings(is_deleted);
        CREATE INDEX IF NOT EXISTS idx_findings_batch ON findings(delete_batch_id);
        CREATE INDEX IF NOT EXISTS idx_tube_states_deleted ON tube_states(is_deleted);
        CREATE INDEX IF NOT EXISTS idx_op_logs_time ON operation_logs(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_delete_batches_time ON delete_batches(deleted_at DESC);
        CREATE INDEX IF NOT EXISTS idx_findings_live_scope ON findings(is_deleted, outage, unit_id, thimble_id, entry_no, datapoint);
        CREATE INDEX IF NOT EXISTS idx_findings_live_site_scope ON findings(is_deleted, site_code, unit_id, outage, thimble_id);
        CREATE INDEX IF NOT EXISTS idx_findings_live_analyst ON findings(is_deleted, analyst, outage, unit_id, thimble_id);
        CREATE INDEX IF NOT EXISTS idx_tube_states_live_scope ON tube_states(is_deleted, outage, unit_id, thimble_id);
        CREATE INDEX IF NOT EXISTS idx_tube_states_live_tube ON tube_states(is_deleted, unit_id, thimble_id, outage);
        CREATE INDEX IF NOT EXISTS idx_tube_state_history_tube ON tube_state_history(unit_id, thimble_id, outage, id DESC);
        CREATE INDEX IF NOT EXISTS idx_validation_issues_live ON validation_issues(is_deleted, resolved_at, severity, id DESC);
        """)
        cross_group_review.install(db)


def init_db(path=None) -> None:
    target = Path(path or DB_PATH)
    schema_migrations.upgrade(target, _legacy_init_db)
    with data_source.SQLiteProvider(target).connect() as db:
        db.execute('PRAGMA journal_mode=WAL')
        local_security.seed(db)


def is_indication_record(finding: Finding) -> bool:
    # Explicit conclusions remain records even when their measurements are
    # empty. For a missing conclusion, only source evidence (not thimble
    # number) makes it a candidate indication.
    return bool(finding.indication.strip() or analysis_reporting.has_wear_information(finding))


def blank_indication_summary(findings: list[Finding], limit: int = 10000) -> dict:
    missing = [finding for finding in findings
               if str(finding.indication or "").strip().upper() in {"", "/"}]
    rows = [finding for finding in missing
            if analysis_reporting.blank_indication_class(finding) == "war_candidate"]
    ndd_rows = [finding for finding in missing
                if analysis_reporting.blank_indication_class(finding) == "ndd"]

    def sample(row):
        return {
        "outage": row.outage, "unit_id": row.unit_id, "thimble_id": row.thimble_id,
        "position": row.position, "volts": row.volts, "degrees": row.degrees,
        "percent": row.percent, "location": row.location,
        "channel": row.channel, "filename": row.filename, "calgroup": row.calgroup,
        "analyst": row.analyst, "source": row.report_path,
        }

    return {
        # count/items are intentionally only the actionable WAR candidates.
        # NDD rows are reported separately and never included in fill_war.
        "count": len(rows),
        "tubes": len({(row.outage, row.unit_id, row.thimble_id) for row in rows}),
        "sources": len({row.report_path for row in rows}),
        "items": [sample(row) for row in rows[:limit]],
        "ndd_count": len(ndd_rows),
        "ndd_items": [sample(row) for row in ndd_rows[:limit]],
        "missing_count": len(missing),
        "review_count": 0,
    }


def import_resolution_summary(findings: list[Finding], policy: str = "") -> dict:
    """Return one stable resolution vocabulary for RPT and Excel imports."""
    classes = Counter(
        analysis_reporting.blank_indication_class(finding)
        for finding in findings
        if str(finding.indication or "").strip().upper() in {"", "/"}
    )
    war_candidate = int(classes.get("war_candidate", 0))
    ndd_auto = int(classes.get("ndd", 0))
    return {
        "blank_total": war_candidate + ndd_auto,
        "war_candidate": war_candidate,
        "ndd_auto": ndd_auto,
        "review": war_candidate if policy == "review" else 0,
    }


def export_indication_warnings(items: list[dict]) -> dict:
    if not isinstance(items, list) or len(items) > 10000:
        raise ValueError("三字符缺失记录格式无效或数量过多")
    headers = ["序号", "大修", "机组", "通道编号", "堆芯位置", "三字符", "幅值(V)", "相位(°)",
               "磨损深度(%)", "磨损位置", "测量通道", "数据文件", "数据组", "分析人员", "RPT来源"]
    book = Workbook(); sheet = book.active; sheet.title = "三字符缺失记录"; sheet.append(headers)
    for index, row in enumerate(items, 1):
        if not isinstance(row, dict):
            continue
        sheet.append([index, row.get("outage", ""), row.get("unit_id", ""), row.get("thimble_id", ""),
                      row.get("position", ""), row.get("indication", "") or "未标注", row.get("volts"),
                      row.get("degrees"), row.get("percent"), row.get("location", ""), row.get("channel", ""),
                      row.get("filename", ""), row.get("calgroup", ""), row.get("analyst", ""), row.get("source", "")])
    apply_plain_excel_table(sheet)
    sheet.freeze_panes = "A2"; sheet.auto_filter.ref = sheet.dimensions
    for column in range(1, sheet.max_column + 1):
        values = [str(sheet.cell(row, column).value or "") for row in range(1, min(sheet.max_row, 300) + 1)]
        sheet.column_dimensions[get_column_letter(column)].width = min(55, max(10, max(map(len, values), default=0) + 2))
    scope = "-".join(sorted({str(row.get("outage") or "") for row in items if isinstance(row, dict)})) or "当前筛选"
    filename = artifact_naming.filename("三字符缺失清单", scope, "xlsx")
    result = workbook_result(filename, book)
    return record_file_export("indication_warnings", {**result, "rows": sheet.max_row - 1}, {
        "rows": sheet.max_row - 1,
        "outages": sorted({str(row.get("outage") or "") for row in items if isinstance(row, dict)} - {""}),
        "finding_ids": [row.get("id") for row in items if isinstance(row, dict) and row.get("id") is not None],
        "note": "三字符缺失记录清单；入库前必须人工确认，未批量填值",
    })


def indication_columns(finding: Finding, policy: str) -> dict:
    columns = asdict(finding)
    source = finding.indication.strip()
    columns["source_indication"] = source
    classification = analysis_reporting.blank_indication_class(finding)
    if classification == "war_candidate":
        columns["indication_resolution"] = "bulk_war" if policy == "fill_war" else "review"
        if policy == "fill_war":
            columns["indication"] = "WAR"
    elif classification == "ndd":
        # Keep source_indication for traceability, but persist a canonical
        # conclusion so all downstream views use the same NDD semantics.
        columns["indication"] = "NDD"
        columns["indication_resolution"] = "auto_ndd"
    else:
        columns["indication_resolution"] = "source"
    return columns


def audit_indication_resolution(db: sqlite3.Connection, finding_id: int, columns: dict) -> None:
    if columns.get("indication_resolution") != "bulk_war":
        return
    exists = db.execute("SELECT 1 FROM indication_resolution_audit WHERE finding_id=? AND action='bulk_war'", (finding_id,)).fetchone()
    if not exists:
        db.execute("""INSERT INTO indication_resolution_audit(
            finding_id,changed_at,source_indication,resolved_indication,action,source_path
        ) VALUES(?,?,?,?,?,?)""", (finding_id, datetime.now().isoformat(timespec="seconds"),
            columns.get("source_indication", ""), "WAR", "bulk_war",
            columns.get("report_path") or columns.get("filepath") or ""))


def display_indication(row) -> str:
    def get(name, default=None):
        try:
            return row[name]
        except (KeyError, IndexError, TypeError):
            return getattr(row, name, default)
    indication = str(get("indication", "") or "").strip()
    evidence = {key: get(key) for key in (
        "indication", "measurement_type", "datapoint", "location", "location_raw",
        "channel", "volts", "degrees", "percent",
    )}
    if analysis_reporting.no_defect_basis(evidence):
        return "NDD"
    return indication or "未标注"


def process_directory(directory: str, selected_reports: list[str] | None = None) -> dict:
    base = Path(directory).expanduser().resolve()
    groups = discover_data_groups(base)
    selected = None if selected_reports is None else {str(Path(path).resolve()).casefold() for path in selected_reports}
    contexts = [parse_sum(group) for group in task_progress.iterate(groups, "读取 SUM 数据组", unit="组", span=(0, 5))]
    group_files = {str(context.path): sorted(path for path in context.path.iterdir()
                  if path.is_file() and path.suffix.casefold() in {".ect", ".rpt"})
                  for context in contexts}
    file_total = sum(len(paths) for paths in group_files.values())
    file_done = 0
    result = {
        "contexts": contexts, "findings": [], "report_rows": [], "tube_summary": [],
        "unreported_ect": [], "calibration_ect": [], "duplicate_same_hash": [],
        "same_name_different_hash": [], "report_reference_errors": [], "ect_mismatches": [],
        "sum_warnings": [], "mapping_failures": [], "parse_errors": [], "ect": [], "reports": [],
    }
    ect_by_group: dict[tuple[str, str], list[dict]] = {}
    ect_by_name: dict[str, list[dict]] = {}
    physical_versions: dict[tuple, list[dict]] = {}
    report_fingerprints: set[tuple] = set()
    for context in contexts:
        if context.warning:
            result["sum_warnings"].append({"group": context.calgroup, "path": str(context.path), "sum": context.sum_path, "message": context.warning})
        paths = group_files[str(context.path)]
        ect_paths = [path for path in paths if path.suffix.casefold() == ".ect"]
        span = (5 + 70 * file_done / max(1, file_total), 5 + 70 * (file_done + len(ect_paths)) / max(1, file_total))
        for ect_path in task_progress.iterate(ect_paths, f"读取 ECT · {context.calgroup}", unit="文件", span=span):
            try:
                ect = parse_ect_header(ect_path)
                ect["context"] = context
                ect["logical_key"] = (context.site_code, context.unit_id, context.component.upper(), context.outage, context.calgroup.upper(), ect["filename"].upper())
                ect["header_matches_name"] = (ect["name_row"], ect["name_col"], ect["name_entry"]) == (ect["row"], ect["col"], ect["entry"])
                result["ect"].append(ect)
                ect_by_group.setdefault((str(context.path).casefold(), ect["filename"].upper()), []).append(ect)
                ect_by_name.setdefault(ect["filename"].upper(), []).append(ect)
                physical_versions.setdefault(ect["logical_key"], []).append(ect)
                if ect["calibration"]:
                    result["calibration_ect"].append(ect)
                if not ect["header_matches_name"]:
                    result["ect_mismatches"].append(ect)
            except Exception as exc:
                result["parse_errors"].append({"type": "ECT 解析", "file": str(ect_path), "message": str(exc)})
        file_done += len(ect_paths)
        reports = [path for path in paths if path.suffix.casefold() == ".rpt"]
        span = (5 + 70 * file_done / max(1, file_total), 5 + 70 * (file_done + len(reports)) / max(1, file_total))
        for report in task_progress.iterate(reports, f"读取 RPT · {context.calgroup}", unit="文件", span=span):
            if selected is not None and str(report.resolve()).casefold() not in selected:
                continue
            try:
                fingerprint = (context.site_code.upper(), context.unit_id, context.component.upper(), context.outage, context.calgroup.upper(), _cached_sha256(report))
            except OSError:
                fingerprint = (context.site_code.upper(), context.unit_id, context.component.upper(), context.outage, context.calgroup.upper(), str(report.resolve()).casefold())
            if fingerprint in report_fingerprints:
                continue
            report_fingerprints.add(fingerprint)
            result["reports"].append(report)
            try:
                rows = parse_report(report, context)
                result["report_rows"].extend(rows)
            except Exception as exc:
                result["parse_errors"].append({"type": "RPT 解析", "file": str(report), "message": str(exc)})
        file_done += len(reports)
    for logical_key, copies in physical_versions.items():
        hashes: dict[str, list[dict]] = {}
        for ect in copies:
            hashes.setdefault(ect["sha256"], []).append(ect)
        for same_hash in hashes.values():
            if len(same_hash) > 1:
                result["duplicate_same_hash"].extend(same_hash[1:])
        if len(hashes) > 1:
            result["same_name_different_hash"].extend(copies)
    referenced_paths: set[str] = set()
    for finding in task_progress.iterate(result["report_rows"], "核对报告与 ECT 关联", span=(75, 100)):
        group_key = (str(Path(finding.report_path).parent.resolve()).casefold(), finding.filename.upper())
        candidates = ect_by_group.get(group_key, [])
        error = ""
        if finding.report_unit_raw.strip() and (
                not finding.report_unit_raw.strip().isdigit()
                or int(finding.report_unit_raw.strip()) != finding.unit_id):
            error = "RPT Id 与 SUM Unit 不一致或无效，记录隔离待核查"
        elif finding.calgroup.upper() != Path(finding.report_path).parent.name.upper():
            error = "RPT Calgroup 与当前数据组不一致"
        elif not candidates:
            elsewhere = ect_by_name.get(finding.filename.upper(), [])
            error = "RPT 跨组引用 ECT" if elsewhere else "RPT 引用的 ECT 不存在"
        else:
            ect = candidates[0]
            referenced_paths.update(item["path"].casefold() for item in candidates)
            if ect["calibration"]:
                error = "RPT 引用了 DIR999 标定文件"
            elif not ect["header_matches_name"]:
                error = "ECT 文件名与 HeaderTube 不一致，记录隔离待核查"
            elif (finding.thimble_id, finding.column_no, finding.entry_no) != (ect["row"], ect["col"], ect["entry"]):
                error = "RPT Row/Column/Entry 与 ECT 不一致"
        if error:
            result["report_reference_errors"].append({"report": finding.report_path, "calgroup": finding.calgroup, "filename": finding.filename, "uid": finding.uid, "message": error, "raw_record": asdict(finding)})
            continue
        if not 1 <= finding.thimble_id <= 50:
            result["report_reference_errors"].append({"report": finding.report_path, "calgroup": finding.calgroup, "filename": finding.filename, "uid": finding.uid, "message": "RPT Row 超出 1-50"})
            continue
        if not finding.unit_id:
            result["mapping_failures"].append({"group": finding.calgroup, "filename": finding.filename, "row": finding.thimble_id, "message": "SUM Unit 缺失，堆芯位置留空"})
        elif not finding.position:
            result["mapping_failures"].append({"group": finding.calgroup, "filename": finding.filename, "row": finding.thimble_id, "message": "堆芯坐标映射失败"})
        result["findings"].append(finding)
    result["unreported_ect"] = [ect for ect in result["ect"] if not ect["calibration"] and ect["path"].casefold() not in referenced_paths]
    tube_rows: dict[tuple, dict] = {}
    for ect in result["ect"]:
        context = ect["context"]
        if ect["calibration"] or not ect["header_matches_name"] or not 1 <= (ect["row"] or 0) <= 50:
            continue
        key = (context.site_code, context.unit_id, context.outage, ect["row"])
        row = tube_rows.setdefault(key, {"site_code": context.site_code, "unit_id": context.unit_id, "outage": context.outage, "thimble_id": ect["row"], "position": position_for(context.unit_id, ect["row"]) if context.unit_id else "", "entries": set(), "files": set(), "indications": [], "position_groups": set()})
        row["entries"].add(ect["entry"]); row["files"].add(ect["filename"])
    for finding in result["findings"]:
        key = (finding.site_code, finding.unit_id, finding.outage, finding.thimble_id)
        row = tube_rows.setdefault(key, {"site_code": finding.site_code, "unit_id": finding.unit_id, "outage": finding.outage, "thimble_id": finding.thimble_id, "position": finding.position, "entries": set(), "files": set(), "indications": [], "position_groups": set()})
        if finding.entry_no is not None: row["entries"].add(finding.entry_no)
        row["files"].add(finding.filename)
        if is_indication_record(finding):
            row["indications"].append(finding)
            row["position_groups"].add((finding.calgroup.upper(), finding.filename.upper(), finding.location, finding.channel))
    for row in tube_rows.values():
        indications = row.pop("indications")
        row["entry_count"] = len(row.pop("entries")); row["file_count"] = len(row.pop("files"))
        row["raw_indication_count"] = len(indications); row["position_group_count"] = len(row.pop("position_groups"))
        percentages = [finding.percent for finding in indications if finding.percent is not None]
        row["max_percent"] = max(percentages) if percentages else None
    result["tube_summary"] = sorted(tube_rows.values(), key=lambda row: (row["site_code"], row["unit_id"], row["outage"], row["thimble_id"]))
    return result


def report_options(directory: str) -> list[dict]:
    base = Path(directory).expanduser().resolve()
    if not base.is_dir():
        raise ValueError("所选路径不是有效文件夹")
    options = []
    fingerprints: dict[tuple[str, str, str], dict] = {}
    reports = [(parse_sum(group), report) for group in discover_data_groups(base) for report in group.iterdir() if report.is_file() and report.suffix.casefold() == ".rpt"]
    for context, report in task_progress.iterate(sorted(reports, key=lambda item: str(item[1]).casefold()),
                                               "扫描 RPT 候选版本", unit="文件"):
        try:
            rows = parse_report(report, context)
            option = {
                "path": str(report),
                "name": report.name,
                "modified_ns": report.stat().st_mtime_ns,
                "modified_at": datetime.fromtimestamp(report.stat().st_mtime).isoformat(timespec="seconds"),
                "group": report.parent.name,
                "outage": context.outage,
                "site_code": context.site_code,
                "unit_id": context.unit_id,
                "sum_warning": context.warning,
                "analysts": sorted({row.analyst for row in rows if row.analyst}),
                "records": len(rows),
                "tubes": sorted({row.thimble_id for row in rows}),
                "tube_count": len({row.thimble_id for row in rows}),
                "indication_count": sum(is_indication_record(row) for row in rows),
                "blank_indication": blank_indication_summary(rows),
                "duplicate_paths": [],
            }
            digest = _cached_sha256(report)
            option["sha256"] = digest
            option["sum_sha256"] = hashlib.sha256(Path(context.sum_path).read_bytes()).hexdigest() if context.sum_path else ""
            key = (context.site_code.upper(), context.unit_id, context.component.upper(), context.outage, option["group"].upper(), digest)
            existing = fingerprints.get(key)
            if existing:
                existing["duplicate_paths"].append(str(report))
            else:
                fingerprints[key] = option
                options.append(option)
        except Exception as exc:
            options.append({"path": str(report), "name": report.name, "group": report.parent.name, "error": str(exc), "analysts": [], "records": 0})
    return options


def unique_report_paths(reports) -> list[Path]:
    unique: dict[tuple, Path] = {}
    for report in sorted(reports):
        context = parse_sum(report.parent)
        try:
            key = (context.site_code.upper(), context.unit_id, context.component.upper(), context.outage, report.parent.name.upper(), _cached_sha256(report))
        except OSError:
            key = (context.site_code.upper(), context.unit_id, context.component.upper(), context.outage, report.parent.name.upper(), str(report.resolve()).casefold())
        unique.setdefault(key, report)
    return list(unique.values())


def validate_report_confirmation(directory, selected_reports, confirmation):
    """Bind manual choices to the complete candidate set seen by the operator."""
    if not isinstance(confirmation, dict) or confirmation.get("confirmed") is not True:
        raise ValueError("请扫描并逐组人工确认 Report 后继续")
    options = [row for row in report_options(directory) if not row.get("error")]
    def path_key(path):
        return str(Path(path).resolve()).casefold()
    expected = {path_key(row["path"]): (row["sha256"], row["sum_sha256"]) for row in options}
    seen = confirmation.get("candidates")
    if not isinstance(seen, list) or not all(isinstance(row, dict) and row.get("path") for row in seen):
        raise ValueError("报告确认信息缺失，请重新扫描")
    actual = {path_key(row["path"]): (row.get("sha256"), row.get("sum_sha256")) for row in seen}
    if actual != expected or len(seen) != len(expected):
        raise ValueError("报告候选或 SUM 内容已变化，请重新扫描并人工确认")
    groups = {}
    for row in options:
        key = (row["site_code"], row["unit_id"], row["outage"], row["group"])
        groups.setdefault(key, set()).add(path_key(row["path"]))
    chosen = [path_key(path) for path in (selected_reports or [])]
    if (not groups or len(chosen) != len(set(chosen)) or any(path not in expected for path in chosen)
            or any(len(paths.intersection(chosen)) != 1 for paths in groups.values())):
        raise ValueError("必须逐组人工确认唯一 Report，不能遗漏数据组")
    return {"confirmed": True, "confirmed_at": datetime.now().isoformat(timespec="seconds"),
            "candidates": options, "selected_paths": list(selected_reports)}


@import_audit.tracked("directory")
def import_directory(directory: str, selected_reports: list[str] | None = None, blank_indication_policy: str = "", operator: str = "", _audit=None, report_confirmation=None) -> dict:
    with task_progress.phase(0, 8):
        confirmed = validate_report_confirmation(directory, selected_reports, report_confirmation) if report_confirmation is not None else None
    if selected_reports is None:
        reports = unique_report_paths(path for group in discover_data_groups(directory)
                                      for path in group.iterdir() if path.is_file() and path.suffix.casefold() == ".rpt")
        groups = set()
        for report in reports:
            context = parse_sum(report.parent)
            key = (context.site_code.upper(), context.unit_id, context.component.upper(),
                   context.outage, context.calgroup.upper())
            if key in groups:
                raise ValueError("同一数据组存在多个报告版本，请逐组人工确认 Report 后继续")
            groups.add(key)
        selected_reports = [str(report) for report in reports]
    else:
        with task_progress.phase(8, 15):
            available = report_options(directory)
        available_paths = {str(Path(row["path"]).resolve()).casefold(): row for row in available if not row.get("error")}
        selected_keys = set()
        for path in selected_reports:
            option = available_paths.get(str(Path(path).resolve()).casefold())
            if option is None:
                raise ValueError("所选报告不属于当前有效数据组，请重新扫描并选择")
            key = (option.get("site_code"), option.get("unit_id"), option.get("outage"), option.get("group"))
            if key in selected_keys:
                raise ValueError("同一数据组只能人工选择一个报告版本")
            selected_keys.add(key)
    with task_progress.phase(15, 60):
        processed = process_directory(directory, selected_reports)
    reports = processed["reports"]
    parsed = inserted = skipped = 0
    errors = list(processed["parse_errors"]) + list(processed["report_reference_errors"])
    blank_indication = blank_indication_summary(processed["findings"])
    resolution = import_resolution_summary(processed["findings"], blank_indication_policy)
    audit_db, batch_id = _audit
    if confirmed:
        audit_db.execute("UPDATE import_batches SET selection_json=? WHERE id=?",
                         (json.dumps(confirmed, ensure_ascii=False), batch_id))
    with task_progress.phase(60, 70):
        import_audit.directory_quality(audit_db, batch_id, processed, selected_reports)
    for finding in processed["findings"]:
        if is_indication_record(finding) and not finding.indication.strip():
            import_audit.issue(audit_db, batch_id, "BLANK_INDICATION", "检测记录缺少三字符，保留原值并需人工核查",
                finding.report_path, "warning", field="indication", payload=asdict(finding))
    if blank_indication["count"] and blank_indication_policy not in {"review", "fill_war"}:
        task_progress.wait_for_confirmation()
        return {"requires_indication_decision": True, "blank_indication": blank_indication,
                "reports": len(reports), "parsed": len(processed["findings"]), "source_total": len(processed["report_rows"]),
                "parsed_total": len(processed["findings"]), "inserted": 0, "updated": 0, "skipped": 0,
                "ndd_auto": resolution["ndd_auto"], "war_candidate": resolution["war_candidate"],
                "review": resolution["war_candidate"], "errors": errors}
    state_entries = []
    with nullcontext(audit_db) as db:
        for finding in task_progress.iterate(processed["findings"], "写入检测记录", span=(70, 94)):
            parsed += 1
            raw_columns = asdict(finding)
            if (not re.fullmatch(r"[A-Z]{1,2}\d{3}", finding.outage) or not finding.unit_id
                    or analysis_reporting.sequence(finding.outage)[1] != finding.unit_id):
                import_audit.issue(db, batch_id, "UNIT_OUTAGE_MISMATCH",
                    "SUM 大修或机组信息缺失/不一致，该记录隔离未入库", finding.report_path, payload=raw_columns)
                continue
            columns = indication_columns(finding, blank_indication_policy)
            columns["business_key"] = finding_business_key(raw_columns)
            columns["imported_at"] = datetime.now().isoformat(timespec="seconds")
            columns["import_batch_id"] = batch_id
            keys = list(columns)
            sql = f"INSERT OR IGNORE INTO findings ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})"
            cur = db.execute(sql, [columns[key] for key in keys])
            inserted += cur.rowcount
            skipped += 1 - cur.rowcount
            if not cur.rowcount:
                audit_duplicate(db, columns)
                import_audit.issue(db, batch_id, "DUPLICATE_IMPORT", "完全相同的检测记录已拦截",
                    finding.report_path, "warning", payload=raw_columns)
            finding_row = db.execute("""SELECT id,indication_resolution FROM findings
                WHERE (source_key=? OR business_key=?) AND is_deleted=0 ORDER BY id LIMIT 1""",
                (columns["source_key"], columns["business_key"])).fetchone()
            before = dict(db.execute("SELECT * FROM findings WHERE id=?", (finding_row["id"],)).fetchone()) if finding_row and not cur.rowcount else None
            if finding_row and columns["indication_resolution"] == "bulk_war":
                db.execute("UPDATE findings SET indication='WAR',source_indication=?,indication_resolution='bulk_war' WHERE id=?",
                           (columns.get("source_indication", ""), finding_row["id"]))
                audit_indication_resolution(db, finding_row["id"], columns)
            elif finding_row and columns["indication_resolution"] == "auto_ndd":
                db.execute("UPDATE findings SET indication='NDD',source_indication=?,indication_resolution='auto_ndd' WHERE id=?",
                           (columns.get("source_indication", ""), finding_row["id"]))
            if finding_row:
                import_audit.remember_change(db, batch_id, finding_row["id"], before)
            import_audit.finding_source(db, batch_id, finding_row["id"] if finding_row else None,
                finding.report_path, raw_columns)
            if finding_row:
                for field_name in ("analysis", "comment"):
                    if getattr(finding, field_name, ""):
                        state_entries.append(dict(outage=finding.outage, unit_id=finding.unit_id,
                            thimble_id=finding.thimble_id, note=getattr(finding, field_name),
                            source=f"{finding.report_path} · {finding.calgroup} · {finding.filename} · {field_name} · 记录{finding_row['id']}"))
        with task_progress.phase(94, 99):
            state_summary = inspection_states.recognize_import(sys.modules[__name__], db, batch_id, state_entries)
    return {"reports": len(reports), "parsed": parsed, "source_total": len(processed["report_rows"]),
            "parsed_total": len(processed["findings"]), "inserted": inserted, "updated": 0,
            "skipped": skipped, "ndd_auto": resolution["ndd_auto"],
            "war_candidate": resolution["war_candidate"],
            "review": resolution["war_candidate"] if blank_indication_policy == "review" else 0,
            "error_total": len(errors), "errors": errors,
            "state_recognition": state_summary,
            "blank_indication": blank_indication,
            "raw_report_rows": len(processed["report_rows"]), "tubes": len(processed["tube_summary"]),
            "calibration_ect": len(processed["calibration_ect"]), "unreported_ect": len(processed["unreported_ect"])}


EXCEL_SUFFIXES = {".xls", ".xlsx", ".xlsm"}
EXCEL_ALIAS_SOURCES = {
    "电站名称": ["电站名称", "基地", "基地名称"], "机组号": ["机组号", "机组", "unitid"],
    "通道编号": ["通道编号", "通道号", "通道", "指套管编号", "incorefluxthimbleid", "套管编号"],
    "在堆芯内的位置": ["在堆芯内的位置", "堆芯位置", "position"], "幅值": ["幅值", "幅值v", "volts"],
    "相位": ["相位", "相位°", "degrees"], "磨损深度": ["磨损深度", "磨损深度%", "percent"],
    "三字码": ["三字码", "三字符", "缺陷类型", "indication"],
    "测量通道": ["测量通道", "记录通道", "测量通道记录通道", "channel"],
    "磨损位置": ["磨损位置", "location"], "分析人员": ["分析人员", "analyst"],
    "数据": ["数据", "数据文件", "filename"], "数据组": ["数据组", "calgroup"],
    "RPT来源": ["RPT来源", "原始RPT", "原始RPT来源", "reportpath", "rptsource"],
    "备注": ["备注", "analysis"], "堵管移位信息": ["堵管移位信息", "割管移位信息", "维护状态", "处理状态", "管状态", "状态"],
    "大修号": ["大修号", "大修", "outage"], "数据流水号": ["数据流水号", "entry", "entryno"],
    "数据点": ["数据点", "datapoint"], "liss区域大小": ["liss区域大小", "lissregionsize"],
    "记录编号": ["记录编号", "findingid", "recordid", "id"],
    "探头类型": ["探头类型", "探头型号", "probe", "probe type"],
    "原始注释": ["原始注释", "comment"],
    "测量类型": ["测量类型", "measurementtype"],
    "有符号位移mm": ["有符号位移mm", "有符号位移", "有符号轴向位移", "signed offset mm", "signed_offset_mm"],
    "方向未确认距离mm": ["方向未确认距离mm", "未确认方向的距离", "未注明方向的距离", "unsigned offset mm", "unsigned_offset_mm"],
    "位移量": ["位移量", "位移量mm", "移位量", "移位量mm", "位移距离", "轴向位移", "offset", "offset_mm"],
    "移位方向": ["移位方向", "位移方向", "轴向方向", "方向", "方向（正负）", "shift direction", "direction"],
}
# English templates vary in case, separators and wording. Keep aliases attached
# to field names so adding or reordering fields cannot silently change detection.
EXCEL_SEMANTIC_ALIASES = {
    "电站名称": ["site", "station", "plant", "base"],
    "机组号": ["unit", "unit no", "unit number", "unitid"],
    "通道编号": ["channel no", "channel number", "thimble", "thimble id"],
    "在堆芯内的位置": ["position", "core position", "core location"],
    "幅值": ["voltage", "amplitude"],
    "相位": ["phase", "angle"],
    "磨损深度": ["wear depth", "wear percent"],
    "三字码": ["defect", "three character code"],
    "测量通道": ["measurement channel", "test channel"],
    "磨损位置": ["wear location", "defect location"],
    "分析人员": ["analyst name", "reviewer"],
    "数据": ["data file", "filename"],
    "数据组": ["data group", "group"],
    "备注": ["notes", "remark", "remarks"],
    "大修号": ["outage", "overhaul", "overhaul no", "maintenance"],
    "数据流水号": ["entry", "entry no", "entry number"],
    "数据点": ["datapoint", "data point"],
    "liss区域大小": ["liss region size", "liss size"],
}


def excel_field_aliases() -> dict[str, set[str]]:
    """Normalized alias table shared by auto-detection and the mapping wizard."""
    aliases = {key: list(values) for key, values in EXCEL_ALIAS_SOURCES.items()}
    for field, names in EXCEL_SEMANTIC_ALIASES.items():
        aliases[field].extend(names)
    return {key: {normalize_header(item) for item in values} for key, values in aliases.items()}


def open_excel_workbook(source: Path):
    """Open .xls (stdlib reader) or .xlsx/.xlsm (openpyxl) with one call site."""
    suffix = source.suffix.lower()
    if suffix == ".xls":
        try:
            from .xls_reader import load_workbook
        except ImportError:
            from xls_reader import load_workbook
        return load_workbook(source, read_only=True, data_only=True)
    if suffix in {".xlsx", ".xlsm"}:
        from openpyxl import load_workbook
        try:
            return load_workbook(source, read_only=True, data_only=True)
        except PermissionError as error:
            raise ValueError("Excel 文件无法访问，请检查文件权限或关闭占用文件的程序") from error
        except (BadZipFile, KeyError, ET.ParseError) as error:
            raise ValueError("无法读取 Excel：文件损坏或实际格式与扩展名不符，请检查文件或重新导出") from error
    raise ValueError("请选择 .xls、.xlsx 或 .xlsm 文件")


def read_excel_rows(sheet, header_row):
    total = max(0, sheet.max_row - header_row) if sheet.max_row is not None else None
    return list(task_progress.iterate(sheet.iter_rows(min_row=header_row + 1, values_only=True),
                                     f"读取工作表 · {sheet.title}", total))

RPT_WORKBOOK_PROPERTY = "ThimbleRPTMetadataV2"
RPT_WORKBOOK_FIELDS = ("thimble_id", "position", "volts", "degrees", "percent", "indication", "channel",
                       "location", "probe", "analyst", "filename", "calgroup", "analysis", "maintenance_text")


def rpt_row_hash(values):
    normalized = [int(value) if isinstance(value, float) and value.is_integer() else value for value in values]
    return hashlib.sha256(json.dumps(normalized, ensure_ascii=False, separators=(",", ":"),
                                     default=str).encode("utf-8")).hexdigest()


def rpt_workbook_metadata(book):
    try:
        prop = book.custom_doc_props[RPT_WORKBOOK_PROPERTY]
        metadata = json.loads(zlib.decompress(base64.b64decode(prop.value)).decode("utf-8"))
        return metadata if isinstance(metadata, dict) else {}
    except (AttributeError, KeyError, ValueError, TypeError, zlib.error):
        return {}


def sheet_header_values(sheet, row_number: int) -> list:
    """Header row values for either workbook backend."""
    if row_number < 1:
        return []
    max_row = getattr(sheet, "max_row", None)
    if max_row is not None and max_row < row_number:
        return []
    if hasattr(sheet, "row_values"):
        try:
            return sheet.row_values(row_number)
        except (IndexError, TypeError):
            return []
    try:
        return [cell.value for cell in sheet[row_number]]
    except (IndexError, KeyError, TypeError):
        return []


REQUIRED_IMPORT_FIELDS = ("机组号", "通道编号")
MEASUREMENT_IMPORT_FIELDS = ("幅值", "三字码")


def detect_sheet_mapping(sheet, aliases: dict[str, set[str]]):
    """Find the header row and column mapping for one worksheet.

    Returns (header_row, {field: 0-based column or None}) or None when the
    sheet is not a findings detail sheet. 汇总表/异常清单类工作表（如导出的
    “管子汇总表”“三字符缺失”“跨组相同缺陷”）同样带有“机组号/通道编号”表头，
    但没有幅值或三字码等测量列，必须排除，否则会被当作缺陷明细重复入库。
    """
    # A few generated workbooks omit the worksheet dimension metadata. Keep
    # header detection usable instead of failing on ``min(None, 12)``.
    max_rows = sheet.max_row or 12
    for header_row in range(1, min(max_rows, 12) + 1):
        headers = [normalize_header(value_) for value_ in sheet_header_values(sheet, header_row)]
        mapping = {key: next((index for index, header in enumerate(headers) if header in names), None)
                   for key, names in aliases.items()}
        has_sheet_scope = bool(re.fullmatch(r"[A-Z]{1,2}\d{3}", sheet.title.strip().upper()))
        has_scope = mapping.get("机组号") is not None or has_sheet_scope
        if has_scope and mapping.get("通道编号") is not None and \
                any(mapping.get(field) is not None for field in MEASUREMENT_IMPORT_FIELDS):
            return header_row, mapping
    # Unrecognized or damaged headers must use the reviewable mapping wizard;
    # inferring fields from fixed column numbers can silently corrupt imports.
    return None


def inspect_excel_file(filename: str) -> dict:
    """Report every worksheet, its detected header row and column mapping.

    Used by the import wizard so operators can review and adjust the mapping
    before anything is written to the database.
    """
    source = Path(filename).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() not in EXCEL_SUFFIXES:
        raise ValueError("请选择 .xls、.xlsx 或 .xlsm 文件")
    book = open_excel_workbook(source)
    aliases = excel_field_aliases()
    sheets = []
    try:
        for sheet in task_progress.iterate(book.worksheets, "检查工作表表头", unit="表"):
            detected = detect_sheet_mapping(sheet, aliases)
            header_row = detected[0] if detected else 1
            mapping = detected[1] if detected else {key: None for key in aliases}
            headers = sheet_header_values(sheet, header_row)
            columns = [{"column": index + 1, "header": "" if value is None else str(value)}
                       for index, value in enumerate(headers)]
            max_row, max_column = sheet.max_row, sheet.max_column
            if max_row is None or max_column is None:
                try:
                    from openpyxl.utils.cell import range_boundaries
                    _, _, max_column, max_row = range_boundaries(sheet.calculate_dimension(force=True))
                except Exception:
                    max_row = max_row or 0
                    max_column = max_column or len(headers)
            outage_hint = sheet.title.strip().upper() if re.fullmatch(r"[A-Z]{1,2}\d{3}", sheet.title.strip().upper()) else ""
            sheets.append({"name": sheet.title, "max_row": max_row,
                           "max_column": max_column, "header_row": header_row,
                           "outage_hint": outage_hint,
                           "unit_hint": infer_unit(outage_hint, "") if outage_hint else None,
                           "recognized": bool(detected), "mapping": mapping, "columns": columns})
    finally:
        book.close()
    return {"file": str(source), "sheets": sheets}


def _normalize_mapping_override(mapping: dict, book) -> tuple[str, int, dict[str, int | None]]:
    """Validate a user-supplied {sheet, header_row, columns} mapping (1-based)."""
    if not isinstance(mapping, dict):
        raise ValueError("字段映射格式无效")
    sheet_name = str(mapping.get("sheet") or "")
    if sheet_name not in book.sheetnames:
        raise ValueError(f"字段映射指定的工作表不存在：{sheet_name or '（未指定）'}")
    sheet = book[sheet_name]
    header_row = number(mapping.get("header_row"), int) or 0
    if not 1 <= header_row <= max(sheet.max_row or 1, 1):
        raise ValueError("字段映射指定的表头行无效")
    columns = mapping.get("columns") or {}
    if not isinstance(columns, dict):
        raise ValueError("字段映射的列对应关系无效")
    normalized: dict[str, int | None] = {}
    for key in EXCEL_ALIAS_SOURCES:
        value = number(columns.get(key), int)
        normalized[key] = value - 1 if value and value > 0 else None
    has_sheet_scope = bool(re.fullmatch(r"[A-Z]{1,2}\d{3}", sheet_name.strip().upper()))
    if (normalized["机组号"] is None and not has_sheet_scope) or normalized["通道编号"] is None:
        raise ValueError("字段映射必须指定“通道编号”；没有机组列时，工作表名必须是有效的大修号")
    if all(normalized.get(field) is None for field in MEASUREMENT_IMPORT_FIELDS):
        raise ValueError("字段映射必须至少指定“幅值”或“三字码”列，汇总表/异常清单不能作为缺陷明细导入")
    if any(column is not None and column >= sheet.max_column for column in normalized.values()):
        raise ValueError("字段映射指定了超出表格范围的列")
    return sheet_name, header_row, normalized


@import_audit.tracked("excel")
def import_excel_file(filename: str, blank_indication_policy: str = "", operator: str = "",
                      _audit=None, mapping: dict | None = None) -> dict:
    if not blank_indication_policy:
        with task_progress.phase(0, 35):
            check = import_excel_file(filename, "check", operator, mapping=mapping)
        if check["blank_indication"]["count"]:
            task_progress.wait_for_confirmation()
            check["requires_indication_decision"] = True
            return check
        with task_progress.phase(35, 99):
            return import_excel_file(filename, "review", operator, mapping=mapping)
    if blank_indication_policy not in {"check", "review", "fill_war"}:
        raise ValueError("三字符处理方式无效，请重新确认")
    dry_run = blank_indication_policy == "check"
    source = Path(filename).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() not in EXCEL_SUFFIXES:
        raise ValueError("请选择 .xls、.xlsx 或 .xlsm 文件")
    book = open_excel_workbook(source)
    rpt_metadata = rpt_workbook_metadata(book)
    rpt_source_workbook = (bool(rpt_metadata) or ("RPT导入说明" in book.sheetnames
                           and book["RPT导入说明"].cell(1, 1).value == "THIMBLE_RPT_CONVERTED_V1"))
    aliases = excel_field_aliases()
    selection_evidence = []
    sheet_results: list[dict] = []
    inserted = updated = skipped = parsed = 0
    invalid_rows: list[int] = []
    invalid_count = 0
    pending: list[dict] = []
    state_entries = []
    state_summary = dict(applied=0, pending=0, skipped=0)
    state_rows: list[tuple] = []

    try:
        if mapping:
            # Operator-adjusted mapping: import exactly the requested sheet.
            sheet_name, header_row, column_map = _normalize_mapping_override(mapping, book)
            with task_progress.phase(0, 25):
                targets = [(book[sheet_name], header_row, column_map,
                            read_excel_rows(book[sheet_name], header_row))]
        else:
            # Auto-detection: import every worksheet with a recognizable header,
            # not only the first one, so multi-sheet workbooks import completely.
            targets = []
            for sheet in task_progress.iterate(book.worksheets, "识别检测工作表", unit="表",
                                              span=(0, 25), partitions=True):
                detected = detect_sheet_mapping(sheet, aliases)
                if detected:
                    targets.append((sheet, detected[0], detected[1],
                                    read_excel_rows(sheet, detected[0])))
            if not targets:
                raise ValueError("无法识别Excel表头：需要通道编号、幅值或三字符，以及机组列或大修号工作表名")
        # Optional maintenance snapshot sheet. It is intentionally separate
        # from finding-detail sheets, but belongs to the same import batch.
        for sheet in task_progress.iterate(book.worksheets, "读取维护工作表", unit="表",
                                          span=(25, 35), partitions=True):
            first_row = list(sheet.iter_rows(min_row=1, max_row=1, values_only=True))
            column_count = sheet.max_column or (len(first_row[0]) if first_row else 0)
            if column_count < 8:
                continue
            for header_row in range(1, min(sheet.max_row or 12, 12) + 1):
                headers = [str(value or "") for value in sheet_header_values(sheet, header_row)]
                named_events = "状态代码" in headers and "方向已确认" in headers
                sample = list(sheet.iter_rows(min_row=header_row + 1, max_row=header_row + 1,
                                              values_only=True))
                if not sample:
                    continue
                values = sample[0]
                outage = str(values[3] or "").strip().upper() if len(values) > 3 else ""
                unit = number(values[4], int) if len(values) > 4 else None
                thimble = number(values[5], int) if len(values) > 5 else None
                state = str(values[7] or "").strip().lower() if len(values) > 7 else ""
                if (re.fullmatch(r"[A-Z]{1,2}\d{3}", outage) and unit and 1 <= unit <= 6
                        and thimble and 1 <= thimble <= 50
                        and state in {"normal", "plugged", "replaced", "shifted"}):
                    for row_number, row_values in enumerate(
                            read_excel_rows(sheet, header_row), header_row + 1):
                        payload = {
                            "outage": str(row_values[3] or "").strip().upper(),
                            "unit_id": number(row_values[4], int),
                            "thimble_id": number(row_values[5], int),
                            "state": str(row_values[7] or "").strip().lower(),
                            "offset_mm": number(row_values[8], float) if len(row_values) > 8 else None,
                            "note": str(row_values[11] or "") if len(row_values) > 11 else "",
                            "source": f"{source} · {sheet.title} 第{row_number}行",
                        }
                        if named_events:
                            event_values = dict(zip(headers, row_values))
                            # Validate and normalize legacy unsigned-distance
                            # cells at the write boundary, without hiding invalid values.
                            payload["offset_mm"] = event_values.get("有符号位移mm")
                            payload["unsigned_offset_mm"] = event_values.get("方向未确认距离mm")
                            payload["direction"] = next(
                                (event_values.get(key) for key in ("移位方向", "位移方向", "方向")
                                 if event_values.get(key) not in (None, "")),
                                None,
                            )
                            payload["note"] = str(event_values.get("备注原文") or "")
                            payload["source"] = str(event_values.get("维护来源") or "")
                        state_rows.append((sheet.title, row_number, payload))
                    break

        original_headers = {sheet.title: sheet_header_values(sheet, header_row)
                            for sheet, header_row, _, _ in targets}
        if rpt_metadata:
            selection_evidence = rpt_metadata.get("confirmation", [])
        elif "报告版本确认" in book.sheetnames:
            confirmation_sheet = book["报告版本确认"]
            expected_headers = ["确认时间", "确认人员", "报告路径", "RPT SHA-256", "SUM SHA-256", "选用"]
            if [cell.value for cell in confirmation_sheet[1]] == expected_headers:
                selection_evidence = [dict(zip(expected_headers, row))
                                      for row in confirmation_sheet.iter_rows(min_row=2, values_only=True)]
        ledger_token = ""
        if "_ledger_metadata" in book.sheetnames:
            ledger_token = str(book["_ledger_metadata"].cell(2, 2).value or "")
    finally:
        book.close()

    def cell(values, key, column_map):
        index = column_map.get(key)
        return values[index] if index is not None and index < len(values) else None

    audit_db, batch_id = _audit if _audit else (None, None)
    with (nullcontext(audit_db) if audit_db else connect()) as db:
        current_token = db.execute("SELECT token FROM ledger_identity WHERE id=1").fetchone()[0]
        allow_record_updates = bool(ledger_token and ledger_token == current_token)
        if not dry_run:
            if selection_evidence:
                db.execute("UPDATE import_batches SET selection_json=? WHERE id=?", (
                    json.dumps({"origin": "imported_workbook", "source": str(source),
                                "candidates": selection_evidence}, ensure_ascii=False, default=str), batch_id))
            import_audit.artifact(db, batch_id, source)
        row_total = sum(len(target[3]) for target in targets)
        row_done = 0
        duplicate_cache: dict[tuple, list[dict]] = {}
        for sheet, header_row, column_map, rows in targets:
            sheet_inserted = sheet_updated = sheet_skipped = sheet_parsed = 0
            sheet_invalid: list[int] = []
            if not dry_run:
                db.execute("""INSERT INTO import_excel_mappings(batch_id,source_path,sheet_name,header_row,mapping_json,created_at)
                    VALUES(?,?,?,?,?,?)""", (
                        batch_id, str(source), sheet.title, header_row,
                        json.dumps({key: (None if column is None else column + 1) for key, column in column_map.items()},
                                   ensure_ascii=False), datetime.now().isoformat(timespec="seconds")))
            span = (35 + 57 * row_done / max(1, row_total), 35 + 57 * (row_done + len(rows)) / max(1, row_total))
            for row_number, values in enumerate(task_progress.iterate(
                    rows, f"{'校验' if dry_run else '写入'}检测记录 · {sheet.title}", span=span), header_row + 1):
                row = {key: cell(values, key, column_map) for key in column_map}
                metadata_row = rpt_metadata.get("rows", {}).get(sheet.title, {}).get(str(row_number), {})
                original = {}
                if len(values) == 14 and metadata_row.get("finding"):
                    identity_fields = ("thimble_id", "position", "filename", "calgroup")
                    identity_matches = all(
                        metadata_row.get("field_hashes", {}).get(field) == rpt_row_hash([
                            None if values[index] == "/" else values[index]])
                        for field, index in ((field, RPT_WORKBOOK_FIELDS.index(field)) for field in identity_fields))
                    if identity_matches:
                        original = {key: value for key, value in metadata_row["finding"].items()
                                    if key not in RPT_WORKBOOK_FIELDS}
                    for field, index in zip(RPT_WORKBOOK_FIELDS, range(14)):
                        visible_value = values[index]
                        if visible_value == "/":
                            visible_value = None
                        if metadata_row.get("field_hashes", {}).get(field) == rpt_row_hash([visible_value if visible_value is not None else "/"]):
                            original[field] = metadata_row["finding"].get(field)
                if rpt_metadata:
                    row = {key: (None if value == "/" else value) for key, value in row.items()}
                outage_hint = sheet.title.strip().upper() if re.fullmatch(r"[A-Z]{1,2}\d{3}", sheet.title.strip().upper()) else ""
                outage = outage_from_standard_row(row, source, outage_hint)
                unit_id = number(row["机组号"], int) or (infer_unit(outage, "") if outage else None)
                thimble_id = number(row["通道编号"], int)
                if not outage or not unit_id or not thimble_id or not 1 <= thimble_id <= 50:
                    if any(value_ not in (None, "") for value_ in values):
                        sheet_invalid.append(row_number)
                        if not dry_run:
                            import_audit.issue(db, batch_id, "INVALID_SCOPE", "大修、机组或管号缺失/越界，该行未入库",
                                source, sheet=sheet.title, row=row_number, payload=row)
                    continue
                if analysis_reporting.sequence(outage)[1] != unit_id:
                    sheet_invalid.append(row_number)
                    if not dry_run:
                        import_audit.issue(db, batch_id, "UNIT_OUTAGE_MISMATCH", "机组号与大修号不一致，该行未入库",
                            source, sheet=sheet.title, row=row_number, field="机组号", payload=row)
                    continue
                sheet_parsed += 1
                expected_position = position_for(unit_id, thimble_id)
                normalized_position = re.sub(r"([A-Z])0+(\d)", r"\1\2", str(row["在堆芯内的位置"] or expected_position).strip().upper())
                finding = Finding(
                    outage=outage, unit_id=unit_id, thimble_id=thimble_id,
                    position=expected_position if normalized_position == "M5" and expected_position == "N5" else str(row["在堆芯内的位置"] or expected_position),
                    entry_no=number(row["数据流水号"], int), volts=number(row["幅值"], float), degrees=number(row["相位"], float),
                    indication=str(row["三字码"] or ""), percent=number(row["磨损深度"], float), channel=str(row["测量通道"] or ""),
                    location=str(row["磨损位置"] or ""), datapoint=number(row["数据点"], int), liss_region_size=number(row["liss区域大小"], int),
                    analyst=str(row["分析人员"] or ""), analysis=str(row["备注"] or ""), filepath="",
                    filename=str(row["数据"] or source.name), calgroup=str(row["数据组"] or ""),
                    report_path=str(row["RPT来源"] or source),
                    maintenance_text=str(row["堵管移位信息"] or ""),
                    probe=str(row["探头类型"] or ""),
                    comment=str(row["原始注释"] or ""),
                    measurement_type=str(row["测量类型"] or ""),
                    site_code=outage_code(outage), site_owner=str(row["电站名称"] or "")
                )
                if original:
                    for key in Finding.__dataclass_fields__:
                        if key in original:
                            setattr(finding, key, original[key])
                finding.source_key = finding_business_key(finding)
                pending.append(finding)
                if dry_run:
                    continue
                if normalized_position != expected_position:
                    import_audit.issue(db, batch_id, "MAPPING_ERROR", "表格堆芯坐标与奇偶机组映射不一致，原值保留供核查",
                        source, sheet=sheet.title, row=row_number, field="在堆芯内的位置", payload=row)
                    if normalized_position == "M5" and expected_position == "N5":
                        finding.position = expected_position
                else:
                    finding.position = normalized_position
                finding.source_key = finding_business_key(finding)
                if is_indication_record(finding) and not finding.indication.strip():
                    import_audit.issue(db, batch_id, "BLANK_INDICATION", "检测记录缺少三字符，保留原值并需人工核查",
                        source, "warning", sheet.title, row_number, "三字码", row)
                raw_columns = asdict(finding)
                columns = indication_columns(finding, blank_indication_policy)
                columns["business_key"] = finding_business_key(raw_columns)
                columns["imported_at"] = datetime.now().isoformat(timespec="seconds")
                columns["import_batch_id"] = batch_id
                record_id = number(row.get("记录编号"), int) if allow_record_updates else None
                if record_id:
                    existing = db.execute("SELECT * FROM findings WHERE id=? AND is_deleted=0", (record_id,)).fetchone()
                    if existing:
                        current = dict(existing)
                        if (current["outage"], current["unit_id"], current["thimble_id"]) != (outage, unit_id, thimble_id):
                            sheet_invalid.append(row_number)
                            import_audit.issue(db, batch_id, "RECORD_ID_SCOPE_MISMATCH",
                                "记录编号对应的基地/机组/大修/通道与工作表不一致，该行未更新",
                                source, sheet=sheet.title, row=row_number, field="记录编号", payload=row)
                            continue
                        source_fields = {
                            "在堆芯内的位置": "position", "数据流水号": "entry_no", "幅值": "volts",
                            "相位": "degrees", "三字码": "indication", "磨损深度": "percent",
                            "测量通道": "channel", "磨损位置": "location", "数据点": "datapoint",
                            "liss区域大小": "liss_region_size", "分析人员": "analyst", "备注": "analysis",
                            "数据": "filename", "数据组": "calgroup", "RPT来源": "report_path",
                            "堵管移位信息": "maintenance_text",
                            "探头类型": "probe",
                            "原始注释": "comment", "测量类型": "measurement_type",
                        }
                        updates = {target: getattr(finding, target) for label, target in source_fields.items()
                                   if column_map.get(label) is not None}
                        if "indication" in updates:
                            if columns["indication_resolution"] == "bulk_war":
                                updates.update(indication="WAR", source_indication=finding.indication,
                                               indication_resolution="bulk_war")
                            elif columns["indication_resolution"] == "auto_ndd":
                                updates.update(indication="NDD", source_indication=finding.indication,
                                               indication_resolution="auto_ndd")
                            elif columns["indication_resolution"] == "review":
                                updates.update(source_indication=finding.indication,
                                               indication_resolution="review")
                            elif updates["indication"] != current.get("source_indication"):
                                updates.update(source_indication=finding.indication,
                                               indication_resolution="source")
                        changed = any(current.get(key) != value for key, value in updates.items())
                        if changed:
                            updates["business_key"] = finding_business_key({**current, **updates})
                            db.execute("UPDATE findings SET " + ",".join(f"{key}=?" for key in updates) + " WHERE id=?",
                                       [*updates.values(), record_id])
                            import_audit.remember_change(db, batch_id, record_id, current, fields=updates)
                            sheet_updated += 1
                        else:
                            sheet_skipped += 1
                        import_audit.finding_source(db, batch_id, record_id, source, row, sheet.title, row_number)
                        if not rpt_source_workbook and row.get("备注") not in (None, ""):
                            state_entries.append(dict(outage=outage, unit_id=unit_id, thimble_id=thimble_id,
                                note=str(row["备注"]), offset_mm=row.get("有符号位移mm"),
                                unsigned_offset_mm=(row.get("方向未确认距离mm")
                                                    if row.get("方向未确认距离mm") not in (None, "")
                                                    else row.get("位移量")),
                                direction=row.get("移位方向"),
                                source=f"{source} · {sheet.title} 第{row_number}行 · 备注"))
                        if not rpt_source_workbook and row.get("堵管移位信息") not in (None, ""):
                            state_entries.append(dict(outage=outage, unit_id=unit_id, thimble_id=thimble_id,
                                note=str(row["堵管移位信息"]), offset_mm=row.get("有符号位移mm"),
                                unsigned_offset_mm=(row.get("方向未确认距离mm")
                                                    if row.get("方向未确认距离mm") not in (None, "")
                                                    else row.get("位移量")),
                                direction=row.get("移位方向"),
                                source=f"{source} · {sheet.title} 第{row_number}行 · 堵管移位信息"))
                        continue
                keys = list(columns)
                sql = f"INSERT OR IGNORE INTO findings ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})"
                cur = db.execute(sql, [columns[key] for key in keys])
                sheet_inserted += cur.rowcount
                sheet_skipped += 1 - cur.rowcount
                if not cur.rowcount:
                    audit_duplicate(db, columns)
                    import_audit.issue(db, batch_id, "DUPLICATE_IMPORT", "完全相同的检测记录已拦截",
                        source, "warning", sheet.title, row_number, payload=row)
                # Newly inserted rows already have their canonical identifier.
                # Avoid a second indexed lookup (and a full-row read) for every
                # record; the lookup is only needed when INSERT OR IGNORE hit a
                # duplicate and we must attach audit/state information to the
                # existing row.
                finding_row = None
                before = None
                if cur.rowcount:
                    finding_id = cur.lastrowid
                else:
                    finding_row = db.execute("""SELECT id,indication_resolution FROM findings
                        WHERE (source_key=? OR business_key=?) AND is_deleted=0 ORDER BY id LIMIT 1""",
                        (columns["source_key"], columns["business_key"])).fetchone()
                    finding_id = finding_row["id"] if finding_row else None
                    if finding_id:
                        before = dict(db.execute("SELECT * FROM findings WHERE id=?", (finding_id,)).fetchone())
                if finding_id and columns["indication_resolution"] == "bulk_war":
                    db.execute("UPDATE findings SET indication='WAR',source_indication=?,indication_resolution='bulk_war' WHERE id=?",
                               (columns.get("source_indication", ""), finding_id))
                    audit_indication_resolution(db, finding_id, columns)
                elif finding_id and columns["indication_resolution"] == "auto_ndd":
                    db.execute("UPDATE findings SET indication='NDD',source_indication=?,indication_resolution='auto_ndd' WHERE id=?",
                               (columns.get("source_indication", ""), finding_id))
                after = None
                if finding_id:
                    after = import_audit.remember_change(db, batch_id, finding_id, before)
                import_audit.finding_source(db, batch_id, finding_id,
                    source, row, sheet.title, row_number,
                    finding_values=after or before or {**raw_columns, "id": finding_id},
                    duplicate_cache=duplicate_cache)
                if finding_id:
                    for field_name in ("备注", "堵管移位信息"):
                        if rpt_source_workbook:
                            continue
                        if row.get(field_name) not in (None, ""):
                            original_field = original_headers[sheet.title][column_map[field_name]]
                            state_entries.append(dict(outage=outage, unit_id=unit_id, thimble_id=thimble_id,
                                note=str(row[field_name]), offset_mm=row.get("有符号位移mm"),
                                unsigned_offset_mm=(row.get("方向未确认距离mm")
                                                    if row.get("方向未确认距离mm") not in (None, "")
                                                    else row.get("位移量")),
                                direction=row.get("移位方向"),
                                source=f"{source} · {sheet.title} 第{row_number}行 · {original_field}"))
            row_done += len(rows)
            sheet_results.append({"sheet": sheet.title, "header_row": header_row, "parsed": sheet_parsed,
                                  "inserted": sheet_inserted, "skipped": sheet_skipped,
                                  "updated": sheet_updated,
                                  "invalid_rows": sheet_invalid[:100]})
            parsed += sheet_parsed
            inserted += sheet_inserted
            updated += sheet_updated
            skipped += sheet_skipped
            invalid_rows.extend(sheet_invalid[:100])
            invalid_count += len(sheet_invalid)
        if not dry_run:
            event_keys = {(payload["outage"], payload["unit_id"], payload["thimble_id"])
                          for _, _, payload in state_rows}
            state_entries = [entry for entry in state_entries
                             if (entry["outage"], entry["unit_id"], entry["thimble_id"]) not in event_keys]
            with task_progress.phase(92, 96):
                state_summary = inspection_states.recognize_import(sys.modules[__name__], db, batch_id, state_entries)
            if state_rows:
                try:
                    from .state_transfer import validate_rows as validate_state_rows
                except ImportError:
                    from state_transfer import validate_rows as validate_state_rows
            for sheet_name, row_number, payload in task_progress.iterate(state_rows, "写入管状态", span=(96, 99)):
                try:
                    payload = validate_state_rows(sys.modules[__name__], [payload])[0]
                    before = inspection_states.snapshot(db, payload)
                    if before and not before["is_deleted"] and all(
                        (before.get(key) if key != "offset_mm" or before.get("offset_confirmed", 1) else None)
                        == payload.get(key) for key in ("state", "offset_mm", "unsigned_offset_mm", "note", "source")
                    ):
                        state_summary["skipped"] += 1
                        continue
                    save_tube_state(payload, connection=db)
                    inspection_states.remember_state_change(db, batch_id, payload, before)
                    state_summary["applied"] += 1
                except (ValueError, TypeError) as error:
                    state_summary["skipped"] += 1
                    import_audit.issue(db, batch_id, "INVALID_MAINTENANCE_EVENT", str(error),
                                       source, sheet=sheet_name, row=row_number, payload=payload)
    first = sheet_results[0]
    blank_summary = blank_indication_summary(pending)
    resolution = import_resolution_summary(pending, blank_indication_policy)
    return {"file": str(source), "sheet": first["sheet"], "header_row": first["header_row"], "parsed": parsed,
            "inserted": inserted, "updated": updated, "skipped": skipped, "invalid_rows": invalid_rows[:100], "invalid_count": invalid_count,
            "sheets": sheet_results,
            "state_recognition": state_summary,
            "blank_indication": blank_summary,
            "source_total": row_total, "parsed_total": parsed,
            "ndd_auto": resolution["ndd_auto"], "war_candidate": resolution["war_candidate"],
            "review": resolution["review"], "error_total": invalid_count}


def analyze_directory(directory: str, selected_reports: list[str] | None = None) -> tuple[list[Finding], list[dict]]:
    processed = process_directory(directory, selected_reports)
    return processed["findings"], processed["parse_errors"] + processed["report_reference_errors"]


def automatic_report_selection(directory: str, policy: str) -> list[str] | None:
    # `latest` was the legacy API value; the desktop UI now exposes
    # `auto_latest` as the explicit automatic-selection strategy.
    if policy not in {"auto_latest", "latest"}:
        return None
    base = Path(directory).expanduser().resolve()
    reports = unique_report_paths(path for group in discover_data_groups(base) for path in group.iterdir() if path.is_file() and path.suffix.casefold() == ".rpt")
    groups: dict[str, list[Path]] = {}
    for report in reports:
        context = parse_sum(report.parent)
        key = f"{context.site_code.upper()}|{context.unit_id}|{context.component.upper()}|{context.outage}|{context.calgroup.upper()}"
        groups.setdefault(key, []).append(report)
    def latest(paths: list[Path]) -> Path:
        return max(paths, key=lambda path: (
            path.stat().st_mtime_ns,
            path.name.casefold(),
            str(path).casefold(),
        ))
    return [str(latest(group)) for group in groups.values()]


def analyze_data_groups(directory: str) -> list[dict]:
    groups = []
    for group_dir in discover_data_groups(directory):
        context = parse_sum(group_dir)
        try:
            root = ET.parse(context.sum_path).getroot() if context.sum_path else ET.Element("Summary")
            operator_node = root.find("Operator"); operator_node = operator_node if operator_node is not None else root
            probe_node = root.find("Probe"); probe_node = probe_node if probe_node is not None else root
            valid_ect = [parse_ect_header(path) for path in group_dir.iterdir() if path.is_file() and path.suffix.casefold() == ".ect"]
            valid_ect = [row for row in valid_ect if not row["calibration"]]
            timestamps = []
            for ect in valid_ect:
                if ect["datetime"]: timestamps.append(ect["datetime"])
            groups.append({
                "site_code": context.site_code, "outage": context.outage, "unit_id": context.unit_id,
                "data_group": group_dir.name,
                "operator": value(operator_node, "Id"),
                "probe_type": value(probe_node, "Type"),
                "probe_sn": value(probe_node, "Sn"),
                "probe_model": value(probe_node, "Model"),
                "tube_number": len({row["row"] for row in valid_ect}),
                "entry_number": len(valid_ect),
                "start_time": min(timestamps) if timestamps else "",
                "end_time": max(timestamps) if timestamps else "",
                "report_versions": len([path for path in group_dir.iterdir() if path.is_file() and path.suffix.casefold() == ".rpt"]),
                "warning": context.warning,
            })
        except Exception:
            continue
    return groups


def discover_server_sources(directory: str, max_directories: int = 12000) -> dict:
    base = Path(directory).expanduser()
    if not base.is_dir():
        raise ValueError("服务器根路径不可访问，请检查网络连接和访问权限")
    queue = [(base, 0)]
    visited = 0
    outages: dict[str, dict] = {}
    while queue and visited < max_directories:
        current, depth = queue.pop(0)
        visited += 1
        try:
            children = [path for path in current.iterdir() if path.is_dir()]
        except (OSError, PermissionError):
            continue
        outage_match = re.search(r"(?<![A-Z0-9])([A-Z]{1,2}\d{3})(?![A-Z0-9])", current.name.upper())
        if outage_match:
            outage = outage_match.group(1)
            local_queue = [(current, 0)]
            thimble_dirs = []
            while local_queue:
                candidate, local_depth = local_queue.pop(0)
                if local_depth > 4:
                    continue
                try:
                    nested = [path for path in candidate.iterdir() if path.is_dir()]
                except (OSError, PermissionError):
                    continue
                for path in nested:
                    try:
                        has_groups = "指套管" in path.name and any(child.is_dir() and child.name.upper().startswith("TH") for child in path.iterdir())
                    except (OSError, PermissionError):
                        has_groups = False
                    if has_groups:
                        thimble_dirs.append(path)
                    elif local_depth < 4:
                        local_queue.append((path, local_depth + 1))
            if thimble_dirs:
                selected = min(thimble_dirs, key=lambda path: len(path.parts))
                station, site_code = infer_station(current, outage)
                unit_folder = current.parent.name
                project_folder = next((part for part in reversed(current.parts[:-1]) if "项目" in part or "市场" in part), current.parent.parent.name if len(current.parents) > 1 else "")
                outages[str(selected).lower()] = {
                    "outage": outage,
                    "unit_id": infer_unit(outage, ""),
                    "site": site_code,
                    "station": station,
                    "path": str(selected),
                    "project": project_folder,
                    "unit_folder": unit_folder,
                    "folder": current.name,
                }
            continue
        if depth < 5:
            queue.extend((path, depth + 1) for path in children)
    items = sorted(outages.values(), key=lambda item: (item["station"], item["unit_id"], item["outage"]), reverse=True)
    return {"root": str(base), "items": items, "scanned_directories": visited, "truncated": bool(queue)}


def export_directory_excel(directory: str, selected_reports: list[str] | None = None, report_policy: str = "manual", report_confirmation=None) -> dict:
    require_import_space(EXCEL_DIR / "import.xlsx")
    with task_progress.phase(0, 10):
        confirmed = validate_report_confirmation(directory, selected_reports, report_confirmation) if report_confirmation is not None else None
    if report_policy == "all":
        raise ValueError("同一数据组不能同时使用多份 RPT，请逐组人工确认唯一报告")
    if selected_reports is None and report_policy in {"auto_latest", "latest"}:
        selected_reports = automatic_report_selection(directory, report_policy)
    with task_progress.phase(10, 70):
        processed = process_directory(directory, selected_reports)
    findings = processed["findings"]
    if not processed["contexts"]:
        raise ValueError("所选目录中没有找到符合 TH数字I数字CAL数字 规则的数据组")
    source_name = Path(directory).resolve().name or "指套管检测数据"
    safe_name = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", source_name)
    filename = artifact_naming.filename("RPT检测数据", safe_name, "xlsx")
    book = Workbook()
    book.remove(book.active)
    headers = ["通道编号", "堆芯位置", "幅值（V）", "相位", "磨损深度", "三字符",
               "测量通道（记录通道）", "磨损位置", "探头类型", "分析人员",
               "数据", "数据组", "备注", "堵管移位信息"]
    fields = RPT_WORKBOOK_FIELDS
    if not findings:
        raise ValueError("已选报告未解析出检测记录，无法生成工作簿；请检查原始数据和报告。")
    invalid = [f for f in findings if not re.fullmatch(r"[A-Z]{1,2}\d{3}", str(f.outage or "").strip().upper())]
    if invalid:
        raise ValueError(f"有 {len(invalid)} 条检测记录无法识别大修号，不能按大修生成工作表；请检查 SUM 和目录信息。")
    grouped = defaultdict(list)
    for finding in findings:
        grouped[finding.outage.strip().upper()].append(finding)
    metadata = {"version": 2, "confirmation": [], "rows": {}}
    widths = [12, 14, 14, 10, 14, 11, 22, 17, 18, 15, 29, 21, 19, 22]
    line = Side(style="thin", color="000000")
    border = Border(left=line, right=line, top=line, bottom=line)
    for outage in sorted(grouped):
        sheet = book.create_sheet(outage)
        sheet.append(headers)
        metadata["rows"][outage] = {}
        for finding in task_progress.iterate(sorted(grouped[outage], key=lambda item: item.thimble_id or 0),
                                             f"生成 Excel · {outage}", span=(70, 90)):
            values = [getattr(finding, field) for field in fields]
            values = ["/" if value is None or value == "" else value for value in values]
            sheet.append(values)
            metadata["rows"][outage][str(sheet.max_row)] = {
                "finding": asdict(finding),
                "field_hashes": {field: rpt_row_hash([value]) for field, value in zip(fields, values)},
            }
        for index, width in enumerate(widths, 1):
            sheet.column_dimensions[get_column_letter(index)].width = width
        for row_cells in sheet.iter_rows():
            for cell in row_cells:
                cell.border = border
                cell.alignment = Alignment(horizontal="center", vertical="center")
                if isinstance(cell.value, str):
                    cell.data_type = "s"
        sheet.row_dimensions[1].height = 22
        sheet.freeze_panes = "A2"
    blank_indication = blank_indication_summary(findings, 10000)
    cross_duplicates = analysis_reporting.cross_group_duplicates([asdict(finding) for finding in findings])
    if confirmed:
        selected_paths = {str(Path(path).resolve()).casefold() for path in (selected_reports or [])}
        for candidate in confirmed["candidates"]:
            metadata["confirmation"].append(dict(zip(
                ["确认时间", "确认人员", "报告路径", "RPT SHA-256", "SUM SHA-256", "选用"],
                [confirmed["confirmed_at"], local_security.actor(), candidate["path"], candidate["sha256"],
                 candidate["sum_sha256"], str(Path(candidate["path"]).resolve()).casefold() in selected_paths])))
    payload = base64.b64encode(zlib.compress(json.dumps(metadata, ensure_ascii=False, default=str).encode("utf-8"))).decode("ascii")
    book.custom_doc_props.append(StringProperty(name=RPT_WORKBOOK_PROPERTY, value=payload))
    outcome = workbook_result(filename, book)
    result = {**outcome, "rows": len(findings), "raw_report_rows": len(processed["report_rows"]),
            "blank_indication": blank_indication,
            "groups": len(processed["contexts"]), "tubes": len(processed["tube_summary"]),
            "cross_group_duplicate_groups": len(cross_duplicates),
            "errors": processed["parse_errors"] + processed["report_reference_errors"],
            "unreported_ect": len(processed["unreported_ect"]), "calibration_ect": len(processed["calibration_ect"])}
    outages = sorted({finding.outage for finding in findings if finding.outage})
    return record_file_export("standard_workbook", result, {
        "source_directory": str(Path(directory).resolve()), "rows": len(findings),
        "groups": len(processed["contexts"]), "outages": outages,
        "blank_indication_count": blank_indication.get("count", 0),
        "cross_group_duplicate_groups": len(cross_duplicates),
        "report_confirmation": {
            "confirmed_at": confirmed.get("confirmed_at") if confirmed else None,
            "selected_reports": selected_reports or [],
        } if confirmed else None,
        "warnings": [{"file": row.get("file"), "reason": row.get("message")}
                     for row in processed["parse_errors"] + processed["report_reference_errors"]],
    })


def query_states() -> dict:
    """Return editable tube-state rows with a best-effort site/position context."""
    with connect() as db:
        rows = db.execute("""
            SELECT s.outage, s.unit_id, s.thimble_id, s.state, s.events_json, s.replacement_stage,
                   CASE WHEN s.offset_confirmed=1 THEN s.offset_mm END AS offset_mm,
                   s.unsigned_offset_mm, s.note, s.source,
                   COALESCE(MAX(f.site_code), '') AS site_code,
                   COALESCE(MAX(f.position), '') AS position,
                   COALESCE(s.updated_at, '') AS updated_at
             FROM tube_states s
            LEFT JOIN findings f ON f.outage=s.outage AND f.unit_id=s.unit_id AND f.thimble_id=s.thimble_id WHERE s.is_deleted=0
            GROUP BY s.outage, s.unit_id, s.thimble_id, s.state, s.offset_mm, s.offset_confirmed, s.unsigned_offset_mm, s.note, s.source
            ORDER BY s.outage DESC, s.unit_id, s.thimble_id
        """).fetchall()
        try:
            from . import inspection_states
        except ImportError:
            import inspection_states
        pending = inspection_states.pending_rows(db)
        scopes = [dict(row) for row in db.execute(
            "SELECT outage,unit_id FROM tube_state_scopes ORDER BY outage,unit_id")]
    for scope in scopes:
        scope["site"] = re.match(r"^[A-Z]+", scope["outage"])[0]
    result = {"items": [tube_lifecycle.public(dict(row)) for row in rows], "pending": pending}
    # Keep the legacy empty response shape for callers that compare the
    # original payload literally; once a manually registered range exists,
    # expose it for the state workspace to populate its selectors.
    if scopes:
        result["scopes"] = scopes
    return result


def save_tube_state_scope(data: dict) -> dict:
    outage, unit, *_ = validate_state_payload({
        "outage": data.get("outage"), "unit_id": data.get("unit_id"),
        "thimble_id": 1, "state": "normal", "offset_mm": 0,
    })
    site, _, _ = tube_lifecycle.scope_key(outage)
    supplied_site = str(data.get("site") or "").strip().upper()
    if supplied_site and tube_lifecycle.ALIASES.get(supplied_site, supplied_site) != site:
        raise ValueError("大修编号中的基地与所选基地不一致")
    with connect() as db:
        cursor = db.execute(
            "INSERT OR IGNORE INTO tube_state_scopes(outage,unit_id,created_at) VALUES(?,?,?)",
            (outage, unit, datetime.now().isoformat(timespec="seconds")))
    return {"ok": True, "created": cursor.rowcount == 1,
            "scope": {"outage": outage, "unit_id": unit, "site": re.match(r"^[A-Z]+", outage)[0]}}


def consolidate_ndd_rows(rows) -> list[dict]:
    """Show one no-defect conclusion per tube while preserving every raw acquisition in SQLite."""
    items, ndd_by_tube = [], {}
    for source in rows:
        row = dict(source)
        if display_indication(row) != "NDD":
            row["source_count"] = 1
            items.append(row)
            continue
        key = (row.get("site_code"), row.get("outage"), row.get("unit_id"), row.get("thimble_id"), row.get("analyst"))
        existing = ndd_by_tube.get(key)
        if existing:
            existing["source_count"] += 1
            existing["source_files"].append(row.get("filename") or "")
            existing["source_groups"].append(row.get("calgroup") or "")
            continue
        row["source_count"] = 1
        row["source_files"] = [row.get("filename") or ""]
        row["source_groups"] = [row.get("calgroup") or ""]
        ndd_by_tube[key] = row
        items.append(row)
    return items


FINDING_COLUMN_FILTERS = {
    "outage", "unit_id", "thimble_id", "position", "indication", "volts", "degrees",
    "percent", "location", "channel", "probe", "analyst", "filename", "calgroup",
    "analysis", "maintenance_text",
}


def query_findings(params: dict[str, list[str]], *, all_rows=False) -> dict:
    page = max(1, number(params.get("page", ["1"])[0], int) or 1)
    size = min(500, max(1, number(params.get("size", ["100"])[0], int) or 100))
    where, args = [], []
    where.append("f.is_deleted = 0")
    for query_key, column in (("site", "f.site_code"), ("outage", "f.outage"), ("unit", "f.unit_id"), ("analyst", "f.analyst"), ("channel", "f.channel"), ("thimble", "f.thimble_id"), ("calgroup", "f.calgroup")):
        val = params.get(query_key, [""])[0].strip()
        if val:
            if query_key == "site":
                where.append(f"({analysis_reporting.site_prefix_sql('f.outage')}=? OR f.site_code=? OR f.site_owner=?)")
                args.extend((val.upper(), val, val))
            else:
                where.append(f"{column} = ?" if query_key in {"unit", "thimble"} else f"CAST({column} AS TEXT) LIKE ?")
                args.append(val if query_key in {"unit", "thimble"} else f"%{val}%")
    for field in sorted(FINDING_COLUMN_FILTERS):
        val = params.get(f"column_{field}", [""])[0].strip()
        if val:
            where.append(f"INSTR(LOWER(CAST(COALESCE(f.{field}, '') AS TEXT)), LOWER(?)) > 0")
            args.append(val)
    clause = " WHERE " + " AND ".join(where) if where else ""
    with connect() as db:
        sql = """SELECT f.*, COALESCE(s.state,'normal') state,
                 CASE WHEN s.thimble_id IS NULL THEN 0 ELSE 1 END AS state_recorded,
                 CASE WHEN s.offset_confirmed=0 THEN NULL ELSE COALESCE(s.offset_mm,0) END AS offset_mm,
                 s.unsigned_offset_mm,
                 s.offset_confirmed, COALESCE(s.source,'') state_source,
                 COALESCE(s.updated_at,'') state_updated_at,
                 COALESCE(s.note,'') note FROM statistical_findings f LEFT JOIN tube_states s ON s.outage=f.outage AND s.unit_id=f.unit_id AND s.thimble_id=f.thimble_id AND s.is_deleted=0
                 """
        if params.get("sources", [""])[0] == "1":
            sql = sql.replace("FROM statistical_findings f", "FROM findings f")
        rows = db.execute(sql + clause + " ORDER BY f.outage DESC,f.thimble_id,f.entry_no,f.id", args).fetchall()
        severity_clause = clause + (" AND " if clause else " WHERE ") + """
            UPPER(TRIM(COALESCE(f.indication,''))) NOT IN ('NDD', 'NONE', 'NO DEFECT')
            AND (TRIM(COALESCE(f.indication,''))<>'' OR TRIM(COALESCE(f.location,''))<>''
                 OR UPPER(TRIM(COALESCE(f.measurement_type,''))) NOT IN ('', 'NONE'))
            AND f.percent IS NOT NULL AND f.percent > 0"""
        core_rows = [] if params.get("core", [""])[0] == "0" else db.execute("""SELECT f.site_code, f.outage, f.unit_id, f.thimble_id, f.position,
                MAX(f.percent) AS percent
            FROM statistical_findings f""" + severity_clause + """
            GROUP BY f.site_code, f.outage, f.unit_id, f.thimble_id, f.position
            ORDER BY f.outage, f.unit_id, f.thimble_id""", args).fetchall()
    display_rows = [dict(row) for row in rows] if params.get("raw", [""])[0] == "1" else consolidate_ndd_rows(rows)
    total = len(display_rows)
    page_rows = display_rows if all_rows else display_rows[(page - 1) * size:page * size]
    items = []
    for item in page_rows:
        item["classification_basis"] = analysis_reporting.no_defect_basis(item)
        item["display_conclusion"] = "NDD" if item["classification_basis"] else item.get("indication") or ""
        # Legacy rows may have a SQL NULL location. Preserve that as an
        # explicit empty raw value so formatting and regex checks stay safe.
        item["location_raw"] = item.get("location") or ""
        item["p_zone"], item["p_offset"] = split_location(item["location_raw"])
        # Keep the confirmed Point alias visible in raw/detail views; the
        # normalized P bucket is carried separately in p_zone.
        item["location"] = item["location_raw"] if re.match(r"^\s*Point\b", item["location_raw"], re.I) else format_location(item["location_raw"])
        items.append(item)
    return {"items": items, "core_items": [dict(row) for row in core_rows], "total": total,
            "page": page, "size": size, "pages": max(1, (total + size - 1) // size)}


def query_all_findings(params: dict[str, list[str]]) -> list[dict]:
    """Read every matching row for exports without weakening the UI page limit."""
    return query_findings({**params, "raw": ["1"], "sources": ["1"]}, all_rows=True)["items"]


LEDGER_COLUMNS = [
    "基地", "大修号", "机组号", "通道编号", "堆芯位置", "幅值（V）", "相位",
    "磨损深度", "三字符", "测量通道（记录通道）", "磨损位置", "探头类型",
    "分析人员", "数据", "数据组", "备注", "堵管移位信息", "记录编号", "RPT来源",
    "数据流水号", "数据点", "liss区域大小",
    "原始注释", "测量类型",
]


def display_state(state: str, offset, unsigned_offset=None, confirmed=True) -> str:
    labels = {"normal": "正常", "plugged": "堵管", "shifted": "移位", "replaced": "换管"}
    label = labels.get(str(state or "").lower(), str(state or ""))
    if state == "shifted":
        value = offset if confirmed else unsigned_offset
        if value not in (None, ""):
            direction = "" if not confirmed else ("+" if float(value) > 0 else "")
            return f"移位 {direction}{float(value):g} mm" + ("（方向待确认）" if not confirmed else "")
    return label


def export_data_ledger(data: dict) -> dict:
    params = {key: [str(data.get(key) or "")] for key in ("site", "unit", "outage", "analyst", "channel", "thimble", "calgroup")}
    params.update({f"column_{field}": [str(data.get(f"column_{field}") or "")] for field in FINDING_COLUMN_FILTERS})
    rows = query_all_findings(params)
    book = Workbook()
    sheet = book.active
    sheet.title = "综合台账"
    sheet.append(LEDGER_COLUMNS)
    for row in task_progress.iterate(rows, "生成综合台账", span=(0, 75)):
        station = SITE_NAMES.get(str(row.get("site_code") or "").upper(), row.get("site_owner") or row.get("site_code") or "")
        maintenance = row.get("maintenance_text") or ""
        sheet.append([
            station or "/", row.get("outage") or "/", row.get("unit_id") or "/", row.get("thimble_id") or "/",
            row.get("position") or "/", row.get("volts") if row.get("volts") is not None else "/",
            row.get("degrees") if row.get("degrees") is not None else "/",
            row.get("percent") if row.get("percent") is not None else "/",
            row.get("source_indication") if row.get("source_indication") is not None else row.get("indication") or "",
            row.get("channel") or "", row.get("location_raw") or "", row.get("probe") or "",
            row.get("analyst") or "", row.get("filename") or "", row.get("calgroup") or "",
            row.get("analysis") or "",
            maintenance, row.get("id"), row.get("report_path") or "",
            row.get("entry_no"), row.get("datapoint"), row.get("liss_region_size"),
            row.get("comment") or "", row.get("measurement_type") or "",
        ])
    apply_plain_excel_table(sheet)
    states = query_states()["items"]
    if data.get("site"):
        states = [row for row in states if outage_code(row["outage"]) == str(data["site"]).upper()]
    if data.get("unit"):
        states = [row for row in states if row["unit_id"] == number(data["unit"], int)]
    if data.get("outage"):
        # Findings use a contains filter for outage codes (so "L30" matches
        # L301/L302). Keep the state-events sheet in the same export scope;
        # otherwise a filtered ledger can silently lose its maintenance rows.
        with connect() as db:
            matching_outages = {row[0] for row in db.execute(
                "SELECT DISTINCT outage FROM tube_states WHERE CAST(outage AS TEXT) LIKE ?",
                (f"%{str(data['outage']).strip()}%",))}
        states = [row for row in states if row["outage"] in matching_outages]
    if data.get("thimble"):
        states = [row for row in states if row["thimble_id"] == number(data["thimble"], int)]
    event = book.create_sheet("管状态事件")
    event.append(["基地", "基地代码", "状态", "大修号", "机组号", "通道编号", "堆芯位置", "状态代码", "有符号位移mm", "方向未确认距离mm", "方向已确认", "备注原文", "维护来源"])
    for state in states:
        station = SITE_NAMES.get(str(state.get("site_code") or "").upper(), state.get("site_code") or "")
        event.append([station, state.get("site_code") or "", display_state(state["state"], state.get("offset_mm"),
                      state.get("unsigned_offset_mm"), state.get("offset_confirmed", 1)), state["outage"], state["unit_id"],
                      state["thimble_id"], state.get("position") or position_for(state["unit_id"], state["thimble_id"]),
                      state["state"], state.get("offset_mm") if state.get("offset_confirmed", 1) else "",
                      state.get("unsigned_offset_mm"), "是" if state.get("offset_confirmed", 1) else "否",
                      state.get("note") or "", state.get("source") or ""])
    apply_plain_excel_table(event)
    for current in (sheet, event):
        current.freeze_panes = "A2"
        current.auto_filter.ref = current.dimensions
        for column in range(1, current.max_column + 1):
            values = [str(current.cell(row, column).value or "") for row in range(1, min(current.max_row, 300) + 1)]
            current.column_dimensions[get_column_letter(column)].width = min(48, max(12, max(map(len, values), default=0) + 2))
        for row_cells in current.iter_rows(min_row=2):
            for cell in row_cells:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
                font = copy(cell.font)
                font.name = PLAIN_EXCEL_FONT
                font.sz = 10
                font.color = "000000"
                cell.font = font
    metadata = book.create_sheet("_ledger_metadata")
    with connect() as db:
        token = db.execute("SELECT token FROM ledger_identity WHERE id=1").fetchone()[0]
    metadata.append(["格式版本", 1])
    metadata.append(["数据库标识", token])
    metadata.sheet_state = "hidden"
    # 摘要放在所有格式化之后创建：表头填充/冻结/筛选等台账样式只作用于数据工作表
    scope_fields = (("基地", "site"), ("机组", "unit"), ("大修", "outage"),
                    ("通道编号", "thimble"), ("分析人员", "analyst"),
                    ("测量通道", "channel"), ("数据组", "calgroup"))
    selected_scope = [(label, key, str(data[key]).strip()) for label, key in scope_fields
                      if data.get(key) is not None and str(data[key]).strip()]
    scope_text = "范围：" + (" · ".join(f"{label} {value}" for label, _, value in selected_scope) or "全量")
    build_ledger_summary_sheet(book, scope_text, rows)
    scope = "-".join(f"{label}{value}" for label, _, value in selected_scope) or "全量"
    filename = artifact_naming.filename("管子综合台账", scope, "xlsx")
    result = workbook_result(filename, book)
    outages = sorted({str(row.get("outage") or "") for row in rows} - {""})
    return record_file_export("data_ledger", {**result, "rows": len(rows), "state_events": len(states)}, {
        "site": data.get("site") or "", "unit": number(data.get("unit"), int),
        "outage": data.get("outage") or "", "outages": outages, "rows": len(rows),
        "analyst": data.get("analyst") or "", "thimble": number(data.get("thimble"), int),
        "channel": data.get("channel") or "", "calgroup": data.get("calgroup") or "",
        "state_events": len(states), "finding_ids": [row.get("id") for row in rows],
        "note": "综合台账与管状态事件分表导出；备注原文和维护来源分列保留",
    })


EDITABLE_FINDING_FIELDS = {
    "thimble_id": ("通道编号", int), "position": ("堆芯位置", str),
    "volts": ("幅值", float), "degrees": ("相位", float), "percent": ("磨损深度", float),
    "indication": ("三字符", str), "channel": ("测量通道", str), "location": ("磨损位置", str),
    "probe": ("探头类型", str), "analyst": ("分析人员", str), "filename": ("数据", str),
    "calgroup": ("数据组", str), "analysis": ("备注", str), "maintenance_text": ("堵管移位信息", str),
}


def update_finding_field(data: dict) -> dict:
    finding_id = number(data.get("id"), int)
    field = str(data.get("field") or "")
    if finding_id is None or field not in EDITABLE_FINDING_FIELDS:
        raise ValueError("检测记录或可编辑字段无效")
    label, cast = EDITABLE_FINDING_FIELDS[field]
    raw = data.get("value")
    if cast is str:
        value = str(raw if raw is not None else "")
    elif raw in (None, "", "/", "-"):
        value = None
    else:
        value = number(raw, cast)
        if value is None or not analysis_reporting.numeric(value):
            raise ValueError(f"{label}必须是有效数字")
        if field == "percent" and not 0 <= value <= 100:
            raise ValueError("磨损深度必须在 0 到 100% 之间")
        if field == "thimble_id" and not 1 <= value <= 50:
            raise ValueError("通道编号必须在 1 到 50 之间")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM findings WHERE id=? AND is_deleted=0", (finding_id,)).fetchone()
        if not row:
            raise ValueError("检测记录已不存在或已删除，请刷新后重试")
        before = row[field]
        if before == value:
            return {"ok": True, "unchanged": True, "id": finding_id, "field": field, "value": value}
        if data.get("expected_value", before) != before:
            raise ValueError("该字段已被其他操作修改，请刷新后重试")
        if field == "position":
            value = value.strip().upper()
            if value != position_for(row["unit_id"], row["thimble_id"]):
                raise ValueError("堆芯位置须与当前机组和通道的管板映射一致；修改通道编号后位置会自动更新")
        before_json = json.dumps(before, ensure_ascii=False)
        after_json = json.dumps(value, ensure_ascii=False)
        db.execute(f"UPDATE findings SET {field}=? WHERE id=?", (value, finding_id))
        if field == "indication":
            db.execute("UPDATE findings SET source_indication=?,indication_resolution='source' WHERE id=?",
                       (value, finding_id))
        if field == "thimble_id":
            db.execute("UPDATE findings SET position=? WHERE id=?", (position_for(row["unit_id"], value), finding_id))
        updated = dict(db.execute("SELECT * FROM findings WHERE id=?", (finding_id,)).fetchone())
        db.execute("UPDATE findings SET business_key=? WHERE id=?", (finding_business_key(updated), finding_id))
        db.execute("INSERT INTO finding_edit_history(finding_id,field_name,before_json,after_json,operator,edited_at) VALUES(?,?,?,?,?,?)",
                   (finding_id, field, before_json, after_json, local_security.actor(),
                    datetime.now().isoformat(timespec="seconds")))
        if field == "thimble_id" and row["position"] != updated["position"]:
            db.execute("INSERT INTO finding_edit_history(finding_id,field_name,before_json,after_json,operator,edited_at) VALUES(?,?,?,?,?,?)",
                       (finding_id, "position", json.dumps(row["position"], ensure_ascii=False),
                        json.dumps(updated["position"], ensure_ascii=False), local_security.actor(),
                        datetime.now().isoformat(timespec="seconds")))
        recognition = None
        if field in {"analysis", "maintenance_text"} and value.strip():
            if re.search(state_recognition.STATE_PATTERN + r"|正常", value, re.I):
                now = datetime.now().isoformat(timespec="seconds")
                batch_id = db.execute("""INSERT INTO import_batches(
                    started_at,finished_at,source_path,import_kind,operator,parser_version,status)
                    VALUES(?,?,?,?,?,?,'completed')""",
                    (now, now, f"检测记录 #{finding_id}", "record_edit",
                     local_security.actor(), SERVICE_VERSION)).lastrowid
                recognition = inspection_states.recognize_import(sys.modules[__name__], db, batch_id, [{
                    "outage": row["outage"], "unit_id": row["unit_id"], "thimble_id": row["thimble_id"],
                    "note": value, "source": f"检测记录 #{finding_id} · {label}编辑",
                }], replace_existing=field == "maintenance_text")
    return {"ok": True, "id": finding_id, "field": field, "field_label": label, "value": value,
            "state_recognition": recognition}


def overview() -> dict:
    with connect() as db:
        stats = dict(db.execute("SELECT COUNT(*) findings, COUNT(DISTINCT outage) outages, COUNT(DISTINCT unit_id) units, COUNT(DISTINCT analyst) analysts FROM statistical_findings WHERE is_deleted=0").fetchone())
        stats["source_findings"] = db.execute("SELECT COUNT(*) FROM findings WHERE is_deleted=0").fetchone()[0]
        outages = [row[0] for row in db.execute("SELECT DISTINCT outage FROM statistical_findings WHERE is_deleted=0 ORDER BY outage DESC")]
        units = [row[0] for row in db.execute("SELECT DISTINCT unit_id FROM statistical_findings WHERE is_deleted=0 ORDER BY unit_id")]
        site_expr = analysis_reporting.site_prefix_sql()
        sites = [row[0] for row in db.execute(f"SELECT DISTINCT {site_expr} FROM statistical_findings WHERE is_deleted=0 ORDER BY 1")]
        combinations = [dict(row) for row in db.execute(f"SELECT DISTINCT {site_expr} site, unit_id, outage FROM statistical_findings WHERE is_deleted=0 ORDER BY site,unit_id,outage DESC")]
        history = [dict(row) for row in db.execute(
            f"""SELECT {site_expr} site, unit_id, outage,
                      COUNT(*) findings, COUNT(DISTINCT thimble_id) tubes,
                      COUNT(DISTINCT analyst) analysts
                 FROM statistical_findings WHERE is_deleted=0
                GROUP BY outage, unit_id
                ORDER BY site, unit_id, outage"""
        )]
        # One coverage scan for all scopes; avoid one DISTINCT query per outage.
        coverage = {}
        for row in db.execute("""SELECT outage, unit_id, thimble_id
                                  FROM statistical_findings
                                 WHERE is_deleted=0 AND thimble_id BETWEEN 1 AND 50
                                 GROUP BY outage, unit_id, thimble_id"""):
            coverage.setdefault((row["outage"], row["unit_id"]), set()).add(row["thimble_id"])
        for scope in history:
            tubes = coverage.get((scope["outage"], scope["unit_id"]), set())
            scope.update(expected_tubes=50, actual_tubes=len(tubes),
                         missing_tubes=sorted(set(range(1, 51)) - tubes),
                         coverage_complete=len(tubes) == 50)
    return {"stats": stats, "sites": sites, "outages": outages, "units": units, "combinations": combinations, "history": history,
            "coverage_warnings": [scope for scope in history if not scope["coverage_complete"]]}


def active_analysis_rules() -> dict:
    """当前生效的对比规则；库内无记录时回退内置初始值（version=0）。"""
    with connect() as db:
        row = db.execute("SELECT * FROM analysis_rules WHERE is_active=1 ORDER BY version DESC LIMIT 1").fetchone()
    if not row:
        return dict(analysis_reporting.DEFAULT_RULES)
    rules = dict(row)
    rules.pop("is_active", None)
    return rules


def list_analysis_rules() -> list[dict]:
    with connect() as db:
        return [dict(row) for row in db.execute("SELECT * FROM analysis_rules ORDER BY version DESC")]


def create_analysis_rule(name: str, match_tolerance_mm, note: str = "") -> dict:
    """建立并激活新的对比规则版本；旧版本保留为历史，不删除。"""
    label = str(name or "").strip()
    if not label:
        raise ValueError("请填写规则名称")
    try:
        tolerance = float(match_tolerance_mm)
    except (TypeError, ValueError):
        raise ValueError("匹配容差必须是数字")
    if not 0 < tolerance <= 5:
        raise ValueError("匹配容差需大于 0 且不超过 5 mm")
    with connect() as db:
        version = db.execute("SELECT COALESCE(MAX(version),0)+1 FROM analysis_rules").fetchone()[0]
        db.execute("UPDATE analysis_rules SET is_active=0")
        cursor = db.execute("""INSERT INTO analysis_rules(version,name,match_tolerance_mm,note,created_by,created_at,is_active)
                               VALUES(?,?,?,?,?,?,1)""",
                            (version, label, tolerance, str(note or "").strip(),
                             local_security.actor(), datetime.now().isoformat(timespec="seconds")))
        rule = dict(db.execute("SELECT * FROM analysis_rules WHERE id=?", (cursor.lastrowid,)).fetchone())
    _log_operation("analysis_rule", "analysis_rules", f"建立并激活规则 v{version}：{label}，容差 {tolerance:g} mm", 1, note=str(note or ""))
    return rule


def compare(old: str, new: str, unit: int) -> dict:
    return analysis_reporting.compare(sys.modules[__name__], old, new, unit, rules=active_analysis_rules())


def compare_many(outages: list[str], unit: int) -> dict:
    """Compare the latest selected outage with the preceding selected batches."""
    outages = [str(item).strip() for item in outages if str(item).strip()]
    if len(outages) < 2:
        raise ValueError("请选择至少两个不同的大修批次")
    if len(set(outages)) != len(outages):
        raise ValueError("大修批次不能重复")
    if any(infer_unit(outage, "") != unit for outage in outages):
        raise ValueError("仅允许比较同一机组的大修批次")
    if len({outage_code(outage) for outage in outages}) != 1:
        raise ValueError("仅允许比较同一基地的大修批次")
    with connect() as db:
        all_rows = {}
        for outage in outages:
            rows = db.execute("SELECT f.*,COALESCE(s.state,'normal') state,CASE WHEN s.offset_confirmed=0 THEN NULL ELSE COALESCE(s.offset_mm,0) END AS offset_mm,s.unsigned_offset_mm,COALESCE(s.note,'') note FROM statistical_findings f LEFT JOIN tube_states s ON s.outage=f.outage AND s.unit_id=f.unit_id AND s.thimble_id=f.thimble_id AND s.is_deleted=0 WHERE f.is_deleted=0 AND f.outage=? AND f.unit_id=?", (outage, unit)).fetchall()
            all_rows[outage] = [dict(row) for row in rows]
    outages.sort(key=outage_sort_key)
    latest = outages[-1]
    matched = compare(outages[-2], latest, unit)
    history_by_tube: dict[int, dict[str, list[dict]]] = {}
    for outage in outages:
        for row in all_rows[outage]:
            if row["thimble_id"] in range(1, 51):
                history_by_tube.setdefault(row["thimble_id"], {}).setdefault(outage, []).append(row)
    items = []
    for thimble in range(1, 51):
        history = history_by_tube.get(thimble, {})
        current_rows = history.get(latest, [])
        previous_rows: list[dict] = []
        for outage in reversed(outages[:-1]):
            if outage in history:
                previous_rows = history[outage]
                break
        results = {r["comparison"] for r in matched["items"] if r["thimble_id"] == thimble}
        comparison = "待确认" if "待确认" in results or not results or any(not history.get(code) for code in outages) else "NDD" if results == {"NDD"} else "R" if results == {"R"} else "NI"
        summarized_history = {}
        for outage in outages:
            rows = history.get(outage, [])
            defects = [row for row in rows if analysis_reporting.category(row) != "NDD"]
            status = "缺少检测记录" if not rows else "NDD" if not defects else ""
            summarized_history[outage] = {
                "volts": "；".join(str(row["volts"]) for row in defects if row.get("volts") is not None),
                "percent": "；".join(str(row["percent"]) for row in defects if row.get("percent") is not None),
                "location": status or "；".join(format_location(row.get("location", "")) for row in defects),
                "count": len(defects), "records": len(rows), "status": status,
            }
        items.append({
            "thimble_id": thimble,
            "position": position_for(unit, thimble),
            "comparison": comparison,
            "note": current_rows[0].get("note", "") if current_rows else "缺少本次检测记录",
            "history": summarized_history,
        })
    coverage = [analysis_reporting.tube_coverage(code, analysis_reporting.rows_for(sys.modules[__name__], outage=code, unit=unit)) for code in outages]
    return {"outages": outages, "new": latest, "unit": unit, "items": items, "coverage": coverage,
            "coverage_complete": all(c["complete"] for c in coverage), "displayed_tubes": 50, "expected_tubes": 50,
            "warnings": [{"thimble_id": tube, "outage": c["outage"], "reason": "缺少该管检测记录，不得视为 NDD"} for c in coverage for tube in c["missing"]],
            "summary": {key: sum(item["comparison"] == key for item in items) for key in ("R", "NI", "待确认", "NDD")}}


def require_complete_comparison(data):
    if not data.get("coverage_complete"):
        missing = "；".join(f"{c['outage']} 缺少通道 {'、'.join(map(str, c['missing']))}" for c in data["coverage"] if c["missing"])
        raise ValueError(f"50根管完整性检查未通过：{missing}。请补齐真实检测记录后导出正式报告，不得用 NDD 补数")

DATAPOINT_MM = 0.125
def comparison_note(summary: dict) -> str:
    """Describe only the comparison markers that actually occur."""
    notes = []
    if int(summary.get("R") or 0) > 0:
        notes.append("结果比对栏内“R”表示此次显示为原有显示")
    if int(summary.get("NI") or 0) > 0:
        notes.append("结果比对栏内“NI”表示此次大修新发现的达到记录标准的显示")
    if int(summary.get("待确认") or 0) > 0 or summary.get("historical_unmatched") or summary.get("missing_tubes"):
        notes.append("“待确认”表示记录不足、位置歧义或历史显示本次未匹配，须人工复核")
    if int(summary.get("NDD") or 0) > 0:
        notes.append("NDD 表示双方均有明确无可记录显示的检测记录；缺少记录不等于 NDD")
    return "；".join(notes) + "。" if notes else "本次对比无达到记录标准的显示。"


def comparison_summary_text(summary: dict) -> str:
    counts = []
    if int(summary.get("R") or 0) > 0:
        counts.append(f"原有显示 R：{summary['R']}")
    if int(summary.get("NI") or 0) > 0:
        counts.append(f"新发现显示 NI：{summary['NI']}")
    return "，".join(counts) if counts else "无达到记录标准的显示"

def normalize_location(location: str) -> tuple[str, float | None]:
    return split_location(location)

def is_real_defect(row) -> bool:
    indication = str(row["indication"] or "").strip().upper()
    if indication in {"NDD", "NONE", "NO DEFECT"}:
        return False
    # DIR999 is a calibration/validation channel, never a physical tube defect.
    channel = str(row.get("channel") or row.get("channel_id") or "").strip().upper()
    if channel == "DIR999" or channel.startswith("DIR999:"):
        return False
    measurement = str(row.get("measurement_type") or "").strip().upper()
    return bool(indication or str(row.get("location") or "").strip() or (measurement and measurement != "NONE"))

def defect_match_key(row, shift_mm: float = 0) -> tuple[str, float]:
    zone, offset = normalize_location(row.get("location", ""))
    if offset is None:
        offset = (row.get("datapoint") or 0) * DATAPOINT_MM
    return zone, round(float(offset) - float(shift_mm or 0), 2)

def annotate_evolution(rows: list[dict], repairs: list[dict] | None = None, rules: dict | None = None) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for row in rows: grouped.setdefault(row["outage"], []).append(row)
    previous = None
    events = repairs if repairs is not None else [row for row in rows if row.get("state") in {"shifted", "replaced", "plugged"}]
    for outage in sorted(grouped, key=outage_sort_key):
        group = grouped[outage]
        for row in group:
            kind = analysis_reporting.category(row)
            row["comparison"] = "无缺陷" if kind == "NDD" else "待确认" if kind == "incomplete" or analysis_reporting.location(row) is None else "NI"
        if previous is not None:
            result = analysis_reporting.compare_rows(previous, outage, group[0]["unit_id"], grouped[previous], group, events, rules=rules)
            for source, matched in zip((r for r in group if analysis_reporting.category(r) != "NDD"), result["items"]):
                source.update({key: matched[key] for key in ("comparison", "comparison_note", "delta_percent", "old_id", "shift_mm")})
        previous = outage
    return rows

def outage_sort_key(outage: str):
    match = re.search(r"^[A-Z]{1,2}(\d)(\d{2})$", str(outage or "").upper())
    return (int(match.group(1)), int(match.group(2))) if match else (999, 999)

def tube_history(site: str, unit: int, thimble: int) -> dict:
    with connect() as db:
        rows = [dict(row) for row in db.execute(f"""SELECT f.*, COALESCE(s.state,'normal') state,
            CASE WHEN s.offset_confirmed=0 THEN NULL ELSE COALESCE(s.offset_mm,0) END AS offset_mm,
            s.unsigned_offset_mm, COALESCE(s.note,'') note
            FROM statistical_findings f LEFT JOIN tube_states s ON s.outage=f.outage AND s.unit_id=f.unit_id AND s.thimble_id=f.thimble_id AND s.is_deleted=0 WHERE f.is_deleted=0
             AND f.unit_id=? AND f.thimble_id=?
            AND {analysis_reporting.site_prefix_sql('f.outage')}=? ORDER BY f.outage""", (unit, thimble, site.upper()))]
    rows.sort(key=lambda row: outage_sort_key(row["outage"]))
    annotate_evolution(rows, analysis_reporting.repairs_for(sys.modules[__name__], site, unit), rules=active_analysis_rules())
    for row in rows:
        row["location_raw"] = row.get("location") or ""
        row["location"] = format_location(row["location_raw"])
    return {"site": site.upper(), "unit": unit, "thimble": thimble, "items": rows}

def unit_evolution(site: str, unit: int) -> dict:
    with connect() as db:
        thimbles = [row[0] for row in db.execute(f"SELECT DISTINCT thimble_id FROM findings WHERE is_deleted=0 AND unit_id=? AND {analysis_reporting.site_prefix_sql()}=? ORDER BY thimble_id", (unit, site.upper()))]
    return {"site": site.upper(), "unit": unit, "tubes": [tube_history(site, unit, thimble) for thimble in thimbles]}


TUBE_LONGITUDINAL_JUMP_DEFAULT = 15.0


def tube_longitudinal(site: str, unit: int, jump: float = TUBE_LONGITUDINAL_JUMP_DEFAULT) -> dict:
    """跨大修纵向对比：同一根管逐次大修的最大报告深度序列、逐次变化与斜率突变标记。

    口径与可视化工作台保持一致：每管每次大修取可量化 WAR 的最大报告深度；
    明确 NDD 或具备无信号依据的占位记录记为 0；未量化或结论待确认时留空；
    缺失轮次直接断线，不重排大修顺序。
    """
    site, unit = str(site).upper(), int(unit)
    try:
        jump_value = float(jump)
    except (TypeError, ValueError):
        jump_value = TUBE_LONGITUDINAL_JUMP_DEFAULT
    if not 5 <= jump_value <= 50:
        raise ValueError("突变阈值须在 5–50 个百分点之间")
    rows = analysis_reporting.rows_for(sys.modules[__name__], site, unit)
    repairs = analysis_reporting.repairs_for(sys.modules[__name__], site, unit)
    def in_scope(row):
        try:
            return analysis_reporting.sequence(row.get("outage"))[:2] == (site, unit) and int(row.get("unit_id", unit)) == unit
        except (TypeError, ValueError):
            return False
    rows = [row for row in rows if in_scope(row)]
    repairs = [{**row, "unit_id": unit} for row in repairs if in_scope(row) and not row.get("is_deleted")]
    outages = {}
    for row in rows:
        outage = str(row.get("outage") or "").upper()
        try:
            _, _, order = analysis_reporting.sequence(outage)
        except ValueError:
            continue
        outages.setdefault(outage, order)
    for event in repairs:
        outage = str(event.get("outage") or "").upper()
        try:
            _, _, order = analysis_reporting.sequence(outage)
        except ValueError:
            continue
        outages.setdefault(outage, order)
    state_by_key = {}
    for event in repairs:
        try:
            tube = int(event.get("thimble_id"))
        except (TypeError, ValueError):
            continue
        if not 1 <= tube <= 50:
            continue
        state_by_key[(tube, str(event.get("outage") or "").upper())] = event
    history = tube_lifecycle.StateHistory(state_by_key.values())
    grouped = defaultdict(lambda: defaultdict(list))
    for row in rows:
        outage = str(row.get("outage") or "").upper()
        if outage not in outages:
            continue
        try:
            tube = int(row.get("thimble_id"))
        except (TypeError, ValueError):
            continue
        if not 1 <= tube <= 50:
            continue
        grouped[tube][outage].append(row)
    tubes = []
    # Keep the physical tube board complete even when a channel has no
    # inspection or maintenance history; an empty series is not a zero depth.
    for tube in sorted(set(range(1, 51)) | set(grouped) | {key[0] for key in state_by_key}):
        series = []
        for outage, order in sorted(outages.items(), key=lambda item: item[1]):
            records = grouped[tube].get(outage)
            current = state_by_key.get((tube, outage))
            if not records and not current:
                continue
            records = records or []
            lifecycle = history.effective(outage, unit, tube)
            names = tube_lifecycle.events(current) if current else []
            depths = [row["percent"] for row in records
                      if str(row.get("indication") or "").strip().upper() == "WAR"
                      and analysis_reporting.numeric(row.get("percent"))
                      and 0 <= row["percent"] <= 100]
            all_ndd = bool(records) and all(analysis_reporting.category(row) == "NDD" for row in records)
            conclusion = ("WAR" if any(str(row.get("indication") or "").strip().upper() == "WAR"
                                      for row in records) else "NDD" if all_ndd
                          else "待核对" if records else "无检测记录")
            report_depth = max(depths) if depths else (0.0 if all_ndd else None)
            replaced = "replaced" in names
            max_depth = (None if lifecycle["needs_review"] else 0.0) if replaced else report_depth
            series.append({"outage": outage, "order": order, "max_depth": max_depth,
                           "report_max_depth": report_depth, "reset": replaced,
                           "generation": lifecycle["generation"],
                           "state_label": lifecycle["state_label"],
                           "current_events": names, "state_outage": lifecycle["last_maintenance"],
                           "needs_review": lifecycle["needs_review"], "warnings": lifecycle["warnings"],
                           "offset_mm": lifecycle["cumulative_offset_mm"],
                           "war_records": len(depths), "records": len(records),
                           "findings": [{"id": row.get("id"),
                                         "indication": row.get("indication") or "",
                                         "location": row.get("location_raw", row.get("location")) or "",
                                         "percent": row.get("percent") if analysis_reporting.numeric(row.get("percent"))
                                                    and 0 <= row["percent"] <= 100 else None,
                                         "channel": row.get("channel") or "",
                                         "source": row.get("report_path") or row.get("filename") or ""}
                                        for row in records],
                           "maintenance_note": current.get("note") or "" if current else "",
                           "maintenance_source": current.get("source") or "" if current else "",
                           "maintenance_offset_mm": current.get("offset_mm") if current and current.get("offset_confirmed", 1) else None,
                           "maintenance_unsigned_offset_mm": current.get("unsigned_offset_mm") if current else None,
                           "ndd": all_ndd and not depths, "conclusion": conclusion, "state": lifecycle["state"],
                           "replaced": replaced, "shifted": lifecycle["shifted"],
                           "plugged": lifecycle["plugged"]})
        previous = None
        for point in series:
            point["delta"] = None
            point["jump"] = False
            point["break_before"] = False
            if previous is None:
                previous = point
                continue
            adjacent = point["order"] - previous["order"] == 1
            interrupted = point["generation"] != previous["generation"]
            point["break_before"] = interrupted
            if adjacent and not interrupted and \
                    previous["max_depth"] is not None and point["max_depth"] is not None:
                delta = round(point["max_depth"] - previous["max_depth"], 2)
                point["delta"] = delta
                point["jump"] = abs(delta) >= jump_value
            previous = point if point["max_depth"] is not None or point["records"] else previous
        tubes.append({"tube": tube, "physical_key": f"{site}/{unit}/{tube}",
                      "position": position_for(unit, tube), "series": series,
                      "has_history": bool(series)})
    return {"site": site, "unit": unit, "unit_code": f"{site}{unit}", "jump": jump_value,
            "outages": [{"outage": outage, "order": order, "label": f"第{order:03d}次大修"}
                        for outage, order in sorted(outages.items(), key=lambda item: item[1])],
            "tubes": tubes}


SUMMARY_WATCH_LEVEL = 30.0   # 关注水位（壁厚%）：与可视化工作台分布视图统一口径
SUMMARY_LIMIT_LEVEL = 50.0   # 极限水位（壁厚%）
SUMMARY_ANOMALY_ROWS = 200   # 摘要异常清单行数上限，超出时提示查看明细工作表


def _summary_bucket_name(level: str) -> str:
    return {
        "ndd": "NDD（无缺陷）", "unquantified": "未量化 / 待确认",
        "low": f"低（< {SUMMARY_WATCH_LEVEL:g}%）",
        "watch": f"关注（{SUMMARY_WATCH_LEVEL:g}–{SUMMARY_LIMIT_LEVEL:g}%）",
        "limit": f"超限（≥ {SUMMARY_LIMIT_LEVEL:g}%）",
    }[level]
SUMMARY_BUCKETS = ("ndd", "unquantified", "low", "watch", "limit")

# 摘要图表配色与前端可视化同源：机组线色取 chart-factory UNIT_PALETTE 前六色，
# 水位线取前端折线图关注/极限水位色（琥珀 #F5A623 / 红 #E84545），
# 分级柱取覆盖度黄与严重度三档（低绿/关注琥珀/超限红），NDD 用中性灰。
SUMMARY_TUBE_COLORS = ("0066CC", "E84545", "22A06B", "F5A623", "7B5BD6", "FF6B1A")
SUMMARY_WATCH_COLOR = "F5A623"
SUMMARY_LIMIT_COLOR = "E84545"
SUMMARY_BUCKET_COLORS = {"ndd": "B8C4C9", "unquantified": "EDC973", "low": "79B98C",
                         "watch": "E5A83B", "limit": "DF4B45"}


def _summary_color_line(series, color: str, width: int = 15875, dash: bool = False) -> None:
    """给折线图系列统一上色；width 单位 EMU（12700 = 1pt）。"""
    from openpyxl.chart.shapes import GraphicalProperties
    from openpyxl.drawing.line import LineProperties
    series.graphicalProperties = GraphicalProperties(
        ln=LineProperties(solidFill=color, w=width, prstDash="dash" if dash else "solid"))
    series.smooth = False


def _summary_color_buckets(chart) -> None:
    """分级柱状图按数据点上色，与前端覆盖度/严重度配色一致。"""
    from openpyxl.chart.series import DataPoint
    from openpyxl.chart.shapes import GraphicalProperties
    chart.series[0].data_points = [
        DataPoint(idx=index, spPr=GraphicalProperties(solidFill=SUMMARY_BUCKET_COLORS[key]))
        for index, key in enumerate(SUMMARY_BUCKETS)]


def _quantified_percent(row) -> float | None:
    """与 tube_longitudinal 同口径：可量化且在 0–100 之间的磨损深度。"""
    value = row.get("percent")
    return value if analysis_reporting.numeric(value) and 0 <= value <= 100 else None


def _summary_sheet(book: Workbook, title: str, scope_text: str, notes: list[str]):
    """可视化摘要工作表：插到工作簿最前，先给结论再看明细。"""
    from openpyxl.chart import BarChart, LineChart, Reference  # noqa: F401（图表在调用方使用）
    sheet = book.create_sheet("可视化摘要", 0)
    sheet["A1"] = title
    sheet["A1"].font = Font(size=15, bold=True)
    sheet["A2"] = scope_text
    sheet["A2"].font = Font(color="647580")
    row = 3
    for note in notes:
        sheet.cell(row, 1, note).font = Font(size=10, color="71818D")
        row += 1
    return sheet, row + 1


def _summary_write_table(sheet, top: int, headers: list, rows: list,
                         formats: dict | None = None) -> int:
    """写一张小表，返回下一个可用行号。None 写作「/」，保持与明细表口径一致。

    formats 按列号（1 起）给数值单元格套用数字格式，如深度列 {3: "0.0"}、
    变化列 {4: "+0.0;-0.0;0.0"}（正负带符号，便于读出增减方向）。
    """
    for column, header in enumerate(headers, 1):
        sheet.cell(top, column, header).font = Font(bold=True)
    for offset, values in enumerate(rows, 1):
        for column, value in enumerate(values, 1):
            cell = sheet.cell(top + offset, column, "/" if value is None or value == "" else value)
            if formats and column in formats and isinstance(value, (int, float)) and not isinstance(value, bool):
                cell.number_format = formats[column]
    apply_plain_excel_table(sheet, header_rows=(top,), data_start=top + 1,
                            end_row=top + len(rows))
    return top + len(rows) + 2


def _summary_percent_bucket(value) -> str:
    if value is None:
        return "unquantified"
    if value <= 0:
        return "ndd"
    if value < SUMMARY_WATCH_LEVEL:
        return "low"
    if value < SUMMARY_LIMIT_LEVEL:
        return "watch"
    return "limit"


def build_evolution_summary_sheet(book: Workbook, site: str, unit: int) -> None:
    """在历次检测演变导出最前插入一页式摘要：趋势折线 + 分级分布 + 异常清单。

    趋势与异常直接复用 tube_longitudinal 的口径（每管每次大修取可量化 WAR 最大深度、
    相邻大修深度突变标记），图表用 openpyxl 原生 LineChart/BarChart，Excel 打开即读。
    """
    from openpyxl.chart import BarChart, LineChart, Reference
    data = tube_longitudinal(site, unit)
    # This export describes inspection reports, not post-maintenance baselines.
    for tube in data["tubes"]:
        previous = None
        reports = []
        for point in tube["series"]:
            if not point["records"]:
                continue
            point = {**point, "max_depth": point["report_max_depth"], "delta": None, "jump": False}
            if previous and point["order"] - previous["order"] == 1 and not point["break_before"] \
                    and not point["reset"] and not previous["reset"] \
                    and point["max_depth"] is not None and previous["max_depth"] is not None:
                point["delta"] = round(point["max_depth"] - previous["max_depth"], 2)
                point["jump"] = abs(point["delta"]) >= data["jump"]
            reports.append(point)
            previous = point
        tube["series"] = reports
    outages = [item["outage"] for item in data["outages"]]
    tubes = data["tubes"]
    peaks = {}
    for tube in tubes:
        values = [point["max_depth"] for point in tube["series"] if point["max_depth"] is not None]
        peaks[tube["tube"]] = max(values) if values else None
    focused = sorted((tube for tube in tubes if peaks[tube["tube"]] and peaks[tube["tube"]] > 0),
                     key=lambda tube: (-peaks[tube["tube"]], tube["tube"]))[:6]
    sheet, top = _summary_sheet(
        book, "历次检测演变 · 可视化摘要",
        f"范围：{data['unit_code']} 机组 · {len(tubes)} 根指套管 · {len(outages)} 次大修 · 生成于 {datetime.now():%Y-%m-%d %H:%M}",
        ["口径：每管每次大修取可量化 WAR 的最大报告深度；明确 NDD 记 0，未量化留空，缺失大修断开。",
         f"关注水位 {SUMMARY_WATCH_LEVEL:g}%、极限水位 {SUMMARY_LIMIT_LEVEL:g}%；"
         f"斜率突变阈值 {data['jump']:g} 个百分点（相邻两次大修深度变化达到阈值即标记）。"])
    # —— 趋势：磨损最重的前几根管逐次大修深度折线（含水位参考线）——
    if focused:
        by_tube = {tube["tube"]: {point["outage"]: point["max_depth"] for point in tube["series"]} for tube in tubes}
        trend_rows = [[f"{tube['tube']} 号管", *[by_tube[tube["tube"]].get(outage) for outage in outages]]
                      for tube in focused]
        trend_rows.append(["关注水位", *[SUMMARY_WATCH_LEVEL for _ in outages]])
        trend_rows.append(["极限水位", *[SUMMARY_LIMIT_LEVEL for _ in outages]])
        trend_top = top
        next_top = _summary_write_table(sheet, trend_top, ["套管 \\ 大修", *outages], trend_rows,
                                        formats={column: "0.0" for column in range(2, 2 + len(outages))})
        chart = LineChart()
        chart.title = f"最大磨损深度趋势（磨损最重的 {len(focused)} 根管）"
        chart.y_axis.title = "磨损深度（壁厚%）"
        chart.x_axis.title = "大修"
        chart.y_axis.scaling.min = 0
        chart.y_axis.scaling.max = 100
        chart.add_data(Reference(sheet, min_col=1, min_row=trend_top,
                                 max_col=1 + len(outages), max_row=trend_top + len(trend_rows)),
                       titles_from_data=True, from_rows=True)
        chart.set_categories(Reference(sheet, min_col=2, min_row=trend_top,
                                       max_col=1 + len(outages), max_row=trend_top))
        # 管线用机组色板，水位线用前端同款琥珀/红虚线加粗，保证打开 Excel 与软件内图表观感一致。
        tube_series_count = len(chart.series) - 2
        for index, series in enumerate(chart.series):
            if index < tube_series_count:
                _summary_color_line(series, SUMMARY_TUBE_COLORS[index % len(SUMMARY_TUBE_COLORS)])
            else:
                _summary_color_line(series, SUMMARY_WATCH_COLOR if index == tube_series_count
                                    else SUMMARY_LIMIT_COLOR, width=25400, dash=True)
        chart.legend.position = "b"
        chart.height, chart.width = 8.5, max(15, min(28, 2.6 * len(outages)))
        chart_row = next_top + 1
        sheet.add_chart(chart, f"A{chart_row}")
        top = chart_row + 18
    else:
        sheet.cell(top, 1, "当前范围没有可量化的磨损数据，趋势图省略。")
        top += 2
    # —— 分布：全部「管 × 大修」数据点的深度分级 ——
    buckets = {key: 0 for key in SUMMARY_BUCKETS}
    for tube in tubes:
        for point in tube["series"]:
            buckets[_summary_percent_bucket(None if point["max_depth"] is None and not point["ndd"] else
                                            (0 if point["ndd"] else point["max_depth"]))] += 1
    dist_top = top
    dist_rows = [[_summary_bucket_name(key), buckets[key]] for key in SUMMARY_BUCKETS]
    next_top = _summary_write_table(sheet, dist_top, ["深度分级", "数据点数"], dist_rows)
    bar = BarChart()
    bar.type = "col"
    bar.title = "数据点分级统计（管 × 大修）"
    bar.y_axis.title = "数据点数"
    bar.add_data(Reference(sheet, min_col=2, min_row=dist_top, max_row=dist_top + len(dist_rows)),
                 titles_from_data=True)
    bar.set_categories(Reference(sheet, min_col=1, min_row=dist_top + 1, max_row=dist_top + len(dist_rows)))
    bar.height, bar.width = 7.5, 14
    bar.legend = None
    _summary_color_buckets(bar)
    bar_row = next_top + 1
    sheet.add_chart(bar, f"A{bar_row}")
    top = bar_row + 16
    # —— 异常清单：超水位点 + 斜率突变点（换管/移位会打断对比，不误报突变）——
    anomalies = []
    for tube in tubes:
        for point in tube["series"]:
            value = point["max_depth"]
            level = "超限" if value is not None and value >= SUMMARY_LIMIT_LEVEL else \
                "关注" if value is not None and value >= SUMMARY_WATCH_LEVEL else ""
            if not level and not point["jump"]:
                continue
            marks = [label for label, on in (("斜率突变", point["jump"]), ("换管", point["replaced"]),
                                             ("移位", point["shifted"]), ("堵管", point["plugged"])) if on]
            anomalies.append([tube["tube"], point["outage"], value,
                              point["delta"] if point["delta"] is not None else "/",
                              level or "突变", "、".join(marks) or "—"])
    anomalies.sort(key=lambda row: (-(row[2] if isinstance(row[2], (int, float)) else -1), row[0], str(row[1])))
    anomaly_note = ""
    if len(anomalies) > SUMMARY_ANOMALY_ROWS:
        anomaly_note = f"（共 {len(anomalies)} 条，仅列出磨损最重的 {SUMMARY_ANOMALY_ROWS} 条，其余见明细工作表）"
        anomalies = anomalies[:SUMMARY_ANOMALY_ROWS]
    sheet.cell(top, 1, f"异常清单{anomaly_note}").font = Font(bold=True, size=12)
    top += 1
    if anomalies:
        _summary_write_table(sheet, top, ["套管", "大修", "最大磨损深度%", "较上次变化", "级别", "标记"], anomalies,
                             formats={3: "0.0", 4: "+0.0;-0.0;0.0"})
    else:
        sheet.cell(top, 1, "当前范围内没有超过关注水位的点，也没有斜率突变。").font = Font(color="647580")
    for column, width in enumerate([14, 12, 16, 12, 10, 18], 1):
        sheet.column_dimensions[get_column_letter(column)].width = width


def build_ledger_summary_sheet(book: Workbook, scope_text: str, rows: list) -> None:
    """在综合台账导出最前插入一页式摘要：记录分级分布 + 按大修概览 + 超水位异常清单。"""
    from openpyxl.chart import BarChart, Reference
    buckets = {key: 0 for key in SUMMARY_BUCKETS}
    per_outage: dict[str, list] = {}
    anomalies = []
    for row in rows:
        outage = str(row.get("outage") or "").upper() or "/"
        stats = per_outage.setdefault(outage, [0, 0, None])
        stats[0] += 1
        category = analysis_reporting.category(row)
        value = _quantified_percent(row) if category == "defect" else None
        if category == "defect":
            stats[1] += 1
            if value is not None:
                stats[2] = max(stats[2] or 0, value)
            bucket = _summary_percent_bucket(value if value is not None and value > 0 else
                                             (None if value is None else 0))
        else:
            bucket = "ndd" if category == "NDD" else "unquantified"
        buckets[bucket] += 1
        if value is not None and value >= SUMMARY_WATCH_LEVEL:
            anomalies.append([row.get("thimble_id"), outage, row.get("unit_id"), row.get("position") or "/",
                              str(row.get("indication") or "").strip() or "/", value,
                              str(row.get("location_raw") or row.get("location") or "").strip() or "/",
                              "超限" if value >= SUMMARY_LIMIT_LEVEL else "关注"])
    sheet, top = _summary_sheet(
        book, "综合台账 · 可视化摘要",
        f"{scope_text} · 共 {len(rows)} 条记录 · 生成于 {datetime.now():%Y-%m-%d %H:%M}",
        ["口径：磨损深度为壁厚%；NDD 与未量化记录不计入超标统计；关注水位 30%、极限水位 50%。",
         "管状态事件按基地、机组、大修和通道编号筛选，不按分析人员、测量通道或数据组筛选。"])
    for row_index in (2, 3, 4):
        sheet.merge_cells(start_row=row_index, start_column=1, end_row=row_index, end_column=8)
        cell = sheet.cell(row_index, 1)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        text_width = sum(2 if ord(char) > 127 else 1 for char in str(cell.value or ""))
        sheet.row_dimensions[row_index].height = 16 * max(1, (text_width + 89) // 90)
    # —— 分布 ——
    dist_top = top
    next_top = _summary_write_table(sheet, dist_top, ["记录分级", "记录数"],
                                    [[_summary_bucket_name(key), buckets[key]] for key in SUMMARY_BUCKETS])
    bar = BarChart()
    bar.type = "col"
    bar.title = "检测记录分级统计"
    bar.y_axis.title = "记录数"
    bar.add_data(Reference(sheet, min_col=2, min_row=dist_top, max_row=dist_top + len(SUMMARY_BUCKETS)),
                 titles_from_data=True)
    bar.set_categories(Reference(sheet, min_col=1, min_row=dist_top + 1, max_row=dist_top + len(SUMMARY_BUCKETS)))
    bar.height, bar.width = 7.5, 14
    bar.legend = None
    _summary_color_buckets(bar)
    bar_row = next_top + 1
    sheet.add_chart(bar, f"A{bar_row}")
    top = bar_row + 16
    # —— 按大修概览 ——
    overview_rows = [[outage, stats[0], stats[1], stats[2]]
                     for outage, stats in sorted(per_outage.items(), key=lambda item: str(item[0]))]
    next_top = _summary_write_table(sheet, top, ["大修", "记录数", "有效缺陷记录", "最大磨损深度%"], overview_rows,
                                    formats={4: "0.0"})
    top = next_top
    # —— 异常清单 ——
    anomalies.sort(key=lambda row: (-row[5], row[0] if isinstance(row[0], int) else 0))
    anomaly_note = ""
    if len(anomalies) > SUMMARY_ANOMALY_ROWS:
        anomaly_note = f"（共 {len(anomalies)} 条，仅列出磨损最重的 {SUMMARY_ANOMALY_ROWS} 条，其余请在台账明细中筛选）"
        anomalies = anomalies[:SUMMARY_ANOMALY_ROWS]
    sheet.cell(top, 1, f"异常清单 · 超过关注水位（≥ {SUMMARY_WATCH_LEVEL:g}%）的记录{anomaly_note}").font = Font(bold=True, size=12)
    top += 1
    if anomalies:
        _summary_write_table(sheet, top, ["套管", "大修", "机组", "堆芯位置", "三字符", "磨损深度%", "磨损位置", "级别"], anomalies,
                             formats={6: "0.0"})
    else:
        sheet.cell(top, 1, "当前范围内没有超过关注水位的缺陷记录。").font = Font(color="647580")
    for column, width in enumerate([10, 12, 8, 12, 10, 14, 20, 8], 1):
        sheet.column_dimensions[get_column_letter(column)].width = width


def export_evolution_excel(site: str, unit: int) -> dict:
    data = unit_evolution(site, unit)
    book = Workbook(); sheet = book.active; sheet.title = "指套管纵向演变"
    sheet.append(["基地", "机组", "套管", "大修", "状态", "位置", "数据点", "磨损深度", "判定", "备注"])
    for tube in data["tubes"]:
        previous = []
        for row in tube["items"]:
            defects = [item for item in [row] if is_real_defect(item)]
            state = row["state"]
            comparison = row.get("comparison", "无缺陷")
            for item in defects or [row]:
                sheet.append([site, unit, tube["thimble"], row["outage"], state, item["location"], item["datapoint"], item["percent"], comparison, row["note"]])
            if defects: previous = defects
    apply_plain_excel_table(sheet)
    build_evolution_summary_sheet(book, site, unit)
    result = workbook_result(artifact_naming.filename("历次检测演变", f"{site}机组{unit}", "xlsx"), book)
    rows = sum(len(tube["items"]) for tube in data["tubes"])
    return record_file_export("evolution", {**result, "rows": rows}, {
        "site": site, "unit": unit, "rows": rows, "tubes": len(data["tubes"]),
        "outages": sorted({row["outage"] for tube in data["tubes"] for row in tube["items"]}),
        "finding_ids": [row.get("id") for tube in data["tubes"] for row in tube["items"]],
        "rules": active_analysis_rules(),
    })


def workbook_result(filename: str, book: Workbook) -> dict:
    book.properties.creator = local_security.actor()
    book.properties.lastModifiedBy = local_security.actor()
    EXCEL_DIR.mkdir(parents=True, exist_ok=True)
    target = EXCEL_DIR / filename
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=f".{target.stem}.", suffix=".tmp", dir=EXCEL_DIR, delete=False) as handle:
            temporary = Path(handle.name)
        try:
            from .state_transfer import save_workbook_exact
        except ImportError:
            from state_transfer import save_workbook_exact
        save_workbook_exact(book, temporary)
        try:
            os.replace(temporary, target)
        except OSError:
            # Some encrypted/redirected Windows profile folders reject an
            # atomic replace even for sibling files. Preserve the completed
            # export with a copy fallback, then remove only our temp file.
            try:
                shutil.copyfile(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
    except Exception:
        if temporary and temporary.exists():
            temporary.unlink(missing_ok=True)
        LOGGER.exception("Excel export failed: %s", target)
        raise
    return {"filename": filename, "file_path": str(target), "download_url": f"/api/download-excel?name={quote(filename)}"}


def record_file_export(export_kind: str, result: dict, evidence: dict) -> dict:
    """为落盘导出补齐来源凭证与审计：SHA-256 + 同名 .provenance.json + report_exports 记录。

    遗留独立导出入口（正式检验报告单 / 综合对比表 / 纵向演变 / 三字符缺失清单）与
    统一报告中心共用同一套追溯结构，保证任何导出的文件都能追溯到当次数据范围、
    记录明细与操作者。evidence 至少说明导出范围；outage/old/new/unit 用于审计列。
    """
    evidence = {k:v for k,v in evidence.items() if k not in {"operator","actor_id","created_at","sha256"}}
    file_path = Path(result["file_path"])
    digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
    payload = {
        "export_kind": export_kind,
        "sha256": digest,
        "operator": local_security.actor(),
        "parser_version": SERVICE_VERSION,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "rule_note": analysis_reporting.RULE_NOTE,
        **evidence,
    }
    provenance = file_path.with_name(file_path.name + ".provenance.json")
    temporary = provenance.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        try:
            temporary.replace(provenance)
        except OSError:
            shutil.copyfile(temporary, provenance)
            temporary.unlink(missing_ok=True)
    finally:
        temporary.unlink(missing_ok=True)
    payload["provenance_sha256"] = hashlib.sha256(provenance.read_bytes()).hexdigest()
    payload["provenance_path"] = str(provenance)
    with connect() as db:
        audit_id = db.execute("""INSERT INTO report_exports(
            created_at,export_kind,outage,old_outage,new_outage,unit_id,path,metadata_json
        ) VALUES(?,?,?,?,?,?,?,?)""", (
            payload["created_at"], export_kind,
            str(evidence.get("outage") or ""), str(evidence.get("old") or ""),
            str(evidence.get("new") or evidence.get("outage") or ""),
            int(evidence.get("unit") or 0), str(file_path),
            json.dumps(payload, ensure_ascii=False, default=str),
        )).lastrowid
    return {**result, "sha256": digest, "export_audit_id": audit_id,
            "provenance_file_path": str(provenance), "provenance_filename": provenance.name,
            "provenance_download_url": result["download_url"].split("?")[0] + "?name=" + quote(provenance.name)}


def export_comparison_excel(old: str, new: str, unit: int) -> dict:
    data = compare(old, new, unit)
    require_complete_comparison(data)
    book = Workbook()
    sheet = book.active
    sheet.title = "涡流检验结果对比表"
    sheet.merge_cells("A1:J1")
    sheet["A1"] = f"{unit}号机组反应堆中子通量测量指套管涡流检验结果对比表"
    sheet["A1"].font = Font(size=15, bold=True)
    sheet["A1"].alignment = Alignment(horizontal="center")
    sheet.append(["序号", "通道编号", "堆芯位置", new, "", "", old, "", "", "备注"])
    sheet.append(["", "", "", "幅值（V）", "磨损深度（壁厚%）", "磨损位置（mm）", "幅值（V）", "磨损深度（壁厚%）", "磨损位置（mm）", ""])
    for column in ("A", "B", "C", "J"):
        sheet.merge_cells(f"{column}2:{column}3")
    sheet.merge_cells("D2:F2")
    sheet.merge_cells("G2:I2")
    for row in analysis_reporting.comparison_values(data["items"]):
        sheet.append(["/" if value is None or value == "" else value for value in row])
    spans = report_tube_rowspans(data["items"])
    for offset, span in enumerate(spans, 4):
        if span > 1:
            sheet.merge_cells(start_row=offset, end_row=offset + span - 1, start_column=2, end_column=2)
            sheet.merge_cells(start_row=offset, end_row=offset + span - 1, start_column=3, end_column=3)
    note_row = sheet.max_row + 1
    sheet.merge_cells(start_row=note_row, end_row=note_row, start_column=1, end_column=10)
    sheet.cell(note_row, 1, f"备注：{comparison_note(data['summary'])}")
    apply_plain_excel_table(sheet, header_rows=(2, 3), data_start=4)
    sheet.freeze_panes = "A4"
    for column in range(1, 11):
        sheet.column_dimensions[get_column_letter(column)].width = 16 if 4 <= column <= 9 else 11
    return {**workbook_result(artifact_naming.filename("历次大修对比", f"机组{unit}_{old}-{new}", "xlsx"), book), **data["summary"]}


def export_comparison_excel_many(outages: list[str], unit: int) -> dict:
    data = compare_many(outages, unit)
    require_complete_comparison(data)
    book = Workbook(); sheet = book.active; sheet.title = "多次大修对比"
    headers = ["判定", "套管", "堆芯位置"]
    for outage in data["outages"]:
        headers.extend([f"{outage}幅值(V)", f"{outage}磨损深度(%)", f"{outage}磨损位置"])
    headers.append("备注"); sheet.append(headers)
    for row in data["items"]:
        values = [row["comparison"], row["thimble_id"], row["position"]]
        for outage in data["outages"]:
            item = row.get("history", {}).get(outage, {})
            values.extend([item.get("volts", ""), item.get("percent", ""), item.get("location", "")])
        values.append(row.get("note", "")); sheet.append(values)
    apply_plain_excel_table(sheet)
    sheet.freeze_panes = "A2"
    for column in range(1, len(headers) + 1): sheet.column_dimensions[get_column_letter(column)].width = 16
    return {**workbook_result(artifact_naming.filename("多次大修对比", f"机组{unit}_{'-'.join(data['outages'])}", "xlsx"), book), **data["summary"]}


def export_inspection_report(outage: str, unit: int, metadata: dict) -> dict:
    if infer_unit(outage, "") != unit:
        raise ValueError("大修编号与机组不匹配")
    with connect() as db:
        rows = [dict(row) for row in db.execute("SELECT * FROM statistical_findings WHERE is_deleted=0 AND outage=? AND unit_id=? ORDER BY thimble_id,entry_no,datapoint", (outage, unit))]
    if not rows:
        raise ValueError("当前条件没有可生成报告的数据")
    book = Workbook()
    sheet = book.active
    sheet.title = "涡流检验报告单"
    sheet.merge_cells("A1:H1")
    sheet["A1"] = metadata.get("title") or "反应堆中子通量测量指套管涡流检验报告单"
    sheet["A1"].font = Font(size=16, bold=True)
    sheet["A1"].alignment = Alignment(horizontal="center")
    info = [
        ("电厂名称", metadata.get("plant", "")), ("机组", unit), ("检查类型", metadata.get("inspection_type", outage)),
        ("设备/部件名称", metadata.get("component", "指套管")), ("安全等级", metadata.get("safety_class", "")), ("方向号", metadata.get("direction", "")),
        ("材料", metadata.get("material", "")), ("尺寸", metadata.get("size", "")), ("报告单编号", metadata.get("report_no", "")),
    ]
    for index in range(0, len(info), 3):
        row = 3 + index // 3
        for offset, (label, value_) in enumerate(info[index:index + 3]):
            col = 1 + offset * 2
            sheet.cell(row, col, label).font = Font(bold=True)
            sheet.cell(row, col + 1, value_)
    header_row = 7
    headers = ["序号", "通道编号", "堆芯位置", "显示类型", "幅值(V)", "磨损深度(壁厚%)", "磨损位置", "测量通道"]
    for col, label in enumerate(headers, 1):
        sheet.cell(header_row, col, label)
    for index, row in enumerate(rows, 1):
        display = display_indication(row)
        ndd = display == "NDD"
        values = [index, row["thimble_id"], row["position"], display,
                  "/" if ndd else row["volts"], "/" if ndd else row["percent"],
                  "/" if ndd else row["location"], "/" if ndd else row["channel"]]
        for col, value_ in enumerate(values, 1):
            sheet.cell(header_row + index, col, value_)
    apply_plain_excel_table(sheet, header_rows=(header_row,), data_start=header_row + 1)
    sheet.freeze_panes = f"A{header_row + 1}"
    widths = [8, 12, 13, 12, 12, 18, 18, 16]
    for col, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(col)].width = width
    return {**workbook_result(artifact_naming.filename("检验结果报告", f"机组{unit}_{outage}", "xlsx"), book), "rows": len(rows)}


def inspection_report_rows(outage: str, unit: int, finding_ids: list[int] | None = None) -> list[dict]:
    outage = str(outage or "").strip().upper()
    if not outage or not unit:
        raise ValueError("请选择大修和机组")
    ids = sorted({int(value) for value in (finding_ids or []) if str(value).isdigit() and int(value) > 0})
    sql = "SELECT * FROM statistical_findings WHERE is_deleted=0 AND outage=? AND unit_id=?"
    args: list = [outage, unit]
    if ids:
        sql += f" AND id IN ({','.join('?' for _ in ids)})"
        args.extend(ids)
    sql += " ORDER BY thimble_id,entry_no,datapoint,id"
    with connect() as db:
        rows = [dict(row) for row in db.execute(sql, args)]
    if not rows:
        raise ValueError("当前条件或勾选记录没有可生成报告的数据")
    return consolidate_ndd_rows(rows)


def report_tube_rowspans(rows: list[dict]) -> list[int]:
    """Return per-row spans for consecutive records of the same physical tube."""
    spans = [1] * len(rows)
    index = 0
    while index < len(rows):
        channel = rows[index].get("thimble_id")
        position = str(rows[index].get("position") or "").strip()
        end = index + 1
        if channel not in (None, "") and position:
            while end < len(rows):
                candidate = rows[end]
                if candidate.get("thimble_id") != channel or str(candidate.get("position") or "").strip() != position:
                    break
                end += 1
        if end - index > 1:
            spans[index] = end - index
            for continuation in range(index + 1, end):
                spans[continuation] = 0
        index = end
    return spans


def report_metadata(metadata: dict, outage: str, unit: int) -> list[tuple[str, str]]:
    return [
        ("设备/部件编号", str(metadata.get("component_no") or "")),
        ("涡流检验报告单（TH）", ""),
        ("报告单编号", str(metadata.get("report_no") or "")),
        ("电厂名称", str(metadata.get("plant") or "")),
        ("机组", str(unit)),
        ("检查类型", str(metadata.get("inspection") or outage)),
        ("设备/部件名称", str(metadata.get("component") or "指套管")),
        ("安全等级", str(metadata.get("safety") or "")),
        ("房间号", str(metadata.get("room") or "")),
        ("检验范围", str(metadata.get("scope") or "")),
        ("材料", str(metadata.get("material") or "")),
        ("尺寸", str(metadata.get("size") or "Φ8.6 × 1.7 mm")),
        ("涡流仪型号", str(metadata.get("instrument_model") or "")),
        ("涡流仪出厂编号", str(metadata.get("instrument_serial") or "")),
        ("标定管编号", str(metadata.get("calibration_no") or "")),
        ("探头类型", str(metadata.get("probe_type") or "")),
        ("探头型号", str(metadata.get("probe_model") or "")),
        ("探头规格", str(metadata.get("probe_spec") or "Φ4.8 mm")),
        ("检验速度", str(metadata.get("speed") or "250 mm/s")),
        ("采样率", str(metadata.get("sample_rate") or "2000 点/秒")),
        ("检验频率", str(metadata.get("frequency") or "160、80、40、20 kHz")),
        ("检验程序/版次", str(metadata.get("procedure") or "")),
    ]


def enrich_report_metadata(metadata: dict, rows: list[dict], outage: str, unit: int) -> dict:
    """Fill only values that are present in imported SUM/RPT data; never guess identifiers."""
    result = dict(metadata or {})
    first = rows[0] if rows else {}
    defaults = {
        "plant": first.get("site_owner") or first.get("site_code") or "",
        "inspection": outage,
        "component": "指套管",
        "instrument_model": first.get("tester") or "",
        "probe_model": first.get("probe") or "",
        "probe_type": "BOBBIN",
        "probe_spec": "Φ4.8 mm",
        "size": "Φ8.6 × 1.7 mm",
        "speed": "250 mm/s",
        "sample_rate": "2000 点/秒",
        "frequency": "160、80、40、20 kHz",
    }
    for key, value in defaults.items():
        if not str(result.get(key) or "").strip() and value:
            result[key] = value
    result["unit"] = unit
    return result


def _w_text(value) -> str:
    return (html.escape("" if value is None else str(value), quote=False)
            .replace("\r", "&#13;")
            .replace("\t", '</w:t><w:tab/><w:t xml:space="preserve">')
            .replace("\n", '</w:t><w:br/><w:t xml:space="preserve">'))


def _w_paragraph(value="", align="center", bold=False, size=20) -> str:
    alignment = f'<w:jc w:val="{align}"/>' if align else ""
    weight = "<w:b/>" if bold else ""
    return f'<w:p><w:pPr>{alignment}</w:pPr><w:r><w:rPr>{weight}<w:sz w:val="{size}"/><w:rFonts w:ascii="SimSun" w:hAnsi="SimSun" w:eastAsia="宋体"/></w:rPr><w:t xml:space="preserve">{_w_text(value)}</w:t></w:r></w:p>'


def _w_table(headers: list[str], rows: list[list], merge_group_columns: tuple[int, ...] = (), merge_columns: tuple[int, ...] = (), widths: list[int] | None = None, font_size: int = 16) -> str:
    count = len(headers); widths = widths or [max(900, 10200 // max(1, count))] * count
    if len(widths) != count:
        raise ValueError("表格列宽数量与表头不一致")
    grid = "".join(f'<w:gridCol w:w="{width}"/>' for width in widths)
    merge_states = ["none"] * len(rows)
    if merge_group_columns and merge_columns:
        groups = [tuple(row[column] for column in merge_group_columns) for row in rows]
        for index, group in enumerate(groups):
            if any(value in (None, "") for value in group):
                continue
            previous_same = index > 0 and groups[index - 1] == group
            next_same = index + 1 < len(groups) and groups[index + 1] == group
            if previous_same:
                merge_states[index] = "continue"
            elif next_same:
                merge_states[index] = "restart"
    def row_xml(values, header=False, merge_state="none"):
        cells = []
        for column, value in enumerate(values):
            vertical_merge = ""
            if not header and column in merge_columns and merge_state != "none":
                vertical_merge = '<w:vMerge w:val="restart"/>' if merge_state == "restart" else "<w:vMerge/>"
                if merge_state == "continue":
                    value = ""
            width = widths[column]
            cells.append(f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/><w:vAlign w:val="center"/><w:tcMar><w:top w:w="40" w:type="dxa"/><w:left w:w="50" w:type="dxa"/><w:bottom w:w="40" w:type="dxa"/><w:right w:w="50" w:type="dxa"/></w:tcMar>{vertical_merge}</w:tcPr>{_w_paragraph(value, "center", header, font_size)}</w:tc>')
        repeat = '<w:trPr><w:tblHeader/></w:trPr>' if header else ""
        return f'<w:tr>{repeat}{"".join(cells)}</w:tr>'
    body = "".join(row_xml(row, merge_state=merge_states[index]) for index, row in enumerate(rows))
    return f'<w:tbl><w:tblPr><w:tblBorders><w:top w:val="single" w:sz="6"/><w:left w:val="single" w:sz="6"/><w:bottom w:val="single" w:sz="6"/><w:right w:val="single" w:sz="6"/><w:insideH w:val="single" w:sz="4"/><w:insideV w:val="single" w:sz="4"/></w:tblBorders><w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>{grid}</w:tblGrid>{row_xml(headers, True)}{body}</w:tbl>'


def _w_comparison_table(new: str, old: str, rows: list[list]) -> str:
    """Build the formal two-level outage comparison table."""
    widths = [520, 760, 820, 800, 900, 980, 800, 900, 980, 560]
    grid = "".join(f'<w:gridCol w:w="{width}"/>' for width in widths)

    def cell(value, width, *, bold=False, grid_span=1, vmerge=""):
        span = f'<w:gridSpan w:val="{grid_span}"/>' if grid_span > 1 else ""
        merge = '<w:vMerge w:val="restart"/>' if vmerge == "restart" else ("<w:vMerge/>" if vmerge == "continue" else "")
        return f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/><w:vAlign w:val="center"/>{span}{merge}</w:tcPr>{_w_paragraph(value, "center", bold, 15)}</w:tc>'

    header_one = "".join([
        cell("序号", widths[0], bold=True, vmerge="restart"),
        cell("通道编号", widths[1], bold=True, vmerge="restart"),
        cell("堆芯位置", widths[2], bold=True, vmerge="restart"),
        cell(new, sum(widths[3:6]), bold=True, grid_span=3),
        cell(old, sum(widths[6:9]), bold=True, grid_span=3),
        cell("备注", widths[9], bold=True, vmerge="restart"),
    ])
    subheaders = ["幅值（V）", "磨损深度（壁厚%）", "磨损位置（mm）"]
    header_two = "".join([
        cell("", widths[0], vmerge="continue"),
        cell("", widths[1], vmerge="continue"),
        cell("", widths[2], vmerge="continue"),
        *(cell(label, widths[3 + index], bold=True) for index, label in enumerate(subheaders)),
        *(cell(label, widths[6 + index], bold=True) for index, label in enumerate(subheaders)),
        cell("", widths[9], vmerge="continue"),
    ])

    groups = [(row[1], str(row[2] or "").strip()) for row in rows]
    body_rows = []
    for row_index, row in enumerate(rows):
        group = groups[row_index]
        merge_state = "none"
        if group[0] not in (None, "") and group[1]:
            if row_index > 0 and groups[row_index - 1] == group:
                merge_state = "continue"
            elif row_index + 1 < len(groups) and groups[row_index + 1] == group:
                merge_state = "restart"
        body_cells = []
        for column, value in enumerate(row):
            state = merge_state if column in (1, 2) else ""
            if state == "continue":
                value = ""
            body_cells.append(cell(value, widths[column], vmerge=state))
        body_rows.append(f'<w:tr>{"".join(body_cells)}</w:tr>')

    borders = '<w:tblBorders><w:top w:val="single" w:sz="6"/><w:left w:val="single" w:sz="6"/><w:bottom w:val="single" w:sz="6"/><w:right w:val="single" w:sz="6"/><w:insideH w:val="single" w:sz="4"/><w:insideV w:val="single" w:sz="4"/></w:tblBorders>'
    return f'<w:tbl><w:tblPr>{borders}<w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>{grid}</w:tblGrid><w:tr>{header_one}</w:tr><w:tr>{header_two}</w:tr>{"".join(body_rows)}</w:tbl>'


def _w_report_info_table(pairs: list[tuple[str, str]]) -> str:
    """Build the fixed TH header: six regular rows followed by two merged rows."""
    widths = [1100, 2300, 1100, 2300, 1100, 2300]
    grid = "".join(f'<w:gridCol w:w="{width}"/>' for width in widths)
    def cell(value, start, span=1, bold=False):
        width = sum(widths[start:start + span]); grid_span = f'<w:gridSpan w:val="{span}"/>' if span > 1 else ""
        return f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/><w:vAlign w:val="center"/>{grid_span}<w:tcMar><w:top w:w="35" w:type="dxa"/><w:left w:w="45" w:type="dxa"/><w:bottom w:w="35" w:type="dxa"/><w:right w:w="45" w:type="dxa"/></w:tcMar></w:tcPr>{_w_paragraph(value, "center", bold, 15)}</w:tc>'
    rows = []
    rows.append(f'<w:tr>{cell(pairs[0][0],0,bold=True)}{cell(pairs[0][1],1)}{cell("涡流检验报告单（TH）",2,2,True)}{cell(pairs[2][0],4,bold=True)}{cell(pairs[2][1],5)}</w:tr>')
    for index in range(3, 18, 3):
        row = pairs[index:index + 3]
        rows.append('<w:tr>' + ''.join(cell(label, pair_index * 2, bold=True) + cell(value, pair_index * 2 + 1) for pair_index, (label, value) in enumerate(row)) + '</w:tr>')
    for left, right in ((pairs[18], pairs[19]), (pairs[20], pairs[21])):
        rows.append(f'<w:tr>{cell(left[0],0,bold=True)}{cell(left[1],1,2)}{cell(right[0],3,bold=True)}{cell(right[1],4,2)}</w:tr>')
    borders = '<w:tblBorders><w:top w:val="single" w:sz="6"/><w:left w:val="single" w:sz="6"/><w:bottom w:val="single" w:sz="6"/><w:right w:val="single" w:sz="6"/><w:insideH w:val="single" w:sz="4"/><w:insideV w:val="single" w:sz="4"/></w:tblBorders>'
    return f'<w:tbl><w:tblPr>{borders}<w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>{grid}</w:tblGrid>{"".join(rows)}</w:tbl>'


def _w_page_break() -> str:
    return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'


def _write_docx(filename: str, blocks: list[str], landscape=True, margin=792) -> dict:
    from zipfile import ZIP_DEFLATED, ZipFile
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    target = REPORT_DIR / filename; temporary = target.with_name(f".{target.stem}.{os.getpid()}.tmp")
    size = '<w:pgSz w:w="15840" w:h="12240"/>' if landscape else '<w:pgSz w:w="12240" w:h="15840"/>'
    document_xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + ''.join(blocks) + f'<w:sectPr>{size}<w:pgMar w:top="{margin}" w:right="{margin}" w:bottom="{margin}" w:left="{margin}"/></w:sectPr></w:body></w:document>'
    content_types = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>'
    rels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>'
    author = html.escape(local_security.actor())
    core = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>{author}</dc:creator><cp:lastModifiedBy>{author}</cp:lastModifiedBy></cp:coreProperties>'
    word_rels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with ZipFile(temporary, "w", ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types); archive.writestr("_rels/.rels", rels); archive.writestr("docProps/core.xml", core); archive.writestr("word/document.xml", document_xml); archive.writestr("word/_rels/document.xml.rels", word_rels)
        try:
            os.replace(temporary, target)
        except OSError:
            shutil.copyfile(temporary, target)
            temporary.unlink(missing_ok=True)
    except Exception:
        temporary.unlink(missing_ok=True); LOGGER.exception("Word report export failed: %s", target); raise
    return {"filename": filename, "file_path": str(target), "download_url": f"/api/download-report?name={quote(filename)}"}


def build_inspection_preview(outage: str, unit: int, metadata: dict, finding_ids: list[int] | None = None) -> dict:
    rows = inspection_report_rows(outage, unit, finding_ids)
    metadata = enrich_report_metadata(metadata, rows, outage, unit)
    title = metadata.get("title") or "反应堆中子通量测量指套管涡流检验报告单"
    fields = report_metadata(metadata, outage, unit)
    info = f"<span>{html.escape(fields[0][0])}</span><b>{html.escape(fields[0][1] or '待填写')}</b><b class='static-title'>涡流检验报告单（TH）</b><span>{html.escape(fields[2][0])}</span><b>{html.escape(fields[2][1] or '待填写')}</b>"
    info += "".join(f"<span>{html.escape(label)}</span><b>{html.escape(value or '待填写')}</b>" for label, value in fields[3:18])
    info += "".join(f"<span>{html.escape(label)}</span><b class='wide-value'>{html.escape(value or '待填写')}</b>" for label, value in fields[18:])
    body_rows = []
    for index, (row, rowspan) in enumerate(zip(rows, report_tube_rowspans(rows)), 1):
        tube_cells = ""
        if rowspan:
            span = f" rowspan='{rowspan}'" if rowspan > 1 else ""
            tube_cells = f"<td{span}>{row['thimble_id']}</td><td{span}>{html.escape(row.get('position') or '')}</td>"
        indication = display_indication(row)
        ndd = indication == "NDD"
        body_rows.append(
            f"<tr><td>{index}</td>{tube_cells}<td>{html.escape(indication)}</td>"
            f"<td>{'/' if ndd or row.get('volts') is None else row['volts']}</td>"
            f"<td>{'/' if ndd or row.get('percent') is None else row['percent']}</td>"
            f"<td>{html.escape('/' if ndd else format_location(row.get('location') or ''))}</td>"
            f"<td>{html.escape('/' if ndd else row.get('channel') or '')}</td></tr>"
        )
    body = "".join(body_rows)
    preview = f"<article class='report-sheet'><div class='report-page-mark'>II-1/1</div><h1>{html.escape(title)}</h1><section class='report-info'>{info}</section><h2>检验结果</h2><div class='report-table-wrap'><table><thead><tr><th>序号</th><th>通道编号</th><th>堆芯位置</th><th>显示类型</th><th>幅值（V）</th><th>磨损深度（壁厚%）</th><th>磨损位置</th><th>测量通道</th></tr></thead><tbody>{body}</tbody></table></div><footer>备注：无。<br><br>分析人员/级别：____________　审核/级别：____________　批准：____________　业主：____________</footer></article>"
    return {"title": title, "rows": len(rows), "html": preview}


def export_inspection_docx(outage: str, unit: int, metadata: dict, finding_ids: list[int] | None = None) -> dict:
    rows = inspection_report_rows(outage, unit, finding_ids)
    metadata = enrich_report_metadata(metadata, rows, outage, unit)
    columns = ["序号", "通道编号", "堆芯位置", "显示类型", "幅值（V）", "磨损深度（壁厚%）", "磨损位置", "测量通道"]
    column_widths = [600, 900, 1000, 900, 900, 1350, 2350, 2200]
    pages = [rows[index:index + 20] for index in range(0, len(rows), 20)] or [[]]
    blocks = []
    for page_index, page_rows in enumerate(pages, 1):
        blocks.append(_w_paragraph(f"II-{page_index}/{len(pages)}", "right", False, 14))
        blocks.append(_w_report_info_table(report_metadata(metadata, outage, unit)))
        blocks.append(_w_paragraph("检验结果", "center", True, 18))
        values = []
        for row_index, row in enumerate(page_rows, page_index * 20 - 19):
            indication = display_indication(row)
            is_ndd = str(indication).strip().upper() in {"NDD", "NONE", "NO DEFECT"}
            values.append([
                row_index, row.get("thimble_id") or "", row.get("position") or "", indication,
                "/" if is_ndd or row.get("volts") is None else row.get("volts"),
                "/" if is_ndd or row.get("percent") is None else row.get("percent"),
                "/" if is_ndd else format_location(row.get("location") or ""),
                "/" if is_ndd else row.get("channel") or "",
            ])
        values.extend([["", "", "", "", "", "", "", ""] for _ in range(20 - len(values))])
        blocks.append(_w_table(columns, values, merge_group_columns=(1, 2), merge_columns=(1, 2), widths=column_widths, font_size=15))
        blocks.append(_w_paragraph("备注：无。", "left", False, 14))
        blocks.append(_w_table(
            ["", "分析人员/级别", "审核/级别", "批准", "业主"],
            [["签名", "", "", "", ""], ["日期", "", "", "", ""]],
            widths=[800, 2500, 2500, 2200, 2200], font_size=14,
        ))
        if page_index < len(pages): blocks.append(_w_page_break())
    result = _write_docx(artifact_naming.filename("检验结果报告", f"机组{unit}_{outage}", "docx"), blocks, landscape=False, margin=500)
    return record_file_export("inspection_form", {**result, "rows": len(rows)}, {
        "outage": outage, "unit": unit, "rows": len(rows),
        "finding_ids": [row.get("id") for row in rows],
        "source_keys": sorted({str(row.get("source_key") or "") for row in rows} - {""}),
        "report_paths": sorted({str(row.get("report_path") or "") for row in rows} - {""}),
        "metadata": metadata,
        "rules": active_analysis_rules(),
        "warnings": [{"thimble_id": row.get("thimble_id"), "reason": "原始结论缺失，报告留空待确认"}
                     for row in rows if analysis_reporting.category(row) == "incomplete"],
    })


def build_comparison_preview(old: str, new: str, unit: int) -> dict:
    data = compare(old, new, unit)
    body_rows = []
    for row, values, rowspan in zip(data["items"], analysis_reporting.comparison_values(data["items"]), report_tube_rowspans(data["items"])):
        tube_cells = ""
        if rowspan:
            span = f" rowspan='{rowspan}'" if rowspan > 1 else ""
            tube_cells = f"<td{span}>{row['thimble_id']}</td><td{span}>{html.escape(row.get('position') or '')}</td>"
        body_rows.append(f"<tr><td>{values[0]}</td>{tube_cells}" + "".join(
            f"<td>{html.escape('/' if value is None or value == '' else str(value))}</td>" for value in values[3:]) + "</tr>")
    body = "".join(body_rows)
    title = f"{unit}号机组反应堆中子通量测量指套管涡流检验结果对比表"
    summary_text = comparison_summary_text(data["summary"])
    note = comparison_note(data["summary"])
    preview = f"<article class='report-sheet comparison-sheet'><h1>{html.escape(title)}</h1><p class='report-lead'>本次大修（{html.escape(new)}）与历史大修（{html.escape(old)}）结果对比。{html.escape(summary_text)}。</p><div class='report-table-wrap'><table><caption>表 5　涡流检验结果比对表</caption><thead><tr><th rowspan='2'>序号</th><th rowspan='2'>通道编号</th><th rowspan='2'>堆芯位置</th><th colspan='3'>{html.escape(new)}</th><th colspan='3'>{html.escape(old)}</th><th rowspan='2'>结果比对</th></tr><tr><th>幅值（V）</th><th>磨损深度（壁厚%）</th><th>磨损位置（mm）</th><th>幅值（V）</th><th>磨损深度（壁厚%）</th><th>磨损位置（mm）</th></tr></thead><tbody>{body}</tbody></table></div><footer>备注：{html.escape(note)}</footer></article>"
    return {"title": title, "rows": len(data["items"]), "html": preview, "coverage": data["coverage"],
            "coverage_complete": data["coverage_complete"], "warnings": data["warnings"], **data["summary"]}


def export_comparison_docx(old: str, new: str, unit: int) -> dict:
    data = compare(old, new, unit)
    require_complete_comparison(data)
    values = [["/" if value is None or value == "" else value for value in row]
              for row in analysis_reporting.comparison_values(data["items"])]
    pages = [values[index:index + 25] for index in range(0, len(values), 25)] or [[]]
    blocks = []
    for page_index, page_rows in enumerate(pages, 1):
        blocks.append(_w_paragraph(f"II-{page_index}/{len(pages)}", "right", False, 14))
        blocks.append(_w_paragraph(f"{unit}号机组反应堆中子通量测量指套管涡流检验结果对比表", "center", True, 24))
        blocks.append(_w_paragraph(f"本次大修（{new}）与历史大修（{old}）的结果对比如下。", "left", False, 17))
        blocks.append(_w_paragraph("表 5　涡流检验结果比对表", "center", True, 17))
        blocks.append(_w_comparison_table(new, old, page_rows))
        if page_index == len(pages):
            blocks.append(_w_paragraph(f"备注：{comparison_note(data['summary'])}", "left", False, 15))
        if page_index < len(pages):
            blocks.append(_w_page_break())
    result = _write_docx(artifact_naming.filename("历次大修对比报告", f"机组{unit}_{old}-{new}", "docx"), blocks, landscape=False)
    return record_file_export("comparison_form", {**result, "rows": len(data["items"]), **data["summary"]}, {
        "outage": new, "old": old, "new": new, "unit": unit, "rows": len(data["items"]),
        "summary": data["summary"], "note": comparison_note(data["summary"]),
        "finding_ids": [row.get("id") for row in data["items"]],
        "source_keys": sorted({str(row.get("source_key") or "") for row in data["items"]} - {""}),
        "rules": data.get("rules") or active_analysis_rules(),
        "warnings": [{"thimble_id": row.get("thimble_id"), "reason": row.get("comparison_note")}
                     for row in data["items"] if row.get("comparison") == "待确认"],
    })


def health_status() -> dict:
    result = {
        "ok": True,
        "service": "thimble-local",
        "version": SERVICE_VERSION,
        "db_path": str(DB_PATH),
        "output_dir": str(EXCEL_DIR),
        "database_exists": DB_PATH.is_file(),
    }
    instance = os.environ.get("THIMBLE_DESKTOP_INSTANCE")
    if instance:
        result["desktop_instance"] = instance
    return result


def documentation_catalog() -> dict:
    docs_root = ROOT / "docs"
    category_rules = [
        ("软件概览", ("使用说明", "readme", "架构", "项目结构", "development")),
        ("数据导入", ("导入", "解析", "台账", "excel", "rpt")),
        ("状态处理", ("管状态", "移位", "堵管", "换管", "维护")),
        ("数据可视化", ("可视化", "图表", "管板")),
        ("三维模型", ("三维", "3d-visualization")),
        ("报告中心", ("报告", "导出")),
        ("数据安全", ("备份", "恢复", "数据库", "安全", "审计", "删除")),
        ("业务规则", ("业务", "依据", "追溯", "口径", "规则", "基线")),
    ]
    category_descriptions = {
        "软件概览": "软件用途、运行方式与系统组成",
        "数据导入": "检测数据来源、解析、字段映射和导入校验",
        "状态处理": "正常、堵管、移位、换管及批量维护规则",
        "数据可视化": "统计口径、筛选联动、趋势和管板展示",
        "三维模型": "模型依据、检查数据和三维交互说明",
        "报告中心": "报告模板、范围筛选、预览编辑和导出校验",
        "数据安全": "本地数据库、备份、恢复、删除和审计",
        "业务规则": "业务口径、规则版本和参考来源追溯",
        "项目记录": "功能验收、回归测试和阶段优化记录",
    }
    category_names = [name for name, _ in category_rules] + ["项目记录"]
    items = []
    if not docs_root.is_dir():
        return {"items": items}
    for path in sorted(docs_root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file() or path.suffix.lower() not in {".md", ".docx", ".pdf", ".ppt", ".pptx", ".xlsx"}:
            continue
        relative_path = path.relative_to(docs_root)
        if any(part.startswith(".") for part in relative_path.parts):
            continue
        name = path.stem
        normalized = name.casefold()
        category = next((label for label, keywords in category_rules
                         if any(keyword.casefold() in normalized for keyword in keywords)), "软件概览")
        if category == "软件概览" and not any(
            keyword.casefold() in normalized
            for keyword in ("使用说明", "readme", "架构", "项目结构", "development")
        ):
            category = "项目记录"
        kind = {".md": "MD", ".docx": "DOCX", ".pdf": "PDF", ".ppt": "PPT",
                ".pptx": "PPTX", ".xlsx": "XLSX"}[path.suffix.lower()]
        items.append({
            "category": category,
            "title": re.sub(r"[_-]20\d{2}.*$", "", name).replace("_", " ").strip(),
            "file": relative_path.as_posix(),
            "type": kind,
            "desc": category_descriptions[category],
        })
    return {"categories": category_names, "items": items}


def validate_state_payload(data: dict) -> tuple[str, int, int, str, float | None, str]:
    outage = str(data.get("outage", "")).strip().upper()
    unit = number(data.get("unit_id"), int)
    thimble = number(data.get("thimble_id"), int)
    for name in ("unit_id", "thimble_id"):
        try:
            if not float(data.get(name)).is_integer():
                raise ValueError()
        except (TypeError, ValueError):
            raise ValueError("机组号与通道编号必须是整数")
    raw_state = str(data.get("state", "")).strip().lower()
    state = {"正常":"normal","堵管":"plugged","封堵":"plugged","封管":"plugged","换管":"replaced","更换":"replaced","替换":"replaced","移位":"shifted","割管":"shifted","切管":"shifted","割管移位":"shifted","切管移位":"shifted","位移":"shifted"}.get(raw_state, raw_state)
    raw_offset = data.get("offset_mm")
    offset = number(raw_offset, float) if raw_offset not in (None, "") else None
    note = str(data.get("note") or "")
    if not re.fullmatch(r"[A-Z]{1,2}\d{3}", outage):
        raise ValueError("大修编号格式应为基地字母加三位数字")
    if not unit or unit < 1 or thimble is None or thimble < 1 or thimble > 50:
        raise ValueError("机组号或套管号无效")
    if analysis_reporting.sequence(outage)[1] != unit:
        raise ValueError("机组号与大修编号不一致")
    if state not in {"normal", "plugged", "replaced", "shifted"}:
        raise ValueError("管状态无效")
    if raw_offset not in (None, "") and (offset is None or not analysis_reporting.numeric(offset)):
        raise ValueError("位移量无效")
    names, _ = tube_lifecycle.validate(data, state)
    if "shifted" not in names and offset is None:
        offset = 0.0
    if offset is not None and (not analysis_reporting.numeric(offset) or offset < -1000 or offset > 1000):
        raise ValueError("位移量应在 -1000 至 1000 mm 之间，正负方向必须按外部记录填写")
    raw_unsigned = data.get("unsigned_offset_mm")
    unsigned = number(raw_unsigned, float) if raw_unsigned not in (None, "") else None
    if raw_unsigned not in (None, "") and (unsigned is None or not analysis_reporting.numeric(unsigned)):
        raise ValueError("未确认方向的移位距离无效")
    if unsigned is not None and not 0 <= unsigned <= 1000:
        raise ValueError("未确认方向的移位距离应在 0 至 1000 mm 之间")
    return outage, unit, thimble, state, offset, note


def save_tube_state(data, revoke=False, connection=None):
    if revoke:
        data = {**data, "state": "normal", "events": [], "offset_mm": 0, "unsigned_offset_mm": None}
    outage, unit, thimble, state, offset, note = validate_state_payload(data)
    names, stage = tube_lifecycle.validate(data, state)
    state = tube_lifecycle.projection(names)
    scope = (outage, unit, thimble)
    from contextlib import nullcontext
    with nullcontext(connection) if connection is not None else connect() as db:
        if connection is None:
            db.execute("BEGIN IMMEDIATE")
        if "shifted" in names and offset is None and data.get("unsigned_offset_mm") not in (None, ""):
            offset, _ = state_preferences.resolve(number(data["unsigned_offset_mm"], float),
                                                  state_preferences.direction(sys.modules[__name__], db))
        row = db.execute("SELECT * FROM tube_states WHERE outage=? AND unit_id=? AND thimble_id=?", scope).fetchone()
        before = dict(row) if row else None
        tube_lifecycle.check_expected(before, data)
        if not revoke and before and not before["is_deleted"] and (
                "plugged" in tube_lifecycle.events(before) and
                "plugged" not in names and "replaced" not in names):
            raise ValueError("堵管不能通过编辑为其他状态解除；请保留堵管事件或记录换管。原记录有误时请撤销并保留纠错审计")
        source = str(data.get("source") or "") if "source" in data else (row["source"] if row else "")
        if revoke:
            if not row or row["is_deleted"]:
                raise ValueError("该管状态已撤销或不存在，请刷新")
            db.execute("UPDATE tube_states SET is_deleted=1,deleted_at=? WHERE outage=? AND unit_id=? AND thimble_id=?",
                       (datetime.now().isoformat(timespec="seconds"), *scope))
        else:
            db.execute("""INSERT INTO tube_states(outage,unit_id,thimble_id,state,offset_mm,note,source,offset_confirmed,unsigned_offset_mm,events_json,replacement_stage)
                VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(outage,unit_id,thimble_id) DO UPDATE SET
                state=excluded.state,offset_mm=excluded.offset_mm,note=excluded.note,source=excluded.source,
                events_json=excluded.events_json,replacement_stage=excluded.replacement_stage,
                offset_confirmed=excluded.offset_confirmed,unsigned_offset_mm=excluded.unsigned_offset_mm,
                is_deleted=0,deleted_at=NULL,delete_batch_id=NULL""",
                (*scope, state, offset if offset is not None else 0, note, source, int(offset is not None),
                (number(data.get("unsigned_offset_mm"), float)
                 if data.get("unsigned_offset_mm") not in (None, "") else None)
                if "shifted" in names and offset is None else None, json.dumps(names), stage))
        db.execute("UPDATE tube_states SET updated_at=? WHERE outage=? AND unit_id=? AND thimble_id=?",
                   (datetime.now().isoformat(timespec="microseconds"), *scope))
        after = dict(db.execute("SELECT * FROM tube_states WHERE outage=? AND unit_id=? AND thimble_id=?", scope).fetchone())
        audit_id = db.execute("""INSERT INTO tube_state_history(
            outage,unit_id,thimble_id,action,before_json,after_json,operator,created_at
        ) VALUES(?,?,?,?,?,?,?,?)""", (
            *scope, "revoke" if revoke else "create" if not before or before["is_deleted"] else "update",
            json.dumps(before, ensure_ascii=False) if before else None,
            json.dumps(after, ensure_ascii=False), local_security.actor(),
            datetime.now().isoformat(timespec="seconds"),
        )).lastrowid
        lifecycle_rows = [dict(item) for item in db.execute(
            "SELECT * FROM tube_states WHERE unit_id=? AND thimble_id=? AND is_deleted=0",
            (unit, thimble)).fetchall()]
        effective = tube_lifecycle.effective(lifecycle_rows, outage, unit, thimble)
    return {"ok": True, "audit_id": audit_id, "effective": effective, "warnings": effective["warnings"]}


def tube_state_history(params):
    where, args = [], []
    for key in ("outage", "unit_id", "thimble_id"):
        value_ = params.get(key, [""])[0]
        if value_ != "":
            where.append(f"{key}=?")
            args.append(value_)
    site = str(params.get("site", [""])[0]).upper()
    if site:
        where.append(analysis_reporting.site_prefix_sql() + "=?")
        args.append(site)
    with connect() as db:
        rows = db.execute("SELECT * FROM tube_state_history" +
                          (" WHERE " + " AND ".join(where) if where else "") +
                          " ORDER BY id DESC LIMIT 200", args).fetchall()
        timeline = []
        unit = int(params.get("unit_id", ["0"])[0])
        tube = int(params.get("thimble_id", ["0"])[0])
        if site and unit and tube:
            records = [dict(row) for row in db.execute(
                "SELECT * FROM tube_states WHERE unit_id=? AND thimble_id=? AND is_deleted=0",
                (unit, tube)) if tube_lifecycle.scope_key(row["outage"])[0] ==
                tube_lifecycle.ALIASES.get(site, site)]
            for record in sorted(records, key=lambda row: tube_lifecycle.scope_key(row["outage"])[2]):
                timeline.append({**tube_lifecycle.public(record),
                                 "effective": tube_lifecycle.effective(records, record["outage"], unit, tube)})
    return {"items": [dict(row) for row in rows], "timeline": timeline}


def tube_state_scope(params):
    outage = str(params.get("outage", [""])[0]).upper()
    unit = int(params.get("unit_id", ["0"])[0])
    validate_state_payload(dict(outage=outage, unit_id=unit, thimble_id=1, state="normal"))
    with connect() as db:
        db.execute("BEGIN")
        history = tube_lifecycle.StateHistory(tube_lifecycle.rows(db))
        token = tube_lifecycle.revision(db)
    include_maintenance = str(params.get("details", [""])[0]).lower() == "maintenance"
    items = []
    for tube in range(1, 51):
        effective = history.effective(outage, unit, tube)
        current = history.get(outage, unit, tube)
        current_events = tube_lifecycle.events(current) if current else []
        has_shift = "shifted" in current_events
        # The effective projection exposes cumulative movement for analysis.
        # Batch editing needs the distance recorded by this outage itself so
        # two selected tubes are never mistaken as sharing one distance.
        current_confirmed = (current.get("offset_confirmed", 1) if current else 1)
        current_offset = (current.get("offset_mm") if has_shift and current_confirmed != 0 else None)
        current_unsigned = (current.get("unsigned_offset_mm") if has_shift and current_confirmed == 0 else None)
        item = {"thimble_id": tube, **effective}
        if include_maintenance:
            item.update({
                "maintenance_offset_mm": current_offset,
                "maintenance_unsigned_offset_mm": current_unsigned,
                "maintenance_offset_confirmed": int(current_confirmed) if current else None,
            })
        items.append(item)
    return {"revision": token, "items": items}

def validation_summary(limit: int = 200) -> dict:
    with connect() as db:
        rows = [dict(row) for row in db.execute("SELECT * FROM validation_issues WHERE is_deleted=0 ORDER BY id DESC LIMIT ?", (max(1, min(limit, 500)),)).fetchall()]
        counts = {row["severity"]: row["count"] for row in db.execute("""SELECT severity,COUNT(*) count FROM validation_issues v
            LEFT JOIN import_batches b ON b.id=v.batch_id WHERE v.resolved_at IS NULL AND v.is_deleted=0
            AND COALESCE(b.status,'completed')='completed' AND COALESCE(b.is_deleted,0)=0 GROUP BY severity""")}
        total = db.execute("SELECT COUNT(*) FROM validation_issues WHERE is_deleted=0").fetchone()[0]
    return {"items": rows, "open": counts, "count": total}

def import_batch_summary(limit: int = 50) -> dict:
    with connect() as db:
        rows = [dict(row) for row in db.execute("SELECT * FROM import_batches ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
    return {"items": rows, "count": len(rows)}

# ============================================================
# 数据删除与回收 / 统计分析 - 扩展 API
# ============================================================

def _backup_dir():
    d = DB_PATH.parent / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _gen_batch_id():
    return "del_" + datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]


def _auto_backup(label="delete"):
    return create_database_backup(note="操作前自动备份", kind="auto:"+label)["path"]


def _startup_backup_due() -> bool:
    """Avoid copying the whole business database on every ordinary launch."""
    if os.environ.get("THIMBLE_FORCE_STARTUP_BACKUP") == "1":
        return True
    try:
        with connect() as db:
            row = db.execute(
                "SELECT path, created_at FROM restore_points "
                "WHERE kind='auto:startup' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if not row:
            return True
        backup = Path(row["path"]).resolve()
        if not backup.is_file():
            return True
        created = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - created).total_seconds()
        return age >= 24 * 60 * 60
    except (OSError, ValueError, sqlite3.Error, TypeError, KeyError):
        # A missing/corrupt registry must never suppress the safety backup.
        return True


REQUIRED_BACKUP_TABLES = ("findings", "tube_states", "report_exports", "analysis_rules")


def _sqlite_backup_to(source_path, target_path) -> None:
    """经 SQLite 在线备份 API 拷贝数据库。库为 WAL 模式，直接复制主文件会丢数据，必须走此通道。"""
    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(f"file:{Path(source_path)}?mode=ro", uri=True)
    try:
        target = sqlite3.connect(target_path)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def create_database_backup(note: str = "", target: str = "", kind: str = "") -> dict:
    return backup_service.create(sys.modules[__name__], note, target, kind)


def list_database_backups() -> dict:
    """合并恢复点记录与 backups 目录既有文件（含删除/去重前的自动备份），按时间倒序。"""
    with connect() as db:
        recorded = {str(row["path"]): dict(row) for row in db.execute("SELECT * FROM restore_points ORDER BY id DESC")}
        current = dict(db.execute("SELECT COUNT(*) findings, COUNT(DISTINCT outage) outages FROM findings WHERE is_deleted=0").fetchone())
    items, seen = [], set()
    for path in sorted(_backup_dir().glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True):
        key = str(path)
        seen.add(key)
        record = recorded.get(key)
        stat = path.stat()
        items.append({
            "name": path.name, "path": key, "size_bytes": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            "kind": record["kind"] if record else "legacy",
            "sha256": record["sha256"] if record else "",
            "note": record["note"] if record else "",
            "recorded": bool(record),
        })
    for path, record in recorded.items():
        if path in seen or not Path(path).is_file():
            continue
        items.append({"name": Path(path).name, "path": path, "size_bytes": record["size_bytes"],
                      "created_at": record["created_at"], "kind": record["kind"],
                      "sha256": record["sha256"], "note": record["note"], "recorded": True})
    for item in items:
        item["kind_label"] = backup_service.kind_label(item["kind"])
    items.sort(key=lambda item: item["created_at"], reverse=True)
    return {"dir": str(_backup_dir()), "items": items, "current": current,
            "db_size_bytes": DB_PATH.stat().st_size if DB_PATH.is_file() else 0}


def validate_backup_file(path: str) -> dict:
    return backup_service.validate(sys.modules[__name__], path)


def restore_database(path: str) -> dict:
    return backup_service.restore(sys.modules[__name__], path)


def _log_operation(op_type, scope, detail="", count=0, batch_id=None, backup_file=None, note="", connection=None):
    if connection is None:
        with connect() as db:
            return _log_operation(op_type,scope,detail,count,batch_id,backup_file,note,connection=db)
    connection.execute(
        "INSERT INTO operation_logs(operation_type,scope,scope_detail,record_count,operator,created_at,delete_batch_id,backup_file,note) VALUES(?,?,?,?,?,?,?,?,?)",
        (op_type,scope,detail,count,local_security.actor(),schema_migrations.utcnow(),batch_id,backup_file,note))


def _site_name_from_code(code):
    if not code:
        return ""
    for name, c in STATION_CODES.items():
        if c == code:
            return name
    return code


def _scope_label(scope, data):
    labels = {
        "finding": f"单条记录 #{data.get('findingId', '')}",
        "selected": f"选中 {len(data.get('findingIds', []))} 条",
        "tube_outage": f"{data.get('tubeNumber', '')} 号管 · {data.get('outageName', '')}",
        "tube_all": f"{data.get('tubeNumber', '')} 号管 · 全部历史",
        "outage": f"{data.get('outageName', '')}",
        "unit": f"{_site_name_from_code(data.get('siteCode', ''))} {data.get('unitName', '')}",
        "site": f"{_site_name_from_code(data.get('siteCode', ''))} · 检测记录",
        "all": "全库检测记录",
    }
    return labels.get(scope, scope)


def api_delete_preview(body):
    scope = body.get("scope", "")
    if scope not in {"finding","selected","tube_outage","tube_all","outage","unit","site","all"}:
        raise ValueError("删除范围无效")
    data = body.get("data", {}) or {}
    if scope == "tube_all" and not str(data.get("siteCode", "")).strip():
        raise ValueError("删除单管全部历史前请选择基地")
    preview = {
        "scope": scope,
        "findings": 0,
        "tube_states": 0,
        "report_versions": 0,
        "import_batches": 0,
        "validation_issues": 0,
        "affected_tables": [],
        "risk_level": "low",
        "risk_label": "低风险",
    }
    with connect() as db:
        if scope == "finding":
            row = db.execute("SELECT COUNT(*) c FROM findings WHERE id=? AND is_deleted=0", (data.get("findingId", 0),)).fetchone()
            preview["findings"] = row["c"]
            preview["risk_level"] = "low"
            preview["risk_label"] = "低风险"

        elif scope == "selected":
            ids = data.get("findingIds", []) or []
            if ids:
                placeholders = ",".join(["?"] * len(ids))
                row = db.execute(f"SELECT COUNT(*) c FROM findings WHERE id IN ({placeholders}) AND is_deleted=0", ids).fetchone()
                preview["findings"] = row["c"]
            preview["risk_level"] = "medium"
            preview["risk_label"] = "中风险"

        elif scope == "tube_outage":
            row = db.execute(
                "SELECT COUNT(*) c FROM findings WHERE outage=? AND unit_id=? AND thimble_id=? AND is_deleted=0",
                (data.get("outage", ""), data.get("unitId", 0), data.get("tubeId", 0)),
            ).fetchone()
            preview["findings"] = row["c"]
            preview["risk_level"] = "medium"
            preview["risk_label"] = "中风险"

        elif scope == "tube_all":
            row = db.execute(
                f"SELECT COUNT(*) c FROM findings WHERE unit_id=? AND thimble_id=? AND is_deleted=0 AND {analysis_reporting.site_prefix_sql()}=?",
                (data.get("unitId", 0), data.get("tubeId", 0), data["siteCode"]),
            ).fetchone()
            preview["findings"] = row["c"]
            row2 = db.execute(
                f"SELECT COUNT(*) c FROM tube_states WHERE unit_id=? AND thimble_id=? AND is_deleted=0 AND {analysis_reporting.site_prefix_sql()}=?",
                (data.get("unitId", 0), data.get("tubeId", 0), data["siteCode"]),
            ).fetchone()
            preview["tube_states"] = row2["c"]
            preview["risk_level"] = "medium"
            preview["risk_label"] = "中风险"

        elif scope == "outage":
            outage = data.get("outage", "")
            for tbl in ["findings", "tube_states", "import_batches"]:
                row = db.execute(f"SELECT COUNT(*) c FROM {tbl} WHERE outage=? AND is_deleted=0", (outage,)).fetchone()
                preview[tbl] = row["c"]
                preview["validation_issues"] = 0
            preview["risk_level"] = "high"
            preview["risk_label"] = "高风险"

        elif scope == "unit":
            site = data.get("siteCode", "")
            unit = data.get("unitId", 0)
            preview["findings"] = db.execute(
                f"SELECT COUNT(*) FROM findings WHERE is_deleted=0 AND {analysis_reporting.site_prefix_sql()}=? AND unit_id=?",
                (site, unit)).fetchone()[0]
            preview["risk_level"] = "veryhigh"
            preview["risk_label"] = "很高风险"

        elif scope == "site":
            site = data.get("siteCode", "")
            outages = [r["outage"] for r in db.execute(
                f"SELECT DISTINCT outage FROM findings WHERE is_deleted=0 AND {analysis_reporting.site_prefix_sql()}=?", (site,)
            ).fetchall()]
            if outages:
                ph = ",".join(["?"] * len(outages))
                for tbl in ["findings"]:
                    row = db.execute(f"SELECT COUNT(*) c FROM {tbl} WHERE outage IN ({ph}) AND is_deleted=0", outages).fetchone()
                    preview[tbl] = row["c"]
            preview["risk_level"] = "extreme"
            preview["risk_label"] = "极高风险"

        elif scope == "all":
            for tbl in ["findings"]:
                row = db.execute(f"SELECT COUNT(*) c FROM {tbl} WHERE is_deleted=0").fetchone()
                preview[tbl] = row["c"]
            preview["risk_level"] = "extreme"
            preview["risk_label"] = "极高风险"

    for t in ["findings", "tube_states", "report_versions", "import_batches", "validation_issues"]:
        if preview.get(t, 0) > 0:
            preview["affected_tables"].append(t)
    preview["total_records"] = sum(preview.get(t, 0) for t in
        ["findings", "tube_states", "report_versions", "import_batches", "validation_issues"])
    return preview


def _do_soft_delete(scope, data, batch_id, connection=None):
    if connection is None:
        with connect() as db:
            return _do_soft_delete(scope,data,batch_id,connection=db)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    count = 0
    db = connection
    if scope == "finding":
        cur = db.execute(
            "UPDATE findings SET is_deleted=1, deleted_at=?, delete_batch_id=? WHERE id=? AND is_deleted=0",
            (now, batch_id, data.get("findingId", 0)))
        count = cur.rowcount

    elif scope == "selected":
        ids = data.get("findingIds", []) or []
        if ids:
            placeholders = ",".join(["?"] * len(ids))
            params = [now, batch_id] + ids
            cur = db.execute(
                f"UPDATE findings SET is_deleted=1, deleted_at=?, delete_batch_id=? "
                f"WHERE id IN ({placeholders}) AND is_deleted=0", params)
            count = cur.rowcount

    elif scope == "tube_outage":
        cur = db.execute(
            "UPDATE findings SET is_deleted=1, deleted_at=?, delete_batch_id=? "
            "WHERE outage=? AND unit_id=? AND thimble_id=? AND is_deleted=0",
            (now, batch_id, data.get("outage", ""), data.get("unitId", 0), data.get("tubeId", 0)))
        count = cur.rowcount

    elif scope == "tube_all":
        if not str(data.get("siteCode", "")).strip():
            raise ValueError("删除单管全部历史前请选择基地")
        cur = db.execute(
            "UPDATE findings SET is_deleted=1, deleted_at=?, delete_batch_id=? "
            f"WHERE unit_id=? AND thimble_id=? AND is_deleted=0 AND {analysis_reporting.site_prefix_sql()}=?",
            (now, batch_id, data.get("unitId", 0), data.get("tubeId", 0), data["siteCode"]))
        count = cur.rowcount
        state_cursor = db.execute(
            "UPDATE tube_states SET is_deleted=1, deleted_at=?, delete_batch_id=? "
            f"WHERE unit_id=? AND thimble_id=? AND is_deleted=0 AND {analysis_reporting.site_prefix_sql()}=?",
            (now, batch_id, data.get("unitId", 0), data.get("tubeId", 0), data["siteCode"]))
        count += state_cursor.rowcount

    elif scope == "outage":
        outage = data.get("outage", "")
        cur = db.execute(
            "UPDATE findings SET is_deleted=1, deleted_at=?, delete_batch_id=? WHERE outage=? AND is_deleted=0",
            (now, batch_id, outage))
        count += cur.rowcount
        cur2 = db.execute(
            "UPDATE tube_states SET is_deleted=1, deleted_at=?, delete_batch_id=? WHERE outage=? AND is_deleted=0",
            (now, batch_id, outage))
        count += cur2.rowcount
        cur3 = db.execute(
            "UPDATE import_batches SET is_deleted=1, deleted_at=?,delete_batch_id=? WHERE outage=? AND is_deleted=0",
            (now, batch_id, outage))
        count += cur3.rowcount

    elif scope == "unit":
        site = data.get("siteCode", "")
        unit = data.get("unitId", 0)
        cur = db.execute(
            "UPDATE findings SET is_deleted=1, deleted_at=?, delete_batch_id=? "
            f"WHERE {analysis_reporting.site_prefix_sql()}=? AND unit_id=? AND is_deleted=0",
            (now, batch_id, site, unit))
        count += cur.rowcount

    elif scope == "site":
        site = data.get("siteCode", "")
        outages = [r["outage"] for r in db.execute(
            f"SELECT DISTINCT outage FROM findings WHERE {analysis_reporting.site_prefix_sql()}=? AND is_deleted=0",
            (site,)).fetchall()]
        for o in outages:
            cur = db.execute(
                "UPDATE findings SET is_deleted=1, deleted_at=?, delete_batch_id=? WHERE outage=? AND is_deleted=0",
                (now, batch_id, o))
            count += cur.rowcount

    elif scope == "all":
        cur = db.execute(
            "UPDATE findings SET is_deleted=1, deleted_at=?, delete_batch_id=? WHERE is_deleted=0",
            (now, batch_id))
        count += cur.rowcount
    return count


def api_data_delete(body):
    scope = body.get("scope", "")
    if scope not in {"finding","selected","tube_outage","tube_all","outage","unit","site","all"}:
        raise ValueError("删除范围无效")
    data = body.get("data", {}) or {}
    batch_id = _gen_batch_id()
    backup_file = _auto_backup(scope)
    label = _scope_label(scope,data)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        count = _do_soft_delete(scope,data,batch_id,connection=db)
        db.execute("UPDATE findings SET deleted_by=? WHERE delete_batch_id=?", (local_security.actor(),batch_id))
        db.execute("INSERT INTO delete_batches(id,scope,scope_label,detail_json,record_count,deleted_at,deleted_by,backup_file) VALUES(?,?,?,?,?,?,?,?)",
                   (batch_id,scope,label,json.dumps(data,ensure_ascii=False),count,schema_migrations.utcnow(),local_security.actor(),backup_file))
        _log_operation("soft_delete",scope,label,count,batch_id=batch_id,backup_file=backup_file,connection=db)
    return {"deletedCount":count,"batchId":batch_id,"hardDelete":False,"backupFile":backup_file}


def api_recycle_list(page, size):
    page, size = max(1, int(page)), max(1, min(200, int(size)))
    offset = (page - 1) * size
    with connect() as db:
        rows = [dict(r) for r in db.execute(
            "SELECT * FROM delete_batches WHERE is_restored=0 ORDER BY deleted_at DESC LIMIT ? OFFSET ?",
            (size, offset)).fetchall()]
        total = db.execute("SELECT COUNT(*) c FROM delete_batches WHERE is_restored=0").fetchone()["c"]
    return {"items": rows, "total": total, "page": page, "size": size}


def api_operation_logs(page=1, size=50):
    page, size = max(1, int(page)), max(1, min(200, int(size)))
    with connect() as db:
        total = db.execute("SELECT COUNT(*) FROM operation_logs").fetchone()[0]
        rows = [dict(row) for row in db.execute(
            "SELECT * FROM operation_logs ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (size, (page - 1) * size)).fetchall()]
    return {"items": rows, "total": total, "page": page, "size": size}


def api_recycle_restore(batch_id):
    if not batch_id:
        raise ValueError("缺少批次号")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        batch = db.execute("SELECT * FROM delete_batches WHERE id=?", (batch_id,)).fetchone()
        if not batch:
            raise ValueError("批次不存在")
        if batch["is_restored"]:
            return {"restoredCount": 0, "batchId": batch_id, "alreadyRestored": True}
        count = 0
        for table in ("findings", "tube_states", "import_batches"):
            count += db.execute(
                f"UPDATE {table} SET is_deleted=0, deleted_at=NULL, delete_batch_id=NULL "
                "WHERE delete_batch_id=? AND is_deleted=1", (batch_id,)).rowcount

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.execute("UPDATE delete_batches SET is_restored=1, restored_at=? WHERE id=?", (now, batch_id))

        _log_operation("restore", batch["scope"], batch["scope_label"],
                       count, batch_id=batch_id, connection=db)
    return {"restoredCount": count, "batchId": batch_id, "alreadyRestored": False}


def api_recycle_purge(batch_id):
    if not batch_id:
        raise ValueError("缺少批次号")
    _auto_backup("purge")
    count = 0
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        batch = db.execute("SELECT * FROM delete_batches WHERE id=?", (batch_id,)).fetchone()
        if not batch:
            raise ValueError("批次不存在")
        if batch["is_restored"]:
            raise ValueError("该批次已恢复，不能从回收站彻底删除")
        cur = db.execute("DELETE FROM findings WHERE delete_batch_id=?", (batch_id,))
        count += cur.rowcount
        count += db.execute("DELETE FROM tube_states WHERE delete_batch_id=?", (batch_id,)).rowcount
        count += db.execute("DELETE FROM import_batches WHERE delete_batch_id=?", (batch_id,)).rowcount
        db.execute("DELETE FROM delete_batches WHERE id=?", (batch_id,))

        _log_operation("purge", batch["scope"], batch["scope_label"], count, batch_id=batch_id, connection=db)
    return {"purgedCount": count}


# ============================================================
# 统计分析 - 真实数据 API
# ============================================================

def api_analytics_summary(site=None):
    where = ["f.is_deleted=0"]
    params = []
    if site and site != "all":
        where.append(analysis_reporting.site_prefix_sql('f.outage') + "=?")
        params.append(site)
    wsql = " AND ".join(where)

    with connect() as db:
        row = db.execute(f"""
            SELECT COUNT(DISTINCT f.unit_id || '-' || f.thimble_id) tubes,
                   COUNT(*) findings,
                   COUNT(DISTINCT f.outage) outages,
                   MAX(f.percent) max_percent
            FROM statistical_findings f
            WHERE f.is_deleted=0 AND {wsql} AND f.percent IS NOT NULL
        """, params).fetchone()

        units = db.execute(f"""
            SELECT COUNT(DISTINCT unit_id) u FROM statistical_findings WHERE is_deleted=0
            {(f"AND {analysis_reporting.site_prefix_sql()}=?") if site and site != "all" else ""}
        """, params if site and site != "all" else []).fetchone()

        active_outages = db.execute(f"""
            SELECT COUNT(DISTINCT f.outage) c
            FROM statistical_findings f
            WHERE f.is_deleted=0
              AND f.imported_at >= datetime('now', '-30 days')
            {(f"AND {analysis_reporting.site_prefix_sql('f.outage')}=?") if site and site != "all" else ""}
        """, params if site and site != "all" else []).fetchone()

        top_tube = db.execute(f"""
            SELECT f.outage, f.unit_id, f.thimble_id, f.position, f.percent, f.indication,
                   {analysis_reporting.site_prefix_sql('f.outage')} site_code
            FROM statistical_findings f
            WHERE f.is_deleted=0 AND {wsql} AND f.percent IS NOT NULL
            ORDER BY f.percent DESC
            LIMIT 1
        """, params).fetchone()

        site_name = _site_name_from_code(top_tube["site_code"]) if top_tube else ""

    return {
        "totalTubes": row["tubes"] or 0,
        "activeDefects": row["findings"] or 0,
        "runningUnits": units["u"] or 0,
        "activeOutages": active_outages["c"] or 0,
        "maxWear": round(row["max_percent"] or 0, 1),
        "topTube": {
            "tubeNumber": top_tube["thimble_id"] if top_tube else None,
            "position": top_tube["position"] if top_tube else None,
            "unitId": top_tube["unit_id"] if top_tube else None,
            "outage": top_tube["outage"] if top_tube else None,
            "siteCode": top_tube["site_code"] if top_tube else None,
            "siteName": site_name,
            "wearDepth": round(top_tube["percent"] or 0, 1) if top_tube else 0,
        } if top_tube else None,
    }


def api_analytics_bases():
    """各基地统计数据，用于地图展示"""
    with connect() as db:
        rows = [dict(r) for r in db.execute(f"""
            SELECT
                {analysis_reporting.site_prefix_sql()} as site_code,
                COUNT(DISTINCT unit_id) as unit_count,
                COUNT(DISTINCT unit_id || '-' || thimble_id) as tube_count,
                COUNT(*) as finding_count
            FROM statistical_findings
            WHERE is_deleted=0
            GROUP BY site_code
            ORDER BY site_code
        """).fetchall()]

    # 坐标映射
    coords = {
        "D": {"x": 0.78, "y": 0.68, "name": "大亚湾"},
        "L": {"x": 0.775, "y": 0.695, "name": "岭澳"},
        "Y": {"x": 0.76, "y": 0.72, "name": "阳江"},
        "H": {"x": 0.72, "y": 0.18, "name": "红沿河"},
        "F": {"x": 0.66, "y": 0.78, "name": "防城港"},
        "N": {"x": 0.83, "y": 0.52, "name": "宁德"},
        "T": {"x": 0.75, "y": 0.70, "name": "台山"},
        "LF": {"x": 0.752, "y": 0.712, "name": "陆丰"},
        "C": {"x": 0.815, "y": 0.5, "name": "苍南"},
        "P": {"x": 0.76, "y": 0.685, "name": "惠州"},
    }

    bases = []
    for r in rows:
        code = r["site_code"] or ""
        c = coords.get(code, {"x": 0.5, "y": 0.5, "name": code})
        bases.append({
            "code": code,
            "name": c["name"],
            "unitCount": r["unit_count"] or 0,
            "tubeCount": r["tube_count"] or 0,
            "findingCount": r["finding_count"] or 0,
            "x": c["x"],
            "y": c["y"],
            "status": "running",
        })
    return bases


def api_analytics_group_trend(site=None):
    where = ["f.is_deleted=0", "f.percent IS NOT NULL"]
    params = []
    if site and site != "all":
        where.append(analysis_reporting.site_prefix_sql('f.outage') + "=?")
        params.append(site)
    wsql = " AND ".join(where)

    with connect() as db:
        rows = [dict(r) for r in db.execute(f"""
            SELECT
                {analysis_reporting.site_prefix_sql('f.outage')} as site_code,
                f.unit_id,
                f.outage,
                AVG(f.percent) as avg_percent,
                MAX(f.percent) as max_percent,
                COUNT(DISTINCT f.thimble_id) as tube_count,
                COUNT(*) as finding_count
            FROM statistical_findings f
            WHERE f.is_deleted=0 AND {wsql}
            GROUP BY f.outage, f.unit_id
            ORDER BY f.outage ASC, f.unit_id ASC
        """, params).fetchall()]

    if not rows:
        return {"xLabels": [], "series": []}

    outages = sorted(set(r["outage"] for r in rows))
    units_map = {}
    colors = ["#2563eb", "#0891b2", "#059669", "#d97706", "#dc2626",
              "#7c3aed", "#ea580c", "#0284c7", "#65a30d", "#db2777",
              "#0d9488", "#4f46e5", "#e11d48", "#f97316", "#84cc16"]

    idx = 0
    for r in rows:
        key = f"{r['site_code']}-{r['unit_id']}"
        if key not in units_map:
            name = f"{_site_name_from_code(r['site_code'])} {r['unit_id']}号机"
            units_map[key] = {"name": name, "siteCode": r["site_code"], "unitId": r["unit_id"],
                              "color": colors[idx % len(colors)], "points": []}
            idx += 1
        units_map[key]["points"].append({
            "outage": r["outage"],
            "value": round(r["avg_percent"] or 0, 2),
            "maxValue": round(r["max_percent"] or 0, 2),
            "tubeCount": r["tube_count"],
            "findingCount": r["finding_count"],
        })

    return {"xLabels": outages, "series": list(units_map.values())}


def api_analytics_p_position(site=None):
    where = ["f.is_deleted=0", "f.location IS NOT NULL", "f.location <> ''"]
    params = []
    if site and site != "all":
        where.append(analysis_reporting.site_prefix_sql('f.outage') + "=?")
        params.append(site)
    wsql = " AND ".join(where)

    with connect() as db:
        rows = [dict(r) for r in db.execute(f"""
            SELECT
                f.location,
                f.outage,
                COUNT(*) as defect_count,
                AVG(f.percent) as avg_percent
            FROM statistical_findings f
            WHERE f.is_deleted=0 AND {wsql} AND f.percent IS NOT NULL
            GROUP BY f.location, f.outage
            ORDER BY f.outage ASC
        """, params).fetchall()]

    if not rows:
        return {"xLabels": [], "series": []}

    outages = sorted(set(r["outage"] for r in rows))
    p_colors = {"P1": "#ef4444", "P2": "#f97316", "P3": "#eab308", "P4": "#22c55e", "P5": "#3b82f6"}
    p_labels = {"P1": "P1 入口", "P2": "P2 上部", "P3": "P3 中部", "P4": "P4 下部", "P5": "P5 出口"}

    series = []
    for p in ["P1", "P2", "P3", "P4", "P5"]:
        points = []
        for outage in outages:
            matching = [r for r in rows if r["location"].upper().startswith(p) and r["outage"] == outage]
            if matching:
                points.append({
                    "outage": outage,
                    "value": matching[0]["defect_count"],
                    "avgWear": round(matching[0]["avg_percent"] or 0, 2),
                })
            else:
                points.append({"outage": outage, "value": 0, "avgWear": 0})
        if any(pt["value"] > 0 for pt in points):
            series.append({
                "name": p_labels.get(p, p),
                "pPosition": p,
                "color": p_colors.get(p, "#64748b"),
                "points": points,
            })

    return {"xLabels": outages, "series": series}


def api_analytics_tube_status(site=None):
    where = ["ts.is_deleted=0"]
    params = []
    if site and site != "all":
        where.append(analysis_reporting.site_prefix_sql('ts.outage') + "=?")
        params.append(site)
    wsql = " AND ".join(where)

    with connect() as db:
        rows = [dict(r) for r in db.execute(f"""
            SELECT
                {analysis_reporting.site_prefix_sql('ts.outage')} as site_code,
                ts.state,
                COUNT(DISTINCT ts.unit_id || '-' || ts.thimble_id) as cnt
            FROM tube_states ts
            WHERE {wsql}
            GROUP BY site_code, ts.state
            ORDER BY site_code
        """, params).fetchall()]

    bases_map = {}
    for r in rows:
        code = r["site_code"]
        if code not in bases_map:
            bases_map[code] = {"siteCode": code, "siteName": _site_name_from_code(code),
                               "normal": 0, "plugged": 0, "shifted": 0, "replaced": 0}
        state = (r["state"] or "normal").lower()
        if "plug" in state:
            bases_map[code]["plugged"] = r["cnt"]
        elif "shift" in state:
            bases_map[code]["shifted"] = r["cnt"]
        elif "replace" in state:
            bases_map[code]["replaced"] = r["cnt"]
        else:
            bases_map[code]["normal"] = r["cnt"]

    result = []
    for code, data in bases_map.items():
        data["total"] = data["normal"] + data["plugged"] + data["shifted"] + data["replaced"]
        result.append(data)
    return result




class Handler(SimpleHTTPRequestHandler):
    MAX_BODY_BYTES = 8 * 1024 * 1024

    def request_is_local(self) -> bool:
        expected_host = f"127.0.0.1:{self.server.server_port}"
        if self.client_address[0] not in {"127.0.0.1", "::1"}:
            return False
        if self.headers.get("Host", "") != expected_host:
            return False
        origin = self.headers.get("Origin")
        return not origin or origin == f"http://{expected_host}"

    def send_security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")

    def log_message(self, fmt, *args):
        sys.stdout.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def json_response(self, data, status=200):
        try:
            local_security.audit_response(sys.modules[__name__], self, data, status)
        except (sqlite3.Error, OSError):
            if status < 400:
                raise
            LOGGER.exception("Failed to audit error response; retaining original failure")
        if status >= 400:
            task_progress.finish(False)
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_security_headers()
        self.send_header("Cache-Control", "no-store")
        if getattr(self, 'auth_cookie', None):
            self.send_header('Set-Cookie', self.auth_cookie)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length < 0:
            raise ValueError("请求长度无效")
        if length > self.MAX_BODY_BYTES:
            raise ValueError("请求体过大，请分批导入文件")
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(payload, dict):
                raise ValueError("请求数据必须是 JSON 对象")
            return payload
        except json.JSONDecodeError as exc:
            raise ValueError("请求数据格式无效") from exc

    @local_security.http_boundary('GET')
    def do_GET(self):
        if not self.request_is_local():
            return self.json_response({"error": "Forbidden"}, HTTPStatus.FORBIDDEN)
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/health": return self.json_response(health_status())
            if parsed.path == "/api/documentation": return self.json_response(documentation_catalog())
            if parsed.path == "/api/import-progress":
                token = parse_qs(parsed.query).get("id", [""])[0]
                progress = task_progress.snapshot(token)
                return self.json_response(progress or {"status": "pending"})
            if parsed.path == "/api/settings/data-source":
                return self.json_response(data_source.settings(DB_PATH))
            if parsed.path == "/api/settings/state-direction":
                return self.json_response(state_preferences.settings(sys.modules[__name__]))
            if parsed.path == "/api/reports/templates":
                try:
                    from . import reference_report
                except ImportError:
                    import reference_report
                return self.json_response(reference_report.catalog(sys.modules[__name__]))
            if parsed.path == "/api/overview": return self.json_response(overview())
            if parsed.path == "/api/analysis/visualization":
                try:
                    from . import visualization_reporting
                except ImportError:
                    import visualization_reporting
                q = parse_qs(parsed.query)
                return self.json_response(visualization_reporting.build(
                    sys.modules[__name__], {k: v[0] for k, v in q.items()}))
            if parsed.path == "/api/analysis/live":
                q = parse_qs(parsed.query)
                return self.json_response(analysis_reporting.analysis(sys.modules[__name__], {k: v[0] for k, v in q.items()}, rules=active_analysis_rules()))
            if parsed.path == "/api/analysis/tube":
                q = parse_qs(parsed.query)
                site = q.get("site", [""])[0]
                unit = int(q.get("unit", ["0"])[0])
                thimble = int(q.get("thimble", ["0"])[0])
                history = tube_history(site, unit, thimble)
                return self.json_response({
                    "site": site.upper(), "unit": unit, "thimble": thimble,
                    "position": position_for(unit, thimble),
                    "records": history["items"],
                    "states": [row for row in query_states()["items"] if row["unit_id"] == unit and row["thimble_id"] == thimble and (not site or row["outage"].startswith(site.upper()))],
                    "sources": sorted({row.get("report_path") or row.get("filename") or "" for row in history["items"] if row.get("report_path") or row.get("filename")})
                })
            if parsed.path == "/api/duplicates": return self.json_response(duplicate_summary())
            if parsed.path == "/api/analysis-rules":
                return self.json_response({"active": active_analysis_rules(), "items": list_analysis_rules(),
                                           "defaults": analysis_reporting.DEFAULT_RULES})
            if parsed.path == "/api/backup-policy": return self.json_response(backup_service.policy(sys.modules[__name__]))
            if parsed.path == "/api/backups": return self.json_response(list_database_backups())
            if parsed.path == "/api/cross-group-reviews":
                q = parse_qs(parsed.query)
                return self.json_response(cross_group_review.listing(sys.modules[__name__], q.get("batch_id", [""])[0]))
            if parsed.path == "/api/validation-issues": return self.json_response(validation_summary())
            if parsed.path == "/api/import-batches": return self.json_response(import_batch_summary())
            if parsed.path == "/api/data-quality":
                q = parse_qs(parsed.query)
                return self.json_response(import_audit.quality(sys.modules[__name__],
                    int(q["batch_id"][0]) if q.get("batch_id") else None,
                    q.get("category", [""])[0], q.get("page", ["1"])[0], q.get("size", ["50"])[0]))

            if parsed.path == "/api/analytics/summary":
                return self.json_response(api_analytics_summary(parse_qs(parsed.query).get("site", ["all"])[0]))
            if parsed.path == "/api/analytics/bases":
                return self.json_response({"bases": api_analytics_bases()})
            if parsed.path == "/api/analytics/group-trend":
                return self.json_response(api_analytics_group_trend(parse_qs(parsed.query).get("site", ["all"])[0]))
            if parsed.path == "/api/analytics/p-position":
                return self.json_response(api_analytics_p_position(parse_qs(parsed.query).get("site", ["all"])[0]))
            if parsed.path == "/api/analytics/tube-status":
                return self.json_response({"items": api_analytics_tube_status(parse_qs(parsed.query).get("site", ["all"])[0])})
            if parsed.path == "/api/recycle-bin/list":
                q = parse_qs(parsed.query)
                return self.json_response(api_recycle_list(int(q.get("page", ["1"])[0]), int(q.get("size", ["20"])[0])))

            if parsed.path == "/api/operation-logs":
                q = parse_qs(parsed.query)
                return self.json_response(api_operation_logs(q.get("page", ["1"])[0], q.get("size", ["50"])[0]))
            if parsed.path == "/api/logs/recent":
                return self.json_response(recent_service_log(parse_qs(parsed.query).get("limit", ["120"])[0]))
            if parsed.path == "/api/states": return self.json_response(query_states())
            if parsed.path == "/api/states/scope": return self.json_response(tube_state_scope(parse_qs(parsed.query)))
            if parsed.path == "/api/state-history": return self.json_response(tube_state_history(parse_qs(parsed.query)))
            if parsed.path == "/api/findings": return self.json_response(query_findings(parse_qs(parsed.query)))
            if parsed.path == "/api/tube-history":
                q = parse_qs(parsed.query); return self.json_response(tube_history(q.get("site", [""])[0], int(q.get("unit", ["0"])[0]), int(q.get("thimble", ["0"])[0])))
            if parsed.path == "/api/unit-evolution":
                q = parse_qs(parsed.query); return self.json_response(unit_evolution(q.get("site", [""])[0], int(q.get("unit", ["0"])[0])))
            if parsed.path == "/api/analysis/tube-longitudinal":
                q = parse_qs(parsed.query)
                return self.json_response(tube_longitudinal(q.get("site", [""])[0], int(q.get("unit", ["0"])[0]), q.get("jump", [TUBE_LONGITUDINAL_JUMP_DEFAULT])[0]))
            if parsed.path == "/api/compare":
                q = parse_qs(parsed.query)
                if q.get("outages"):
                    return self.json_response(compare_many(q.get("outages", [""])[0].split(","), int(q.get("unit", ["0"])[0])))
                return self.json_response(compare(q.get("old", [""])[0], q.get("new", [""])[0], int(q.get("unit", ["0"])[0])))
            if parsed.path == "/api/export": return self.export_csv(parse_qs(parsed.query))
            if parsed.path == "/api/download-excel": return self.download_excel(parse_qs(parsed.query))
            if parsed.path == "/api/download-report": return self.download_report(parse_qs(parsed.query))
            return self.serve_static(parsed.path)
        except Exception as exc:
            LOGGER.exception("GET %s failed", urlparse(self.path).path)
            self.json_response({"error": str(exc) if isinstance(exc, ValueError) else "本地服务处理失败，请查看日志"}, 400 if isinstance(exc, ValueError) else 500)

    @local_security.http_boundary('POST')
    @task_progress.track_http
    def do_POST(self):
        if not self.request_is_local():
            return self.json_response({"error": "Forbidden"}, HTTPStatus.FORBIDDEN)
        if self.headers.get_content_type() != "application/json":
            return self.json_response({"error": "Content-Type must be application/json"}, HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        path = urlparse(self.path).path
        try:
            data = self.request_data
            if path == "/api/findings/edit":
                return self.json_response(update_finding_field(data))
            if path == "/api/data-ledger/export":
                return self.json_response(export_data_ledger(data))
            if path == "/api/settings/data-source":
                return self.json_response(data_source.save_settings(DB_PATH, data))
            if path == "/api/settings/state-direction":
                return self.json_response(state_preferences.save(sys.modules[__name__], data))
            if path == "/api/settings/data-source/validate":
                return self.json_response(data_source.validate_settings(DB_PATH, data))
            if path == "/api/cross-group-reviews":
                return self.json_response(cross_group_review.save(sys.modules[__name__], data))
            if path == "/api/reports/preview":
                return self.json_response(analysis_reporting.preview(analysis_reporting.report_snapshot(sys.modules[__name__], data, rules=active_analysis_rules()), sys.modules[__name__]))
            if path == "/api/reports/export":
                return self.json_response(analysis_reporting.export(sys.modules[__name__], data, rules=active_analysis_rules()))
            if path == "/api/report-options": return self.json_response({"reports": report_options(data.get("path", ""))})
            if path == "/api/discover-server": return self.json_response(discover_server_sources(data.get("path", "")))
            if path == "/api/import":
                return self.json_response(import_directory(data.get("path", ""), data.get("reports"), data.get("blank_indication_policy", ""), local_security.actor(), report_confirmation=data.get("report_confirmation") or {}))
            if path == "/api/import-excel":
                return self.json_response(import_excel_file(data.get("path", ""), data.get("blank_indication_policy", ""), local_security.actor(), mapping=data.get("mapping") or None))
            if path == "/api/import-excel-inspect":
                return self.json_response(inspect_excel_file(data.get("path", "")))
            if path == "/api/data-quality/export":
                return self.json_response(import_audit.export_quality(sys.modules[__name__],
                    int(data["batch_id"]) if data.get("batch_id") else None, data.get("category", "")))
            if path == "/api/import-batches/action":
                return self.json_response(import_audit.change_batch(sys.modules[__name__], int(data.get("batch_id", 0)), data.get("action", "")))
            if path == "/api/export-indication-warnings": return self.json_response(export_indication_warnings(data.get("items") or []))
            if path == "/api/deduplicate": return self.json_response(deduplicate_database())
            if path == "/api/analysis-rules":
                return self.json_response(create_analysis_rule(data.get("name", ""), data.get("match_tolerance_mm"), data.get("note", "")))
            if path == "/api/backup-policy":
                return self.json_response(backup_service.policy(sys.modules[__name__], data))
            if path == "/api/backup":
                return self.json_response(create_database_backup(data.get("note", ""), data.get("target", "")))
            if path == "/api/backup-validate":
                return self.json_response(validate_backup_file(data.get("path", "")))
            if path == "/api/restore":
                return self.json_response(restore_database(data.get("path", "")))
            if path == "/api/export-comparison":
                outages = data.get("outages") or []
                if len(outages) >= 2:
                    return self.json_response(export_comparison_docx(outages[-2], outages[-1], int(data.get("unit", 0))))
                return self.json_response(export_comparison_docx(data.get("old", ""), data.get("new", ""), int(data.get("unit", 0))))
            if path == "/api/export-evolution": return self.json_response(export_evolution_excel(data.get("site", ""), int(data.get("unit", 0))))
            if path == "/api/export-report": return self.json_response(export_inspection_docx(data.get("outage", ""), int(data.get("unit", 0)), data.get("metadata") or {}, data.get("finding_ids") or []))
            if path == "/api/report-preview":
                if data.get("kind") == "comparison":
                    return self.json_response(build_comparison_preview(data.get("old", ""), data.get("new", ""), int(data.get("unit", 0))))
                return self.json_response(build_inspection_preview(data.get("outage", ""), int(data.get("unit", 0)), data.get("metadata") or {}, data.get("finding_ids") or []))

            if path == "/api/data/delete-preview":
                return self.json_response({"preview": api_delete_preview(data)})
            if path == "/api/data/delete":
                return self.json_response(api_data_delete(data))
            if path == "/api/recycle-bin/restore":
                return self.json_response(api_recycle_restore(data.get("batchId", "")))
            if path == "/api/recycle-bin/purge":
                return self.json_response(api_recycle_purge(data.get("batchId", "")))

            if path == "/api/clear":
                if data.get("confirmed") is not True:
                    return self.json_response({"error": "清空操作必须明确确认"}, 400)
                return self.json_response(clear_database())
            if path == "/api/export-folder-excel":
                return self.json_response(export_directory_excel(data.get("path", ""), data.get("reports"), data.get("report_policy", "manual"), report_confirmation=data.get("report_confirmation") or {}))
            if path == "/api/state":
                return self.json_response(save_tube_state(data))
            if path == "/api/states/scopes":
                return self.json_response(save_tube_state_scope(data))
            if path == "/api/states/dismiss-recognition":
                return self.json_response(inspection_states.dismiss(sys.modules[__name__], data))
            if path in {"/api/states/batch", "/api/states/batch-preview", "/api/states/import-preview", "/api/states/export", "/api/states/delete-batch", "/api/states/recognize-note"}:
                try:
                    from . import state_transfer
                except ImportError:
                    import state_transfer
                handlers = {"/api/states/batch": state_transfer.apply_batch,
                            "/api/states/batch-preview": state_transfer.preview_batch,
                            "/api/states/delete-batch": state_transfer.delete_batch,
                            "/api/states/recognize-note": state_transfer.recognize_note,
                            "/api/states/import-preview": state_transfer.preview,
                            "/api/states/export": state_transfer.export}
                return self.json_response(handlers[path](sys.modules[__name__], data))
            if path == "/api/state-delete":
                return self.json_response(save_tube_state(data, revoke=True))
            self.json_response({"error": "接口不存在"}, 404)
        except local_security.AccessError:
            raise
        except Exception as exc:
            LOGGER.exception("POST %s failed", path)
            if path in {"/api/import", "/api/import-excel", "/api/import-excel-inspect", "/api/report-options", "/api/export-folder-excel"}:
                source = str(data.get("path", "")) if isinstance(locals().get("data"), dict) else ""
                self.json_response(import_error_response(source, exc), 400 if isinstance(exc, ValueError) else 500)
            else:
                self.json_response({"error": str(exc) if isinstance(exc, ValueError) else "本地服务处理失败，请查看日志"}, 400 if isinstance(exc, ValueError) else 500)

    def do_HEAD(self):
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)

    def export_csv(self, params):
        rows = query_all_findings(params)
        output = io.StringIO()
        fields = ["outage","unit_id","thimble_id","position","entry_no","volts","degrees","indication","percent","channel","location","datapoint","analyst","analysis","filename","calgroup","state","offset_mm","note"]
        writer = csv.DictWriter(output, fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)
        payload = b"\xef\xbb\xbf" + output.getvalue().encode("utf-8")
        local_security.export_bytes(sys.modules[__name__], "CSV export", payload)
        self.send_response(200); self.send_header("Content-Type", "text/csv; charset=utf-8"); self.send_header("X-Content-Type-Options", "nosniff")
        scope_parts = []
        for key, label in (("site", ""), ("unit", "号机组"), ("outage", ""), ("thimble", "号管")):
            value = str(params.get(key, [""])[0]).strip()
            if value:
                scope_parts.append(_site_name_from_code(value) if key == "site" else value + label)
        filename = artifact_naming.filename("检测数据", "_".join(scope_parts) or "全部记录", "csv")
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(filename)}")
        self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload)

    def download_excel(self, params):
        name = Path(params.get("name", [""])[0]).name
        target = (EXCEL_DIR / name).resolve()
        if target.parent != EXCEL_DIR.resolve() or not target.is_file():
            return self.send_error(HTTPStatus.NOT_FOUND)
        payload = target.read_bytes()
        local_security.export_bytes(sys.modules[__name__], target.name, payload)
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(name)}")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def download_report(self, params):
        name = Path(params.get("name", [""])[0]).name
        target = (REPORT_DIR / name).resolve()
        if target.parent != REPORT_DIR.resolve() or not target.is_file():
            return self.send_error(HTTPStatus.NOT_FOUND)
        payload = target.read_bytes()
        local_security.export_bytes(sys.modules[__name__], target.name, payload)
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(name)}")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers(); self.wfile.write(payload)

    def serve_static(self, path):
        target = STATIC / ("index.html" if path == "/" else path.lstrip("/"))
        target = target.resolve()
        if STATIC.resolve() not in target.parents and target != STATIC.resolve():
            return self.send_error(HTTPStatus.FORBIDDEN)
        if not target.is_file(): return self.send_error(HTTPStatus.NOT_FOUND)
        payload = target.read_bytes(); self.send_response(200)
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type += "; charset=utf-8"
        self.send_header("Content-Type", content_type)
        self.send_security_headers()
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-src 'self'")
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload)


class LocalHTTPServer(ThreadingHTTPServer):
    # The desktop loads scripts, styles and API data together on startup.
    request_queue_size = 128


def main():
    local_storage.migrate_legacy(sys.modules[__name__])
    init_db()
    if _startup_backup_due():
        _auto_backup("startup")
    else:
        LOGGER.info("skip startup backup: a valid startup snapshot is less than 24 hours old")
    port = int(os.environ.get("THIMBLE_PORT", "18767"))
    server = LocalHTTPServer(("127.0.0.1", port), Handler)
    print(f"在役检查系统-指套管数据管理工具: http://127.0.0.1:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__": main()
