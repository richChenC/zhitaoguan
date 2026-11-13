"""Paging boundaries, stale responses, native editing and table presentation."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import native_test_env
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit

from qt_shell.native_components import workspace_styles
from qt_shell.native_windows import DataWorkbench
from qt_shell.native_workbench_table import FieldModeControl
from test_native_workflows import Client


class WorkbenchTableTests(unittest.TestCase):
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

    def page(self, permissions=None):
        page = DataWorkbench(Client(), {"permissions": permissions or ["data.read", "data.edit"]})
        page.setStyleSheet(workspace_styles())
        page.resize(1480, 940)
        page.show()
        self.respond(page)
        self.app.processEvents()
        return page

    def queries(self, page):
        return [row for row in page.client.requests if row[1].startswith("/api/findings?")]

    def respond(self, page, number=1, total=4517, size=100, core=True):
        data = {"page": number, "size": size, "pages": max(1, (total + size - 1) // size), "total": total,
                "items": [{"id": number, "outage": "N101", "unit_id": 1, "thimble_id": 1,
                           "position": "B5", "indication": "WAR", "percent": 10}] if total else []}
        if core:
            data["core_items"] = [{"unit_id": 1, "thimble_id": 1, "percent": 10}]
        self.queries(page)[-1][3](data, None)

    def test_jump_boundary_busy_stale_and_failed_page_keep_accepted_data(self):
        page = self.page()
        self.assertEqual(page.status.text(), "第 1\u2013100 条，共 4517 条")
        self.assertEqual(page.page_info.text(), "1 / 46")
        count = len(self.queries(page))
        self.assertFalse(page.go_to_page(0))
        self.assertFalse(page.go_to_page(1))
        self.assertEqual(len(self.queries(page)), count)
        self.assertTrue(page.go_to_page(999))
        self.assertIn("page=46", self.queries(page)[-1][1])
        self.assertIn("core=0", self.queries(page)[-1][1])
        self.assertFalse(page.page_jump.isEnabled())
        self.assertFalse(page.page_size.isEnabled())
        self.assertFalse(page.go_to_page(2))
        self.respond(page, 46, core=False)
        self.assertEqual(page.status.text(), "第 4501\u20134517 条，共 4517 条")
        self.assertEqual(page.model.page_offset, 4500)
        self.assertTrue(page.core_rows)
        self.assertFalse(page.next.isEnabled())
        self.assertTrue(page.go_to_page(45))
        self.queries(page)[-1][3](None, "network failure")
        self.assertEqual(page.page, 46)
        self.assertEqual(page.model.rows[0]["id"], 46)
        self.assertEqual(page.page_info.text(), "46 / 46")
        self.assertTrue(page.core_rows)
        self.assertIn("network failure", page.status.text())
        # A full refresh invalidates any earlier page response.
        page.go_to_page(45)
        stale = self.queries(page)[-1][3]
        page.apply_filters()
        stale({"page": 45, "items": [], "total": 0}, None)
        self.assertTrue(page._filter_busy)
        self.respond(page, total=0)
        self.assertEqual(page.model.rowCount(), 0)
        self.assertEqual(page.status.text(), "共 0 条")
        self.assertFalse(page.page_jump.isEnabled())
        self.assertEqual(page.page_info.text(), "1 / 1")

    def test_real_keyboard_jump_escape_blur_and_page_size(self):
        page = self.page()
        page.scroll.ensureWidgetVisible(page.pager)
        page.page_jump.setText("46")
        QTest.keyClick(page.page_jump, Qt.Key.Key_Return)
        self.assertEqual(page.page_jump.text(), "")
        self.respond(page, 46)
        count = len(self.queries(page))
        page.page_jump.setText("999")
        QTest.keyClick(page.page_jump, Qt.Key.Key_Return)
        self.assertEqual(len(self.queries(page)), count)
        self.assertEqual(page.page_jump.text(), "999")
        QTest.keyClick(page.page_jump, Qt.Key.Key_Escape)
        self.assertFalse(page.page_jump.text())
        page.page_jump.setFocus()
        page.page_jump.setText("3")
        page.table.setFocus()
        self.app.processEvents()
        self.assertFalse(page.page_jump.text())
        page.page_jump.setText("0")
        QTest.keyClick(page.page_jump, Qt.Key.Key_Return)
        self.assertFalse(page.page_jump.text())
        self.assertEqual(len(self.queries(page)), count)
        page.page_size.setCurrentIndex(page.page_size.findData(20))
        self.assertIn("size=20", self.queries(page)[-1][1])
        self.assertIn("page=1", self.queries(page)[-1][1])
        self.assertNotIn("core=0", self.queries(page)[-1][1])
        self.respond(page, size=20)
        self.assertEqual(page.status.text(), "第 1\u201320 条，共 4517 条")
        self.assertEqual(page.page_info.text(), "1 / 226")
        page.table.setFocus()
        page.activateWindow()
        QTest.qWait(30)
        QTest.keyClick(page.table, Qt.Key.Key_Right, Qt.KeyboardModifier.AltModifier)
        self.assertEqual(page.page, 2)
        self.respond(page, 2, size=20, core=False)
        QTest.keyClick(page.table, Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
        self.assertEqual(page.page, 1)

    def test_pending_filter_prevents_paging_old_scope_and_core_is_reloaded(self):
        page = self.page()
        QTest.keyClicks(page.analyst, "new-scope")
        count = len(self.queries(page))
        self.assertFalse(page.go_to_page(2))
        self.assertEqual(len(self.queries(page)), count + 1)
        self.assertIn("page=1", self.queries(page)[-1][1])
        self.assertIn("analyst=new-scope", self.queries(page)[-1][1])
        self.assertNotIn("core=0", self.queries(page)[-1][1])
        self.assertFalse(page._filter_timer.isActive())
        self.respond(page)
        page.analyst.setText("programmatic-scope")
        page.go_to_page(2)
        self.assertNotIn("core=0", self.queries(page)[-1][1])

    def test_field_persistence_plain_table_and_native_f2_editor(self):
        with tempfile.TemporaryDirectory(dir=native_test_env.test_data.name) as folder:
            state = Path(folder) / "fields.json"
            control = FieldModeControl(state_path=state)
            self.assertEqual(control.tabs.currentIndex(), 0)
            control.tabs.setCurrentIndex(1)
            self.assertEqual(json.loads(state.read_text()), {"columns": "all"})
            restored = FieldModeControl(state_path=state)
            self.assertEqual(restored.tabs.currentIndex(), 1)
            with patch("qt_shell.native_workbench_table.QSaveFile") as output:
                output.return_value.open.return_value = False
                output.return_value.errorString.return_value = "read only"
                restored.tabs.setCurrentIndex(0)
            self.assertIn("read only", restored.toolTip())
            self.assertEqual(json.loads(state.read_text()), {"columns": "all"})
        page = self.page()
        page.field_mode.setCurrentIndex(0)
        self.assertFalse(page.table.isColumnHidden(page.model.fields.index("maintenance_text")))
        self.assertTrue(page.table.isColumnHidden(page.model.fields.index("degrees")))
        page.field_mode.setCurrentIndex(1)
        self.assertFalse(any(page.table.isColumnHidden(index) for index in range(page.model.columnCount())))
        index = page.model.index(0, page.model.fields.index("analysis"))
        page.table.setCurrentIndex(index)
        page.table.scrollTo(index)
        page.table.setFocus()
        QTest.keyClick(page.table, Qt.Key.Key_F2)
        self.app.processEvents()
        editors = [editor for editor in page.table.findChildren(QLineEdit) if editor.isVisible()]
        self.assertEqual(len(editors), 1)
        editors[0].setText("reviewed")
        QTest.keyClick(editors[0], Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertEqual(page.client.requests[-1][1], "/api/findings/edit")
        readonly = self.page(["data.read"])
        self.assertFalse(readonly.edit_action.isEnabled())
        self.assertFalse(readonly.model.flags(readonly.model.index(0, index.column())) & Qt.ItemFlag.ItemIsEditable)

    def test_reference_dimensions_and_no_outer_horizontal_overflow(self):
        page = self.page()
        for width, theme in ((1480, "light"), (1120, "dark"), (1024, "light"), (980, "dark")):
            page.resize(width, 940)
            page.setStyleSheet(workspace_styles(theme))
            QTest.qWait(40)
            self.assertEqual(page.field_modes.size().toTuple(), (134, 34))
            self.assertEqual(page.field_mode.tabRect(0).size().toTuple(), (64, 28))
            self.assertEqual(page.table.horizontalHeader().height(), 51)
            self.assertEqual(page.prev.size().toTuple(), (30, 30))
            self.assertEqual(page.page_size.size().toTuple(), (66, 34))
            self.assertEqual(page.page_jump.size().toTuple(), (54, 30))
            self.assertEqual(page.status.font().hintingPreference(), QFont.HintingPreference.PreferNoHinting)
            self.assertTrue(page.status.font().isFeatureSet(QFont.Tag.fromString("tnum")))
            self.assertEqual(page.scroll.horizontalScrollBar().maximum(), 0)
            self.assertLessEqual(page.pager.navigation.geometry().right(), page.pager.width() - 12)
            self.assertEqual([page.page_size.itemData(i) for i in range(page.page_size.count())],
                             [20, 50, 100, 200, 500])


if __name__ == "__main__":
    unittest.main()
