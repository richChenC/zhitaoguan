"""单管跨大修纵向对比（server.tube_longitudinal）的口径与突变标记单测。

口径基线与可视化工作台一致：
- 每管每次大修取可量化 WAR 的最大报告深度；
- 明确 NDD 记为 0；仅有未量化缺陷或结论待确认时留空（None），不补零；
- 缺失轮次直接断线（不进序列、不重排 order），跨缺口不算逐次变化；
- 换管分代归零、保留原检测值；移位不归零，堵管按历史沿用；
- 突变阈值默认 15 个百分点（按绝对值判定），可自定义且限定 5–50。
"""
import unittest
from unittest.mock import patch

from src.backend import server


def finding(outage, tube=1, indication="WAR", percent=10, location="P1+2", datapoint=1):
    return dict(outage=outage, unit_id=1, thimble_id=tube, indication=indication,
                percent=percent, location=location, datapoint=datapoint)


def event(outage, tube=1, state="replaced", **extra):
    return dict(outage=outage, thimble_id=tube, state=state, offset_mm=12 if state == "shifted" else 0, **extra)


class TubeLongitudinalTests(unittest.TestCase):
    def build(self, rows=None, repairs=None, jump=server.TUBE_LONGITUDINAL_JUMP_DEFAULT):
        with patch.object(server.analysis_reporting, "rows_for", return_value=rows or []), patch.object(
                server.analysis_reporting, "repairs_for", return_value=repairs or []):
            return server.tube_longitudinal("N", 1, jump)

    def test_ndd_zero_unquantified_blank_and_max_within_outage(self):
        data = self.build([
            finding("N101", indication="NDD", percent=None),
            finding("N102", percent=12),
            finding("N102", percent=30),
            finding("N103", indication="", percent=None, datapoint=1),
        ])
        series = data["tubes"][0]["series"]
        self.assertEqual([p["max_depth"] for p in series], [0.0, 30.0, None])
        self.assertTrue(series[0]["ndd"])
        self.assertFalse(series[1]["ndd"])
        self.assertEqual(series[1]["war_records"], 2)
        self.assertEqual(series[1]["records"], 2)

    def test_complete_findings_and_maintenance_are_preserved(self):
        rows = [finding("N101", percent=10, location="P1"),
                finding("N101", percent=None, location="P4+20"),
                finding("N103", percent=40, location="P1+12")]
        repairs = [event("N102", state="shifted", note="direction unknown",
                         offset_confirmed=0, unsigned_offset_mm=12),
                   event("N103", state="replaced"), event("N104", state="plugged")]
        points = self.build(rows, repairs)["tubes"][0]["series"]
        self.assertEqual([item["location"] for item in points[0]["findings"]], ["P1", "P4+20"])
        self.assertIsNone(points[0]["findings"][1]["percent"])
        self.assertEqual(points[1]["findings"], [])
        self.assertIsNone(points[1]["maintenance_offset_mm"])
        self.assertEqual(points[1]["maintenance_unsigned_offset_mm"], 12)
        self.assertEqual(points[1]["maintenance_note"], "direction unknown")
        self.assertIn("replaced", points[2]["current_events"])
        self.assertIn("plugged", points[3]["current_events"])

    def test_missing_outage_breaks_series_and_delta(self):
        # N102 该管无记录：序列断线且 order 不重排；N101→N103 跨缺口不算 delta。
        data = self.build([finding("N101", percent=10), finding("N103", percent=25)])
        series = data["tubes"][0]["series"]
        self.assertEqual([p["outage"] for p in series], ["N101", "N103"])
        self.assertEqual([p["order"] for p in series], [1, 3])
        self.assertEqual([p["delta"] for p in series], [None, None])
        self.assertEqual([o["outage"] for o in data["outages"]], ["N101", "N103"])

    def test_conclusion_survives_replacement_and_missing_depth(self):
        points = self.build([
            finding("N101", indication="NDD", percent=None),
            finding("N102", percent=32),
            finding("N103", percent=48),
            finding("N104", indication="NDD", percent=None),
            finding("N105", percent=None),
        ], [event("N103"), event("N106", state="plugged")])["tubes"][0]["series"]
        self.assertEqual([p["conclusion"] for p in points],
                         ["NDD", "WAR", "WAR", "NDD", "WAR", "无检测记录"])
        self.assertEqual([p["generation"] for p in points], [1, 1, 2, 2, 2, 2])
        self.assertEqual(points[2]["report_max_depth"], 48)
        self.assertEqual(points[2]["max_depth"], 0)
        self.assertIsNone(points[4]["report_max_depth"])

    def test_no_signal_ndd_and_unknown_codes_match_visualization_conclusions(self):
        data = self.build([
            dict(finding("N109", indication="", percent=None, location="", datapoint=0),
                 measurement_type="None"),
            finding("N110", indication="NOS", percent=60),
            finding("N111", indication="/", percent=None, location="/", datapoint=None),
        ])
        points = data["tubes"][0]["series"]
        self.assertEqual([point["report_max_depth"] for point in points], [0, None, 0])
        self.assertTrue(points[0]["ndd"])
        self.assertFalse(points[1]["ndd"])

    def test_adjacent_delta_and_jump_threshold(self):
        data = self.build([finding("N101", percent=10), finding("N102", percent=30),
                           finding("N103", percent=20)])
        series = data["tubes"][0]["series"]
        self.assertEqual([p["delta"] for p in series], [None, 20.0, -10.0])
        self.assertEqual([p["jump"] for p in series], [False, True, False])

    def test_replacement_starts_new_generation_without_overwriting_measurement(self):
        series = self.build([finding("N101", percent=10), finding("N102", percent=30),
                             finding("N103", percent=8)], [event("N102")])["tubes"][0]["series"]
        self.assertEqual([p["max_depth"] for p in series], [10, 0, 8])
        self.assertEqual([p["report_max_depth"] for p in series], [10, 30, 8])
        self.assertEqual([p["generation"] for p in series], [1, 2, 2])
        self.assertEqual([p["delta"] for p in series], [None, None, 8])
        self.assertTrue(series[1]["break_before"])
        self.assertFalse(series[2]["break_before"])

    def test_shift_keeps_depth_and_adjacent_delta(self):
        series = self.build([finding("N101", percent=10), finding("N102", percent=30)],
                            [event("N102", state="shifted")])["tubes"][0]["series"]
        self.assertTrue(series[1]["shifted"])
        self.assertEqual(series[1]["max_depth"], 30)
        self.assertEqual(series[1]["delta"], 20)
        self.assertFalse(series[1]["break_before"])

    def test_unknown_shift_direction_warns_without_resetting_wear(self):
        repair = {**event("N102", state="shifted"), "offset_mm": None, "offset_confirmed": 0}
        point = self.build([finding("N101", percent=10), finding("N102", percent=30)],
                           [repair])["tubes"][0]["series"][1]
        self.assertTrue(point["needs_review"])
        self.assertEqual(point["delta"], 20)
        self.assertFalse(point["break_before"])

    def test_plugged_records_state_but_keeps_delta(self):
        repairs = [event("N102", state="plugged")]
        data = self.build([finding("N101", percent=10), finding("N102", percent=30)], repairs)
        series = data["tubes"][0]["series"]
        self.assertTrue(series[1]["plugged"])
        self.assertEqual(series[1]["delta"], 20.0)

    def test_repair_only_outage_retains_status_with_missing_depth(self):
        repairs = [event("N102", state="plugged")]
        data = self.build([finding("N101", percent=10)], repairs)
        self.assertEqual([o["outage"] for o in data["outages"]], ["N101", "N102"])
        self.assertEqual([p["outage"] for p in data["tubes"][0]["series"]], ["N101", "N102"])
        self.assertIsNone(data["tubes"][0]["series"][1]["max_depth"])
        self.assertTrue(data["tubes"][0]["series"][1]["plugged"])

    def test_plug_inherited_despite_normal_then_cleared_by_replacement(self):
        rows = [finding(f"N10{order}", percent=order*10) for order in range(1, 5)]
        repairs = [event("N101", state="plugged"), event("N102", state="normal"), event("N104")]
        series = self.build(rows, repairs)["tubes"][0]["series"]
        self.assertEqual([p["plugged"] for p in series], [True, True, True, False])
        self.assertEqual(series[2]["state_outage"], "N102")
        self.assertEqual(series[2]["state_label"], "堵管")

    def test_compound_events_and_unknown_replacement_order(self):
        repairs = [event("N101", events=["plugged", "shifted"], state="plugged"),
                   event("N102", events=["replaced", "plugged"], replacement_stage="unknown")]
        series = self.build([finding("N101"), finding("N102")], repairs)["tubes"][0]["series"]
        self.assertTrue(series[0]["plugged"])
        self.assertTrue(series[0]["shifted"])
        self.assertTrue(series[1]["needs_review"])
        self.assertIsNone(series[1]["max_depth"])
        self.assertEqual(series[1]["report_max_depth"], 10)

    def test_replacement_without_findings_is_baseline_not_reported_ndd(self):
        point = self.build([], [event("N102")])["tubes"][0]["series"][0]
        self.assertEqual(point["max_depth"], 0)
        self.assertIsNone(point["report_max_depth"])
        self.assertFalse(point["ndd"])
        self.assertEqual(point["records"], 0)

    def test_same_tube_number_isolated_by_site_and_unit(self):
        rows = [finding("N101", percent=11), {**finding("N201", percent=90), "unit_id": 2},
                finding("D101", percent=80)]
        repairs = [event("D101", state="plugged"), event("N201", unit_id=2),
                   event("N101", is_deleted=1)]
        tube = self.build(rows, repairs)["tubes"][0]
        self.assertEqual(tube["physical_key"], "N/1/1")
        self.assertEqual(len(tube["series"]), 1)
        self.assertEqual(tube["series"][0]["max_depth"], 11)
        self.assertFalse(tube["series"][0]["plugged"])
        self.assertFalse(tube["series"][0]["reset"])
        with patch.object(server.analysis_reporting, "rows_for", return_value=rows), patch.object(
                server.analysis_reporting, "repairs_for", return_value=repairs):
            even = server.tube_longitudinal("N", 2)["tubes"][0]
        self.assertEqual(even["physical_key"], "N/2/1")
        self.assertEqual(even["position"], server.position_for(2, 1))
        self.assertNotEqual(even["position"], tube["position"])

    def test_jump_threshold_custom_value_and_range_validation(self):
        data = self.build([finding("N101", percent=10), finding("N102", percent=25)], jump=20)
        self.assertEqual(data["jump"], 20.0)
        self.assertFalse(data["tubes"][0]["series"][1]["jump"])
        for bad in [4, 51]:
            with self.subTest(jump=bad), self.assertRaises(ValueError):
                self.build(jump=bad)
        # 非法字符串按设计回退默认阈值，不抛错
        fallback = self.build(jump="abc")
        self.assertEqual(fallback["jump"], server.TUBE_LONGITUDINAL_JUMP_DEFAULT)

    def test_invalid_tubes_and_unparsable_outages_ignored(self):
        data = self.build([finding("N101", tube=51), finding("N101", tube=0),
                           finding("ZZZ9"), finding("N101", tube=1)])
        self.assertEqual(data["outages"][0]["outage"], "N101")
        self.assertEqual([t["tube"] for t in data["tubes"]], list(range(1, 51)))
        self.assertTrue(data["tubes"][0]["has_history"])
        self.assertFalse(data["tubes"][1]["has_history"])

    def test_multiple_tubes_sorted_with_positions(self):
        rows = [finding("N101", tube=2, percent=20), finding("N102", tube=2, percent=40),
                finding("N101", tube=1, percent=10)]
        data = self.build(rows)
        self.assertEqual([t["tube"] for t in data["tubes"]], list(range(1, 51)))
        self.assertEqual(data["tubes"][0]["position"], "L11")
        self.assertEqual(data["tubes"][1]["position"], "G14")
        self.assertFalse(data["tubes"][2]["has_history"])
        self.assertEqual(data["tubes"][2]["series"], [])
        self.assertEqual(data["unit_code"], "N1")
        self.assertEqual(data["tubes"][1]["series"][1]["delta"], 20.0)

    def test_no_rows_yields_fifty_empty_tubes_without_invented_depths(self):
        data = self.build([])
        self.assertEqual([tube["tube"] for tube in data["tubes"]], list(range(1, 51)))
        self.assertTrue(all(not tube["has_history"] and not tube["series"] for tube in data["tubes"]))
        self.assertEqual(data["outages"], [])


if __name__ == "__main__":
    unittest.main()
