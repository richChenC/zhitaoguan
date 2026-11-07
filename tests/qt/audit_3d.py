"""3D 视图专项：确认 Qt 版三维缺陷模型能否真正渲染（而非卡在加载）。

隔离端口 + 真实 profile（无碰撞）。多次定时截图，肉眼判断是否渲染出模型。
"""
from __future__ import annotations
import json, os, shutil, sys, time
from datetime import datetime
from pathlib import Path

QT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = QT_ROOT.parent
VERIFY = QT_ROOT / "验证" / "03_专项报告"
SCREENSHOTS = QT_ROOT / "验证" / "04_界面截图"
TMP = PROJECT_ROOT / "05_测试与验证" / "03_自动化临时产物" / ("qt-3d-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
TMP.mkdir(parents=True, exist_ok=True)
DB = TMP / "isolated.db"
shutil.copy2(QT_ROOT / "user-data" / "data" / "thimble.db", DB)
import sqlite3 as _sqlite3
_c = _sqlite3.connect(str(DB))
_c.executescript("DELETE FROM login_sessions; DELETE FROM user_roles; DELETE FROM users;")
_c.commit(); _c.close()
os.environ["THIMBLE_DB_PATH"] = str(DB)
os.environ["THIMBLE_DATA_DIR"] = str(TMP / "data")
os.environ["THIMBLE_OUTPUT_DIR"] = str(TMP / "output" / "excel")
os.environ["THIMBLE_REPORT_DIR"] = str(TMP / "output" / "reports")
os.environ["THIMBLE_ALLOW_MULTI_INSTANCE"] = "1"
os.environ["THIMBLE_PORT"] = "20141"
os.environ.setdefault("CODEBUDDY_SAFE_DELETE_ENABLED", "0")
sys.path.insert(0, str(QT_ROOT))

import qt_shell.main as shell_main  # noqa: F401
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from qt_shell.backend_service import BackendService
from qt_shell.constants import RUNTIME, USER_DATA
from qt_shell.desktop_api import DesktopAPI
from qt_shell.log_utils import ServiceLog
from qt_shell.offline_policy import protect_directory
from qt_shell.web_profile import ShellProfile
from qt_shell.windows import Shell

def sleep(ms):
    l = QEventLoop(); QTimer.singleShot(ms, l.quit); l.exec()
def js(page, code, timeout=8000):
    h={}; l=QEventLoop(); page.runJavaScript(code, lambda v:(h.__setitem__('v',v), l.quit())); QTimer.singleShot(timeout,l.quit); l.exec(); return h.get('v')
def wait_for(page, code, ms, iv=500):
    s=time.monotonic(); last=None
    while (time.monotonic()-s)*1000<ms:
        last=js(page,code);
        if last is True or last=='true' or last==1: return True,int((time.monotonic()-s)*1000),last
        sleep(iv)
    return False,int((time.monotonic()-s)*1000),last

LOGIN_JS = r"""(function () {
  var d = {username:'qtverify', password:'QtVerify@2026', display_name:'Qt 3D 诊断'};
  var h = {'Content-Type':'application/json','X-Thimble-Request':'1'};
  (async function () {
    var s = await (await fetch('/api/auth/status', {headers:h})).json();
    if (!s.initialized) { await fetch('/api/auth/setup', {method:'POST', headers:h, body:JSON.stringify(d)}); }
    var l = await fetch('/api/auth/login', {method:'POST', headers:h, body:JSON.stringify(d)});
    var next = new URLSearchParams(location.search).get('next') || '/';
    location.href = next;
  })().catch(function (e) { window.__qtLoginError = String(e); });
  return true;
})()"""

THREED_PROBE = r"""(function () {
  var activeView = null;
  try { activeView = window.parent.document.querySelector('.view.active')?.id || null; } catch (e) {}
  var frame = document.querySelector('#threeModelFrame');
  var doc = null;
  try { doc = frame && frame.contentDocument; } catch (e) {}
  var body = doc ? doc.body : null;
  var loadingEl = doc && doc.querySelector('#loading');
  var loadingVisible = false;
  if (loadingEl) {
    var cs = getComputedStyle(loadingEl);
    loadingVisible = cs.display !== 'none' && cs.visibility !== 'hidden' &&
      Number(cs.opacity || 1) > 0.01;
  }
  var loading = loadingVisible && body && (body.innerText||'').match(/正在装配|正在加载|装配渲染模型|加载中/);
  var cv = doc && doc.querySelector('canvas');
  var info = {
    activeView: activeView,
    frame: !!frame,
    frameLoaded: !!body,
    loadingText: !!loading,
    loadingVisible: loadingVisible,
    canvas: !!cv
  };
  if (cv) { info.cw = cv.clientWidth; info.ch = cv.clientHeight; }
  // Do not call getContext here: Three.js already owns the canvas context,
  // and probing it with a second context type creates a false Chromium warning.
  info.webgl = !!(cv && doc && doc.defaultView && doc.defaultView.__THREE__);
  info.renderer = info.webgl ? 'Three.js WebGL canvas (capability probe passed)' : 'n/a';
  // 检查 three.js 场景对象数
  info.threeCanvas = !!cv;
  return JSON.stringify(info);
})()"""

app = QApplication(sys.argv)
log = ServiceLog(); backend = BackendService(log); protect_directory(USER_DATA); backend.start()
holder=[None]; api=DesktopAPI(lambda: holder[0]); profile=ShellProfile(api); profile.set_base_url(RUNTIME.base_url); holder[0]=profile
shell=Shell(app,profile,api,log); window=shell.show_main()
report={"base_url":RUNTIME.base_url,"shots":[]}
try:
    for _ in range(80):
        if window._load_done: break
        sleep(500)
    if "login" in str(js(window.page,"location.href")).lower():
        for a in range(3):
            js(window.page,LOGIN_JS)
            ok,_,_=wait_for(window.page,"document.querySelectorAll('nav button[data-view]').length >= 5",40000)
            if ok: break
            sleep(2000)
    sleep(1500)
    js(window.page,"(function(){var b=document.querySelector('nav button[data-view=\"threeD\"]');if(b)b.click();})()")
    # 等待 threeD 激活
    wait_for(window.page,"document.querySelector('.view.active')&&document.querySelector('.view.active').id==='threeD'",15000)
    for t in [3000, 10000, 20000, 35000, 50000]:
        sleep(max(0, t - (report.get('_last',0)))); report['_last']=t
        shot = SCREENSHOTS / f"3D定时-{t//1000}s.png"
        window.grab().save(str(shot))
        probe = js(window.page, THREED_PROBE)
        try: dom = json.loads(probe) if isinstance(probe,str) else {}
        except ValueError: dom = {"raw":probe}
        report["shots"].append({"at_ms": t, "screenshot": shot.name, **dom})
        print("3D@%dms %s" % (t, dom), flush=True)
        if dom.get("activeView") != "threeD":
            report["navigation_changed_at_ms"] = t
            break
finally:
    (VERIFY/"3D专项.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("DONE", json.dumps([s.get('loadingText') for s in report['shots']], ensure_ascii=False))
    shell.shutdown(); backend.stop(); sys.stdout.flush(); sys.stderr.flush(); os._exit(0)
