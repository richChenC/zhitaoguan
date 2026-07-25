from __future__ import annotations

import csv
import hashlib
import io
import json
import mimetypes
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DB_PATH = ROOT / "data" / "thimble.db"
EXCEL_DIR = ROOT / "output" / "excel"

ODD_POSITIONS = "L11 G14 N7 H13 J12 R8 N12 N10 L14 J15 H11 F13 J7 L5 N5 L8 N8 L6 J10 L9 F9 C12 G7 L4 J5 M3 G9 E11 F11 D12 F6 B10 D7 E5 H3 J3 H6 H4 F8 D10 B7 B5 D3 D5 F2 H1 B8 F4 C8 A9".split()
EVEN_POSITIONS = "B5 C8 E11 D10 D12 C12 B10 B7 A9 B8 D5 D3 F6 H13 F9 G14 F13 E5 F11 D7 G7 F2 H6 H11 J10 J12 J15 G9 F8 F4 H3 H1 J3 N12 L9 L11 L14 J5 J7 H4 M3 M5 R8 N7 N8 N10 L5 L8 L6 L4".split()

STANDARD_EXCEL_FIELDS = [
    "电站名称", "大修号", "机组号", "安全级别", "设备名称", "被检部位", "通道编号",
    "在堆芯内的位置", "幅值", "相位", "磨损深度", "三字码", "测量通道",
    "磨损位置", "探头类型", "分析人员", "数据", "数据组", "备注", "堵管移位信息"
]
STATION_CODES = {
    "大亚湾": "D", "岭澳": "L", "宁德": "N", "红沿河": "H", "阳江": "Y",
    "防城港": "F", "台山": "T", "太平岭（惠州）": "P", "苍南": "C", "陆丰": "L",
}
STATION_PROJECT_HINTS = (
    ("大亚湾", ("CNPS",)),
    ("岭澳", ("LNPS",)),
    ("红沿河", ("红沿河项目", "LHNP")),
    ("宁德", ("宁德项目", "NDNP")),
    ("阳江", ("阳江项目", "YJNP")),
    ("防城港", ("防城港项目", "BLNP")),
    ("台山", ("台山项目", "TSNP")),
    ("太平岭（惠州）", ("太平岭", "惠州", "HENP")),
    ("苍南", ("苍南项目", "CNMP")),
    ("陆丰", ("陆丰项目", "LFNP")),
    ("外部市场", ("外部市场",)),
)


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


def value(node: ET.Element, name: str) -> str:
    child = node.find(name)
    return (child.text or "").strip() if child is not None else ""


def number(text: str, cast):
    try:
        return cast(text)
    except (TypeError, ValueError):
        return None


def infer_outage(path: Path) -> str:
    for part in reversed(path.parts):
        match = re.search(r"(?<![A-Z0-9])([A-Z]\d{3})(?![A-Z0-9])", part.upper())
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
            if re.fullmatch(r"[A-Z]\d{3}", outage):
                return outage
        except (ET.ParseError, OSError):
            continue
    return "UNKNOWN"


def infer_unit(outage: str, report_id: str) -> int:
    match = re.search(r"[A-Z](\d)", outage)
    return int(match.group(1)) if match else (number(report_id, int) or 0)


def infer_station(path: Path, outage: str = "") -> tuple[str, str]:
    context = "|".join(path.parts).upper()
    for station, hints in STATION_PROJECT_HINTS:
        if any(hint.upper() in context for hint in hints):
            return station, STATION_CODES.get(station, outage[:1])
    code = outage[:1].upper()
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
    match = re.match(r"^\s*(P\d+)\s*(?:\+\s*([-+]?\d+(?:\.\d+)?))?\s*$", location or "", re.I)
    return (match.group(1).upper(), number(match.group(2), float)) if match else ((location or "").strip(), None)


def normalize_header(value_) -> str:
    return re.sub(r"[\s()（）%％/\\_-]+", "", str(value_ or "")).lower()


def outage_from_standard_row(row: dict, source: Path) -> str:
    explicit = str(row.get("大修号") or row.get("大修") or "").strip().upper()
    if re.fullmatch(r"[A-Z]\d{3}", explicit):
        return explicit
    group = str(row.get("数据组") or "").strip().upper()
    match = re.search(r"TH(\d)I(\d{2})", group)
    station = str(row.get("电站名称") or "").strip()
    code = next((value_ for name, value_ in STATION_CODES.items() if name in station), "")
    if match and code:
        return f"{code}{match.group(1)}{match.group(2)}"
    inferred = infer_outage(source)
    return inferred if inferred != "UNKNOWN" else ""


ECT_NAME = re.compile(r"^DIR(\d{3})C(\d{3})I(\d{3})\.ECT$", re.I)


def parse_ect_header(path: Path) -> dict:
    match = ECT_NAME.match(path.name)
    if not match:
        raise ValueError("ECT文件名不符合 DIRrrrCcccIeee.ECT")
    name_row, name_col, name_entry = map(int, match.groups())
    raw = path.read_bytes()[:131072].decode("utf-8", errors="ignore")
    xml_match = re.search(r"<HeaderTube\b.*?</HeaderTube>", raw, re.S)
    if not xml_match:
        raise ValueError("ECT中未找到HeaderTube XML")
    header = ET.fromstring(xml_match.group(0))
    row, col, entry = number(value(header, "Row"), int), number(value(header, "Col"), int), number(value(header, "Entry"), int)
    return {
        "path": str(path), "filename": path.name, "calgroup": path.parent.name,
        "name_row": name_row, "name_col": name_col, "name_entry": name_entry,
        "row": row, "col": col, "entry": entry, "datetime": value(header, "DateTime"),
        "calibration": row in {0, 999} or col in {0, 999},
    }


def scan_thimble_directory(directory: str) -> dict:
    base = Path(directory).expanduser().resolve()
    if not base.is_dir():
        raise ValueError("所选路径不是有效文件夹")
    ect_rows, errors = [], []
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.suffix.lower() != ".ect" or not path.parent.name.upper().startswith("TH"):
            continue
        try:
            item = parse_ect_header(path)
            status = []
            if (item["name_row"], item["name_col"], item["name_entry"]) != (item["row"], item["col"], item["entry"]):
                status.append("文件名与HeaderTube不一致")
            if not item["calibration"] and item["row"] != item["col"]:
                status.append("Row与Column不一致")
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


def parse_report(path: Path) -> list[Finding]:
    root = ET.parse(path).getroot()
    outage = infer_outage(path)
    findings: list[Finding] = []
    for item in root.findall("ReportEntry"):
        thimble_id = number(value(item, "Row"), int)
        if not thimble_id:
            continue
        unit_id = infer_unit(outage, value(item, "Id"))
        findings.append(Finding(
            outage=outage, unit_id=unit_id, thimble_id=thimble_id,
            position=position_for(unit_id, thimble_id),
            entry_no=number(value(item, "Entry"), int),
            volts=number(value(item, "Volts"), float),
            degrees=number(value(item, "Degrees"), float),
            indication=value(item, "Indication"), percent=number(value(item, "Percent"), float),
            channel=value(item, "Channel"), location=value(item, "Location"),
            datapoint=number(value(item, "Datapoint"), int),
            liss_region_size=number(value(item, "LissRegionSize"), int),
            analyst=value(item, "Analyst"), analysis=value(item, "Analysis"),
            filepath=value(item, "Filepath"), filename=value(item, "Filename"),
            calgroup=value(item, "Calgroup") or path.parent.name, report_path=str(path),
        ))
    return findings


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(DB_PATH, factory=ClosingConnection)
    db.row_factory = sqlite3.Row
    return db


def init_db() -> None:
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS findings (
          id INTEGER PRIMARY KEY, outage TEXT NOT NULL, unit_id INTEGER NOT NULL,
          thimble_id INTEGER NOT NULL, position TEXT, entry_no INTEGER, volts REAL,
          degrees REAL, indication TEXT, percent REAL, channel TEXT, location TEXT,
          datapoint INTEGER, liss_region_size INTEGER, analyst TEXT, analysis TEXT,
          filepath TEXT, filename TEXT, calgroup TEXT, report_path TEXT,
          imported_at TEXT NOT NULL,
          UNIQUE(outage, unit_id, thimble_id, entry_no, analyst, analysis, calgroup, filename, datapoint, channel)
        );
        CREATE TABLE IF NOT EXISTS tube_states (
          outage TEXT NOT NULL, unit_id INTEGER NOT NULL, thimble_id INTEGER NOT NULL,
          state TEXT NOT NULL DEFAULT 'normal', offset_mm REAL NOT NULL DEFAULT 0,
          note TEXT NOT NULL DEFAULT '', PRIMARY KEY(outage, unit_id, thimble_id)
        );
        """)
        table_sql = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='findings'").fetchone()[0] or ""
        unique_sql = re.sub(r"\s+", "", table_sql.lower())
        if "filename,datapoint,channel" not in unique_sql:
            db.executescript("""
            ALTER TABLE findings RENAME TO findings_legacy;
            CREATE TABLE findings (
              id INTEGER PRIMARY KEY, outage TEXT NOT NULL, unit_id INTEGER NOT NULL,
              thimble_id INTEGER NOT NULL, position TEXT, entry_no INTEGER, volts REAL,
              degrees REAL, indication TEXT, percent REAL, channel TEXT, location TEXT,
              datapoint INTEGER, liss_region_size INTEGER, analyst TEXT, analysis TEXT,
              filepath TEXT, filename TEXT, calgroup TEXT, report_path TEXT,
              imported_at TEXT NOT NULL,
              UNIQUE(outage, unit_id, thimble_id, entry_no, analyst, analysis, calgroup, filename, datapoint, channel)
            );
            INSERT OR IGNORE INTO findings SELECT * FROM findings_legacy;
            DROP TABLE findings_legacy;
            """)
        db.execute("DELETE FROM findings WHERE thimble_id NOT BETWEEN 1 AND 50")


def report_options(directory: str) -> list[dict]:
    base = Path(directory).expanduser().resolve()
    if not base.is_dir():
        raise ValueError("所选路径不是有效文件夹")
    options = []
    fingerprints: dict[tuple[str, str, str], dict] = {}
    for report in sorted(path for path in base.rglob("*") if path.is_file() and path.name.lower().startswith("report") and path.suffix.lower() == ".rpt" and path.parent.name.upper().startswith("TH")):
        try:
            rows = parse_report(report)
            option = {
                "path": str(report),
                "name": report.name,
                "group": report.parent.name,
                "outage": infer_outage(report),
                "analysts": sorted({row.analyst for row in rows if row.analyst}),
                "records": len(rows),
                "tubes": sorted({row.thimble_id for row in rows}),
                "tube_count": len({row.thimble_id for row in rows}),
                "indication_count": sum(bool(row.indication.strip()) for row in rows),
                "duplicate_paths": [],
            }
            digest = hashlib.sha256(report.read_bytes()).hexdigest()
            key = (option["outage"], option["group"].upper(), digest)
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
    unique: dict[tuple[str, str, str], Path] = {}
    for report in sorted(reports):
        try:
            key = (infer_outage(report), report.parent.name.upper(), hashlib.sha256(report.read_bytes()).hexdigest())
        except OSError:
            key = (infer_outage(report), report.parent.name.upper(), str(report.resolve()).lower())
        unique.setdefault(key, report)
    return list(unique.values())


def import_directory(directory: str, selected_reports: list[str] | None = None) -> dict:
    base = Path(directory).expanduser().resolve()
    if not base.is_dir():
        raise ValueError("所选路径不是有效文件夹")
    reports = sorted(path for path in base.rglob("*") if path.is_file() and path.name.lower().startswith("report") and path.suffix.lower() == ".rpt" and path.parent.name.upper().startswith("TH"))
    if selected_reports is not None:
        selected = {str(Path(path).resolve()).lower() for path in selected_reports}
        reports = [path for path in reports if str(path.resolve()).lower() in selected]
    else:
        reports = unique_report_paths(reports)
    parsed = inserted = skipped = 0
    errors = []
    with connect() as db:
        for report in reports:
            try:
                rows = parse_report(report)
                parsed += len(rows)
                for finding in rows:
                    columns = asdict(finding)
                    columns["imported_at"] = datetime.now().isoformat(timespec="seconds")
                    keys = list(columns)
                    sql = f"INSERT OR IGNORE INTO findings ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})"
                    cur = db.execute(sql, [columns[key] for key in keys])
                    inserted += cur.rowcount
                    skipped += 1 - cur.rowcount
            except Exception as exc:
                errors.append({"file": str(report), "error": str(exc)})
    return {"reports": len(reports), "parsed": parsed, "inserted": inserted, "skipped": skipped, "errors": errors}


def import_excel_file(filename: str) -> dict:
    source = Path(filename).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise ValueError("请选择 .xlsx 或 .xlsm 文件")
    from openpyxl import load_workbook
    book = load_workbook(source, read_only=True, data_only=True)
    aliases = {
        "电站名称": ["电站名称", "基地", "基地名称"], "机组号": ["机组号", "机组", "unitid"],
        "通道编号": ["通道编号", "指套管编号", "incorefluxthimbleid", "套管编号"],
        "在堆芯内的位置": ["在堆芯内的位置", "堆芯位置", "position"], "幅值": ["幅值", "幅值v", "volts"],
        "相位": ["相位", "相位°", "degrees"], "磨损深度": ["磨损深度", "磨损深度%", "percent"],
        "三字码": ["三字码", "缺陷类型", "indication"], "测量通道": ["测量通道", "channel"],
        "磨损位置": ["磨损位置", "location"], "分析人员": ["分析人员", "analyst"],
        "数据": ["数据", "数据文件", "filename"], "数据组": ["数据组", "calgroup"],
        "备注": ["备注", "analysis"], "堵管移位信息": ["堵管移位信息", "管状态"],
        "大修号": ["大修号", "大修", "outage"], "数据流水号": ["数据流水号", "entry", "entryno"],
        "数据点": ["数据点", "datapoint"], "liss区域大小": ["liss区域大小", "lissregionsize"]
    }
    normalized_aliases = {key: {normalize_header(item) for item in values} for key, values in aliases.items()}
    selected = None
    for sheet in book.worksheets:
        for header_row in range(1, min(sheet.max_row, 12) + 1):
            headers = [normalize_header(cell.value) for cell in sheet[header_row]]
            mapping = {key: next((index for index, header in enumerate(headers) if header in names), None) for key, names in normalized_aliases.items()}
            if mapping["机组号"] is not None and mapping["通道编号"] is not None:
                selected = (sheet, header_row, mapping)
                break
        if selected:
            break
    if not selected:
        book.close()
        raise ValueError("无法识别Excel表头：至少需要“机组号”和“通道编号/指套管编号”列")
    sheet, header_row, mapping = selected
    rows = list(sheet.iter_rows(min_row=header_row + 1, values_only=True))
    book.close()
    def cell(values, key):
        index = mapping.get(key)
        return values[index] if index is not None and index < len(values) else None
    inserted = skipped = parsed = 0
    invalid = []
    with connect() as db:
        for row_number, values in enumerate(rows, header_row + 1):
            row = {key: cell(values, key) for key in mapping}
            outage, unit_id, thimble_id = outage_from_standard_row(row, source), number(row["机组号"], int), number(row["通道编号"], int)
            if not outage or not unit_id or not thimble_id or not 1 <= thimble_id <= 50:
                if any(value_ not in (None, "") for value_ in values): invalid.append(row_number)
                continue
            parsed += 1
            finding = Finding(
                outage=outage, unit_id=unit_id, thimble_id=thimble_id,
                position=str(row["在堆芯内的位置"] or position_for(unit_id, thimble_id)),
                entry_no=number(row["数据流水号"], int), volts=number(row["幅值"], float), degrees=number(row["相位"], float),
                indication=str(row["三字码"] or ""), percent=number(row["磨损深度"], float), channel=str(row["测量通道"] or ""),
                location=str(row["磨损位置"] or ""), datapoint=number(row["数据点"], int), liss_region_size=number(row["liss区域大小"], int),
                analyst=str(row["分析人员"] or ""), analysis=str(row["备注"] or ""), filepath="",
                filename=str(row["数据"] or source.name), calgroup=str(row["数据组"] or ""), report_path=str(source)
            )
            columns = asdict(finding)
            columns["imported_at"] = datetime.now().isoformat(timespec="seconds")
            keys = list(columns)
            sql = f"INSERT OR IGNORE INTO findings ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})"
            cur = db.execute(sql, [columns[key] for key in keys])
            inserted += cur.rowcount
            skipped += 1 - cur.rowcount
    return {"file": str(source), "sheet": sheet.title, "header_row": header_row, "parsed": parsed, "inserted": inserted, "skipped": skipped, "invalid_rows": invalid[:100]}


def analyze_directory(directory: str, selected_reports: list[str] | None = None) -> tuple[list[Finding], list[dict]]:
    base = Path(directory).expanduser().resolve()
    if not base.is_dir():
        raise ValueError("所选路径不是有效文件夹")
    findings, errors = [], []
    reports = sorted(path for path in base.rglob("*") if path.is_file() and path.name.lower().startswith("report") and path.suffix.lower() == ".rpt" and path.parent.name.upper().startswith("TH"))
    if selected_reports is not None:
        selected = {str(Path(path).resolve()).lower() for path in selected_reports}
        reports = [path for path in reports if str(path.resolve()).lower() in selected]
    else:
        reports = unique_report_paths(reports)
    for report in reports:
        try:
            findings.extend(parse_report(report))
        except Exception as exc:
            errors.append({"file": str(report), "error": str(exc)})
    return findings, errors


def automatic_report_selection(directory: str, policy: str) -> list[str] | None:
    if policy == "all":
        return None
    if policy != "latest":
        return None
    base = Path(directory).expanduser().resolve()
    reports = unique_report_paths(path for path in base.rglob("*") if path.is_file() and path.name.lower().startswith("report") and path.suffix.lower() == ".rpt" and path.parent.name.upper().startswith("TH"))
    groups: dict[str, list[Path]] = {}
    for report in reports:
        groups.setdefault(f"{infer_outage(report)}|{report.parent.name.upper()}", []).append(report)
    return [str(max(group, key=lambda path: (path.stat().st_mtime, path.name.lower()))) for group in groups.values()]


def analyze_data_groups(directory: str) -> list[dict]:
    base = Path(directory).expanduser().resolve()
    groups = []
    for summary_path in sorted(base.rglob("*.SUM")):
        group_dir = summary_path.parent
        if not group_dir.name.upper().startswith("TH"):
            continue
        try:
            root = ET.parse(summary_path).getroot()
            site_node = root.find("Site")
            operator_node = root.find("Operator")
            probe_node = root.find("Probe")
            site_node = site_node if site_node is not None else root
            operator_node = operator_node if operator_node is not None else root
            probe_node = probe_node if probe_node is not None else root
            valid_ect = [path for path in group_dir.glob("*.ECT") if not re.search(r"999C999", path.name, re.I)]
            timestamps = []
            for ect in valid_ect:
                text = ect.read_bytes()[:8192].decode("utf-8", errors="ignore")
                match = re.search(r"<DateTime>(.*?)</DateTime>", text, re.S)
                if match:
                    timestamps.append(match.group(1).strip())
            groups.append({
                "site_code": value(site_node, "SiteCode"),
                "outage": value(site_node, "Outage") or infer_outage(group_dir),
                "unit_id": number(value(site_node, "Unit"), int),
                "data_group": group_dir.name,
                "operator": value(operator_node, "Id"),
                "probe_type": value(probe_node, "Type"),
                "probe_sn": value(probe_node, "Sn"),
                "probe_model": value(probe_node, "Model"),
                "tube_number": len(valid_ect),
                "start_time": min(timestamps) if timestamps else "",
                "end_time": max(timestamps) if timestamps else "",
                "report_versions": len(list(group_dir.glob("Report*.rpt")))
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
        outage_match = re.search(r"(?<![A-Z0-9])([A-Z]\d{3})(?![A-Z0-9])", current.name.upper())
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


def export_directory_excel(directory: str, selected_reports: list[str] | None = None, report_policy: str = "manual") -> dict:
    if selected_reports is None and report_policy in {"latest", "all"}:
        selected_reports = automatic_report_selection(directory, report_policy)
    findings, errors = analyze_directory(directory, selected_reports)
    groups = analyze_data_groups(directory)
    validation = scan_thimble_directory(directory)
    ect_index = {(item["calgroup"].upper(), item["filename"].upper()): item for item in validation["ect"]}
    if not findings:
        raise ValueError("目录中没有可导出的指套管检测记录")
    EXCEL_DIR.mkdir(parents=True, exist_ok=True)
    source_name = Path(directory).resolve().name or "指套管检测数据"
    safe_name = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", source_name)
    filename = f"{safe_name}_解析结果_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    target = EXCEL_DIR / filename
    book = Workbook()
    sheet = book.active
    sheet.title = "标准数据表"
    sheet.append(STANDARD_EXCEL_FIELDS)
    for finding in findings:
        site_code = finding.outage[:1] if finding.outage != "UNKNOWN" else ""
        station = next((name for name, code in STATION_CODES.items() if code == site_code), "")
        sheet.append([
            station, "" if finding.outage == "UNKNOWN" else finding.outage, finding.unit_id,
            "规范非强制要求的检查项目", "其它", "指套管", finding.thimble_id,
            finding.position, finding.volts, finding.degrees, finding.percent, finding.indication or "NDD",
            finding.channel, finding.location, "TH048NAF25A", finding.analyst, finding.filename,
            finding.calgroup, finding.analysis or "/", "/"
        ])
    header_fill = PatternFill("solid", fgColor="263942")
    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    sheet.row_dimensions[1].height = 24
    for index, label in enumerate(STANDARD_EXCEL_FIELDS, 1):
        values = [str(sheet.cell(row, index).value or "") for row in range(1, min(sheet.max_row, 200) + 1)]
        sheet.column_dimensions[get_column_letter(index)].width = min(48, max(len(label) + 3, max(map(len, values), default=0) + 2))
    summary = book.create_sheet("数据组汇总")
    group_fields = [("基地代码", "site_code"), ("大修号", "outage"), ("机组号", "unit_id"), ("数据组", "data_group"), ("操作员", "operator"), ("探头类型", "probe_type"), ("探头序列号", "probe_sn"), ("探头型号", "probe_model"), ("有效ECT数量", "tube_number"), ("开始时间", "start_time"), ("结束时间", "end_time"), ("报告版本数", "report_versions")]
    summary.append([label for label, _ in group_fields])
    for group in groups:
        summary.append([group[key] for _, key in group_fields])
    for cell in summary[1]:
        cell.fill = header_fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")
    summary.freeze_panes = "A2"
    summary.auto_filter.ref = summary.dimensions
    for index, (label, _) in enumerate(group_fields, 1):
        values = [str(summary.cell(row, index).value or "") for row in range(1, summary.max_row + 1)]
        summary.column_dimensions[get_column_letter(index)].width = min(42, max(len(label) + 3, max(map(len, values), default=0) + 2))
    checks = book.create_sheet("文件校验")
    checks.append(["类型", "文件", "数据组", "文件名Row", "文件名Column", "文件名Entry", "HeaderRow", "HeaderColumn", "HeaderEntry", "标定文件", "校验状态"])
    for item in validation["ect"]:
        checks.append(["ECT", item["path"], item["calgroup"], item["name_row"], item["name_col"], item["name_entry"], item["row"], item["col"], item["entry"], "是" if item["calibration"] else "否", item["validation"]])
    for error in validation["errors"]:
        checks.append([error["type"], error["file"], "", "", "", "", "", "", "", "", error["message"]])
    checks.append(["覆盖统计", "", "", "", "", "", "", "", "", "", f"有效唯一管号{len(validation['unique_tubes'])}根；缺失：{','.join(map(str, validation['missing_tubes'])) or '无'}；标定ECT：{validation['calibration_count']}个"])
    for cell in checks[1]:
        cell.fill = header_fill
        cell.font = Font(color="FFFFFF", bold=True)
    checks.freeze_panes = "A2"
    checks.column_dimensions["B"].width = 70
    checks.column_dimensions["K"].width = 46
    book.save(target)
    return {"rows": len(findings), "groups": len(groups), "errors": errors + validation["errors"], "unique_tubes": len(validation["unique_tubes"]), "missing_tubes": validation["missing_tubes"], "calibration_ect": validation["calibration_count"], "filename": filename, "file_path": str(target), "download_url": f"/api/download-excel?name={quote(filename)}"}


def query_findings(params: dict[str, list[str]]) -> dict:
    page = max(1, number(params.get("page", ["1"])[0], int) or 1)
    size = min(200, max(1, number(params.get("size", ["50"])[0], int) or 50))
    where, args = [], []
    for query_key, column in (("site", "SUBSTR(f.outage,1,1)"), ("outage", "f.outage"), ("unit", "f.unit_id"), ("analyst", "f.analyst"), ("channel", "f.channel"), ("thimble", "f.thimble_id"), ("calgroup", "f.calgroup")):
        val = params.get(query_key, [""])[0].strip()
        if val:
            where.append(f"CAST({column} AS TEXT) LIKE ?")
            args.append(f"%{val}%")
    clause = " WHERE " + " AND ".join(where) if where else ""
    with connect() as db:
        total = db.execute("SELECT COUNT(*) FROM findings f" + clause, args).fetchone()[0]
        sql = """SELECT f.*, COALESCE(s.state,'normal') state, COALESCE(s.offset_mm,0) offset_mm,
                 COALESCE(s.note,'') note FROM findings f LEFT JOIN tube_states s
                 ON s.outage=f.outage AND s.unit_id=f.unit_id AND s.thimble_id=f.thimble_id"""
        rows = db.execute(sql + clause + " ORDER BY f.outage DESC,f.thimble_id,f.entry_no LIMIT ? OFFSET ?", args + [size, (page - 1) * size]).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["p_zone"], item["p_offset"] = split_location(item.get("location", ""))
        items.append(item)
    return {"items": items, "total": total, "page": page, "size": size, "pages": max(1, (total + size - 1) // size)}


def overview() -> dict:
    with connect() as db:
        stats = dict(db.execute("SELECT COUNT(*) findings, COUNT(DISTINCT outage) outages, COUNT(DISTINCT unit_id) units, COUNT(DISTINCT analyst) analysts FROM findings").fetchone())
        outages = [row[0] for row in db.execute("SELECT DISTINCT outage FROM findings ORDER BY outage DESC")]
        units = [row[0] for row in db.execute("SELECT DISTINCT unit_id FROM findings ORDER BY unit_id")]
        sites = [row[0] for row in db.execute("SELECT DISTINCT SUBSTR(outage,1,1) FROM findings ORDER BY 1")]
        combinations = [dict(row) for row in db.execute("SELECT DISTINCT SUBSTR(outage,1,1) site, unit_id, outage FROM findings ORDER BY site,unit_id,outage DESC")]
        history = [dict(row) for row in db.execute(
            """SELECT SUBSTR(outage,1,1) site, unit_id, outage,
                      COUNT(*) findings, COUNT(DISTINCT thimble_id) tubes,
                      COUNT(DISTINCT analyst) analysts
                 FROM findings
                WHERE outage <> '' AND outage <> 'UNKNOWN'
                GROUP BY outage, unit_id
                ORDER BY site, unit_id, outage"""
        )]
    return {"stats": stats, "sites": sites, "outages": outages, "units": units, "combinations": combinations, "history": history}


def compare(old: str, new: str, unit: int) -> dict:
    if not old or not new or old == new:
        raise ValueError("请选择同一机组的两个不同大修")
    if old[:1].upper() != new[:1].upper() or infer_unit(old, "") != unit or infer_unit(new, "") != unit:
        raise ValueError("仅允许对比相同基地、相同机组的不同大修")
    with connect() as db:
        old_rows = [dict(row) for row in db.execute("SELECT * FROM findings WHERE outage=? AND unit_id=?", (old, unit)).fetchall()]
        new_rows = [dict(row) for row in db.execute("SELECT f.*,COALESCE(s.state,'normal') state,COALESCE(s.offset_mm,0) offset_mm,COALESCE(s.note,'') note FROM findings f LEFT JOIN tube_states s ON s.outage=f.outage AND s.unit_id=f.unit_id AND s.thimble_id=f.thimble_id WHERE f.outage=? AND f.unit_id=?", (new, unit)).fetchall()]
    new_rows = [row for row in new_rows if is_real_defect(row) and row["state"] != "plugged"]
    offsets = {row["thimble_id"]: float(row.get("offset_mm") or 0) for row in new_rows if row["state"] == "shifted"}
    old_by_key = {(row["thimble_id"], *defect_match_key(row, -offsets.get(row["thimble_id"], 0))): row for row in old_rows if is_real_defect(row)}
    items = []
    for row in new_rows:
        key = (row["thimble_id"], *defect_match_key(row))
        item = dict(row)
        previous = old_by_key.get(key)
        item["comparison"] = "NI" if row["state"] == "replaced" or previous is None else "R"
        item["old_volts"] = previous["volts"] if previous else None
        item["old_percent"] = previous["percent"] if previous else None
        item["old_location"] = previous["location"] if previous else ""
        item["old_datapoint"] = previous["datapoint"] if previous else None
        items.append(item)
    return {"old": old, "new": new, "unit": unit, "items": items, "summary": {"R": sum(i["comparison"] == "R" for i in items), "NI": sum(i["comparison"] == "NI" for i in items)}}

DATAPOINT_MM = 0.125

def normalize_location(location: str) -> tuple[str, float | None]:
    match = re.match(r"^\s*(P\d+)\s*(?:\+\s*([-+]?\d+(?:\.\d+)?))?\s*(?:mm)?\s*$", str(location or ""), re.I)
    return (match.group(1).upper(), number(match.group(2), float)) if match else ((str(location or "").strip(), None))

def is_real_defect(row) -> bool:
    indication = str(row["indication"] or "").strip().upper()
    return bool(indication) and indication != "NDD" and bool(row["datapoint"] and row["datapoint"] > 0)

def defect_match_key(row, shift_mm: float = 0) -> tuple[str, float]:
    zone, offset = normalize_location(row.get("location", ""))
    if offset is None:
        offset = (row.get("datapoint") or 0) * DATAPOINT_MM
    return zone, round(float(offset) - float(shift_mm or 0), 2)

def annotate_evolution(rows: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for row in rows: grouped.setdefault(row["outage"], []).append(row)
    baseline: set[tuple[str, float]] = set(); blocked = False
    for outage in sorted(grouped, key=outage_sort_key):
        group = grouped[outage]; state = group[0].get("state", "normal"); shift = group[0].get("offset_mm", 0)
        defects = [row for row in group if is_real_defect(row)]
        for row in group:
            row["comparison"] = "堵管后不比对" if blocked else ("无缺陷" if not defects else "")
        if blocked: continue
        if state == "replaced": baseline = set()
        for row in defects:
            row["comparison"] = "R" if baseline and defect_match_key(row, shift if state == "shifted" else 0) in baseline else "NI"
        if state == "plugged":
            blocked = True
            continue
        if defects:
            baseline = {defect_match_key(row) for row in defects}
    return rows

def outage_sort_key(outage: str):
    match = re.search(r"^[A-Z](\d)(\d{2})$", str(outage or "").upper())
    return (int(match.group(1)), int(match.group(2))) if match else (999, 999)

def tube_history(site: str, unit: int, thimble: int) -> dict:
    with connect() as db:
        rows = [dict(row) for row in db.execute("""SELECT f.*, COALESCE(s.state,'normal') state,
            COALESCE(s.offset_mm,0) offset_mm, COALESCE(s.note,'') note
            FROM findings f LEFT JOIN tube_states s ON s.outage=f.outage AND s.unit_id=f.unit_id
            AND s.thimble_id=f.thimble_id WHERE f.unit_id=? AND f.thimble_id=?
            AND SUBSTR(f.outage,1,1)=? ORDER BY f.outage""", (unit, thimble, site.upper()))]
    rows.sort(key=lambda row: outage_sort_key(row["outage"]))
    annotate_evolution(rows)
    return {"site": site.upper(), "unit": unit, "thimble": thimble, "items": rows}

def unit_evolution(site: str, unit: int) -> dict:
    with connect() as db:
        thimbles = [row[0] for row in db.execute("SELECT DISTINCT thimble_id FROM findings WHERE unit_id=? AND SUBSTR(outage,1,1)=? ORDER BY thimble_id", (unit, site.upper()))]
    return {"site": site.upper(), "unit": unit, "tubes": [tube_history(site, unit, thimble) for thimble in thimbles]}

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
            if state == "plugged": break
            if defects: previous = defects
    for cell in sheet[1]: cell.font = Font(bold=True)
    return workbook_result(f"{site}{unit}_指套管纵向演变_{datetime.now():%Y%m%d_%H%M%S}.xlsx", book)


def workbook_result(filename: str, book: Workbook) -> dict:
    EXCEL_DIR.mkdir(parents=True, exist_ok=True)
    target = EXCEL_DIR / filename
    book.save(target)
    return {"filename": filename, "file_path": str(target), "download_url": f"/api/download-excel?name={quote(filename)}"}


def export_comparison_excel(old: str, new: str, unit: int) -> dict:
    data = compare(old, new, unit)
    book = Workbook()
    sheet = book.active
    sheet.title = "涡流检验结果对比表"
    sheet.merge_cells("A1:L1")
    sheet["A1"] = f"{unit}号机组反应堆中子通量测量指套管涡流检验结果对比表"
    sheet["A1"].font = Font(size=15, bold=True)
    sheet["A1"].alignment = Alignment(horizontal="center")
    sheet.append(["序号", "通道编号", "堆芯位置", f"{new}幅值(V)", f"{new}磨损深度(%)", f"{new}磨损位置", f"{new}数据点", f"{old}幅值(V)", f"{old}磨损深度(%)", f"{old}磨损位置", f"{old}数据点", "备注"])
    for index, row in enumerate(data["items"], 1):
        sheet.append([index, row["thimble_id"], row["position"], row["volts"], row["percent"], row["location"], row["datapoint"], row["old_volts"], row["old_percent"], row["old_location"], row["old_datapoint"], row["comparison"]])
    for cell in sheet[2]:
        cell.fill = PatternFill("solid", fgColor="DCE6EA")
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.freeze_panes = "A3"
    for column in range(1, 13):
        sheet.column_dimensions[get_column_letter(column)].width = 15 if column > 3 else 11
    return {**workbook_result(f"{new}_对比_{old}_{datetime.now():%Y%m%d_%H%M%S}.xlsx", book), **data["summary"]}


def export_inspection_report(outage: str, unit: int, metadata: dict) -> dict:
    if infer_unit(outage, "") != unit:
        raise ValueError("大修编号与机组不匹配")
    with connect() as db:
        rows = [dict(row) for row in db.execute("SELECT * FROM findings WHERE outage=? AND unit_id=? ORDER BY thimble_id,entry_no,datapoint", (outage, unit))]
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
        display = row["indication"] or "NDD"
        values = [index, row["thimble_id"], row["position"], display, row["volts"], row["percent"], row["location"], row["channel"]]
        for col, value_ in enumerate(values, 1):
            sheet.cell(header_row + index, col, value_)
    for cell in sheet[header_row]:
        cell.fill = PatternFill("solid", fgColor="DCE6EA")
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.freeze_panes = f"A{header_row + 1}"
    widths = [8, 12, 13, 12, 12, 18, 18, 16]
    for col, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(col)].width = width
    return {**workbook_result(f"{outage}_指套管涡流检验报告单_{datetime.now():%Y%m%d_%H%M%S}.xlsx", book), "rows": len(rows)}


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stdout.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def json_response(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def body(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")

    def do_GET(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/overview": return self.json_response(overview())
            if parsed.path == "/api/findings": return self.json_response(query_findings(parse_qs(parsed.query)))
            if parsed.path == "/api/tube-history":
                q = parse_qs(parsed.query); return self.json_response(tube_history(q.get("site", [""])[0], int(q.get("unit", ["0"])[0]), int(q.get("thimble", ["0"])[0])))
            if parsed.path == "/api/unit-evolution":
                q = parse_qs(parsed.query); return self.json_response(unit_evolution(q.get("site", [""])[0], int(q.get("unit", ["0"])[0])))
            if parsed.path == "/api/compare":
                q = parse_qs(parsed.query)
                return self.json_response(compare(q.get("old", [""])[0], q.get("new", [""])[0], int(q.get("unit", ["0"])[0])))
            if parsed.path == "/api/export": return self.export_csv(parse_qs(parsed.query))
            if parsed.path == "/api/download-excel": return self.download_excel(parse_qs(parsed.query))
            return self.serve_static(parsed.path)
        except Exception as exc:
            self.json_response({"error": str(exc)}, 400)

    def do_POST(self):
        try:
            data = self.body()
            if self.path == "/api/report-options": return self.json_response({"reports": report_options(data.get("path", ""))})
            if self.path == "/api/discover-server": return self.json_response(discover_server_sources(data.get("path", "")))
            if self.path == "/api/import": return self.json_response(import_directory(data.get("path", ""), data.get("reports")))
            if self.path == "/api/import-excel": return self.json_response(import_excel_file(data.get("path", "")))
            if self.path == "/api/export-comparison": return self.json_response(export_comparison_excel(data.get("old", ""), data.get("new", ""), int(data.get("unit", 0))))
            if self.path == "/api/export-evolution": return self.json_response(export_evolution_excel(data.get("site", ""), int(data.get("unit", 0))))
            if self.path == "/api/export-report": return self.json_response(export_inspection_report(data.get("outage", ""), int(data.get("unit", 0)), data.get("metadata") or {}))
            if self.path == "/api/clear":
                with connect() as db:
                    db.execute("DELETE FROM findings")
                    db.execute("DELETE FROM tube_states")
                return self.json_response({"ok": True})
            if self.path == "/api/export-folder-excel": return self.json_response(export_directory_excel(data.get("path", ""), data.get("reports"), data.get("report_policy", "manual")))
            if self.path == "/api/state":
                with connect() as db:
                    db.execute("INSERT INTO tube_states(outage,unit_id,thimble_id,state,offset_mm,note) VALUES(?,?,?,?,?,?) ON CONFLICT(outage,unit_id,thimble_id) DO UPDATE SET state=excluded.state,offset_mm=excluded.offset_mm,note=excluded.note", (data["outage"], data["unit_id"], data["thimble_id"], data["state"], data.get("offset_mm", 0), data.get("note", "")))
                return self.json_response({"ok": True})
            self.json_response({"error": "接口不存在"}, 404)
        except Exception as exc:
            self.json_response({"error": str(exc)}, 400)

    def export_csv(self, params):
        result = query_findings({**params, "page": ["1"], "size": ["200"]})
        output = io.StringIO()
        fields = ["outage","unit_id","thimble_id","position","entry_no","volts","degrees","indication","percent","channel","location","datapoint","analyst","analysis","filename","calgroup","state","offset_mm","note"]
        writer = csv.DictWriter(output, fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(result["items"])
        payload = b"\xef\xbb\xbf" + output.getvalue().encode("utf-8")
        self.send_response(200); self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", "attachment; filename=thimble-findings.csv")
        self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload)

    def download_excel(self, params):
        name = Path(params.get("name", [""])[0]).name
        target = (EXCEL_DIR / name).resolve()
        if target.parent != EXCEL_DIR.resolve() or not target.is_file():
            return self.send_error(HTTPStatus.NOT_FOUND)
        payload = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.send_header("Content-Disposition", "attachment; filename=thimble-report.xlsx")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def serve_static(self, path):
        target = STATIC / ("index.html" if path == "/" else path.lstrip("/"))
        target = target.resolve()
        if STATIC.resolve() not in target.parents and target != STATIC.resolve():
            return self.send_error(HTTPStatus.FORBIDDEN)
        if not target.is_file(): return self.send_error(HTTPStatus.NOT_FOUND)
        payload = target.read_bytes(); self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload)


def main():
    init_db()
    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    print("指套管检测数据管理系统: http://127.0.0.1:8765", flush=True)
    server.serve_forever()


if __name__ == "__main__": main()
