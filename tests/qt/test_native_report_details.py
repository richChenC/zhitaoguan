"""Report draft history, authoritative preview and native settings navigation."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import native_test_env  # noqa: F401
from PySide6.QtCore import QCoreApplication, QEvent, QSignalBlocker, Qt
from PySide6.QtTest import QTest
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit, QMessageBox

from qt_shell.native_windows import NativeMainWindow, NativeReportsPage
from test_native_workflows import Client


class ReportDetailTests(unittest.TestCase):
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

    def report(self):
        client = Client()
        page = NativeReportsPage(client)
        page.site.setText("N")
        page.unit.setValue(1)
        page.outage.setText("N101")
        page._on_preview({
            "snapshot_id": "original",
            "editable_cells": [
                {"key": "zero", "value": 0, "source_value": 0, "type": "number", "editable": True},
                {"key": "note", "value": "原文", "type": "text", "editable": True},
            ],
            "html": '<table><tr><td data-edit-key="zero"><b>0</b></td>'
                    '<td data-edit-key="note"><p>原文</p></td></tr></table>',
        }, None)
        return page, client

    def test_draft_history_zero_restore_and_rich_markup_survive_preview(self):
        page, client = self.report()
        page._inline_report_edit("zero", "0.0")
        self.assertEqual(page.draft_edits, [])
        page._inline_report_edit("zero", ".5")
        page._inline_report_edit("note", "第一行\n第二行")
        self.assertEqual(page.draft_edits, [{"key": "note", "value": "第一行\n第二行"},
                                          {"key": "zero", "value": "0.5"}])
        self.assertIsNone(page.snapshot_id)
        self.assertFalse(page.export.isEnabled())
        page.undo_report_draft()
        self.assertEqual(page.draft_edits, [{"key": "zero", "value": "0.5"}])
        page._on_preview({
            "snapshot_id": "changed",
            "editable_cells": [
                {"key": "zero", "value": "0.5", "source_value": 0, "type": "number", "editable": True},
                {"key": "note", "value": "原文", "type": "text", "editable": True}],
            "html": '<table><tr><td data-edit-key="zero">0.5</td><td data-edit-key="note">原文</td></tr></table>',
        }, None)
        page.restore_report_cell("zero")
        item = page.preview_text.tables[0].item(0, 0)
        self.assertEqual(item.text(), "0")
        self.assertIn("<b>0</b>", item.data(Qt.ItemDataRole.UserRole + 1))
        self.assertEqual(page.draft_edits, [])
        page.undo_report_draft()
        self.assertEqual(item.text(), "0.5")
        page.clear_report_draft()
        self.assertEqual(item.text(), "0")
        page.undo_report_draft()
        self.assertEqual(item.text(), "0.5")
        self.assertTrue(page.preview_text.locate_cell("zero"))
        self.assertFalse(page.preview_text.locate_cell("missing"))

    def test_invalid_number_reverts_without_history_or_snapshot_invalidation(self):
        page, _client = self.report()
        item = page.preview_text.tables[0].item(0, 0)
        for invalid in ("NaN", "1e5", "1,5", "abc", "9" * 2001):
            item.setText(invalid)
            self.assertEqual(item.text(), "0")
            self.assertEqual(page.draft_edits, [])
            self.assertEqual(page._draft_history, [])
            self.assertEqual(page.snapshot_id, "original")
        page._inline_report_edit("zero", "/")
        self.assertEqual(page.draft_edits, [{"key": "zero", "value": "/"}])

    def test_report_statistics_keep_record_and_exclusive_tube_counts_separate(self):
        page, _client = self.report()
        page.show()
        page._on_preview({
            "snapshot_id": "counts", "kind": "comparison", "html": "<p>report</p>",
            "detection_counts": [
                {"outage": "N102", "tubes": 3, "records": 5, "war_tubes": 1, "war_records": 2,
                 "ndd_tubes": 1, "ndd_records": 2, "other_tubes": 1, "other_records": 1,
                 "tube_ids": {"war": [1], "ndd": [2], "other": [3]}, "mixed_ndd_tubes": [1]},
                {"outage": "N101", "tubes": 2, "records": 2, "tube_ids": {}, "mixed_ndd_tubes": []}],
            "rules": {"version": 3, "name": "test", "match_tolerance_mm": .5},
        }, None)
        self.assertEqual(page.count_table.rowCount(), 2)
        self.assertEqual(page.count_table.item(0, 1).text(), "3 根 / 5 条")
        self.assertEqual(page.count_table.item(0, 2).text(), "1 根 / 2 条")
        self.assertEqual(page.count_table.item(0, 2).toolTip(), "1")
        self.assertIn("1号管同时含 NDD", page.count_note.text())
        self.assertIn("容差 ±0.5 mm", page.count_note.text())
        self.assertFalse(page.count_panel.isVisible())
        QTest.mouseClick(page.count_toggle, Qt.MouseButton.LeftButton)
        self.assertTrue(page.count_panel.isVisible())
        page._on_preview({"snapshot_id": "empty", "html": "<p>empty</p>"}, None)
        self.assertEqual(page.count_table.rowCount(), 0)
        self.assertFalse(page.count_toggle.isEnabled())
        self.assertFalse(page.count_panel.isVisible())

    def test_draft_sidebar_background_follows_dark_theme(self):
        from qt_shell.native_components import workspace_styles
        page, _client = self.report()
        page.resize(1200, 800)
        page.setStyleSheet(workspace_styles("dark"))
        page._inline_report_edit("note", "暗色主题文字")
        page.show()
        page.edit_report()
        self.app.processEvents()
        contents = page.draft_entries.widget()
        self.assertEqual(contents.objectName(), "reportDraftContents")
        image = contents.grab().toImage()
        background = image.pixelColor(image.width() - 3, image.height() - 3)
        self.assertLess(background.lightness(), 70)
        page.setStyleSheet(workspace_styles("light"))
        self.app.processEvents()
        image = contents.grab().toImage()
        self.assertGreater(image.pixelColor(image.width() - 3, image.height() - 3).lightness(), 230)

    def test_review_warnings_group_dedupe_and_expand_with_full_evidence(self):
        from qt_shell.native_report_view import ReportWarnings
        panel = ReportWarnings()
        panel.resize(1000, 300)
        warning = {
            "thimble_id": 10, "code": "unmatched_history", "old_id": 8, "reason": "超出容差；请核对",
            "historical": {"outage": "N101", "location": "P3", "volts": 0, "percent": 0, "datapoint": "<b>来源</b>"},
            "current": {"state": "defects", "defects": 2,
                        "nearest": {"location": "P3+42", "distance_mm": 42}},
            "tolerance_mm": .5,
        }
        warnings = [warning, dict(warning), {"thimble_id": 2, "code": "missing_tube", "reason": "本次缺少"},
                    {"reason": "范围不足"}]
        panel.set_warnings(warnings, scope="N102")
        panel.show()
        self.app.processEvents()
        self.assertEqual(list(panel.groups), ["范围", "2号管", "10号管"])
        self.assertIn("3 个管号   4 条提示", panel.toggle.text())
        self.assertFalse(panel.scroll.isVisible())
        self.assertFalse(panel.groups["10号管"]["built"])
        QTest.mouseClick(panel.toggle, Qt.MouseButton.LeftButton)
        group = panel.groups["10号管"]
        QTest.mouseClick(group["toggle"], Qt.MouseButton.LeftButton)
        self.app.processEvents()
        evidence = "\n".join(label.text() for label in group["body"].findChildren(QLabel))
        self.assertIn("幅值 0 · 深度 0%", evidence)
        self.assertIn("数据点 <b>来源</b>", evidence)
        self.assertIn("最近显示 P3+42 · 相距 42 mm · 当前容差 ±0.5 mm", evidence)
        self.assertIn("不得自动判定为消失", evidence)
        self.assertTrue(all(label.textFormat() == Qt.TextFormat.PlainText
                            for label in group["body"].findChildren(QLabel)))
        panel.set_warnings(warnings, scope="N102")
        self.assertTrue(panel.toggle.isChecked())
        self.assertTrue(panel.groups["10号管"]["toggle"].isChecked())
        panel.resize(600, 300)
        self.app.processEvents()
        self.assertEqual(panel._columns, 1)
        panel.set_warnings(warnings, scope="N103")
        self.assertFalse(panel.toggle.isChecked())
        self.assertFalse(panel.groups["10号管"]["toggle"].isChecked())
        panel.set_warnings([], scope="N103")
        self.assertTrue(panel.isHidden())
        self.assertEqual(panel.groups, {})

    def test_review_warning_context_and_missing_ndd_states(self):
        from qt_shell.native_report_view import ReportWarnings
        panel = ReportWarnings()
        panel.set_warnings([
            {"thimble_id": 1, "current_location": "P3", "historical_locations": ["P3-42"],
             "shift_mm": -42, "reason": "方向冲突"},
            {"thimble_id": 2, "code": "unmatched_history", "historical": {"location": "P1"},
             "current": {"state": "NDD"}},
            {"thimble_id": 3, "code": "unmatched_history", "historical": {"location": "P2"},
             "current": {"state": "missing"}},
        ])
        for group in panel.groups.values():
            group["toggle"].setChecked(True)
        labels = "\n".join(label.text() for label in panel.findChildren(QLabel))
        self.assertIn("本次位置 P3；历史同 P 位 P3-42；移位 -42 mm。方向冲突", labels)
        self.assertIn("本次该管全部为 NDD / 无显示", labels)
        self.assertIn("本次该管无检测记录", labels)

    def test_debounce_only_sends_latest_and_stale_response_does_not_replace_draft(self):
        page, client = self.report()
        page._inline_report_edit("note", "first")
        page._inline_report_edit("note", "second")
        QTest.qWait(470)
        posts = [entry for entry in client.requests if entry[:2] == ("POST", "/api/reports/preview")]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[-1][2]["draft_edits"], [{"key": "note", "value": "second"}])
        old = posts[-1][3]
        page._inline_report_edit("note", "third")
        old({"snapshot_id": "late", "html": "<table><tr><td>late</td></tr></table>"}, None)
        self.assertIsNone(page.snapshot_id)
        self.assertEqual(page.preview_text.tables[0].item(0, 1).text(), "third")
        page.source_data_changed()
        count = len(client.requests)
        QTest.qWait(470)
        self.assertEqual(len(client.requests), count)
        with patch("qt_shell.native_windows.QMessageBox.question", return_value=QMessageBox.StandardButton.No):
            page.preview_report()
        self.assertEqual(len(client.requests), count)
        self.assertEqual(page.draft_edits, [{"key": "note", "value": "third"}])

    def test_native_editor_supports_newline_commit_and_escape(self):
        page, _client = self.report()
        page.resize(1000, 750)
        page.show()
        self.app.processEvents()
        table = page.preview_text.tables[0]
        item = table.item(0, 1)
        table.editItem(item)
        self.app.processEvents()
        editor = next(e for e in table.findChildren(QPlainTextEdit) if e.isVisible())
        editor.setPlainText("第一行")
        editor.moveCursor(QTextCursor.MoveOperation.End)
        QTest.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
        editor.insertPlainText("第二行")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.assertEqual(page.draft_edits, [{"key": "note", "value": "第一行\n第二行"}])
        table.editItem(item)
        self.app.processEvents()
        editor = next(e for e in table.findChildren(QPlainTextEdit) if e.isVisible())
        editor.setPlainText("不保存")
        QTest.keyClick(editor, Qt.Key.Key_Escape)
        self.assertEqual(item.text(), "第一行\n第二行")

    def test_response_waits_for_active_native_editor(self):
        page, client = self.report()
        page.resize(1000, 750)
        page.show()
        self.app.processEvents()
        page.preview_report()
        callback = client.requests[-1][3]
        table = page.preview_text.tables[0]
        item = table.item(0, 1)
        table.editItem(item)
        self.app.processEvents()
        editor = next(e for e in table.findChildren(QPlainTextEdit) if e.isVisible())
        editor.setFocus()
        editor.setPlainText("正在输入")
        callback({"snapshot_id": "too-early", "html": "<table><tr><td>replace</td></tr></table>"}, None)
        self.assertTrue(editor.isVisible())
        self.assertIsNone(page.snapshot_id)
        QTest.keyClick(editor, Qt.Key.Key_Return)
        QTest.qWait(100)
        self.assertEqual(page.draft_edits, [{"key": "note", "value": "正在输入"}])
        self.assertIsNone(page.snapshot_id)
        self.assertEqual(page.preview_text.tables[0].item(0, 1).text(), "正在输入")

    def test_settings_six_categories_keep_audit_and_backup_routes(self):
        window = NativeMainWindow(Client(), {"username": "viewer", "permissions": ["data.read"]})
        dialog = window.settings_dialog
        self.assertEqual(dialog.nav.count(), 6)
        self.assertEqual(dialog.nav.item(4).data(Qt.ItemDataRole.UserRole), "个人账户、角色与密码")
        window.open_settings(6)
        self.assertEqual(dialog.nav.currentRow(), 5)
        self.assertEqual(dialog.maintenance_tabs.currentIndex(), 1)
        window.open_settings(5)
        self.assertEqual(dialog.maintenance_tabs.currentIndex(), 0)
        window.open_settings(0)
        self.app.processEvents()
        self.assertTrue(window.settings_page.source.isVisible())
        self.assertTrue(window.settings_page.source_fields["path"].isVisible())
        QTest.mouseClick(dialog.quick_actions[2], Qt.MouseButton.LeftButton)
        self.assertEqual(dialog.nav.currentRow(), 2)
        window.settings_page._source_loaded({"active": {"path": "test-data.db", "engine": "sqlite",
                                                       "exists": True, "size_bytes": 1048576}}, None)
        window.settings_page.copy_source_path()
        self.assertEqual(QApplication.clipboard().text(), "test-data.db")
        self.assertFalse(window.settings_page.source_validate.isEnabled())
        with patch.object(dialog.preferences, "save"):
            dialog.start.setCurrentIndex(dialog.start.findData(3))
            self.assertFalse(dialog.remember.isChecked())
            dialog.remember.setChecked(True)
            self.assertEqual(dialog.start.currentData(), -1)
            dialog.theme.setCurrentIndex(dialog.theme.findData("dark"))
            self.assertTrue(dialog.theme_choices["dark"].isChecked())
            self.assertFalse(dialog.theme_choices["light"].isChecked())
            dialog._preference_timer.stop()

    def test_chart_options_reach_authoritative_queries_and_survive_redraw(self):
        from PySide6.QtCharts import QScatterSeries, QBarSeries
        from qt_shell.native_charts import ChartPanel
        from qt_shell.native_components import Preferences
        panel = ChartPanel()
        panel.lines("Labels", {"N1": [(1, 10), (2, 20)]}, "")
        markers = [series for series in panel.view.chart().series() if isinstance(series, QScatterSeries)]
        self.assertTrue(markers)
        self.assertTrue(all(not marker.pointLabelsVisible() for marker in markers))
        panel.set_point_labels(True)
        self.assertTrue(all(marker.pointLabelsVisible() for marker in markers))
        panel.lines("Redraw", {"N1": [(1, 12)]}, "")
        self.assertTrue(all(series.pointLabelsVisible() for series in panel.view.chart().series()
                            if isinstance(series, QScatterSeries)))
        panel.bars("Bins", [("0-5", 1)], "")
        self.assertTrue(next(series for series in panel.view.chart().series()
                             if isinstance(series, QBarSeries)).isLabelsVisible())
        panel.set_point_labels(False)
        self.assertFalse(next(series for series in panel.view.chart().series()
                              if isinstance(series, QBarSeries)).isLabelsVisible())
        client = Client()
        window = NativeMainWindow(client, {"username": "viewer", "permissions": ["data.read"]})
        window.context.preferences.values.update(ndd_zero=False, point_labels=True)
        client.requests.clear()
        window.apply_preferences()
        self.assertTrue(any("ndd_zero=0" in entry[1] for entry in client.requests))
        vis = window.stack.widget(3).visualization
        self.assertFalse(vis.ndd_zero)
        vis.data = {"snapshots": [{"unit": "N1", "outage": "N101", "tubes": []}]}
        with QSignalBlocker(vis.snapshot):
            vis.snapshot.clear()
            vis.snapshot.addItem("N101", 0)
        vis.load_longitudinal()
        self.assertIn("ndd_zero=0", client.requests[-1][1])
        normalised = Preferences.validated({"ndd_zero": "false", "point_labels": True})
        self.assertIs(normalised["ndd_zero"], True)
        self.assertIs(normalised["point_labels"], True)


if __name__ == "__main__":
    unittest.main()
