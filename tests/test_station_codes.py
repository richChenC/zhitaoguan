"""陆丰 LF 与岭澳 L 编码隔离（F09：站点编码同码冲突）。

背景：STATION_CODES 原将岭澳与陆丰同时映射为 "L"，与前端地图
SITE_GEO['陆丰'].apiCode='LF' 的定案矛盾；一旦导入陆丰数据，
outage 前缀、site_code、地图计数、统计分组会全部并入岭澳。
本测试锁定修复后的行为：两位代号（LF）与一位代号（L）全程隔离。
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.backend import analysis_reporting, server  # 先导入 server：由它把 .vendor 加入 sys.path
from openpyxl import Workbook


class StationCodeTests(unittest.TestCase):
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

    def workbook(self, rows, filename="stations.xlsx"):
        source = self.root / filename
        book = Workbook()
        book.active.append(["大修号", "机组号", "通道编号", "在堆芯内的位置", "幅值", "三字码", "磨损位置"])
        for row in rows:
            book.active.append(row)
        book.save(source)
        book.close()
        return source

    def import_stations(self):
        rows = [
            ["LF209", 2, 1, "B5", 5.0, "WAR", "P1"],
            ["LF209", 2, 2, "A1", 4.0, "NDD", ""],
            ["L209", 2, 1, "B5", 5.0, "WAR", "P1"],
            ["L209", 2, 2, "A1", 4.0, "NDD", ""],
        ]
        result = server.import_excel_file(str(self.workbook(rows)), operator="检验员A")
        self.assertEqual(result["inserted"], 4, result)
        return result

    # ---------- 纯函数 ----------

    def test_outage_code_separates_lufeng_from_lingao(self):
        self.assertEqual(server.outage_code("LF209"), "LF")
        self.assertEqual(server.outage_code("L209"), "L")
        self.assertEqual(server.outage_code("H209"), "H")
        self.assertEqual(server.outage_code("lf209"), "LF")
        self.assertEqual(server.outage_code(""), "")
        self.assertEqual(server.outage_code(None), "")

    def test_infer_unit_reads_two_letter_code(self):
        self.assertEqual(server.infer_unit("LF209", ""), 2)
        self.assertEqual(server.infer_unit("L209", ""), 2)
        self.assertEqual(server.infer_unit("LF1", ""), 1)

    def test_sequence_accepts_two_letter_code(self):
        self.assertEqual(analysis_reporting.sequence("LF209"), ("LF", 2, 9))

    def test_outage_sort_key_orders_by_unit_then_sequence(self):
        self.assertEqual(server.outage_sort_key("LF209"), (2, 9))
        self.assertEqual(server.outage_sort_key("L209"), (2, 9))

    def test_infer_station_maps_lufeng_project_and_keeps_lingao(self):
        station, code = server.infer_station(Path(r"DATA\9--------陆丰项目\LFNP1\LF101"))
        self.assertEqual((station, code), ("陆丰", "LF"))
        station, code = server.infer_station(Path(r"DATA\1--------大亚湾项目\LNPS2\L210"))
        self.assertEqual((station, code), ("岭澳", "L"))

    def test_outage_from_standard_row_uses_station_specific_code(self):
        lufeng = server.outage_from_standard_row(
            {"电站名称": "陆丰核电", "数据组": "TH2I09", "大修号": ""}, Path("x"))
        self.assertEqual(lufeng, "LF209")
        lingao = server.outage_from_standard_row(
            {"电站名称": "岭澳", "数据组": "TH2I09", "大修号": ""}, Path("x"))
        self.assertEqual(lingao, "L209")
        for alias in ["惠州核电", "太平岭核电", "太平岭（惠州）"]:
            self.assertEqual(server.outage_from_standard_row(
                {"电站名称": alias, "数据组": "TH1I01"}, Path("x")), "P101")
        self.assertEqual(server.infer_station(Path(r"DATA\太平岭项目\HENP1\P101")),
                         ("惠州", "P"))

    def test_explicit_two_letter_outage_is_accepted(self):
        explicit = server.outage_from_standard_row(
            {"电站名称": "陆丰核电", "大修号": "LF209"}, Path("x"))
        self.assertEqual(explicit, "LF209")

    # ---------- SQL 分组与筛选 ----------

    def test_overview_lists_lufeng_and_lingao_as_separate_sites(self):
        self.import_stations()
        data = server.overview()
        self.assertIn("L", data["sites"])
        self.assertIn("LF", data["sites"])
        combinations = {(row["site"], row["outage"]) for row in data["combinations"]}
        self.assertIn(("L", "L209"), combinations)
        self.assertIn(("LF", "LF209"), combinations)

    def test_analytics_bases_groups_by_two_letter_code(self):
        self.import_stations()
        bases = {item["code"]: item for item in server.api_analytics_bases()}
        self.assertEqual(bases["L"]["findingCount"], 2)
        self.assertEqual(bases["LF"]["findingCount"], 2)
        self.assertEqual(bases["LF"]["name"], "陆丰")
        self.assertEqual(bases["L"]["name"], "岭澳")

    def test_rows_for_filters_exact_station(self):
        self.import_stations()
        lufeng = analysis_reporting.rows_for(server, site="LF")
        lingao = analysis_reporting.rows_for(server, site="L")
        self.assertEqual({row["outage"] for row in lufeng}, {"LF209"})
        self.assertEqual({row["outage"] for row in lingao}, {"L209"})

    def test_repairs_for_does_not_leak_lufeng_into_lingao(self):
        self.import_stations()
        with server.connect() as db:
            db.execute("INSERT INTO tube_states(outage,unit_id,thimble_id,state,offset_mm,note) VALUES('LF209',2,3,'shifted',42,'陆丰移位')")
        self.assertEqual(len(analysis_reporting.repairs_for(server, "LF", 2)), 1)
        self.assertEqual(len(analysis_reporting.repairs_for(server, "L", 2)), 0)

    def test_query_findings_site_filter_matches_only_selected_station(self):
        self.import_stations()
        lufeng = server.query_findings({"site": ["LF"], "size": ["100"]})
        lingao = server.query_findings({"site": ["L"], "size": ["100"]})
        self.assertEqual({row["outage"] for row in lufeng["items"]}, {"LF209"})
        self.assertEqual({row["outage"] for row in lingao["items"]}, {"L209"})

    def test_compare_many_rejects_mixing_lufeng_and_lingao(self):
        self.import_stations()
        with self.assertRaisesRegex(ValueError, "同一基地"):
            server.compare_many(["L209", "LF209"], 2)

    def test_site_name_lookup_resolves_both_codes(self):
        self.assertEqual(server._site_name_from_code("LF"), "陆丰")
        self.assertEqual(server._site_name_from_code("L"), "岭澳")

    def test_station_codes_are_unique(self):
        codes = list(server.STATION_CODES.values())
        self.assertEqual(len(codes), len(set(codes)), "电站代号必须全局唯一")
        self.assertEqual(server.STATION_CODES["陆丰"], "LF")
        self.assertEqual(server.STATION_CODES["岭澳"], "L")


if __name__ == "__main__":
    unittest.main()
