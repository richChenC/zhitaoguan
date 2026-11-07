from enterprise_fixtures import mark_legacy
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from openpyxl import Workbook, load_workbook

from src.backend import server, import_audit


# Independently transcribed from the official plate supplied on 2026-10-20.
ODD = "L11 G14 N7 H13 J12 R8 N12 N10 L14 J15 H11 F13 J7 L5 N5 L8 N8 L6 J10 L9 F9 C12 G7 L4 J5 M3 G9 E11 F11 D12 F6 B10 D7 E5 H3 J3 H6 H4 F8 D10 B7 B5 D3 D5 F2 H1 B8 F4 C8 A9".split()
EVEN = "B5 C8 E11 D10 D12 C12 B10 B7 A9 B8 D5 D3 F6 H13 F9 G14 F13 E5 F11 D7 G7 F2 H6 H11 J10 J12 J15 G9 F8 F4 H3 H1 J3 N12 L9 L11 L14 J5 J7 H4 M3 N5 R8 N7 N8 N10 L5 L8 L6 L4".split()


class OfficialCoreMappingTests(unittest.TestCase):
    def test_all_hundred_mappings_and_all_unit_parities(self):
        for unit in range(1, 121):
            expected = ODD if unit % 2 else EVEN
            self.assertEqual([server.position_for(unit, tube) for tube in range(1, 51)], expected)
            self.assertEqual(len(set(expected)), 50)
        self.assertEqual(set(ODD), set(EVEN))

    def test_desktop_model_and_analysis_match_official_mapping(self):
        ui = server.STATIC
        for filename in ("app.js", "visualizations/reference-thimble/defect-location.js"):
            text = (ui / filename).read_text(encoding="utf-8")
            for parity, expected in (("ODD", ODD), ("EVEN", EVEN)):
                actual = re.search(rf'{parity}_POSITIONS\s*=\s*[\'\"]([^\'\"]+)', text).group(1).split()
                self.assertEqual(actual, expected, filename)
        text = (ui / "modules/analytics/chart-3-4.js").read_text(encoding="utf-8")
        for parity, expected in (("odd", ODD), ("even", EVEN)):
            actual = json.loads(re.search(rf'{parity}:\s*(\{{[^}}]+\}})', text).group(1))
            self.assertEqual([actual[str(i)] for i in range(1, 51)], expected)
        self.assertNotRegex(text, r"POS_MAP\.(odd|even)\[")
        index = json.loads((ui / "modules/analytics/data/thimble-ledger/index.json").read_text(encoding="utf-8"))
        for parity, expected in (("odd", ODD), ("even", EVEN)):
            self.assertEqual([index["posMap"][parity][str(i)] for i in range(1, 51)], expected)
        for unit in index["units"].values():
            expected = ODD if unit["unitNo"] % 2 else EVEN
            for outage in unit["outages"]:
                for channel in outage["channels"]:
                    self.assertEqual(channel["pos"], expected[int(channel["ch"]) - 1])

    def test_legacy_database_correction_is_scoped_audited_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(server, "DB_PATH", Path(directory) / "test.db"):
            server.init_db()
            with server.connect() as db:
                for unit, tube, position in ((1, 15, "M5"), (2, 42, "M5"), (3, 15, "N5"), (2, 41, "M3"), (1, 14, "M5")):
                    db.execute("INSERT INTO findings(outage,unit_id,thimble_id,position,imported_at) VALUES(?,?,?,?,?)",
                               (f"H{unit}09", unit, tube, position, "now"))
            mark_legacy(server)
            server.init_db()
            server.init_db()
            self.assertTrue(any((Path(directory)/'backups').glob('migration-*.db')))
            with server.connect() as db:
                self.assertEqual([r[0] for r in db.execute("SELECT position FROM findings ORDER BY id")], ["N5", "N5", "N5", "M3", "M5"])
                audit = db.execute("SELECT before_json,after_json FROM core_mapping_corrections").fetchall()
                self.assertEqual(len(audit), 2)
                for before, after in audit:
                    self.assertEqual(json.loads(before)["position"], "M5")
                    self.assertEqual(json.loads(after)["position"], "N5")
                for row in db.execute("SELECT * FROM findings WHERE position='N5'"):
                    self.assertEqual(row["business_key"], server.finding_business_key(dict(row)))

    def test_legacy_correction_keeps_import_rollback_and_restore_available(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(server, "DB_PATH", Path(directory) / "test.db"):
            server.init_db()
            with server.connect() as db:
                batch = db.execute("INSERT INTO import_batches(started_at,source_path,import_kind,status) VALUES('now','old.xlsx','excel','completed')").lastrowid
                finding = db.execute("INSERT INTO findings(outage,unit_id,thimble_id,position,site_code,imported_at,import_batch_id) VALUES('H209',2,42,'M5','H','now',?)", (batch,)).lastrowid
                import_audit.remember_change(db, batch, finding)
                snapshot = db.execute("SELECT after_json FROM import_finding_changes").fetchone()[0]
            mark_legacy(server)
            server.init_db()
            import_audit.change_batch(server, batch, "rollback")
            import_audit.change_batch(server, batch, "restore")
            with server.connect() as db:
                row = db.execute("SELECT position,is_deleted FROM findings").fetchone()
                self.assertEqual(tuple(row), ("N5", 0))
                self.assertEqual(db.execute("SELECT after_json FROM import_finding_changes").fetchone()[0], snapshot)

    def test_excel_legacy_value_is_audited_corrected_and_reimport_deduplicated(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(server, "DB_PATH", Path(directory) / "test.db"), patch.object(server, "EXCEL_DIR", Path(directory)):
            server.init_db()
            source = Path(directory) / "legacy.xlsx"
            book = Workbook()
            book.active.append(["大修号", "机组号", "通道编号", "在堆芯内的位置", "三字码", "磨损位置"])
            book.active.append(["H209", 2, 42, "M5", "WAR", "P1"])
            book.save(source)
            book.close()
            result = server.import_excel_file(str(source), "review")
            self.assertEqual(result["inserted"], 1)
            with server.connect() as db:
                self.assertEqual(db.execute("SELECT position FROM findings").fetchone()[0], "N5")
                issue = db.execute("SELECT payload_json FROM validation_issues WHERE code='MAPPING_ERROR'").fetchone()
                self.assertIn("M5", issue[0])
            self.assertEqual(server.import_excel_file(str(source), "review")["inserted"], 0)
            source.unlink()

    def test_restore_of_old_backup_repairs_mapping_before_outputs(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(server, "DB_PATH", Path(directory) / "test.db"), patch.object(server, "EXCEL_DIR", Path(directory)):
            server.init_db()
            with server.connect() as db:
                db.execute("INSERT INTO findings(outage,unit_id,thimble_id,position,site_code,imported_at) VALUES('H209',2,42,'M5','H','now')")
            mark_legacy(server)
            old = Path(directory)/"legacy.db"
            server._sqlite_backup_to(server.DB_PATH,old)
            server.init_db()
            backup = {"path":str(old)}
            server.restore_database(backup["path"])
            with server.connect() as db:
                self.assertEqual(db.execute("SELECT position FROM findings").fetchone()[0], "N5")
            exported = import_audit.export_quality(server)
            book = load_workbook(exported["file_path"], read_only=True)
            try:
                self.assertEqual(book["管位映射修正"].max_row, 2)
                self.assertIn('"position": "M5"', book["管位映射修正"].cell(2, 4).value)
                self.assertIn('"position": "N5"', book["管位映射修正"].cell(2, 5).value)
            finally:
                book.close()
