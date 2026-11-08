"""Axial placement preserves reference uncertainty and measurement provenance."""
import unittest
import native_test_env  # noqa: F401

from qt_shell.native_model_data import defect_placement, reference_layout, scene_data


class ModelDataTests(unittest.TestCase):
    def setUp(self):
        self.channel = reference_layout()["channels"][0]

    def test_reference_endpoints_and_signed_offsets(self):
        self.assertEqual(defect_placement({"location": "P1"}, self.channel)["y"], self.channel["yTop"])
        self.assertAlmostEqual(defect_placement({"location": "P6"}, self.channel)["y"], self.channel["yBase"], places=3)
        self.assertEqual(defect_placement({"location": "Point 2 - 12.5 mm"}, self.channel)["y"],
                         self.channel["yTop"] - 851 + 12.5)
        self.assertIsNone(defect_placement({"location": "待核对"}, self.channel))

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


if __name__ == "__main__":
    unittest.main()
