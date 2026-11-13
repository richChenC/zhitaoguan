"""RPT preselection never bypasses explicit, resumable confirmation."""
import unittest
import json
from pathlib import Path
from types import SimpleNamespace
import native_test_env  # noqa: F401
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from qt_shell.native_components import Preferences, workspace_styles
from qt_shell.native_import import ImportWizard
from qt_shell.native_report_choice import ReportChoiceDialog, ReportSelectionSummary
from qt_shell.native_windows import DataWorkbench, NativeMainWindow
from test_native_workflows import Client


class ReportChoiceTests(unittest.TestCase):
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
    def reports():
        base = {"site_code": "N", "unit_id": 1, "outage": "N101", "group": "TH1I1CAL1",
                "records": 2, "tube_count": 2, "tubes": [1, 2], "analysts": ["<b>原名</b>"],
                "sha256": "first", "sum_sha256": "sum", "modified_ns": 5}
        return [
            {**base, "path": "D:/source/Report2.rpt", "name": "Report2.rpt"},
            {**base, "path": "D:/source/Report10.rpt", "name": "Report10.rpt", "sha256": "second",
             "tubes": [2, 3], "blank_indication": {"count": 1, "tubes": 1}},
            {**base, "group": "TH2I1CAL1", "path": "D:/source/other.rpt", "name": "other.rpt",
             "tubes": [3, 4], "sha256": "third"},
            {"path": "D:/source/failed.rpt", "error": "parse failed"},
        ]

    def test_manual_single_report_still_requires_selection_and_each_group_confirmation(self):
        choice = ReportChoiceDialog(self.reports())
        self.assertEqual(len(choice.groups), 2)
        self.assertEqual(choice.selected, [None, None])
        choice.confirm_current()
        self.assertFalse(choice.confirmed)
        self.assertIn("请选择", choice.context.text())
        choice.radios[0].click()
        choice.confirm_current()
        self.assertEqual(choice.index, 1)
        self.assertEqual(choice.coverage(choice.groups[1][0]), {1, 2})
        self.assertFalse(choice.radios[0].isChecked())
        choice.radios[0].click()
        choice.confirm_current()
        self.assertTrue(choice.complete)

    def test_latest_preselect_is_unconfirmed_tie_breaking_and_resume_are_stable(self):
        choice = ReportChoiceDialog(self.reports(), latest=True)
        choice.show()
        self.assertEqual(choice.selected[0]["name"], "Report10.rpt")
        self.assertFalse(choice.complete)
        self.assertFalse(choice.confirmed)
        choice.confirm_current()
        choice.reject()
        choice.show()
        self.assertEqual(choice.index, 1)
        self.assertEqual(choice.confirmed, {0})
        choice.confirm_current()
        self.assertTrue(choice.complete)
        choice.show_group(0)
        choice.radios[0].click()
        self.assertEqual(choice.confirmed, {1})
        self.assertFalse(choice.complete)
        choice.show_group(1)
        choice.confirm_current()
        self.assertEqual(choice.index, 0)
        self.assertIn("第一处遗漏", choice.context.text())

    def test_coverage_cannot_mix_same_outage_other_units_or_sites(self):
        reports = self.reports()[:1]
        reports += [{**reports[0], "unit_id": 2, "path": "D:/source/n2.rpt", "tubes": [20]},
                    {**reports[0], "site_code": "F", "path": "D:/source/f.rpt", "tubes": [30]}]
        choice = ReportChoiceDialog(reports, latest=True)
        choice.confirm_current()
        self.assertEqual(choice.coverage(choice.groups[1][0]), set())
        choice.confirm_current()
        self.assertEqual(choice.coverage(choice.groups[2][0]), set())

    def test_analyst_plain_text_clickable_labels_and_small_dark_layout(self):
        choice = ReportChoiceDialog(self.reports(), latest=True)
        choice.setStyleSheet(workspace_styles("dark"))
        choice.resize(460, 500)
        choice.show()
        self.app.processEvents()
        label = choice.option_host.findChild(QLabel, "reportAnalystHeading")
        self.assertEqual(label.textFormat(), Qt.TextFormat.PlainText)
        self.assertIn("<b>原名</b>", label.text())
        QTest.mouseClick(label, Qt.MouseButton.LeftButton)
        self.assertEqual(choice.selected[0]["name"], "Report2.rpt")
        self.assertTrue(choice.confirm.isVisible())
        self.assertLessEqual(choice.confirm.geometry().right(), choice.width())
        QTest.keyClick(choice, Qt.Key.Key_Right)
        self.assertEqual(choice.confirmed, {0})
        QTest.keyClick(choice, Qt.Key.Key_Left)
        self.assertEqual(choice.index, 0)

    def test_import_blocks_unconfirmed_latest_and_preserves_all_candidate_hashes(self):
        client = Client()
        wizard = ImportWizard(client, DataWorkbench.MAPPING_FIELDS, {"report_policy": "latest"}, mode="directory")
        wizard.path.setText("D:/source")
        reports = self.reports()
        wizard.source_loaded(wizard.generation, {"reports": reports}, None, advance=False)
        self.assertTrue(wizard.mapping_split.isHidden())
        self.assertTrue(wizard.excel_settings.isHidden())
        self.assertFalse(wizard.directory_export.isEnabled())
        self.assertFalse(wizard.prepare_payload())

        self.assertFalse(client.requests)
        wizard.report_choice.confirm_current()
        wizard.report_choice.confirm_current()
        self.assertTrue(wizard.directory_export.isEnabled())
        self.assertTrue(wizard.prepare_payload())
        self.assertEqual(wizard.payload["reports"], [reports[1]["path"], reports[2]["path"]])
        self.assertEqual(len(wizard.payload["report_confirmation"]["candidates"]), 3)
        self.assertEqual(wizard.payload["report_confirmation"]["candidates"][0]["sha256"], "first")
        self.assertIn("parse failed", wizard.mapping_note.text())
        wizard.report_policy.setCurrentIndex(0)
        self.assertFalse(wizard.report_choice.complete)
        self.assertEqual(wizard.report_choice.selected, [None, None])
        wizard.path.setText("D:/another-source")
        self.assertIsNone(wizard.report_choice)
        self.assertFalse(wizard.ready_source)
        self.assertFalse(wizard.prepare_payload())

    def test_rpt_source_and_summary_share_the_original_source_panel(self):
        wizard = ImportWizard(Client(), DataWorkbench.MAPPING_FIELDS, {}, mode="directory")
        wizard.path.setText("D:/source")
        wizard.source_loaded(wizard.generation, {"reports": self.reports()}, None)
        self.assertEqual(wizard.currentId(), 1)
        self.assertEqual(wizard.pages.currentIndex(), 0)
        self.assertTrue(wizard.source_host.isAncestorOf(wizard.report_summary))
        self.assertTrue(wizard.source_host.isAncestorOf(wizard.mapping_note))
        self.assertFalse(wizard.source_status.text())
        wizard.path.setText("D:/changed")
        self.assertEqual(wizard.currentId(), 0)
        self.assertFalse(wizard.report_summary.rows)

    def test_summary_rows_preserve_plain_text_dates_filter_and_group_activation(self):
        reports = self.reports()
        reports[1]["modified_at"] = "2026-11-12T10:20:30"
        reports[2]["analysts"] = ["OTHER"]
        choice = ReportChoiceDialog(reports, latest=True)
        summary = ReportSelectionSummary()
        summary.setStyleSheet(workspace_styles("light"))
        summary.resize(820, 280)
        summary.set_choice(choice)
        summary.show()
        QTest.qWait(30)
        self.assertEqual(len(summary.rows), 2)
        first = summary.rows[0]
        self.assertEqual(first["group"].text(), "N101 · TH1I1CAL1")
        self.assertIn("修改于 2026-11-12 10:20:30", first["source"].text())
        self.assertEqual(first["source"].toolTip(), reports[1]["path"])
        self.assertEqual(first["widget"].layout().getItemPosition(2), (0, 2, 1, 1))
        self.assertGreaterEqual(summary.scroll.height(), 96)
        self.assertTrue(all(label.textFormat() == Qt.TextFormat.PlainText
                            for label in summary.findChildren(QLabel)))
        summary.search.setText("other")
        self.assertTrue(first["widget"].isHidden())
        self.assertFalse(summary.rows[1]["widget"].isHidden())
        summary.search.setText("Report10")
        self.assertFalse(first["widget"].isHidden())
        self.assertTrue(summary.rows[1]["widget"].isHidden())
        selected_before = list(choice.selected)
        self.assertFalse(choice.complete)
        summary.search.clear()
        summary.resize(460, 280)
        QTest.qWait(30)
        self.assertEqual(first["widget"].layout().getItemPosition(2), (1, 0, 1, 2))
        self.assertEqual(summary.scroll.horizontalScrollBar().maximum(), 0)
        self.assertFalse(summary._layout_timer.isActive())
        activated = []
        summary.groupActivated.connect(activated.append)
        QTest.mouseDClick(first["group"], Qt.MouseButton.LeftButton)
        self.assertEqual(activated, [0])
        self.assertEqual(choice.selected, selected_before)
        summary.set_choice(None)
        self.assertFalse(summary.rows)
        self.assertTrue(summary.search.isHidden())

    def test_summary_unselected_and_empty_analyst_states_follow_reference(self):
        choice = ReportChoiceDialog(self.reports())
        summary = ReportSelectionSummary()
        summary.set_choice(choice)
        self.assertEqual(summary.rows[0]["source"].text(), "尚未确认 · 0 条结果")
        self.assertEqual(summary.rows[0]["analysts"].findChild(QLabel).text(), "未确认")
        choice.selected[0] = {**self.reports()[0], "analysts": []}
        summary.set_choice(choice)
        self.assertEqual(summary.rows[0]["analysts"].findChild(QLabel).text(), "未标明分析人员")

    def test_import_source_change_clears_summary_without_enabling_export(self):
        wizard = ImportWizard(Client(), DataWorkbench.MAPPING_FIELDS, {}, mode="directory")
        wizard.path.setText("D:/source")
        wizard.source_loaded(wizard.generation, {"reports": self.reports()}, None, advance=False)
        self.assertEqual(len(wizard.report_summary.rows), 2)
        wizard.report_summary.search.setText("missing")
        self.assertTrue(all(row["widget"].isHidden() for row in wizard.report_summary.rows))
        self.assertFalse(wizard.directory_export.isEnabled())
        wizard.path.setText("D:/changed")
        self.assertFalse(wizard.report_summary.rows)
        self.assertFalse(wizard.directory_export.isEnabled())

    def test_policy_save_does_not_mutate_shared_preferences_before_change_notification(self):
        parent = QWidget()
        preferences = Preferences(parent)
        preferences.path = Path(native_test_env.test_data.name) / "rpt-policy.json"
        preferences.save(report_policy="manual")
        parent.context = SimpleNamespace(preferences=preferences)
        notifications = []
        preferences.changed.connect(lambda: notifications.append(True))
        wizard = ImportWizard(Client(), DataWorkbench.MAPPING_FIELDS, preferences.values, parent)
        wizard.report_policy.setCurrentIndex(wizard.report_policy.findData("latest"))
        self.assertEqual(preferences.values["report_policy"], "latest")
        self.assertEqual(len(notifications), 1)
        self.assertEqual(json.loads(preferences.path.read_text(encoding="utf-8"))["report_policy"], "latest")

    def test_import_policy_updates_existing_settings_control_before_other_display_saves(self):
        window = NativeMainWindow(Client(), {"username": "viewer", "permissions": ["data.read"]})
        preferences = window.context.preferences
        preferences.path = Path(native_test_env.test_data.name) / "rpt-window-policy.json"
        preferences.save(report_policy="manual")
        wizard = ImportWizard(Client(), DataWorkbench.MAPPING_FIELDS, preferences.values, window.workbench)
        wizard.report_policy.setCurrentIndex(wizard.report_policy.findData("latest"))
        self.assertEqual(window.settings_dialog.policy.currentData(), "latest")
        self.assertFalse(window.settings_dialog._display_timer.isActive())
        window.settings_dialog.save_display()
        self.assertEqual(preferences.values["report_policy"], "latest")


if __name__ == "__main__":
    unittest.main()
