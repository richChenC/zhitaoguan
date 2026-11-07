import unittest

from src.backend import tube_lifecycle


class TubeLifecycleTests(unittest.TestCase):
    def row(self, outage, events, **extra):
        return {"outage": outage, "unit_id": 1, "thimble_id": 7,
                "events": events, **extra}

    def effective(self, records, outage):
        return tube_lifecycle.effective(records, outage, 1, 7)

    def test_plug_persists_across_outages_until_replacement(self):
        records = [self.row("D116", ["plugged"]),
                   self.row("D117", ["shifted"], offset_mm=-12),
                   self.row("D118", [])]
        current = self.effective(records, "D118")
        self.assertTrue(current["plugged"])
        self.assertEqual(current["plug_since"], "D116")
        self.assertEqual(current["state"], "plugged")
        self.assertEqual(current["cumulative_offset_mm"], -12)
        self.assertTrue(current["inherited_plug"])

    def test_replacement_starts_generation_and_resets_offset(self):
        records = [self.row("D116", ["shifted"], offset_mm=-12),
                   self.row("D117", ["replaced"])]
        current = self.effective(records, "D117")
        self.assertEqual(current["generation"], 2)
        self.assertEqual(current["cumulative_offset_mm"], 0)
        self.assertFalse(current["plugged"])

    def test_replacement_with_confirmed_post_events_applies_events_to_new_tube(self):
        records = [self.row("D116", ["plugged"]),
                   self.row("D117", ["replaced", "plugged", "shifted"],
                            replacement_stage="after_replacement", offset_mm=8)]
        current = self.effective(records, "D117")
        self.assertTrue(current["plugged"])
        self.assertEqual(current["plug_since"], "D117")
        self.assertEqual(current["cumulative_offset_mm"], 8)
        self.assertFalse(current["needs_review"])

    def test_replacement_with_unknown_order_does_not_guess_coevents(self):
        records = [self.row("D116", ["plugged"]),
                   self.row("D117", ["replaced", "plugged", "shifted"],
                            replacement_stage="unknown", offset_mm=8)]
        current = self.effective(records, "D117")
        self.assertEqual(current["generation"], 2)
        self.assertFalse(current["plugged"])
        self.assertIsNone(current["cumulative_offset_mm"])
        self.assertTrue(current["needs_review"])
        self.assertTrue(any("先后顺序待确认" in warning for warning in current["warnings"]))

    def test_unknown_shift_direction_stays_unconfirmed(self):
        current = self.effective([
            self.row("D116", ["shifted"], offset_mm=None, unsigned_offset_mm=42,
                     offset_confirmed=0)
        ], "D116")
        self.assertIsNone(current["cumulative_offset_mm"])
        self.assertTrue(current["needs_review"])
        self.assertTrue(any("未确认" in warning for warning in current["warnings"]))

    def test_shift_badge_persists_with_plug_and_even_zero_net_movement(self):
        records = [self.row("D116", ["shifted"], offset_mm=-12),
                   self.row("D117", ["shifted", "plugged"], offset_mm=12)]
        current = self.effective(records, "D118")
        self.assertEqual(current["state_label"], "堵管 · 移位")
        self.assertEqual(current["cumulative_offset_mm"], 0)
        self.assertTrue(current["shifted"])

    def test_pre_replacement_events_do_not_apply_to_new_tube(self):
        records = [self.row("D116", ["plugged", "shifted"], offset_mm=-12),
                   self.row("D117", ["replaced", "plugged", "shifted"],
                            replacement_stage="before_replacement", offset_mm=8)]
        current = self.effective(records, "D118")
        self.assertEqual(current["generation"], 2)
        self.assertEqual(current["state_label"], "正常")
        self.assertFalse(current["plugged"])
        self.assertFalse(current["shifted"])
        self.assertEqual(current["cumulative_offset_mm"], 0)

    def test_ambiguous_replacement_never_displays_normal_in_later_outage(self):
        records = [self.row("D116", ["plugged", "replaced"])]
        current = self.effective(records, "D117")
        self.assertEqual(current["state"], "unknown")
        self.assertEqual(current["state_label"], "状态待核对")
        self.assertTrue(current["needs_review"])

    def test_index_matches_history_with_aliases_and_isolates_tubes(self):
        records = [
            self.row("HZ101", ["plugged"]),
            self.row("P102", ["shifted"], offset_mm=-42),
            self.row("HZ104", ["replaced"]),
            self.row("HZ103", ["replaced"], is_deleted=1),
            self.row("CN101", ["shifted"], offset_mm=12),
            self.row("C102", ["plugged"]),
            self.row("D101", ["replaced"]),
            self.row("P201", ["plugged"], unit_id=2),
            self.row("P101", ["replaced"], thimble_id=8),
            self.row("P101", ["replaced"], unit_id=2),
        ]
        history = tube_lifecycle.StateHistory(records)
        for outage, unit, tube in [
                ("HZ103", 1, 7), ("P104", 1, 7), ("CN102", 1, 7),
                ("C103", 1, 7), ("P201", 2, 7), ("P103", 1, 8),
                ("P103", 2, 7), ("D102", 1, 7), ("LF101", 1, 7)]:
            for inclusive in (True, False):
                with self.subTest(outage=outage, unit=unit, tube=tube, inclusive=inclusive):
                    self.assertEqual(
                        history.effective(outage, unit, tube, inclusive=inclusive),
                        tube_lifecycle.effective(records, outage, unit, tube, inclusive=inclusive))

    def test_index_updates_and_removes_records_without_stale_state(self):
        history = tube_lifecycle.StateHistory([self.row("D101", ["plugged"])])
        self.assertTrue(history.effective("D103", 1, 7)["plugged"])
        history.upsert(self.row("D102", ["replaced"]))
        self.assertFalse(history.effective("D103", 1, 7)["plugged"])
        history.upsert(self.row("D102", ["replaced"], is_deleted=1))
        self.assertTrue(history.effective("D103", 1, 7)["plugged"])
        self.assertIsNone(history.get("D102", 1, 7))


if __name__ == "__main__":
    unittest.main()
