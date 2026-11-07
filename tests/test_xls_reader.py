import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "backend"))

from xls_reader import XlsError, load_workbook  # noqa: E402
from tests import xls_fixtures as fx  # noqa: E402

REFERENCE_DATA = (Path(__file__).resolve().parents[1] / "项目资料"
                  / "02_业务参考资料" / "孔姐发的" / "指套管数据测试 202007")
REAL_FILES = [
    REFERENCE_DATA / "大亚湾" / "L3.xls",
    REFERENCE_DATA / "大亚湾" / "L4.xls",
    REFERENCE_DATA / "宁德" / "宁德4台机组指套管割管移位信息汇总20200804.xls",
]


class XlsReaderTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)

    def build(self, name, sheets, **kwargs):
        target = self.root / name
        fx.build_xls(target, sheets, **kwargs)
        return target

    def test_reads_small_workbook_from_mini_stream(self):
        sheets = [("数据", [["电站名称", "机组号", "通道编号"], ["大亚湾", 2, 42], ["大亚湾", 2, 7]])]
        book = load_workbook(self.build("small.xls", sheets))
        self.assertEqual(book.sheetnames, ["数据"])
        sheet = book["数据"]
        self.assertEqual(sheet.max_row, 3)
        self.assertEqual(sheet.max_column, 3)
        self.assertEqual([cell.value for cell in sheet[1]], ["电站名称", "机组号", "通道编号"])
        self.assertEqual([cell.value for cell in sheet[2]], ["大亚湾", 2, 42])
        self.assertEqual([cell.value for cell in sheet[3]], ["大亚湾", 2, 7])
        rows = list(sheet.iter_rows(min_row=2, values_only=True))
        self.assertEqual(rows, [("大亚湾", 2, 42), ("大亚湾", 2, 7)])

    def test_reads_large_workbook_from_regular_sectors(self):
        rows = [["大修", "机组", "通道", "深度"]]
        for index in range(600):
            rows.append([f"H{200 + index // 50}", 2, index % 50 + 1, round(index * 0.37, 2)])
        book = load_workbook(self.build("large.xls", [("缺陷明细", rows)]))
        sheet = book["缺陷明细"]
        self.assertEqual(sheet.max_row, 601)
        self.assertEqual(sheet.max_column, 4)
        self.assertEqual(sheet.cell(601, 4).value, round(599 * 0.37, 2))
        self.assertEqual(sheet.cell(2, 1).value, "H200")

    def test_reads_sst_strings_across_continue_boundaries(self):
        # Force small CONTINUE chunks so strings (and their flag bytes) straddle.
        sheets = [("表一", [["列一", "列二", "列三"],
                            ["在堆芯内的位置", "磨损深度", "测量通道"],
                            ["割管移位（切除42mm）", 41.5, "P1: 4-6"]]),
                  ("表二", [["通道", "位置"], ["1", "B5"], ["2", "C8"]])]
        book = load_workbook(self.build("chunked.xls", sheets, sst_chunk_size=29))
        self.assertEqual(book.sheetnames, ["表一", "表二"])
        first = book["表一"]
        self.assertEqual([cell.value for cell in first[2]], ["在堆芯内的位置", "磨损深度", "测量通道"])
        self.assertEqual([cell.value for cell in first[3]], ["割管移位（切除42mm）", 41.5, "P1: 4-6"])
        self.assertEqual([cell.value for cell in book["表二"][2]], ["1", "B5"])

    def test_reads_rich_text_string_and_formula_result(self):
        sheets = [("混合", [["说明", "计算"],
                            ["=FORMULA_TEXT", "富文本字符串"],
                            ["普通", 3.25]])]
        book = load_workbook(self.build("mixed.xls", sheets))
        sheet = book["混合"]
        self.assertEqual(sheet.cell(2, 1).value, "计算2-1")
        self.assertEqual(sheet.cell(2, 2).value, "富文本字符串")
        self.assertEqual(sheet.cell(3, 2).value, 3.25)

    def test_reads_rk_mulrk_and_blank_cells(self):
        sheets = [("数值", [[None, 100, 200, 300, 1.5, True, "文本"]])]
        book = load_workbook(self.build("numbers.xls", sheets))
        row = [cell.value for cell in book["数值"][1]]
        self.assertEqual(row[0], None)
        self.assertEqual(row[1:4], [100, 200, 300])
        self.assertEqual(row[4], 1.5)
        self.assertIs(row[5], True)
        self.assertEqual(row[6], "文本")

    def test_supports_wps_style_boundsheet_names(self):
        sheets = [("L301", [["机组号", "通道编号"], [3, 1]]), ("L302", [["机组号", "通道编号"], [3, 2]])]
        book = load_workbook(self.build("wps.xls", sheets, boundsheet_style="wps"))
        self.assertEqual(book.sheetnames, ["L301", "L302"])
        self.assertEqual([cell.value for cell in book["L302"][2]], [3, 2])

    def test_rejects_non_ole_files(self):
        target = self.root / "fake.xls"
        target.write_bytes(b"not an ole file at all")
        with self.assertRaises(XlsError):
            load_workbook(target)

    def test_missing_workbook_stream_is_reported(self):
        target = self.root / "empty.xls"
        fx.build_xls(target, [("A", [["x"]])])
        data = bytearray(target.read_bytes())
        # Corrupt the Workbook directory entry type so no stream is found.
        # The directory lives at sector 1 (file offset 1024); entry 0 is Root
        # Entry, entry 1 is Workbook.
        data[1024 + 128 + 0x42] = 0
        target.write_bytes(bytes(data))
        with self.assertRaises(XlsError):
            load_workbook(target)


@unittest.skipUnless(all(path.is_file() for path in REAL_FILES), "真实 .xls 样本不在本机")
class RealXlsFileTests(unittest.TestCase):
    def test_reads_dayabay_lingao_ledgers(self):
        for path in REAL_FILES[:2]:
            with self.subTest(path=path.name):
                book = load_workbook(path)
                self.assertTrue(book.sheetnames)
                for name in book.sheetnames:
                    self.assertTrue(name.startswith("L"), f"工作表名异常：{name}")
                sheet = book.worksheets[0]
                headers = [str(cell.value or "") for cell in sheet[1]]
                self.assertIn("电站名称", headers)
                self.assertIn("机组号", headers)
                self.assertIn("通道编号", headers)
                data = list(sheet.iter_rows(min_row=2, values_only=True))
                self.assertTrue(data)
                self.assertTrue(all(str(row[1]) in {"3", "4"} for row in data[:5]))

    def test_reads_ningde_cut_shift_summary(self):
        book = load_workbook(REAL_FILES[2])
        self.assertEqual(book.sheetnames, ["N1", "N2", "N3", "N4"])
        sheet = book["N1"]
        self.assertEqual(sheet.cell(1, 2).value, "在堆芯内\n的位置")
        self.assertEqual(sheet.cell(1, 3).value, 101)
        self.assertIn("割管移位", str(sheet.cell(2, 3).value))
        self.assertEqual(sheet.max_row, 51)
        self.assertEqual(sheet.max_column, 9)


if __name__ == "__main__":
    unittest.main()
