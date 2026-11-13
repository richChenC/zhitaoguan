"""Import source drafts, async failures and native comparison rule workflows."""
import unittest
from pathlib import Path
import native_test_env
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qt_shell.native_components import Preferences
from qt_shell.native_settings_business import ColorSwatch, RulesSettingsPanel
from qt_shell.native_windows import NativeMainWindow
from test_native_workflows import Client


class NativeSettingsBusinessTests(unittest.TestCase):
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

    def dialog(self, permissions=("data.read", "settings.manage", "data.import")):
        client = Client()
        window = NativeMainWindow(client, {"permissions": list(permissions)})
        dialog = window.settings_dialog
        dialog.preferences.path = Path(native_test_env.test_data.name) / (self.id().split(".")[-1] + ".json")
        return window, dialog, client

    def test_source_load_preserves_early_edit_and_save_merges_latest_profile(self):
        window, dialog, client = self.dialog()
        dialog.source_path.setText("temporary-folder")
        dialog._source_profile_loaded({"profile": {"source_directory": "saved", "timeout_seconds": 10,
                                                  "server_url": ""}}, None)
        self.assertEqual(dialog.source_path.text(), "temporary-folder")
        self.assertTrue(dialog.save_source.isEnabled())
        before = len(client.requests)
        dialog.persist_source()
        dialog.persist_source()
        self.assertEqual(len(client.requests), before + 1)
        current = client.requests[-1]
        dialog.source_path.setText("newer-draft")
        current[3]({"profile": {"source_directory": "external", "timeout_seconds": 57,
                               "server_url": "https://example.test/api"}}, None)
        save = client.requests[-1]
        self.assertEqual(save[2]["profile"], {"source_directory": "temporary-folder", "timeout_seconds": 57,
                                             "server_url": "https://example.test/api"})
        save[3]({"profile": save[2]["profile"]}, None)
        self.assertEqual(dialog.source_path.text(), "newer-draft")
        self.assertEqual(dialog.preferences.values["source_path"], "temporary-folder")
        self.assertTrue(dialog.save_source.isEnabled())
        self.assertIn("尚未保存", dialog.source_save_status.text())

    def test_source_failure_preserves_baseline_and_does_not_save_draft_as_display_preference(self):
        window, dialog, client = self.dialog()
        dialog._source_profile_loaded({"profile": {"source_directory": "saved"}}, None)
        original = dialog.preferences.values["source_path"]
        dialog.source_path.setText("draft")
        dialog.save_display()
        self.assertEqual(dialog.preferences.values["source_path"], original)
        dialog.persist_source()
        client.requests[-1][3](None, "<b>offline</b>")
        self.assertEqual(dialog._source_baseline["source_directory"], "saved")
        self.assertEqual(dialog.source_path.text(), "draft")
        self.assertTrue(dialog.save_source.isEnabled())
        self.assertEqual(dialog.source_save_status.textFormat(), Qt.TextFormat.PlainText)
        self.assertIn("<b>offline</b>", dialog.source_save_status.text())

    def test_scan_blocks_duplicates_and_results_request_rpt_import(self):
        window, dialog, client = self.dialog()
        dialog.source_path.setText("rpt-root")
        emitted = []
        dialog.sourceImportRequested.disconnect()
        dialog.sourceImportRequested.connect(emitted.append)
        dialog.scan_sources()
        scan = client.requests[-1]
        before = len(client.requests)
        dialog.scan_sources()
        self.assertEqual(len(client.requests), before)
        self.assertFalse(dialog.source_browse.isEnabled())
        scan[3]({"items": [{"path": "rpt-result", "station": "N", "outage": "N101"}],
                 "scanned_directories": 3}, None)
        self.assertEqual(len(dialog.source_results.buttons), 1)
        dialog.nav.setCurrentRow(2)
        dialog.show()
        QTest.qWait(30)
        self.assertGreater(dialog.source_results.height(), 0)
        self.assertFalse(dialog.source_results.buttons[0].visibleRegion().isEmpty())
        dialog.source_results.buttons[0].click()
        self.assertEqual(emitted, ["rpt-result"])
        self.assertIn("发现 1 个", dialog.scan_status.text())
        dialog.scan_sources()
        dialog._sources_loaded({"items": [{"path": "stale"}]}, None, 1)
        self.assertTrue(dialog._source_scanning)
        client.requests[-1][3](None, "scan refused")
        self.assertTrue(dialog.source_browse.isEnabled())
        self.assertIn("失败", dialog.scan_status.text())

    def test_readonly_source_and_rules_reject_direct_writes(self):
        window, dialog, client = self.dialog(("data.read",))
        dialog._source_profile_loaded({"profile": {"source_directory": "saved"}}, None)
        dialog.source_path.setText("draft")
        before = len(client.requests)
        dialog.persist_source()
        dialog.scan_sources()
        dialog.rules_panel.loaded = True
        dialog.rules_panel.name.setText("forbidden")
        dialog.rules_panel.create_version()
        dialog._open_source({"path": "forbidden"})
        self.assertEqual(len(client.requests), before)
        self.assertFalse(dialog.save_source.isEnabled())
        self.assertFalse(dialog.create_rule.isEnabled())
        self.assertIn("没有导入权限", dialog.scan_status.text())

    def test_dynamic_rule_history_keeps_form_reachable_in_small_window(self):
        window, dialog, client = self.dialog()
        panel = dialog.rules_panel
        dialog.resize(820, 600)
        dialog.nav.setCurrentRow(3)
        dialog.show()
        self.app.processEvents()
        for count in (1, 20, 2, 40):
            rows = [{"version": version, "name": "规则" + str(version),
                     "match_tolerance_mm": .01, "is_active": version == count,
                     "note": "多行依据\n" * (version % 3)}
                    for version in range(count, 0, -1)]
            panel._loaded(panel.serial, {"active": rows[0], "items": rows}, None)
            QTest.qWait(30)
            host = dialog.stack.currentWidget()
            host.verticalScrollBar().setValue(host.verticalScrollBar().maximum())
            self.app.processEvents()
            self.assertFalse(panel.create.visibleRegion().isEmpty(), count)
            self.assertLessEqual(panel.history.height(), 260)
            self.assertGreater(panel.history.height(), 0)
            host.verticalScrollBar().setValue(0)
            self.app.processEvents()
            self.assertTrue(any(not control.visibleRegion().isEmpty()
                                for control in panel.group.buttons()), count)
            if count > 2:
                self.assertGreater(panel.history.verticalScrollBar().maximum(), 0)

    def test_equal_and_zero_thresholds_and_ndd_color_persist(self):
        window, dialog, client = self.dialog()
        dialog.levels[0].setValue(0)
        dialog.levels[1].setValue(0)
        dialog.none_color = "#123456"
        dialog.save_display()
        self.assertEqual(dialog.preferences.values["depth_levels"], [0, 0])
        self.assertEqual(dialog.preferences.values["ndd_color"], "#123456")
        window.workbench.plate.set_records([{"unit_id": 1, "thimble_id": 1, "indication": "NDD"}], 1)
        self.assertEqual(window.workbench.plate._record_color(1, 1).name(), "#123456")
        self.assertEqual(window.workbench.plate._record_color(1, 2).name(), "#ffffff")
        self.assertEqual(window.stack.widget(3).visualization.severity_none, "#123456")
        self.assertEqual(Preferences.validated(dialog.preferences.values)["depth_levels"], [0, 0])
        dialog.levels[0].setValue(40)
        dialog.levels[1].setValue(30)
        dialog.save_display()
        self.assertEqual(dialog.preferences.values["depth_levels"], [0, 0])
        self.assertIn("不能大于", dialog.display_status.text())
        dialog._display_timer.stop()

    def test_rule_base_selection_refresh_drafts_and_create_failure_retry(self):
        client = Client()
        panel = RulesSettingsPanel(client, {"settings.manage"})
        rules = [{"version": 2, "name": "new", "match_tolerance_mm": .2, "note": "new note", "is_active": 1},
                 {"version": 1, "name": "old", "match_tolerance_mm": .01, "note": "old note"}]
        data = {"active": rules[0], "items": rules}
        client.requests[-1][3](data, None)
        self.assertEqual(panel.tolerance.text(), "0.2")
        self.assertEqual(panel.note.text(), "")
        panel.name.setText("draft")
        panel.group.button(1).click()
        self.assertEqual(panel.note.text(), "old note")
        self.assertEqual(panel.name.text(), "draft")
        panel.tolerance.setText("0.0001")
        panel.note.setText("custom draft")
        panel.load()
        client.requests[-1][3](data, None)
        self.assertEqual(panel.tolerance.text(), "0.0001")
        self.assertEqual(panel.note.text(), "custom draft")
        panel.create_version()
        create = client.requests[-1]
        self.assertEqual(create[2]["parent_version"], 1)
        self.assertEqual(create[2]["match_tolerance_mm"], .0001)
        before = len(client.requests)
        panel.create_version()
        panel.load()
        self.assertEqual(len(client.requests), before)
        create[3](None, "<b>refused</b>")
        self.assertEqual(panel.name.text(), "draft")
        self.assertEqual(panel.error.text(), "<b>refused</b>")
        panel.create_version()
        client.requests[-1][3]({"version": 3, "name": "draft"}, None)
        self.assertEqual(panel.name.text(), "")
        self.assertEqual(panel.note.text(), "")
        self.assertEqual(client.requests[-1][0], "GET")

    def test_rule_load_failure_blocks_creation_and_stale_response_is_ignored(self):
        client = Client()
        panel = RulesSettingsPanel(client, {"settings.manage"})
        old = client.requests[-1]
        panel.load()
        latest = client.requests[-1]
        old[3]({"active": {}, "items": []}, None)
        self.assertFalse(panel.loaded)
        latest[3](None, "offline")
        panel.name.setText("draft")
        before = len(client.requests)
        panel.create_version()
        self.assertEqual(len(client.requests), before)
        self.assertFalse(panel.create.isEnabled())
        self.assertIn("读取失败", panel.active.text())

    def test_color_swatch_center_is_actual_selected_color(self):
        window, dialog, client = self.dialog()
        dialog.nav.setCurrentRow(2)
        dialog.show()
        self.app.processEvents()
        for swatch in (dialog.none_swatch, *dialog.swatches):
            self.assertEqual((swatch.width(), swatch.height()), (48, 30))
        for value in ("#79b98c", "#e5a83b", "#df4b45", "#123456"):
            swatch = ColorSwatch(value)
            swatch.show()
            self.app.processEvents()
            image = swatch.grab().toImage()
            self.assertEqual(image.pixelColor(image.width() // 2, image.height() // 2).name(), value)
            swatch.close()


if __name__ == "__main__":
    unittest.main()
