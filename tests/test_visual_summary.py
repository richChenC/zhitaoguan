"""方向4：导出物一页式摘要（趋势 + 分布 + 异常清单）单元测试。

覆盖两个导出入口的「可视化摘要」工作表：
- 历次检测演变：趋势折线（水位参考线）+ 数据点分级 + 突变/超水位异常清单；
- 综合台账：记录分级分布 + 按大修概览 + 超关注水位异常清单。
口径与 tube_longitudinal / 可视化工作台一致（NDD 记 0、未量化留空、30/50 水位）。
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from openpyxl import Workbook, load_workbook

from src.backend import server


class EvolutionSummaryTests(unittest.TestCase):
    """端到端：插检测记录 → 导出演变 → 校验摘要工作表内容与图表文件。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        for name, value in (("DB_PATH", root / "summary.db"), ("EXCEL_DIR", root / "excel")):
            patcher = patch.object(server, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        server.init_db()

    def finding(self, outage, tube, percent, indication="WAR"):
        with server.connect() as db:
            db.execute("""INSERT INTO findings(outage,unit_id,thimble_id,position,indication,percent,location,imported_at)
                          VALUES(?,1,?,?,?,?,?,?)""",
                       (outage, tube, server.position_for(1, tube), indication, percent, "P1+42", "now"))

    def test_summary_sheet_layout_and_charts(self):
        # 管 1：20 → 45（+25，未突变但超关注）→ 62（+17，超限）
        # 管 2：10 → 36（+26 突变）
        # 管 3：全程 NDD
        self.finding("H109", 1, 20)
        self.finding("H110", 1, 45)
        self.finding("H111", 1, 62)
        self.finding("H109", 2, 10)
        self.finding("H110", 2, 36)
        self.finding("H109", 3, None, indication="NDD")
        result = server.export_evolution_excel("H", 1)
        book = load_workbook(result["file_path"])
        try:
            self.assertEqual(book.sheetnames[0], "可视化摘要")
            sheet = book["可视化摘要"]
            self.assertEqual(sheet["A1"].value, "历次检测演变 · 可视化摘要")
            texts = {str(cell.value) for row in sheet.iter_rows() for cell in row if cell.value is not None}
            # 趋势表含最重管与水位参考行；明细表仍完整保留
            self.assertIn("关注水位", texts)
            self.assertIn("极限水位", texts)
            self.assertTrue(any("号管" in text for text in texts))
            # 异常清单：62% 超限；36% 突变以「关注 + 斜率突变」标记列出
            self.assertIn("超限", texts)
            self.assertIn("斜率突变", texts)
            # 明细工作表未被摘要破坏
            self.assertEqual(book["指套管纵向演变"].cell(1, 1).value, "基地")
        finally:
            book.close()
        with ZipFile(result["file_path"]) as archive:
            charts = [name for name in archive.namelist() if name.startswith("xl/charts/chart")]
        # 趋势折线图 + 分布柱状图
        self.assertEqual(len(charts), 2)

    def test_summary_without_quantified_data(self):
        self.finding("H109", 1, None, indication="")
        result = server.export_evolution_excel("H", 1)
        book = load_workbook(result["file_path"])
        try:
            sheet = book["可视化摘要"]
            texts = {str(cell.value) for row in sheet.iter_rows() for cell in row if cell.value is not None}
            self.assertIn("当前范围内没有超过关注水位的点，也没有斜率突变。", texts)
            self.assertTrue(any("趋势图省略" in text for text in texts))
        finally:
            book.close()

    def test_replacement_baseline_does_not_change_exported_report_depth(self):
        self.finding("H101", 1, 20)
        self.finding("H102", 1, 44)
        with server.connect() as db:
            db.execute("""INSERT INTO tube_states(outage,unit_id,thimble_id,state,events_json)
                          VALUES('H102',1,1,'replaced','["replaced"]')""")
        result = server.export_evolution_excel("H", 1)
        book = load_workbook(result["file_path"])
        try:
            row = next(row for row in book["可视化摘要"].iter_rows(values_only=True) if row[0] == "1 号管")
            self.assertEqual(row[1:3], (20, 44))
        finally:
            book.close()


class LedgerSummaryTests(unittest.TestCase):
    """直接构造记录行调用 build_ledger_summary_sheet，校验统计与异常清单。"""

    def build(self, rows):
        book = Workbook()
        book.active.title = "综合台账"
        server.build_ledger_summary_sheet(book, "范围：测试", rows)
        return book

    def test_buckets_and_anomaly_list(self):
        rows = [
            {"outage": "H209", "unit_id": 1, "thimble_id": 1, "position": "B5", "indication": "WAR",
             "percent": 62, "location": "P1+10", "datapoint": 1, "measurement_type": "WAR"},
            {"outage": "H209", "unit_id": 1, "thimble_id": 2, "position": "C8", "indication": "WAR",
             "percent": 35, "location": "P2-4", "datapoint": 1, "measurement_type": "WAR"},
            {"outage": "H209", "unit_id": 1, "thimble_id": 3, "position": "E11", "indication": "NDD",
             "percent": None, "location": "", "datapoint": 0, "measurement_type": ""},
            {"outage": "H209", "unit_id": 1, "thimble_id": 4, "position": "D10", "indication": "WAR",
             "percent": None, "location": "P3", "datapoint": 1, "measurement_type": "WAR"},
            {"outage": "H210", "unit_id": 1, "thimble_id": 1, "position": "B5", "indication": "WAR",
             "percent": 18, "location": "P1+10", "datapoint": 1, "measurement_type": "WAR"},
        ]
        book = self.build(rows)
        try:
            sheet = book["可视化摘要"]
            self.assertEqual(sheet["A1"].value, "综合台账 · 可视化摘要")
            grid = [[cell.value for cell in row] for row in sheet.iter_rows()]
            first_two = [row[:2] for row in grid]
            first_four = [row[:4] for row in grid]
            # 分布：62 超限、35 关注、18 低、NDD 一条、未量化一条
            for expected in (["超限（≥ 50%）", 1], ["关注（30–50%）", 1], ["低（< 30%）", 1],
                             ["NDD（无缺陷）", 1], ["未量化 / 待确认", 1]):
                self.assertIn(expected, first_two)
            # 按大修概览：H209 4 条记录 3 条缺陷最大 62；H210 1 条记录 1 条缺陷最大 18
            self.assertIn(["H209", 4, 3, 62], first_four)
            self.assertIn(["H210", 1, 1, 18], first_four)
            # 异常清单只含 62 与 35 两条，按深度降序
            anomaly_rows = [row for row in grid if row and row[0] in (1, 2) and row[5] in (62, 35)]
            self.assertEqual([row[5] for row in anomaly_rows], [62, 35])
            self.assertIn("超限", [row[7] for row in anomaly_rows])
        finally:
            book.close()

    def test_no_anomalies_message(self):
        book = self.build([{"outage": "H209", "unit_id": 1, "thimble_id": 1, "position": "B5",
                            "indication": "WAR", "percent": 12, "location": "P1", "datapoint": 1,
                            "measurement_type": "WAR"}])
        try:
            texts = {cell.value for row in book["可视化摘要"].iter_rows() for cell in row if cell.value}
            self.assertIn("当前范围内没有超过关注水位的缺陷记录。", texts)
        finally:
            book.close()


if __name__ == "__main__":
    unittest.main()
