"""Settings storage state, native navigation and long path regression."""
import unittest
from pathlib import Path
from unittest.mock import patch
import native_test_env  # noqa: F401
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from qt_shell.native_windows import NativeMainWindow, NativeSettingsPage
from test_native_workflows import Client


class NativeSettingsLayoutTests(unittest.TestCase):
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

    def test_pending_storage_request_blocks_duplicates_and_stale_responses(self):
        client = Client()
        page = NativeSettingsPage(client, {"permissions": ["settings.manage"]})
        first = next(row for row in client.requests if row[1] == "/api/settings/data-source")
        before = len(client.requests)
        page.load_source()
        page.validate_source()
        self.assertEqual(len(client.requests), before)
        first[3]({"active": {"engine": "sqlite", "mode": "local", "exists": True,
                             "path": "current.db", "size_bytes": 512}}, None)
        self.assertEqual(page.source_fields["size"].text(), "0.5 KB")
        self.assertEqual(page.source_badge.text(), "本地使用中")
        page.validate_source()
        validate = client.requests[-1]
        self.assertEqual(validate[1], "/api/settings/data-source/validate")
        self.assertFalse(page.source_refresh.isEnabled())
        first[3]({"active": {"path": "STALE.db"}}, None)
        self.assertTrue(page._source_busy)
        self.assertEqual(page.source_fields["path"].text(), "current.db")
        validate[3]({"ok": True, "message": "本地数据库校验通过。",
                     "active": {"engine": "sqlite", "mode": "local", "exists": True,
                                "path": "current.db", "size_bytes": 1048576}}, None)
        self.assertEqual(page.source_fields["size"].text(), "1.00 MB")
        self.assertIn("校验通过", page.source_badge.text())
        self.assertTrue(page.source_validate.isEnabled())
        page.load_source()
        client.requests[-1][3](None, "<b>offline</b>")
        self.assertFalse(page._source_busy)
        self.assertEqual(page.source_status.text(), "<b>offline</b>")
        self.assertEqual(page.source_status.textFormat(), Qt.TextFormat.PlainText)
        self.assertEqual(page.source_fields["path"].text(), "current.db")
        self.assertTrue(page.source_refresh.isEnabled())
        self.assertEqual(page.source_badge.text(), "状态不可用")

    def test_readonly_cannot_invoke_storage_validation_directly(self):
        client = Client()
        page = NativeSettingsPage(client, {"permissions": ["data.read"]})
        page._source_loaded({"active": {"engine": "sqlite", "exists": True, "path": "readonly.db"}}, None)
        before = len(client.requests)
        page.validate_source()
        self.assertEqual(len(client.requests), before)
        self.assertFalse(page.source_validate.isEnabled())

    def test_six_category_keyboard_wrap_and_quick_action_focus(self):
        window = NativeMainWindow(Client(), {"permissions": ["data.read"]})
        window.open_settings()
        dialog = window.settings_dialog
        self.app.processEvents()
        for width, expected in ((1180, 236), (901, 236), (900, 190), (820, 190)):
            dialog.resize(width, 820)
            self.app.processEvents()
            self.assertEqual(dialog.sidebar.width(), expected)
            self.assertGreater(dialog.nav.visualItemRect(dialog.nav.item(5)).bottom(), 390)
            self.assertLess(dialog.nav.visualItemRect(dialog.nav.item(5)).bottom(), dialog.nav.height())
        QTest.mouseClick(dialog.quick_actions[2], Qt.MouseButton.LeftButton)
        self.assertEqual(dialog.nav.currentRow(), 2)
        self.assertTrue(dialog.nav.hasFocus())
        for key, expected in ((Qt.Key.Key_Down, 3), (Qt.Key.Key_End, 5), (Qt.Key.Key_Right, 0),
                              (Qt.Key.Key_Left, 5), (Qt.Key.Key_Home, 0)):
            QTest.keyClick(dialog.nav, key)
            self.assertEqual(dialog.nav.currentRow(), expected)
            self.assertEqual(dialog.stack.currentIndex(), expected)
        window.context.preferences.save(theme="dark")
        window.apply_preferences()
        self.assertTrue(dialog.nav.property("dark"))

    def test_source_path_wrap_and_copy_preserve_exact_text(self):
        client = Client()
        page = NativeSettingsPage(client, {"permissions": ["settings.manage"]})
        page.source.resize(569, 400)
        path = "D:/" + "检测数据/" * 30 + "<original>&.db"
        page._source_loaded({"active": {"engine": "sqlite", "mode": "local", "exists": True,
                                        "path": path, "size_bytes": 20}}, None)
        field = page.source_fields["path"]
        self.assertEqual(field.text(), path)
        self.assertGreater(field.height(), 60)
        self.assertGreaterEqual(page.source.actions.y(), page.source.stats[2][0].geometry().bottom())
        page.copy_source_path()
        self.assertEqual(QApplication.clipboard().text(), path)
        self.assertEqual(page.source_copy.text(), "已复制")
        page.source.show()
        self.app.processEvents()
        self.assertTrue(field.isReadOnly())
        self.assertFalse(page.source_text.isVisible())

    def test_preference_controls_save_and_synchronize_report_policy_without_database_writes(self):
        client = Client()
        window = NativeMainWindow(client, {"permissions": ["settings.manage"]})
        dialog = window.settings_dialog
        prefs = dialog.preferences
        prefs.path = Path(native_test_env.test_data.name) / "settings-controls.json"
        window.open_settings(1)
        self.app.processEvents()
        before = len(client.requests)
        with patch.object(prefs, "save", wraps=prefs.save) as save:
            with patch.object(prefs, "path", prefs.path):
                dialog.animations.setCurrentIndex(dialog.animations.findData(False))
                dialog.policy.setCurrentIndex(dialog.policy.findData("latest"))
                self.assertEqual(dialog.display_policy.currentData(), "latest")
                QTest.mouseClick(dialog.notification_sound, Qt.MouseButton.LeftButton)
                QTest.qWait(350)
                self.assertEqual(sum("report_policy" in call.kwargs for call in save.call_args_list), 1,
                                 save.call_args_list)
                self.assertFalse(prefs.values["animations"])
                self.assertEqual(prefs.values["report_policy"], "latest")
                self.assertEqual(prefs.values["notification_sound"], dialog.notification_sound.isChecked())
                self.assertEqual(dialog.preference_badge.text(), "已保存")
                dialog.display_policy.setCurrentIndex(dialog.display_policy.findData("manual"))
                QTest.qWait(350)
                self.assertEqual(prefs.values["report_policy"], "manual")
                self.assertEqual(dialog.policy.currentData(), "manual")
        self.assertFalse(any(row[0] == "POST" for row in client.requests[before:]))

    def test_direction_failure_reverts_control_and_reset_does_not_discard_other_settings(self):
        client = Client()
        window = NativeMainWindow(client, {"permissions": ["settings.manage"]})
        dialog = window.settings_dialog
        initial = next(row for row in reversed(client.requests) if row[1] == "/api/settings/state-direction")
        initial[3]({"shift_direction": "-1", "writable": True}, None)
        dialog.direction.setCurrentIndex(dialog.direction.findData("pending"))
        dialog.save_direction()
        pending = client.requests[-1]
        before = len(client.requests)
        dialog.save_direction()
        self.assertEqual(len(client.requests), before)
        self.assertFalse(dialog.direction.isEnabled())
        pending[3](None, "<b>save refused</b>")
        self.assertEqual(dialog.direction.currentData(), "-1")
        self.assertTrue(dialog.direction.isEnabled())
        self.assertIn("<b>save refused</b>", dialog.save_status.text())
        self.assertEqual(dialog.save_status.textFormat(), Qt.TextFormat.PlainText)
        with patch.object(dialog.preferences, "save", wraps=dialog.preferences.save) as save:
            with patch.object(dialog.preferences, "path",
                              Path(native_test_env.test_data.name) / "settings-defaults.json"):
                dialog.preferences.save(source_path="preserve-import-folder", auto_ndd=False,
                                        depth_levels=[20, 60], depth_colors=["#123456", "#345678", "#789abc"])
                save.reset_mock()
                with patch("qt_shell.native_settings.QMessageBox.question",
                           return_value=QMessageBox.StandardButton.No):
                    dialog.reset_preferences()
                self.assertEqual(save.call_count, 0)
                with patch("qt_shell.native_settings.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
                    dialog.reset_preferences()
                reset = client.requests[-1]
                self.assertEqual(reset[2], {"shift_direction": "1"})
                self.assertEqual(save.call_count, 0)
                dialog.levels[0].setValue(25)
                self.assertTrue(dialog._display_timer.isActive())
                reset[3]({"shift_direction": "1", "writable": True}, None)
                self.assertEqual(save.call_count, 1)
                self.assertEqual(dialog.preferences.values["theme"], "system")
                self.assertTrue(dialog.preferences.values["notification_sound"])
                self.assertEqual(dialog.preferences.values["source_path"], "preserve-import-folder")
                self.assertFalse(dialog.preferences.values["auto_ndd"])
                self.assertEqual(dialog.preferences.values["depth_levels"], [20, 60])
                self.assertEqual(dialog.start.currentData(), -1)
                self.assertEqual(dialog.direction.currentData(), "1")
                self.assertEqual(dialog.save_status.text(), "已恢复本页默认设置")
                self.assertFalse(dialog._preference_timer.isActive())
                QTest.qWait(350)
                self.assertEqual(dialog.preferences.values["depth_levels"][0], 25)

    def test_preference_page_remains_scrollable_and_toggle_works_with_keyboard(self):
        window = NativeMainWindow(Client(), {"permissions": ["data.read"]})
        window.open_settings(1)
        dialog = window.settings_dialog
        for width in (1180, 901, 900, 820):
            dialog.resize(width, 600)
            QTest.qWait(80)
            host = dialog.stack.widget(1)
            host.verticalScrollBar().setValue(host.verticalScrollBar().maximum())
            QTest.qWait(40)
            self.assertGreaterEqual(dialog.reset_button.visibleRegion().boundingRect().height(), 35)
            self.assertLessEqual(dialog.policy.width(), dialog.preference_panel.width() - 42)
        host.ensureWidgetVisible(dialog.remember)
        dialog.remember.setFocus()
        before = dialog.remember.isChecked()
        QTest.keyClick(dialog.remember, Qt.Key.Key_Space)
        self.assertIs(dialog.remember.isChecked(), not before)
        self.assertEqual(dialog.start.currentData() == -1, dialog.remember.isChecked())
        self.assertFalse(dialog.direction.isEnabled())
        dialog._preference_timer.stop()

    def test_notification_preferences_do_not_restyle_or_redraw_models(self):
        window = NativeMainWindow(Client(), {"permissions": ["data.read"]})
        preferences = window.context.preferences
        preferences.path = Path(native_test_env.test_data.name) / "settings-performance.json"
        visual = window.stack.widget(3).visualization
        model = window.stack.widget(2)
        with patch.object(window, "setStyleSheet", wraps=window.setStyleSheet) as style, \
                patch.object(model, "set_theme", wraps=model.set_theme) as model_theme, \
                patch.object(model, "set_severity", wraps=model.set_severity) as model_levels, \
                patch.object(visual, "set_theme", wraps=visual.set_theme) as chart_theme:
            preferences.save(notification_duration=5000)
            window.apply_preferences()
            self.assertEqual((style.call_count, model_theme.call_count, model_levels.call_count,
                              chart_theme.call_count), (0, 0, 0, 0))
            preferences.save(density="compact")
            window.apply_preferences()
            self.assertEqual(style.call_count, 1)
            self.assertEqual(window.workbench.table.verticalHeader().defaultSectionSize(), 28)
            self.assertEqual((model_theme.call_count, model_levels.call_count, chart_theme.call_count), (0, 0, 0))
            preferences.save(animations=not preferences.values["animations"])
            window.apply_preferences()
            self.assertEqual(chart_theme.call_count, 1)
            self.assertEqual(model_levels.call_count, 0)
            preferences.save(depth_levels=[25, 65], depth_colors=["#123456", "#345678", "#789abc"])
            window.apply_preferences()
            self.assertEqual(model_levels.call_count, 1)
            self.assertEqual(model_theme.call_count, 0)


if __name__ == "__main__":
    unittest.main()
