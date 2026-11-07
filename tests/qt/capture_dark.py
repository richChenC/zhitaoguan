"""隔离库上的六视图 + 独立设置窗【暗色主题】采集。

基于 capture_views_base.py 的已验证逻辑，仅在进入每个视图前注入
document.documentElement.dataset.theme='dark'（并为独立设置窗预备
localStorage.thimbleAppearance='dark'），用于 1:1 还原的暗色对比。

所有写入只落在 08_Qt移植版/验证/04_界面截图/ 与 05_测试与验证/03_自动化临时产物/。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

QT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = QT_ROOT.parent
VERIFY = QT_ROOT / "验证" / "04_界面截图"
TMP = PROJECT_ROOT / "05_测试与验证" / "03_自动化临时产物" / (
    "qt-capture-dark-" + datetime.now().strftime("%Y%m%d-%H%M%S")
)
TMP.mkdir(parents=True, exist_ok=True)
VERIFY.mkdir(parents=True, exist_ok=True)

DB = TMP / "isolated.db"
shutil.copy2(QT_ROOT / "user-data" / "data" / "thimble.db", DB)
os.environ["THIMBLE_DB_PATH"] = str(DB)
os.environ["THIMBLE_DATA_DIR"] = str(TMP / "data")
os.environ["THIMBLE_OUTPUT_DIR"] = str(TMP / "output" / "excel")
os.environ["THIMBLE_REPORT_DIR"] = str(TMP / "output" / "reports")
os.environ["THIMBLE_ALLOW_MULTI_INSTANCE"] = "1"
os.environ.setdefault("CODEBUDDY_SAFE_DELETE_ENABLED", "0")
sys.path.insert(0, str(QT_ROOT))

import qt_shell.main as shell_main  # noqa: F401  触发顶层 Chromium 开关配置
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from qt_shell.backend_service import BackendService  # noqa: E402
from qt_shell.constants import RUNTIME, USER_DATA  # noqa: E402
from qt_shell.desktop_api import DesktopAPI  # noqa: E402
from qt_shell.log_utils import ServiceLog  # noqa: E402
from qt_shell.offline_policy import protect_directory  # noqa: E402
from qt_shell.web_profile import ShellProfile  # noqa: E402
from qt_shell.windows import Shell  # noqa: E402


def sleep(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def js(page, code: str, timeout: int = 4000):
    holder = {}
    loop = QEventLoop()
    page.runJavaScript(code, lambda value: (holder.__setitem__("v", value), loop.quit()))
    QTimer.singleShot(timeout, loop.quit)
    loop.exec()
    return holder.get("v")


def wait_for(page, code: str, timeout_ms: int, interval: int = 400):
    started = time.monotonic()
    last = None
    while (time.monotonic() - started) * 1000 < timeout_ms:
        last = js(page, code)
        if last is True or last == "true" or last == 1:
            return True, int((time.monotonic() - started) * 1000), last
        sleep(interval)
    return False, int((time.monotonic() - started) * 1000), last


LOGIN_JS = r"""(function () {
  var d = {username:'qtdark', password:'QtDark@2026', display_name:'Qt 暗色验证'};
  var h = {'Content-Type':'application/json','X-Thimble-Request':'1'};
  (async function () {
    var s = await (await fetch('/api/auth/status', {headers:h})).json();
    if (!s.initialized) {
      var r = await fetch('/api/auth/setup', {method:'POST', headers:h, body:JSON.stringify(d)});
      if (!r.ok) throw new Error('setup HTTP ' + r.status);
    }
    var l = await fetch('/api/auth/login', {method:'POST', headers:h, body:JSON.stringify(d)});
    if (!l.ok) throw new Error('login HTTP ' + l.status);
    var next = new URLSearchParams(location.search).get('next') || '/';
    location.href = next;
  })().catch(function (e) { window.__qtLoginError = String(e); });
  return true;
})()"""

DOM_JS = r"""(function () {
  var nav = document.querySelectorAll('nav button[data-view]');
  var active = document.querySelector('.view.active');
  return JSON.stringify({
    href: location.href,
    title: document.title,
    activeView: active ? active.id : '',
    viewCount: document.querySelectorAll('section.view').length,
    navLabels: Array.prototype.map.call(nav, function (b) { return b.textContent.trim(); }),
    desktopAPICount: window.desktopAPI ? Object.keys(window.desktopAPI).length : 0,
    bridgeReady: window.__qtBridgeReady === true,
    theme: document.documentElement.dataset.theme || '',
    loginError: window.__qtLoginError || null,
    alerts: (document.querySelector('#analysisAlerts') || {}).innerText || '',
    anWrapClass: (document.querySelector('#analytics .an-wrap') || {}).className || '',
    bodyText: (document.body.innerText || '').slice(0, 900)
  });
})()"""

READY_JS = {
    "workspace": "(function(){var v=document.querySelector('.view.active');return !!v&&v.id==='workspace'&&/共\\s*\\d+\\s*条|检测记录/.test(v.innerText||'')})()",
    "threeD": "(function(){var v=document.querySelector('.view.active');return !!v&&v.id==='threeD'})()",
    "analytics": "(function(){var v=document.querySelector('.view.active');if(!v||v.id!=='analytics')return false;var w=document.querySelector('#analytics .an-wrap');var a=document.querySelector('#analysisAlerts');if(w&&w.classList.contains('viz-loading'))return false;if(a&&/正在读取本机检测数据/.test(a.innerText||''))return false;return !!(a&&a.innerText.trim())})()",
    "reports": "(function(){var v=document.querySelector('.view.active');return !!v&&v.id==='reports'&&/检验报告单|检验结果比对表/.test(v.innerText||'')})()",
    "states": "(function(){var v=document.querySelector('.view.active');return !!v&&v.id==='states'&&/状态概览|管板/.test(v.innerText||'')})()",
}
TIMEOUTS = {"workspace": 25000, "threeD": 12000, "analytics": 35000,
            "reports": 20000, "states": 20000}
VIEWS = ["workspace", "threeD", "analytics", "reports", "states"]


def main() -> int:
    app = QApplication(sys.argv)
    log = ServiceLog()
    backend = BackendService(log)
    protect_directory(USER_DATA)
    backend.start()

    holder = [None]
    api = DesktopAPI(lambda: holder[0])
    profile = ShellProfile(api)
    profile.set_base_url(RUNTIME.base_url)
    holder[0] = profile
    shell = Shell(app, profile, api, log)
    window = shell.show_main()

    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "theme": "dark",
        "base_url": RUNTIME.base_url,
        "isolated_db": str(DB),
        "views": {},
        "settings": {},
        "errors": [],
    }

    def set_dark(page) -> None:
        js(page, "try{localStorage.setItem('thimbleAppearance','dark')}catch(e){}")
        js(page, "document.documentElement.dataset.theme='dark'")

    try:
        for _ in range(80):
            if window._load_done:
                break
            sleep(500)
        report["initial_href"] = js(window.page, "location.href")
        report["initial_ready"] = js(
            window.page, "document.querySelectorAll('nav button[data-view]').length"
        )

        need_login = "login" in str(report["initial_href"]).lower() or report["initial_ready"] in (0, None)
        if need_login:
            js(window.page, LOGIN_JS)
            ok, cost, _ = wait_for(
                window.page,
                "document.querySelectorAll('nav button[data-view]').length >= 5",
                40000,
            )
            report["login"] = {"entered_workspace": ok, "wait_ms": cost,
                               "error": js(window.page, "window.__qtLoginError || null")}
            # 为后续所有窗口预备暗色 localStorage
            set_dark(window.page)
        else:
            report["login"] = {"entered_workspace": True, "reused_session": True}
            set_dark(window.page)

        sleep(1800)
        for index, name in enumerate(VIEWS, 1):
            js(window.page,
               "(function(){var b=document.querySelector('nav button[data-view=\"%s\"]');"
               "if(b){b.click();return true}return false})()" % name)
            ok, cost, last = wait_for(window.page, READY_JS[name], TIMEOUTS[name])
            set_dark(window.page)  # 切视图后确保暗色即时生效
            sleep(1500)  # 暗色 CSS 过渡 + SVG/图表重绘
            shot = VERIFY / f"Qt暗-{index:02d}-{name}.png"
            window.grab().save(str(shot))
            raw = js(window.page, DOM_JS)
            try:
                dom = json.loads(raw) if isinstance(raw, str) else {}
            except ValueError:
                dom = {"raw": raw}
            report["views"][name] = {
                "ready": ok, "wait_ms": cost, "last_probe": last,
                "theme": dom.get("theme"), "screenshot": shot.name, **dom,
            }

        # 设置是独立窗口，不是主窗口内视图
        shell.open_settings_window("settingsPreferencesPane")
        settings = shell.settings_window
        if settings is not None:
            for _ in range(60):
                if settings._load_done:
                    break
                sleep(500)
            set_dark(settings.page)
            sleep(2000)
            shot = VERIFY / "Qt暗-06-settings.png"
            settings.grab().save(str(shot))
            report["settings"] = {
                "screenshot": shot.name,
                "title": settings.windowTitle(),
                "width": settings.width(), "height": settings.height(),
                "href": js(settings.page, "location.href"),
                "theme": js(settings.page, "document.documentElement.dataset.theme||''"),
                "bodyText": js(settings.page, "(document.body.innerText||'').slice(0,700)"),
                "section": js(settings.page,
                              "(document.querySelector('[role=tab][aria-selected=true]')||{}).innerText||''"),
            }
        else:
            report["errors"].append("settings window missing")

        report["blocked_requests"] = profile.blocked_report()
        report["session_cookie_present"] = bool(profile.cookie_header())
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        (VERIFY / "六视图暗色补采.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps({
            "base_url": report["base_url"],
            "login": report.get("login"),
            "views": {k: {"ready": v["ready"], "wait_ms": v["wait_ms"],
                          "activeView": v.get("activeView"), "theme": v.get("theme")}
                      for k, v in report["views"].items()},
            "settings": {k: report["settings"].get(k) for k in ("title", "href", "theme", "section")},
            "blocked": report.get("blocked_requests"),
            "errors": report["errors"],
        }, ensure_ascii=False))
        shell.shutdown()
        backend.stop()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)

    return 0


if __name__ == "__main__":
    sys.exit(main())
