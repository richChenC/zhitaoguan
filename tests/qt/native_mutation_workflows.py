"""Control-driven data mutations and permission checks on a disposable database."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QCheckBox, QDialogButtonBox, QLineEdit, QListWidget, QMessageBox, QPushButton,
)


def run(app, window, client, work, scope, request, wait, until):
    result, completed, errors = {}, [], []
    client.mutationFinished.connect(lambda path, data, error: completed.append((path, data, error)))

    def click(widget):
        assert widget.isVisible() and widget.isEnabled(), widget
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
        app.processEvents()

    def finish(path, action, timeout=30):
        before = len(completed)
        action()
        until(app, lambda: any(p == path for p, _, _ in completed[before:]), path, timeout)
        response = next((data, error) for p, data, error in completed[before:] if p == path)
        assert not response[1], response
        return response[0]

    def edit_cell(page, row, column, text):
        index = page.model.index(row, column)
        page.table.scrollTo(index)
        page.table.setCurrentIndex(index)
        page.table.setFocus()
        click(page.edit_button)
        until(app, lambda: any(e.isVisible() for e in page.table.findChildren(QLineEdit)), "inline editor")
        editor = next(e for e in page.table.findChildren(QLineEdit) if e.isVisible())
        editor.setText(text)
        QTest.keyClick(editor, Qt.Key.Key_Return)

    info = patch.object(QMessageBox, "information", return_value=QMessageBox.StandardButton.Ok)
    warning = patch.object(QMessageBox, "warning",
                           side_effect=lambda *args, **kwargs: (
                               QMessageBox.StandardButton.Yes if len(args) > 3 else
                               errors.append(str(args[-1])) or QMessageBox.StandardButton.Ok))
    yes = patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes)
    with info, warning, yes:
        window.context.set_scope(scope)
        window.nav.setCurrentIndex(0)
        page = window.workbench
        page.load_findings()
        until(app, lambda: page.search.isEnabled() and page.model.rows
              and page.model.rows[0]["outage"] == scope["outage"], "workbench scope")
        wait(app, 700)
        original = dict(page.model.rows[0])
        column = page.model.fields.index("analysis")
        changed = finish("/api/findings/edit",
                         lambda: edit_cell(page, 0, column, "NATIVE INLINE MUTATION VERIFIED"))
        assert changed["value"] == "NATIVE INLINE MUTATION VERIFIED"
        until(app, lambda: page.model.rows and page.model.rows[0].get("analysis") ==
              "NATIVE INLINE MUTATION VERIFIED", "inline persisted refresh")
        finish("/api/findings/edit", lambda: edit_cell(page, 0, column, original.get("analysis") or ""))
        result["inline_edit"] = {"finding_id": original["id"], "saved_and_reverted": True}
        page.clear_selection()
        page.table.scrollTo(page.model.index(0, 0))
        rect = page.table.visualRect(page.model.index(0, 0))
        QTest.mouseClick(page.table.viewport(), Qt.MouseButton.LeftButton,
                         pos=QPoint(rect.x() + 10, rect.center().y()))
        until(app, lambda: len(page.model.selected) == 1, "first checkbox")
        # The isolated database may contain fewer rows than the configured
        # page size.  Exercise a real second page when it exists; otherwise
        # select another visible row on the current page.  The workflow should
        # validate cross-page selection semantics without fabricating data.
        if page.pages >= 2:
            click(page.next)
            until(app, lambda: page.page == 2 and page.model.rows
                  and page.model.rows[0]["id"] != original["id"], "second page")
            rect = page.table.visualRect(page.model.index(0, 0))
            QTest.mouseClick(page.table.viewport(), Qt.MouseButton.LeftButton,
                             pos=QPoint(rect.x() + 10, rect.center().y()))
        else:
            assert page.model.rowCount() >= 2
            second = page.model.index(1, 0)
            rect = page.table.visualRect(second)
            QTest.mouseClick(page.table.viewport(), Qt.MouseButton.LeftButton,
                             pos=QPoint(rect.x() + 10, rect.center().y()))
        assert len(page.model.selected) == 2
        selected_ids = list(page.model.selected)
        exported = finish("/api/data-ledger/export", lambda: click(page.ledger))
        assert Path(exported["file_path"]).is_file(), exported
        before = request(client, "GET", "/api/findings?raw=1&sources=1&size=1")["total"]
        deleted = finish("/api/data/delete", lambda: click(page.delete))
        assert request(client, "GET", "/api/findings?raw=1&sources=1&size=1")["total"] == before - 2, deleted
        window.open_settings(6)
        maintenance = window.maintenance
        maintenance.tabs.setCurrentWidget(maintenance.recycle)
        maintenance.recycle.load()
        until(app, lambda: bool(maintenance.recycle.model.rows), "recycle batch")
        maintenance.recycle.table.selectRow(0)
        restored = finish("/api/recycle-bin/restore", lambda: click(maintenance.restore))
        assert request(client, "GET", "/api/findings?raw=1&sources=1&size=1")["total"] == before, restored
        result["selection_delete_restore"] = {"ids": selected_ids, "restored_total": before,
                                              "ledger_exists": True}
        maintenance.tabs.setCurrentWidget(maintenance.audit)
        audit = maintenance.audit
        audit.load()
        until(app, lambda: bool(audit.model.rows) and audit.status.text() != "正在加载...", "audit records")
        row = next(i for i, item in enumerate(audit.model.rows) if audit.record_scope(item))
        expected_scope = audit.record_scope(audit.model.rows[row])
        def locate_record():
            dialog = app.activeModalWidget()
            if dialog is None:
                return
            control = next(b for b in dialog.findChildren(QPushButton) if b.text() == "定位检测范围")
            click(control)
        QTimer.singleShot(70, locate_record)
        index = audit.model.index(row, 0)
        audit.table.scrollTo(index)
        QTest.mouseClick(audit.table.viewport(), Qt.MouseButton.LeftButton,
                         pos=audit.table.visualRect(index).center())
        QTest.mouseDClick(audit.table.viewport(), Qt.MouseButton.LeftButton,
                         pos=audit.table.visualRect(index).center())
        until(app, lambda: not window.settings_dialog.isVisible(), "audit context jump")
        assert window.context.scope["outage"] == expected_scope["outage"]
        assert window.stack.currentWidget() is window.workbench
        result["audit_context"] = {"outage": expected_scope["outage"], "native_detail_jump": True}
        window.settings_dialog.hide()

        states = window.stack.widget(1)
        window.nav.setCurrentIndex(4)
        window.context.set_scope(scope)
        states.load()
        until(app, lambda: bool(states.model.rows), "state rows")
        compound_before = next(dict(r) for r in states.model.rows if r["thimble_id"] == 1)
        before_bulk = len(completed)
        click(states.bulk_normal)
        until(app, lambda: any(path in {"/api/states/batch-preview", "/api/states/batch"}
                               for path, _, _ in completed[before_bulk:]),
              "bulk maintenance preview")
        preview_event = next(
            (event for event in completed[before_bulk:]
             if event[0] == "/api/states/batch-preview"),
            None,
        )
        bulk_preview = preview_event[1] if preview_event else {}
        if preview_event and int((bulk_preview or {}).get("affected", 0) or 0) > 0:
            until(app, lambda: any(path == "/api/states/batch"
                                   for path, _, _ in completed[before_bulk:]),
                  "bulk maintenance save")
            batch_event = next(event for event in completed[before_bulk:]
                               if event[0] == "/api/states/batch")
            assert not batch_event[2], batch_event
            bulk_changed = int((batch_event[1] or {}).get("changed", 0) or 0)
        else:
            # A fully maintained scope is a valid no-op.  The UI must report
            # it without issuing a duplicate write.
            bulk_changed = 0
        until(app, lambda: len(states.model.rows) == 50, "bulk maintenance 50 tubes")
        compound_after = next(r for r in states.model.rows if r["thimble_id"] == 1)
        assert compound_after["events"] == compound_before["events"]
        assert compound_after["offset_mm"] == compound_before["offset_mm"]
        for fmt in ("xlsx", "docx"):
            states.export_format.setCurrentIndex(states.export_format.findData(fmt))
            data = finish("/api/states/export", lambda: click(states.export_button))
            assert data["rows"] >= 50, data
            if fmt == "docx":
                import zipfile
                with zipfile.ZipFile(data["file_path"]) as document:
                    assert "UI REGRESSION COMPOUND EVENT" in document.read("word/document.xml").decode("utf-8")
        removable = next((i for i, row in enumerate(states.model.rows)
                          if row.get("note") == "人工批量确认正常"), None)
        removed_tube = None
        if removable is not None:
            removed_tube = states.model.rows[removable]["thimble_id"]
            states.table.selectRow(removable)
            finish("/api/states/delete-batch", lambda: click(states.delete_button))
            until(app, lambda: len(states.model.rows) == 49, "state deletion")
        result["bulk_states"] = {"confirmed": 50, "existing_compound_preserved": True,
                                  "changed": bulk_changed, "exports": ["xlsx", "docx"],
                                  "revoked_tube": removed_tube}

        reports = window.stack.widget(4)
        combinations = request(client, "GET", "/api/overview")["combinations"]
        grouped = defaultdict(list)
        for item in combinations:
            grouped[(item["site"], item["unit_id"])].append(item["outage"])
        (site, unit), outages = next((key, sorted(codes)) for key, codes in grouped.items() if len(codes) >= 2)
        window.context.set_scope({"site": site, "unit": str(unit), "outage": outages[-1]})
        window.nav.setCurrentIndex(3)
        reports.report_tabs.setCurrentIndex(1)
        assert not reports.use_selected.isEnabled()
        assert not reports.use_selected.isChecked()
        until(app, lambda: reports.history_combo.findText(outages[0]) >= 0, "earlier outage option")
        reports.history_combo.setCurrentText(outages[0])
        preview = finish("/api/reports/preview", lambda: click(reports.preview))
        assert preview["kind"] == "comparison"
        assert preview.get("coverage_complete") is True, preview
        assert preview["rows"] > 0
        assert all(scope["tubes"] == 50 and not scope["missing_tubes"]
                   for scope in preview["detection_counts"])
        comparison_exports = []
        for fmt in ("docx", "xlsx"):
            reports.export_format.setCurrentIndex(reports.export_format.findData(fmt))
            exported = finish("/api/reports/export", lambda: click(reports.export))
            output = exported.get("file_path") or exported.get("path")
            assert output and Path(output).is_file(), exported
            comparison_exports.append(fmt)
        result["comparison_report"] = {"old": outages[0], "new": outages[-1],
                                        "rows": preview["rows"], "exports": comparison_exports}
        window.grab().save(str(work / "screens" / "comparison-controls.png"))
        reports.report_tabs.setCurrentIndex(0)
        assert not reports.draft_edits and reports.snapshot_id is None

        # Create an actual viewer through the native account editor.
        window.open_settings(4)
        account = window.settings_page
        until(app, lambda: bool(account.roles), "account roles")
        def create_viewer():
            dialog = app.activeModalWidget()
            edits = dialog.findChildren(QLineEdit)
            edits[0].setText("nativeviewer")
            edits[1].setText("Native Viewer")
            edits[2].setText("NativeViewer@2026")
            roles = dialog.findChild(QListWidget)
            for i in range(roles.count()):
                item = roles.item(i)
                item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) == "viewer"
                                   else Qt.CheckState.Unchecked)
            click(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok))
        QTimer.singleShot(60, create_viewer)
        created = finish("/api/auth/users", lambda: click(account.user_add))
        from qt_shell.native_client import NativeClient
        viewer = NativeClient(client.base_url, app)
        viewer_user = request(viewer, "POST", "/api/auth/login",
                              {"username": "nativeviewer", "password": "NativeViewer@2026"})["user"]
        denied = {}
        viewer.post("/api/state", {"outage": scope["outage"], "unit_id": int(scope["unit"]),
                                   "thimble_id": 50, "state": "normal"},
                    lambda data, error: denied.update(data=data, error=error))
        until(app, lambda: "error" in denied, "viewer forbidden mutation")
        assert denied["error"], denied
        assert "state.write" not in viewer_user["permissions"]
        viewer.abort_all()
        result["accounts"] = {"created_in_native_editor": True, "viewer_write_rejected": True}
        window.settings_dialog.hide()
        window.task_center.show()
        assert window.task_center.unread == 0
        assert any(item["status"] == "完成" for item in window.task_center.items.values())
        window.task_center.dialog.grab().save(str(work / "screens" / "task-center.png"))
        window.task_center.dialog.close()
        assert not errors, errors
    return result


def run_state_import(app, window, client, work, request, wait, until):
    import base64
    from PySide6.QtWidgets import QFileDialog, QTableView
    project = Path(__file__).resolve().parents[3]
    sources = project / "02_项目原始资料" / "03_原始检测数据" / "指套管数据测试 202007"
    paths = [sources / "指套管割管移位统计（含阳江、防城港、红沿河）.xlsx",
             sources / "宁德" / "宁德4台机组指套管割管移位信息汇总20200804.xls"]
    page = window.stack.widget(1)
    window.nav.setCurrentIndex(4)
    results, errors = [], []
    for source in paths:
        preview = request(client, "POST", "/api/states/import-preview",
                          {"filename": source.name, "content": base64.b64encode(source.read_bytes()).decode("ascii"),
                           "direction_policy": "pending"}, timeout=60)
        assert preview["rows"], preview
        before = len(request(client, "GET", "/api/states")["items"])
        response, selected, dialogs, unsigned = {}, [], [], []
        def choose_rows():
            dialog = app.activeModalWidget()
            table = dialog.findChild(QTableView, "stateImportTable") if dialog else None
            if table is None:
                QTimer.singleShot(50, choose_rows)
                return
            model = table.model()
            for index, row in enumerate(model.rows):
                if model.checked[index] and model.needs_direction(row):
                    # Real source direction is unknown; leave it out of the
                    # business import rather than guessing its sign.
                    unsigned.append(row)
                    model.setData(model.index(index, 0), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
            selected.extend(model.selected_rows())
            dialogs.append(dialog)
            dialog.grab().save(str(work / "screens" / f"state-import-{source.suffix[1:]}.png"))
            if not selected:
                dialog.reject()
            else:
                QTest.mouseClick(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok),
                                 Qt.MouseButton.LeftButton)
        def completed(path, data, error):
            if path == "/api/states/batch":
                response.update(data=data, error=error)
        client.mutationFinished.connect(completed)
        with patch.object(QFileDialog, "getOpenFileName", return_value=(str(source), "")), \
             patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No), \
             patch.object(QMessageBox, "information", return_value=QMessageBox.StandardButton.Ok), \
             patch.object(QMessageBox, "warning", side_effect=lambda *args: errors.append(str(args[-1]))):
            QTimer.singleShot(50, choose_rows)
            QTest.mouseClick(page.import_button, Qt.MouseButton.LeftButton)
            until(app, lambda: bool(dialogs) and (not selected or "data" in response), "real state import", 60)
            wait(app, 100)
        client.mutationFinished.disconnect(completed)
        assert not response.get("error"), response
        after = request(client, "GET", "/api/states")["items"]
        assert len(after) == before + len(selected), (before, len(after), len(selected), response)
        for chosen in selected:
            stored = next(row for row in after if (row["outage"], row["unit_id"], row["thimble_id"]) ==
                          (chosen["outage"], chosen["unit_id"], chosen["thimble_id"]))
            assert set(stored["events"]) == set(chosen["events"]), (stored, chosen)
            assert stored.get("offset_mm") == chosen.get("offset_mm")
            assert stored.get("unsigned_offset_mm") == chosen.get("unsigned_offset_mm")
        results.append({"file": source.name, "recognized": len(preview["rows"]), "selected": len(selected),
                        "missing_scopes": len(preview.get("missing_scopes") or []), "database_rows": len(after),
                        "unsigned_rows_held_for_confirmation": len(unsigned)})
    assert not errors, errors
    return results
