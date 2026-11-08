"""Statistical parity at uncertainty, lifecycle and bin boundaries."""
import unittest
import native_test_env  # noqa: F401

from qt_shell.native_analysis_data import channel_frequency, depth_distribution, status_change


def tube(number, depth=10, **changes):
    return {"tube": number, "max_depth": depth, "coverage": "defect", "position": f"P{number}",
            "state_recorded": True, "state_badges": [], "current_events": [], "replacements": 0,
            "lifetime_replacements": 9, "offset_mm": 0, **changes}


def snap(order, tubes):
    return {"unit": "H2", "outage": f"H2{order:02}", "order": order, "tubes": tubes}


class NativeAnalysisDataTests(unittest.TestCase):
    def test_histogram_has_twenty_equal_bins_ndd_separate_and_no_missing_zeroes(self):
        result = depth_distribution([snap(1, [
            tube(1, 0), tube(2, 5), tube(3, 100), tube(4, None, coverage="NDD"),
            tube(5, None, coverage="missing"), tube(6, 40, missing_depth=1),
            tube(7, float("nan")), tube(8, 99.9)])])
        self.assertEqual(len(result["bins"]), 20)
        self.assertEqual(result["bins"][0][1], 1)
        self.assertEqual(result["bins"][1][1], 1)
        self.assertEqual(result["bins"][-1][1], 2)
        self.assertEqual((result["quantified"], result["NDD"], result["excluded"]), (4, 1, 3))

    def test_frequency_is_strict_and_deduplicates_channel_per_scope(self):
        first = snap(1, [tube(1, 30), tube(2, 31), tube(3, None, coverage="NDD")])
        second = snap(2, [tube(2, 40)])
        self.assertEqual(dict(channel_frequency([first, first, second], 30)), {"P2": 2})

    def test_intermediate_shift_excludes_delta_even_after_offset_is_restored(self):
        history = [snap(1, [tube(1, 10)]),
                   snap(2, [tube(1, 20, current_events=["shifted"], offset_mm=25)]),
                   snap(3, [tube(1, 30)])]
        result = status_change(history, "H2", "H203", baseline="H201")
        self.assertIsNone(result["rows"][0]["delta"])
        self.assertIn("移位", result["rows"][0]["exclusion"])

    def test_future_lifetime_replacement_does_not_exclude_past_comparison(self):
        history = [snap(1, [tube(1, 10)]), snap(2, [tube(1, 30)])]
        result = status_change(history, "H2", "H202")
        self.assertEqual(result["rows"][0]["delta"], 20)
        self.assertEqual(result["counts"]["up"], 1)

    def test_transient_position_and_unquantified_war_exclude_channel_delta(self):
        history = [snap(1, [tube(1), tube(2)]),
                   snap(2, [tube(1, position="B5"), tube(2)]),
                   snap(3, [tube(1, 30), tube(2, 30, missing_depth=1)])]
        result = status_change(history, "H2", "H203", baseline="H201")
        self.assertEqual(result["counts"]["comparable"], 0)
        self.assertIn("位置", result["rows"][0]["exclusion"])
        self.assertIn("未量化", result["rows"][1]["exclusion"])

    def test_ndd_to_war_and_stable_ndd_are_never_arithmetic_growth(self):
        history = [snap(1, [tube(1, None, coverage="NDD"), tube(2, None, coverage="NDD")]),
                   snap(2, [tube(1, 30), tube(2, None, coverage="NDD")])]
        result = status_change(history, "H2", "H202")
        self.assertEqual(result["counts"]["newWar"], 1)
        self.assertEqual(result["counts"]["comparable"], 0)
        self.assertFalse(result["rows"][1]["changed"])


if __name__ == "__main__":
    unittest.main()
