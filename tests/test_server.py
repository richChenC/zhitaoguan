import tempfile
import unittest
import sqlite3
from pathlib import Path
from unittest.mock import patch

import server
from openpyxl import Workbook, load_workbook

DATA_ROOT = server.ROOT.parent / "测试数据"
H209_ROOT = DATA_ROOT / "指套管数据1" / "H209"
N208_ROOT = DATA_ROOT / "指套管数据1" / "N208"


def write_sum(group: Path, unit="2", outage="H209"):
    (group / "SUR000C000I000.SUM").write_text(
        f'<?xml version="1.0" encoding="utf-8"?><Summary><Site><Owner>LHNP</Owner><SiteCode>LHNP</SiteCode><Unit>{unit}</Unit><Component>TH</Component><Outage>{outage}</Outage></Site><Equipment><Tester>TEDDY+A</Tester></Equipment><Probe><Model>TH048NAF25A</Model></Probe></Summary>',
        encoding="utf-8",
    )


def write_ect(group: Path, name: str, row: int, col: int, entry: int, marker=""):
    xml = f'xx<?xml version="1.0" encoding="utf-8"?><HeaderTube><Entry>{entry}</Entry><Row>{row}</Row><Col>{col}</Col><DateTime>2026/1/1 {marker}</DateTime></HeaderTube>yy'
    (group / name).write_bytes(xml.encode("utf-8"))


def report_entry(filename, row, col, entry, uid, indication="WAR", location="P1+10", channel="P1: 4-6", percent="20", calgroup="TH2I09CAL00001", measurement="Point"):
    return f'<ReportEntry><Row>{row}</Row><Column>{col}</Column><Entry>{entry}</Entry><Volts>1.2</Volts><Degrees>0</Degrees><Percent>{percent}</Percent><Indication>{indication}</Indication><Channel>{channel}</Channel><ChannelID>4</ChannelID><Location>{location}</Location><MeasurementType>{measurement}</MeasurementType><Probe>TH048NAF25A</Probe><Analyst>A</Analyst><Analysis>Secondary</Analysis><Datapoint>80</Datapoint><Uid>{uid}</Uid><Filename>{filename}</Filename><Filepath>Z:\\old\\{filename}</Filepath><Calgroup>{calgroup}</Calgroup><Distance>10</Distance><Extent>2</Extent><Length>3</Length><Width>4</Width><Comment>note</Comment></ReportEntry>'


def write_report(group: Path, entries: list[str], name="Report-final.rpt"):
    (group / name).write_text('<?xml version="1.0" encoding="utf-8"?><CitecReport>' + "".join(entries) + "</CitecReport>", encoding="utf-8")


class ParserTests(unittest.TestCase):
    def test_position_mappings(self):
        self.assertEqual(server.position_for(1, 1), "L11")
        self.assertEqual(server.position_for(2, 1), "B5")
        self.assertEqual(server.position_for(2, 27), "J15")
        self.assertEqual(server.position_for(1, 15), "M5")
        self.assertEqual(server.position_for(2, 42), "M5")
        self.assertEqual(server.position_for(2, 3), "E11")
        self.assertEqual(server.position_for(2, 47), "L5")
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

    def test_database_migration_backs_up_and_preserves_legacy_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "legacy.db"
            connection = sqlite3.connect(db)
            connection.execute("""CREATE TABLE findings (
                id INTEGER PRIMARY KEY, outage TEXT NOT NULL, unit_id INTEGER NOT NULL,
                thimble_id INTEGER NOT NULL, position TEXT, entry_no INTEGER, volts REAL,
                degrees REAL, indication TEXT, percent REAL, channel TEXT, location TEXT,
                datapoint INTEGER, liss_region_size INTEGER, analyst TEXT, analysis TEXT,
                filepath TEXT, filename TEXT, calgroup TEXT, report_path TEXT, imported_at TEXT NOT NULL)""")
            connection.execute("INSERT INTO findings(outage,unit_id,thimble_id,position,filename,calgroup,imported_at) VALUES('H209',2,3,'E11','DIR003C003I004.ECT','TH2I09CAL00001','now')")
            connection.commit(); connection.close()
            with patch.object(server, "DB_PATH", db):
                server.init_db()
                with server.connect() as migrated:
                    row = migrated.execute("SELECT outage,unit_id,thimble_id,position,source_key FROM findings").fetchone()
                    columns = {item[1] for item in migrated.execute("PRAGMA table_info(findings)")}
            self.assertEqual(tuple(row), ("H209", 2, 3, "E11", None))
            self.assertIn("uid", columns)
            self.assertTrue(db.with_suffix(db.suffix + ".before-raw-fields.bak").is_file())

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
                required = ["缺陷明细表", "管子汇总表", "未进入RPT的真实ECT", "DIR999标定文件", "同名同哈希副本", "同名不同哈希文件", "RPT引用异常", "ECT编号校验异常", "SUM或机组号缺失", "堆芯映射失败"]
                self.assertEqual(book.sheetnames, required)
                sheet = book["缺陷明细表"]
                self.assertEqual(sheet.max_row - 1, result["rows"])
                headers = {cell.value: cell.column for cell in sheet[1]}
                self.assertEqual(sheet.cell(2, headers["电站名称"]).value, "红沿河")
                self.assertEqual(sheet.cell(2, headers["机组号"]).value, 2)
                self.assertGreater(book["管子汇总表"].max_row, 1)
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
                repeated = server.import_excel_file(str(source))
                self.assertEqual(result["parsed"], 1)
                self.assertEqual(repeated["inserted"], 0)
                self.assertEqual(repeated["skipped"], 1)
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

    def test_strict_group_processing_and_layered_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); group = root / "TH2I09CAL00001"; group.mkdir()
            write_sum(group)
            write_ect(group, "DIR003C003I004.ECT", 3, 3, 4)
            write_ect(group, "DIR003C003I005.ECT", 3, 3, 5)
            write_ect(group, "DIR004C004I006.ECT", 5, 4, 6)
            write_ect(group, "DIR999C999I001.ECT", 999, 999, 1)
            write_report(group, [
                report_entry("DIR003C003I004.ECT", 3, 3, 4, "u1"),
                report_entry("DIR003C003I004.ECT", 3, 3, 4, "u2"),
                report_entry("DIR999C999I001.ECT", 999, 999, 1, "cal"),
                report_entry("DIR050C050I999.ECT", 50, 50, 999, "missing"),
            ])
            ignored = root / "整合一起看" / "TH2I09CAL00002"; ignored.mkdir(parents=True)
            write_sum(ignored); write_ect(ignored, "DIR001C001I001.ECT", 1, 1, 1)
            (root / "TH2I09CAL00001-copy").mkdir()
            result = server.process_directory(str(root))
            self.assertEqual(len(result["contexts"]), 1)
            self.assertEqual(len(result["report_rows"]), 4)
            self.assertEqual(len(result["findings"]), 2)
            tube = next(row for row in result["tube_summary"] if row["thimble_id"] == 3)
            self.assertEqual((tube["entry_count"], tube["raw_indication_count"], tube["position_group_count"]), (2, 2, 1))
            self.assertEqual(tube["position"], "E11")
            self.assertEqual(len(result["calibration_ect"]), 1)
            self.assertEqual(len(result["ect_mismatches"]), 1)
            self.assertEqual(len(result["report_reference_errors"]), 2)
            self.assertEqual(len(result["unreported_ect"]), 2)
            db = root / "test.db"
            with patch.object(server, "DB_PATH", db):
                server.init_db()
                imported = server.import_directory(str(root))
                self.assertEqual(imported["inserted"], 2)
                with server.connect() as connection:
                    rows = connection.execute("SELECT degrees,uid,measurement_type,distance,extent,length,width,comment FROM findings ORDER BY uid").fetchall()
                self.assertEqual([row["uid"] for row in rows], ["u1", "u2"])
                self.assertTrue(all(row["degrees"] == 0 for row in rows))
                self.assertTrue(all(tuple(row[key] for key in ("measurement_type", "distance", "extent", "length", "width", "comment")) == ("Point", "10", "2", "3", "4", "note") for row in rows))

    def test_missing_sum_never_guesses_unit_or_position(self):
        with tempfile.TemporaryDirectory() as directory:
            group = Path(directory) / "TH2I09CAL00001"; group.mkdir()
            write_ect(group, "DIR003C003I004.ECT", 3, 3, 4)
            write_report(group, [report_entry("DIR003C003I004.ECT", 3, 3, 4, "u1")])
            result = server.process_directory(directory)
            self.assertEqual(result["findings"][0].unit_id, 0)
            self.assertEqual(result["findings"][0].position, "")
            self.assertTrue(result["sum_warnings"])
            self.assertTrue(result["mapping_failures"])

    def test_physical_duplicate_hash_classification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for branch, marker in (("a", "same"), ("b", "same"), ("c", "different")):
                group = root / branch / "TH2I09CAL00001"; group.mkdir(parents=True)
                write_sum(group); write_ect(group, "DIR003C003I004.ECT", 3, 3, 4, marker)
            result = server.process_directory(directory)
            self.assertEqual(len(result["duplicate_same_hash"]), 1)
            self.assertEqual(len(result["same_name_different_hash"]), 3)


if __name__ == "__main__": unittest.main()
