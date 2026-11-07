import unittest
from unittest.mock import patch
from src.backend import visualization_reporting as visual


class Service:
    @staticmethod
    def position_for(unit, tube):
        return f"N{tube}"


def finding(outage, tube=1, indication="WAR", percent=10, location="P1+2"):
    return dict(outage=outage, unit_id=1, thimble_id=tube, indication=indication,
                percent=percent, location=location, datapoint=1)


class VisualizationTests(unittest.TestCase):
    def build(self, rows, query=None, repairs=None):
        with patch.object(visual.analysis, "rows_for", return_value=rows), patch.object(
                visual.analysis, "repairs_for", return_value=repairs or []):
            return visual.build(Service, query or {})

    def test_multiple_sites_and_lufeng_not_lingao(self):
        rows = [finding("LF101"), finding("L101"), finding("F101")]
        data = self.build(rows, {"sites": "LF,F"})
        self.assertEqual({t["unit"] for t in data["trends"]}, {"LF1", "F1"})
        self.assertEqual(data["map"]["L"]["findings"], 0)
        with self.assertRaises(ValueError):
            self.build(rows, {"sites": "LF", "unit": "L1"})

    def test_future_sites_empty_and_populated_scopes(self):
        for code, name in [("P", "惠州"), ("LF", "陆丰"), ("C", "苍南")]:
            empty = self.build([finding("N101")], {"sites": code})
            self.assertEqual(empty["summary"]["records"], 0)
            self.assertEqual(empty["sites"][code], name)
            populated = self.build([finding(f"{code}101"), finding("L101")],
                                   {"sites": code, "unit": f"{code}1"})
            self.assertEqual([row["unit"] for row in populated["trends"]], [f"{code}1"])

    def test_position_reconciliation_and_invalid_depth(self):
        rows = [finding("N101", percent=12), finding("N101", percent=8, location="P6-2.5mm"),
                finding("N101", percent=7, location="other"), finding("N101", percent=None)]
        data = self.build(rows)
        trend = data["trends"][0]
        self.assertEqual(trend["total"], 27)
        self.assertEqual(sum(trend["positions"].values()), trend["total"])
        self.assertEqual(trend["positions"]["P6"], 8)
        self.assertEqual(data["quality"]["unquantified_wear_rows"], 1)
        self.assertEqual(trend["position_stats"]["P1"]["max_depth"], 12)
        self.assertEqual(trend["position_stats"]["P6"]["total"], 8)
        self.assertEqual(trend["position_stats"]["未解析"]["tubes"], 1)
        self.assertEqual(data["snapshots"][0]["tubes"][0]["findings"][0]["depth"], 12)
        self.assertEqual(data["snapshots"][0]["tubes"][0]["findings"][0]["location"], "P1+2")
        self.assertEqual(data["snapshots"][0]["tubes"][0]["missing_depth"], 1)

    def test_zero_ndd_missing_and_unknown_are_distinct(self):
        data = self.build([finding("N101", indication="NDD", percent=None),
                           finding("N102", indication="", percent=None),
                           finding("N103", percent=None)])
        self.assertEqual([r["total"] for r in data["trends"]], [0, None, None])
        self.assertEqual(data["snapshots"][0]["tubes"][1]["coverage"], "missing")
        self.assertEqual(data["snapshots"][2]["tubes"][0]["coverage"], "defect")
        self.assertIsNone(data["snapshots"][2]["tubes"][0]["max_depth"])

    def test_screenshot_position_anomalies_keep_all_war_depths(self):
        rows = [
            dict(finding("F101", percent=29, location="Point 1"), channel="M1a4-6"),
            dict(finding("F101", tube=2, percent=21, location="Point 4"), channel="M1a4-6"),
            dict(finding("F107", tube=19, percent=52, location=""), channel="P1: 4-6", datapoint=21359),
            dict(finding("N109", percent=47, location="PI+168"), channel="P1: 4-6"),
            dict(finding("Y402", tube=50, percent=26, location="M1a4-6"), unit_id=4, channel="P5"),
        ]
        originals = [row.copy() for row in rows]
        data = self.build(rows)
        totals = {}
        for trend in data["trends"]:
            self.assertEqual(sum(trend["positions"].values()), trend["total"])
            for key, value in trend["positions"].items():
                totals[key] = totals.get(key, 0) + value
        self.assertEqual(totals, {"P1": 29, "P4": 21, "未解析": 125})
        self.assertEqual(sum(totals.values()), 175)
        self.assertEqual(data["quality"]["unparsed_wear_positions"], 3)
        self.assertNotIn("provisional_wear_positions", data["quality"])
        findings = [f for snapshot in data["snapshots"] for tube in snapshot["tubes"] for f in tube["findings"]]
        self.assertEqual(sorted(f["depth"] for f in findings), [21, 26, 29, 47, 52])
        self.assertEqual({f["location"]: f["position_status"] for f in findings},
                         {"Point 1": "parsed", "Point 4": "parsed", "": "missing",
                          "PI+168": "source_label", "M1a4-6": "source_label"})
        self.assertTrue(all(f["position_note"] for f in findings))
        for snapshot in data["snapshots"]:
            for tube in snapshot["tubes"]:
                if tube["findings"]:
                    self.assertEqual(tube["coverage"], "defect")
                    self.assertEqual(tube["max_depth"], tube["findings"][0]["depth"])
                    self.assertEqual(tube["incomplete_records"], 0)
        self.assertEqual(rows, originals)

    def test_depth_statistics_are_independent_of_location_and_channel(self):
        expected = None
        for location in ["P1", "Point 1", "Point 4", "M1a4-6", "PI+168", "", "other"]:
            for channel in ["", "P5", "Point 4", "M1a4-6"]:
                with self.subTest(location=location, channel=channel):
                    rows = [dict(finding("F101", tube=i + 1, percent=depth, location=location),
                                 channel=channel)
                            for i, depth in enumerate([0, 29, 47, 100, None, -1, 101, float("nan")])]
                    rows.append(finding("F101", tube=9, indication="NDD", percent=90, location=location))
                    data = self.build(rows)
                    trend = data["trends"][0]
                    facts = (data["summary"], trend["total"], data["quality"]["unquantified_wear_rows"],
                             [(t["tube"], t["coverage"], t["max_depth"], t["records"],
                               t["missing_depth"], t["incomplete_records"])
                              for t in data["snapshots"][0]["tubes"]])
                    if expected is None:
                        expected = facts
                    self.assertEqual(facts, expected)
                    self.assertEqual(trend["total"], 176)
                    self.assertEqual(sum(trend["positions"].values()), trend["total"])

    def test_mixed_valid_and_incomplete_rows_keep_review_flag(self):
        data = self.build([finding("N101", percent=15),
                           finding("N101", indication="", percent=None)])
        tube = data["snapshots"][0]["tubes"][0]
        self.assertEqual(tube["coverage"], "defect")
        self.assertEqual(tube["max_depth"], 15)
        self.assertEqual(tube["incomplete_records"], 1)
        self.assertEqual(data["units"][0]["history"][0]["incomplete_tubes"], [1])

    def test_maintenance_history_and_original_note(self):
        note = "  割管移位 -2 mm\n保留原文  "
        events = [dict(outage=o,unit_id=1,thimble_id=1,state=s,offset_mm=None,note=note,source="原表")
                  for o,s in [("N101","replaced"),("N102","shifted"),("N104","replaced")]]
        data = self.build([finding("N103")], repairs=events)
        tube = next(item for item in data["snapshots"] if item["outage"] == "N103")["tubes"][0]
        self.assertEqual(tube["state"], "shifted")
        self.assertEqual(tube["replacements"], 1)
        self.assertEqual(tube["lifetime_replacements"], 2)
        self.assertEqual(tube["lifetime_replacement_outages"], ["N101", "N104"])
        self.assertEqual(tube["remarks"], note)
        self.assertIsNone(tube["offset_mm"])

    def test_replacement_evidence_is_current_not_inherited_and_survives_filter(self):
        events = [
            dict(id=11, outage="N101", thimble_id=1, state="replaced",
                 source="模拟原表.xlsx", note="模拟换管", updated_at="2026-11-01"),
            dict(id=12, outage="N103", thimble_id=1, state="shifted", offset_mm=42),
            dict(id=13, outage="N104", thimble_id=2, state="replaced",
                 events=["replaced", "shifted"], replacement_stage="unknown", offset_mm=42),
        ]
        data = self.build([finding("N102")], {"outage": "N102"}, events)
        self.assertEqual(len(data["snapshots"]), 1)
        self.assertIsNone(data["snapshots"][0]["tubes"][0]["replacement_record"])
        history = {entry["outage"]: entry for entry in data["units"][0]["history"]}
        self.assertEqual(history["N101"]["replacement_records"], [
            dict(key="N101/1/1", outage="N101", tube=1, source="模拟原表.xlsx",
                 note="模拟换管", updated_at="2026-11-01")])
        self.assertEqual(history["N102"]["replacement_records"], [])
        self.assertEqual(history["N103"]["replacement_records"], [])
        self.assertEqual(history["N104"]["replacement_records"][0]["key"], "N104/1/2")
        self.assertEqual(history["N104"]["state_current_tubes"], [2])

    def test_outage_must_belong_to_scope(self):
        with self.assertRaises(ValueError):
            self.build([finding("N101"),finding("F101")], {"sites":"N","outage":"F101"})

    def test_comparison_baseline_survives_single_outage_filter(self):
        data = self.build([finding("N101"), finding("N102"), finding("N103"), finding("N201")],
                          {"sites": "N", "unit": "N1", "outage": "N103"})
        self.assertEqual([row["outage"] for row in data["snapshots"]], ["N103"])
        self.assertEqual([row["outage"] for row in data["comparison_baselines"]], ["N101", "N102"])
        self.assertEqual(data["summary"]["outages"], 1)
        self.assertEqual(len(data["comparison_baselines"][0]["tubes"]), 50)

    def test_comparison_baseline_does_not_invent_missing_round_or_other_unit(self):
        rows = [finding("N101"), finding("N103"), finding("N202")]
        gap = self.build(rows, {"outage": "N103"})
        self.assertEqual([row["outage"] for row in gap["comparison_baselines"]], ["N101"])
        self.assertEqual(gap["comparison_baselines"][0]["order"], 1)
        self.assertEqual(self.build(rows, {"outage": "N202"})["comparison_baselines"], [])
        self.assertEqual(self.build(rows)["comparison_baselines"], [])

    def test_lifetime_replacements_survive_earlier_outage_filter(self):
        events = [
            dict(outage="N102", thimble_id=1, state="replaced"),
            dict(outage="N104", thimble_id=1, state="replaced"),
            dict(outage="N104", thimble_id=2, state="shifted"),
            dict(outage="N201", thimble_id=1, state="replaced"),
        ]
        data = self.build([finding("N101"), finding("N104")], {"outage": "N101"}, events)
        self.assertEqual(len(data["snapshots"]), 1)
        tubes = data["snapshots"][0]["tubes"]
        self.assertEqual(tubes[0]["replacements"], 0)
        self.assertEqual(tubes[0]["lifetime_replacements"], 2)
        self.assertEqual(tubes[0]["lifetime_replacement_outages"], ["N102", "N104"])
        self.assertEqual(tubes[1]["lifetime_replacements"], 0)
        self.assertEqual(tubes[0]["current_events"], [])

    def test_unsigned_shift_distance_is_preserved(self):
        event = dict(outage="N101", thimble_id=1, state="shifted",
                     offset_mm=None, unsigned_offset_mm=42, note="割管移位42mm", source="原表")
        tube = self.build([finding("N102")], repairs=[event])["snapshots"][0]["tubes"][0]
        self.assertIsNone(tube["offset_mm"])
        self.assertEqual(tube["unsigned_offset_mm"], 42)
        self.assertEqual(tube["replacements"], 0)

    def test_future_maintenance_and_other_units_are_excluded(self):
        events = [dict(outage=o, thimble_id=1, state="replaced") for o in ["N103","F101","N201"]]
        data = self.build([finding("N102")], repairs=events)
        tube = next(item for item in data["snapshots"] if item["outage"] == "N102")["tubes"][0]
        self.assertIsNone(tube["state"])
        self.assertEqual(tube["replacements"], 0)

    def test_latest_coverage_counts_channels_not_findings(self):
        rows = [finding("N101", tube=1), finding("N102", tube=2), finding("N102", tube=2)]
        data = self.build(rows)
        self.assertEqual(data["summary"]["reported_tubes"], 1)
        self.assertEqual(data["summary"]["missing_tubes"], 49)
        self.assertEqual(data["summary"]["records"], 3)
        self.assertEqual(self.build(rows, {"outage":"N101"})["coverage"][0]["outage"], "N101")

    def test_coverage_never_rounds_missing_channels_to_complete(self):
        rows = [finding(f"N{unit}01", tube=tube) for unit in range(1, 5)
                for tube in range(1, 51) if (unit, tube) != (1, 27)]
        data = self.build(rows)
        self.assertEqual(data["site_summary"]["N"]["reported"], 199)
        self.assertEqual(data["site_summary"]["N"]["total"], 200)
        self.assertEqual(data["site_summary"]["N"]["coverageRate"], 99.5)
        self.assertEqual(data["site_summary"][""]["coverageRate"], 99.5)
        self.assertEqual(self.build(rows, {"unit": "N1"})["site_summary"], data["site_summary"])

    def test_no_signal_placeholders_are_ndd_other_unknowns_remain_reviewable(self):
        rows = [finding("N101", tube=1, indication="NOS", percent=90),
                finding("N101", tube=2, indication="/", percent=None),
                dict(finding("N101", tube=3, indication="", percent=None, location=""), datapoint=0),
                finding("N101", tube=4, indication="WAR", percent=12),
                finding("N101", tube=4, indication="NOS", percent=95),
                finding("N101", tube=5, indication="NDD", percent=None)]
        data = self.build(rows)
        tubes = data["snapshots"][0]["tubes"]
        self.assertEqual([tube["coverage"] for tube in tubes[:5]],
                         ["incomplete", "incomplete", "NDD", "defect", "NDD"])
        self.assertTrue(all(tube["max_depth"] is None for tube in tubes[:3]))
        self.assertEqual(tubes[3]["max_depth"], 12)
        self.assertEqual(tubes[3]["incomplete_records"], 1)
        self.assertEqual(tubes[3]["missing_depth"], 0)
        self.assertEqual(data["trends"][0]["total"], 12)
        self.assertEqual(data["trends"][0]["incomplete_tubes"], 3)
        history = data["units"][0]["history"][0]
        self.assertEqual(history["conclusion_records"], {"NOS": 2, "/": 1, "": 1, "WAR": 1, "NDD": 1})
        self.assertEqual(history["detection_tubes"], {"defect": [4], "NDD": [3, 5], "incomplete": [1, 2]})
        self.assertEqual(history["incomplete_tubes"], [1, 2, 4])
        self.assertEqual(tubes[0]["findings"][0]["indication"], "NOS")
        self.assertEqual(tubes[2]["findings"][0]["indication"], "")
        self.assertIn("按 NDD 统计", tubes[2]["findings"][0]["classification_basis"])

    def test_ndd_inference_requires_no_signal_evidence_and_preserves_sources(self):
        base = dict(finding("N109", indication="/", percent=None, location="/"),
                    datapoint=0, volts=None, measurement_type="None")
        original = base.copy()
        self.assertEqual(visual.report_category(base), "NDD")
        for field, value in [("volts", 0.2), ("degrees", 0.0), ("percent", 1),
                             ("channel", "P1: 4-6"), ("location", "Point 1"), ("measurement_type", "WALL"),
                             ("indication", "NOS"), ("indication", "WAR")]:
            with self.subTest(field=field, value=value):
                row = {**base, field: value}
                self.assertNotEqual(visual.report_category(row), "NDD")
        result = self.build([base])
        self.assertEqual(result["snapshots"][0]["tubes"][0]["coverage"], "NDD")
        self.assertEqual(result["snapshots"][0]["tubes"][0]["findings"][0]["indication"], "/")
        self.assertEqual(base, original)

    def test_history_keeps_maintenance_source_and_note_without_truncation(self):
        note = "  原始维护备注\n第二行  "
        source = "原始台账.xlsx · N101 第18行\n另一个来源第19行"
        data = self.build([finding("N102")], repairs=[
            dict(outage="N101", thimble_id=1, state="shifted", offset_mm=None,
                 unsigned_offset_mm=42, source=source, note=note)])
        record = next(row for row in data["units"][0]["history"]
                      if row["outage"] == "N102")["state_sources"][0]
        self.assertEqual(record["tube"], 1)
        self.assertEqual(record["outage"], "N101")
        self.assertEqual(record["note"], note)
        self.assertEqual(record["source"], source)
        self.assertTrue(record["warnings"])

    def test_outage_summary_counts_only_filtered_snapshots_including_maintenance(self):
        rows = [finding("N101"), finding("N102"), finding("N201"), finding("F101")]
        repairs = [dict(outage="N103", thimble_id=1, state="plugged")]
        for query, expected in [({}, 5), ({"sites": "N"}, 4),
                                ({"unit": "N1"}, 3), ({"outage": "N103"}, 1),
                                ({"sites": "LF"}, 0)]:
            with self.subTest(query=query):
                data = self.build(rows, query, repairs)
                self.assertEqual(data["summary"]["outages"], expected)
                self.assertEqual(len(data["snapshots"]), expected)

    def test_partial_trends_keep_numeric_values_and_distinguish_full_coverage(self):
        for indication, percent, total in [("WAR", 10, 10), ("NDD", None, 0)]:
            with self.subTest(indication=indication):
                row = self.build([finding("N101", indication=indication, percent=percent)])["trends"][0]
                self.assertEqual(row["total"], total)
                self.assertEqual(row["reported_tubes"], 1)
                self.assertEqual(row["missing_tubes"], 49)
                self.assertTrue(row["partial"])
                complete = self.build([finding("N101", tube=tube, indication=indication,
                                               percent=percent) for tube in range(1, 51)])["trends"][0]
                self.assertEqual(complete["reported_tubes"], 50)
                self.assertEqual(complete["missing_tubes"], 0)
                self.assertFalse(complete["partial"])

    def test_incomplete_conclusions_stay_partial_even_with_numeric_wear(self):
        rows = [finding("N101", tube=tube) for tube in range(1, 51)]
        for additional in [False, True]:
            with self.subTest(additional=additional):
                incomplete = finding("N101", tube=1, indication="", percent=None)
                data = self.build(rows + [incomplete] if additional else [incomplete] + rows[1:])
                trend = data["trends"][0]
                self.assertEqual(trend["missing_tubes"], 0)
                self.assertEqual(trend["incomplete_tubes"], 1)
                self.assertTrue(trend["partial"])
                self.assertEqual(trend["total"], 500 if additional else 490)

    def test_inherited_ambiguous_state_has_a_record_and_requires_review(self):
        data = self.build([finding("D203")], repairs=[
            dict(outage="D202", thimble_id=3, state="replaced",
                 events=["replaced", "shifted"], replacement_stage="unknown", offset_mm=8)])
        entry = data["units"][0]["history"][-1]
        self.assertEqual(entry["state_review_tubes"], [3])
        self.assertEqual(len(entry["state_missing_tubes"]), 49)
        self.assertNotIn(3, entry["state_missing_tubes"])
        self.assertTrue(all(not tubes for tubes in entry["state_tubes"].values()))
        tube = data["snapshots"][-1]["tubes"][2]
        self.assertEqual(tube["state"], "unknown")
        self.assertTrue(tube["state_recorded"])
        self.assertEqual(tube["state_badges"], [])

    def test_physical_outage_numbers_and_each_units_missing_history(self):
        data = self.build([finding("D101"), finding("D120"), finding("D203")])
        units = {unit["code"]: unit for unit in data["units"]}
        self.assertEqual(units["D1"]["latest_order"], 20)
        self.assertEqual(units["D1"]["outage_entries"][-1]["label"], "第020次大修")
        self.assertEqual(units["D1"]["missing_outages"], [f"D1{n:02d}" for n in range(2, 20)])
        self.assertEqual(units["D2"]["missing_outages"], ["D201", "D202"])
        self.assertEqual([t["outage_index"] for t in data["trends"]], [1, 20, 3])
        self.assertEqual(units["D1"]["history"][-1]["missing_tubes"], list(range(2, 51)))
        self.assertEqual(units["D1"]["history"][-1]["state_missing_tubes"], list(range(1, 51)))

    def test_maintenance_only_outage_does_not_claim_detection_or_ndd(self):
        data = self.build([finding("D101")], repairs=[
            dict(outage="D103", thimble_id=2, state="plugged")])
        unit = data["units"][0]
        self.assertEqual(unit["detection_outages"], ["D101"])
        self.assertEqual(unit["missing_outages"], ["D102"])
        last = unit["history"][-1]
        self.assertEqual(last["outage"], "D103")
        self.assertEqual(last["records"], 0)
        self.assertEqual(last["counts"], {"missing": 50})
        self.assertEqual(last["state_tubes"]["plugged"], [2])
        self.assertEqual(last["state_current_missing_tubes"], [n for n in range(1, 51) if n != 2])
        self.assertEqual(data["summary"]["missing_tubes"], 50)
        self.assertEqual([t["outage"] for t in data["trends"]], ["D101"])

    def test_history_distinguishes_overlap_inheritance_and_replacement(self):
        rows = [finding(f"D1{n:02d}") for n in range(1, 6)]
        events = [
            dict(outage="D101", thimble_id=1, events=["plugged", "shifted"],
                 state="plugged", offset_mm=12),
            dict(outage="D103", thimble_id=1, state="normal"),
            dict(outage="D104", thimble_id=1, state="replaced"),
            dict(outage="D105", thimble_id=2, state="replaced",
                 events=["replaced", "shifted"], replacement_stage="unknown", offset_mm=8),
        ]
        history = self.build(rows, repairs=events)["units"][0]["history"]
        self.assertEqual(history[1]["state_tubes"]["plugged"], [1])
        self.assertEqual(history[1]["state_tubes"]["shifted"], [1])
        self.assertEqual(history[1]["inherited_plug_tubes"], [1])
        self.assertEqual(history[1]["state_current_tubes"], [])
        self.assertEqual(history[1]["state_current_missing_tubes"], list(range(1, 51)))
        self.assertNotIn(1, history[1]["state_missing_tubes"])
        self.assertEqual(history[2]["state_tubes"]["plugged"], [1])
        self.assertEqual(history[3]["state_tubes"]["plugged"], [])
        self.assertEqual(history[3]["state_tubes"]["shifted"], [])
        self.assertEqual(history[3]["state_tubes"]["replaced"], [1])
        self.assertEqual(history[4]["state_review_tubes"], [2])


class VisualizationIncrementTests(unittest.TestCase):
    build = VisualizationTests.build

    @staticmethod
    def record(outage, ident, tube=1, **changes):
        return {**finding(outage, tube), "id": ident, "report_path": f"原表/{outage}.rpt",
                "channel": "M1a4-6", **changes}

    def test_pairs_preserve_mp_labels_sources_and_negative_deltas(self):
        rows = [self.record("F101", 1, percent=20), self.record("F102", 2, percent=14, channel="P1: 4-6"),
                self.record("F101", 3, tube=2, location="Point 6", percent=10),
                self.record("F102", 4, tube=2, location="P6", percent=15),
                self.record("N101", 5, percent=90)]
        originals = [row.copy() for row in rows]
        data = self.build(rows, {"unit": "F1", "outage": "F102"})
        self.assertEqual(len(data["increments"]), 1)
        result = data["increments"][0]
        self.assertEqual((result["matched"], result["total"], result["positions"]), (2, -1, {"P1": -6, "P6": 5}))
        self.assertEqual(result["items"][0]["previous"]["channel"], "M1a4-6")
        self.assertEqual(result["items"][0]["current"]["channel"], "P1: 4-6")
        self.assertEqual(result["items"][0]["previous"]["source"], "原表/F101.rpt")
        self.assertEqual(result["items"][0]["previous"]["id"], 1)
        self.assertEqual(rows, originals)
        self.assertTrue(result["partial"], "49 missing tubes must not become complete fleet coverage")

    def test_missing_round_is_not_bridged_and_first_round_is_not_zero(self):
        data = self.build([self.record("F101", 1), self.record("F103", 2),
                           self.record("N102", 3)])
        for result in data["increments"]:
            self.assertIsNone(result["total"])
            self.assertEqual(result["matched"], 0)
            self.assertIsNone(result["old_outage"])
            self.assertTrue(result["items"][0]["reason"])
        data = self.build([self.record("F101", 1), self.record("F103", 2)],
                          repairs=[dict(outage="F102", thimble_id=3, state="normal")])
        current = data["increments"][-1]
        self.assertEqual(current["old_outage"], "F102")
        self.assertIsNone(current["total"], "Maintenance alone is not a detection baseline")

    def test_ndd_or_new_indication_is_not_a_zero_baseline(self):
        data = self.build([self.record("F101", 1, indication="NDD", percent=None),
                           self.record("F102", 2, percent=20)])
        self.assertIsNone(data["increments"][1]["total"])
        self.assertIn("不按零计算", data["increments"][1]["items"][0]["reason"])
        data = self.build([self.record("F101", 1, indication="NDD", percent=None),
                           self.record("F102", 2, indication="NDD", percent=None)])
        self.assertEqual(data["increments"][1]["items"], [])
        self.assertIsNone(data["increments"][1]["total"])

    def test_invalid_depths_and_unparsed_positions_never_enter_increment(self):
        for value in (None, -1, 101, float("nan")):
            for old_invalid in (True, False):
                with self.subTest(value=value, old_invalid=old_invalid):
                    rows = [self.record("F101", 1, percent=value if old_invalid else 20),
                            self.record("F102", 2, percent=20 if old_invalid else value)]
                    result = self.build(rows)["increments"][1]
                    self.assertIsNone(result["total"])
                    self.assertIn("深度", result["items"][0]["reason"])
        for location in ("", "M1a4-6", "PI+168"):
            result = self.build([self.record("F101", 1, location=location),
                                 self.record("F102", 2, location=location)])["increments"][1]
            self.assertIsNone(result["total"])
            self.assertIn("位置", result["items"][0]["reason"])

    def test_history_reuse_and_multiple_candidates_are_excluded(self):
        rows = [self.record("F101", 1), self.record("F102", 2), self.record("F102", 3)]
        current = self.build(rows)["increments"][1]
        self.assertEqual(current["excluded"], 2)
        self.assertIsNone(current["total"])
        self.assertTrue(all("多条本次" in row["reason"] for row in current["items"]))
        rows = [self.record("F101", 1), self.record("F101", 2), self.record("F102", 3)]
        current = self.build(rows)["increments"][1]
        self.assertIsNone(current["total"])
        self.assertIn("多条候选", current["items"][0]["reason"])
        self.assertEqual(current["unmatched_history"], 2)

    def test_shift_replacement_and_plugging_follow_confirmed_events(self):
        rows = [self.record("F101", 1, location="P1+44", percent=20),
                self.record("F102", 2, percent=30)]
        event = dict(outage="F101", thimble_id=1, state="shifted", offset_mm=42)
        result = self.build(rows, repairs=[event])["increments"][1]
        self.assertEqual(result["total"], 10)
        self.assertEqual(result["items"][0]["shift_mm"], 42)
        for change in (dict(offset_mm=None, offset_confirmed=0), dict(state="replaced"),
                       dict(state="plugged")):
            result = self.build(rows, repairs=[{**event, **change}])["increments"][1]
            self.assertIsNone(result["total"])
            self.assertTrue(result["items"][0]["reason"])
        # A replacement after the current inspection must not invalidate its pair.
        rows[0]["location"] = rows[1]["location"]
        result = self.build(rows, repairs=[{**event, "outage": "F102", "state": "replaced"}])["increments"][1]
        self.assertEqual(result["total"], 10)

    def test_active_tolerance_and_filtered_baseline_are_used(self):
        rows = [self.record("F101", 1), self.record("F102", 2, location="P1+2.5", percent=30),
                self.record("N101", 3), self.record("N102", 4, percent=60)]
        query = {"sites": "F", "unit": "F1", "outage": "F102"}
        self.assertIsNone(self.build(rows, query)["increments"][0]["total"])
        active = {"version": 7, "name": "测试规则", "match_tolerance_mm": 1}
        with patch.object(Service, "active_analysis_rules", return_value=active, create=True):
            result = self.build(rows, query)
        self.assertEqual([row["outage"] for row in result["snapshots"]], ["F102"])
        self.assertEqual(len(result["increments"]), 1)
        self.assertEqual(result["increments"][0]["old_outage"], "F101")
        self.assertEqual(result["increments"][0]["total"], 20)
        self.assertEqual(result["increments"][0]["rules"], active)

    def test_complete_coverage_can_contain_real_zero_increment(self):
        rows = [self.record(outage, ident + tube, tube=tube, indication="WAR" if tube == 1 else "NDD",
                            percent=10 if tube == 1 else None)
                for outage, ident in (("F101", 0), ("F102", 50)) for tube in range(1, 51)]
        current = self.build(rows)["increments"][1]
        self.assertEqual(current["total"], 0)
        self.assertEqual(current["matched"], 1)
        self.assertFalse(current["partial"])
        self.assertEqual(self.build(rows)["increments"][0]["total"], None)


if __name__ == "__main__":
    unittest.main()
