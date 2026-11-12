"""TRAE query contracts and native interactions against isolated data."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import native_test_env

os.environ.setdefault("THIMBLE_USER_DATA_DIR", native_test_env.test_data.name)
from src.backend import server
from openpyxl import Workbook, load_workbook
from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
    QTableWidget, QWidget, QWizard,
)
from qt_shell.native_windows import NativeMainWindow, FindingsModel, NativeStatePage, NativeAnalyticsPage, DataWorkbench
from qt_shell.native_import import ImportWizard, scan_excel_sources
from qt_shell.native_components import ReferencePlateMap, Preferences, TubeStateGrid
from test_native_workflows import Client


class QueryParityTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=native_test_env.test_data.name)
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        overrides = {"DB_PATH": self.root / "data.db", "DATA_DIR": self.root / "data",
                     "EXCEL_DIR": self.root / "excel", "REPORT_DIR": self.root / "reports"}
        patcher = patch.multiple(server, **overrides)
        patcher.start()
        self.addCleanup(patcher.stop)
        server.init_db()
        with server.connect() as db:
            db.executemany("""INSERT INTO findings(outage,site_code,unit_id,thimble_id,position,
                indication,percent,location,analysis,imported_at) VALUES(?,'N',1,?,?,?,?,?,?,'test')""", [
                ("N101", 1, "B10", "WAR", 12, "P1+1", "z"),
                ("N102", 1, "B10", "WAR", 35, "P1+1", "a"),
                ("N102", 2, "B2", "NDD", None, "", ""),
                ("N102", 3, "A1", "", None, "", ""),
                ("N102", 4, "B5", "WAR", 5, "P2", "b"),
            ])
            db.execute("""INSERT INTO tube_states(outage,unit_id,thimble_id,state,offset_mm,
                events_json,source,updated_at) VALUES('N101',1,1,'plugged',0,'["plugged"]','test','test')""")

    def test_detection_and_inherited_maintenance_are_independent(self):
        result = server.query_findings({"outage": ["N102"], "detection_status": ["war"],
                                       "maintenance_status": ["plugged"]})
        self.assertEqual(result["total"], 1)
        row = result["items"][0]
        self.assertEqual((row["thimble_id"], row["display_conclusion"]), (1, "WAR"))
        self.assertIn("plugged", row["maintenance_statuses"])
        self.assertIn("历史", row["maintenance_status_source"])
        self.assertEqual([r["thimble_id"] for r in result["core_items"]], [1])

    def test_unrecorded_is_not_normal(self):
        result = server.query_findings({"outage": ["N102"], "maintenance_status": ["unrecorded"]})
        self.assertEqual({row["thimble_id"] for row in result["items"]}, {2, 3, 4})
        self.assertEqual(server.query_findings({"maintenance_status": ["normal"]})["total"], 0)

    def test_auto_ndd_switch_never_changes_stored_conclusion(self):
        self.assertEqual(server.query_findings({"detection_status": ["blank"]})["total"], 0)
        result = server.query_findings({"detection_status": ["blank"], "auto_ndd": ["0"]})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["display_conclusion"], "")
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT indication FROM findings WHERE thimble_id=3").fetchone()[0], "")

    def test_sort_precedes_pagination_and_missing_is_last_in_both_orders(self):
        ascending = server.query_findings({"sort": ["position"], "size": ["1"], "page": ["2"]})
        self.assertEqual(ascending["items"][0]["position"], "B2")
        for direction in ("asc", "desc"):
            rows = server.query_findings({"sort": ["percent"], "order": [direction]}, all_rows=True)["items"]
            present = [row["percent"] for row in rows if row["percent"] is not None]
            self.assertEqual(present, sorted(present, reverse=direction == "desc"))
            self.assertIsNone(rows[-1]["percent"])

    def test_ledger_keeps_detection_maintenance_and_sort_scope(self):
        result = server.export_data_ledger({"outage": "N102", "detection_status": "war",
                                           "maintenance_status": "plugged", "sort": "percent", "order": "desc"})
        self.assertEqual(result["rows"], 1)
        book = load_workbook(result["file_path"], read_only=True)
        try:
            rows = list(book["综合台账"].values)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[1][3], 1)
            self.assertEqual(rows[1][7], 35)
        finally:
            book.close()

    def test_column_filter_treats_sql_characters_as_literal(self):
        self.assertEqual(server.query_findings({"column_analysis": ["' OR 1=1 --"]})["total"], 0)

    def test_overview_exposes_other_conclusions_and_analyst_candidates(self):
        with server.connect() as db:
            db.execute("""INSERT INTO findings(outage,site_code,unit_id,thimble_id,indication,analyst,imported_at)
                          VALUES('N102','N',1,5,'NOS','Analyst Alpha','test')""")
        overview = server.overview()
        self.assertIn("NOS", overview["indications"])
        self.assertIn("Analyst Alpha", overview["analysts"])
        filtered = server.query_findings({"detection_status": ["nos"]})
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["items"][0]["indication"], "NOS")

    def test_excel_changed_after_preflight_is_rejected_before_findings_write(self):
        path = self.root / "N103.xlsx"
        book = Workbook()
        sheet = book.active
        sheet.title = "N103"
        sheet.append(["通道编号", "三字码", "幅值"])
        sheet.append([1, "WAR", 1.2])
        book.save(path)
        preflight = server.import_excel_file(str(path), "check")
        sheet.cell(2, 3, 9.8)
        book.save(path)
        book.close()
        with self.assertRaisesRegex(ValueError, "来源文件已变化"):
            server.import_excel_file(str(path), "review", expected_sha256=preflight["source_sha256"])
        self.assertEqual(server.query_findings({"outage": ["N103"]})["total"], 0)


class NativeParityTests(unittest.TestCase):
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

    def test_controls_issue_server_sort_and_all_filters_and_reset(self):
        client = Client()
        window = NativeMainWindow(client, {"username": "test", "permissions": ["data.read"]})
        page = window.workbench
        page.detection_status.setCurrentIndex(page.detection_status.findData("war"))
        page.maintenance_status.setCurrentIndex(page.maintenance_status.findData("plugged"))
        page.column_filters["analysis"] = "A&B"
        page.page = 4
        page.sort_column(FindingsModel.fields.index("percent"))
        path = client.requests[-1][1]
        for text in ("page=1", "detection_status=war", "maintenance_status=plugged", "sort=percent", "column_analysis=A%26B"):
            self.assertIn(text, path)
        page.reset_query()
        self.assertFalse(page.column_filters)
        self.assertEqual(page.sort_field, "")
        self.assertEqual(page.detection_status.currentData(), "")

    def test_workbench_source_conclusions_and_analyst_completer_refresh_without_duplicates(self):
        page = DataWorkbench(Client(), {"permissions": ["data.read"]})
        overview = {"stats": {}, "indications": ["WAR", "NOS", "nos", "NONE", "/"], "analysts": ["Alpha", "Beta"]}
        page._on_overview(overview, None)
        page.detection_status.setCurrentIndex(page.detection_status.findData("nos"))
        page._on_overview(overview, None)
        self.assertEqual(page.detection_status.count(), 5)
        self.assertEqual(page.detection_status.currentData(), "nos")
        self.assertEqual(page.analyst.completer().model().stringList(), ["Alpha", "Beta"])
        page.apply_filters()
        self.assertIn("detection_status=nos", page.client.requests[-1][1])

    def test_narrow_workbench_keeps_table_readable_and_map_reachable(self):
        page = DataWorkbench(Client(), {"permissions": ["data.read"]})
        page.resize(1024, 680)
        page.show()
        self.app.processEvents()
        self.assertGreaterEqual(page.table.viewport().height(), 170)
        self.assertGreater(page.scroll.verticalScrollBar().maximum(), 0)
        page.scroll.ensureWidgetVisible(page.plate)
        self.app.processEvents()
        self.assertGreaterEqual(page.plate.height(), 330)
        self.assertTrue(page.plate.visibleRegion().boundingRect().height() >= 300)
        page.resize(1480, 940)
        self.app.processEvents()
        self.assertEqual(page.scroll.verticalScrollBar().maximum(), 0)

    def test_preferences_autosave_and_apply_ndd_immediately(self):
        window = NativeMainWindow(Client(), {"username": "test", "permissions": ["data.read"]})
        settings = window.settings_dialog
        previous = settings.auto_ndd.isChecked()
        settings.auto_ndd.setChecked(not previous)
        settings.notification_duration.setCurrentIndex(settings.notification_duration.findData(5000))
        QTest.qWait(260)
        self.assertEqual(window.workbench.auto_ndd, not previous)
        self.assertEqual(Preferences().values["notification_duration"], 5000)
        self.assertEqual(settings.save_status.text(), "偏好已保存")

    def test_native_login_reveal_remember_and_lock_feedback(self):
        from qt_shell.native_login import NativeLoginWindow
        from PySide6.QtWidgets import QLineEdit
        client = Client()
        login = NativeLoginWindow(client)
        login._on_status({"initialized": True}, None)
        login.show()
        login.username.setText("remembered")
        login.password.setText("SecretPass@2026")
        self.assertEqual(login.strength.value(), 4)
        login.password_reveal.setChecked(True)
        self.assertEqual(login.password.echoMode(), QLineEdit.EchoMode.Normal)
        login.remember.setChecked(True)
        login._submit()
        self.assertTrue(client.requests[-1][2]["remember"])
        login._on_auth({"user": {"username": "remembered"}}, None)
        self.assertEqual(login.password.text(), "")
        self.assertEqual(login.password.echoMode(), QLineEdit.EchoMode.Password)
        self.assertEqual(Preferences().values["login_username"], "remembered")
        self.assertNotIn("SecretPass", Preferences().path.read_text(encoding="utf-8"))
        login._on_auth({"locked_seconds": 120}, "locked")
        self.assertFalse(login.submit.isEnabled())
        pending = len(client.requests)
        login._submit()
        self.assertEqual(len(client.requests), pending)
        login._lock_until = 0
        login._update_lock()
        self.assertTrue(login.submit.isEnabled())

    def test_state_grid_drag_selects_and_deselects_each_crossed_tube(self):
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent
        grid = TubeStateGrid()
        grid.resize(700, 390)
        grid.show()
        self.app.processEvents()
        grid.multiselect = True
        first, second = (grid.hit_regions[tube].center().toPoint() for tube in (1, 2))
        QTest.mousePress(grid, Qt.MouseButton.LeftButton, pos=first)
        drag = QMouseEvent(QEvent.Type.MouseMove, QPointF(second), QPointF(grid.mapToGlobal(second)),
                           Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(grid, drag)
        QTest.mouseRelease(grid, Qt.MouseButton.LeftButton, pos=second)
        self.assertEqual(grid.selected, {1, 2})
        QTest.mousePress(grid, Qt.MouseButton.LeftButton, pos=first)
        QApplication.sendEvent(grid, drag)
        QTest.mouseRelease(grid, Qt.MouseButton.LeftButton, pos=second)
        self.assertEqual(grid.selected, set())

    def test_hidden_offset_does_not_block_simple_state_and_recognized_unsigned_needs_confirmation(self):
        page = NativeStatePage(Client(), {"permissions": ["state.write"]})
        page.current = {"outage": "N101", "unit_id": 1, "thimble_id": 1, "state": "shifted",
                        "events": ["shifted"], "offset_mm": -12, "note": ""}
        page._populate_editor()
        page.state.setCurrentIndex(page.state.findData("normal"))
        self.assertEqual(page._editor_payload()["offset_mm"], 0)
        page.note.setText("original description")
        page._note_recognized(page.current, "original description", {"rows": [{
            "state": "shifted", "events": ["shifted"], "offset_mm": None, "unsigned_offset_mm": 42}],
            "requires_direction": True}, None)
        with self.assertRaisesRegex(ValueError, "正负号"):
            page._editor_payload()
        page.default_direction.setCurrentIndex(page.default_direction.findData("-1"))
        page._use_default_offset()
        self.assertEqual(page.offset.text(), "-42")
        self.assertEqual(page._editor_payload()["offset_mm"], -42)

    def test_reference_grid_has_exactly_50_odd_even_pairs(self):
        plate = ReferencePlateMap()
        plate.resize(640, 650)
        plate.show()
        self.app.processEvents()
        plate.grab()
        self.assertEqual(len(plate.hit_regions), 50)
        self.assertEqual({odd for odd, _ in plate.hit_regions}, set(range(1, 51)))
        self.assertEqual({even for _, even in plate.hit_regions}, set(range(1, 51)))
        for (odd, even), rect in plate.hit_regions.items():
            self.assertEqual(plate._hit(QPointF(rect.center().x() - 1, rect.center().y()))[:2], (odd, 1))
            self.assertEqual(plate._hit(QPointF(rect.center().x() + 1, rect.center().y()))[:2], (even, 0))

    def test_header_is_inline_saved_and_maintenance_column_is_readonly(self):
        window = NativeMainWindow(Client(), {"username": "test", "permissions": ["data.read"]})
        window.show()
        window.nav.setCurrentIndex(3)
        report = window.stack.widget(4)
        report.edit_header()
        self.app.processEvents()
        self.assertTrue(report.header_panel.isVisible())
        report.header_edits["reportPlant"].setText("test plant")
        self.assertTrue(report._save_inline_header())
        self.assertEqual(report._load_saved_header()["reportPlant"], "test plant")
        model = window.workbench.model
        model.editable = True
        model.replace([{"id": 1, "maintenance_statuses": ["plugged", "shifted"]}])
        index = model.index(0, model.fields.index("maintenance_status"))
        self.assertFalse(model.flags(index) & Qt.ItemFlag.ItemIsEditable)
        self.assertEqual(model.data(index), "堵管 · 移位")

    def test_state_current_effective_views_keep_unrecorded_distinct(self):
        page = NativeStatePage(Client(), {"permissions": ["state.write"]})
        page._state_scope = {"site": "N", "unit": "1", "outage": "N102"}
        page.all_rows = [{"outage": "N102", "unit_id": 1, "thimble_id": 2,
                          "state": "normal", "events": []}]
        page._scope_items = [{"thimble_id": 1, "state": "plugged", "last_maintenance": "N101",
                              "maintained": False, "current_events": [], "state_label": "堵管 · 移位",
                              "plugged": True, "shifted": True, "cumulative_offset_mm": -12},
                             {"thimble_id": 2, "state": "normal", "last_maintenance": "N102", "maintained": True}]
        self.assertEqual(page.grid_mode.currentIndex(), 1)
        page.grid_mode.setCurrentIndex(0)
        page._show_filtered()
        self.assertNotIn(1, page.plate.rows)
        self.assertEqual(page.summary_buttons["unmaintained"].text(), "未维护  49")
        page.grid_mode.setCurrentIndex(1)
        self.assertEqual(page.plate.rows[1]["state"], "plugged")
        self.assertFalse(page.plate.rows[1]["maintained"])
        self.assertEqual(page.plate.rows[1]["events"], ["plugged", "shifted"])
        self.assertEqual(page.plate.rows[1]["offset_mm"], -12)
        page._set_state_filter("plugged")
        self.assertEqual(page.model.rowCount(), 0)
        self.assertIn(1, page.plate.rows)

    def test_batch_form_is_independent_and_preserves_preview_commit_options(self):
        client = Client()
        page = NativeStatePage(client, {"permissions": ["state.write"]})
        page.show()
        page._state_scope = {"site": "N", "unit": "1", "outage": "N101"}
        page.all_rows = [{"outage": "N101", "unit_id": 1, "thimble_id": tube,
                          "state": "shifted", "events": ["shifted"], "offset_mm": offset,
                          "note": f"evidence {tube}", "source": f"source {tube}", "updated_at": f"v{tube}"}
                         for tube, offset in ((1, -12), (2, 42))]
        page.current = page.all_rows[0]
        page._populate_editor()
        page.batch_mode.setChecked(True)
        self.assertTrue(page.single_editor.isHidden())
        self.assertTrue(page.batch_editor.isVisible())
        self.assertEqual(page.plate.selected, {1})
        page.plate.selected = {1, 2}
        page.batch_state.setCurrentIndex(page.batch_state.findData("shifted"))
        self.assertEqual(page.batch_offset.text(), "")
        page.batch_offset.setText("+7")
        page._batch_offset_edited()
        page.plate.selected = {1}
        page._batch_selection_changed()
        self.assertEqual(page.batch_offset.text(), "+7")
        page.batch_state.setCurrentIndex(page.batch_state.findData("plugged"))
        page.batch_note.setPlainText("batch evidence")
        page._apply_selected_states()
        preview = client.requests[-1]
        self.assertEqual(preview[2]["mode"], "append")
        self.assertTrue(preview[2]["bulk_edit"])
        self.assertEqual(preview[2]["rows"][0]["events"], ["plugged"])
        self.assertEqual(preview[2]["rows"][0]["offset_mm"], 0)
        self.assertEqual(preview[2]["rows"][0]["note"], "batch evidence")
        self.assertEqual(preview[2]["rows"][0]["source"], "")
        self.assertEqual(preview[2]["rows"][0]["expected_updated_at"], "v1")
        self.assertFalse(page.batch_mode.isEnabled())
        from PySide6.QtWidgets import QDialog
        with patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Accepted):
            preview[3]({"affected": 1, "revision": "revision", "rows": [
                {"thimble_id": 1, "before": {}, "after": {}}]}, None)
        commit = client.requests[-1]
        self.assertEqual(commit[1], "/api/states/batch")
        self.assertEqual(commit[2], {**preview[2], "revision": "revision", "confirmed": True})
        with patch.object(QMessageBox, "warning"):
            commit[3](None, "concurrent modification")
        self.assertTrue(page.batch_mode.isEnabled())
        self.assertEqual(page.plate.selected, {1})
        self.assertEqual(page.batch_note.toPlainText(), "batch evidence")

    def test_batch_common_offset_never_copies_to_unshifted_or_unknown_tube(self):
        page = NativeStatePage(Client(), {"permissions": ["state.write"]})
        page._state_scope = {"site": "N", "unit": "1", "outage": "N101"}
        page.all_rows = [{"outage": "N101", "unit_id": 1, "thimble_id": tube,
                          "state": "shifted", "events": ["shifted"], "offset_mm": -12}
                         for tube in (1, 2)]
        page.batch_mode.setChecked(True)
        page.plate.selected = {1, 2}
        page.batch_state.setCurrentIndex(page.batch_state.findData("shifted"))
        self.assertEqual(page.batch_offset.text(), "-12")
        page.plate.selected.add(3)
        page._batch_selection_changed()
        self.assertEqual(page.batch_offset.text(), "")
        page.plate.selected = {1, 2}
        page.all_rows[1]["offset_mm"] = None
        page.all_rows[1]["unsigned_offset_mm"] = 12
        page._batch_selection_changed()
        self.assertEqual(page.batch_offset.text(), "")

    def test_single_composite_mode_rejects_incomplete_and_projects_events(self):
        page = NativeStatePage(Client(), {"permissions": ["state.write"]})
        page.current = {"outage": "N101", "unit_id": 1, "thimble_id": 1, "state": "normal"}
        page._populate_editor()
        page.state.setCurrentIndex(page.state.findData("composite"))
        with self.assertRaisesRegex(ValueError, "至少选择两项"):
            page._editor_payload()
        page.event_checks["shifted"].setChecked(True)
        page.event_checks["plugged"].setChecked(True)
        page.offset.setText("-12")
        self.assertEqual(page.state.currentData(), "composite")
        self.assertEqual(page._editor_payload()["state"], "plugged")
        self.assertEqual(set(page._editor_payload()["events"]), {"plugged", "shifted"})

    def test_refresh_preserves_state_draft_and_rejects_stale_response(self):
        client = Client()
        page = NativeStatePage(client, {"permissions": ["state.write"]})
        original = {"outage": "N101", "unit_id": 1, "thimble_id": 1, "state": "shifted",
                    "events": ["shifted"], "offset_mm": -12, "note": "source", "updated_at": "v1"}
        page.current = original
        page._populate_editor()
        page.note.setText("unsaved")
        page.load()
        first = client.requests[-1][3]
        page.load()
        second = client.requests[-1][3]
        second({"items": [{**original, "note": "changed elsewhere", "updated_at": "v2"}]}, None)
        first({"items": []}, None)
        self.assertEqual(page.note.text(), "unsaved")
        self.assertEqual(page.current["updated_at"], "v1")
        self.assertEqual(len(page.all_rows), 1)
        self.assertEqual(page._editor_payload()["expected_updated_at"], "v1")

    def test_state_scope_clears_editor_and_external_tube_selects_actual_record(self):
        page = NativeStatePage(Client(), {"permissions": ["state.write"]})
        page.show()
        self.assertTrue(page.offset.isHidden())
        self.assertTrue(page.replacement_stage.isHidden())
        self.assertFalse(page.save.isEnabled())
        scope = {"site": "N", "unit": "1", "outage": "N101"}
        page._filter_scope(scope)
        page.all_rows = [{"outage": "N101", "unit_id": 1, "thimble_id": 2,
                          "state": "plugged", "events": ["plugged"], "note": "original"}]
        page.set_workspace_scope({**scope, "thimble": "2"})
        self.assertEqual(page.current["thimble_id"], 2)
        self.assertEqual(page.note.text(), "original")
        self.assertTrue(page.save.isEnabled())
        page._filter_scope({**scope, "outage": "N102"})
        self.assertIsNone(page.current)
        self.assertEqual(page.editor_tube.value(), 0)
        self.assertEqual(page.note.text(), "")
        self.assertFalse(page.save.isEnabled())

    def test_state_summary_lists_missing_tubes_and_can_open_their_editor(self):
        client = Client()
        page = NativeStatePage(client, {"permissions": ["state.write"]})
        page.show()
        page._state_scope = {"site": "N", "unit": "1", "outage": "N101"}
        page._show_state_summary("unmaintained")
        reply = client.requests[-1][3]
        reply({"items": [{"outage": "N101", "unit_id": 1, "thimble_id": 1, "state": "normal"}]}, None)
        dialog = page.summary_dialog
        table = dialog.findChild(QTableWidget)
        self.assertEqual(table.rowCount(), 49)
        self.assertEqual(table.item(0, 0).text(), "#2")
        QTest.mouseClick(table.cellWidget(0, 5), Qt.MouseButton.LeftButton)
        self.assertEqual(page.current["thimble_id"], 2)
        self.assertTrue(page.save.isEnabled())
        # A response after close must not repopulate a dismissed summary.
        reply({"items": []}, None)
        self.assertEqual(table.rowCount(), 49)

    def test_saved_state_editor_reselects_authoritative_record(self):
        client = Client()
        page = NativeStatePage(client, {"permissions": ["state.write"]})
        page.current = {"outage": "N101", "unit_id": 1, "thimble_id": 1,
                        "state": "normal", "events": [], "updated_at": "v1"}
        page._populate_editor()
        page.event_checks["plugged"].setChecked(True)
        page._save()
        with patch.object(QMessageBox, "information"):
            client.requests[-1][3]({"ok": True}, None)
        client.requests[-1][3]({"items": [{"outage": "N101", "unit_id": 1, "thimble_id": 1,
                                         "state": "plugged", "events": ["plugged"], "updated_at": "v2",
                                         "offset_mm": 0, "note": "persisted"}]}, None)
        self.assertEqual(page.state.currentData(), "plugged")
        self.assertTrue(page.event_checks["plugged"].isChecked())
        self.assertEqual(page.note.text(), "persisted")
        self.assertEqual(page.current["updated_at"], "v2")
        self.assertFalse(page._editor_dirty())

    def test_inline_state_note_keeps_compound_source_and_original_version(self):
        client = Client()
        page = NativeStatePage(client, {"permissions": ["state.write"]})
        row = {"outage": "N101", "unit_id": 1, "thimble_id": 1, "state": "plugged",
               "events": ["plugged", "shifted"], "offset_mm": -12, "note": "original",
               "source": "plant register", "replacement_stage": "unknown", "updated_at": "v1"}
        page.all_rows = [row]
        page._show_filtered()
        index = page.model.index(0, page.model.fields.index("note"))
        self.assertTrue(page.model.setData(index, "revised note"))
        page._inline_state_action(0, "save")
        payload = client.requests[-1][2]
        self.assertEqual(payload["events"], ["plugged", "shifted"])
        self.assertEqual(payload["source"], "plant register")
        self.assertEqual(payload["offset_mm"], -12)
        self.assertEqual(payload["expected_updated_at"], "v1")
        client.requests[-1][3](None, "concurrent edit")
        page.all_rows = [{**row, "updated_at": "v2"}]
        page._show_filtered()
        self.assertEqual(page.model.data(index), "revised note")
        page._inline_state_action(0, "save")
        self.assertEqual(client.requests[-1][2]["expected_updated_at"], "v1")

    def test_state_pagination_keeps_drafts_and_clears_checked_rows_on_page_change(self):
        page = NativeStatePage(Client(), {"permissions": ["state.write"]})
        page.all_rows = [{"outage": "N101" if tube <= 50 else "N102", "unit_id": 1,
                          "thimble_id": (tube - 1) % 50 + 1, "state": "normal",
                          "events": [], "offset_mm": 0, "note": "", "updated_at": "v1"}
                         for tube in range(1, 61)]
        page._show_filtered()
        self.assertEqual(page.model.rowCount(), 50)
        note = page.model.index(0, page.model.fields.index("note"))
        page.model.setData(note, "draft across pages")
        page.model.setData(page.model.index(0, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
        page._change_record_page(1)
        self.assertEqual(page.model.rowCount(), 10)
        page._change_record_page(-1)
        self.assertEqual(page.model.data(page.model.index(0, page.model.fields.index("note"))), "draft across pages")
        self.assertEqual(page.model.data(page.model.index(0, 0), Qt.ItemDataRole.CheckStateRole), Qt.CheckState.Unchecked)
        self.assertFalse(page.model.flags(page.model.index(0, page.model.fields.index("offset_mm")))
                         & Qt.ItemFlag.ItemIsEditable)

    def test_manual_scopes_survive_overview_refresh(self):
        page = NativeStatePage(Client())
        page._loaded({"items": [], "scopes": [{"site": "LF", "outage": "LF198", "unit_id": 1}]}, None)
        page.scope_bar.set_scope({"site": "LF", "unit": "1", "outage": "LF198"})
        page.scope_bar._loaded({"combinations": [{"site": "N", "unit_id": 1, "outage": "N101"}]}, None)
        self.assertEqual(page.scope_bar.values()["outage"], "LF198")

    def test_maintenance_list_filters_independently_and_keeps_hidden_drafts(self):
        page = NativeStatePage(Client(), {"permissions": ["state.write"]})
        rows = [
            {"outage": "N101", "unit_id": 1, "thimble_id": 1, "state": "plugged",
             "events": ["plugged", "shifted"], "note": "Mixed Case", "source": "Register A", "updated_at": "v1"},
            {"outage": "N102", "unit_id": 1, "thimble_id": 2, "state": "normal", "events": []},
            {"outage": "H201", "unit_id": 2, "thimble_id": 1, "state": "replaced", "events": ["replaced"]},
        ]
        page._loaded({"items": rows}, None)
        page.set_workspace_scope({"site": "N", "unit": "1", "outage": "N102"})
        self.assertEqual(page.model.rowCount(), 3)
        page.model.setData(page.model.index(0, page.model.fields.index("note")), "unsaved evidence")
        page.model.setData(page.model.index(0, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
        page.record_scope.site.setCurrentIndex(page.record_scope.site.findData("H"))
        self.assertEqual([row["outage"] for row in page.model.rows], ["H201"])
        self.assertEqual(page._state_scope["outage"], "N102")
        self.assertFalse(page.model.selected)
        page._clear_record_filters()
        self.assertEqual(page.model.data(page.model.index(0, page.model.fields.index("note"))), "unsaved evidence")
        page.record_type.setCurrentIndex(page.record_type.findData("composite"))
        self.assertEqual(page.model.rowCount(), 1)
        self.assertEqual(page.record_categories.currentIndex(), page.record_type.currentIndex())
        page.filter_text.setText("REGISTER a")
        self.assertEqual(page.model.rowCount(), 1)
        page._clear_record_filters()
        page.record_scope.site.setCurrentIndex(page.record_scope.site.findData("N"))
        page._latest_record_scope()
        self.assertEqual(page.record_scope.values()["outage"], "N102")
        self.assertEqual([row["thimble_id"] for row in page.model.rows], [2])

    def test_selecting_independently_filtered_record_updates_editor_scope(self):
        page = NativeStatePage(Client(), {"permissions": ["state.write"]})
        page._loaded({"items": [{"outage": "N101", "unit_id": 1, "thimble_id": 1,
                                "state": "plugged", "events": ["plugged"]},
                               {"outage": "H201", "unit_id": 2, "thimble_id": 4,
                                "state": "normal", "events": []}]}, None)
        page._select(page.model.index(1, 0))
        self.assertEqual(page._state_scope, {"site": "H", "unit": "2", "outage": "H201"})
        self.assertEqual(page.current["thimble_id"], 4)
        self.assertEqual(page.model.rowCount(), 2)

    def test_selecting_record_broadcasts_scope_and_confirms_dirty_editor_once(self):
        window = NativeMainWindow(Client(), {"permissions": ["data.read", "state.write"]})
        page = window.stack.widget(1)
        page._loaded({"items": [{"outage": "N101", "unit_id": 1, "thimble_id": 1,
                                "state": "normal", "events": []},
                               {"outage": "H201", "unit_id": 2, "thimble_id": 4,
                                "state": "normal", "events": []}]}, None)
        page._select(page.model.index(0, 0))
        page.note.setText("unsaved")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard) as question:
            page._select(page.model.index(1, 0))
        self.assertEqual(question.call_count, 1)
        self.assertEqual(window.context.scope["outage"], "H201")
        self.assertEqual(page.current["thimble_id"], 4)

    def test_workbench_field_tabs_and_direct_recycle_route(self):
        window = NativeMainWindow(Client(), {"permissions": ["data.read", "data.delete"]})
        page = window.workbench
        field = page.model.fields.index("degrees")
        self.assertTrue(page.table.isColumnHidden(field))
        page.field_mode.setCurrentIndex(1)
        self.assertFalse(page.table.isColumnHidden(field))
        QTest.mouseClick(page.recycle_button, Qt.MouseButton.LeftButton)
        self.assertTrue(window.settings_dialog.isVisible())
        self.assertEqual(window.maintenance.tabs.currentWidget(), window.maintenance.recycle)
        viewer = DataWorkbench(Client(), {"permissions": ["data.read"]})
        self.assertFalse(viewer.recycle_button.isEnabled())

    def test_overview_resets_absent_counts_and_escapes_chart_categories(self):
        from PySide6.QtCharts import QBarCategoryAxis
        from qt_shell.native_charts import VisualizationWorkspace
        page = VisualizationWorkspace()
        page.data = {"snapshots": [{"unit": "N1", "outage": "N101", "order": 1, "tubes": [
            {"tube": 1, "position": "J10", "coverage": "defect", "max_depth": 42,
             "state_badges": ["shifted"], "state_recorded": True},
            {"tube": 2, "coverage": "incomplete"}, {"tube": 3, "coverage": "missing"},
            {"tube": 4, "coverage": "NDD"}]}]}
        page.refresh_overview()
        self.assertEqual(page.summary_labels["war"].text(), "1")
        self.assertEqual(page.summary_labels["review"].text(), "1")
        self.assertIn("42%", page.insight_buttons["peak"].text())
        self.assertIn("J10", page.insight_buttons["position"].text())
        page.open_overview_insight("maintenance")
        self.assertEqual(page.insight_dialog.findChild(QTableWidget).rowCount(), 1)
        axis = next(axis for axis in page.overview.view.chart().axes() if isinstance(axis, QBarCategoryAxis))
        self.assertEqual(axis.categories()[-1], "NDD")
        self.assertTrue(any("&lt;" in label for label in axis.categories()))
        self.assertTrue(page.overview.view.chart()._bar_value_labels)
        page.data = {"snapshots": [{"unit": "H2", "outage": "H201", "order": 1,
                                   "tubes": [{"tube": 1, "coverage": "NDD"}]}]}
        page.refresh_overview()
        for key in ("war", "review", "missing"):
            self.assertEqual(page.summary_labels[key].text(), "0")
        self.assertEqual(page.summary_labels["ndd"].text(), "1")
        self.assertFalse(page.insight_buttons["peak"].isEnabled())
        page.data = {"snapshots": []}
        page.refresh_overview()
        self.assertEqual(page.summary_labels["ndd"].text(), "0")
        self.assertEqual(page.summary_labels["coverage"].text(), "0%")

    def test_overview_separates_zero_war_from_ndd_and_threshold_is_strict(self):
        from qt_shell.native_charts import VisualizationWorkspace
        page = VisualizationWorkspace()
        page.data = {"snapshots": [{"unit": "N1", "outage": "N101", "order": 1, "tubes": [
            {"tube": 1, "position": "J10", "coverage": "defect", "max_depth": 0},
            {"tube": 2, "position": "N8", "coverage": "NDD", "max_depth": 0},
            {"tube": 3, "position": "J10", "coverage": "defect", "max_depth": 40},
            {"tube": 4, "position": "N8", "coverage": "defect", "max_depth": 41}]}]}
        page.refresh_overview()
        values = {label: count for label, count, _ in page.overview.contract["values"]}
        self.assertEqual(values["NDD"], 1)
        self.assertEqual(values["原记录 0%"], 1)
        self.assertFalse(any("无检测记录" == label for label in values))
        QTest.mouseClick(page.heat_presets.button(40), Qt.MouseButton.LeftButton)
        self.assertEqual(page.heat_threshold.value(), 40)
        self.assertEqual(page.heatmap.counts, {"N8": 1})
        page.heat_threshold.setValue(39)
        self.assertFalse(any(preset.isChecked() for preset in page.heat_presets.buttons()))
        self.assertEqual(page.heatmap.counts, {"J10": 1, "N8": 1})

    def test_overview_unit_history_keeps_global_gaps_and_source_notes(self):
        from qt_shell.native_charts import VisualizationWorkspace
        page = VisualizationWorkspace()
        current = {"unit": "N1", "outage": "N103", "order": 3, "tubes": [
            {"tube": 1, "coverage": "NDD", "state_recorded": True}]}
        source_note = "Original\nmaintenance evidence"
        page.data = {"snapshots": [current], "units": [{"code": "N1", "missing_outages": ["N102"],
            "detection_outages": ["N103"], "history": [
                {"outage": "N101", "order": 1, "records": 0, "counts": {"missing": 50},
                 "state_sources": [{"tube": 1, "outage": "N101", "label": "移位", "note": source_note,
                                    "source": "Original register", "warnings": ["Direction pending"]}]},
                {"outage": "N103", "order": 3, "records": 1, "counts": {"NDD": 1}}]}]}
        page.refresh_overview()
        overview = page.unit_overview
        self.assertEqual(set(overview.groups), {"N"})
        self.assertEqual(set(overview.rows), {"N1"})
        history = overview.disclosures[("unit", "N1")]
        self.assertIsNone(history.body)
        QTest.mouseClick(history.header, Qt.MouseButton.LeftButton)
        labels = "\n".join(label.text() for label in history.body.findChildren(QLabel))
        self.assertIn("本库编号缺口", labels)
        self.assertIn("N102", labels)
        self.assertIn("仅有维护", labels)
        self.assertIn("N101", labels)
        outage = overview.disclosures[("outage", "N1", "N101")]
        self.assertIsNone(outage.body)
        QTest.mouseClick(outage.header, Qt.MouseButton.LeftButton)
        sources = overview.disclosures[("sources", "N1", "N101")]
        self.assertIsNone(sources.body)
        QTest.mouseClick(sources.header, Qt.MouseButton.LeftButton)
        self.assertEqual(sources.body.item(0, 3).text(), source_note)
        updated = dict(page.data)
        page.data = updated
        page.refresh_overview()
        self.assertTrue(overview.disclosures[("unit", "N1")].header.isChecked())
        self.assertTrue(overview.disclosures[("outage", "N1", "N101")].header.isChecked())
        self.assertTrue(overview.disclosures[("sources", "N1", "N101")].header.isChecked())
        page.open_unit_history("N1", "N101")
        table = page.unit_history_dialog.findChild(QTableWidget)
        self.assertEqual(table.item(0, 3).text(), source_note)
        self.assertEqual(table.item(0, 4).text(), "Original register")
        self.assertEqual(table.item(0, 5).text(), "Direction pending")
        page.snapshot.addItem("N1 N103", 0)
        page.open_unit_overview("N1", "N103")
        self.assertEqual(page.currentIndex(), 2)

    def test_multisite_filter_keeps_coded_units_and_survives_navigation_and_reload(self):
        from urllib.parse import parse_qs, urlsplit
        client = Client()
        window = NativeMainWindow(client, {"username": "viewer", "permissions": ["data.read"]})
        page = window.stack.widget(3)
        page.scope_bar._loaded({"combinations": [
            {"site": "N", "unit_id": 1, "outage": "N101"},
            {"site": "H", "unit_id": 1, "outage": "H101"},
            {"site": "D", "unit_id": 1, "outage": "D120"}]}, None)
        QTest.mouseClick(page.site_coverage_buttons["N"], Qt.MouseButton.LeftButton)
        QTest.mouseClick(page.site_coverage_buttons["H"], Qt.MouseButton.LeftButton)
        self.assertEqual(page.scope_bar.selected_sites, {"N", "H"})
        analysis_request = next(request for request in reversed(client.requests)
                                if request[1].startswith("/api/analysis/visualization?"))
        query = parse_qs(urlsplit(analysis_request[1]).query)
        self.assertEqual(query["sites"], ["H,N"])
        self.assertEqual([page.scope_bar.unit.itemData(i) for i in range(page.scope_bar.unit.count())], ["", "H1", "N1"])
        self.assertFalse(page.site_coverage_buttons[""].isChecked())
        self.assertTrue(page.site_coverage_buttons["N"].isChecked())
        window.nav.setCurrentIndex(0)
        window.nav.setCurrentIndex(2)
        self.assertEqual(page.scope_bar.selected_sites, {"N", "H"})
        page.scope_bar.reload()
        client.requests[-1][3]({"combinations": [
            {"site": "N", "unit_id": 1, "outage": "N101"},
            {"site": "H", "unit_id": 1, "outage": "H101"}]}, None)
        self.assertEqual(page.scope_bar.selected_sites, {"N", "H"})
        page.scope_bar.unit.setCurrentIndex(page.scope_bar.unit.findData("H1"))
        analysis_request = next(request for request in reversed(client.requests)
                                if request[1].startswith("/api/analysis/visualization?"))
        query = parse_qs(urlsplit(analysis_request[1]).query)
        self.assertEqual(query["unit"], ["H1"])
        self.assertEqual(query["sites"], ["H,N"])
        self.assertEqual(window.context.scope["site"], "H")
        self.assertEqual(window.context.scope["unit"], "1")
        page.scope_bar.reset.click()
        self.assertEqual(page.scope_bar.selected_sites, set())
        self.assertEqual(page.scope_bar.values(), {"site": "", "unit": "", "outage": ""})

    def test_raw_history_paginates_keeps_original_conclusions_and_ignores_late_responses(self):
        from urllib.parse import parse_qs, urlsplit
        from qt_shell.native_charts import VisualizationWorkspace
        client = Client()
        page = VisualizationWorkspace(client=client)
        page.open_unit_records("N1", "N101")
        request = client.requests[-1]
        query = parse_qs(urlsplit(request[1]).query)
        self.assertEqual(query["auto_ndd"], ["0"])
        self.assertEqual(query["raw"], ["1"])
        self.assertEqual(query["site"], ["N"])
        request[3]({"total": 201, "items": [{"thimble_id": 1, "indication": "", "analysis": "Original\nnote"}]}, None)
        dialog = page.unit_records_dialog
        table = dialog.findChild(QTableWidget)
        self.assertEqual(table.item(0, 2).text(), "")
        self.assertEqual(table.item(0, 6).text(), "Original\nnote")
        following = next(control for control in dialog.findChildren(QPushButton) if control.text() == "下一页")
        following.click()
        second = client.requests[-1]
        self.assertEqual(parse_qs(urlsplit(second[1]).query)["page"], ["2"])
        page.set_data({"snapshots": []})
        current = client.requests[-1]
        second[3]({"total": 201, "items": [{"thimble_id": 2}]}, None)
        self.assertEqual(table.item(0, 0).text(), "1")
        current[3]({"total": 201, "items": [{"thimble_id": 3}]}, None)
        self.assertEqual(table.item(0, 0).text(), "3")
        following.click()
        client.requests[-1][3](None, "Read failed")
        self.assertEqual(table.rowCount(), 0)
        self.assertFalse(following.isEnabled())
        retry = next(control for control in dialog.findChildren(QPushButton) if control.text() == "重试")
        retry.click()
        latest = client.requests[-1]
        self.assertEqual(parse_qs(urlsplit(latest[1]).query)["page"], ["3"])
        latest[3]({"total": 201, "items": [{"thimble_id": 8}]}, None)
        dialog.reject()
        latest[3]({"total": 201, "items": [{"thimble_id": 4}]}, None)
        self.assertEqual(table.item(0, 0).text(), "8")

    def test_missing_tube_details_keep_history_state_and_multiline_notes(self):
        from qt_shell.native_charts import VisualizationWorkspace
        page = VisualizationWorkspace()
        page._unit_history_rows = {("N1", "N101"): {"detection_tubes": {"defect": [2]},
            "state_sources": [{"tube": 2, "label": "移位", "note": "Original\n<evidence>"}]}}
        page.open_unit_tubes("N1", "N101", [2, 4], "state")
        table = page.unit_tubes_dialog.findChild(QTableWidget)
        self.assertEqual(table.rowCount(), 2)
        self.assertEqual(table.item(0, 2).text(), "WAR")
        self.assertEqual(table.item(0, 3).text(), "移位")
        self.assertEqual(table.item(0, 4).text(), "Original\n<evidence>")
        self.assertEqual(table.item(1, 2).text(), "无检测记录")
        self.assertEqual(table.item(1, 3).text(), "未记录")

    def test_history_and_tube_dialogs_refresh_and_keep_original_view_scope(self):
        from qt_shell.native_charts import VisualizationWorkspace
        client = Client()
        page = VisualizationWorkspace(client=client)
        old = {"outage": "N101", "records": 1, "detection_tubes": {"defect": [2]},
               "state_sources": [{"tube": 2, "outage": "N101", "label": "移位", "note": "old"}]}
        page._unit_history_rows = {("N1", "N101"): old}
        page.open_unit_history("N1", "N101")
        history = page.unit_history_dialog
        page.open_unit_tubes("N1", "N101", [2], "state")
        details = page.unit_tubes_dialog
        history_table = history.findChild(QTableWidget)
        table = details.findChild(QTableWidget)
        updated = {**old, "records": 2, "detection_tubes": {"NDD": [2]},
                   "state_sources": [{"tube": 2, "outage": "N101", "label": "堵管", "note": "new\n<original>"}]}
        data = {"units": [{"code": "N1", "history": [updated]}], "snapshots": [
            {"unit": "N1", "outage": "N101", "order": 1, "tubes": [
                {"tube": 2, "coverage": "NDD", "position": "B10"}]}]}
        page.set_data(data)
        self.assertEqual(history_table.item(0, 3).text(), "new\n<original>")
        self.assertIn("检测记录：2 条", history.findChild(QPlainTextEdit).toPlainText())
        self.assertEqual(table.item(0, 2).text(), "NDD")
        self.assertEqual(table.item(0, 3).text(), "堵管")
        page.set_data({"snapshots": []})
        pending = client.requests[-2:]
        self.assertEqual(len(pending), 2)
        for request in pending:
            self.assertIn("site=N&unit=1&outage=N101", request[1])
        page.set_data({"snapshots": []})
        current = client.requests[-2:]
        for request in pending:
            request[3]({"units": [{"code": "N1", "history": [old]}]}, None)
        self.assertEqual(table.rowCount(), 0)
        for request in current:
            request[3](data, None)
        self.assertEqual(table.item(0, 1).text(), "B10")
        self.assertEqual(table.item(0, 4).text(), "new\n<original>")
        page.set_data({"snapshots": []})
        failed = client.requests[-2:]
        for request in failed:
            request[3](None, "Read failed")
        self.assertEqual(table.rowCount(), 0)
        self.assertIn("Read failed", history.findChild(QPlainTextEdit).toPlainText())
        retry = next(control for control in details.findChildren(QPushButton) if control.text() == "重试")
        retry.click()
        client.requests[-1][3](data, None)
        self.assertEqual(table.rowCount(), 1)
        history.reject()
        details.reject()
        count = len(client.requests)
        page.set_data({"snapshots": []})
        self.assertEqual(len(client.requests), count)
        failed[-1][3]({"units": []}, None)
        self.assertEqual(table.rowCount(), 1)

    def test_overview_insight_dialog_refreshes_after_changes_and_deletions(self):
        from qt_shell.native_charts import VisualizationWorkspace
        page = VisualizationWorkspace()
        def data(depth):
            return {"snapshots": [{"unit": "N1", "outage": "N101", "order": 1, "tubes": [
                {"tube": 2, "coverage": "defect", "max_depth": depth}]}]}
        page.set_data(data(25))
        page.open_overview_insight("war")
        table = page.insight_dialog.findChild(QTableWidget)
        self.assertEqual(table.item(0, 4).text(), "25%")
        page.set_data(data(35))
        self.assertEqual(table.item(0, 4).text(), "35%")
        page.set_data({"snapshots": []})
        self.assertEqual(table.rowCount(), 0)

    def test_hidden_unit_history_does_not_stretch_trend_charts(self):
        page = NativeAnalyticsPage(Client())
        page.resize(1480, 880)
        page.show()
        vis = page.visualization
        vis.set_data({"snapshots": [
            {"unit": f"N{unit}", "outage": f"N{unit}01", "order": 1,
             "tubes": [{"tube": tube, "coverage": "NDD"} for tube in range(1, 51)]}
            for unit in range(1, 21)]})
        QTest.qWait(150)
        self.assertGreater(page.scroll.verticalScrollBar().maximum(), 1000)
        heading = vis.overview_page.findChild(QLabel, "sectionHeading")
        self.assertEqual(heading.height(), 42)
        self.assertLessEqual(heading.geometry().top(), 5)
        self.assertEqual(vis.overview_page.findChild(QWidget, "unitOverviewHeading").height(), 60)
        self.assertLessEqual(page.site_coverage_host.parentWidget().geometry().top(), 18)
        self.assertLessEqual(vis.overview.height(), 380)
        vis.setCurrentIndex(1)
        QTest.qWait(100)
        self.assertLess(vis.total.view.height(), 800)
        self.assertLess(page.scroll.verticalScrollBar().maximum(), 200)
        vis.setCurrentIndex(0)
        QTest.qWait(100)
        self.assertGreater(page.scroll.verticalScrollBar().maximum(), 1000)

    def test_navigation_account_and_site_filters_fit_supported_widths(self):
        window = NativeMainWindow(Client(), {"username": "viewer", "display_name": "A very long display name for testing",
                                              "permissions": ["data.read"]})
        window.show()
        for width in (1024, 1480):
            window.resize(width, 940)
            window.nav.setCurrentIndex(2)
            self.app.processEvents()
            account = window.account_button
            self.assertLessEqual(account.name_label.fontMetrics().horizontalAdvance(account.name_label.text()),
                                 account.name_label.width())
            self.assertIn("A very long display name", account.accessibleName())
            self.assertLessEqual(window.settings_button.mapTo(window, window.settings_button.rect().topRight()).x(), width)
            page = window.stack.widget(3)
            columns = page.site_coverage.columnCount()
            self.assertGreater(columns, 2)
            self.assertLessEqual(columns, 8)
            for control in page.site_coverage_buttons.values():
                self.assertLessEqual(control.coverage_label.geometry().right(), control.width())

    def test_global_coverage_does_not_change_with_filtered_chart(self):
        page = NativeAnalyticsPage(Client())
        snapshots = [{"unit": "N1", "outage": "N101", "order": 1,
                      "tubes": [{"coverage": "defect"}, {"coverage": "missing"}]},
                     {"unit": "H1", "outage": "H101", "order": 1, "tubes": [{"coverage": "ndd"}]}]
        page._coverage_loaded({"snapshots": snapshots}, None)
        expected = page.site_coverage_buttons["H"].text()
        page._complex_loaded({"snapshots": []}, None)
        self.assertEqual(page.site_coverage_buttons["H"].text(), expected)
        self.assertIn("100%", expected)

    def test_initial_unfiltered_analysis_reuses_inflight_coverage_request(self):
        client = Client()
        page = NativeAnalyticsPage(client)
        initial = len([row for row in client.requests if row[1].startswith("/api/analysis/visualization")])
        page.load_complex_analysis()
        self.assertEqual(len([row for row in client.requests
                              if row[1].startswith("/api/analysis/visualization")]), initial)
        page._coverage_loaded({"snapshots": [], "summary": {}}, None)
        self.assertFalse(page._coverage_pending)
        self.assertEqual(page.visualization.data["snapshots"], [])

    def test_state_default_direction_only_applies_after_explicit_action(self):
        page = NativeStatePage(Client(), {"permissions": ["state.write"]})
        page.current = {"outage": "N101", "unit_id": 1, "thimble_id": 1,
                        "state": "shifted", "events": ["shifted"], "offset_mm": None,
                        "unsigned_offset_mm": 42, "updated_at": "version"}
        page._populate_editor()
        page._direction_loaded({"shift_direction": "-1", "writable": True}, None)
        self.assertEqual(page.offset.text(), "")
        page._use_default_offset()
        self.assertEqual(page.offset.text(), "-42")
        self.assertIsNone(page.current["offset_mm"])
        self.assertEqual(page._editor_payload()["offset_mm"], -42)
        page.default_direction.setCurrentIndex(page.default_direction.findData("pending"))
        page.offset.clear()
        page._use_default_offset()
        self.assertEqual(page.offset.text(), "")

    def test_three_d_plate_is_overlay_and_preserves_camera_mode(self):
        window = NativeMainWindow(Client(), {"username": "test", "permissions": ["data.read"]})
        window.show()
        window.nav.setCurrentIndex(1)
        page = window.stack.widget(2)
        page.mode_tabs.setCurrentIndex(1)
        root = page.view.rootObject()
        root.setProperty("yaw", 27)
        page.plate_view.setChecked(True)
        self.assertTrue(root.property("showPlateOverlay"))
        self.assertEqual(root.property("displayMode"), "joint")
        self.assertEqual(root.property("yaw"), 27)
        page.mode_tabs.setCurrentIndex(2)
        self.assertTrue(root.property("showPlateOverlay"))
        self.assertEqual(root.property("displayMode"), "full")
        page.plate_view.setChecked(False)
        self.assertFalse(root.property("showPlateOverlay"))

    def test_plate_texture_has_exact_model_alignment_and_native_pixels(self):
        from qt_shell.native_plate_texture import plate_mapping, plate_svg, plate_image
        import xml.etree.ElementTree as ET
        _drawing, x, z, height = plate_mapping()
        self.assertGreater(height, 0)
        self.assertNotEqual(x[0] * z[1] - x[1] * z[0], 0)
        drawing = ET.fromstring(plate_svg(1, 1))
        groups = [node for node in drawing if node.get("class") == "thimble"]
        self.assertEqual(len(groups), 50)
        self.assertTrue(all(len(group.findall("{http://www.w3.org/2000/svg}text")) == 1 for group in groups))
        selected = [node for node in drawing.iter() if node.get("fill") == "#ffe09b"]
        self.assertEqual(len(selected), 1)
        image = plate_image(1, 1)
        self.assertFalse(image.isNull())
        self.assertGreater(len({image.pixel(u, v) for u in range(0, 2120, 20)
                                for v in range(0, 1920, 20)}), 20)

    def test_mutation_keeps_report_draft_and_refreshes_unknown_write(self):
        window = NativeMainWindow(Client(), {"username": "test", "permissions": ["data.read"]})
        report = window.stack.widget(4)
        report.draft_edits = [{"key": "t1:r1:c1", "value": "unsaved"}]
        report.snapshot_id = "old"
        report.source_data_changed()
        self.assertIsNone(report.snapshot_id)
        self.assertEqual(report.draft_edits[0]["value"], "unsaved")
        self.assertTrue(report._draft_source_changed)
        changes = []
        window.context.dataChanged.connect(lambda: changes.append(True))
        window._request_finished("/api/new-write", {"ok": True}, "")
        self.assertEqual(changes, [True])
        window._request_finished("/api/states/recognize-note", {"rows": []}, "")
        window._request_finished("/api/new-write", {"ok": True}, "failed")
        self.assertEqual(changes, [True])

    def test_selected_rows_refreshes_off_page_and_removes_deleted(self):
        client = Client()
        page = DataWorkbench(client)
        original = {"id": 1, "unit_id": 1, "outage": "N101", "thimble_id": 1, "percent": 10}
        page.model.selected = {1: original, 2: {**original, "id": 2}}
        page.refresh_selection()
        client.requests[-1][3]({"items": [{**original, "percent": 40}]}, None)
        self.assertEqual(list(page.model.selected), [1])
        self.assertEqual(page.model.selected[1]["percent"], 40)

    def test_batch_queue_preflights_all_before_write_and_keeps_file_hashes(self):
        client = Client()
        wizard = ImportWizard(client, DataWorkbench.MAPPING_FIELDS, {})
        wizard.show()
        wizard.set_sources(["a.xlsx", "b.xlsx"])
        wizard.next()
        client.requests[-1][3]({"sheets": [{"name": "N101", "columns": [], "sample_rows": []}]}, None)
        self.assertEqual(wizard.currentId(), 1)
        wizard.next()
        first = client.requests[-1]
        self.assertEqual(first[2]["blank_indication_policy"], "check")
        first[3]({"parsed": 2, "source_sha256": "hash-a"}, None)
        second = client.requests[-1]
        self.assertEqual(second[2]["blank_indication_policy"], "check")
        self.assertEqual(wizard.currentId(), 1)
        second[3]({"parsed": 3, "source_sha256": "hash-b"}, None)
        self.assertEqual(wizard.currentId(), 2)
        self.assertEqual(wizard.result["parsed"], 5)
        wizard.next()
        self.assertEqual(client.requests[-1][2]["expected_sha256"], "hash-a")
        client.requests[-1][3]({"inserted": 2, "batch_id": 10}, None)
        self.assertEqual(client.requests[-1][2]["expected_sha256"], "hash-b")
        imported = []
        wizard.imported.connect(imported.append)
        client.requests[-1][3](None, "second failed")
        self.assertEqual(wizard.currentId(), 4)
        self.assertTrue(wizard.retry.isVisible())
        self.assertEqual(imported[0]["inserted"], 2)
        self.assertTrue(imported[0]["partial"])
        self.assertEqual(wizard.result["files"][0]["batch_id"], 10)

    def test_import_sources_queue_and_busy_controls_follow_selected_route(self):
        wizard = ImportWizard(Client(), DataWorkbench.MAPPING_FIELDS, {})
        wizard.resize(900, 768)
        wizard.show()
        self.app.processEvents()
        self.assertTrue(wizard.queue_table.isVisible())
        self.assertFalse(wizard.rpt_note.isVisible())
        wizard.set_sources(["first.xlsx", "second.xlsx"])
        wizard.queue_table.selectRow(1)
        self.assertEqual(wizard.queue_summary.text(), "2 个文件")
        self.assertEqual(wizard.queue_table.item(1, 0).text(), "second.xlsx")
        self.assertTrue(wizard.queue_table.item(1, 0).toolTip().endswith("second.xlsx"))
        wizard.set_busy(True)
        self.assertFalse(wizard.browse_source.isEnabled())
        self.assertFalse(wizard.remove_file.isEnabled())
        wizard.set_busy(False)
        wizard.remove_file.click()
        self.assertEqual(len(wizard.source_paths), 1)
        wizard.source_tabs.setCurrentIndex(1)
        self.app.processEvents()
        self.assertEqual(wizard.mode.currentData(), "directory")
        self.assertTrue(wizard.rpt_note.isVisible())
        self.assertFalse(wizard.queue_heading.isVisible())
        self.assertFalse(wizard.queue_table.isVisible())
        self.assertFalse(wizard.path.isReadOnly())
        wizard.path.setText("D:/isolated-rpt-source")
        self.assertLess(wizard.browse_source.mapTo(wizard, wizard.browse_source.rect().bottomRight()).x(),
                        wizard.width())
        wizard.source_tabs.setCurrentIndex(0)
        self.assertEqual(len(wizard.source_paths), 1)
        self.assertTrue(wizard.path.text().endswith("first.xlsx"))
        self.assertTrue(wizard.queue_heading.isVisible())
        wizard.source_tabs.setCurrentIndex(1)
        self.assertEqual(wizard.path.text(), "D:/isolated-rpt-source")

    def test_queue_preflight_failure_writes_nothing(self):
        client = Client()
        wizard = ImportWizard(client, DataWorkbench.MAPPING_FIELDS, {})
        wizard.show()
        wizard.set_sources(["a.xlsx", "b.xlsx"])
        wizard.next()
        client.requests[-1][3]({"sheets": [{"name": "N101", "columns": []}]}, None)
        wizard.next()
        client.requests[-1][3]({"parsed": 2}, None)
        with patch.object(QMessageBox, "warning"):
            client.requests[-1][3](None, "invalid mapping")
        self.assertFalse(wizard.ready_preview)
        self.assertEqual(wizard.currentId(), 1)
        self.assertTrue(all(row[2].get("blank_indication_policy") == "check"
                            for row in client.requests if row[1] == "/api/import-excel"))

    def test_folder_scan_is_recursive_bounded_and_skips_office_lock_files(self):
        with tempfile.TemporaryDirectory(dir=native_test_env.test_data.name) as folder:
            root = Path(folder)
            nested = root / "one" / "two"
            nested.mkdir(parents=True)
            for path in (root / "a.xlsx", nested / "b.xls", nested / "~$lock.xlsx", nested / "c.csv"):
                path.touch()
            paths, truncated = scan_excel_sources(root)
            self.assertEqual({Path(path).name for path in paths}, {"a.xlsx", "b.xls"})
            self.assertFalse(truncated)
            with patch("qt_shell.native_import.EXCEL_SCAN_LIMIT", 1):
                paths, truncated = scan_excel_sources(root)
            self.assertEqual(len(paths), 1)
            self.assertTrue(truncated)

    def test_rpt_standard_excel_export_never_enters_import_path(self):
        client = Client()
        wizard = ImportWizard(client, DataWorkbench.MAPPING_FIELDS, {"report_policy": "latest"}, mode="directory")
        wizard.show()
        wizard.path.setText("source")
        report = {"path": "source/one.rpt", "outage": "N101", "unit_id": 1, "site_code": "N",
                  "group": "one", "sha256": "rpt-hash", "sum_sha256": "sum-hash", "records": 2}
        wizard.source_loaded(wizard.generation, {"reports": [report]}, None, advance=False)
        wizard.export_directory()
        self.assertEqual(client.requests[-1][1], "/api/export-folder-excel")
        self.assertEqual(client.requests[-1][2]["report_confirmation"]["candidates"][0]["sha256"], "rpt-hash")
        imported = []
        wizard.imported.connect(imported.append)
        with tempfile.TemporaryDirectory(dir=native_test_env.test_data.name) as folder:
            source, target = Path(folder) / "source.xlsx", Path(folder) / "saved.xlsx"
            book = Workbook()
            book.save(source)
            book.close()
            with patch.object(QFileDialog, "getSaveFileName", return_value=(str(target), "")):
                client.requests[-1][3]({"file_path": str(source), "rows": 2}, None)
            self.assertEqual(client.requests[-1][1], "/api/auth/me")
            client.requests[-1][3]({"user": {"permissions": ["export.create"]}}, None)
            self.assertEqual(target.read_bytes(), source.read_bytes())
        self.assertFalse(imported)
        self.assertFalse(any(row[1] in {"/api/import", "/api/import-excel"} for row in client.requests))


if __name__ == "__main__":
    unittest.main()
