"""Fifty-tube coverage is mandatory; missing evidence must never become NDD."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from src.backend import analysis_reporting as reporting, reference_report, report_forms, server


class ComparisonCoverageTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        for key, path in (("DB_PATH", "test.db"), ("REPORT_DIR", "reports"), ("EXCEL_DIR", "excel")):
            item = patch.object(server, key, Path(folder.name) / path)
            item.start()
            self.addCleanup(item.stop)
        server.init_db()

    def insert(self, outage, tube, indication="NDD", location="", percent=None):
        with server.connect() as db:
            return db.execute("""INSERT INTO findings(outage,unit_id,thimble_id,position,
                indication,location,percent,volts,imported_at) VALUES(?,1,?,?,?,?,?,1.78,'test')""",
                (outage, tube, server.position_for(1, tube), indication, location, percent)).lastrowid

    def complete(self):
        for outage in ("N107", "N108"):
            for tube in range(1, 51):
                self.insert(outage, tube, "WAR" if tube == 1 else "NDD", "P1+127" if tube == 1 else "", 28 if tube == 1 else None)

    def payload(self):
        return dict(kind="comparison", site="N", unit=1, outage="N108", old="N107")

    def test_all_ndd_tubes_remain_visible_and_do_not_count_as_defects(self):
        self.complete()
        result = server.compare("N107", "N108", 1)
        self.assertEqual([r["thimble_id"] for r in result["items"]], list(range(1, 51)))
        self.assertTrue(result["coverage_complete"])
        self.assertEqual(result["summary"]["R"], 1)
        self.assertEqual(result["summary"]["NDD"], 49)
        snapshot = reporting.report_snapshot(server, self.payload())
        self.assertEqual(len(snapshot["headers"]), 10)
        self.assertTrue(all(len(r) == 10 for r in snapshot["values"]))
        self.assertEqual(len(snapshot["values"]), 1)
        self.assertEqual(snapshot["values"][0][5:10], ["P1+127mm", 1.78, 28, "P1+127mm", "R"])
        self.assertEqual(snapshot["detection_counts"][0]["ndd_tubes"], 49)
        self.assertEqual(snapshot["detection_counts"][0]["war_records"], 1)

    def test_multiple_positions_and_unmatched_history_are_not_lost(self):
        self.complete()
        self.insert("N107", 1, "WAR", "P4+42", 38)
        self.insert("N108", 1, "WAR", "P5", 25)
        result = server.compare("N107", "N108", 1)
        self.assertEqual(len(result["items"]), 52)
        self.assertEqual(len({r["thimble_id"] for r in result["items"]}), 50)
        historical = [r for r in result["items"] if r["row_kind"] == "historical_only"]
        self.assertEqual([r["old_location"] for r in historical], ["P4+42"])
        self.assertEqual(historical[0]["comparison"], "待确认")
        self.assertEqual(result["summary"]["historical_unmatched"], 1)

    def test_missing_tube_is_not_ndd_and_blocks_every_formal_export(self):
        self.complete()
        with server.connect() as db:
            db.execute("UPDATE findings SET is_deleted=1 WHERE outage='N108' AND thimble_id=27")
        result = server.compare("N107", "N108", 1)
        self.assertFalse(result["coverage_complete"])
        self.assertEqual(result["missing_tubes"]["N108"], [27])
        row = next(r for r in result["items"] if r["thimble_id"] == 27)
        self.assertEqual(row["row_kind"], "missing")
        self.assertEqual(row["comparison"], "待确认")
        self.assertNotEqual(row["indication"], "NDD")
        snapshot = reporting.report_snapshot(server, self.payload())
        self.assertEqual(snapshot["detection_counts"][0]["missing_tubes"], [27])
        self.assertEqual(snapshot["coverage"][0]["missing"], [27])
        self.assertTrue(all(row[1] != 27 for row in snapshot["values"]))
        for fmt in ("docx", "xlsx", "csv"):
            with self.subTest(fmt=fmt), self.assertRaisesRegex(ValueError, "N108 缺少通道 27"):
                reporting.export(server, {**self.payload(), "snapshot_id": snapshot["snapshot_id"], "format": fmt})
        for writer in (server.export_comparison_docx, server.export_comparison_excel):
            with self.assertRaisesRegex(ValueError, "N108 缺少通道 27"):
                writer("N107", "N108", 1)
        with self.assertRaisesRegex(ValueError, "N108 缺少通道 27"):
            server.export_comparison_excel_many(["N107", "N108"], 1)

    def test_entirely_missing_side_remains_visible(self):
        self.insert("N107", 1, "WAR", "P4", 25)
        result = server.compare("N107", "N108", 1)
        self.assertEqual(result["coverage"][1]["present"], 0)
        self.assertEqual(len({r["thimble_id"] for r in result["items"]}), 50)
        self.assertEqual(result["items"][0]["old_percent"], 25)
        self.assertFalse(reporting.report_snapshot(server, self.payload())["coverage_complete"])

    def test_incomplete_conclusion_never_becomes_ndd(self):
        self.complete()
        with server.connect() as db:
            db.execute("UPDATE findings SET is_deleted=1 WHERE thimble_id=1 AND outage IN ('N107','N108')")
        self.insert("N107", 1, "", "P1", 20)
        self.insert("N108", 1, "NDD")
        result = server.compare("N107", "N108", 1)
        row = next(r for r in result["items"] if r["thimble_id"] == 1)
        self.assertEqual(row["row_kind"], "historical_only")
        self.assertEqual(row["comparison"], "待确认")
        self.assertNotEqual(row["comparison"], "NDD")
        self.assertTrue(any(w["code"] == "unmatched_history" and w["thimble_id"] == 1
                            for w in result["warnings"]))

    def test_comparison_selection_cannot_remove_tubes(self):
        self.complete()
        with self.assertRaisesRegex(ValueError, "全部50根管"):
            reporting.report_snapshot(server, {**self.payload(), "finding_ids": [1]})

    def test_form_keeps_indications_merged_groups_and_checks_50_tube_coverage(self):
        self.complete()
        self.insert("N108", 1, "WAR", "P4", 35)
        snapshot = reporting.report_snapshot(server, self.payload())
        _, document = report_forms.documents(server, snapshot)
        rows = document.findall("w:body/w:tbl/w:tr", report_forms.NS)[2:-1]
        self.assertEqual(len(rows), 2)
        self.assertEqual(snapshot["detection_counts"][0]["tubes"], 50)
        self.assertTrue(snapshot["coverage_complete"])
        self.assertTrue(all(r.find('w:trPr/w:tblHeader', report_forms.NS) is not None
                            for r in document.findall('w:body/w:tbl/w:tr', report_forms.NS)[:2]))
        self.assertIn('表5 涡流检验结果比对表', ''.join(document.itertext()))
        self.assertTrue(all(len(r.findall("w:tc", report_forms.NS)) == 10 for r in rows))
        self.assertEqual(rows[0].find("w:tc[2]/w:tcPr/w:vMerge", report_forms.NS).get(f"{{{report_forms.W}}}val"), "restart")
        for template_id in (None, "comparison"):
            payload = {**self.payload(), **({"template_id": template_id} if template_id else {})}
            snapshot = reporting.report_snapshot(server, payload)
            for fmt in ("docx", "xlsx"):
                result = reporting.export(server, {**payload, "format": fmt, "snapshot_id": snapshot["snapshot_id"]})
                self.assertTrue(Path(result["file_path"]).is_file())
                if fmt == "docx":
                    with ZipFile(result["file_path"]) as archive:
                        doc = ET.fromstring(archive.read("word/document.xml"))
                    data = doc.findall("w:body/w:tbl/w:tr", report_forms.NS)[2:-1]
                    tubes = {int(''.join(r.findall('w:tc', report_forms.NS)[1].itertext())) for r in data
                             if ''.join(r.findall('w:tc', report_forms.NS)[1].itertext()).isdigit()}
                    self.assertEqual(tubes, {1})

    def test_source_form_draft_cannot_erase_a_tube(self):
        self.complete()
        payload = {**self.payload(), "template_id": "comparison"}
        snapshot = reporting.report_snapshot(server, payload)
        key = next(c["key"] for c in snapshot["editable_cells"] if c["label"] == "表8 第3行第2列")
        with self.assertRaisesRegex(ValueError, "保留当前显示记录"):
            reporting.report_snapshot(server, {**payload, "draft_edits": [{"key": key, "value": ""}]})


if __name__ == "__main__":
    unittest.main()
