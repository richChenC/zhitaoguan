"""阶段 2/3 冒烟：隔离库自动注册登录 → 进入主窗口 → 逐视图采集截图与 DOM 指标。

所有数据写入 05_测试与验证/03_自动化临时产物/qt-port-<ts>/，
不触碰 QT/user-data/data/thimble.db（用户实际使用的副本）与正式业务库。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path("D:/work-projects/在役检查系统-指套管数据管理工具")
QT = ROOT / "08_Qt移植版"
sys.path.insert(0, str(QT))

STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")
TMP = ROOT / "05_测试与验证" / "03_自动化临时产物" / f"qt-port-{STAMP}"
OUT = QT / "验证" / "01_启动与环境"
TMP.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)

SOURCE_DB = QT / "user-data" / "data" / "thimble.db"
ISOLATED_DB = TMP / "isolated.db"
shutil.copy2(SOURCE_DB, ISOLATED_DB)

os.environ["THIMBLE_DB_PATH"] = str(ISOLATED_DB)
os.environ["THIMBLE_DATA_DIR"] = str(TMP / "data")
os.environ["THIMBLE_OUTPUT_DIR"] = str(TMP / "output")
os.environ["THIMBLE_REPORT_DIR"] = str(TMP / "reports")
os.environ["THIMBLE_LOG_PATH"] = str(TMP / "server.log")
os.environ["THIMBLE_ALLOW_MULTI_INSTANCE"] = "1"
os.environ.setdefault("QT_SCALE_FACTOR", "1")
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "0")

from PySide6.QtCore import QTimer, QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from qt_shell.backend_service import BackendService  # noqa: E402
from qt_shell.constants import CHROMIUM_FLAGS, RUNTIME  # noqa: E402
from qt_shell.desktop_api import DesktopAPI  # noqa: E402
from qt_shell.log_utils import ServiceLog  # noqa: E402
from qt_shell.web_profile import ShellProfile  # noqa: E402
from qt_shell.windows import Shell  # noqa: E402

os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(CHROMIUM_FLAGS)

PROBE_USER = "qt_probe"
PROBE_PASSWORD = "QtProbe-2026-1105"

LOGIN_JS = """
(async function () {
  var payload = {username: %s, password: %s, display_name: 'Qt 验证账号'};
  var status = await (await fetch('/api/auth/status', {headers:{'X-Thimble-Request':'1'}})).json();
  if (!status.initialized) {
    var r = await fetch('/api/auth/setup', {method:'POST',
      headers:{'Content-Type':'application/json','X-Thimble-Request':'1'},
      body: JSON.stringify(payload)});
    if (!r.ok) throw new Error('setup failed: ' + r.status);
  }
  var login = await fetch('/api/auth/login', {method:'POST',
    headers:{'Content-Type':'application/json','X-Thimble-Request':'1'},
    body: JSON.stringify({username: payload.username, password: payload.password})});
  if (!login.ok) throw new Error('login failed: ' + login.status);
  var next = new URLSearchParams(location.search).get('next') || '/';
  location.href = next;
})().catch(function (e) { window.__qtLoginError = String(e); });
""" % (json.dumps(PROBE_USER), json.dumps(PROBE_PASSWORD))

DOM_JS = r"""(function () {
  var nav = document.querySelectorAll('nav button[data-view]');
  return JSON.stringify({
    href: location.href,
    title: document.title,
    viewCount: document.querySelectorAll('section.view').length,
    activeView: (document.querySelector('.view.active') || {}).id || '',
    navLabels: Array.prototype.map.call(nav, function (b) { return b.textContent.trim(); }),
    settingsGearLast: !!(document.querySelector('.app-nav .nav-utilities button:last-child[data-open-settings]')),
    desktopAPICount: window.desktopAPI ? Object.keys(window.desktopAPI).length : 0,
    bridgeReady: window.__qtBridgeReady === true,
    cookies: document.cookie,
    bodyText: (document.body.innerText || '').slice(0, 400)
  });
})()"""

VIEWS = ["workspace", "threeD", "analytics", "reports", "states", "settings"]


def main() -> int:
    app = QApplication(sys.argv)
    log = ServiceLog(OUT / "登录采集服务.log")
    backend = BackendService(log)
    try:
        backend.start()
    except Exception as exc:
        print("BACKEND_FAILED", exc)
        return 1

    holder: list = [None]
    api = DesktopAPI(lambda: holder[0])
    profile = ShellProfile(api)
    profile.set_base_url(RUNTIME.base_url)
    holder[0] = profile
    shell = Shell(app, profile, api, log)
    window = shell.show_main()

    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "base_url": RUNTIME.base_url,
        "isolated_db": str(ISOLATED_DB),
        "views": {},
        "errors": [],
    }
    state = {"logged_in": False, "collecting": False, "index": 0, "done": False}

    def save(path: Path) -> None:
        try:
            window.grab().save(str(path))
        except Exception as exc:
            report["errors"].append("screenshot: " + str(exc))

    def finish() -> None:
        if state["done"]:
            return
        state["done"] = True
        report["blocked_requests"] = profile.blocked_report()
        report["session_cookie_present"] = bool(profile.cookie_header())
        target = OUT / "登录与六视图采集.json"
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("CAPTURE_REPORT", json.dumps({
            "base_url": RUNTIME.base_url,
            "views": {k: v.get("activeView") for k, v in report["views"].items()},
            "errors": report["errors"],
            "blocked": report["blocked_requests"]["blocked_count"],
        }, ensure_ascii=False))
        backend.stop()
        app.quit()
        QTimer.singleShot(1500, lambda: os._exit(0))

    def capture_view(index: int) -> None:
        if index >= len(VIEWS):
            finish()
            return
        name = VIEWS[index]
        if name == "settings":
            js = "document.querySelector('[data-open-settings]')?.click(); 'ok';"
        else:
            js = f"document.querySelector('nav button[data-view=\"{name}\"]')?.click(); 'ok';"

        def after_click(_result) -> None:
            QTimer.singleShot(1400, lambda: collect(name, index))

        window.page.runJavaScript(js, after_click)

    def collect(name: str, index: int) -> None:
        def on_dom(raw) -> None:
            info = {}
            try:
                info = json.loads(raw) if isinstance(raw, str) else {}
            except ValueError:
                info = {"raw": raw}
            info["screenshot"] = f"Qt-{index+1:02d}-{name}.png"
            report["views"][name] = info
            save(OUT / info["screenshot"])
            capture_view(index + 1)

        window.page.runJavaScript(DOM_JS, on_dom)

    def on_load(ok: bool) -> None:
        url = window.page.url().toString()
        if state["collecting"]:
            return
        if "login.html" in url:
            if state["logged_in"]:
                return
            state["logged_in"] = True
            window.page.runJavaScript(LOGIN_JS, lambda _: None)
            return
        # 已进入主窗口
        state["collecting"] = True
        window.showNormal()
        window.resize(1440, 900)
        QTimer.singleShot(900, lambda: capture_view(0))

    window.page.loadFinished.connect(on_load)
    QTimer.singleShot(45000, finish)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
