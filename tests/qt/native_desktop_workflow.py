"""Native Qt desktop workflow regression on an isolated real-data database.

This script exercises the actual Widgets shell (not the compatibility WebEngine
shell), captures each page, and records the data counts observed by the UI.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path


QT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = QT_ROOT.parent
ARTIFACT_ROOT = PROJECT_ROOT / "05_测试与验证" / "03_自动化临时产物"


def wait(app, milliseconds: int) -> None:
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()
    app.processEvents()


def until(app, predicate, description, timeout=20):
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        app.processEvents()
        if predicate():
            return
        wait(app, 50)
    raise AssertionError(f"timeout waiting for {description}")


def request(client, method: str, path: str, payload=None, timeout=12):
    from PySide6.QtCore import QEventLoop, QTimer

    result = {}
    loop = QEventLoop()

    def done(data, error):
        result["data"] = data
        result["error"] = error
        loop.quit()

    if method == "GET":
        client.get(path, done)
    else:
        client.post(path, payload or {}, done)
    QTimer.singleShot(timeout * 1000, loop.quit)
    loop.exec()
    if "data" not in result:
        raise RuntimeError(f"request timeout: {method} {path}")
    if result["error"]:
        raise RuntimeError(f"{method} {path}: {result['error']}")
    return result["data"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, help="isolated real-data SQLite database")
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    work = ARTIFACT_ROOT / f"native-desktop-{stamp}"
    work.mkdir(parents=True, exist_ok=True)
    (work / "screens").mkdir()
    source = args.database or (QT_ROOT / "user-data" / "data" / "thimble.db")
    db = work / "thimble.db"
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as src, sqlite3.connect(db) as dest:
        src.backup(dest)
    with sqlite3.connect(db) as conn:
        conn.executescript(
            "DELETE FROM login_sessions; DELETE FROM user_roles; DELETE FROM users;"
        )
        conn.commit()

    os.environ["THIMBLE_QT_TEST_DATA_ROOT"] = str(work)
    os.environ["THIMBLE_ALLOW_MULTI_INSTANCE"] = "1"
    os.environ["THIMBLE_DB_PATH"] = str(db)
    os.environ["THIMBLE_DATA_DIR"] = str(work / "data")
    os.environ["THIMBLE_OUTPUT_DIR"] = str(work / "output" / "excel")
    os.environ["THIMBLE_REPORT_DIR"] = str(work / "output" / "reports")
    os.environ["THIMBLE_PORT"] = "0"
    os.environ["THIMBLE_NATIVE_QT"] = "1"
    os.environ.setdefault("QSG_RENDER_LOOP", "basic")
    sys.path.insert(0, str(QT_ROOT))

    from PySide6.QtCore import QPoint, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (QApplication, QCheckBox, QDialogButtonBox, QLineEdit,
                                  QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QWizard)
    from unittest.mock import patch
    from qt_shell.backend_service import BackendService
    from qt_shell.log_utils import ServiceLog
    from qt_shell.native_client import NativeClient
    from qt_shell.native_windows import (
        NativeAnalyticsPage,
        NativeMainWindow,
        NativeReportsPage,
        NativeSettingsPage,
        NativeStatePage,
        NativeThreeDPage,
    )

    app = QApplication(sys.argv)
    backend = BackendService(ServiceLog(work / "service.log"))
    report = {
        "database": str(db),
        "screens": {},
        "errors": [],
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    window = None
    try:
        base_url = backend.start()
        client = NativeClient(base_url, app)
        setup = request(
            client, "POST", "/api/auth/setup",
            {"username": "qtworkflow", "password": "QtWorkflow@2026",
             "display_name": "Qt 工作流回归"},
        )
        login = request(
            client, "POST", "/api/auth/login",
            {"username": "qtworkflow", "password": "QtWorkflow@2026"},
        )
        user = login["user"]
        report["auth"] = {
            "setup": bool(setup.get("ok")),
            "username": user.get("username"),
            "permissions": len(user.get("permissions") or []),
        }

        window = NativeMainWindow(client, user)
        window.resize(1480, 940)
        window.show()
        wait(app, 2500)
        overview = request(client, "GET", "/api/overview")
        candidates = overview.get("combinations") or []
        chosen = next((c for c in candidates if c["outage"] == "H209"), candidates[0] if candidates else None)
        if not chosen:
            raise AssertionError("No real inspection scope available")
        scope = {"site": chosen["site"], "unit": str(chosen["unit_id"]), "outage": chosen["outage"]}
        report["scope"] = scope
        window.context.set_scope(scope)
        wait(app, 1000)
        def click(control):
            assert control.isVisible() and control.isEnabled(), control.text()
            QTest.mouseClick(control, Qt.MouseButton.LeftButton,
                             pos=QPoint(8, control.height() // 2) if isinstance(control, QCheckBox) else QPoint())
            app.processEvents()

        # Open the actual native maintenance editor and save a compound event.
        states = window.stack.widget(1)
        window.nav.setCurrentIndex(window._navigation_indices.index(1))
        until(app, lambda: bool(states.all_rows), "maintenance records")
        states.record_scope.set_scope(scope)
        states.record_scope._emit()
        wait(app, 100)
        existing = next((i for i, row in enumerate(states.model.rows)
                         if row["thimble_id"] == 1), None)
        if existing is not None:
            target = states.model.index(existing, 0)
            states.table.scrollTo(target)
            QTest.mouseClick(states.table.viewport(), Qt.MouseButton.LeftButton,
                             pos=states.table.visualRect(target).center())
        maintenance_note = "UI REGRESSION COMPOUND EVENT " + stamp
        def maintain():
            dialog = app.activeModalWidget()
            assert dialog is not None
            dialog.findChild(QLineEdit, "maintenanceOutage").setText(scope["outage"])
            dialog.findChild(QSpinBox, "maintenanceUnit").setValue(int(scope["unit"]))
            dialog.findChild(QSpinBox, "maintenanceTube").setValue(1)
            for event in ("shifted", "plugged", "normal", "cut", "replaced"):
                check = dialog.findChild(QCheckBox, "maintenance_" + event)
                if check and check.isChecked() != (event in {"shifted", "plugged"}):
                    click(check)
            dialog.findChild(QLineEdit, "maintenanceOffset").setText("+12.5")
            dialog.findChild(QPlainTextEdit, "maintenanceNote").setPlainText(maintenance_note)
            click(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok))
        with patch.object(QMessageBox, "information", return_value=QMessageBox.StandardButton.Ok), \
                patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok):
            QTimer.singleShot(50, maintain)
            click(states.advanced if existing is not None else states.new_state)
            until(app, lambda: any(row.get("note") == maintenance_note
                                  for row in states.model.rows), "compound maintenance saved")
        maintained = request(client, "GET", "/api/states")["items"]
        maintained = next(r for r in maintained if r["outage"] == scope["outage"]
                          and r["unit_id"] == int(scope["unit"]) and r["thimble_id"] == 1)
        assert set(maintained["events"]) == {"shifted", "plugged"}, maintained
        assert maintained["offset_mm"] == 12.5, maintained
        report["state_ui"] = {"events": maintained["events"], "offset_mm": maintained["offset_mm"],
                              "rows": states.model.rowCount()}
        original_note = maintained["note"]
        inline_note = "INLINE STATE NOTE " + stamp

        def inline_state_note(value):
            row = next(i for i, record in enumerate(states.model.rows) if record["thimble_id"] == 1)
            index = states.model.index(row, states.model.fields.index("note"))
            states.table.scrollTo(index)
            states.findChild(QScrollArea).ensureWidgetVisible(states.table)
            wait(app, 100)
            QTest.mouseClick(states.table.viewport(), Qt.MouseButton.LeftButton,
                             pos=states.table.visualRect(index).center())
            QTest.mouseDClick(states.table.viewport(), Qt.MouseButton.LeftButton,
                             pos=states.table.visualRect(index).center())
            app.processEvents()
            editor = QApplication.focusWidget()
            if not isinstance(editor, QLineEdit):
                window.grab().save(str(work / "screens" / "inline-editor-failure.png"))
                raise AssertionError(f"Inline editor missing: focus={type(editor).__name__}, "
                                     f"current={states.table.currentIndex().column()}, "
                                     f"editable={states.model.editable}, rect={states.table.visualRect(index)}")
            editor.setText(value)
            QTest.keyClick(editor, Qt.Key.Key_Return)
            app.processEvents()
            action_index = states.model.index(row, states.model.fields.index("_actions"))
            states.table.scrollTo(action_index)
            host = states.table.indexWidget(action_index)
            save_row = next(control for control in host.findChildren(QPushButton) if control.text() == "保存")
            click(save_row)
            until(app, lambda: any(record.get("note") == value for record in states.model.rows),
                  "inline maintenance note persisted")

        inline_state_note(inline_note)
        saved = request(client, "GET", "/api/states")["items"]
        saved = next(record for record in saved if record["outage"] == scope["outage"]
                     and record["unit_id"] == int(scope["unit"]) and record["thimble_id"] == 1)
        assert set(saved["events"]) == {"shifted", "plugged"}
        assert saved["offset_mm"] == 12.5 and saved["source"] == maintained["source"]
        inline_state_note(original_note)
        report["state_inline_ui"] = {"saved_and_reverted": True, "compound_events_preserved": True,
                                      "offset_preserved": True, "source_preserved": True}

        # Use independent batch controls over heterogeneous maintenance facts.
        batch_scope = {"site": "N", "unit": "1", "outage": "N199"}
        originals = [
            {"outage": "N199", "unit_id": 1, "thimble_id": 1, "state": "shifted",
             "events": ["shifted"], "offset_mm": -12, "note": "BATCH ORIGINAL ONE", "source": "REGISTER ONE"},
            {"outage": "N199", "unit_id": 1, "thimble_id": 2, "state": "shifted",
             "events": ["shifted"], "offset_mm": None, "unsigned_offset_mm": 42,
             "direction": "pending", "note": "BATCH ORIGINAL TWO", "source": "REGISTER TWO"},
        ]
        for original in originals:
            request(client, "POST", "/api/state", original)
        states.load()
        until(app, lambda: any(row["outage"] == "N199" and row["thimble_id"] == 2
                              for row in states.all_rows), "batch fixture")
        states.set_workspace_scope(batch_scope)
        states.findChild(QScrollArea).ensureWidgetVisible(states.batch_mode)
        wait(app, 100)
        click(states.batch_mode)
        assert states.single_editor.isHidden() and states.batch_editor.isVisible()
        for tube in (1, 2):
            point = states.plate.hit_regions[tube].center().toPoint()
            QTest.mouseClick(states.plate, Qt.MouseButton.LeftButton, pos=point)
        assert states.plate.selected == {1, 2}, states.plate.selected
        states.batch_state.setCurrentIndex(states.batch_state.findData("shifted"))
        assert states.batch_offset.text() == ""
        states.batch_state.setCurrentIndex(states.batch_state.findData("plugged"))
        states.batch_note.setPlainText("BATCH UI APPEND")
        states.findChild(QScrollArea).ensureWidgetVisible(states.batch_apply)
        preview_details = {}
        def confirm_batch():
            dialog = app.activeModalWidget()
            if dialog is None or dialog.windowTitle() != "批量维护影响预览":
                return
            confirm_timer.stop()
            from PySide6.QtWidgets import QTableWidget
            table = dialog.findChild(QTableWidget)
            assert table.rowCount() == 2
            preview_details["rows"] = table.rowCount()
            dialog.grab().save(str(work / "screens" / "state-batch-preview.png"))
            click(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok))
        with patch.object(QMessageBox, "information", return_value=QMessageBox.StandardButton.Ok):
            confirm_timer = QTimer(window)
            confirm_timer.timeout.connect(confirm_batch)
            confirm_timer.start(100)
            click(states.batch_apply)
            until(app, lambda: not states._batch_busy and any(
                row["outage"] == "N199" and "BATCH UI APPEND" in row["note"]
                for row in states.all_rows), "batch UI append saved")
            confirm_timer.stop()
        saved = request(client, "GET", "/api/states")["items"]
        saved = sorted([row for row in saved if row["outage"] == "N199" and row["thimble_id"] in (1, 2)],
                       key=lambda row: row["thimble_id"])
        for row, original in zip(saved, originals):
            assert set(row["events"]) == {"shifted", "plugged"}, row
            assert row["note"] == original["note"] + "\nBATCH UI APPEND", row
            assert row["source"] == original["source"], row
            assert row["offset_mm"] == original["offset_mm"], row
        assert saved[1]["unsigned_offset_mm"] == 42
        report["state_batch_ui"] = {"preview_rows": preview_details["rows"], "append_preserved_each_note": True,
                                     "sources_preserved": True, "signed_and_unknown_distances_preserved": True}
        click(states.batch_mode)
        states.set_workspace_scope(scope)
        window.context.set_scope(scope)

        # Maintain the old stack identities while testing the top navigation.
        pages = [
            ("workbench", 0),
            ("states", 1),
            ("three_d", 2),
            ("analytics", 3),
            ("reports", 4),
            ("maintenance", 5),
            ("settings", 6),
        ]
        for name, index in pages:
            if index < 5:
                window.nav.setCurrentIndex(window._navigation_indices.index(index))
                page = window.stack.widget(index)
            else:
                window.open_settings(6 if index == 5 else 0)
                page = window.maintenance if index == 5 else window.settings_page
            wait(app, 1200)
            item = {
                "class": type(page).__name__,
            }
            if name == "workbench":
                item["rows"] = page.model.rowCount()
            elif name == "states":
                item["rows"] = page.table.model().rowCount() if page.table.model() else 0
            elif name == "three_d":
                scope_index = next((i for i in range(page.scope.count()) if
                                    (page.scope.itemData(i) or {}).get("outage") == scope["outage"]), 0)
                page.scope.setCurrentIndex(scope_index)
                wait(app, 1800)
                root = page.view.rootObject()
                item["scope_count"] = page.scope.count()
                item["tube_count"] = len(root.property("tubes") or []) if root else 0
                item["status"] = page.status.text()
            elif name == "analytics":
                page.analysis_site.setText(scope["site"])
                page.analysis_unit.setValue(int(scope["unit"]))
                page.analysis_outage.setText(scope["outage"])
                page.load_live_analysis()
                wait(app, 1800)
                item["plate_rows"] = page.plate_table.rowCount()
                item["status"] = page.analysis_status.text()
                page.load_complex_analysis()
                wait(app, 1800)
                item["complex_loaded"] = bool(page.visualization.data)
                item["trend_rows"] = page.trend_table.rowCount()
            elif name == "reports":
                item["template_count"] = page.templates.count()
                page.site.setText(scope["site"])
                page.unit.setValue(int(scope["unit"]))
                page.outage.setText(scope["outage"])
                click(page.preview)
                until(app, lambda: bool(page.snapshot_id), "native report preview")
                item["preview_ready"] = bool(page.snapshot_id)
                item["preview_rows"] = len((page.preview_payload or {}).get("draft_edits") or [])
                item["host_size"] = [page.preview_text.host.width(), page.preview_text.host.height()]
                item["visible_table_width"] = page.preview_text.tables[0].visibleRegion().boundingRect().width()
                assert item["visible_table_width"] > 500, item
            elif name == "maintenance":
                item["tabs"] = page.tabs.count()
            elif name == "settings":
                item["tabs"] = window.settings_dialog.nav.count()
                item["backup_enabled"] = page.backup_now.isEnabled()
                item["restore_enabled"] = page.restore_backup.isEnabled()
            shot = work / "screens" / f"{name}.png"
            if name == "three_d" and hasattr(page.view, "grabWindow"):
                page.view.grabWindow().save(str(shot))
            elif index >= 5:
                window.settings_dialog.grab().save(str(shot))
            else:
                window.grab().save(str(shot))
            item["screenshot"] = str(shot)
            report["screens"][name] = item

        window.settings_dialog.hide()
        from native_real_workflows import run
        report["real_controls"] = run(app, window, client, work, scope, request, wait, until)
        from native_mutation_workflows import run as run_mutations
        report["mutation_controls"] = run_mutations(app, window, client, work, scope, request, wait, until)
        from native_mutation_workflows import run_state_import
        report["state_import_controls"] = run_state_import(app, window, client, work, request, wait, until)

        backup = request(
            client, "POST", "/api/backup", {"note": "原生 Qt 工作流回归"}
        )
        backup_path = str(backup.get("path") or "")
        backup_list = request(client, "GET", "/api/backups")
        if not backup_path:
            backup_path = str((backup_list.get("items") or [{}])[0].get("path") or "")
        validated = request(
            client, "POST", "/api/backup-validate", {"path": backup_path}
        )
        with sqlite3.connect(db) as connection:
            before = connection.execute("SELECT COUNT(*) FROM findings WHERE is_deleted=0").fetchone()[0]
        finding = request(client, "GET", "/api/findings?raw=1&size=20")["items"][0]
        request(client, "POST", "/api/findings/edit",
                {"id": finding["id"], "field": "analysis", "value": "恢复前临时修改",
                 "expected_value": finding.get("analysis")})
        restored = request(client, "POST", "/api/restore", {"path": backup_path}, timeout=40)
        from PySide6.QtCore import QEventLoop, QTimer
        expired = {}
        loop = QEventLoop()
        client.get("/api/auth/me", lambda data, error: (expired.update(data=data, error=error), loop.quit()))
        QTimer.singleShot(10000, loop.quit)
        loop.exec()
        with sqlite3.connect(db) as connection:
            after = connection.execute("SELECT analysis FROM findings WHERE id=?", (finding["id"],)).fetchone()[0]
        relogin = request(
            client, "POST", "/api/auth/login",
            {"username": "qtworkflow", "password": "QtWorkflow@2026"},
        )
        rules_before = request(client, "GET", "/api/analysis-rules")
        created_rule = request(
            client, "POST", "/api/analysis-rules",
            {"name": "Qt 工作流回归规则", "match_tolerance_mm": 1.25,
             "note": "隔离数据库回归"},
        )
        rules_after = request(client, "GET", "/api/analysis-rules")
        report["backup_restore"] = {
            "created": bool(backup_path),
            "listed": any(item.get("path") == backup_path for item in backup_list.get("items", [])),
            "integrity": validated.get("integrity"),
            "findings": validated.get("findings"),
            "restored": bool(restored.get("safety_backup")),
            "relogin": bool(relogin.get("user")),
            "changed_value_restored": after == finding.get("analysis"),
            "old_session_rejected": bool(expired.get("error")),
            "count_before": before,
            "count_after": restored.get("findings_after"),
        }
        report["analysis_rules"] = {
            "before": len(rules_before.get("rules") or rules_before.get("items") or []),
            "created": bool(created_rule.get("id") or created_rule.get("version")),
            "after": len(rules_after.get("rules") or rules_after.get("items") or []),
        }

        report["passed"] = (
            report["auth"]["setup"]
            and report["screens"]["workbench"].get("rows", 0) > 0
            and report["screens"]["three_d"].get("tube_count") == 50
            and report["screens"]["analytics"].get("plate_rows", 0) == 50
            and report["screens"]["analytics"].get("complex_loaded") is True
            and report["screens"]["reports"].get("template_count", 0) >= 2
            and report["screens"]["reports"].get("preview_ready") is True
            and report["screens"]["settings"].get("tabs", 0) >= 4
            and report["backup_restore"].get("integrity") == "ok"
            and report["backup_restore"].get("restored") is True
            and report["backup_restore"].get("relogin") is True
            and report["backup_restore"].get("changed_value_restored") is True
            and report["backup_restore"].get("old_session_rejected") is True
            and report["analysis_rules"].get("created") is True
            and report["analysis_rules"].get("after", 0) >= report["analysis_rules"].get("before", 0)
        )
    except Exception as exc:
        import traceback
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        report["traceback"] = traceback.format_exc()
        report["passed"] = False
    finally:
        if window is not None:
            window.close()
            window.deleteLater()
            wait(app, 100)
        backend.stop()
        report["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        (work / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
        client.abort_all() if "client" in locals() else None
        app.processEvents()
        app.quit()
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())
