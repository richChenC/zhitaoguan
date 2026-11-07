"""Reconcile every visualization snapshot with read-only database queries."""
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.backend import cross_group_review, visualization_reporting


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

    sql = """SELECT * FROM statistical_findings WHERE is_deleted=0
        AND thimble_id BETWEEN 1 AND 50
        AND UPPER(COALESCE(filename,'')) NOT LIKE 'DIR999%'
        AND UPPER(COALESCE(filename,'')) NOT LIKE 'DIR000%'
        ORDER BY outage,thimble_id,entry_no,datapoint,id"""
    state_sql = "SELECT * FROM tube_states WHERE is_deleted=0"
    with Service.connect() as db:
        rows = [dict(row) for row in db.execute(sql)]
        states = [dict(row) for row in db.execute(state_sql)]
    groups = defaultdict(list)
    for row in rows:
        if re.fullmatch(r"[A-Z]+\d\d{2,}", row["outage"]):
            groups[row["outage"]].append(row)
    actual = visualization_reporting.build(Service, {})
    histories = {entry["outage"]: entry for unit in actual["units"] for entry in unit["history"]}
    expected_latest = {}
    for snapshot in actual["snapshots"]:
        outage = snapshot["outage"]
        original = groups[outage]
        by_tube = defaultdict(list)
        for row in original:
            by_tube[int(row["thimble_id"])].append(row)
        history = histories[outage]
        assert history["records"] == len(original), outage
        assert history["conclusion_records"] == dict(Counter(row["indication"] or "" for row in original)), outage
        assert history["missing_tubes"] == sorted(set(range(1, 51)) - by_tube.keys()), outage
        current = sorted({int(row["thimble_id"]) for row in states if row["outage"] == outage})
        assert history["state_current_tubes"] == current, outage
        recorded = {int(row["thimble_id"]) for row in states
                    if row["outage"][:-2] == outage[:-2] and row["outage"][-2:] <= outage[-2:]}
        assert history["state_missing_tubes"] == sorted(set(range(1, 51)) - recorded), outage
        assert {row["tube"] for row in history["state_sources"]} == recorded, outage
        for tube in snapshot["tubes"]:
            raw = by_tube[tube["tube"]]
            codes = {str(row["indication"] or "").strip().upper() for row in raw}
            def has_wear_signal(row):
                empty = {"", "/", "NA", "N/A", "NONE", "NULL", "NOT AVAILABLE"}
                for field in ("volts", "degrees", "percent", "location", "location_raw"):
                    value = row.get(field)
                    if value is None:
                        continue
                    if isinstance(value, str) and value.strip().upper() in empty:
                        continue
                    return True
                channel = str(row.get("channel") or "").strip().upper()
                return bool(channel and channel not in empty
                    and not re.fullmatch(r"CH[-_ ]?\d+", channel))
            def is_ndd(row):
                code = str(row["indication"] or "").strip().upper()
                return code in {"NDD", "NONE", "NO DEFECT"} or (
                    code in {"", "/"} and not has_wear_signal(row))
            expected = "defect" if "WAR" in codes else "incomplete" if any(not is_ndd(row) for row in raw) else "NDD" if raw else "missing"
            assert tube["coverage"] == expected, (outage, tube["tube"], codes)
            depths = [row["percent"] for row in raw
                      if str(row["indication"] or "").strip().upper() == "WAR"
                      and type(row["percent"]) in (int, float) and 0 <= row["percent"] <= 100]
            assert tube["max_depth"] == (max(depths) if depths else None), (outage, tube["tube"])
            assert tube["records"] == len(raw), (outage, tube["tube"])
            if tube["state_recorded"]:
                last = max((row for row in states if int(row["thimble_id"]) == tube["tube"]
                            and row["outage"][:-2] == outage[:-2] and row["outage"][-2:] <= outage[-2:]),
                           key=lambda row: row["outage"][-2:])
                assert tube["source"] == last["source"], (outage, tube["tube"])
                assert tube["remarks"] == last["note"], (outage, tube["tube"])
        if snapshot["unit"] not in expected_latest or snapshot["order"] > expected_latest[snapshot["unit"]]["order"]:
            expected_latest[snapshot["unit"]] = snapshot
    for site, summary in actual["site_summary"].items():
        chosen = [row for row in expected_latest.values() if not site or row["site"] == site]
        reported = sum(tube["coverage"] != "missing" for row in chosen for tube in row["tubes"])
        total = len(chosen) * 50
        assert summary["units"] == len(chosen), site
        assert summary["total"] == total and summary["reported"] == reported, site
        assert summary["coverageRate"] == (reported / total * 100 if total else 0), site
        assert summary["findings"] == sum(tube["coverage"] == "defect" for row in chosen for tube in row["tubes"]), site
    return {
        "database": str(database), "queries": {"detection": sql, "maintenance": state_sql},
        "checked_snapshots": len(actual["snapshots"]),
        "checked_channels": len(actual["snapshots"]) * 50,
        "summary": actual["summary"], "site_summary": actual["site_summary"],
        "units": actual["units"], "passed": True,
    }


if __name__ == "__main__":
    print(json.dumps(verify(sys.argv[1]), ensure_ascii=False))
