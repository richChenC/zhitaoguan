"""Reference row selection, editing, sorting and audited native plate exports."""
from __future__ import annotations

import hashlib
from pathlib import Path
import json
import re
import tempfile
import unittest
from unittest.mock import patch

import native_test_env
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox, QPlainTextEdit

from qt_shell.native_components import workspace_styles
from qt_shell.native_plate_snapshot import create_plate_snapshot
from qt_shell.native_windows import DataWorkbench
from qt_shell.native_workbench_table import WorkbenchSortPreference
from test_native_workflows import Client


class WorkbenchSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=native_test_env.test_data.name)
        self.addCleanup(self.folder.cleanup)
        state = patch("qt_shell.native_workbench_table.USER_DATA", Path(self.folder.name))
        state.start()
        self.addCleanup(state.stop)

    def tearDown(self):
        for widget in self.app.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def page(self, permissions=None):
        page = DataWorkbench(Client(), {"permissions": permissions or ["data.read", "data.edit", "export.create"]})
        page.setStyleSheet(workspace_styles())
        page.resize(1480, 940)
        page.show()
        rows = [{"id": number + 1, "site_code": "N", "outage": "N101" if number < 4 else "N102",
                 "unit_id": 1, "thimble_id": number + 1, "indication": "WAR",
                 "percent": 10 + number * 10, "location": "P1", "analysis": "before"}
                for number in range(6)]
        page._on_findings({"page": 1, "pages": 1, "total": len(rows), "size": 100,
                           "items": rows, "core_items": rows}, None)
        self.app.processEvents()
        return page

    def click(self, page, row, column=2, modifiers=Qt.KeyboardModifier.NoModifier):
        index = page.model.index(row, column)
        page.table.scrollTo(index)
        QTest.mouseClick(page.table.viewport(), Qt.MouseButton.LeftButton, modifiers,
                         page.table.visualRect(index).center())
        self.app.processEvents()

    def test_actual_row_range_checkbox_keyboard_and_same_scope_selection(self):
        page = self.page()
        self.click(page, 0)
        self.assertEqual(list(page.model.selected), [1])
        self.click(page, 3, modifiers=Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(list(page.model.selected), [1, 2, 3, 4])
        self.click(page, 3, modifiers=Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(list(page.model.selected), [1, 2, 3])
        self.click(page, 4)
        self.assertEqual(list(page.model.selected), [1, 2, 3])
        self.assertIn("不能同时选择", page.status.text())
        page.toggle_page()
        self.assertEqual(list(page.model.selected), [1, 2, 3, 4])
        page.toggle_page()
        self.assertEqual(list(page.model.selected), [1, 2, 3, 4])
        page.clear_selection()
        self.click(page, 0, 0)
        self.assertEqual(list(page.model.selected), [1])
        page.table.setCurrentIndex(page.model.index(0, 0))
        QTest.keyClick(page.table, Qt.Key.Key_Space)
        self.assertFalse(page.model.selected)
        QTest.keyClick(page.table, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(list(page.model.selected), [1, 2, 3, 4])
        self.assertEqual(page.model.index(1, 3).data(Qt.ItemDataRole.BackgroundRole).color().name(), "#e9f5f4")
        page.model.replace([dict(page.model.rows[0], id=7)])
        self.assertEqual(page.table._anchor, -1)
        self.assertEqual(len(page.model.selected), 4)
        self.click(page, 0, 0)
        self.assertIn(7, page.model.selected)

    def test_double_click_restores_checked_state_then_escape_preserves_original(self):
        page = self.page()
        page.field_mode.setCurrentIndex(1)
        column = page.model.fields.index("analysis")
        original_mode = page.parity_tabs.currentIndex()
        self.click(page, 0, column)
        self.assertIn(1, page.model.selected)
        index = page.model.index(0, column)
        QTest.mouseDClick(page.table.viewport(), Qt.MouseButton.LeftButton,
                          pos=page.table.visualRect(index).center())
        self.app.processEvents()
        self.assertNotIn(1, page.model.selected)
        self.assertEqual(page.parity_tabs.currentIndex(), original_mode)
        editor = next(control for control in page.table.findChildren(QPlainTextEdit) if control.isVisible())
        editor.setPlainText("canceled")
        QTest.keyClick(editor, Qt.Key.Key_Escape)
        self.app.processEvents()
        self.assertEqual(page.model.rows[0]["analysis"], "before")
        self.assertFalse(any(path == "/api/findings/edit" for _method, path, _payload, _callback in page.client.requests))

    def start_editor(self, page, field, row=0):
        index = page.model.index(row, page.model.fields.index(field))
        page.table.setCurrentIndex(index)
        page.table.scrollTo(index)
        page.table.setFocus()
        QTest.keyClick(page.table, Qt.Key.Key_F2)
        self.app.processEvents()
        kind = QPlainTextEdit if field in {"analysis", "maintenance_text"} else QLineEdit
        return next(control for control in page.table.findChildren(kind) if control.isVisible())

    def edits(self, page):
        return [item for item in page.client.requests if item[1] == "/api/findings/edit"]

    def test_multiline_enter_control_enter_and_success_deselect_only_saved_row(self):
        page = self.page()
        page.model.set_checked_rows([0, 1], True)
        editor = self.start_editor(page, "analysis")
        self.assertEqual(editor.toPlainText(), "before")
        self.assertEqual(page.table.rowHeight(0), 90)
        self.assertGreaterEqual(editor.height(), editor.fontMetrics().lineSpacing() * 3)
        editor.setPlainText("first")
        editor.moveCursor(editor.textCursor().MoveOperation.End)
        QTest.keyClick(editor, Qt.Key.Key_Return)
        QTest.keyClicks(editor, "second")
        self.assertEqual(editor.toPlainText(), "first\nsecond")
        self.assertFalse(self.edits(page))
        QTest.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        self.app.processEvents()
        self.assertEqual(len(self.edits(page)), 1)
        self.assertEqual(page.table.rowHeight(0), page.table.verticalHeader().defaultSectionSize())
        method, endpoint, payload, callback = self.edits(page)[0]
        self.assertEqual(payload, {"id": 1, "field": "analysis", "value": "first\nsecond",
                                  "expected_value": "before"})
        callback({"ok": True, "value": "first\nsecond"}, None)
        self.assertEqual(list(page.model.selected), [2])
        self.assertFalse(page.model.pending)

    def test_multiline_blur_commits_escape_cancels_and_unchanged_never_writes(self):
        page = self.page()
        editor = self.start_editor(page, "maintenance_text")
        editor.setPlainText("first\nsecond")
        QTest.keyClick(editor, Qt.Key.Key_Escape)
        self.app.processEvents()
        self.assertFalse(self.edits(page))
        editor = self.start_editor(page, "analysis")
        QTest.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        self.app.processEvents()
        self.assertFalse(self.edits(page))
        editor = self.start_editor(page, "analysis")
        editor.setPlainText("blur\nsaved")
        QTest.mouseClick(editor.viewport(), Qt.MouseButton.LeftButton)
        self.assertFalse(self.edits(page))
        QTest.mouseClick(page.records_title, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertEqual(len(self.edits(page)), 1)
        self.assertEqual(self.edits(page)[0][2]["value"], "blur\nsaved")

    def test_location_edits_use_source_value_and_conflicts_preserve_selection(self):
        page = self.page()
        page.model.rows[0].update(location="P1 + 0 mm", location_raw="P1")
        page.model.set_checked_rows([0], True)
        editor = self.start_editor(page, "location")
        self.assertEqual(editor.text(), "P1")
        self.assertEqual(page.table.rowHeight(0), 54)
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertFalse(self.edits(page))
        editor = self.start_editor(page, "location")
        editor.setText("P1+2")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.app.processEvents()
        payload = self.edits(page)[-1][2]
        self.assertEqual(payload["expected_value"], "P1")
        self.assertEqual(payload["value"], "P1+2")
        with patch.object(QMessageBox, "warning"):
            self.edits(page)[-1][3](None, "该字段已被其他操作修改")
        self.assertIn(1, page.model.selected)
        self.assertFalse(page.model.pending)
        self.assertEqual(page.model.rows[0]["location_raw"], "P1")

    def test_editor_last_row_is_visible_restores_height_and_model_reset_releases_it(self):
        page = self.page()
        rows = [dict(page.model.rows[0], id=number + 1) for number in range(50)]
        page.model.replace(rows)
        for width, theme in ((1480, "light"), (980, "dark")):
            page.setStyleSheet(workspace_styles(theme))
            page.resize(width, 940)
            self.app.processEvents()
            editor = self.start_editor(page, "analysis", 49)
            self.assertEqual(editor.height(), 70)
            self.assertGreaterEqual(editor.y(), 0)
            self.assertLessEqual(editor.geometry().bottom(), page.table.viewport().rect().bottom())
            QTest.keyClick(editor, Qt.Key.Key_Escape)
            self.app.processEvents()
            self.assertEqual(page.table.rowHeight(49), page.table.verticalHeader().defaultSectionSize())
        editor = self.start_editor(page, "analysis")
        editor.setPlainText("must not write to replacement row")
        page.model.replace(list(reversed(rows)))
        self.app.processEvents()
        self.assertIsNone(page.table.itemDelegate()._active_editor)
        QTest.mouseClick(page.records_title, Qt.MouseButton.LeftButton)
        self.assertFalse(self.edits(page))

    def test_sort_cycles_through_cancel_and_checkbox_scope_guard_applies_to_model(self):
        page = self.page()
        column = page.model.fields.index("percent")
        for field, order in (("percent", "asc"), ("percent", "desc"), ("", "asc")):
            page.sort_column(column)
            self.assertEqual((page.sort_field, page.sort_order), (field, order))
            self.assertEqual(page.table.horizontalHeader().isSortIndicatorShown(), bool(field))
        page.model.setData(page.model.index(0, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
        self.assertFalse(page.model.setData(page.model.index(5, 0), Qt.CheckState.Checked,
                                           Qt.ItemDataRole.CheckStateRole))

    def test_sort_memory_is_per_account_validated_and_atomic(self):
        fields = DataWorkbench(Client()).model.fields
        first = WorkbenchSortPreference("../first", fields)
        second = WorkbenchSortPreference("second", fields)
        self.assertEqual(first.load(), ("", "asc"))
        first.save("percent", "desc")
        self.assertEqual(first.load(), ("percent", "desc"))
        self.assertEqual(second.load(), ("", "asc"))
        self.assertEqual(first.path.parent, Path(self.folder.name) / "workspace-sorting")
        with patch("qt_shell.native_workbench_table.QSaveFile.open", return_value=False):
            with self.assertRaises(OSError):
                first.save("outage", "asc")
        self.assertEqual(first.load(), ("percent", "desc"))
        first.save("", "asc")
        self.assertFalse(first.path.exists())
        second.path.write_text(json.dumps({"sort": "note", "order": "bad"}), encoding="utf-8")
        self.assertEqual(second.load(), ("analysis", "asc"))
        second.path.write_text('{"sort": "_checked"}', encoding="utf-8")
        self.assertEqual(second.load(), ("", "asc"))
        second.path.write_text('{"sort": []}', encoding="utf-8")
        self.assertEqual(second.load(), ("", "asc"))
        first.save("percent", "desc")
        page = DataWorkbench(Client(), {"username": "../first", "permissions": ["data.read"]})
        self.assertEqual((page.sort_field, page.sort_order), ("percent", "desc"))
        self.assertEqual(page.table.horizontalHeader().sortIndicatorSection(), fields.index("percent"))
        self.assertTrue(page.table.horizontalHeader().isSortIndicatorShown())
        page.reset_query()
        self.assertEqual((page.sort_field, page.sort_order), ("percent", "desc"))
        self.assertEqual(first.load(), ("percent", "desc"))

    def test_filters_clear_selection_but_sort_and_page_size_preserve_it(self):
        page = self.page()
        rows = list(page.model.rows)
        def respond():
            query = next(item for item in reversed(page.client.requests) if item[1].startswith("/api/findings?"))
            query[3]({"page": 1, "pages": 2, "total": 200, "size": 100, "items": rows}, None)
        page.model.set_checked_rows([0, 1], True)
        page.sort_column(page.model.fields.index("percent"))
        respond()
        self.assertEqual(list(page.model.selected), [1, 2])
        page.page_size.setCurrentText("500")
        respond()
        self.assertEqual(list(page.model.selected), [1, 2])
        page.analyst.setText("new analyst")
        page.apply_filters()
        self.assertFalse(page.model.selected)
        respond()
        page.model.set_checked_rows([0], True)
        page._on_findings({"page": 1, "total": 0, "items": []}, None)
        self.assertFalse(page.model.selected)

    def test_snapshot_dimensions_coordinates_severity_and_audit_before_file_write(self):
        page = self.page()
        rows = page.model.rows[:4]
        page.plate.levels = [30, 50]
        page.plate.colors = ["#79b98c", "#e5a83b", "#df4b45"]
        image, stats = create_plate_snapshot(rows, page.plate.channels, page.plate.levels, page.plate.colors)
        self.assertEqual(image.size().toTuple(), (1500, 1390))
        self.assertEqual(stats["max_percent"], 40)
        self.assertEqual(stats["dense_count"], 4)
        self.assertEqual(image.pixelColor(100, 1230).name(), "#eef2f3")
        channel = next(item for item in page.plate.channels if int(item["serialOdd"]) == 1)
        position = re.fullmatch(r"([A-Z])(\d+)", channel["pos"])
        x = 260 + ("RPNMLKJHGFEDCBA".index(position[1]) + .5) * 62
        y = 190 + (int(position[2]) - .5) * 62
        self.assertEqual(image.pixelColor(int(x) + 10, int(y) - 10).name(), "#79b98c")
        path = Path(self.folder.name) / "plate.png"
        page.model.selected = {row["id"]: row for row in rows}
        with patch("qt_shell.native_components.QFileDialog.getSaveFileName", return_value=(str(path), "PNG")):
            page.export_plate()
        method, endpoint, payload, callback = page.client.requests[-1]
        self.assertEqual((method, endpoint), ("POST", "/api/security/image-export"))
        self.assertFalse(path.exists())
        callback({"ok": True}, None)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), payload["sha256"])
        self.assertEqual(QImage(str(path)).size().toTuple(), (1500, 1390))
        original = path.read_bytes()
        with patch("qt_shell.native_components.QFileDialog.getSaveFileName", return_value=(str(path), "PNG")), \
                patch("qt_shell.native_components.QMessageBox.warning"):
            page.export_plate()
            page.client.requests[-1][3](None, "session expired")
        self.assertEqual(path.read_bytes(), original)
        with self.assertRaises(ValueError):
            create_plate_snapshot([], page.plate.channels, [30, 50], page.plate.colors)
        with self.assertRaises(ValueError):
            create_plate_snapshot([rows[0], page.model.rows[5]], page.plate.channels, [30, 50], page.plate.colors)
        readonly = self.page(["data.read"])
        self.assertFalse(readonly.map_panel.export_button.isEnabled())
        readonly.export_plate()
        self.assertIn("没有图片导出权限", readonly.status.text())
