"""Actual setup/login/logout/relogin controls, including the production event loop."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from datetime import datetime
import time

project = Path(__file__).resolve().parents[2]
work = project.parent / "05_测试与验证" / "03_自动化临时产物" / (
    "native-session-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
work.mkdir(parents=True, exist_ok=True)
for key, value in {
    "THIMBLE_QT_TEST_DATA_ROOT": work, "THIMBLE_DB_PATH": work / "data" / "thimble.db",
    "THIMBLE_DATA_DIR": work / "data", "THIMBLE_OUTPUT_DIR": work / "exports",
    "THIMBLE_REPORT_DIR": work / "reports", "THIMBLE_PORT": "0",
    "THIMBLE_ALLOW_MULTI_INSTANCE": "1", "THIMBLE_NATIVE_QT": "1",
    "QSG_RENDER_LOOP": "basic",
}.items():
    os.environ[key] = str(value)
sys.path.insert(0, str(project))

from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qt_shell.backend_service import BackendService
from qt_shell.log_utils import ServiceLog
from qt_shell.main import _run_native_qt
from qt_shell.native_login import NativeLoginWindow
from qt_shell.native_windows import NativeMainWindow


def main():
    app = QApplication([])
    backend = BackendService(ServiceLog(work / "service.log"))
    backend.start()
    state = {"stage": 0, "errors": []}
    started = time.monotonic()
    def tick():
        try:
            assert time.monotonic() - started < 40, f"session stage {state['stage']} timed out"
            login = next((w for w in app.topLevelWidgets() if isinstance(w, NativeLoginWindow) and w.isVisible()), None)
            window = next((w for w in app.topLevelWidgets() if isinstance(w, NativeMainWindow) and w.isVisible()), None)
            stage = state["stage"]
            if stage == 0 and login and login.submit.isEnabled():
                assert login.initialized is False
                login.username.setText("sessionprobe")
                login.display_name.setText("Native Session Probe")
                login.password.setText("NativeSession@2026")
                login.confirm_password.setText("NativeSession@2026")
                QTest.mouseClick(login.submit, Qt.MouseButton.LeftButton)
                state["stage"] = 1
            elif stage == 1 and window:
                window.open_settings(4)
                state["stage"] = 2
            elif stage == 2 and window and window.settings_page.logout.isVisible():
                QTest.mouseClick(window.settings_page.logout, Qt.MouseButton.LeftButton)
                state["stage"] = 3
            elif stage == 3 and login and login.submit.isEnabled():
                assert login.initialized is True
                assert login.password.text() == ""
                login.username.setText("sessionprobe")
                login.password.setText("NativeSession@2026")
                QTest.mouseClick(login.submit, Qt.MouseButton.LeftButton)
                state["stage"] = 4
            elif stage == 4 and window:
                assert window.user["username"] == "sessionprobe"
                state["stage"] = 5
                window.close()
        except Exception as exc:
            state["errors"].append(str(exc))
            app.quit()
    timer = QTimer()
    timer.setInterval(100)
    timer.timeout.connect(tick)
    timer.start()
    code = _run_native_qt(app, backend)
    timer.stop()
    state["passed"] = state["stage"] == 5 and not state["errors"] and code == 0
    (work / "result.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(state, ensure_ascii=False), flush=True)
    return 0 if state["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
