"""Native control workflows: mapping, preflight/commit and report cell editing."""
import unittest
import native_test_env  # noqa: F401

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWizard

from qt_shell.native_components import ScopeBar
from qt_shell.native_import import ImportWizard
from qt_shell.native_report_view import ReportPreview
from qt_shell.native_windows import DataWorkbench


class Client:
    def __init__(self):
        self.requests = []

    def get(self, path, callback=None, **kwargs):
        self.requests.append(("GET", path, None, callback))

    def post(self, path, payload, callback=None, **kwargs):
        self.requests.append(("POST", path, payload, callback))


class NativeWorkflowTests(unittest.TestCase):
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

    def click(self, widget):
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
        self.app.processEvents()

    def test_chart_theme_preserves_series_palette_and_partial_markers(self):
        from PySide6.QtCharts import QScatterSeries
        from qt_shell.native_charts import ChartPanel, PALETTE
        panel = ChartPanel()
        panel.lines("Theme regression", {"Unit 1": [(1, 20), (2, 22), (3, 23)]},
                    "Partial observations", partial={"Unit 1": {2}})
        markers = [s for s in panel.view.chart().series() if isinstance(s, QScatterSeries)]
        self.assertEqual(markers[0].color().name(), PALETTE[0])
        for theme, background in (("dark", "#292f33"), ("light", "#ffffff")):
            panel.set_theme(theme, False)
            self.assertEqual(markers[0].color().name(), PALETTE[0])
            self.assertEqual(markers[1].color().name(), background)
            self.assertEqual(markers[1].borderColor().name(), PALETTE[0])
            self.assertFalse(panel.view.chart().legend().markers(markers[1])[0].isVisible())

    def test_position_fleet_aggregation_uses_weighted_tube_counts(self):
        from qt_shell.native_charts import VisualizationWorkspace
        page = VisualizationWorkspace()
        page.data = {"trends": [
            {"unit": "N1", "order": 1, "total": 40, "positions": {"P1": 40},
             "position_stats": {"P1": {"total": 40, "tubes": 2}}},
            {"unit": "N2", "order": 1, "total": 20, "positions": {"P1": 20},
             "position_stats": {"P1": {"total": 20, "tubes": 1}}},
            {"unit": "N1", "order": 2, "total": None, "positions": {"P1": None}},
        ]}
        page.trend_metric.setCurrentIndex(page.trend_metric.findData("mean"))
        page.refresh_trends()
        self.assertEqual(page.position.contract["groups"]["群厂汇总 · P1"], [(1, 20)])
        page.trend_metric.setCurrentIndex(page.trend_metric.findData("share"))
        self.assertEqual(page.position.contract["groups"]["群厂汇总 · P1"], [(1, 100)])

    def test_mutation_refreshes_report_history_and_all_scope_options(self):
        from qt_shell.native_windows import NativeMainWindow
        client = Client()
        window = NativeMainWindow(client, {"username": "viewer", "permissions": ["data.read"]})
        window.context.set_scope({"site": "D", "unit": "1", "outage": "D120"})
        window._refresh_data()
        window._refresh_data()
        before = len(client.requests)
        QTest.qWait(100)
        requests = client.requests[before:]
        overview = [request for request in requests if request[1] == "/api/overview"]
        self.assertEqual(len(overview), 1)
        combinations = [{"site": "D", "unit_id": 1, "outage": "D117"},
                        {"site": "D", "unit_id": 1, "outage": "D120"}]
        overview[0][3]({"combinations": combinations, "stats": {}}, None)
        for index in (0, 1, 3, 4):
            self.assertEqual(window.stack.widget(index).scope_bar.combinations, combinations)
        report = window.stack.widget(4)
        self.assertGreaterEqual(report.history_combo.findText("D117"), 0)
        self.assertTrue(any(request[1].startswith("/api/analysis/visualization") for request in requests))

    def test_restore_uses_selected_filtered_backup(self):
        from qt_shell.native_windows import NativeSettingsPage
        client = Client()
        page = NativeSettingsPage(client, {"username": "admin", "permissions": ["backup.manage", "database.restore"]})
        page.backups.rows = [{"name": "first", "path": "first.db"}, {"name": "target", "path": "target.db"}]
        page.backups.search.setText("target")
        page.backups.table.selectRow(0)
        page.validate_backup()
        self.assertEqual(client.requests[-1][1], "/api/backup-validate")
        self.assertEqual(client.requests[-1][2]["path"], "target.db")

    def test_backup_table_and_commands_are_visible_after_tab_reparent(self):
        from qt_shell.native_windows import NativeMainWindow
        window = NativeMainWindow(Client(), {"username": "admin",
                                  "permissions": ["data.read", "backup.manage", "database.restore"]})
        window.show()
        window.open_settings(5)
        self.app.processEvents()
        self.assertTrue(window.settings_page.backups.table.isVisible())
        self.assertTrue(window.settings_page.backup_now.isVisible())
        self.assertTrue(window.settings_page.restore_backup.isVisible())

    def test_workbench_save_does_not_schedule_a_second_table_reset(self):
        from qt_shell.native_windows import NativeMainWindow
        client = Client()
        window = NativeMainWindow(client, {"username": "viewer", "permissions": ["data.read"]})
        client.requests.clear()
        window.workbench.dataChanged.emit()
        QTest.qWait(100)
        self.assertFalse(any(request[1].startswith("/api/findings?") for request in client.requests))
        self.assertTrue(any(request[1].startswith("/api/analysis/visualization") for request in client.requests))

    def test_report_repaint_reuses_text_layouts(self):
        preview = ReportPreview()
        preview.resize(1000, 600)
        preview.show()
        preview.setHtml("<table><tr><td>Repeated rich text</td><td>Repeated rich text</td></tr></table>")
        self.app.processEvents()
        table = preview.tables[0]
        table.grab()
        delegate = table.itemDelegate()
        self.assertTrue(delegate._documents)
        first = {key: id(document) for key, document in delegate._documents.items()}
        table.grab()
        self.assertEqual(first, {key: id(document) for key, document in delegate._documents.items()})

    def test_excel_wizard_requires_preview_before_commit_and_renders_source_rows(self):
        client = Client()
        wizard = ImportWizard(client, DataWorkbench.MAPPING_FIELDS, {})
        wizard.show()
        wizard.path.setText("test.xlsx")
        self.click(wizard.button(QWizard.WizardButton.NextButton))
        self.assertEqual(client.requests[-1][1], "/api/import-excel-inspect")
        client.requests[-1][3]({"sheets": [
            {"name": "N101", "header_row": 1, "recognized": True,
             "columns": [{"column": 1, "header": "通道编号"}, {"column": 2, "header": "三字码"}],
             "mapping": {"通道编号": 0, "三字码": 1},
             "sample_rows": [{"row_number": 2, "values": ["1", "WAR"]}]}
        ]}, None)
        self.app.processEvents()
        self.assertEqual(wizard.currentId(), 1)
        self.assertEqual(wizard.source_table.item(0, 0).text(), "2")
        wizard.manual.setChecked(True)
        self.click(wizard.button(QWizard.WizardButton.NextButton))
        request = client.requests[-1]
        self.assertEqual(request[2]["blank_indication_policy"], "check")
        self.assertEqual(request[2]["mapping"]["columns"]["通道编号"], 1)
        self.assertFalse(any(r[2] and r[2].get("blank_indication_policy") == "review" for r in client.requests))
        request[3]({"parsed": 1, "preview_rows": [
            {"outage": "N101", "unit_id": 1, "thimble_id": 1, "indication": "WAR", "location": "P1"}]}, None)
        self.app.processEvents()
        self.assertEqual(wizard.currentId(), 2)
        self.assertEqual(wizard.preview_table.rowCount(), 1)
        self.click(wizard.button(QWizard.WizardButton.NextButton))
        self.assertEqual(wizard.currentId(), 3)
        self.assertFalse(wizard.button(QWizard.WizardButton.CancelButton).isEnabled())
        self.assertEqual(client.requests[-1][2]["blank_indication_policy"], "review")
        client.requests[-1][3]({"inserted": 1, "skipped": 0, "batch_id": 3}, None)
        self.app.processEvents()
        self.assertEqual(wizard.currentId(), 4)
        self.assertIn("新增 1", wizard.result_summary.text())
        self.assertFalse(wizard.button(QWizard.WizardButton.BackButton).isEnabled())

    def test_wizard_cancelled_inspection_ignores_late_result(self):
        client = Client()
        wizard = ImportWizard(client, DataWorkbench.MAPPING_FIELDS, {})
        wizard.show()
        wizard.path.setText("first.xlsx")
        self.click(wizard.button(QWizard.WizardButton.NextButton))
        callback = client.requests[-1][3]
        wizard.reject()
        current = wizard.currentId()
        callback({"sheets": []}, None)
        self.assertFalse(wizard.isVisible())
        self.assertEqual(wizard.currentId(), current)

    def test_scope_is_preserved_when_overview_arrives_later(self):
        client = Client()
        scope = ScopeBar(client)
        scope.set_scope({"site": "N", "unit": "1", "outage": "N101"})
        client.requests[-1][3]({"combinations": [{"site": "N", "unit_id": 1, "outage": "N101"}]}, None)
        self.assertEqual(scope.values(), {"site": "N", "unit": "1", "outage": "N101"})

    def test_report_preserves_merges_proportions_and_native_inline_edits(self):
        preview = ReportPreview()
        preview.resize(1000, 700)
        preview.show()
        self.app.processEvents()
        preview.editable_keys = {"t1:r2:c1"}
        preview.setHtml('<table><colgroup><col style="width:20%"><col style="width:80%"></colgroup>'
                        '<tr style="height:24pt"><td colspan="2"><p>报告标题</p></td></tr>'
                        '<tr><td data-edit-key="t1:r2:c1"><p>原值</p></td><td><p>固定值</p></td></tr></table>')
        preview.resize(1000, 700)
        preview.show()
        self.app.processEvents()
        table = preview.tables[0]
        self.assertEqual(table.columnSpan(0, 0), 2)
        self.assertGreater(table.columnWidth(1), table.columnWidth(0) * 3)
        self.assertGreater(preview.host.width(), 800)
        self.assertGreater(preview.host.height(), 100)
        self.assertGreater(table.visibleRegion().boundingRect().width(), 600)
        changes = []
        preview.cellEdited.connect(lambda key, text: changes.append((key, text)))
        table.item(1, 0).setText("修订")
        self.assertEqual(changes, [("t1:r2:c1", "修订")])
        self.assertFalse(table.item(1, 1).flags() & Qt.ItemFlag.ItemIsEditable)

    def test_cross_page_selection_retains_identity_and_edit_is_not_optimistic(self):
        from qt_shell.native_windows import FindingsModel
        model = FindingsModel()
        model.editable = True
        first = {"id": 1, "outage": "N101", "unit_id": 1, "thimble_id": 1, "percent": 20}
        model.replace([first])
        model.setData(model.index(0, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
        model.replace([{"id": 2, "percent": 30}])
        self.assertEqual(list(model.selected), [1])
        requested = []
        model.editRequested.connect(lambda *args: requested.append(args))
        model.setData(model.index(0, 9), "42")
        self.assertEqual(model.rows[0]["percent"], 30)
        self.assertEqual(requested[0], (2, "percent", "42", 30))

    def test_corrupt_preferences_are_normalized_before_widget_construction(self):
        from qt_shell.native_components import Preferences
        values = Preferences.validated({"theme": ["dark"], "last_page": "garbage",
                                        "depth_levels": [30, 20, 20], "depth_colors": ["red"],
                                        "animations": "false", "report_policy": "all"})
        self.assertEqual(values["theme"], "system")
        self.assertEqual(values["last_page"], 0)
        self.assertEqual(values["depth_levels"], [30, 50])
        self.assertIs(values["animations"], True)
        self.assertEqual(values["report_policy"], "manual")

    def test_report_switch_clears_draft_and_comparison_uses_full_scope(self):
        from qt_shell.native_windows import NativeReportsPage
        page = NativeReportsPage(Client())
        page.scope_bar.combinations = [
            {"site": "N", "unit_id": 1, "outage": code} for code in ("N101", "N102", "N103")]
        page.set_workspace_scope({"site": "N", "unit": 1, "outage": "N102"})
        self.assertEqual([page.history_combo.itemText(i) for i in range(page.history_combo.count())],
                         ["", "N101"])
        page.use_selected.setChecked(True)
        page.draft_edits = [{"key": "t1:r1:c1", "value": "old draft"}]
        page.snapshot_id = "stale"
        page.report_tabs.setCurrentIndex(1)
        self.assertFalse(page.use_selected.isChecked())
        self.assertFalse(page.use_selected.isEnabled())
        self.assertEqual(page.draft_edits, [])
        self.assertIsNone(page.snapshot_id)
        self.assertEqual(page._payload()["metadata"], {})

    def test_chart_click_publishes_physical_scope_without_programmatic_echo(self):
        from qt_shell.native_charts import VisualizationWorkspace
        page = VisualizationWorkspace(client=Client())
        page.data = {"snapshots": [{"unit": "N1", "outage": "N101", "tubes": []}]}
        page.snapshot.blockSignals(True)
        page.snapshot.addItem("N101", 0)
        page.snapshot.blockSignals(False)
        events = []
        page.scopeChanged.connect(events.append)
        page.select_tube(3)
        self.assertEqual(events, [])
        page._tube_selected(4)
        self.assertEqual(events, [{"site": "N", "unit": "1", "outage": "N101", "thimble": 4}])

    def test_fleet_aggregation_does_not_zero_fill_and_preserves_partial_flags(self):
        from qt_shell.native_charts import VisualizationWorkspace
        page = VisualizationWorkspace(client=Client())
        page.data = {"trends": [
            {"unit": "N1", "order": 1, "total": 20},
            {"unit": "N2", "order": 1, "total": 30, "partial": True},
            {"unit": "N1", "order": 2, "total": None},
            {"unit": "N2", "order": 3, "total": 10},
        ], "increments": [
            {"unit": "N1", "order": 2, "total": -3},
            {"unit": "N2", "order": 2, "total": None, "partial": True},
        ]}
        page.refresh_total()
        self.assertEqual(page.total.contract["groups"]["群厂汇总"], [(1, 50), (2, None), (3, 10)])
        self.assertEqual(page.total.contract["partial"]["群厂汇总"], {1, 2, 3})
        page.total_metric.setCurrentIndex(1)
        self.assertEqual(page.total.contract["groups"]["群厂汇总"], [(2, -3)])
        page.comparison_units = {"N2"}
        page.comparison_mode.setCurrentIndex(2)
        self.assertEqual(page.total.contract["groups"]["N2"], [(2, None)])

    def test_task_center_unread_counts_and_failed_read_retry(self):
        from qt_shell.native_notifications import NativeTaskCenter
        from PySide6.QtWidgets import QPushButton, QWidget
        class RetryClient(Client):
            def retry_read(self, key):
                self.retried = key
        client = RetryClient()
        parent = QWidget()
        from qt_shell.native_components import WorkspaceContext
        parent.context = WorkspaceContext(parent)
        parent.show()
        indicator = QPushButton(parent)
        center = NativeTaskCenter(client, indicator, parent)
        center.started("1", "GET", "/api/findings")
        center.finished("1", "GET", "/api/findings", "offline")
        self.assertEqual(center.unread, 1)
        center.show()
        self.assertEqual(center.unread, 0)
        center.history.setCurrentRow(0)
        self.click(center.retry)
        self.assertEqual(client.retried, "1")
        center.started("2", "POST", "/api/state")
        center.finished("2", "POST", "/api/state", "timeout")
        self.assertFalse(center.items["2"]["retryable"])
        center.filters.setCurrentIndex(3)
        self.assertEqual(center.history.count(), 0)
        center.filters.setCurrentIndex(1)
        self.assertEqual(center.history.count(), 2)
        self.assertTrue(center.dialog.parent() is parent)
        QTest.keyClick(center.filters, Qt.Key.Key_Escape)
        self.assertFalse(center.dialog.isVisible())

    def test_audit_json_can_locate_scope_and_invalid_tube_does_not_crash_context(self):
        from qt_shell.native_windows import JsonTablePage
        from qt_shell.native_components import WorkspaceContext
        self.assertEqual(JsonTablePage.record_scope(
            {"after_json": '{"outage":"N101","unit_id":1,"thimble_id":3}'}),
            {"site": "N", "unit": "1", "outage": "N101", "thimble": "3"})
        context = WorkspaceContext()
        context.set_scope({"site": "N", "unit": "1", "thimble": "bad"})
        self.assertEqual(context.scope["thimble"], "")

    def test_readonly_window_does_not_request_privileged_maintenance_endpoints(self):
        from qt_shell.native_windows import NativeMainWindow
        client = Client()
        window = NativeMainWindow(client, {"username": "viewer", "permissions": ["data.read"]})
        paths = [r[1].split("?")[0] for r in client.requests]
        for path in ("/api/backups", "/api/backup-policy", "/api/operation-logs",
                     "/api/security/events", "/api/security/exports", "/api/recycle-bin/list", "/api/logs/recent"):
            self.assertNotIn(path, paths)
        self.assertFalse(window.settings_dialog.save_policy.isEnabled())
        self.assertFalse(window.settings_dialog.restore_external.isEnabled())
        self.assertFalse(window.settings_dialog.create_rule.isEnabled())
        self.assertFalse(window.settings_dialog.deduplicate_button.isEnabled())

    def test_lifecycle_curve_never_connects_across_replacement_or_missing_outage(self):
        from qt_shell.native_charts import ChartPanel
        panel = ChartPanel()
        panel.lines("test", {"current": [(1, 10), (2, 20), (3, 0), (4, 5), (6, 8)]}, "",
                    breaks={"current": {3}})
        from PySide6.QtCharts import QLineSeries
        segments = [[point.x() for point in series.points()] for series in panel.view.chart().series()
                    if isinstance(series, QLineSeries)]
        self.assertEqual(segments, [[1, 2], [3, 4]])


if __name__ == "__main__":
    unittest.main()
