import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server
from openpyxl import Workbook, load_workbook

DATA_ROOT = server.ROOT.parent / "测试数据"
H209_ROOT = DATA_ROOT / "指套管数据1" / "H209"
N208_ROOT = DATA_ROOT / "指套管数据1" / "N208"


class ParserTests(unittest.TestCase):
    def test_position_mappings(self):
        self.assertEqual(server.position_for(1, 1), "L11")
        self.assertEqual(server.position_for(2, 1), "B5")
        self.assertEqual(server.position_for(2, 27), "J15")
        self.assertEqual(server.position_for(2, 42), "N5")
        self.assertEqual(server.position_for(2, 50), "L4")
        self.assertEqual(len({server.position_for(1, tube) for tube in range(1, 51)}), 50)
        self.assertEqual(len({server.position_for(2, tube) for tube in range(1, 51)}), 50)

    def test_database_removes_out_of_range_legacy_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "test.db"
            with patch.object(server, "DB_PATH", db):
                server.init_db()
                with server.connect() as connection:
                    connection.execute("INSERT INTO findings(outage,unit_id,thimble_id,imported_at) VALUES('N208',2,82,'now')")
                server.init_db()
                with server.connect() as connection:
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM findings").fetchone()[0], 0)

    def test_outage_ignores_calgroup_digits(self):
        path = Path(r"D:\data\H209\TH2I09CAL00005\Report-x.rpt")
        self.assertEqual(server.infer_outage(path), "H209")

    def test_parse_real_report(self):
        reports = [path for path in DATA_ROOT.rglob("Report*.rpt") if path.parent.name.upper().startswith("TH")]
        self.assertTrue(reports)
        findings = server.parse_report(reports[0])
        self.assertTrue(findings)
        self.assertTrue(all(1 <= x.thimble_id <= 50 for x in findings))
        self.assertTrue(all(x.position for x in findings))

    def test_import_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "test.db"
            with patch.object(server, "DB_PATH", db):
                server.init_db()
                first = server.import_directory(str(H209_ROOT))
                second = server.import_directory(str(H209_ROOT))
            self.assertGreater(first["inserted"], 0)
            self.assertEqual(second["inserted"], 0)
            self.assertEqual(second["skipped"], first["parsed"])

    def test_overview_contains_compact_outage_history(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(server, "DB_PATH", Path(directory) / "history.db"):
                server.init_db()
                server.import_directory(str(H209_ROOT))
                history = server.overview()["history"]
                self.assertTrue(history)
                self.assertEqual({item["outage"] for item in history}, {"H209"})
                self.assertTrue(all(item["findings"] > 0 and item["tubes"] > 0 for item in history))

    def test_import_excludes_steam_generator_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "test.db"
            with patch.object(server, "DB_PATH", db):
                server.init_db()
                server.import_directory(str(N208_ROOT))
                with server.connect() as connection:
                    maximum = connection.execute("SELECT MAX(thimble_id) FROM findings").fetchone()[0]
                self.assertLessEqual(maximum, 50)

    def test_ect_coverage_excludes_calibration_and_steam_generator(self):
        h209 = server.scan_thimble_directory(str(H209_ROOT))
        n208 = server.scan_thimble_directory(str(N208_ROOT))
        self.assertEqual(h209["unique_tubes"], list(range(1, 51)))
        self.assertEqual(n208["unique_tubes"], list(range(1, 51)))
        self.assertEqual(h209["missing_tubes"], [])
        self.assertEqual(n208["missing_tubes"], [])
        self.assertGreater(h209["calibration_count"], 0)
        self.assertGreater(n208["calibration_count"], 0)
        self.assertTrue(all(Path(row["path"]).parent.name.upper().startswith("TH") for row in n208["ect"]))

    def test_folder_exports_real_xlsx(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(server, "EXCEL_DIR", Path(directory)):
                result = server.export_directory_excel(str(H209_ROOT))
                target = Path(result["file_path"])
                self.assertTrue(target.is_file())
                book = load_workbook(target, read_only=True)
                sheet = book["标准数据表"]
                self.assertEqual([cell.value for cell in sheet[1]], server.STANDARD_EXCEL_FIELDS)
                self.assertEqual(sheet.max_row - 1, result["rows"])
                headers = {cell.value: cell.column for cell in sheet[1]}
                self.assertEqual(sheet.cell(2, headers["电站名称"]).value, "红沿河")
                self.assertEqual(sheet.cell(2, headers["大修号"]).value, "H209")
                self.assertIn("数据组汇总", book.sheetnames)
                self.assertGreater(book["数据组汇总"].max_row, 1)
                book.close()

    def test_imports_custom_standard_excel_by_header_name(self):
        with tempfile.TemporaryDirectory() as directory:
            source, db = Path(directory) / "custom.xlsx", Path(directory) / "test.db"
            book = Workbook()
            sheet = book.active
            sheet.title = "用户自定义数据"
            sheet.append(["备注", "数据组", "磨损位置", "分析人员", "通道编号", "机组号", "电站名称", "三字码", "磨损深度", "幅值", "相位"])
            sheet.append(["人工备注", "TH1I20CAL00001", "P1+40", "MQQ", 2, 1, "大亚湾", "WAR", 48, 5.07, 258])
            book.save(source)
            with patch.object(server, "DB_PATH", db):
                server.init_db()
                result = server.import_excel_file(str(source))
                self.assertEqual(result["parsed"], 1)
                with server.connect() as connection:
                    row = connection.execute("SELECT outage,unit_id,thimble_id,position,location FROM findings").fetchone()
                self.assertEqual(tuple(row), ("D120", 1, 2, "G14", "P1+40"))

    def test_discovers_server_thimble_directories_without_fixed_depth(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "2--------红沿河项目" / "LHNP2" / "9.H209" / "2. 数据" / "2.3 指套管"
            (target / "TH2I09CAL00001").mkdir(parents=True)
            unrelated = root / "3--------宁德项目" / "NDNP1" / "N109" / "2.数据" / "2.1蒸发器"
            (unrelated / "SG1").mkdir(parents=True)
            result = server.discover_server_sources(str(root))
            self.assertEqual(len(result["items"]), 1)
            self.assertEqual(result["items"][0]["outage"], "H209")
            self.assertEqual(result["items"][0]["station"], "红沿河")
            self.assertEqual(result["items"][0]["unit_folder"], "LHNP2")
            self.assertEqual(Path(result["items"][0]["path"]), target)

    def test_infers_station_from_documented_project_and_unit_paths(self):
        samples = {
            r"DATA\1--------大亚湾项目\CNPS1\D110": "大亚湾",
            r"DATA\1--------大亚湾项目\LNPS2\L210": "岭澳",
            r"DATA\3--------宁德项目\NDNP4\N409": "宁德",
            r"DATA\4--------阳江项目\YJNP6\Y603": "阳江",
            r"DATA\5--------防城港项目\BLNP1\F107": "防城港",
            r"DATA\6--------台山项目\TSNP2\T205": "台山",
            r"DATA\7--------太平岭（惠州）项目\HENP1\P101": "太平岭（惠州）",
            r"DATA\8--------苍南项目\CNMP2\C201": "苍南",
        }
        for path, expected in samples.items():
            with self.subTest(path=path):
                self.assertEqual(server.infer_station(Path(path))[0], expected)

    def test_infers_outage_from_sum_when_parent_path_has_no_outage(self):
        report = DATA_ROOT / "指套管数据2" / "2.3 指套管" / "TH2I09CAL00001" / "Report-TH2I09CAL00001-KYY-SEC.rpt"
        self.assertEqual(server.infer_outage(report), "H209")

    def test_report_options_merge_byte_identical_copies(self):
        options = server.report_options(str(DATA_ROOT))
        h209 = [item for item in options if item.get("outage") == "H209" and item.get("group") == "TH2I09CAL00001"]
        self.assertEqual(len(h209), 1)
        self.assertGreaterEqual(len(h209[0]["duplicate_paths"]), 1)

    def test_report_option_distinguishes_entries_from_unique_tubes(self):
        options = server.report_options(str(DATA_ROOT / "指套管数据2"))
        y108 = next(item for item in options if item.get("outage") == "Y108" and item.get("group") == "TH1I08CAL00002" and "LYY" in item.get("name", ""))
        self.assertEqual(y108["records"], 41)
        self.assertEqual(y108["tube_count"], 24)
        self.assertEqual(y108["indication_count"], 32)


if __name__ == "__main__": unittest.main()
