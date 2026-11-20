"""统计补齐：管子总数 + 缺陷总数、区间缺陷数、新增缺陷。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.backend import server


class AnalyticsSummaryTests(unittest.TestCase):
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

    def test_totals_and_buckets(self):
        self.finding("H109", 1, 20)
        self.finding("H109", 2, 35)
        self.finding("H109", 2, 40)
        data = server.api_analytics_summary("all", ["30", "50"])
        self.assertEqual(data["tube_total"], 2)
        self.assertEqual(data["defect_total"], 3)
        self.assertEqual([item["label"] for item in data["bucket_defects"]],
                         ["0–30%", "30–50%", "≥50%"])
        self.assertEqual([item["tubes"] for item in data["bucket_defects"]], [1, 1, 0])
        self.assertEqual([item["defects"] for item in data["bucket_defects"]], [1, 2, 0])
        self.assertIsNone(data["new_defects"])

    def test_new_defects_against_previous_outage(self):
        self.finding("H109", 2, 30, indication="NDD")
        self.finding("H109", 3, 20, indication="NDD")
        self.finding("H110", 2, 35)
        self.finding("H110", 3, 45)
        data = server.api_analytics_summary("all", ["30", "50"])
        self.assertEqual(data["new_defects"], 2)

    def test_custom_thresholds_change_buckets(self):
        self.finding("H109", 1, 45)
        data = server.api_analytics_summary("all", ["20", "40", "60"])
        self.assertEqual([item["label"] for item in data["bucket_defects"]],
                         ["0–20%", "20–40%", "40–60%", "≥60%"])
        self.assertEqual(data["bucket_defects"][2]["defects"], 1)


if __name__ == "__main__":
    unittest.main()
