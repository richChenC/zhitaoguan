"""Verify the supplied workbook end-to-end; --apply resets the live DB after backup."""
import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from openpyxl import load_workbook
from src.backend import server


SOURCE_FIELDS = [
    ("thimble_id", int), ("position", str), ("volts", float), ("degrees", float),
    ("percent", float), ("indication", str), ("channel", str), ("location", str),
    ("probe", str), ("analyst", str), ("filename", str), ("calgroup", str),
    ("analysis", str), ("maintenance_text", str),
]


def expected_rows(source):
    book = load_workbook(source, read_only=True, data_only=True)
    records = []
    try:
        for sheet in book.worksheets:
            header = next(sheet.iter_rows(values_only=True))
            assert len(header) == len(SOURCE_FIELDS), (sheet.title, header)
            for row in sheet.iter_rows(min_row=2, values_only=True):
                if not any(value not in (None, "") for value in row):
                    continue
                record = {"outage": sheet.title, "unit_id": int(sheet.title[-3])}
                for (field, cast), value in zip(SOURCE_FIELDS, row):
                    record[field] = str(value or "") if cast is str else server.number(value, cast)
                records.append(record)
    finally:
        book.close()
    return records


def read_rows():
    with server.connect() as db:
        return [dict(row) for row in db.execute("SELECT * FROM findings WHERE is_deleted=0 ORDER BY id")]


def compare(expected, actual):
    assert len(actual) == len(expected), (len(actual), len(expected))
    fields = list(expected[0])
    order = lambda row: json.dumps({field: row.get(field) for field in fields},
                                   ensure_ascii=False, sort_keys=True)
    expected = sorted(expected, key=order)
    actual = sorted(actual, key=order)
    checked = 0
    for index, (reference, record) in enumerate(zip(expected, actual), 1):
        for field, value in reference.items():
            assert record[field] == value, (index, field, value, record[field])
            checked += 1
    return checked


def state_values():
    return sorted(
        ({key: row.get(key) for key in (
            "outage", "unit_id", "thimble_id", "state", "offset_mm",
            "offset_confirmed", "unsigned_offset_mm", "note", "source",
        )} for row in server.query_states()["items"]),
        key=lambda row: (row["outage"], row["unit_id"], row["thimble_id"]),
    )


def verify(source, output, apply):
    evidence = {"source": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "started_at": datetime.now().isoformat(), "live_database_reset": apply}
    expected = expected_rows(source)
    evidence["source_records"] = len(expected)
    evidence["source_sheets"] = len({row["outage"] for row in expected})
    evidence["scope_counts"] = dict(sorted(Counter(row["outage"] for row in expected).items()))
    try:
        server.init_db()
        evidence["database"] = str(server.DB_PATH)
        if apply:
            evidence["clear"] = server.clear_database()
            with server.connect() as db:
                remaining = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                             for table in evidence["clear"]["cleared"] if table != "operation_logs"}
            assert all(count == 0 for count in remaining.values()), remaining
            evidence["cleared_counts_verified"] = remaining
        started = time.monotonic()
        inspected = server.inspect_excel_file(str(source))
        assert len([sheet for sheet in inspected["sheets"] if sheet["recognized"]]) == evidence["source_sheets"]
        result = server.import_excel_file(str(source), "review", operator="综合台账验证")
        evidence["import"] = result
        with server.connect() as db:
            evidence["validation_codes"] = {row["code"]: row["count"] for row in db.execute(
                "SELECT code,COUNT(*) count FROM validation_issues WHERE batch_id=? GROUP BY code",
                (result["batch_id"],))}
        evidence["import_seconds"] = round(time.monotonic() - started, 3)
        assert result["inserted"] == len(expected) and result["invalid_count"] == 0
        evidence["source_fields_verified"] = compare(expected, read_rows())
        initial_states = state_values()
        initial_pending = len(server.query_states()["pending"])
        evidence["state_events"] = len(initial_states)
        evidence["pending_states"] = initial_pending
        started = time.monotonic()
        exported = server.export_data_ledger({})
        evidence["export"] = exported
        evidence["export_seconds"] = round(time.monotonic() - started, 3)
        assert exported["rows"] == len(expected)
        with patch.object(server, "DB_PATH", output / "roundtrip.db"):
            server.init_db()
            roundtrip = server.import_excel_file(exported["file_path"], "review")
            evidence["roundtrip"] = roundtrip
            evidence["roundtrip_fields_verified"] = compare(expected, read_rows())
            assert state_values() == initial_states, "Maintenance event text or distance changed during roundtrip"
        if not apply:
            duplicate = server.import_excel_file(str(source), "review")
            evidence["duplicate"] = duplicate
            assert duplicate["inserted"] == 0 and duplicate["skipped"] == len(expected)
            assert state_values() == initial_states
            same_db = server.import_excel_file(exported["file_path"], "review")
            evidence["same_database_roundtrip"] = same_db
            assert same_db["updated"] == 0 and same_db["inserted"] == 0
            assert same_db["skipped"] == len(expected)
        with server.connect() as db:
            evidence["integrity"] = db.execute("PRAGMA integrity_check").fetchone()[0]
        assert evidence["integrity"] == "ok"
        assert hashlib.sha256(source.read_bytes()).hexdigest() == evidence["source_sha256"]
        evidence["passed"] = True
        print(json.dumps({key: evidence[key] for key in (
            "passed", "database", "source_sheets", "source_records", "source_fields_verified",
            "roundtrip_fields_verified", "state_events", "pending_states", "import_seconds",
            "export_seconds", "export",
        )}, ensure_ascii=False, indent=2))
    finally:
        (output / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    output = ROOT / "tmp" / ("unified-ledger-live-" if args.apply else "unified-ledger-test-")
    output = output.with_name(output.name + datetime.now().strftime("%Y%m%d-%H%M%S"))
    output.mkdir(parents=True)
    if args.apply:
        verify(args.source.resolve(), output, True)
    else:
        with patch.object(server, "DB_PATH", output / "thimble.db"), \
                patch.object(server, "EXCEL_DIR", output / "exports"):
            verify(args.source.resolve(), output, False)
    print("EVIDENCE", output / "evidence.json")


if __name__ == "__main__":
    main()
