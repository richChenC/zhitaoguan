"""定位 Qt 版退出链路卡点：记录 quit 调用 / aboutToQuit / exec 返回三个里程碑。"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path

QT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = QT_ROOT.parent
TMP = PROJECT_ROOT / "05_测试与验证" / "03_自动化临时产物" / (
    "qt-exit-probe-" + datetime.now().strftime("%Y%m%d-%H%M%S")
)
TMP.mkdir(parents=True, exist_ok=True)
MARK = TMP / "milestones.txt"

import shutil
DB = TMP / "isolated.db"
shutil.copy2(QT_ROOT / "user-data" / "data" / "thimble.db", DB)
os.environ["THIMBLE_DB_PATH"] = str(DB)
os.environ["THIMBLE_DATA_DIR"] = str(TMP / "data")
os.environ["THIMBLE_OUTPUT_DIR"] = str(TMP / "output" / "excel")
os.environ["THIMBLE_REPORT_DIR"] = str(TMP / "output" / "reports")
os.environ["THIMBLE_ALLOW_MULTI_INSTANCE"] = "1"
sys.path.insert(0, str(QT_ROOT))


def mark(text: str) -> None:
    with MARK.open("a", encoding="utf-8") as fh:
        fh.write(f"{time.monotonic():.2f} {text}\n")


import qt_shell.main as M  # noqa: E402  触发顶层 env
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from qt_shell.backend_service import BackendService  # noqa: E402
from qt_shell.constants import RUNTIME, USER_DATA  # noqa: E402
from qt_shell.desktop_api import DesktopAPI  # noqa: E402
from qt_shell.log_utils import ServiceLog  # noqa: E402
from qt_shell.offline_policy import protect_directory  # noqa: E402
from qt_shell.web_profile import ShellProfile  # noqa: E402
from qt_shell.windows import Shell  # noqa: E402

mark(f"probe start pid={os.getpid()}")
app = QApplication(sys.argv)
log = ServiceLog()
backend = BackendService(log)
protect_directory(USER_DATA)
backend.start()
mark("backend started")

holder = [None]
api = DesktopAPI(lambda: holder[0])
profile = ShellProfile(api)
profile.set_base_url(RUNTIME.base_url)
holder[0] = profile
shell = Shell(app, profile, api, log)
window = shell.show_main()
mark("main window shown")

app.aboutToQuit.connect(lambda: mark("SIGNAL aboutToQuit"))
app.aboutToQuit.connect(backend.stop)


def request_quit() -> None:
    mark("CALL app.quit()")
    app.quit()
    mark("RETURN app.quit()")


QTimer.singleShot(6000, request_quit)
QTimer.singleShot(12000, lambda: (mark("hard watchdog fired"), os._exit(0)))

code = app.exec()
mark(f"app.exec() RETURNED {code}")
shell.shutdown()
backend.stop()
mark("cleanup done")
os._exit(0)
