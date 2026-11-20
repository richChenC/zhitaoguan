"""磨损阈值档位：1–6 档自定义与非法配置拒绝。"""
import unittest

import native_test_env  # noqa: F401

from qt_shell.native_components import Preferences

COLORS = ["#eef4f2", "#efe0a8", "#e0a35c", "#c8424a", "#8f2f3b"]


class DepthLevelTests(unittest.TestCase):
    def test_four_levels_roundtrip(self):
        values = Preferences.validated({"depth_levels": [10, 25, 50, 75], "depth_colors": COLORS})
        self.assertEqual(values["depth_levels"], [10, 25, 50, 75])
        self.assertEqual(values["depth_colors"], COLORS)

    def test_single_level_roundtrip(self):
        values = Preferences.validated({"depth_levels": [40], "depth_colors": COLORS[:2]})
        self.assertEqual(values["depth_levels"], [40])
        self.assertEqual(values["depth_colors"], COLORS[:2])

    def test_invalid_levels_are_rejected(self):
        for levels, colors in (([10, 5, 30], COLORS[:4]), ([10, 20], COLORS[:2]),
                               ([10, 20, 30, 40, 50, 60, 70], COLORS[:8])):
            values = Preferences.validated({"depth_levels": levels, "depth_colors": colors})
            self.assertEqual(values["depth_levels"], Preferences.defaults["depth_levels"])
            self.assertEqual(values["depth_colors"], Preferences.defaults["depth_colors"])


if __name__ == "__main__":
    unittest.main()
