"""Original records and position history remain distinct from lifecycle values."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import native_test_env  # noqa: F401
from PySide6.QtCharts import QLineSeries
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QPushButton, QTableWidget

from qt_shell.native_charts import VisualizationWorkspace
from qt_shell.native_tube_history import TubeHistoryView, position_series, report_depth
from qt_shell.native_windows import NativeMainWindow
from test_native_chart_windows import WindowClient


class TubeHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def tearDown(self):
        for widget in self.app.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    @staticmethod
    def tube():
        return {"tube": 2, "position": "G14", "series": [
            {"outage": "N101", "order": 1, "records": 2, "generation": 1, "conclusion": "WAR",
             "report_max_depth": 10, "current_events": ["shifted"], "maintenance_unsigned_offset_mm": 12,
             "needs_review": True, "warnings": ["方向未确认"], "maintenance_note": "<b>原始维护</b>\n第二行",
             "findings": [{"id": 4, "indication": "WAR", "location": "P3+12", "percent": 0,
                           "channel": "P3", "source": "D:\\test\\a.rpt"},
                          {"id": 5, "indication": "WAR", "location": "P3-4", "percent": 10,
                           "channel": "P3", "source": "D:\\test\\b.rpt"}]},
            {"outage": "N103", "order": 3, "records": 1, "generation": 2, "replaced": True,
             "report_max_depth": 40, "max_depth": 0, "current_events": ["replaced"],
             "findings": [{"indication": "WAR", "location": "P3", "percent": 40}]},
            {"outage": "N104", "order": 4, "records": 1, "generation": 2, "ndd": True,
             "conclusion": "NDD", "findings": [{"indication": "NDD", "percent": None}]},
        ]}

    @staticmethod
    def outages():
        return [{"outage": f"N10{index}", "order": index} for index in range(1, 5)]

    def test_lazy_rounds_raw_zero_plain_text_missing_round_and_generation(self):
        widget = TubeHistoryView(WindowClient(), {"data.read"})
        widget.set_data("N1", self.tube(), self.outages(), True)
        self.assertEqual(len(widget.rounds), 4)
        self.assertTrue(all(row.body is None for row in widget.rounds.values()))
        self.assertFalse(widget.export.isEnabled())
        row = widget.rounds["N101"]
        self.assertIn("方向待确认", row.header.accessibleName())
        row.header.setChecked(True)
        table = row.body.findChild(QTableWidget)
        self.assertEqual(table.item(0, 2).text(), "0%")
        self.assertEqual(table.item(0, 0).text(), "P3+12")
        self.assertEqual(table.item(0, 4).toolTip(), "D:\\test\\a.rpt")
        note = next(label for label in row.body.findChildren(QLabel) if "<b>原始维护</b>" in label.text())
        self.assertEqual(note.textFormat(), Qt.TextFormat.PlainText)
        self.assertIn("第 2 代", widget.rounds["N103"].header.accessibleName())
        self.assertIn("无有效深度", widget.rounds["N102"].header.accessibleName())
        widget.expand_all(True)
        self.assertTrue(all(row.body is not None for row in widget.rounds.values()))
        widget.expand_all(False)
        self.assertFalse(any(row.header.isChecked() for row in widget.rounds.values()))

    def test_position_curves_keep_raw_locations_missing_depth_ndd_policy_and_breaks(self):
        points = self.tube()["series"]
        groups, breaks, evidence = position_series(points, True)
        self.assertEqual(groups["P3"], [(1, 10), (3, 40), (4, 0)])
        self.assertEqual(breaks["P3"], {3})
        self.assertEqual([row["location"] for row in evidence[("P3", 1)][1]], ["P3+12", "P3-4"])
        self.assertIsNone(position_series(points, False)[0]["P3"][-1][1])
        self.assertEqual(report_depth(points[1], True), 40)
        self.assertIsNone(report_depth({"report_max_depth": float("nan")}, True))
        widget = TubeHistoryView()
        widget.set_data("N1", self.tube(), self.outages(), True)
        chart = widget.position_chart.view.chart()
        self.assertEqual(len(chart.axes(Qt.Orientation.Horizontal)), 1)
        self.assertEqual(len(chart.axes(Qt.Orientation.Vertical)), 1)
        for series in chart.series():
            self.assertEqual(len(series.attachedAxes()), 2)
        lines = [series for series in chart.series() if isinstance(series, QLineSeries)]
        self.assertEqual(len(lines), 1)
        self.assertEqual([point.x() for point in lines[0].points()], [3, 4])
        toggle = widget.toggles.findChild(QCheckBox)
        toggle.setChecked(False)
        self.assertFalse(any(series.isVisible() for series in chart.series()))

    def test_live_refresh_preserves_same_tube_disclosures_and_position_choices(self):
        widget = TubeHistoryView()
        tube = self.tube()
        widget.set_data("N1", tube, self.outages(), True)
        widget.rounds["N101"].header.setChecked(True)
        widget.toggle_layout.itemAt(0).widget().setChecked(False)
        updated = deepcopy(tube)
        updated["series"][0]["maintenance_note"] = "NEW SOURCE"
        widget.set_data("N1", updated, self.outages(), True)
        self.assertTrue(widget.rounds["N101"].header.isChecked())
        self.assertFalse(widget.toggle_layout.itemAt(0).widget().isChecked())
        self.assertTrue(any("NEW SOURCE" in label.text() for label in
                            widget.rounds["N101"].body.findChildren(QLabel)))
        widget.set_data("N2", updated, self.outages(), True)
        self.assertFalse(any(row.header.isChecked() for row in widget.rounds.values()))
        self.assertTrue(widget.toggle_layout.itemAt(0).widget().isChecked())

    def test_history_unit_and_tube_are_independent_of_general_scope_and_old_responses(self):
        client = WindowClient()
        workspace = VisualizationWorkspace(client=client)
        workspace.set_history_units([
            {"site": "F", "unit_id": 1, "outage": "F101"},
            {"site": "N", "unit_id": 1, "outage": "N101"}])
        pending_f = next(row[3] for row in client.requests if "site=F" in row[1])
        workspace.history_site.setCurrentIndex(workspace.history_site.findData("N"))
        pending_n = next(row[3] for row in client.requests if "site=N" in row[1])
        pending_n({"tubes": [self.tube()], "outages": self.outages()}, None)
        workspace.tube_number.setValue(2)
        self.assertEqual(workspace.tube_history.unit, "N1")
        pending_f(None, "old failure")
        self.assertEqual(workspace.tube_history.unit, "N1")
        workspace.set_data({"snapshots": [{"unit": "F1", "outage": "F101", "order": 1, "tubes": []}]})
        self.assertEqual(workspace.longitudinal_unit(), "N1")
        self.assertEqual(workspace.tube_number.value(), 2)
        self.assertEqual(workspace._selected_tube, 1)
        workspace.set_history_units([])
        workspace.set_data({"snapshots": []})
        self.assertTrue(workspace.tube_history.isHidden())
        self.assertTrue(workspace.tube_history.intro.isHidden())
        self.assertEqual(workspace.longitudinal_table.rowCount(), 0)

    def test_original_record_jump_clears_workbench_filters_and_reaches_selected_tube(self):
        window = NativeMainWindow(WindowClient(), {"username": "viewer", "permissions": ["data.read"]})
        window.workbench.scope_bar._loaded({"combinations": [{"site": "N", "unit_id": 1, "outage": "N101"}]}, None)
        window.workbench.analyst.setText("unrelated")
        window.workbench.column_filters["percent"] = ">50"
        history = window.stack.widget(3).visualization.tube_history
        history.set_data("N1", self.tube(), self.outages(), True)
        row = history.rounds["N101"]
        row.header.setChecked(True)
        control = next(button for button in row.body.findChildren(QPushButton) if "工作台" in button.text())
        control.click()
        self.assertEqual(window.nav.currentIndex(), 0)
        self.assertEqual(window.workbench.channel.text(), "2")
        self.assertEqual(window.workbench.analyst.text(), "")
        self.assertEqual(window.workbench.column_filters, {})
        self.assertEqual(window.context.scope["outage"], "N101")

    def test_csv_exports_authoritative_scope_and_saves_only_after_success(self):
        client = WindowClient()
        widget = TubeHistoryView(client, {"data.read", "export.create"})
        widget.set_data("N1", self.tube(), self.outages(), False)
        with TemporaryDirectory(prefix="native-csv-", dir=native_test_env.artifact_root) as directory:
            target, source = Path(directory) / "saved.csv", Path(directory) / "server.csv"
            source.write_bytes(b"\xef\xbb\xbforiginal")
            with patch("qt_shell.native_tube_history.QFileDialog.getSaveFileName", return_value=(str(target), "")):
                widget.export.click()
            _, route, payload, callback = client.requests[-1]
            self.assertEqual(route, "/api/analysis/tube-history/export")
            self.assertEqual(payload, {"site": "N", "unit": 1, "tube": 2, "ndd_zero": False})
            self.assertFalse(target.exists())
            callback({"file_path": str(source), "rows": 3}, None)
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertIn("3 行", widget.status.text())


if __name__ == "__main__":
    unittest.main()
