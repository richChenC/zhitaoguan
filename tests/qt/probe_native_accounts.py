"""Real account controls, TRAE layout measurements and isolated SQLite contracts."""
from contextlib import closing
from datetime import datetime
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import traceback

from native_desktop_workflow import request, until, wait
from probe_native_import_quality import hashes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("reference", type=Path)
    parser.add_argument("--actions-reference", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    work = root.parent / "05_测试与验证/03_自动化临时产物" / (
        "native-accounts-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    work.mkdir(parents=True)
    database = work / "data/thimble.db"
    database.parent.mkdir()
    formal = root / "user-data/data/thimble.db"
    preferences = root / "user-data/native-preferences.json"
    before, pref_before = hashes(formal), hashlib.sha256(preferences.read_bytes()).hexdigest()
    with closing(sqlite3.connect(formal.as_uri() + "?mode=ro", uri=True)) as source, \
            closing(sqlite3.connect(database)) as target:
        source.backup(target)
        target.executescript("DELETE FROM login_sessions; DELETE FROM user_roles; DELETE FROM users;")
        target.commit()
    for key, value in {
        "THIMBLE_QT_TEST_DATA_ROOT": work, "THIMBLE_DB_PATH": database,
        "THIMBLE_DATA_DIR": database.parent, "THIMBLE_OUTPUT_DIR": work / "exports",
        "THIMBLE_REPORT_DIR": work / "reports", "THIMBLE_PORT": "0",
        "THIMBLE_ALLOW_MULTI_INSTANCE": "1", "QSG_RENDER_LOOP": "basic",
    }.items():
        os.environ[key] = str(value)
    from PySide6.QtCore import QPoint, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox
    from qt_shell.backend_service import BackendService
    from qt_shell.log_utils import ServiceLog
    from qt_shell.native_accounts import AccountSecurityDialog, AccountWorkspace, account_styles
    from qt_shell.native_client import NativeClient
    from qt_shell.native_windows import NativeMainWindow
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    backend = BackendService(ServiceLog(work / "service.log"))
    result = {"passed": False, "errors": [], "samples": []}
    window = client = viewer = readonly = security = None
    try:
        client = NativeClient(backend.start(), app)
        credentials = {"username": "accountsprobe", "display_name": "Accounts Probe", "password": "AccountsProbe@2026"}
        request(client, "POST", "/api/auth/setup", credentials)
        user = request(client, "POST", "/api/auth/login", credentials)["user"]
        window = NativeMainWindow(client, user)
        window.show()
        window.open_settings(4)
        dialog, panel = window.settings_dialog, window.settings_dialog.account_workspace
        host = dialog.stack.widget(4)
        until(app, lambda: panel.fresh and not panel.reading, "account directory")
        if args.actions_reference:
            actions = json.loads(args.actions_reference.read_text(encoding="utf-8-sig"))
            result["security_samples"] = []
            dialog.hide()
            QTest.mouseClick(window.account_button, Qt.MouseButton.LeftButton)
            until(app, lambda: window._account_security.isVisible(), "navigation security dialog")
            security = window._account_security
            for sample in actions["security"]:
                theme = sample["theme"]
                window.context.preferences.save(theme=theme)
                window.apply_preferences()
                security.setStyleSheet(dialog.styleSheet())
                security.duties.setChecked(sample["expanded"])
                security._toggle_duties()
                wait(app, 100)
                origin = sample["controls"][":scope"][0]["rect"]
                controls = {"h2": [security.title], ".account-dialog-identity": [security.identity],
                            ".account-dialog-role": [security.role, security.duties_note],
                            "input": security.fields, ".auth-message": [security.status],
                            "menu": [security.actions], "button": [
                                security.close_button, security.preferences, security.logout, security.submit]}
                actual, differences = {}, {}
                for key, widgets in controls.items():
                    actual[key], differences[key] = [], []
                    for control, reference in zip(widgets, sample["controls"][key]):
                        point = control.mapTo(security, QPoint())
                        bounds = dict(x=point.x(), y=point.y(), width=control.width(), height=control.height())
                        ref = reference["rect"]
                        expected = {**ref, "x": ref["x"] - origin["x"], "y": ref["y"] - origin["y"]}
                        actual[key].append(bounds)
                        if control.isVisible():
                            differences[key].append({k: round(v - expected[k], 3) for k, v in bounds.items()})
                result["security_samples"].append({"theme": theme, "expanded": sample["expanded"],
                                                   "controls": actual, "differences": differences})
                security.grab().save(str(work / f"security-{theme}-{sample['expanded']}.png"))
            QTest.mouseClick(security.preferences, Qt.MouseButton.LeftButton)
            until(app, lambda: dialog.isVisible(), "security to account settings")
            assert all(not edit.text() for edit in security.fields)
            result["navigation_security_to_permissions"] = True
        for sample in json.loads(args.reference.read_text(encoding="utf-8-sig"))["samples"]:
            theme, width = sample["theme"], sample["width"]
            window.context.preferences.save(theme=theme)
            window.apply_preferences()
            dialog.resize(width, 820)
            host.verticalScrollBar().setValue(0)
            wait(app, 180)
            controls = {
                "#currentAccountPanel": [panel.profile], "#currentAccountPanel > h3": [panel.profile_header],
                ".account-profile > div": [entry[0] for entry in panel.profile_fields],
                "#currentAccountPanel > button": [panel.security], "#localAccountsPanel": [panel.admin],
                "#localAccountsPanel > header": [panel.admin_header], ".account-stat": [entry[0] for entry in panel.stats],
                ".account-storage-note": [panel.storage], ".account-role-guide > summary": [panel.guide.toggle],
                ".account-directory": [panel.directory], ".account-editor": [panel.editor],
                ".account-directory > header": [panel.directory_header], ".account-editor > header": [panel.editor_header],
                ".account-search input": [panel.search], "[data-account-roster]": [panel.roster],
                ".account-roster-row": panel.roster_rows, ".account-editor form > label": [f[0] for f in panel.fields] + [panel.active],
                ".account-editor form > label > input": [f[2] for f in panel.fields],
                ".account-editor fieldset": [panel.roles_host], ".account-editor fieldset > label": list(panel.role_choices.values()),
                ".account-permission-preview": [panel.preview], ".account-form-actions": [panel.actions],
            }
            origin = sample["controls"]["#currentAccountPanel"][0]["rect"]
            actual, differences = {}, {}
            for key, widgets in controls.items():
                actual[key], differences[key] = [], []
                for control, ref in zip(widgets, sample["controls"][key]):
                    point = control.mapTo(panel, QPoint())
                    bounds = dict(x=point.x(), y=point.y(), width=control.width(), height=control.height())
                    expected = ref["rect"]
                    expected = {**expected, "x": expected["x"] - origin["x"], "y": expected["y"] - origin["y"]}
                    actual[key].append(bounds)
                    differences[key].append({k: round(v - expected[k], 3) for k, v in bounds.items()})
            result["samples"].append({"width": width, "theme": theme, "controls": actual, "differences": differences})
            dialog.grab().save(str(work / f"accounts-{theme}-{width}-top.png"))
            host.ensureWidgetVisible(panel.actions)
            wait(app, 80)
            dialog.grab().save(str(work / f"accounts-{theme}-{width}-editor.png"))
            assert panel.submit.isVisible() and panel.submit.mapTo(host.viewport(), QPoint()).y() < host.viewport().height()
        dialog.resize(1180, 820)
        click_matrix = panel.guide.toggle
        for width in (1180, 900, 820):
            dialog.resize(width, 820)
            if not click_matrix.isChecked():
                click_matrix.click()
            host.ensureWidgetVisible(panel.guide)
            wait(app, 80)
            assert len(panel.guide.cards) == 6
            dialog.grab().save(str(work / f"matrix-{width}.png"))
        click_matrix.click()
        dialog.resize(1180, 820)
        host.verticalScrollBar().setValue(0)
        wait(app, 300)
        heartbeat, gaps = QTimer(), []
        previous = [time.perf_counter()]
        def beat():
            now = time.perf_counter()
            gaps.append((now - previous[0]) * 1000)
            previous[0] = now
        heartbeat.setInterval(16)
        heartbeat.timeout.connect(beat)
        heartbeat.start()
        read_times = []
        for _ in range(8):
            started = time.perf_counter()
            panel.load()
            until(app, lambda: panel.fresh and not panel.reading, "account responsiveness read")
            read_times.append(round((time.perf_counter() - started) * 1000, 2))
        heartbeat.stop()
        result["account_local_samples"] = {"read_ms": read_times,
            "heartbeat_max_ms": round(max(gaps, default=0), 2),
            "heartbeat_p95_ms": round(sorted(gaps)[min(len(gaps) - 1, int(len(gaps) * .95))], 2) if gaps else None}

        def click(control):
            host.ensureWidgetVisible(control)
            wait(app, 30)
            assert control.isVisible() and control.isEnabled(), control
            QTest.mouseClick(control, Qt.MouseButton.LeftButton)
            app.processEvents()

        def fill(edit, value):
            edit.setFocus()
            edit.selectAll()
            if value.isascii():
                QTest.keyClicks(edit, value)
            else:
                previous_clipboard = app.clipboard().text()
                app.clipboard().setText(value)
                QTest.keyClick(edit, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
                app.clipboard().setText(previous_clipboard)

        def ready():
            until(app, lambda: panel.fresh and not panel.saving and not panel.reading, "account saved and refreshed")

        def new_viewer():
            click(panel.new)
            fill(panel.username, "nativeviewer")
            panel.display_name.setText("原生账户验证")
            fill(panel.password, "NativeViewer@2026")
            fill(panel.confirm_password, "Mismatch@2026")
            before_count = len(panel.users)
            click(panel.submit)
            assert "不一致" in panel.status.text() and len(panel.users) == before_count
            fill(panel.confirm_password, "NativeViewer@2026")
            click(panel.submit)
            ready()
        new_viewer()
        viewer_id = next(u["id"] for u in panel.users if u["username"] == "nativeviewer")
        assert panel.selected_id == viewer_id and panel.username.isReadOnly()
        viewer = NativeClient(client.base_url, app)
        viewer_user = request(viewer, "POST", "/api/auth/login",
                              {"username": "nativeviewer", "password": "NativeViewer@2026"})["user"]
        assert viewer_user["permissions"] == ["data.read"]
        result["create_confirm_and_roles"] = True
        fill(panel.search, "只读")
        assert [row.user["id"] for row in panel.roster_rows] == [viewer_id]
        fill(panel.search, "Accounts Probe")
        assert len(panel.roster_rows) == 1
        panel.display_name.setText("尚未保存的名字")
        panel._edited()
        expected = panel.display_name.text()

        def decision(text):
            modal = app.activeModalWidget()
            assert isinstance(modal, QMessageBox), modal
            choice = next(b for b in modal.buttons() if b.text() == text)
            QTest.mouseClick(choice, Qt.MouseButton.LeftButton)
        QTimer.singleShot(70, lambda: decision("继续编辑"))
        click(panel.roster_rows[0])
        assert panel.selected_id == viewer_id and panel.display_name.text() == expected
        QTimer.singleShot(70, lambda: decision("放弃更改"))
        click(panel.roster_rows[0])
        assert panel.selected_id == user["id"] and not panel.dirty()
        result["discard_actual_dialog"] = True
        panel.search.clear()
        panel.choose_user(viewer_id)
        panel.display_name.setText("修改后名称")
        panel._edited()
        panel.load()
        ready()
        assert panel.display_name.text() == "修改后名称" and panel.dirty()
        click(panel.submit)
        ready()
        assert next(u for u in panel.users if u["id"] == viewer_id)["display_name"] == "修改后名称"
        revoked = {}
        viewer.get("/api/auth/me", lambda data, error: revoked.update(data=data, error=error))
        until(app, lambda: "error" in revoked, "edited account session revoked")
        assert revoked["error"], revoked
        viewer_user = request(viewer, "POST", "/api/auth/login",
                              {"username": "nativeviewer", "password": "NativeViewer@2026"})["user"]
        result["edit_preserved_password_and_revoked_session"] = True
        denied = {}
        viewer.post("/api/auth/users", {"username": "forbidden", "display_name": "Forbidden",
                    "password": "Forbidden@2026", "roles": ["admin"]},
                    lambda data, error: denied.update(data=data, error=error))
        until(app, lambda: "error" in denied, "viewer cannot create account")
        assert denied["error"]
        readonly = AccountWorkspace(viewer, viewer_user)
        readonly.setStyleSheet(account_styles(True))
        readonly.resize(855, 800)
        readonly.show()
        assert readonly.admin.isHidden()
        readonly.save()
        assert readonly.current_permissions.values == ["查询数据"]
        readonly.close()
        result["readonly_controls_and_backend_denial"] = True
        panel.choose_user(user["id"])
        panel.active.setChecked(False)
        click(panel.submit)
        until(app, lambda: not panel.saving, "last admin rejection")
        assert "至少一个" in panel.status.text()
        assert panel.active.isChecked() is False and panel.dirty()
        panel.discard.click()
        assert panel.active.isChecked()
        result["last_admin_protection_preserves_form"] = True
        panel.choose_user(viewer_id)
        panel.active.setChecked(False)
        click(panel.submit)
        ready()
        disabled = {}
        viewer.post("/api/auth/login", {"username": "nativeviewer", "password": "NativeViewer@2026"},
                    lambda data, error: disabled.update(data=data, error=error))
        until(app, lambda: "error" in disabled, "disabled viewer login rejected")
        assert disabled["error"]
        panel.active.setChecked(True)
        click(panel.submit)
        ready()
        viewer_user = request(viewer, "POST", "/api/auth/login",
                              {"username": "nativeviewer", "password": "NativeViewer@2026"})["user"]
        result["disable_and_reenable"] = True
        security = AccountSecurityDialog(viewer, viewer_user, dialog)
        security.show()
        for edit, value in zip(security.fields, ("Incorrect@2026", "ChangedViewer@2026", "ChangedViewer@2026")):
            fill(edit, value)
        security.submit.click()
        until(app, lambda: not security.busy, "wrong current password")
        assert security.isVisible() and "错误" in security.status.text()
        fill(security.fields[0], "NativeViewer@2026")
        exits = []
        security.logoutRequested.connect(lambda: exits.append(True))
        security.submit.click()
        until(app, lambda: bool(exits), "password change exit signal")
        assert not security.isVisible() and all(not edit.text() for edit in security.fields)
        request(viewer, "POST", "/api/auth/login", {"username": "nativeviewer", "password": "ChangedViewer@2026"})
        result["actual_password_change"] = True
        click(panel.storage_button)
        assert dialog.nav.currentRow() == 0
        result["storage_link"] = True
        window.open_settings(4)
        panel.choose_user(user["id"])
        panel.display_name.setText("Accounts Probe Updated")
        panel._edited()
        exited = []
        window.logoutRequested.connect(lambda: exited.append(True))
        click(panel.submit)
        until(app, lambda: bool(exited), "current account edit returns to login")
        current_session = {}
        client.get("/api/auth/me", lambda data, error: current_session.update(data=data, error=error))
        until(app, lambda: "error" in current_session, "current session revoked")
        assert current_session["error"]
        relogged = request(client, "POST", "/api/auth/login", credentials)["user"]
        assert relogged["display_name"] == "Accounts Probe Updated"
        result["current_account_edit_logout_and_relogin"] = True
        with closing(sqlite3.connect(database)) as db:
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            rows = db.execute("SELECT username,active,password_hash FROM users ORDER BY username").fetchall()
            assert len(rows) == 2 and all(row[1] for row in rows)
            assert all("ChangedViewer" not in row[2] and "AccountsProbe" not in row[2] for row in rows)
            result["sqlite"] = {"integrity": "ok", "users": len(rows), "roles": db.execute(
                "SELECT role_code,COUNT(*) FROM user_roles GROUP BY role_code").fetchall()}
        result["formal_business_unchanged"] = before == hashes(formal)
        result["formal_preferences_unchanged"] = pref_before == hashlib.sha256(preferences.read_bytes()).hexdigest()
        assert result["formal_business_unchanged"] and result["formal_preferences_unchanged"]
        result["passed"] = True
    except Exception:
        result["errors"].append(traceback.format_exc())
    finally:
        for control in (security, readonly, window):
            if control:
                control.close()
        for connection in (viewer, client):
            if connection:
                connection.abort_all()
        backend.stop()
        (work / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"artifacts": str(work), "passed": result["passed"], "errors": result["errors"]},
                     ensure_ascii=False), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
