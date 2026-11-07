"""Exercise import, API and export without guessing instrument labels."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook, load_workbook
from src.backend import server, visualization_reporting


class InstrumentLocationPreservationTests(unittest.TestCase):
    def test_rpt_parser_distinguishes_letter_i_from_digit_one(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "instrument.rpt"
            labels = ["PI+168", "P1+168", "Point 1", "M1a4-6"]
            source.write_text(
                "<CitecReport>" + "".join(
                    f"<ReportEntry><Row>{index}</Row><Entry>{index}</Entry>"
                    f"<Uid>instrument-{index}</Uid><Datapoint>{index * 80}</Datapoint>"
                    f"<Location>{label}</Location><Channel>P5</Channel>"
                    "<Indication>WAR</Indication><Percent>26</Percent></ReportEntry>"
                    for index, label in enumerate(labels, 1)) + "</CitecReport>",
                encoding="utf-8")
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            context = server.DataGroupContext(root, "TH1I01CAL00001", site_code="F", unit_id=1, outage="F101")
            findings = server.parse_report(source, context)
            self.assertEqual([f.location for f in findings], labels)
            self.assertEqual([f.channel for f in findings], ["P5"] * 4)
            self.assertEqual([f.indication for f in findings], ["WAR"] * 4)
            self.assertEqual([f.percent for f in findings], [26] * 4)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)

    def test_excel_import_query_and_ledger_export_keep_instrument_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "instrument-labels.xlsx"
            originals = [
                ("M1a4-6", "P5", 26), ("Point 1", "M1a4-6", 29),
                ("Point 4", "M1a4-6", 21), ("PI+168", "P1: 4-6", 47),
                ("", "P1: 4-6", 52),
            ]
            book = Workbook()
            sheet = book.active
            sheet.append(["大修号", "机组号", "通道编号", "三字码", "磨损深度", "测量通道", "磨损位置"])
            for tube, (location, channel, depth) in enumerate(originals, 1):
                sheet.append(["F101", 1, tube, "WAR", depth, channel, location])
            book.save(source)
            book.close()
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            with patch.object(server, "DB_PATH", root / "test.db"), \
                 patch.object(server, "EXCEL_DIR", root / "exports"):
                server.init_db()
                first = server.import_excel_file(str(source))
                second = server.import_excel_file(str(source))
                self.assertEqual(first["inserted"], 5)
                self.assertEqual(second["inserted"], 0)
                with server.connect() as db:
                    stored = [tuple(row) for row in db.execute(
                        "SELECT location,channel,percent FROM findings ORDER BY thimble_id")]
                self.assertEqual(stored, originals)
                rows = server.query_all_findings({"outage": ["F101"], "unit": ["1"]})
                self.assertEqual([(r["location_raw"], r["channel"], r["percent"]) for r in rows], originals)
                self.assertEqual([r["location"] for r in rows], ["M1a4-6", "Point 1", "Point 4", "PI+168", "-"])
                self.assertEqual([r["p_offset"] for r in rows], [None, 0, 0, None, None])
                result = visualization_reporting.build(server, {})
                self.assertEqual(result["trends"][0]["total"], 175)
                self.assertEqual(result["trends"][0]["positions"], {"未解析": 125, "P1": 29, "P4": 21})
                tubes = result["snapshots"][0]["tubes"][:5]
                self.assertEqual([t["max_depth"] for t in tubes], [r[2] for r in originals])
                self.assertTrue(all(t["coverage"] == "defect" for t in tubes))
                exported = server.export_data_ledger({"outage": "F101", "unit": 1})
                book = load_workbook(exported["file_path"], data_only=True)
                try:
                    sheet = book["综合台账"]
                    headers = [cell.value for cell in sheet[1]]
                    actual = [(
                        row[headers.index("磨损位置")] or "",
                        row[headers.index("测量通道（记录通道）")] or "",
                        row[headers.index("磨损深度")],
                    ) for row in sheet.iter_rows(min_row=2, values_only=True)]
                    self.assertEqual(actual, originals)
                finally:
                    book.close()
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
