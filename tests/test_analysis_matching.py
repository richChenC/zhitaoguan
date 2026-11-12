"""Displacement matching parity without weakening unresolved maintenance guards."""
import unittest
from types import SimpleNamespace

from src.backend.analysis_reporting import compare_rows, complete_comparison, comparison_values, detection_summary


def finding(ident, location, percent=20, **changes):
    return dict(id=ident, thimble_id=1, indication="WAR", location=location,
                percent=percent, volts=1.2, **changes)


def repair(offset=42, **changes):
    return dict(outage="F101", unit_id=1, thimble_id=1, state="shifted",
                offset_mm=offset, **changes)


class AnalysisMatchingTests(unittest.TestCase):
    def compare(self, before, current, repairs=(), old="F101", new="F102"):
        return compare_rows(old, new, 1, before, current, repairs)

    def test_signed_shift_adds_to_historical_position(self):
        for offset, before, current in ((42, "P1+2", "P1+44"), (-42, "P1+44", "P1+2")):
            with self.subTest(offset=offset):
                result = self.compare([finding(1, before)], [finding(2, current, 30)],
                                      [repair(offset)])
                row = result["items"][0]
                self.assertEqual((row["comparison"], row["old_id"], row["delta_percent"]), ("R", 1, 10))
                self.assertIn("加上有符号移位量", row["comparison_note"])

    def test_opposite_direction_requires_confirmation(self):
        row = self.compare([finding(1, "P1+44")], [finding(2, "P1+2")], [repair()])["items"][0]
        self.assertEqual(row["comparison"], "待确认")
        self.assertIn("反方向", row["comparison_note"])
        self.assertIsNone(row["old_id"])
        self.assertIsNone(row["delta_percent"])

    def test_outside_tolerance_is_not_new_indication(self):
        row = self.compare([finding(1, "P1")], [finding(2, "P1+1")])["items"][0]
        self.assertEqual(row["comparison"], "待确认")
        self.assertIn("超出当前容差", row["comparison_note"])
        row = self.compare([finding(1, "P1")], [finding(2, "P2")])["items"][0]
        self.assertEqual(row["comparison"], "NI")

    def test_historical_record_cannot_be_reused(self):
        result = self.compare([finding(1, "P1")], [finding(2, "P1"), finding(3, "P1")])
        self.assertEqual([r["comparison"] for r in result["items"]], ["待确认", "待确认"])
        self.assertTrue(all(r["old_id"] is None and r["delta_percent"] is None for r in result["items"]))

    def test_complete_unchanged_pattern_conflicts_with_displacement(self):
        result = self.compare([finding(1, "P1"), finding(2, "P1+42")],
                              [finding(3, "P1"), finding(4, "P1+42")], [repair()])
        self.assertTrue(all(r["comparison"] == "待确认" for r in result["items"]))
        self.assertTrue(all("完整原位" in r["comparison_note"] for r in result["items"]))

    def test_original_position_can_be_new_after_old_indication_is_uniquely_claimed(self):
        result = self.compare([finding(1, "P1")],
                              [finding(2, "P1"), finding(3, "P1+42")], [repair()])
        self.assertEqual([r["comparison"] for r in result["items"]], ["NI", "R"])
        self.assertEqual(result["warnings"], [])

    def test_other_site_or_unit_maintenance_does_not_shift_matching(self):
        for event in ({**repair(), "outage": "N101"}, {**repair(), "unit_id": 2},
                      {**repair(), "outage": "F201", "unit_id": 2}):
            with self.subTest(event=event):
                row = self.compare([finding(1, "P1")], [finding(2, "P1")], [event])["items"][0]
                self.assertEqual((row["comparison"], row["shift_mm"]), ("R", 0))

    def test_uncertain_maintenance_and_plugging_keep_review_protection(self):
        for event in ({**repair(), "offset_mm": None, "offset_confirmed": 0},
                      {**repair(), "state": "plugged", "offset_mm": 0}):
            row = self.compare([finding(1, "P1")], [finding(2, "P1")], [event])["items"][0]
            self.assertEqual(row["comparison"], "待确认")
            self.assertIsNone(row["old_id"])
            self.assertIsNone(row["delta_percent"])
        event = {**repair(), "offset_mm": None, "offset_confirmed": 0}
        row = self.compare([finding(1, "P1")], [finding(2, "P1")], [event],
                           old="F102", new="F103")["items"][0]
        self.assertEqual(row["comparison"], "待确认")
        self.assertTrue(row["comparison_note"].startswith("维护状态需人工核查："))

    def test_replacement_breaks_old_baseline(self):
        row = self.compare([finding(1, "P1")], [finding(2, "P1", 30)],
                           [{**repair(), "state": "replaced", "offset_mm": 0}])["items"][0]
        self.assertEqual(row["comparison"], "NI")
        self.assertIsNone(row["old_id"])
        self.assertIsNone(row["delta_percent"])

    def test_input_records_remain_unchanged(self):
        before, current = [finding(1, "P1")], [finding(2, "P1+42")]
        original = [r.copy() for r in before + current]
        self.compare(before, current, [repair()])
        self.assertEqual(before + current, original)

    def test_detection_counts_use_exclusive_tubes_and_separate_raw_records(self):
        rows = [finding(1, "P1"), finding(2, "P4"),
                {**finding(3, ""), "indication": "NDD", "percent": None, "volts": None},
                {**finding(4, ""), "thimble_id": 2, "indication": "NDD", "percent": None, "volts": None},
                {**finding(5, "P1"), "thimble_id": 3, "indication": ""}]
        data = detection_summary(rows, "F102")
        self.assertEqual((data["records"], data["tubes"]), (5, 3))
        self.assertEqual((data["war_tubes"], data["ndd_tubes"], data["other_tubes"]), (1, 1, 1))
        self.assertEqual((data["war_records"], data["ndd_records"], data["other_records"]), (2, 2, 1))
        self.assertEqual(data["tube_ids"], {"war": [1], "ndd": [2], "other": [3]})
        self.assertEqual(data["mixed_ndd_tubes"], [1])
        self.assertEqual(data["missing_tubes"], list(range(4, 51)))


class OfficialComparisonTests(unittest.TestCase):
    def compare(self, old, new, unit, tube, offset, pairs, changes=None):
        before, current = [], []
        for index, (old_pos, old_v, old_depth, new_pos, new_v, new_depth) in enumerate(pairs, 1):
            before.append(dict(id=index, thimble_id=tube, indication="WAR",
                               location=old_pos, volts=old_v, percent=old_depth))
            current.append(dict(id=index + 100, thimble_id=tube, indication="WAR",
                                location=new_pos, volts=new_v, percent=new_depth))
        if changes:
            changes(before, current)
        events = [dict(outage=old, unit_id=unit, thimble_id=tube,
                       state="shifted", offset_mm=offset)]
        result = compare_rows(old, new, unit, before, current, events)
        service = SimpleNamespace(position_for=lambda _unit, _tube: "test-position")
        return complete_comparison(service, result, before, current), before, current

    def test_h101_original_p3_adjudication(self):
        result, _, _ = self.compare("H101", "H102", 1, 2, 42,
                                    [("P3", 1.12, 23, "P3", 1.46, 21)])
        row = result["items"][1]
        self.assertEqual((row["comparison"], row["old_id"], row["delta_percent"]), ("R", 1, -2))
        self.assertIn("PDF第9页", row["official_evidence"])

    def test_f202_covered_old_indication_is_r1_without_fabricated_depth(self):
        result, _, _ = self.compare("F201", "F202", 2, 43, 42,
                                    [("P5", 7.57, 61, "P5", 20.74, 84)])
        rows = [row for row in result["items"] if row["thimble_id"] == 43]
        self.assertEqual([row["comparison"] for row in rows], ["NI", "R1"])
        self.assertIsNone(rows[0]["old_id"])
        self.assertEqual((rows[1]["location"], rows[1]["old_id"]), ("P5+42", 1))
        self.assertIsNone(rows[1]["percent"])
        self.assertEqual(result["summary"]["R1"], 1)
        self.assertEqual(comparison_values(result["items"])[1][5:10],
                         ["P5+42mm", 7.57, 61, "P5", "R1"])

    def test_f103_corrected_position_preserves_original_p4(self):
        result, before, _ = self.compare("F102", "F103", 1, 42, 45,
                                         [("P4", 4.20, 47, "P5+45", 4.39, 47)])
        row = next(row for row in result["items"] if row["thimble_id"] == 42)
        self.assertEqual((row["comparison"], row["comparison_display"], row["old_location"]), ("R", "R*", "P5"))
        self.assertEqual((row["old_source_location"], before[0]["location"]), ("P4", "P4"))
        self.assertEqual(result["summary"]["R*"], 1)
        self.assertEqual(comparison_values(result["items"])[0][9], "R*")

    def test_h204_all_six_original_positions(self):
        result, _, _ = self.compare("H203", "H204", 2, 45, 44, [
            (pos, old_v, old_depth, pos, new_v, new_depth)
            for pos, old_v, old_depth, new_v, new_depth in (
                ("P1", 1.75, 27, 1.73, 26), ("P1+44", 2.33, 33, 2.18, 31),
                ("P1+86", 2.12, 31, 2.00, 29), ("P4", 2.74, 37, 2.76, 36),
                ("P4+44", 4.44, 48, 4.32, 47), ("P4+86", 4.37, 48, 4.14, 46))])
        rows = [row for row in result["items"] if row["thimble_id"] == 45]
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(row["comparison"] == "R" and "官方报告" in row["comparison_note"] for row in rows))
        self.assertEqual([row["delta_percent"] for row in rows], [-1, -2, -2, -1, -1, -2])

    def test_adjudication_requires_unique_exact_source_and_offset(self):
        pairs = [("P3", 1.12, 23, "P3", 1.46, 21)]
        for offset, changes in (
                (41, None),
                (42, lambda _before, current: current[0].update(volts=1.47)),
                (42, lambda before, _current: before.append({**before[0], "id": 2})),
                (42, lambda _before, current: current.append({**current[0], "id": 102})),
                (None, None)):
            with self.subTest(offset=offset, changes=changes):
                result, _, _ = self.compare("H101", "H102", 1, 2, offset, pairs, changes)
                self.assertFalse(any(row.get("official_evidence") for row in result["items"]))


if __name__ == "__main__":
    unittest.main()
