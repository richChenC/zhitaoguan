"""Confirmed Point/P aliases are normalized without guessing other labels."""
import unittest

from src.backend import analysis_reporting as analysis, server


class LocationResolutionTests(unittest.TestCase):
    def test_explicit_p_coordinates_preserve_signed_offsets(self):
        for raw, expected in [
            ("P1", ("P1", 0)), ("P6-2.5mm", ("P6", -2.5)),
            ("Ｐ３＋１２毫米", ("P3", 12)),
            ("P1 − 42 mm", ("P1", -42)), ("P1 + -42 mm", ("P1", -42)),
            ("Point 1", ("P1", 0)), (" point 4 ", ("P4", 0)),
            ("POINT 2 + 42 mm", ("P2", 42)), ("ＰＯＩＮＴ　３＋１２毫米", ("P3", 12)),
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(analysis.location({"location": raw}), expected)
                self.assertEqual(server.split_location(raw), expected)
                self.assertEqual(server.normalize_location(raw), expected)

    def test_unusable_positions_never_become_exact_coordinates(self):
        for raw in ["", None, "/", "P0", "P7", "P10", "unknown P1",
                    "Point 10", "Point I", "Point 7",
                    "PI+168", "M1a4-6", "P1+nan", "P1+inf", "P1+" + "9" * 400]:
            with self.subTest(raw=raw):
                self.assertIsNone(analysis.location({"location": raw}))
                self.assertIsNone(server.split_location(raw)[1])
        self.assertIsNone(analysis.location({"location": "P1", "location_raw": ""}))
        self.assertEqual(analysis.location({"location": "P5", "location_raw": "Point 4"}), ("P4", 0))

    def test_display_classification_retains_original_evidence(self):
        for raw, channel, bucket, status in [
            ("Point 1", "M1a4-6", "P1", "parsed"),
            ("Point 4", "M1a4-6", "P4", "parsed"),
            ("PI+168", "P1: 4-6", "未解析", "source_label"),
            ("pi+168mm", "", "未解析", "source_label"),
            ("M1a4-6", "P5", "未解析", "source_label"),
            ("", "P1: 4-6", "未解析", "missing"),
            ("", "P5", "未解析", "missing"),
            ("unknown", "P5", "未解析", "source_label"),
            ("M1a4-6", "P10", "未解析", "source_label"),
        ]:
            row = dict(location=raw, channel=channel, datapoint=21359, percent=52, indication="WAR")
            before = row.copy()
            with self.subTest(raw=raw, channel=channel):
                result = analysis.position_resolution(row)
                self.assertEqual(result["position_bucket"], bucket)
                self.assertEqual(result["position_status"], status)
                self.assertTrue(result["position_note"])
                self.assertEqual(row, before)
                if status != "parsed":
                    self.assertIsNone(analysis.location(row))
                else:
                    self.assertEqual(analysis.location(row), (bucket, 0))
                self.assertNotIn("疑似", result["position_note"])
                self.assertNotIn("暂按", result["position_note"])

    def test_instrument_labels_do_not_participate_in_physical_position_matching(self):
        def row(outage, raw, channel=""):
            return dict(outage=outage, unit_id=1, thimble_id=1, indication="WAR",
                        percent=20, location=raw, channel=channel, datapoint=21359)
        baseline = row("F101", "P1")
        current = row("F102", "P1")
        self.assertEqual(analysis.compare_rows("F101", "F102", 1, [baseline], [current], [])["summary"]["R"], 1)
        self.assertEqual(analysis.compare_rows("F101", "F102", 1, [baseline], [row("F102", "Point 1")], [])["summary"]["R"], 1)
        for raw, channel in [("PI+168", ""),
                             ("M1a4-6", "P5"), ("", "P1: 4-6")]:
            with self.subTest(raw=raw):
                uncertain = row("F102", raw, channel)
                result = analysis.compare_rows("F101", "F102", 1, [baseline], [uncertain], [])
                self.assertEqual(result["summary"]["待确认"], 1)
                # Uncertain historical evidence also cannot establish an NI result.
                historical = row("F101", raw, channel)
                result = analysis.compare_rows("F101", "F102", 1, [historical], [current], [])
                self.assertEqual(result["summary"]["待确认"], 1)
