"""Plate coordinates, severity isolation and native selection detail behavior."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import native_test_env
from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from qt_shell.native_components import ReferencePlateMap, workspace_styles
from qt_shell.native_windows import DataWorkbench
from qt_shell.native_workbench_plate import WorkbenchPlatePanel
from test_native_workflows import Client


class WorkbenchPlateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=native_test_env.test_data.name)
        self.addCleanup(folder.cleanup)
        state = patch("qt_shell.native_workbench_table.USER_DATA", Path(folder.name))
        state.start()
        self.addCleanup(state.stop)

    def tearDown(self):
        for widget in self.app.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def test_selection_stats_densest_zone_and_virtualized_plain_text_details(self):
        panel = WorkbenchPlatePanel(lambda: None)
        rows = [
            {"id": 1, "outage": "N101", "unit_id": 1, "thimble_id": 1, "position": "L11",
             "indication": "WAR", "percent": 35, "location": "P1 + 2 mm", "analyst": "<b>Alpha</b>"},
            {"id": 2, "outage": "N101", "unit_id": 1, "thimble_id": 1, "position": "L11",
             "indication": "WAR", "percent": 50, "location": "P1"},
            {"id": 3, "outage": "N101", "unit_id": 1, "thimble_id": 2, "position": "G14",
             "indication": "NDD", "percent": 99, "location": "P2"},
        ]
        panel.resize(531, 1000)
        panel.show()
        panel.show_records(rows)
        self.app.processEvents()
        self.assertEqual([label.text() for _host, label in panel.stats.fields],
                         ["3", "1", "50%", "P1 · 2条"])
        self.assertEqual(panel.details.model.rowCount(), 3)
        self.assertIn("<b>Alpha</b>", panel.details.model.index(0).data())
        self.assertEqual(panel.details.caption.textFormat(), Qt.TextFormat.PlainText)
        panel.show_records(rows * 1000)
        self.assertEqual(panel.details.height(), 260)
        self.assertEqual(panel.details.model.rowCount(), 3000)
        self.assertLess(len(panel.details.records.findChildren(QWidget)), 20)
        panel.show_records([rows[0], {**rows[1], "unit_id": 2}])
        self.assertIn("跨机组", panel.stats.message.text())
        panel.show_records([])
        self.assertEqual(panel.stats.height(), 42)
        self.assertEqual(panel.details.height(), 74)
        self.assertEqual(panel.details.model.rowCount(), 0)

    def test_grid_geometry_palette_and_half_clicks_are_preserved(self):
        plate = ReferencePlateMap()
        plate.resize(529, 491)
        plate.show()
        plate.grab()
        self.assertEqual(plate.grid_rect().getRect(), (68, 52, 393, 393))
        light = plate.grab().toImage()
        self.assertEqual(light.pixelColor(5, 5).name(), "#ffffff")
        plate.set_theme("dark")
        dark = plate.grab().toImage()
        self.assertEqual(plate.grid_rect().getRect(), (69, 53, 391, 391))
        self.assertEqual(dark.pixelColor(10, 10).name(), "#182123")
        self.assertEqual(dark.pixelColor(69 + 6 * 26 + 5, 58).name(), "#233032")
        self.assertEqual(len(plate.hit_regions), 50)
        for (odd, even), rect in plate.hit_regions.items():
            self.assertAlmostEqual(rect.width(), 391 * .062)
            self.assertEqual(plate._hit(QPointF(rect.center().x() - 1, rect.center().y()))[:2], (odd, 1))
            self.assertEqual(plate._hit(QPointF(rect.center().x() + 1, rect.center().y()))[:2], (even, 0))
        plate.set_records([{"unit_id": 1, "thimble_id": 1, "indication": "NDD", "percent": 90}])
        self.assertFalse(plate.parity_rows[1])
        self.assertEqual(plate._record_color(1, 1).name(), "#ffffff")

    def test_narrow_layout_reference_order_and_three_native_tabs(self):
        page = DataWorkbench(Client(), {"permissions": ["data.read"]})
        page.setStyleSheet(workspace_styles())
        page.resize(1024, 940)
        page.show()
        self.app.processEvents()
        self.assertIs(page.splitter.widget(0), page.map_panel)
        self.assertTrue(page.map_panel.side_by_side)
        self.assertGreater(page.map_panel.stats.x(), page.plate.x() + page.plate.width())
        for index, parity in enumerate(("both", "odd", "even")):
            QTest.mouseClick(page.parity_tabs, Qt.MouseButton.LeftButton,
                             pos=page.parity_tabs.tabRect(index).center())
            self.assertEqual(page.plate.parity, parity)
            self.assertEqual(page.parity_tabs.tabRect(index).size().toTuple(), (74, 34))
        page.resize(1120, 940)
        self.app.processEvents()
        self.assertIs(page.splitter.widget(0), page.table_host)
        self.assertTrue(page.map_panel.side_by_side)
        page.resize(1480, 940)
        self.app.processEvents()
        self.assertFalse(page.map_panel.side_by_side)
        self.assertGreater(page.map_panel.minimumHeight(), 700)
        self.assertGreater(page.scroll.verticalScrollBar().maximum(), 0)

    def test_tube_details_use_actual_scope_reject_stale_and_emit_native_focus(self):
        client = Client()
        page = DataWorkbench(client, {"permissions": ["data.read"]})
        row = {"id": 1, "site_code": "N", "outage": "N101", "unit_id": 6,
               "thimble_id": 2, "position": "C8", "indication": "WAR", "percent": 35}
        page.model.selected = {1: row}
        page._selection_changed()
        self.assertEqual(page.map_unit.value(), 6)
        self.assertEqual(page.plate.parity, "even")
        self.assertTrue(page.plate.selection_ready)
        page._tube_clicked(2)
        method, path, _payload, stale = client.requests[-1]
        self.assertEqual(method, "GET")
        for field in ("site=N", "outage=N101", "unit=6", "thimble=2", "size=200"):
            self.assertIn(field, path)
        page._tube_clicked(3)
        callback = client.requests[-1][3]
        stale({"items": [row]}, None)
        self.assertNotIn("2号指套管", page.plate_detail.text())
        callback({"items": [{**row, "thimble_id": 3}]}, None)
        self.assertIn("6号机 · 3号指套管", page.plate_detail.text())
        focused = []
        page.tubeFocusRequested.connect(focused.append)
        page.plate_detail.focus_button.click()
        self.assertEqual(focused[0], {"site": "N", "unit": "6", "outage": "N101", "thimble": "3"})
        page.clear_selection()
        self.assertFalse(page.plate.selection_ready)
        self.assertFalse(page.plate.allow_parity_switch)

