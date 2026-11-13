"""Compare actual native login geometry and authenticate against an isolated snapshot."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from native_desktop_workflow import request, until, wait


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("reference", type=Path)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[2]
    work = project.parent / "05_测试与验证/03_自动化临时产物" / (
        "native-login-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    work.mkdir(parents=True)
    database = work / "data/thimble.db"
    database.parent.mkdir()
    tables = ("findings", "tube_states", "import_batches", "analysis_rules")
    def hashes(path):
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
            return {table: hashlib.sha256(json.dumps(db.execute(
                f"SELECT * FROM {table} ORDER BY rowid").fetchall(), ensure_ascii=False,
                separators=(",", ":")).encode()).hexdigest() for table in tables}
    formal = project / "user-data/data/thimble.db"
    before = hashes(formal)
    with sqlite3.connect(formal.as_uri() + "?mode=ro", uri=True) as source, sqlite3.connect(database) as target:
        source.backup(target)
        target.executescript("DELETE FROM login_sessions; DELETE FROM user_roles; DELETE FROM users;")
    for key, value in {
        "THIMBLE_QT_TEST_DATA_ROOT": work, "THIMBLE_DB_PATH": database,
        "THIMBLE_DATA_DIR": database.parent, "THIMBLE_OUTPUT_DIR": work / "exports",
        "THIMBLE_REPORT_DIR": work / "reports", "THIMBLE_PORT": "0",
        "THIMBLE_ALLOW_MULTI_INSTANCE": "1",
    }.items():
        os.environ[key] = str(value)
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from qt_shell.backend_service import BackendService
    from qt_shell.log_utils import ServiceLog
    from qt_shell.native_client import NativeClient
    from qt_shell.native_login import NativeLoginWindow
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    backend = BackendService(ServiceLog(work / "service.log"))
    result = {"passed": False, "samples": [], "errors": []}
    login = client = None
    reference = json.loads(args.reference.read_text(encoding="utf-8-sig"))
    def capture(state):
        for sample in reference["samples"]:
            if sample["state"] != state:
                continue
            login.preferences.save(theme=sample["theme"])
            login._apply_theme()
            login.resize(sample["width"], sample["height"])
            wait(app, 120)
            controls = {
                ".login-shell": login.shell, ".login-product": login.brand, ".login-card": login.card,
                "#loginTitle": login.subtitle, "#loginDisplayName": login.display_name,
                "#loginUsername": login.username, "#loginPassword": login.password_field,
                "#loginReveal": login.password_reveal, "#loginConfirmPassword": login.confirm_field,
                "#loginPasswordMeter": login.strength_host, ".login-options": login.options,
                "#loginMessage": login.message, "#loginSubmit": login.submit, ".login-card-footer": login.footer,
            }
            actual, differences = {}, {}
            for selector, control in controls.items():
                expected = sample["controls"][selector]
                assert control.isVisible() == expected["visible"], (state, selector, "visibility")
                if not control.isVisible():
                    continue
                origin = control.mapTo(login, QPoint())
                bounds = dict(x=origin.x(), y=origin.y(), width=control.width(), height=control.height())
                actual[selector] = bounds
                differences[selector] = {key: round(value - expected["rect"][key], 3)
                                         for key, value in bounds.items()}
            result["samples"].append({"state": state, "width": sample["width"], "height": sample["height"],
                                      "theme": sample["theme"], "controls": actual, "differences": differences})
            login.grab().save(str(work / f"native-login-{state}-{sample['width']}-{sample['theme']}.png"))
    try:
        client = NativeClient(backend.start(), app)
        login = NativeLoginWindow(client)
        login.show()
        until(app, lambda: login.submit.isEnabled(), "native setup status")
        assert not login.initialized
        capture("setup")
        login.resize(1080, 760)
        login.preferences.save(theme="light")
        login._apply_theme()
        login.display_name.setText("Login Probe")
        login.username.setText("loginprobe")
        login.password.setText("LoginProbe@2026")
        login.confirm_password.setText("Mismatch@2026")
        QTest.mouseClick(login.submit, Qt.MouseButton.LeftButton)
        assert login.message.text() == "两次输入的密码不一致"
        assert not request(client, "GET", "/api/auth/status")["initialized"]
        result["mismatch_prevents_setup"] = True
        strengths = []
        for value in ("", "abc", "abcdef", "abc123", "abc1234567", "SecretPass@2026"):
            login.password.setText(value)
            strengths.append({"length": len(value), "text": login.strength_text.text(), "score": login.strength.value()})
        assert [item["text"] for item in strengths] == [item["text"] for item in reference["strengths"]]
        result["strengths"] = strengths
        login.password.setText("LoginProbe@2026")
        login.confirm_password.setText("LoginProbe@2026")
        accepted = []
        login.authenticated.connect(accepted.append)
        QTest.keyClick(login.confirm_password, Qt.Key.Key_Return)
        until(app, lambda: accepted, "setup and login")
        assert accepted[-1]["username"] == "loginprobe"
        assert login.password.text() == login.confirm_password.text() == ""
        assert login.submit.isEnabled()
        login.close()
        login = NativeLoginWindow(client)
        login.show()
        until(app, lambda: login.submit.isEnabled(), "native login status")
        assert login.initialized
        capture("login")
        login.resize(1080, 760)
        login.preferences.save(theme="light")
        login._apply_theme()
        login.username.setText("loginprobe")
        login.password.setText("WrongPassword@2026")
        QTest.mouseClick(login.submit, Qt.MouseButton.LeftButton)
        until(app, lambda: login.submit.isEnabled() and bool(login.message.text()), "wrong password")
        result["wrong_password"] = login.message.text()
        assert "还可尝试" in login.message.text()
        login.password.setText("LoginProbe@2026")
        QTest.mouseClick(login.password_reveal, Qt.MouseButton.LeftButton)
        assert login.password.echoMode() == login.password.EchoMode.Normal and login.password.hasFocus()
        QTest.mouseClick(login.password_reveal, Qt.MouseButton.LeftButton)
        assert login.password.echoMode() == login.password.EchoMode.Password
        login.remember.setChecked(True)
        accepted = []
        login.authenticated.connect(accepted.append)
        QTest.keyClick(login.password, Qt.Key.Key_Return)
        until(app, lambda: accepted, "remembered login")
        raw_preferences = login.preferences.path.read_text(encoding="utf-8")
        assert "LoginProbe@2026" not in raw_preferences
        assert request(client, "GET", "/api/auth/me")["user"]["username"] == "loginprobe"
        with sqlite3.connect(database) as db:
            sessions = db.execute("SELECT * FROM login_sessions").fetchall()
            result["session_count"] = len(sessions)
        assert sessions
        login.close()
        login = NativeLoginWindow(client)
        login.show()
        until(app, lambda: login.submit.isEnabled(), "remembered username")
        assert login.username.text() == "loginprobe" and login.remember.isChecked()
        assert not login.password.text()
        result["remembered_without_password"] = True
        result["formal_hashes"] = hashes(formal)
        assert result["formal_hashes"] == before == hashes(database)
        result["business_unchanged"] = True
        bad = [(s["state"], s["width"], s["theme"], selector, diff) for s in result["samples"]
               for selector, diff in s["differences"].items() if any(abs(v) > 2 for v in diff.values())]
        assert not bad, bad
        result["passed"] = True
    except Exception as exc:
        result["errors"].append(str(exc))
    finally:
        if login:
            login.close()
        if client:
            client.abort_all()
        backend.stop()
        (work / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"artifacts": str(work), **result}, ensure_ascii=False, indent=2), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
