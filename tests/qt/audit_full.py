"""Qt 版全功能审计：六视图 + 设置六分区 + 暗色 + 控制台报错 + 页面内交互。

测试截图、运行日志和完整报告只写 05_测试与验证/03_自动化临时产物/。
不触发任何原生文件对话框（select-directory/select-excel/save-*），避免阻塞事件循环；
导入/导出文件选择的端到端留给真实桌面会话，本脚本聚焦 Qt 壳的渲染/导航/交互/报错。
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

QT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = QT_ROOT.parent
TMP = PROJECT_ROOT / "05_测试与验证" / "03_自动化临时产物" / (
    "qt-audit-" + datetime.now().strftime("%Y%m%d-%H%M%S")
)
TMP.mkdir(parents=True, exist_ok=True)
ARTIFACTS = TMP / "artifacts"
ARTIFACTS.mkdir(parents=True, exist_ok=True)

DB = TMP / "isolated.db"
import sqlite3 as _sqlite3
_source = _sqlite3.connect(
    f"file:{(QT_ROOT / 'user-data' / 'data' / 'thimble.db').as_posix()}?mode=ro",
    uri=True,
)
_c = _sqlite3.connect(str(DB))
_source.backup(_c)
_source.close()
# 仅清空身份表（不影响检测数据），使副本处于“未初始化”，setup 会重建测试管理员
_c.executescript(
    "DELETE FROM login_sessions; DELETE FROM user_roles; DELETE FROM users;")
_c.commit(); _c.close()
os.environ["THIMBLE_QT_TEST_DATA_ROOT"] = str(TMP)
os.environ["THIMBLE_DB_PATH"] = str(DB)
os.environ["THIMBLE_DATA_DIR"] = str(TMP / "data")
os.environ["THIMBLE_OUTPUT_DIR"] = str(TMP / "output" / "excel")
os.environ["THIMBLE_REPORT_DIR"] = str(TMP / "output" / "reports")
os.environ["THIMBLE_ALLOW_MULTI_INSTANCE"] = "1"
os.environ["THIMBLE_PORT"] = "20117"  # 唯一端口，避免与用户/残留实例冲突
os.environ.setdefault("CODEBUDDY_SAFE_DELETE_ENABLED", "0")
sys.path.insert(0, str(QT_ROOT))

import qt_shell.main as shell_main  # noqa: F401  触发顶层 Chromium 开关
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from qt_shell.backend_service import BackendService  # noqa: E402
from qt_shell.constants import RUNTIME, USER_DATA  # noqa: E402
from qt_shell.desktop_api import DesktopAPI  # noqa: E402
from qt_shell.log_utils import ServiceLog  # noqa: E402
from qt_shell.offline_policy import protect_directory, allowed_url  # noqa: E402
from qt_shell.web_profile import ShellProfile  # noqa: E402
from qt_shell.windows import Shell, OfflinePage, APP_ICON, BACKGROUND  # noqa: E402
from PySide6.QtCore import Qt, QEventLoop, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWebEngineCore import QWebEnginePage  # noqa: E402
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: E402
from PySide6.QtWidgets import QMainWindow, QMessageBox  # noqa: E402


class AuditPage(OfflinePage):
    """捕获浏览器控制台与运行时报错（含加载期），无需改动源码。"""

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceId):  # noqa: N802
        try:
            CONSOLE_LOG.append({"src": str(sourceId), "level": int(level),
                                "msg": str(message), "line": int(lineNumber)})
        except Exception:
            pass
        super().javaScriptConsoleMessage(level, message, lineNumber, sourceId)


CONSOLE_LOG = []


def sleep(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def js(page, code: str, timeout: int = 6000):
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
  var d = {username:'qtverify', password:'QtVerify@2026', display_name:'Qt 审计账号'};
  var h = {'Content-Type':'application/json','X-Thimble-Request':'1'};
  (async function () {
    var s = await (await fetch('/api/auth/status', {headers:h})).json();
    if (!s.initialized) {
      await fetch('/api/auth/setup', {method:'POST', headers:h, body:JSON.stringify(d)});
    }
    var l = await fetch('/api/auth/login', {method:'POST', headers:h, body:JSON.stringify(d)});
    var next = new URLSearchParams(location.search).get('next') || '/';
    location.href = next;
  })().catch(function (e) { window.__qtLoginError = String(e); });
  return true;
})()"""

# 页面内统一安装错误收集（覆盖加载期之后的运行时错误）
INSTALL_ERR_HOOK = r"""(function () {
  window.__qtErrors = window.__qtErrors || [];
  var push = function (lvl, msg, src, line) {
    window.__qtErrors.push({lvl:lvl, msg:String(msg), src:String(src||''), line:line||0, t:Date.now()});
    if (window.__qtErrors.length > 200) window.__qtErrors.shift();
  };
  var oe = window.onerror;
  window.onerror = function (m, s, l, c, e) { push('error', m, s, l); if (oe) return oe(m,s,l,c,e); return false; };
  if (!window.__qtCEHooked && window.console && console.error) {
    var ce = console.error;
    window.__qtCEHooked = true;
    console.error = function () {
      try { push('console.error', Array.prototype.map.call(arguments, String).join(' ')); } catch(e){}
      return ce.apply(console, arguments);
    };
  }
  return true;
})()"""

PROBE_JS = r"""(function () {
  function txt(sel){var e=document.querySelector(sel);return e?(e.innerText||e.textContent||'').trim().slice(0,300):null;}
  function count(sel){return document.querySelectorAll(sel).length;}
  var frame = document.querySelector('#threeModelFrame');
  var frameDoc = null;
  try { frameDoc = frame && frame.contentDocument; } catch (e) {}
  function frameCount(sel){return frameDoc ? frameDoc.querySelectorAll(sel).length : 0;}
  var v = document.querySelector('.view.active');
  var errs = [];
  // 常见错误横幅
  ['#analysisAlerts','.error-banner','.alert-danger','.toast-error','[role=alert]'].forEach(function(s){
    var e=document.querySelector(s); if(e && (e.innerText||'').trim()) errs.push(s+': '+(e.innerText||'').trim().slice(0,200));
  });
  return JSON.stringify({
    activeView: v?v.id:'',
    bodyTextHead: (document.body.innerText||'').replace(/\s+/g,' ').slice(0,600),
    canvasCount: count('canvas'),
    threeFramePresent: !!frame,
    threeFrameLoaded: !!(frameDoc && frameDoc.body),
    threeFrameCanvasCount: frameCount('canvas'),
    svgCount: count('svg'),
    tableCount: count('table'),
    buttonCount: count('button'),
    navButtons: count('nav button[data-view]'),
    hasLoginForm: !!document.querySelector('form.login, #login, .login-form'),
    scrollW: document.documentElement.scrollWidth,
    clientW: document.documentElement.clientWidth,
    horizOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    firstTableCols: (function(){var t=document.querySelector('table');if(!t)return 0;var r=t.querySelector('tr');return r?r.children.length:0;})(),
    qtErrors: (window.__qtErrors||[]).length
  });
})()"""

VIEWS = ["workspace", "threeD", "analytics", "reports", "states"]
READY_JS = {
    "workspace": "(function(){var v=document.querySelector('.view.active');return !!v&&v.id==='workspace'&&/共\\s*\\d+\\s*条|检测记录/.test(v.innerText||'')})()",
    "threeD": "(function(){var v=document.querySelector('.view.active'),f=document.querySelector('#threeModelFrame'),d=null;try{d=f&&f.contentDocument}catch(e){};return !!v&&v.id==='threeD'&&!!d&&!!d.querySelector('canvas')})()",
    "analytics": "(function(){var v=document.querySelector('.view.active');if(!v||v.id!=='analytics')return false;var w=document.querySelector('#analytics .an-wrap');var a=document.querySelector('#analysisAlerts');if(w&&w.classList.contains('viz-loading'))return false;if(a&&/正在读取本机检测数据/.test(a.innerText||''))return false;return !!(a&&a.innerText.trim())})()",
    "reports": "(function(){var v=document.querySelector('.view.active');return !!v&&v.id==='reports'&&/检验报告单|检验结果比对表/.test(v.innerText||'')})()",
    "states": "(function(){var v=document.querySelector('.view.active');return !!v&&v.id==='states'&&/状态概览|管板/.test(v.innerText||'')})()",
}
TIMEOUTS = {"workspace": 25000, "threeD": 15000, "analytics": 35000, "reports": 20000, "states": 20000}
SETTINGS_SECTIONS = [
    "settingsDataPane", "settingsPreferencesPane", "settingsImportPane",
    "settingsRulesPane", "settingsAccountsPane", "settingsMaintenancePane",
]
REPORT_TABS = ["检验结果比对表", "检验报告单"]


def main() -> int:
    app = QApplication(sys.argv)
    log = ServiceLog()
    backend = BackendService(log)
    protect_directory(USER_DATA)
    backend.start()

    import qt_shell.windows as _winmod
    _winmod.OfflinePage = AuditPage  # 注入控制台/错误捕获（不改源码）

    holder = [None]
    api = DesktopAPI(lambda: holder[0])
    profile = ShellProfile(api)
    profile.set_base_url(RUNTIME.base_url)
    holder[0] = profile
    shell = Shell(app, profile, api, log)
    window = shell.show_main()

    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "base_url": RUNTIME.base_url,
        "views": {}, "settings": {}, "dark": {}, "interactions": {},
        "console_errors": [], "errors": [],
    }

    try:
        for _ in range(80):
            if window._load_done:
                break
            sleep(500)
        js(window.page, INSTALL_ERR_HOOK)
        report["initial_href"] = js(window.page, "location.href")
        ready0 = js(window.page, "document.querySelectorAll('nav button[data-view]').length")
        need_login = "login" in str(report["initial_href"]).lower() or ready0 in (0, None)
        if need_login:
            ok, cost = False, 0
            login_err = None
            for attempt in range(3):
                js(window.page, LOGIN_JS)
                ok, cost, _ = wait_for(window.page,
                    "document.querySelectorAll('nav button[data-view]').length >= 5", 40000)
                login_err = js(window.page, "window.__qtLoginError || null")
                if ok:
                    break
                sleep(2000)
            report["login"] = {"entered_workspace": ok, "wait_ms": cost,
                               "error": login_err,
                               "cookie": profile.cookie_header()}
        else:
            report["login"] = {"entered_workspace": True, "reused_session": True}
        sleep(1800)

        for index, name in enumerate(VIEWS, 1):
            js(window.page,
               "(function(){var b=document.querySelector('nav button[data-view=\"%s\"]');"
               "if(b){b.click();return true}return false})()" % name)
            ok, cost, last = wait_for(window.page, READY_JS[name], TIMEOUTS[name])
            sleep(900)
            shot = ARTIFACTS / f"审计-{index:02d}-{name}-light.png"
            window.grab().save(str(shot))
            probe = js(window.page, PROBE_JS)
            try:
                dom = json.loads(probe) if isinstance(probe, str) else {}
            except ValueError:
                dom = {"raw": probe}
            # 报告页额外切换标签页
            if name == "reports":
                for ti, tab in enumerate(REPORT_TABS, 1):
                    clicked = js(window.page,
                        "(function(){var bs=[].slice.call(document.querySelectorAll('button, .tab, [role=tab]'));"
                        "var t=bs.find(function(b){return (b.innerText||'').indexOf(%r)>=0;});"
                        "if(t){t.click();return true}return false})()" % tab)
                    sleep(1200)
                    shot2 = ARTIFACTS / f"审计-04-reports-tab{ti}-{tab}.png"
                    window.grab().save(str(shot2))
                    report["interactions"].setdefault("reports_tabs", {})[tab] = {
                        "clicked": clicked, "screenshot": shot2.name}
            # 三维页尝试切换筛选（基地/机组下拉）并点击画布中心
            if name == "threeD":
                canvas_clicked = js(window.page,
                    "(function(){var f=document.querySelector('#threeModelFrame'),d=null;"
                    "try{d=f&&f.contentDocument}catch(e){};"
                    "var c=d&&d.querySelector('canvas');if(!c)return false;"
                    "var r=c.getBoundingClientRect();"
                    "var ev=new MouseEvent('click',{bubbles:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2});"
                    "c.dispatchEvent(ev);return true})()")
                sleep(1500)
                shot3 = ARTIFACTS / "审计-02-threeD-click.png"
                window.grab().save(str(shot3))
                report["interactions"]["threeD_canvas_click"] = {
                    "dispatched": canvas_clicked, "screenshot": shot3.name}
            if name == "analytics":
                action_checks = []
                for value in ("40", "65", "20"):
                    result = js(window.page,
                        "(function(value){var input=document.querySelector("
                        "'input[name=vwFrequencyThreshold][value=\"'+value+'\"]');"
                        "if(!input)return null;input.checked=true;"
                        "input.dispatchEvent(new Event('change',{bubbles:true}));"
                        "var ids=['vwDepthDistribution','vwFrequencyChart'];"
                        "return JSON.stringify(ids.map(function(id){var chart=document.getElementById(id);"
                        "var panel=chart&&chart.closest('.panel');var title=panel&&panel.querySelector(':scope > .panel-title');"
                        "return {id:id,groups:title?title.querySelectorAll(':scope > .vw-panel-actions').length:0,"
                        "exports:title?title.querySelectorAll(':scope > .vw-panel-actions > .vw-export').length:0}}))"
                        "})(%r)" % value)
                    try:
                        counts = json.loads(result) if isinstance(result, str) else None
                    except ValueError:
                        counts = None
                    action_checks.append({"threshold": value, "counts": counts})
                    if not counts or any(item["groups"] != 1 or item["exports"] != 1 for item in counts):
                        report["errors"].append(
                            f"visualization action duplication after threshold {value}: {counts}")
                report["interactions"]["visualization_export_actions"] = action_checks
            report["views"][name] = {
                "ready": ok, "wait_ms": cost, "last_probe": last,
                "screenshot": shot.name, **dom}

        # ---- 设置窗六分区 ----
        shell.open_settings_window("settingsDataPane")
        settings = shell.settings_window
        if settings is not None:
            for _ in range(60):
                if settings._load_done:
                    break
                sleep(500)
            for si, sec in enumerate(SETTINGS_SECTIONS, 1):
                shell.profile.emit_settings_section(sec)
                sleep(1500)
                shot = ARTIFACTS / f"审计-07-settings-{si:02d}-{sec}.png"
                settings.grab().save(str(shot))
                probe = js(settings.page, PROBE_JS)
                try:
                    dom = json.loads(probe) if isinstance(probe, str) else {}
                except ValueError:
                    dom = {"raw": probe}
                report["settings"][sec] = {"screenshot": shot.name, **dom}
        else:
            report["errors"].append("settings window missing")

        # ---- 暗色模式：回到主窗口逐视图 ----
        if shell.main_window:
            js(shell.main_window.page, "document.documentElement.setAttribute('data-theme','dark');"
                                      "window.dispatchEvent(new Event('themechange'));"
                                      "document.body&&(document.body.dataset.theme='dark');"
                                      "(function(){var s=document.createElement('style');"
                                      "s.id='__qtDarkForce';s.textContent='html[data-theme=dark]{background:#1f2a30!important}';"
                                      "document.head.appendChild(s);})();")
            sleep(1500)
            for index, name in enumerate(VIEWS, 1):
                js(shell.main_window.page,
                   "(function(){var b=document.querySelector('nav button[data-view=\"%s\"]');"
                   "if(b){b.click();return true}return false})()" % name)
                ok, cost, _ = wait_for(shell.main_window.page, READY_JS[name], TIMEOUTS[name])
                sleep(900)
                shot = ARTIFACTS / f"审计-{index:02d}-{name}-dark.png"
                shell.main_window.grab().save(str(shot))
                report["dark"][name] = {"ready": ok, "wait_ms": cost, "screenshot": shot.name}

        # 收集客户端收集到的运行时错误
        client_errs = js(window.page, "JSON.stringify(window.__qtErrors||[])")
        try:
            report["client_errors"] = json.loads(client_errs) if isinstance(client_errs, str) else []
        except ValueError:
            report["client_errors"] = []
        report["console_errors"] = CONSOLE_LOG
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        (ARTIFACTS / "审计全量.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        try:
            print(json.dumps({
                "login": report.get("login"),
                "views": {k: {"ready": v.get("ready"), "horizOverflow": v.get("horizOverflow"),
                              "qtErrors": v.get("qtErrors"), "hasLoginForm": v.get("hasLoginForm")}
                          for k, v in report["views"].items()},
                "settings": {k: {"horizOverflow": v.get("horizOverflow"), "canvasCount": v.get("canvasCount")}
                             for k, v in report["settings"].items()},
                "dark": {k: {"ready": v.get("ready")} for k, v in report["dark"].items()},
                "console_errors_count": len(CONSOLE_LOG),
                "client_errors_count": len(report.get("client_errors", [])),
                "errors": report["errors"],
            }, ensure_ascii=False))
        except Exception as _pe:  # noqa: BLE001
            print("PRINT_ERROR", _pe)
        shell.shutdown()
        backend.stop()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
