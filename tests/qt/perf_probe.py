"""Measure Qt startup and in-document navigation against an isolated data copy."""
from __future__ import annotations

import json
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

QT_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = QT_ROOT.parent / "05_测试与验证" / "03_自动化临时产物"
TMP = ARTIFACT_ROOT / ("qt-perf-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
TMP.mkdir(parents=True)
DB = TMP / "isolated.db"
with sqlite3.connect((QT_ROOT / "user-data/data/thimble.db").as_uri() + "?mode=ro",
                     uri=True) as source, sqlite3.connect(DB) as target:
    source.backup(target)
    # Only the disposable copy loses identities; business rows stay unchanged.
    target.executescript("DELETE FROM login_sessions; DELETE FROM user_roles; DELETE FROM users;")
with socket.socket() as port_socket:
    port_socket.bind(("127.0.0.1", 0))
    port = port_socket.getsockname()[1]
os.environ.update({
    "THIMBLE_QT_TEST_DATA_ROOT": str(TMP),
    "THIMBLE_ALLOW_MULTI_INSTANCE": "1",
    "THIMBLE_DB_PATH": str(DB),
    "THIMBLE_DATA_DIR": str(TMP / "data"),
    "THIMBLE_OUTPUT_DIR": str(TMP / "output/excel"),
    "THIMBLE_REPORT_DIR": str(TMP / "output/reports"),
    "THIMBLE_LOG_PATH": str(TMP / "logs/server.log"),
    "THIMBLE_PORT": str(port),
})
sys.path.insert(0, str(QT_ROOT))
START = time.perf_counter()

import qt_shell.main  # noqa: E402,F401
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtWebEngineCore import QWebEngineScript  # noqa: E402
from qt_shell.backend_service import BackendService  # noqa: E402
from qt_shell.constants import RUNTIME, USER_DATA  # noqa: E402
from qt_shell.desktop_api import DesktopAPI  # noqa: E402
from qt_shell.log_utils import ServiceLog  # noqa: E402
from qt_shell.web_profile import ShellProfile  # noqa: E402
from qt_shell.windows import Shell  # noqa: E402


def pause(ms: int) -> None:
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(ms)
    loop.exec()


def js(page, code: str):
    values = []
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(5000)
    page.runJavaScript(code, lambda value: (values.append(value), loop.quit()))
    loop.exec()
    timer.stop()
    if not values:
        raise TimeoutError("JavaScript callback timed out")
    return values[0]


def wait(page, condition: str, seconds: int = 40) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        if js(page, condition):
            return
        pause(100)
    raise AssertionError("Page did not become ready: " + condition)


# Sample only this test process and its descendants, never whole-machine deltas.
def process_tree() -> dict:
    script = (
        "$rows=@(Get-CimInstance Win32_Process);"
        f"$ids=[Collections.Generic.HashSet[int]]::new();[void]$ids.Add({os.getpid()});"
        "do{$added=$false;foreach($row in $rows){"
        "if($ids.Contains([int]$row.ParentProcessId) -and $ids.Add([int]$row.ProcessId))"
        "{$added=$true}}}while($added);"
        "$result=@(Get-Process -Id @($ids) -ErrorAction SilentlyContinue |"
        "Where-Object {$_.ProcessName -match '^(pythonw?|QtWebEngineProcess|thimble-backend)$'} |"
        "Select-Object Id,ProcessName,WorkingSet64,CPU);"
        "ConvertTo-Json -InputObject $result -Compress"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        capture_output=True, text=True, timeout=20,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        raise RuntimeError("Cannot sample process tree: " + result.stderr[:500])
    rows = json.loads(result.stdout)
    return {
        "count": len(rows),
        "working_set_mb": round(sum(row["WorkingSet64"] for row in rows) / 1024 ** 2, 1),
        "cpu_seconds": round(sum(row["CPU"] or 0 for row in rows), 3),
        "detail": rows,
    }


INSTRUMENT = r"""
window.__perfErrors = [];
window.addEventListener('error', e => window.__perfErrors.push(String(e.message || 'resource error')));
window.addEventListener('unhandledrejection', e => window.__perfErrors.push(String(e.reason)));
window.__perfLongTasks = [];
new PerformanceObserver(list => {
  for (const item of list.getEntries()) window.__perfLongTasks.push({
    start_ms: Math.round(item.startTime), duration_ms: Math.round(item.duration)
  });
}).observe({type: 'longtask', buffered: true});
"""


def page_snapshot(page) -> dict:
    return json.loads(js(page, """JSON.stringify({
      href:location.href, active:document.querySelector('.view.active')?.id,
      nodes:document.querySelectorAll('*').length,
      errors:window.__perfErrors, long_tasks:window.__perfLongTasks,
      resources:performance.getEntriesByType('resource').map(r=>({
        path:new URL(r.name).pathname, type:r.initiatorType,
        ms:Math.round(r.duration), bytes:r.decodedBodySize
      }))
    })"""))


READY = {
    "workspace": "!!window.__thimbleState?.overview && !!document.querySelector('#rows tr')",
    "analytics": "document.querySelector('#analytics .official-viz')?.getAttribute('aria-busy') === 'false'",
    "reports": "!!document.querySelector('#rcPreview') && !!document.querySelector('#reportModeTabs')",
    "states": "!!document.querySelector('#stateRows tr') && !!window.stateMaintenance",
    "threeD": "document.querySelector('#threeModelFrame')?.contentWindow?.__thimbleReference?.ready === true",
}


def navigate(page, name: str) -> dict:
    code = r"""(() => {
      const name = %s, ready = () => (%s);
      const button = document.querySelector(`nav button[data-view="${name}"]`);
      if (!button) throw Error('Navigation button missing: ' + name);
      const result = window.__perfNavigation = {view:name};
      const start = performance.now();
      button.click();
      result.active = document.querySelector('.view.active')?.id;
      result.handler_ms = performance.now() - start;
      requestAnimationFrame(() => requestAnimationFrame(() => {
        result.paint_ms = performance.now() - start;
      }));
      const deadline = start + 45000;
      const check = () => {
        if (document.querySelector('.view.active')?.id === name && ready()) {
          result.ready_ms = performance.now() - start;
        } else if (performance.now() > deadline) {
          result.error = 'Workspace content readiness timed out';
        } else setTimeout(check, 25);
      };
      check();
      return true;
    })()""" % (json.dumps(name), READY[name])
    js(page, code)
    wait(page, "!!window.__perfNavigation?.error || (window.__perfNavigation?.paint_ms != null"
         " && window.__perfNavigation?.ready_ms != null)", seconds=50)
    result = json.loads(js(page, "JSON.stringify(window.__perfNavigation)"))
    assert result.get("active") == name and not result.get("error"), result
    if name == "analytics":
        assert not js(page, "!!document.querySelector('#vizRetry')"), "Analytics data request failed"
    return {key: round(value, 1) if isinstance(value, float) else value
            for key, value in result.items()}


def main() -> int:
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "test_root": str(TMP),
        "timer_scope": "Qt imports + QApplication + backend + first page (excludes DB snapshot)",
        "navigation_scope": "in-document handler, two animation frames, content readiness; not polling time",
    }
    backend = BackendService(ServiceLog())
    shell = None
    try:
        assert USER_DATA == TMP, "Qt profile must be isolated"
        app = QApplication(sys.argv)
        backend.start()
        report["backend_ready_ms"] = round((time.perf_counter() - START) * 1000)
        assert Path(backend._environment()["THIMBLE_DB_PATH"]) == DB
        holder = [None]
        api = DesktopAPI(lambda: holder[0])
        profile = ShellProfile(api)
        profile.set_base_url(RUNTIME.base_url)
        holder[0] = profile
        hook = QWebEngineScript()
        hook.setName("performance-probe")
        hook.setInjectionPoint(QWebEngineScript.DocumentCreation)
        hook.setWorldId(QWebEngineScript.MainWorld)
        hook.setSourceCode(INSTRUMENT)
        profile.profile.scripts().insert(hook)
        shell = Shell(app, profile, api, backend.log)
        window = shell.show_main()
        page = window.page
        wait(page, "!!document.querySelector('#localLoginForm')")
        report["login_visible_ms"] = round((time.perf_counter() - START) * 1000)
        credentials = {"username": "qtperf", "password": secrets.token_urlsafe(24),
                       "display_name": "qtperf"}
        js(page, """(() => {
          const body = %s;
          (async () => {
            const r=await fetch('/api/auth/setup',{method:'POST',
              headers:{'Content-Type':'application/json','X-Thimble-Request':'1'},
              body:JSON.stringify(body)});
            if (!r.ok) throw Error('Test administrator setup failed: ' + r.status);
            const login=await fetch('/api/auth/login',{method:'POST',
              headers:{'Content-Type':'application/json','X-Thimble-Request':'1'},
              body:JSON.stringify(body)});
            if (!login.ok) throw Error('Test administrator login failed: ' + login.status);
            location.assign('/');
          })().catch(e=>window.__perfLoginError=String(e));
          return true;
        })()""" % json.dumps(credentials))
        wait(page, "!!window.__perfLoginError || (!!window.localAccount?.user &&"
             " !!window.__thimbleState?.overview && !!document.querySelector('#rows tr'))")
        assert not js(page, "window.__perfLoginError || ''")
        assert js(page, "window.localAccount.user.username === 'qtperf'")
        report["authenticated_workbench_ms"] = round((time.perf_counter() - START) * 1000)
        pause(500)
        report["startup_page"] = page_snapshot(page)
        assert not js(page, "!!document.querySelector('#threeModelFrame')?.getAttribute('src')")
        assert not js(page, "!!document.querySelector('#oeWrap,#ledger,.an-secondary,.an-retired')")
        assert not any(
            row["path"].endswith(("/official-workspace.js", "/analysis-center.js"))
            for row in report["startup_page"]["resources"]
        ), "Heavy workspaces must stay unloaded at startup"
        report["initial_workbench_processes"] = process_tree()
        report["navigation_first"] = {}
        # Heavy workspaces go last so their load is not confused with workbench startup.
        for name in ("workspace", "states", "analytics", "reports", "threeD"):
            report["navigation_first"][name] = navigate(page, name)
            if name == "analytics":
                report["analytics_without_reports"] = json.loads(js(page, """JSON.stringify({
                  display:getComputedStyle(document.querySelector('#analytics .an-wrap')).display,
                  width:document.querySelector('#analytics .an-wrap').getBoundingClientRect().width,
                  overflow:document.documentElement.scrollWidth > innerWidth,
                  retired:!!document.querySelector('#oeWrap,#ledger,.an-secondary,.an-retired')
                })"""))
                assert report["analytics_without_reports"]["display"] == "grid"
                assert not report["analytics_without_reports"]["overflow"]
                window.grab().save(str(TMP / "analytics.png"))
        report["navigation_repeat"] = {}
        for name in ("workspace", "states", "reports", "analytics", "threeD", "workspace"):
            report["navigation_repeat"][name] = navigate(page, name)
        report["final_page"] = page_snapshot(page)
        assert not report["final_page"]["errors"], report["final_page"]["errors"]
        report["layout_checks"] = []
        window.showNormal()
        for width, height in ((1480, 960), (1000, 720)):
            window.resize(width, height)
            for name in ("workspace", "states", "analytics", "reports"):
                navigate(page, name)
                layout = json.loads(js(page, """JSON.stringify({
                  view:document.querySelector('.view.active').id,
                  width:innerWidth, height:innerHeight,
                  overflow:document.documentElement.scrollWidth > innerWidth
                })"""))
                assert not layout["overflow"], layout
                report["layout_checks"].append(layout)
        report["all_views_processes"] = process_tree()
        report["blocked_requests"] = profile.blocked_report()
        report["status"] = "passed"
        return 0
    except Exception:
        report["status"] = "failed"
        report["error"] = traceback.format_exc()
        return 1
    finally:
        if shell:
            shell.shutdown()
        backend.stop()
        (TMP / "performance.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({key: value for key, value in report.items()
                          if key not in ("startup_page", "final_page")}, ensure_ascii=False),
              flush=True)


if __name__ == "__main__":
    os._exit(main())
