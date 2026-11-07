"""Repeatable offline validation using original files and isolated SQLite databases."""
from __future__ import annotations

import hashlib
import csv
import json
import os
import sqlite3
import sys
import zipfile
from xml.etree import ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / ".vendor"))


def digest(path):
    sha = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def main():
    output = PROJECT / "tmp" / ("real-data-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    output.mkdir(parents=True)
    os.environ["THIMBLE_DATA_DIR"] = str(output)
    os.environ["THIMBLE_OUTPUT_DIR"] = str(output / "excel")
    os.environ["THIMBLE_REPORT_DIR"] = str(output / "reports")
    from src.backend import server, analysis_reporting, import_audit, cross_group_review
    from src.backend.setup_parser import parse_setup
    from openpyxl import load_workbook

    data_root = PROJECT / "项目资料" / "03_原始验证数据" / "测试数据"
    roots = [data_root / name for name in ("指套管数据1", "指套管数据2")]
    sources = [p for root in roots for p in root.rglob("*")
               if p.is_file() and p.suffix.lower() in {".ect", ".rpt", ".sum", ".set", ".xlsx", ".db"}]
    before = {str(p): digest(p) for p in sources}
    evidence = {"created_at": datetime.now().isoformat(), "service_version": server.SERVICE_VERSION,
                "database": str(server.DB_PATH), "source_files": len(sources),
                "report_choice_policy": "仅自动化验证：按文件名排序选每组第一候选，不代表用户人工确认或业务最终版本",
                "datasets": [], "set": [], "exports": [], "checks": [],
                "limitations": ["本脚本不代表界面、严格报告版式、真实模型物理标定或全部聊天需求验收通过"]}
    server.init_db()
    for root in roots:
        print("DATASET", root.name, flush=True)
        options = server.report_options(str(root))
        grouped = defaultdict(list)
        for option in options:
            if not option.get("error"):
                grouped[(option["site_code"], option["unit_id"], option["outage"], option["group"])].append(option)
        selected = [sorted(items, key=lambda item: item["path"])[0]["path"] for items in grouped.values()]
        result = server.import_directory(str(root), selected, blank_indication_policy="review",
                                         operator="自动化真实数据验证（非人工确认）")
        repeated = server.import_directory(str(root), selected, blank_indication_policy="review",
                                           operator="自动化重复导入验证")
        evidence["checks"].append({"check": str(root) + " 重复导入不新增", "passed": repeated["inserted"] == 0})
        evidence["datasets"].append({"path": str(root), "candidate_count": len(options),
            "invalid_candidates": [o for o in options if o.get("error")],
            "ambiguous_groups": [{"key": list(key), "candidates": [i["path"] for i in items]}
                                 for key, items in grouped.items() if len(items) > 1],
            "selected_for_test_only": selected, "import": result, "repeat": repeated})

    for root in roots:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() != ".set":
                continue
            try:
                config = parse_setup(path)
                item = {"path": str(path), "sha256": before[str(path)], "status": "parsed_configuration",
                        "channels": len(config["channels"]),
                        "channel_types": dict(Counter(c["type"] for c in config["channels"]))}
            except Exception as exc:
                item = {"path": str(path), "sha256": before[str(path)], "status": "unparsed", "error": str(exc)}
            evidence["set"].append(item)

    with server.connect() as db:
        scopes = [dict(row) for row in db.execute(
            "SELECT outage,unit_id,COUNT(*) records FROM findings WHERE is_deleted=0 GROUP BY outage,unit_id")]
        evidence["integrity"] = db.execute("PRAGMA integrity_check").fetchone()[0]
        evidence["quality_counts"] = dict(db.execute(
            "SELECT code,COUNT(*) FROM validation_issues GROUP BY code").fetchall())
    evidence["checks"].append({"check": "SQLite integrity_check", "passed": evidence["integrity"] == "ok"})
    evidence["scopes"] = scopes
    evidence["cross_group_reviews"] = {k: v for k, v in cross_group_review.listing(server).items() if k != "items"}
    for scope in scopes:
        payload = {"site": scope["outage"][0], "unit": scope["unit_id"], "outage": scope["outage"], "kind": "inspection"}
        snapshot = analysis_reporting.report_snapshot(server, payload)
        for fmt in ("docx", "xlsx", "csv"):
            exported = analysis_reporting.export(server, {**payload, "snapshot_id": snapshot["snapshot_id"], "format": fmt})
            target = Path(exported["file_path"])
            check = {"outage": scope["outage"], "format": fmt, "path": str(target),
                     "sha256": digest(target), "snapshot": snapshot["snapshot_id"], "rows": snapshot["rows"]}
            companion = json.loads(Path(exported["provenance_file_path"]).read_text(encoding="utf-8"))
            check["provenance_matches"] = (companion["snapshot_id"] == snapshot["snapshot_id"]
                and companion["sources"] == snapshot["sources"] and companion["warnings"] == snapshot["warnings"]
                and companion["sha256"] == check["sha256"])
            assert check["provenance_matches"]
            if fmt == "xlsx":
                book = load_workbook(target, data_only=True)
                check["sheets"] = book.sheetnames
                if "检验结果" in book.sheetnames:
                    sheet = book["检验结果"]
                    actual = []
                    for row in sheet.iter_rows():
                        if not isinstance(row[0].value, (int, float)):
                            continue
                        columns = (1, 2, 5, 7, 9, 11, 14, 17)
                        values = [sheet.cell(row[0].row, col).value for col in columns]
                        for index, column in enumerate(columns):
                            for merged in sheet.merged_cells.ranges:
                                if merged.min_col <= column <= merged.max_col and merged.min_row <= row[0].row <= merged.max_row:
                                    values[index] = sheet.cell(merged.min_row, merged.min_col).value
                                    break
                        actual.append(values)
                    expected = [list(row[:8]) for row in snapshot["values"]]
                    for row in expected:
                        if row[3] == "NDD":
                            row[4:8] = ["/", "/", "/", "/"]
                    normalize = lambda rows: [["" if v is None else format(v, ".12g") if isinstance(v, (int, float)) else str(v) for v in row] for row in rows]
                    check["row_count_matches"] = len(actual) == snapshot["rows"]
                    check["values_match"] = normalize(actual) == normalize(expected)
                else:
                    actual = list(book["报告结果"].values)
                    expected = [snapshot["headers"], *snapshot["values"]]
                    check["row_count_matches"] = len(actual) - 1 == snapshot["rows"]
                    check["values_match"] = ([list(row) for row in actual] ==
                        [[None if value == "" else value for value in row] for row in expected])
                book.close()
                if not (check["row_count_matches"] and check["values_match"]):
                    raise AssertionError({"outage": scope["outage"], "actual_rows": len(actual), "expected_rows": len(expected),
                        "first_mismatches": [(a, b) for a, b in zip(actual, expected) if a != b][:3]})
            elif fmt == "docx":
                with zipfile.ZipFile(target) as archive:
                    ET.fromstring(archive.read("word/document.xml"))
                    check["xml_valid"] = archive.testzip() is None
                assert check["xml_valid"]
            elif fmt == "csv":
                with target.open(encoding="utf-8-sig", newline="") as stream:
                    actual = list(csv.reader(stream))
                expected = [snapshot["headers"]]
                for row in snapshot["values"]:
                    expected.append(["'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@"))
                                     else "" if value is None else str(value) for value in row])
                check["values_match"] = actual == expected
                assert check["values_match"]
            evidence["exports"].append(check)

    # Exercise real folder -> workbook -> new database instead of only reading fixtures.
    for root in roots[:1]:
        selected = evidence["datasets"][0]["selected_for_test_only"]
        workbook = server.export_directory_excel(str(root), selected)
        old_db = server.DB_PATH
        try:
            server.DB_PATH = output / "roundtrip.db"
            server.init_db()
            imported = server.import_excel_file(workbook["file_path"], "review", operator="真实数据往返验证")
            with server.connect() as db:
                count = db.execute("SELECT COUNT(*) FROM findings WHERE is_deleted=0").fetchone()[0]
            evidence["roundtrip"] = {"file": workbook["file_path"], "import": imported, "records": count}
            assert count > 0
        finally:
            server.DB_PATH = old_db

    by_unit = defaultdict(list)
    for scope in scopes:
        by_unit[(scope["outage"][0], scope["unit_id"])].append(scope["outage"])
    evidence["comparisons"] = []
    for (_, unit), outages in by_unit.items():
        outages.sort(key=lambda value: analysis_reporting.sequence(value)[2])
        for old, new in zip(outages, outages[1:]):
            compared = analysis_reporting.compare(server, old, new, unit)
            evidence["comparisons"].append({"old": old, "new": new, "summary": compared["summary"],
                                            "rows": len(compared["items"]), "warnings": len(compared["warnings"])})

    reference = PROJECT / "项目资料" / "02_业务参考资料" / "孔姐发的" / "指套管信息" / "指套管资料" / "指套管P1-P6距离.xlsx"
    book = load_workbook(reference, read_only=True, data_only=True)
    evidence["distance_reference"] = {"path": str(reference), "sha256": digest(reference),
        "sheets": [{"name": sheet.title, "rows": list(sheet.values)} for sheet in book],
        "status": "原值读取；未自动套用到所有基地或替代完整P1-P6坐标"}
    book.close()
    model_path = PROJECT / "项目资料" / "02_业务参考资料" / "孔姐发的" / "指套管3D模型" / "step_models.json"
    model = json.loads(model_path.read_text(encoding="utf-8"))
    evidence["model_reference"] = {"path": str(model_path), "sha256": digest(model_path), "units": model.get("units"),
        "assemblies": {key: {"name": item.get("name"), "parts": len(item["parts"]),
                            "vertices": sum(len(part.get("verts", [])) // 3 for part in item["parts"])}
                       for key, item in model["assemblies"].items()},
        "status": "网格已识别；不代表当前软件已接入或标定"}

    # Copy the original software DB with SQLite's backup API and migrate only the copy.
    original_db = PROJECT / "data" / "thimble.db"
    if original_db.exists():
        original_hash = digest(original_db)
        with sqlite3.connect(original_db.as_uri() + "?mode=ro", uri=True) as source:
            with sqlite3.connect(output / "existing-db-copy.db") as dest:
                source.backup(dest)
                initial = dest.execute("SELECT COUNT(*) FROM findings").fetchone()[0]
        old_db = server.DB_PATH
        try:
            server.DB_PATH = output / "existing-db-copy.db"
            server.init_db()
            server.init_db()
            with server.connect() as db:
                final = db.execute("SELECT COUNT(*) FROM findings").fetchone()[0]
                stored_scopes = db.execute("SELECT DISTINCT outage,unit_id FROM findings WHERE is_deleted=0").fetchall()
            stored_units = defaultdict(list)
            for outage, unit in stored_scopes:
                stored_units[(outage[0], unit)].append(outage)
            evidence["existing_database_comparisons"] = []
            for (site, unit), outages in stored_units.items():
                outages.sort(key=lambda value: analysis_reporting.sequence(value)[2])
                for old, new in zip(outages, outages[1:]):
                    compared = analysis_reporting.compare(server, old, new, unit)
                    assert sum(compared["summary"].values()) == len(compared["items"])
                    evidence["existing_database_comparisons"].append({
                        "site": site, "unit": unit, "old": old, "new": new,
                        "summary": compared["summary"], "rows": len(compared["items"])})
            evidence["existing_database"] = {"before": initial, "after": final,
                "original_unchanged": digest(original_db) == original_hash}
            review_listing = cross_group_review.listing(server)
            evidence["existing_database"]["cross_group_review_groups"] = review_listing["total"]
            assert initial == final and evidence["existing_database"]["original_unchanged"]
        finally:
            server.DB_PATH = old_db
    changed = [path for path, sha in before.items() if digest(path) != sha]
    evidence["checks"].append({"check": "原始数据文件SHA-256未变", "passed": not changed, "changed": changed})
    evidence["source_hashes"] = before
    (output / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    assert all(check["passed"] for check in evidence["checks"])
    print(json.dumps({"evidence": str(output / "evidence.json"), "scopes": scopes,
                      "set_status": dict(Counter(item["status"] for item in evidence["set"])),
                      "exports": len(evidence["exports"]), "comparisons": evidence["comparisons"]},
                     ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
