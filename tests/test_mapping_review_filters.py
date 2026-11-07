import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook
from src.backend import import_audit, server


class MappingReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patcher = patch.object(server, "DB_PATH", Path(self.temp.name) / "test.db")
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        server.init_db()

    def test_mapping_hints_support_both_parities_and_unknown_position(self):
        with server.connect() as db:
            batch = db.execute("INSERT INTO import_batches(started_at,source_path,import_kind,status) VALUES('now','test.xlsx','excel','completed')").lastrowid
            for unit, tube, position in ((1, 1, "B5"), (2, 1, "L11"), (2, 2, "A1")):
                import_audit.issue(db, batch, "MAPPING_ERROR", "mismatch", row=unit * 10 + tube,
                                   payload={"机组号": unit, "通道编号": tube, "在堆芯内的位置": position})
        items = import_audit.quality(server, batch)["issues"]
        hints = {(item["mapping_hint"]["unit"], item["mapping_hint"]["tube"]): item["mapping_hint"] for item in items}
        self.assertEqual((hints[1, 1]["expected_position"], hints[1, 1]["position_tube"]), ("L11", 42))
        self.assertEqual((hints[2, 1]["expected_position"], hints[2, 1]["position_tube"]), ("B5", 36))
        self.assertEqual((hints[2, 2]["expected_position"], hints[2, 2]["position_tube"]), ("C8", None))

    def test_column_filter_applies_before_pagination_and_to_core(self):
        with server.connect() as db:
            for tube in range(1, 4):
                db.execute("""INSERT INTO findings(outage,unit_id,thimble_id,position,indication,percent,location,imported_at)
                              VALUES('H209',2,?,?, 'WAR', 20, ?, 'now')""",
                           (tube, server.position_for(2, tube), "Point 1" if tube == 3 else "P4"))
        result = server.query_findings({"column_location": ["Point"], "size": ["1"]})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["thimble_id"], 3)
        self.assertEqual([item["thimble_id"] for item in result["core_items"]], [3])
        self.assertEqual(server.query_findings({"column_location": ["%"]})["total"], 0)

    def test_excel_import_provides_review_hint_and_preserves_position(self):
        path = Path(self.temp.name) / "test.xlsx"
        book = Workbook()
        book.active.title = "H209"
        book.active.append(["大修号", "机组号", "通道编号", "在堆芯内的位置", "三字码", "磨损位置"])
        book.active.append(["H209", 2, 1, "L11", "WAR", "Point 1/4"])
        book.save(path)
        book.close()
        with patch.object(server, "EXCEL_DIR", Path(self.temp.name)):
            batch = server.import_excel_file(str(path))["batch_id"]
        issue = next(item for item in import_audit.quality(server, batch)["issues"] if item["code"] == "MAPPING_ERROR")
        self.assertEqual(issue["mapping_hint"]["expected_position"], "B5")
        self.assertEqual(issue["mapping_hint"]["position_tube"], 36)
        with server.connect() as db:
            row = db.execute("SELECT position,location FROM findings").fetchone()
        self.assertEqual(tuple(row), ("L11", "Point 1/4"))

    def test_channel_change_audits_the_linked_position(self):
        with server.connect() as db:
            finding_id = db.execute("""INSERT INTO findings(outage,unit_id,thimble_id,position,imported_at)
                                       VALUES('H209',2,1,'B5','now')""").lastrowid
        server.update_finding_field({"id": finding_id, "field": "thimble_id", "value": 2, "expected_value": 1})
        with server.connect() as db:
            edits = {row["field_name"]: (json.loads(row["before_json"]), json.loads(row["after_json"]))
                     for row in db.execute("SELECT * FROM finding_edit_history WHERE finding_id=?", (finding_id,))}
        self.assertEqual(edits["thimble_id"], (1, 2))
        self.assertEqual(edits["position"], ("B5", "C8"))


if __name__ == "__main__":
    unittest.main()
