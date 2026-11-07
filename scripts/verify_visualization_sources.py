"""Read-only reconciliation of visualization aggregates and original WAR report entries."""
import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.backend import server, visualization_reporting


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--originals", required=True)
    parser.add_argument("--ledger", required=True)
    args = parser.parse_args()
    database = Path(args.database).resolve()
    digest = hashlib.sha256(database.read_bytes()).hexdigest()
    with patch.object(server, "DB_PATH", database):
        data = visualization_reporting.build(server, {})
        with server.connect() as db:
            rows = [dict(r) for r in db.execute(
                """SELECT * FROM statistical_findings WHERE is_deleted=0
                AND thimble_id BETWEEN 1 AND 50
                AND UPPER(COALESCE(filename,'')) NOT LIKE 'DIR999%'
                AND UPPER(COALESCE(filename,'')) NOT LIKE 'DIR000%'""")]
    assert len(rows) == data["summary"]["records"]
    sums = Counter()
    war = []
    for row in rows:
        if str(row["indication"] or "").strip().upper() == "WAR":
            depth = row["percent"]
            if isinstance(depth, (int, float)) and 0 <= depth <= 100:
                sums[row["outage"]] += depth
                war.append(row)
    for trend in data["trends"]:
        if trend["total"] is not None:
            assert abs(trend["total"] - sums[trend["outage"]]) < 1e-7, trend
    reports = defaultdict(list)
    for path in Path(args.originals).rglob("*"):
        if path.is_file() and path.suffix.lower() == ".rpt":
            reports[path.name.lower()].append(path)
    cache = {}
    checked = 0
    unmatched = []
    code_differences = 0
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    ledger_signatures = set()
    with ZipFile(args.ledger) as archive:
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = ["".join(item.itertext()) for item in ET.fromstring(
                archive.read("xl/sharedStrings.xml")).findall("m:si", ns)]
        for name in archive.namelist():
            if not re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name):
                continue
            for item in ET.fromstring(archive.read(name)).findall("m:sheetData/m:row", ns)[1:]:
                cells = {}
                for cell in item:
                    col = re.sub(r"\d", "", cell.get("r"))
                    value = cell.findtext("m:v", default="", namespaces=ns)
                    if cell.get("t") == "s":
                        value = strings[int(value)]
                    elif cell.get("t") == "inlineStr":
                        value = "".join(cell.find("m:is", ns).itertext())
                    cells[col] = value
                try:
                    ledger_signatures.add((cells["A"], int(cells["D"]), float(cells["H"]),
                                           cells.get("K", "").strip(), cells.get("I", "").strip()))
                except (ValueError, KeyError):
                    continue
    ledger_checked = 0
    for row in war:
        name = re.split(r"[/\\]", row["report_path"])[-1].lower()
        if name.endswith(".xlsx"):
            signature = (row["outage"], row["thimble_id"], row["percent"],
                         str(row["location"] or "").strip(), str(row["indication"] or "").strip())
            if signature in ledger_signatures:
                ledger_checked += 1
            else:
                unmatched.append({"id": row["id"], "outage": row["outage"], "report": name})
            continue
        if name not in cache:
            signatures = defaultdict(set)
            for path in reports[name]:
                try:
                    root = ET.parse(path).getroot()
                except ET.ParseError:
                    continue
                for entry in root.findall("ReportEntry"):
                    try:
                        key = (int(entry.findtext("Row")), float(entry.findtext("Percent")),
                                        (entry.findtext("Location") or "").strip(),
                                        (entry.findtext("Filename") or "").strip().upper())
                        signatures[key].add((entry.findtext("Indication") or "").strip().upper())
                    except (ValueError, TypeError):
                        continue
            cache[name] = signatures
        signature = (row["thimble_id"], row["percent"], str(row["location"] or "").strip(),
                     str(row["filename"] or "").strip().upper())
        if signature in cache[name]:
            checked += 1
            if "WAR" not in cache[name][signature]:
                code_differences += 1
        else:
            unmatched.append({"id": row["id"], "outage": row["outage"], "report": name})
    assert hashlib.sha256(database.read_bytes()).hexdigest() == digest
    result = {"records": len(rows), "outages_checked": len(data["trends"]), "war_rpt_measurement_matches": checked,
              "war_ledger_matches": ledger_checked, "rpt_indication_differs_from_current": code_differences,
              "war_rows": len(war), "unmatched_count": len(unmatched), "unmatched_examples": unmatched[:10], "source_unchanged": True,
              "original_report_names_checked": len(cache),
              "scope": "RPT核对通道、深度、位置、检测文件名；Excel核对大修、通道、深度、位置、三字符。同名RPT候选合并匹配；三字符差异单列，不验证旧路径编码"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    assert not unmatched, "Some WAR entries cannot be reconciled with original RPT files"


if __name__ == "__main__":
    main()
