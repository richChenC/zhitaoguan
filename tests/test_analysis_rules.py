"""版本化对比配置（analysis_rules）的单元测试。

覆盖：
- 初始默认规则在建立任何自定义规则前即生效；
- 建立新规则后自动激活并停用旧版本；
- 名称/容差校验拒绝非法输入；
- 容差通过 compare 链路真实改变缺陷匹配结果（R / 待确认）。
"""
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from src.backend import analysis_reporting, schema_migrations, server


class AnalysisRulesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "rules.db"
        self.patcher = patch.object(server, "DB_PATH", self.db)
        self.patcher.start()
        server.init_db()

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def test_default_rule_active_before_custom_rules(self):
        active = server.active_analysis_rules()
        self.assertAlmostEqual(float(active["match_tolerance_mm"]),
                               float(analysis_reporting.DEFAULT_RULES["match_tolerance_mm"]))
        self.assertTrue(active["version"] >= 1)

    def test_create_rule_activates_and_retires_previous(self):
        before = server.active_analysis_rules()
        rule = server.create_analysis_rule("秋检容差调整", 0.5, "扩大轴向容差")
        self.assertTrue(rule["version"] > before["version"])
        self.assertTrue(rule["is_active"])
        active = server.active_analysis_rules()
        self.assertEqual(active["version"], rule["version"])
        self.assertEqual(active["match_tolerance_mm"], 0.5)
        previous = [r for r in server.list_analysis_rules() if r["version"] == before["version"]]
        self.assertTrue(previous and not previous[0]["is_active"])

    def test_create_rule_rejects_empty_name(self):
        with self.assertRaises(ValueError):
            server.create_analysis_rule("", 0.5)

    def test_create_rule_rejects_out_of_range_tolerance(self):
        for bad in (0, -1, 5.0001, "x", float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                server.create_analysis_rule("bad", bad)

    def test_parent_is_preserved_and_invalid_parent_does_not_deactivate_rule(self):
        parent = server.active_analysis_rules()["version"]
        created = server.create_analysis_rule("基于初始规则", .025, "复核", parent)
        self.assertEqual(created["parent_version"], parent)
        for invalid in (-1, "x", 1.5, True, 99999):
            with self.subTest(parent=invalid), self.assertRaises(ValueError):
                server.create_analysis_rule("无效基础", .01, "", invalid)
            self.assertEqual(server.active_analysis_rules()["version"], created["version"])
        self.assertEqual(len(server.list_analysis_rules()), 2)

    def test_concurrent_creations_have_unique_versions_and_one_active_rule(self):
        parent = server.active_analysis_rules()["version"]
        with ThreadPoolExecutor(max_workers=4) as workers:
            created = list(workers.map(lambda number: server.create_analysis_rule(
                f"并发规则{number}", .02, "", parent), range(8)))
        self.assertEqual(len({row["version"] for row in created}), 8)
        self.assertTrue(all(row["parent_version"] == parent for row in created))
        self.assertEqual(sum(row["is_active"] for row in server.list_analysis_rules()), 1)

    def test_version_five_upgrade_preserves_old_rows_and_makes_safety_backup(self):
        with server.connect() as db:
            db.execute("ALTER TABLE analysis_rules DROP COLUMN parent_version")
            db.execute("DELETE FROM schema_migrations WHERE version>=6")
            db.execute("PRAGMA user_version=5")
            before = [tuple(row) for row in db.execute("SELECT * FROM analysis_rules")]
        server.init_db()
        with server.connect() as db:
            after = [tuple(row) for row in db.execute("SELECT * FROM analysis_rules")]
        self.assertEqual([row[:-1] for row in after], before)
        self.assertTrue(all(row[-1] == 0 for row in after))
        self.assertEqual(schema_migrations.validate(self.db, True), schema_migrations.VERSION)
        self.assertEqual(len(list((self.db.parent / "backups").glob("migration-*.db"))), 1)
        server.init_db()
        self.assertEqual(len(list((self.db.parent / "backups").glob("migration-*.db"))), 1)

    def test_compatible_trae_lineage_column_survives_legacy_upgrade(self):
        from enterprise_fixtures import mark_legacy
        rule = server.create_analysis_rule("兼容来源", .03, "", 1)
        mark_legacy(server)
        server.init_db()
        self.assertEqual(server.active_analysis_rules()["parent_version"], 1)
        self.assertEqual(server.active_analysis_rules()["version"], rule["version"])

    def test_rule_tolerance_helper_falls_back_to_default(self):
        self.assertAlmostEqual(analysis_reporting.rule_tolerance(None),
                               analysis_reporting.DEFAULT_RULES["match_tolerance_mm"])
        self.assertAlmostEqual(analysis_reporting.rule_tolerance({"match_tolerance_mm": 0.3}), 0.3)

    def test_tolerance_changes_defect_matching_via_compare(self):
        before = self._finding("H101", "P1+10", 1)
        current = self._finding("H102", "P1+10.02", 2)
        with server.connect() as db:
            db.execute(_INSERT, before)
            db.execute(_INSERT, current)
        strict = server.compare("H101", "H102", 1)
        self.assertEqual(strict["summary"]["待确认"], 1)
        self.assertEqual(strict["summary"]["NI"], 0)
        self.assertEqual(strict["summary"]["R"], 0)
        server.create_analysis_rule("宽松容差", 0.05, "覆盖 0.02 mm 差异")
        loose = server.compare("H101", "H102", 1)
        self.assertEqual(loose["summary"]["R"], 1)
        self.assertEqual(loose["summary"]["NI"], 0)

    @staticmethod
    def _finding(outage, location, idx):
        # (outage, unit_id, thimble_id, indication, location, percent, datapoint, analyst,
        #  calgroup, filename, report_path, channel, volts, degrees, measurement_type, uid,
        #  source_key, business_key, imported_at)
        return (outage, 1, 1, "WAR", location, 20, 80, "A", "C1", f"f{idx}.ect", f"z\\f{idx}.ect",
                "P1: 4-6", 1.2, 0, "Point", f"u{idx}", f"k{idx}", f"b{idx}", "now")


_INSERT = """INSERT INTO findings(
  outage,unit_id,thimble_id,indication,location,percent,datapoint,analyst,calgroup,
  filename,report_path,channel,volts,degrees,measurement_type,uid,source_key,business_key,imported_at
) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""


if __name__ == "__main__":
    unittest.main()
