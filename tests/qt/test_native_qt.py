"""Focused regression tests for the native Qt migration slice."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import native_test_env  # noqa: E402,F401

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer, Qt  # noqa: E402
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QLineEdit,
                               QMessageBox, QPlainTextEdit, QTableView)  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from qt_shell.native_client import NativeClient  # noqa: E402
from qt_shell.native_windows import (  # noqa: E402
    FindingsModel,
    DataWorkbench,
    NativeAnalyticsPage,
    NativeMainWindow,
    NativeMaintenancePage,
    NativeReportsPage,
    NativeSettingsPage,
    NativeStatePage,
    StateImportModel,
    NativeThreeDPage,
)
import qt_shell.native_windows as native_windows  # noqa: E402


class NativeQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        # Explicitly drain and stop the singleton event loop.  Letting the
        # offscreen Qt platform tear down implicitly can intermittently return
        # 0xC0000005 after all assertions have already passed.
        cls.app.processEvents()
        cls.app.quit()
        cls.app.processEvents()

    @classmethod
    def drain_qt_events(cls):
        loop = QEventLoop()
        QTimer.singleShot(0, loop.quit)
        loop.exec()

    def tearDown(self):
        for widget in self.app.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        import gc
        gc.collect()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_findings_model_has_stable_columns_and_rows(self):
        model = FindingsModel()
        self.assertEqual(model.columnCount(), 19)
        self.assertNotIn("maintenance_status", model.editable_fields)
        model.replace([{
            "site_code": "N",
            "outage": "N101",
            "unit_id": 1,
            "thimble_id": 7,
            "position": "P2-07",
            "display_conclusion": "NDD",
            "percent": 0,
            "state": "normal",
            "analyst": "tester",
        }])
        self.assertEqual(model.rowCount(), 1)
        self.assertEqual(model.data(model.index(0, 2)), "N101")
        self.assertEqual(model.data(model.index(0, 9)), "0%")

    def test_native_window_builds_without_webengine(self):
        client = NativeClient("http://127.0.0.1:18767")
        window = NativeMainWindow(client, {"username": "tester", "permissions": []})
        self.assertEqual(window.nav.count(), 5)
        self.assertEqual(window.stack.count(), 5)
        self.assertEqual(window.workbench.model.columnCount(), 19)
        self.assertIsInstance(window.stack.widget(1), NativeStatePage)
        self.assertIsInstance(window.stack.widget(2), NativeThreeDPage)
        self.assertIsInstance(window.stack.widget(3), NativeAnalyticsPage)
        self.assertIsInstance(window.stack.widget(4), NativeReportsPage)
        self.assertIsInstance(window.maintenance, NativeMaintenancePage)
        self.assertIsInstance(window.settings_page, NativeSettingsPage)
        self.assertEqual(window.settings_dialog.nav.count(), 6)
        self.app.processEvents()
        self.assertIsNotNone(window.stack.widget(2).view.status())
        window.close()
        window.deleteLater()
        self.drain_qt_events()

    def test_report_export_uses_current_preview_snapshot(self):
        class Client:
            def __init__(self):
                self.requests = []

            def get(self, path, callback):
                self.requests.append(("GET", path, None))

            def post(self, path, payload, callback):
                self.requests.append(("POST", path, payload))

        client = Client()
        page = NativeReportsPage(client)
        page.site.setText("N")
        page.unit.setValue(1)
        page.outage.setText("N101")
        page.preview_report()
        self.assertEqual(client.requests[-1][1], "/api/reports/preview")
        page._on_preview({"snapshot_id": "snapshot", "values": []}, None)
        page.export_report()
        self.assertEqual(client.requests[-1][1], "/api/reports/export")
        self.assertEqual(client.requests[-1][2]["snapshot_id"], "snapshot")
        page.close()

    def test_report_template_catalog_and_format_are_sent_to_backend(self):
        class Client:
            def __init__(self):
                self.requests = []
            def get(self, path, callback):
                self.requests.append(("GET", path))
            def post(self, path, payload, callback):
                self.requests.append(("POST", path, payload))

        client = Client()
        page = NativeReportsPage(client)
        page._templates_loaded({
            "templates": [
                {"id": "inspection", "title": "检验报告单", "mode": "inspection",
                 "formats": ["docx", "xlsx"]},
                {"id": "comparison", "title": "检验结果比对表", "mode": "comparison",
                 "formats": ["xlsx"]},
            ]
        }, None)
        page.kind.setCurrentIndex(1)
        self.assertEqual(page.templates.currentItem().data(Qt.ItemDataRole.UserRole)["id"], "comparison")
        self.assertEqual(page.export_format.currentData(), "xlsx")
        self.assertEqual(page._payload()["template_id"], "comparison")
        page.close()

    def test_state_batch_and_export_payloads_use_selected_scope(self):
        class Client:
            def __init__(self):
                self.requests = []
            def get(self, path, callback):
                pass
            def post(self, path, payload, callback):
                self.requests.append((path, payload))

        client = Client()
        page = NativeStatePage(client, {"permissions": ["state.write", "export.create"]})
        page.current = {"outage": "N101", "unit_id": 1}
        with patch("qt_shell.native_windows.QMessageBox.question",
                   return_value=QMessageBox.StandardButton.No):
            page._bulk_normal()
        path, payload = client.requests[-1]
        self.assertEqual(path, "/api/states/batch-preview")
        self.assertEqual(len(payload["rows"]), 50)
        self.assertEqual(payload["rows"][0]["outage"], "N101")
        page._export_states()
        path, payload = client.requests[-1]
        self.assertEqual(path, "/api/states/export")
        self.assertEqual(payload, {"outage": "N101", "unit_id": 1, "format": "xlsx"})
        page.close()

    def test_state_inline_edit_preserves_complex_events_and_concurrency(self):
        class Client:
            def __init__(self):
                self.requests = []
            def get(self, path, callback):
                pass
            def post(self, path, payload, callback):
                self.requests.append((path, payload))

        client = Client()
        page = NativeStatePage(client, {"permissions": ["state.write"]})
        page.current = {"outage": "N101", "unit_id": 1, "thimble_id": 1,
                        "state": "plugged", "events": ["shifted", "plugged"], "updated_at": "version",
                        "unsigned_offset_mm": 42, "source": "original"}
        page._populate_editor()
        with patch("qt_shell.native_windows.QMessageBox.warning"):
            page._save()
        self.assertEqual(client.requests, [])
        page.offset.setText("-42")
        page._save()
        path, payload = client.requests[-1]
        self.assertEqual(path, "/api/state")
        self.assertEqual(payload["expected_updated_at"], "version")
        self.assertEqual(set(payload["events"]), {"plugged", "shifted"})
        self.assertEqual(payload["offset_mm"], -42)
        self.assertEqual(payload["source"], "original")
        page.close()

    def test_advanced_state_editor_preserves_events_and_concurrency(self):
        class Client:
            def __init__(self):
                self.requests = []
            def get(self, path, callback):
                pass
            def post(self, path, payload, callback):
                self.requests.append((path, payload))

        client = Client()
        page = NativeStatePage(client, {"permissions": ["state.write"]})
        page.current = {"outage": "N101", "unit_id": 1, "thimble_id": 1,
                        "events": ["plugged", "shifted", "replaced"],
                        "replacement_stage": "after_replacement", "offset_mm": -42,
                        "note": "原备注", "source": "原始资料", "updated_at": "v1"}

        def accept_dialog():
            dialog = QApplication.activeModalWidget()
            self.assertTrue(dialog.findChild(QCheckBox, "maintenance_plugged").isChecked())
            self.assertEqual(dialog.findChild(QComboBox, "maintenanceStage").currentData(), "after_replacement")
            self.assertEqual(dialog.findChild(QLineEdit, "maintenanceOffset").text(), "-42")
            dialog.findChild(QPlainTextEdit, "maintenanceNote").setPlainText("已核对")
            dialog.accept()

        QTimer.singleShot(0, accept_dialog)
        page._edit_advanced()
        path, payload = client.requests[-1]
        self.assertEqual(path, "/api/state")
        self.assertEqual(payload["events"], ["plugged", "shifted", "replaced"])
        self.assertEqual(payload["replacement_stage"], "after_replacement")
        self.assertEqual(payload["offset_mm"], -42)
        self.assertEqual(payload["expected_updated_at"], "v1")
        self.assertNotIn("source", payload)
        page.close()

    def test_advanced_state_editor_requires_explicit_unsigned_direction(self):
        class Client:
            def __init__(self):
                self.requests = []
            def get(self, path, callback):
                pass
            def post(self, path, payload, callback):
                self.requests.append((path, payload))
        client = Client()
        page = NativeStatePage(client, {"permissions": ["state.write"]})
        page.current = {"outage": "N101", "unit_id": 1, "thimble_id": 1,
                        "events": ["shifted"], "offset_mm": None,
                        "unsigned_offset_mm": 42, "updated_at": "v1"}
        QTimer.singleShot(0, lambda: QApplication.activeModalWidget().accept())
        with patch("qt_shell.native_windows.QMessageBox.warning") as warning:
            page._edit_advanced()
        self.assertEqual(client.requests, [])
        self.assertIn("正负号", warning.call_args.args[2])
        page.close()

    def test_state_empty_list_allows_explicit_scope(self):
        class Client:
            def get(self, path, callback):
                pass
        page = NativeStatePage(Client())
        with patch("qt_shell.native_windows.QInputDialog.getText", return_value=("n101", True)), \
             patch("qt_shell.native_windows.QInputDialog.getInt", return_value=(1, True)):
            self.assertEqual(page._scope_from_current(), {"outage": "N101", "unit_id": 1})
        page.close()

    def test_state_import_supplements_unrecognized_outage(self):
        class Client:
            def __init__(self):
                self.requests = []
            def get(self, path, callback):
                pass
            def post(self, path, payload, callback):
                self.requests.append((path, payload))
        client = Client()
        page = NativeStatePage(client, {"permissions": ["state.write"]})
        preview = {"rows": [], "revision": "rev", "missing_scopes": [
            {"key": "sheet-1", "title": "维护记录", "site": "N", "unit_id": 1, "rows": 3}
        ]}
        with patch("qt_shell.native_windows.QMessageBox.question",
                   return_value=QMessageBox.StandardButton.Yes), \
             patch("qt_shell.native_windows.QInputDialog.getText", return_value=("n101", True)):
            page._state_import_preview("states.xlsx", preview, None, "base64-content")
        self.assertEqual(client.requests[-1], (
            "/api/states/import-preview",
            {"filename": "states.xlsx", "content": "base64-content",
             "scope_overrides": {"sheet-1": "N101"}, "direction_policy": "pending"},
        ))
        page.close()

    def test_state_import_requires_direction_and_sends_signed_distance(self):
        class Client:
            def __init__(self):
                self.requests = []
            def get(self, path, callback):
                pass
            def post(self, path, payload, callback):
                self.requests.append((path, payload))
        client = Client()
        page = NativeStatePage(client, {"permissions": ["state.write"]})
        preview = {"rows": [{"outage": "N101", "unit_id": 1, "thimble_id": 1,
                             "state": "shifted", "events": ["shifted"], "offset_mm": None,
                             "unsigned_offset_mm": 42}], "revision": "revision"}
        QTimer.singleShot(0, lambda: QApplication.activeModalWidget().accept())
        with patch("qt_shell.native_windows.QMessageBox.warning"):
            page._state_import_preview("state.xlsx", preview, None)
        self.assertEqual(client.requests, [])
        def choose_direction():
            dialog = QApplication.activeModalWidget()
            model = dialog.findChild(QTableView, "stateImportTable").model()
            model.setData(model.index(0, 7), "负向 (-)")
            dialog.accept()
        QTimer.singleShot(0, choose_direction)
        page._state_import_preview("state.xlsx", preview, None)
        path, payload = client.requests[-1]
        self.assertEqual(path, "/api/states/batch")
        self.assertEqual(payload["rows"][0]["offset_mm"], -42)
        self.assertIsNone(payload["rows"][0]["unsigned_offset_mm"])
        self.assertEqual(payload["import_revision"], "revision")
        page.close()

    def test_state_import_model_large_batch_preserves_individual_edits(self):
        rows = [{"outage": "N101", "unit_id": 1, "thimble_id": i % 50 + 1,
                 "state": "shifted", "events": ["shifted"], "offset_mm": None,
                 "unsigned_offset_mm": 42, "note": "原备注", "source": "原始文件"}
                for i in range(8750)]
        rows[1]["existing_status"] = "different"
        rows[2]["existing_status"] = "revoked"
        model = StateImportModel(rows)
        self.assertEqual(model.rowCount(), 8750)
        self.assertFalse(model.checked[1])
        self.assertFalse(model.checked[2])
        self.assertFalse(model.setData(model.index(2, 0), Qt.CheckState.Checked,
                                       Qt.ItemDataRole.CheckStateRole))
        model.setData(model.index(0, 7), "负向 (-)")
        model.setData(model.index(0, 8), "人工核对")
        for index in range(3, len(rows)):
            model.setData(model.index(index, 0), Qt.CheckState.Unchecked,
                          Qt.ItemDataRole.CheckStateRole)
        selected = model.selected_rows()
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["offset_mm"], -42)
        self.assertEqual(selected[0]["note"], "人工核对")
        self.assertEqual(selected[0]["source"], "原始文件")

    def test_state_import_bulk_actions_leave_conflicts_unselected(self):
        rows = [
            {"outage": "N101", "thimble_id": 1, "unsigned_offset_mm": 12},
            {"outage": "N101", "thimble_id": 2, "unsigned_offset_mm": 14,
             "existing_status": "different", "existing_state": "堵管", "existing_offset_mm": 8},
            {"outage": "N101", "thimble_id": 3, "unsigned_offset_mm": 16,
             "existing_status": "revoked"},
        ]
        model = StateImportModel(rows)
        model.select_new_rows(False)
        self.assertEqual(model.checked, [False, False, False])
        model.select_new_rows(True)
        self.assertEqual(model.checked, [True, False, False])
        model.set_selected_direction("正向 (+)")
        self.assertEqual(model.directions_by_row, ["正向 (+)", "待确认", "待确认"])
        self.assertIn("堵管", model.data(model.index(1, 9)))
        self.assertIn("8 mm", model.data(model.index(1, 9)))

    def test_state_import_rejects_duplicate_selection_and_missing_revision(self):
        rows = [{"outage": "N101", "unit_id": 1, "thimble_id": 1},
                {"outage": "N101", "unit_id": 1, "thimble_id": 1}]
        model = StateImportModel(rows)
        with self.assertRaisesRegex(ValueError, "重复记录"):
            model.selected_rows()
        model.setData(model.index(1, 0), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
        self.assertEqual(len(model.selected_rows()), 1)
        class Client:
            def get(self, path, callback):
                pass
        page = NativeStatePage(Client())
        with patch("qt_shell.native_windows.QMessageBox.warning") as warning:
            page._state_import_preview("state.csv", {"rows": rows}, None)
        self.assertIn("数据库版本", warning.call_args.args[2])
        page.close()

    def test_advanced_state_editor_writes_isolated_database(self):
        from src.backend import server
        test_root = Path(__file__).resolve().parents[3] / "05_测试与验证" / "03_自动化临时产物"
        with tempfile.TemporaryDirectory(dir=test_root) as folder, \
             patch.object(server, "DB_PATH", Path(folder) / "state.db"):
            server.init_db()
            server.save_tube_state({
                "outage": "N101", "unit_id": 1, "thimble_id": 1,
                "state": "plugged", "events": ["plugged", "shifted", "replaced"],
                "replacement_stage": "after_replacement", "offset_mm": -42,
                "note": "原备注", "source": "原始资料",
            })
            original = server.query_states()["items"][0]

            class Client:
                def get(self, path, callback):
                    pass
                def post(self, path, payload, callback):
                    try:
                        callback(server.save_tube_state(payload), None)
                    except ValueError as error:
                        callback(None, str(error))

            page = NativeStatePage(Client(), {"permissions": ["state.write"]})
            page.current = original

            def accept_dialog():
                dialog = QApplication.activeModalWidget()
                dialog.findChild(QPlainTextEdit, "maintenanceNote").setPlainText("核对完成")
                dialog.accept()

            with patch("qt_shell.native_windows.QMessageBox.information"):
                QTimer.singleShot(0, accept_dialog)
                page._edit_advanced()
            saved = server.query_states()["items"][0]
            self.assertEqual(saved["events"], ["plugged", "shifted", "replaced"])
            self.assertEqual(saved["replacement_stage"], "after_replacement")
            self.assertEqual(saved["offset_mm"], -42)
            self.assertEqual(saved["source"], "原始资料")
            self.assertEqual(saved["note"], "核对完成")
            with self.assertRaisesRegex(ValueError, "已变化"):
                server.save_tube_state({**original, "expected_updated_at": original["updated_at"]})
            page.close()

    def test_complex_analysis_displays_actual_result_and_hides_on_error(self):
        class Client:
            def get(self, path, callback):
                pass
        page = NativeAnalyticsPage(Client(), {"permissions": ["data.read"]})
        page._complex_loaded({
        "trends": [{"unit": "N1", "outage": "N101", "order": 1, "records": 3,
                        "wear_records": 1, "total": 12, "missing_tubes": 47, "partial": True}],
            "increments": [{"unit": "N1", "outage": "N101", "matched": 0,
                            "rules": {"version": 4}}],
            "coverage": [{"unit": "N1", "outage": "N101",
                          "counts": {"defect": 1, "NDD": 2, "missing": 47}}],
            "summary": {"records": 3, "units": 1, "outages": 1, "missing_tubes": 47},
            "quality": {},
        }, None)
        self.assertEqual(page.trend_table.item(0, 0).text(), "N1")
        self.assertEqual(page.coverage_table.item(0, 3).text(), "2")
        self.assertIn("版本：4", page.quality_text.toPlainText())
        page.analysis_details.setChecked(True)
        self.assertFalse(page.complex_tabs.isHidden())
        page._complex_loaded(None, "分析失败")
        self.assertTrue(page.complex_tabs.isHidden())
        page.close()

    def test_quality_table_uses_issues_not_batches(self):
        client = NativeClient("http://127.0.0.1:18767")
        page = NativeMaintenancePage(client)
        page.quality._loaded({"batches": [{"id": 1}], "issues": [{"id": 2, "code": "X"}]}, None)
        self.assertEqual(page.quality.model.rows[0]["id"], 2)
        page.recycle._loaded({"items": [{"id": "batch-1"}], "total": 1}, None)
        self.assertEqual(page.recycle.model.data(page.recycle.model.index(0, 0)), "batch-1")
        page.close()

    def test_three_d_scope_uses_data_and_rejects_stale_response(self):
        class Client:
            def __init__(self):
                self.pending = []

            def get(self, path, callback):
                self.pending.append((path, callback))

        client = Client()
        page = NativeThreeDPage(client)
        page._overview_loaded({"combinations": [
            {"site": "N", "unit_id": 1, "outage": "N101"},
            {"site": "N", "unit_id": 1, "outage": "N102"},
        ]}, None)
        page.scope.setCurrentIndex(1)
        first = client.pending[-1][1]
        page.scope.setCurrentIndex(2)
        second = client.pending[-1][1]
        from qt_shell.native_model_data import reference_layout
        plate = [
            {"tube": int(channel["serialOdd"]), "position": channel["pos"],
             "records": 0, "defects": 0, "ndd": False}
            for channel in reference_layout()["channels"]
        ]
        plate.sort(key=lambda row: row["tube"])
        plate[0].update(records=1, defects=1, max_percent=35, state_label="堵管")
        plate[1].update(records=1, ndd=True)
        plate[2].update(records=1)
        second({"scope": {"site": "N", "unit": 1, "outage": "N102"}, "plate": plate}, None)
        self.assertEqual(len(page.rows), 50)
        self.assertEqual(page.rows[1]["category_label"], "存在缺陷")
        self.assertEqual(page.rows[2]["category_label"], "NDD")
        self.assertEqual(page.rows[3]["category_label"], "待复核")
        self.assertEqual(page.rows[4]["category_label"], "无记录")
        page.resize(1000, 750)
        page.show()
        QTest.qWait(500)
        frame = page.view.grabWindow()
        self.assertFalse(frame.isNull())
        colors = {frame.pixelColor(x, y).name()
                  for x in range(0, frame.width(), 15)
                  for y in range(0, frame.height(), 15)}
        self.assertGreater(len(colors), 4, "3D framebuffer does not contain rendered geometry")
        page.filter_defect.setChecked(False)
        self.app.processEvents()
        self.assertFalse(page.view.rootObject().property("showDefect"))
        page._reset_three_d_view()
        self.assertEqual(page.view.rootObject().property("zoomFactor"), 1)
        first({"scope": {"site": "N", "unit": 1, "outage": "N101"}, "plate": []}, None)
        self.assertEqual(len(page.rows), 50)
        page.view.rootObject().tubeSelected.emit(1)
        self.assertIn("堵管", page.detail.text())
        page.scope.setCurrentIndex(0)

        self.assertEqual(page.rows, {})
        page.scope.setCurrentIndex(2)
        plate[1]["position"] = plate[0]["position"]
        client.pending[-1][1]({"scope": {"site": "N", "unit": 1, "outage": "N102"}, "plate": plate}, None)
        self.assertEqual(page.rows, {})
        self.assertIn("无效", page.status.text())
        page.close()
        page.deleteLater()
        self.drain_qt_events()

    def test_three_d_exposes_seven_standard_camera_views(self):
        class Client:
            def get(self, _path, _callback):
                return None

        page = NativeThreeDPage(Client())
        labels = [page.camera_preset.itemText(index)
                  for index in range(page.camera_preset.count())]
        self.assertEqual(
            labels,
            ["等轴视角", "正视", "后视", "左视", "右视", "俯视", "仰视"],
        )
        angles = [page.camera_preset.itemData(index)
                  for index in range(page.camera_preset.count())]
        self.assertEqual(angles[2], (180, 0))
        self.assertEqual(angles[3], (-90, 0))
        self.assertEqual(angles[5], (0, -90))
        self.assertEqual(angles[6], (0, 90))
        root = page.view.rootObject()
        for index in range(7):
            page.camera_buttons[index].click()
            self.assertEqual(root.property("orthographicView"), index > 0)
            self.assertEqual(root.property("mirrorTop"), index == 5)
            self.assertEqual(root.property("yaw"), angles[index][0])
            self.assertEqual(root.property("pitch"), angles[index][1])
            self.assertEqual([b.isChecked() for b in page.camera_buttons],
                             [i == index for i in range(7)])
        root.setProperty("panX", 120)
        root.setProperty("zoomFactor", 3)
        page.camera_buttons[6].click()
        self.assertTrue(page.camera_buttons[6].isChecked())
        self.assertEqual(root.property("panX"), 0)
        self.assertEqual(root.property("zoomFactor"), 1)
        page.camera_preset.setCurrentIndex(-1)
        self.assertFalse(any(b.isChecked() for b in page.camera_buttons))
        page._reset_three_d_view()
        self.assertEqual(page.camera_preset.currentIndex(), 0)
        self.assertTrue(page.camera_buttons[0].isChecked())
        self.assertFalse(root.property("orthographicView"))
        self.assertFalse(root.property("mirrorTop"))
        page.close()

    def test_three_d_axis_controls_keep_assembly_and_detail_independent(self):
        class Client:
            def get(self, _path, _callback):
                return None

        page = NativeThreeDPage(Client())
        root = page.view.rootObject()
        self.assertTrue(page.axes.isChecked())
        self.assertFalse(page.detail_axis.isChecked())
        page.display_mode.setCurrentIndex(page.display_mode.findData("joint"))
        self.assertTrue(page.detail_axis.isEnabled())
        page.detail_axis.click()
        self.assertTrue(root.property("showDetailAxis"))
        page.display_mode.setCurrentIndex(page.display_mode.findData("assembly"))
        self.assertFalse(page.detail_axis.isEnabled())
        self.assertTrue(page.detail_axis.isChecked())
        page.axes.click()
        self.assertFalse(root.property("showAxes"))
        self.assertTrue(root.property("showDetailAxis"))
        page.display_mode.setCurrentIndex(page.display_mode.findData("socket"))
        self.assertTrue(page.detail_axis.isChecked())
        self.assertFalse(root.property("showAxes"))
        page.close()

    def test_vessel_wire_clips_all_axes_and_restores_original_segments(self):
        from array import array
        from qt_shell.native_geometry import VesselWireGeometry, vessel_wire_positions

        geometry = VesselWireGeometry()
        original = array("f", vessel_wire_positions()).tobytes()
        self.assertEqual(bytes(geometry.vertexData()), original)
        self.assertEqual(len(original)//24, 4145)
        geometry.setProperty("clipActive", True)
        for index, axis in enumerate(("x", "y", "z")):
            geometry.setProperty("clipAxis", axis)
            geometry.setProperty("clipOffset", 0.)
            clipped = array("f")
            clipped.frombytes(bytes(geometry.vertexData()))
            self.assertGreater(len(clipped), 0)
            self.assertLess(len(clipped)*4, len(original))
            self.assertEqual(len(clipped) % 6, 0)
            self.assertLessEqual(max(clipped[index::3]), .001)
            geometry.setProperty("clipOffset", min(vessel_wire_positions()[index::3])-1)
            self.assertEqual(bytes(geometry.vertexData()), b"")
            geometry.setProperty("clipOffset", max(vessel_wire_positions()[index::3])+1)
            self.assertEqual(bytes(geometry.vertexData()), original)
        geometry.setProperty("clipActive", False)
        self.assertEqual(bytes(geometry.vertexData()), original)

    def test_three_d_penetrations_and_metalness_follow_original_source(self):
        from qt_shell.native_model_data import reference_parts

        class Client:
            def get(self, _path, _callback):
                return None

        page = NativeThreeDPage(Client())
        root = page.view.rootObject()
        self.assertEqual(root.property("partMetalness"),
                         {part["id"]: part["metalness"] for part in reference_parts()})
        self.assertEqual(page.opacity.value(), 100)
        control = page.visibility_checks["showPenetrations"]
        self.assertTrue(control.isChecked())
        control.click()
        self.assertFalse(root.property("showPenetrations"))
        control.click()
        self.assertTrue(root.property("showPenetrations"))
        page.close()

    def test_three_d_rotation_fit_and_shutdown_keep_camera_controls_consistent(self):
        class Client:
            def get(self, _path, _callback):
                return None

        page = NativeThreeDPage(Client())
        page.resize(1100, 800)
        page.show()
        self.app.processEvents()
        root = page.view.rootObject()
        self.assertGreater(root.property("coveredRight"), 0)
        self.assertGreater(root.property("coveredBottom"), 0)
        page.camera_buttons[5].click()
        page._fit_scene()
        self.assertEqual(page.camera_preset.currentIndex(), 5)
        self.assertTrue(root.property("orthographicView"))
        self.assertEqual(root.property("pitch"), -90)
        page.auto_rotate.setChecked(True)
        page._rotate_scene()
        self.assertFalse(root.property("orthographicView"))
        self.assertFalse(root.property("standardAligned"))
        self.assertEqual(page.camera_preset.currentIndex(), -1)
        page.camera_buttons[1].click()
        self.assertFalse(page.auto_rotate.isChecked())
        self.assertFalse(page._rotation_timer.isActive())
        page.display_mode.setCurrentIndex(page.display_mode.findData("joint"))
        self.assertFalse(root.property("orthographicView"))
        self.assertEqual(page.camera_preset.currentIndex(), 0)
        with patch.object(page.view, "rootObject", return_value=None):
            page._rotation_changed(True)
        page.close()
        self.assertFalse(page._camera_layout_timer.isActive())
        self.assertFalse(page._rotation_timer.isActive())

    def test_three_d_model_settings_float_scroll_and_preserve_controls(self):
        class Client:
            def get(self, _path, _callback):
                return None

        page = NativeThreeDPage(Client())
        page.resize(800, 650)
        page.show()
        self.app.processEvents()
        original_scene_height = page.scene_host.height()
        page.scene_settings_button.click()
        self.app.processEvents()
        self.assertEqual(page.width(), 800)
        self.assertEqual(page.scene_host.height(), original_scene_height)
        self.assertTrue(page.scene_settings_host.isVisible())
        self.assertGreater(page.view.rootObject().property("coveredLeft"), 0)
        self.assertEqual(page.scene_settings_host.horizontalScrollBar().maximum(), 0)
        self.assertLessEqual(page.scene_settings_host.height(),
                             page.scene_host.height() - page.scene_footer.height() - 16)
        self.assertEqual(page.scene_settings_host.height(),
                         page.scene_host.height() - page.scene_footer.height() - 16)
        heading, body = page.scene_sections["剖切与测距"]
        page.section_offset.setValue(-1250)
        heading.click()
        self.assertTrue(body.isHidden())
        heading.click()
        self.assertFalse(body.isHidden())
        self.assertEqual(page.section_offset.value(), -1250)
        page.scene_settings_host.ensureWidgetVisible(page.image_export)
        self.app.processEvents()
        position = page.image_export.mapTo(page.scene_settings_host.viewport(), page.image_export.rect().center())
        self.assertTrue(page.scene_settings_host.viewport().rect().contains(position))
        expanded_height = page.scene_settings_host.height()
        for disclosure, _body in page.scene_sections.values():
            disclosure.click()
        self.app.processEvents()
        self.assertLess(page.scene_settings_host.height(), expanded_height)
        page.scene_settings_button.click()
        self.app.processEvents()
        self.assertEqual(page.view.rootObject().property("coveredLeft"), 0)
        collapsed_width = page.scene_detail_host.width()
        self.assertLess(collapsed_width, 322)
        page.data_details_button.click()
        QTest.qWait(30)
        self.assertEqual(page.scene_detail_host.width(), 322)
        page.data_details_button.click()
        QTest.qWait(30)
        self.assertEqual(page.scene_detail_host.width(), collapsed_width)
        page.close()

    def test_three_d_coloring_modes_filters_and_live_severity(self):
        class Client:
            def get(self, _path, _callback):
                return None

        page = NativeThreeDPage(Client())
        page._scene_tubes = [{"tube": 1, "type": "I", "length": 100, "category": "defect"},
                            {"tube": 2, "type": "II", "length": 200, "category": "ndd"}]
        page._scope_data = {"records": [{"thimble_id": 1, "indication": "FRE", "percent": 35}]}
        page.color_checks["length"].click()
        self.assertEqual(page._tube_color_mode(), "length")
        page.color_checks["type"].click()
        self.assertFalse(page.color_checks["length"].isChecked())
        self.assertEqual(page._tube_color_mode(), "type")
        page.color_checks["depth"].click()
        self.assertFalse(page.color_checks["type"].isChecked())
        self.assertEqual(page._tube_color_mode(), "depth")
        root = page.view.rootObject()
        self.assertEqual(root.property("tubeColors"), {"1": "#e5a83b", "2": "#667c8c"})
        page.color_checks["length"].click()
        self.assertEqual(page._tube_color_mode(), "depth")
        page.type_buttons["II"].click()
        self.assertEqual(page.type_filter.currentData(), "II")
        self.assertEqual(root.property("tubeColors"), {"1": "#6b7480", "2": "#667c8c"})
        page.type_buttons["II"].click()
        self.assertEqual(page.type_filter.currentData(), "")
        page.set_severity([10, 20, 40], ["#111111", "#222222", "#333333", "#444444"])
        self.assertEqual(root.property("tubeColors"), {"1": "#333333", "2": "#667c8c"})
        legend = [item.text() for item in page.color_legend.findChildren(native_windows.QLabel)
                  if item.text()]
        self.assertIn("20 – 40%", legend)
        page.load_scope()
        self.assertEqual(root.property("tubes"), [])
        self.assertEqual(root.property("tubeColors"), {})
        self.assertEqual(page._scene_tubes, [])
        page.close()

    def test_three_d_part_tree_text_tracks_theme_and_visibility(self):
        from PySide6.QtGui import QColor
        from qt_shell.native_components import workspace_styles

        class Client:
            def get(self, _path, _callback):
                return None

        page = NativeThreeDPage(Client())
        page.resize(800, 650)
        page.show()
        page.scene_settings_button.setChecked(True)
        for theme, text, muted in (("dark", "#e5eeec", "#a8b8b5"),
                                   ("light", "#23465b", "#647c8c"),
                                   ("dark", "#e5eeec", "#a8b8b5")):
            page.setStyleSheet(workspace_styles(theme))
            page.set_theme(theme)
            self.app.processEvents()
            visible, hidden = page.part_items["P01"], page.part_items["P03"]
            self.assertEqual(visible.foreground(0).style(), Qt.BrushStyle.NoBrush)
            self.assertEqual(hidden.foreground(0).color().name(), muted)
            image = page.part_tree.viewport().grab().toImage()
            for item, color in ((visible, text), (hidden, muted)):
                rect = page.part_tree.visualItemRect(item).intersected(image.rect())
                count = sum(image.pixelColor(x, y) == QColor(color)
                            for y in range(rect.top(), rect.bottom()+1)
                            for x in range(rect.left()+20, min(rect.right()+1, 180)))
                self.assertGreater(count, 5, (theme, color, count))
        page.toggle_part("P03")
        self.assertEqual(hidden.foreground(0).style(), Qt.BrushStyle.NoBrush)
        page.close()

    def test_three_d_parts_click_visibility_metadata_and_empty_scope(self):
        class Client:
            def get(self, _path, _callback):
                return None

        from qt_shell.native_components import workspace_styles
        from qt_shell.native_model_data import reference_channel
        page = NativeThreeDPage(Client())
        page.setStyleSheet(workspace_styles("light"))
        page.resize(800, 650)
        page.show()
        page.scene_settings_button.click()
        self.app.processEvents()
        root = page.view.rootObject()
        self.assertEqual(root.property("partVisibility"),
                         {"P01": True, "P02": True, "P03": False, "P04": False, "P05": True, "P06": True})
        nut = page.part_items["P04"]
        page.scene_settings_host.ensureWidgetVisible(page.part_tree)
        QTest.mouseClick(page.part_tree.viewport(), Qt.MouseButton.LeftButton,
                         pos=page.part_tree.visualItemRect(nut).center())
        self.app.processEvents()
        self.assertEqual(page.mode_tabs.currentIndex(), 1)
        self.assertEqual(page.display_mode.currentData(), "joint")
        self.assertTrue(root.property("partVisibility")["P04"])
        self.assertTrue(page.part_info_host.isVisible())
        self.assertIn("4,224 三角面", page.part_tags.text())
        self.assertIn("调整螺母", page.part_name.text())
        self.assertIn("图纸 AAX44226010", page.part_note.text())
        self.assertFalse(page.visibility_checks["enlargeTubes"].isChecked())
        self.assertTrue(page.ghost.isEnabled())
        self.assertTrue(page.scene_sections["整体布置"][0].isHidden())
        page._part_context(page.part_tree.visualItemRect(nut).center())
        self.assertFalse(root.property("partVisibility")["P04"])
        self.assertTrue(page.part_info_host.isHidden())
        page.show_part("P04")
        self.assertTrue(root.property("partVisibility")["P04"])
        self.assertEqual(page.part_tree.horizontalScrollBar().maximum(), 0)
        self.assertEqual(page.part_info_host.horizontalScrollBar().maximum(), 0)
        root.partSelected.emit("P01")
        self.assertIn("10,752", page.part_tags.text())
        page.tube_selector.setValue(22)
        self.assertEqual(root.property("selectedTube"), 22)
        self.assertEqual(root.property("detailLength"), reference_channel(22)["L"])
        self.assertIn(f"{reference_channel(22)['L']:.1f} mm",
                      [label.text() for label in page.part_info_body.findChildren(native_windows.QLabel)])
        page.display_mode.setCurrentIndex(page.display_mode.findData("full"))
        self.assertEqual(page.mode_tabs.currentIndex(), 2)
        self.assertTrue(page.part_info_host.isHidden())
        self.assertTrue(page.visibility_checks["enlargeTubes"].isChecked())
        page.display_mode.setCurrentIndex(0)
        self.assertFalse(page.ghost.isEnabled())
        self.assertTrue(page.scene_sections["整体布置"][0].isVisible())
        page.close()

    def test_three_d_station_dimensions_and_scale_follow_controls(self):
        class Client:
            def get(self, _path, _callback):
                return None

        page = NativeThreeDPage(Client())
        root = page.view.rootObject()
        self.assertFalse(page.dimensions.isEnabled())
        self.assertFalse(page.stations.isEnabled())
        page.mode_tabs.setCurrentIndex(1)
        self.assertTrue(page.dimensions.isEnabled())
        self.assertTrue(page.stations.isEnabled())
        labels = root.property("dimensionLabels")
        self.assertIn("socketOD", [label["id"] for label in labels])
        self.assertNotIn("nutOD", [label["id"] for label in labels])
        page.show_part("P04")
        self.assertIn("nutOD", [label["id"] for label in root.property("dimensionLabels")])
        page.toggle_part("P04")
        self.assertNotIn("nutOD", [label["id"] for label in root.property("dimensionLabels")])
        page.tube_selector.setValue(33)
        stations = root.property("stations")
        self.assertEqual(stations[-1]["distance"], root.property("detailLength"))
        self.assertEqual(stations[4]["label"], "P5?")
        page.dimensions.click()
        self.assertEqual(root.property("dimensionLabels"), [])
        page.stations.click()
        self.assertFalse(root.property("showStations"))
        page.visibility_checks["enlargeTubes"].click()
        page.dimensions.click()
        tube_label = next(label for label in root.property("dimensionLabels") if label["id"] == "tubeOD")
        self.assertEqual(tube_label["anchor"][0], 17.2)
        page.show()
        self.app.processEvents()
        page._hide_part_info()
        page.mode_tabs.setCurrentIndex(2)
        self.app.processEvents()
        self.assertFalse(root.property("suppressScale"))
        page.detection_filter_button.click()
        self.app.processEvents()
        self.assertTrue(root.property("suppressScale"))
        page.close()

    def test_report_draft_is_part_of_snapshot_payload(self):
        class Client:
            def get(self, path, callback):
                pass
            def post(self, path, payload, callback):
                self.payload = payload

        client = Client()
        page = NativeReportsPage(client)
        page.draft_edits = [{"key": "0:1:2", "value": "修改"}]
        page.preview_report()
        self.assertEqual(client.payload["draft_edits"], page.draft_edits)
        page._on_preview({"snapshot_id": "s", "editable_cells": [
            {"key": "0:1:2", "editable": True, "value": "修改"}
        ]}, None)
        self.assertTrue(page.edit_draft.isEnabled())
        page.clear_report_draft()
        self.assertIsNone(page.snapshot_id)
        self.assertEqual(page.draft_edits, [])
        page.close()

    def test_import_surfaces_recorded_quality_problems(self):
        class Client:
            def get(self, path, callback):
                pass

        page = DataWorkbench(Client())
        with patch("qt_shell.native_windows.QMessageBox.warning") as warning:
            page._on_import({"inserted": 3, "updated": 1, "skipped": 2, "error_count": 7}, None)
        self.assertIn("7 条质量问题", warning.call_args.args[2])
        self.assertIn("跳过 2 条", warning.call_args.args[2])
        page.close()

    def test_directory_import_posts_report_confirmation_and_policy(self):
        class Client:
            def __init__(self):
                self.requests = []

            def post(self, path, payload, callback=None, task_token=None):
                self.requests.append((path, payload, task_token))

            def get(self, path, callback):
                pass

        client = Client()
        page = DataWorkbench(client)
        page._import_path = r"C:\isolated\thimble-data"
        page._import_reports = [r"C:\isolated\thimble-data\TH1.RPT"]
        page._import_confirmation = {
            "confirmed": True,
            "candidates": [{"path": page._import_reports[0], "sha256": "r", "sum_sha256": "s"}],
        }
        page.import_policy = "review"
        page._run_directory_import()
        path, payload, token = client.requests[-1]
        self.assertEqual(path, "/api/import")
        self.assertEqual(payload["reports"], page._import_reports)
        self.assertEqual(payload["blank_indication_policy"], "review")
        self.assertTrue(payload["report_confirmation"]["confirmed"])
        self.assertTrue(token)
        page.close()

    def test_report_header_settings_roundtrip_in_isolated_user_data(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(native_windows, "USER_DATA", Path(temp)):
                page = NativeReportsPage(type("Client", (), {
                    "get": lambda *_args: None,
                    "post": lambda *_args: None,
                })())
                values = {"reportComponent": "指套管", "reportPlant": "测试电厂"}
                page._save_header(values)
                self.assertEqual(NativeReportsPage._load_saved_header()["reportPlant"], "测试电厂")
                self.assertEqual(NativeReportsPage._load_saved_header()["reportComponent"], "指套管")
                page.close()

    def test_analysis_page_renders_real_plate_and_preserves_summary(self):
        class Client:
            def __init__(self):
                self.requests = []
            def get(self, path, callback):
                self.requests.append(path)

        client = Client()
        page = NativeAnalyticsPage(client)
        page.analysis_site.setText("N")
        page.analysis_unit.setValue(1)
        page.analysis_outage.setText("N101")
        page._live_loaded({
            "summary": {"records": 53, "defect_tubes": 11, "ndd_tubes": 39,
                        "incomplete": 0, "missing_tubes": 0, "max_percent": 50},
            "plate": [{"tube": 1, "position": "R1", "records": 1,
                       "defects": 1, "max_percent": 35, "state": "堵管"}],
            "rule_note": "后端规则",
        }, None)
        self.assertEqual(page.plate_table.rowCount(), 1)
        self.assertEqual(page.plate_table.item(0, 3).text(), "存在缺陷")
        self.assertIn("缺陷管 11", page.analysis_status.text())
        page.load_live_analysis()
        self.assertTrue(client.requests[-1].startswith("/api/analysis/live?"))
        page.close()

    def test_account_management_obeys_permission_and_loads_roles(self):
        class Client:
            def __init__(self):
                self.requests = []
            def get(self, path, callback):
                self.requests.append(path)
                if path == "/api/auth/users":
                    callback({"users": [{"id": "u1", "username": "admin",
                                         "display_name": "管理员", "roles": ["admin"], "active": True}],
                              "roles": [{"code": "admin", "label": "系统管理员"}]}, None)
            def post(self, path, payload, callback):
                self.requests.append((path, payload))
        client = Client()
        page = NativeSettingsPage(client, {"username": "admin", "permissions": ["users.manage"]})
        self.assertEqual(page.users_table.rowCount(), 1)
        self.assertFalse(page.user_add.isHidden())
        self.assertEqual(page.users_table.item(0, 2).text(), "admin")
        page.close()

    def test_native_entry_does_not_import_webengine(self):
        root = Path(__file__).resolve().parents[2]
        env = dict(os.environ)
        env["THIMBLE_NATIVE_QT"] = "1"
        env["QT_QPA_PLATFORM"] = "offscreen"
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys, qt_shell.main; "
             "print(any(k.startswith('PySide6.QtWebEngine') for k in sys.modules))"],
            cwd=root, env=env, capture_output=True, text=True, check=True,
        )
        self.assertEqual(result.stdout.strip(), "False")


if __name__ == "__main__":
    unittest.main()
