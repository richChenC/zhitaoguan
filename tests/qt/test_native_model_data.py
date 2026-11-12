"""Axial placement preserves reference uncertainty and measurement provenance."""
import unittest
import native_test_env  # noqa: F401

from qt_shell.native_model_data import (color_tubes, defect_placement, effective_depths, part_info,
                                       reference_channel, reference_parts, reference_layout, scene_data)


class ModelDataTests(unittest.TestCase):
    def setUp(self):
        self.channel = reference_layout()["channels"][0]

    def test_reference_endpoints_and_signed_offsets(self):
        self.assertEqual(defect_placement({"location": "P1"}, self.channel)["y"], self.channel["yTop"])
        self.assertAlmostEqual(defect_placement({"location": "P6"}, self.channel)["y"], self.channel["yBase"], places=3)
        self.assertEqual(defect_placement({"location": "Point 2 - 12.5 mm"}, self.channel)["y"],
                         self.channel["yTop"] - 851 + 12.5)
        self.assertIsNone(defect_placement({"location": "待核对"}, self.channel))

    def test_part_metadata_and_defaults_preserve_reference_evidence(self):
        parts = reference_parts()
        self.assertEqual([p["id"] for p in parts], [f"P0{i}" for i in range(1, 7)])
        self.assertEqual([p["id"] for p in parts if not p["visible"]], ["P03", "P04"])
        self.assertEqual([p["triCount"] for p in parts], [10752, 2700, 280, 4224, 3072, 3072])
        self.assertEqual([d["id"] for d in parts[3]["dimensions"]],
                         ["D15", "D16", "D17", "D18", "D19", "D21"])
        rows = part_info("P01", self.channel)
        self.assertEqual(rows[0][:2], ("指套管外径", "8.6　±0.05"))
        self.assertIn("推导", rows[2][2])
        self.assertIn("110.36 cm³", [row[1] for row in rows])
        self.assertIn("非电厂实测标定", rows[-2][2])
        for channel in reference_layout()["channels"]:
            self.assertEqual(reference_channel(int(channel["serialOdd"]), 1)["pos"], channel["pos"])
            self.assertEqual(reference_channel(int(channel["serialEven"]), 2)["pos"], channel["pos"])

    def test_uncertainty_and_maintenance_are_explicit(self):
        record = {"location": "P5+20", "state": "shifted", "offset_mm": -42}
        original = dict(record)
        measured = defect_placement(record, self.channel)
        preview = defect_placement(record, self.channel, maintenance_preview=True)
        self.assertEqual(measured["status"], "推定")
        self.assertFalse(measured["calibrated"])
        self.assertFalse(measured["maintenance_applied"])
        self.assertTrue(preview["maintenance_applied"])
        self.assertEqual(preview["y"] - measured["y"], 42)
        self.assertEqual(record, original)
        record["offset_confirmed"] = False
        self.assertFalse(defect_placement(record, self.channel, maintenance_preview=True)["maintenance_applied"])

    def test_scene_uses_source_lengths_and_does_not_invent_points(self):
        plate = [{"tube": int(c["serialOdd"]), "position": c["pos"], "records": 1,
                  "defects": 1} for c in reference_layout()["channels"]]
        records = [{"id": 1, "thimble_id": plate[0]["tube"], "category": "defect", "location": "P3+10"},
                   {"id": 2, "thimble_id": plate[0]["tube"], "category": "defect", "location": "未知"}]
        rows, tubes, defects, details, unresolved = scene_data({"plate": plate, "records": records})
        self.assertEqual(len(rows), 50)
        self.assertEqual(tubes[0]["length"], self.channel["L"])
        self.assertEqual(len(defects), 1)
        self.assertEqual(unresolved[0]["id"], 2)
        self.assertEqual(len(details[plate[0]["tube"]]), 2)
        plate[1]["position"] = plate[0]["position"]
        with self.assertRaises(ValueError):
            scene_data({"plate": plate})

    def test_depth_color_excludes_unquantified_and_nonfindings(self):
        records = [{"thimble_id": 1, "indication": "FRE", "percent": 30},
                   {"thimble_id": 1, "indication": "FRE", "percent": 50},
                   {"thimble_id": 1, "indication": "NDD", "percent": 90},
                   {"thimble_id": 2, "indication": "no defect", "percent": 70},
                   {"thimble_id": 3, "indication": "", "location_raw": "", "location": "P1", "percent": 90},
                   {"thimble_id": 4, "location_raw": None, "location": "P2", "percent": "20"},
                   {"thimble_id": 5, "indication": "FRE", "percent": float("inf")},
                   {"thimble_id": 6.5, "indication": "FRE", "percent": 70},
                   {"thimble_id": 7, "indication": "FRE", "percent": 0},
                   {"thimble_id": 8, "indication": "FRE", "percent": -1},
                   {"thimble_id": 9, "indication": "FRE", "percent": None}]
        self.assertEqual(effective_depths(records), {1: 50, 4: 20})

    def test_presentation_colors_preserve_geometry_and_follow_reference_priority(self):
        tubes = [{"tube": 1, "type": "I", "length": 100, "category": "ndd"},
                 {"tube": 2, "type": "空心柱", "length": 200, "category": "defect"},
                 {"tube": 3, "type": "II", "length": 150, "category": "missing"}]
        original = [dict(tube) for tube in tubes]
        records = [{"thimble_id": 1, "indication": "FRE", "percent": 30},
                   {"thimble_id": 2, "indication": "FRE", "percent": 50}]
        self.assertEqual([t["color"] for t in color_tubes(tubes, [], mode="type")],
                         ["#2f6fb5", "#8d8d8d", "#37a08a"])
        self.assertEqual([t["color"] for t in color_tubes(tubes, records, mode="depth")],
                         ["#e5a83b", "#df4b45", "#667c8c"])
        self.assertEqual([t["color"] for t in color_tubes(tubes, records, mode="depth", type_filter="II")],
                         ["#6b7480", "#6b7480", "#667c8c"])
        custom = color_tubes(tubes, records, mode="depth", levels=[10, 30, 50],
                            colors=["#111111", "#222222", "#333333", "#444444"])
        self.assertEqual([t["color"] for t in custom], ["#333333", "#444444", "#667c8c"])
        lengths = color_tubes(tubes, [], mode="length")
        self.assertEqual(lengths[0]["color"], "#8ec5eb")
        self.assertEqual(lengths[1]["color"], "#eb8e8e")
        self.assertEqual(tubes, original)
        self.assertEqual([{k: v for k, v in t.items() if k != "color"} for t in custom], original)


if __name__ == "__main__":
    unittest.main()
