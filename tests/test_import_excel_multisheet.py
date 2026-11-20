"""同一 Excel 多工作表：全部有效表头的工作表都应导入，无效表只记诊断。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook

from src.backend import import_audit, server

HEADER = ["大修号", "机组号", "通道编号", "在堆芯内的位置", "三字码", "磨损位置"]


class MultiSheetImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, value in (("DB_PATH", self.root / "multi.db"), ("EXCEL_DIR", self.root / "exports")):
            patcher = patch.object(server, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        server.init_db()

    def book(self, rows_by_sheet, extra=None):
        source = self.root / "multi.xlsx"
        book = Workbook()
        book.active.title = next(iter(rows_by_sheet))
        book.active.append(HEADER)
        for row in rows_by_sheet[book.active.title]:
            book.active.append(row)
        for title, rows in list(rows_by_sheet.items())[1:]:
            sheet = book.create_sheet(title)
            sheet.append(HEADER)
            for row in rows:
                sheet.append(row)
        if extra:
            sheet = book.create_sheet(extra[0])
            sheet.append(extra[1])
        book.save(source)
        book.close()
        return source

    def test_all_valid_sheets_are_imported(self):
        source = self.book({"第一组": [["H209", 2, 1, "B5", "WAR", "P1"]],
                            "第二组": [["H209", 2, 2, "B6", "NDD", ""]]})
        result = server.import_excel_file(str(source))
        self.assertEqual(result["inserted"], 2)
        with server.connect() as db:
            tubes = {row[0] for row in db.execute("SELECT thimble_id FROM findings")}
        self.assertEqual(tubes, {1, 2})

    def test_invalid_sheet_records_diagnostic_without_blocking(self):
        source = self.book({"第一组": [["H209", 2, 1, "B5", "WAR", "P1"]]},
                           extra=("说明", ["本表为填写说明，无检测数据"]))
        result = server.import_excel_file(str(source))
        self.assertEqual(result["inserted"], 1)
        quality = import_audit.quality(server, result["batch_id"])
        self.assertIn("SHEET_SKIPPED", {item["code"] for item in quality["issues"]})


if __name__ == "__main__":
    unittest.main()
