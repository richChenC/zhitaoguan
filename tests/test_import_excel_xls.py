import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "backend"))

from src.backend import server  # noqa: E402
from tests import xls_fixtures as fx  # noqa: E402

DETAIL_HEADERS = ["大修号", "电站名称", "机组号", "通道编号", "在堆芯内的位置",
                  "幅值", "相位", "磨损深度", "三字码", "测量通道", "磨损位置", "分析人员"]
DETAIL_ROWS = [
    ["H209", "大亚湾", 2, 1, "", 5.07, 258, 22, "WAR", "P1: 4-6", "P1+10", "MQQ"],
    ["H209", "大亚湾", 2, 2, "", 4.91, 12, 51, "NDD", "", "", "MQQ"],
]
SECOND_HEADERS = ["大修号", "机组号", "通道编号", "在堆芯内的位置", "幅值", "三字码", "磨损位置"]
SECOND_ROWS = [["H208", 2, 3, "", 3.2, "WAR", "P2"]]


class ImportExcelXlsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_patch = patch.object(server, "DB_PATH", self.root / "test.db")
        self.output_patch = patch.object(server, "EXCEL_DIR", self.root / "exports")
        self.db_patch.start()
        self.output_patch.start()
        server.init_db()

    def tearDown(self):
        self.output_patch.stop()
        self.db_patch.stop()
        self.temp.cleanup()

    def build(self, name, sheets):
        source = self.root / name
        fx.build_xls(source, sheets)
        return source

    def test_xls_single_sheet_import_records_mapping(self):
        source = self.build("single.xls", [("标准检查表", [DETAIL_HEADERS] + DETAIL_ROWS)])
        result = server.import_excel_file(str(source))
        self.assertFalse(result.get("requires_indication_decision", False))
        self.assertEqual(result["parsed"], 2)
        self.assertEqual(result["inserted"], 2)
        self.assertEqual([sheet["sheet"] for sheet in result["sheets"]], ["标准检查表"])
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM findings").fetchone()[0], 2)
            mappings = db.execute("SELECT sheet_name, header_row, mapping_json FROM import_excel_mappings").fetchall()
        self.assertEqual(len(mappings), 1)
        self.assertEqual(mappings[0][0], "标准检查表")
        self.assertEqual(mappings[0][1], 1)
        import json
        self.assertEqual(json.loads(mappings[0][2])["机组号"], 3)

    def test_xls_multi_sheet_skips_summary_and_exception_sheets(self):
        source = self.build("multi.xls", [
            ("缺陷明细表", [DETAIL_HEADERS] + DETAIL_ROWS),
            ("管子汇总表", [["站点代码", "机组号", "大修号", "通道编号", "堆芯位置", "最大报告百分比"],
                            ["H", 2, "H209", 1, "A1", 48]]),
            ("跨组相同缺陷", [["核查组", "大修", "机组", "通道编号", "分析人员"],
                              [1, "H209", 2, 1, "MQQ"]]),
        ])
        result = server.import_excel_file(str(source))
        self.assertEqual([sheet["sheet"] for sheet in result["sheets"]], ["缺陷明细表"])
        self.assertEqual(result["inserted"], 2)

    def test_xls_converted_rpt_keeps_remarks_without_inventing_states(self):
        source = self.build("converted-rpt.xls", [
            ("缺陷明细表", [DETAIL_HEADERS + ["备注", "堵管移位信息"],
                           DETAIL_ROWS[0] + ["检查后换管", ""]]),
            ("RPT导入说明", [["THIMBLE_RPT_CONVERTED_V1"]]),
        ])
        result = server.import_excel_file(str(source))
        repeated = server.import_excel_file(str(source))
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(result["state_recognition"], dict(applied=0, pending=0, skipped=0))
        self.assertEqual(repeated["skipped"], 1)
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT analysis FROM findings").fetchone()[0], "检查后换管")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tube_states").fetchone()[0], 0)
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM inspection_state_candidates WHERE status='pending'"
            ).fetchone()[0], 0)

    def test_mapping_override_imports_only_requested_sheet(self):
        source = self.build("override.xls", [
            ("第一张表", [DETAIL_HEADERS] + DETAIL_ROWS),
            ("第二张表", [SECOND_HEADERS] + SECOND_ROWS),
        ])
        result = server.import_excel_file(str(source), mapping={
            "sheet": "第二张表", "header_row": 1,
            "columns": {"大修号": 1, "机组号": 2, "通道编号": 3, "在堆芯内的位置": 4, "幅值": 5,
                        "三字码": 6, "磨损位置": 7},
        })
        self.assertEqual(result["sheet"], "第二张表")
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(len(result["sheets"]), 1)
        with server.connect() as db:
            rows = db.execute("SELECT sheet_name FROM import_excel_mappings").fetchall()
            self.assertEqual([row[0] for row in rows], ["第二张表"])
            self.assertEqual(db.execute("SELECT unit_id FROM findings").fetchone()[0], 2)

    def test_mapping_override_rejects_sheet_without_measurement_column(self):
        source = self.build("reject.xls", [("汇总", [["机组号", "通道编号"], [2, 1]])])
        with self.assertRaisesRegex(ValueError, "幅值"):
            server.import_excel_file(str(source), mapping={
                "sheet": "汇总", "header_row": 1, "columns": {"机组号": 1, "通道编号": 2}})

    def test_inspect_reports_every_sheet_with_recognized_flag(self):
        source = self.build("inspect.xls", [
            ("缺陷明细表", [DETAIL_HEADERS] + DETAIL_ROWS),
            ("管子汇总表", [["站点代码", "机组号", "大修号", "通道编号", "堆芯位置"],
                            ["H", 2, "H209", 1, "A1"]]),
        ])
        report = server.inspect_excel_file(str(source))
        by_name = {sheet["name"]: sheet for sheet in report["sheets"]}
        self.assertTrue(by_name["缺陷明细表"]["recognized"])
        self.assertFalse(by_name["管子汇总表"]["recognized"])
        self.assertEqual(by_name["缺陷明细表"]["mapping"]["机组号"], 2)  # 0-based column
        self.assertEqual(by_name["缺陷明细表"]["header_row"], 1)
        self.assertEqual(by_name["管子汇总表"]["columns"][0]["header"], "站点代码")

    def test_reordered_headers_are_detected_by_field_name(self):
        headers = ["幅值(V)", "通道编号", "机组", "大修号", "三字符"]
        rows = [[5.07, 12, 2, "H209", "WAR"]]
        source = self.build("reordered.xls", [("缺陷明细表", [headers] + rows)])

        inspected = server.inspect_excel_file(str(source))["sheets"][0]
        self.assertTrue(inspected["recognized"])
        self.assertEqual(inspected["mapping"]["幅值"], 0)
        self.assertEqual(inspected["mapping"]["通道编号"], 1)
        self.assertEqual(inspected["mapping"]["机组号"], 2)

        result = server.import_excel_file(str(source))
        self.assertEqual(result["inserted"], 1)
        with server.connect() as db:
            row = db.execute(
                "SELECT outage,unit_id,thimble_id,volts,indication FROM findings"
            ).fetchone()
        self.assertEqual(tuple(row), ("H209", 2, 12, 5.07, "WAR"))

    def test_unrecognized_headers_do_not_guess_fields_from_column_positions(self):
        headers = [f"字段{i}" for i in range(30)]
        row = [None] * 30
        row[3], row[4], row[8], row[9] = "H209", 2, 12, "B5"
        source = self.build("unrecognized.xls", [("工作表", [headers, row])])

        inspected = server.inspect_excel_file(str(source))["sheets"][0]
        self.assertFalse(inspected["recognized"])
        with self.assertRaisesRegex(ValueError, "无法识别Excel表头"):
            server.import_excel_file(str(source))

    def test_empty_xlsx_sheet_is_skipped_during_inspection_and_import(self):
        from openpyxl import Workbook

        source = self.root / "empty-sheet.xlsx"
        book = Workbook()
        book.active.title = "空工作表"
        detail = book.create_sheet("H209")
        detail.append(["通道", "幅值", "三字码"])
        detail.append([7, 5.4, "WAR"])
        book.save(source)
        book.close()

        inspected = server.inspect_excel_file(str(source))["sheets"]
        self.assertFalse(inspected[0]["recognized"])
        self.assertTrue(inspected[1]["recognized"])
        result = server.import_excel_file(str(source))
        self.assertEqual(result["parsed"], 1)
        self.assertEqual(result["inserted"], 1)
        with server.connect() as db:
            row = db.execute("SELECT outage, unit_id, thimble_id FROM findings").fetchone()
        self.assertEqual(tuple(row), ("H209", 2, 7))


if __name__ == "__main__":
    unittest.main()
