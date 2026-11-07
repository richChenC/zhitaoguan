"""Read-only reconciliation of the five reported WAR location anomalies."""
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.backend import analysis_reporting, cross_group_review, visualization_reporting


def verify(database):
    database = Path(database).resolve()

    class Service:
        @staticmethod
        def connect():
            db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
            db.row_factory = sqlite3.Row
            cross_group_review.attach_view(db)
            return db

        @staticmethod
        def position_for(unit, tube):
            return str(tube)

    rows = analysis_reporting.rows_for(Service)
    old = Counter()
    for row in rows:
        if str(row.get("indication") or "").strip().upper() != "WAR":
            continue
        raw = str(row.get("location_raw", row.get("location")) or "").strip()
        match = re.fullmatch(r"P(?:oint)?\s*([1-6])\s*(?:([+-])\s*(\d+(?:\.\d+)?))?\s*(?:mm)?", raw, re.I)
        depth = row.get("percent")
        if analysis_reporting.numeric(depth) and 0 <= depth <= 100:
            old["P" + match.group(1) if match else "未解析"] += depth
    data = visualization_reporting.build(Service, {})
    totals, records = Counter(), Counter()
    for trend in data["trends"]:
        for key, value in trend["positions"].items():
            totals[key] += value
        for key, value in trend["position_stats"].items():
            records[key] += value["records"]
    assert old == totals, (old, totals)
    # Calculate the overall statistic independently, without reading locations.
    war = [row for row in rows if str(row.get("indication") or "").strip().upper() == "WAR"]
    independent_total = sum(row["percent"] for row in war
                            if analysis_reporting.numeric(row.get("percent")) and 0 <= row["percent"] <= 100)
    assert independent_total == sum(totals.values())
    assert sum(records.values()) == len(war)
    # Select representative real records from the current source database.
    # Historical examples are not guaranteed to remain in every valid database.
    representatives = {}
    for row in rows:
        if str(row.get("indication") or "").strip().upper() != "WAR":
            continue
        raw = str(row.get("location_raw", row.get("location")) or "").strip()
        depth = row.get("percent")
        if not analysis_reporting.numeric(depth) or not 0 <= depth <= 100:
            continue
        match = re.fullmatch(
            r"P(?:oint)?\s*([1-6])\s*(?:([+-])\s*(\d+(?:\.\d+)?))?\s*(?:mm)?",
            raw, re.I)
        status = "parsed" if match else "missing" if not raw else "source_label"
        bucket = "P" + match.group(1) if match else "未解析"
        representatives.setdefault(status, (row["outage"], int(row["thimble_id"]),
            raw, depth, bucket, status))
    assert {"parsed", "source_label"}.issubset(representatives), representatives
    expected = list(representatives.values())
    checked = []
    for outage, tube, raw, depth, bucket, status in expected:
        snapshot = next(s for s in data["snapshots"] if s["outage"] == outage)
        tube_data = snapshot["tubes"][tube - 1]
        assert tube_data["coverage"] == "defect"
        findings = tube_data["findings"]
        finding = next(f for f in findings if f["location"] == raw and f["depth"] == depth)
        assert finding["indication"].strip().upper() == "WAR"
        assert finding["position_bucket"] == bucket, finding
        assert finding["position_status"] == status, finding
        assert tube_data["max_depth"] >= depth
        assert "疑似" not in finding["position_note"]
        assert "暂按" not in finding["position_note"]
        checked.append(dict(outage=outage, tube=tube, **finding))
    return dict(passed=True, old_totals=dict(old), totals=dict(totals), records=dict(records),
                total=independent_total, war_records=len(war), quality=data["quality"], checked=checked)


if __name__ == "__main__":
    print(json.dumps(verify(sys.argv[1]), ensure_ascii=False))
