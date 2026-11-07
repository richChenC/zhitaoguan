"""登录诊断：隔离 profile+端口，验证 Qt 版能否完成登录进入工作台。"""
from __future__ import annotations
import json, os, shutil, sys, time
from datetime import datetime
from pathlib import Path

QT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = QT_ROOT.parent
TMP = PROJECT_ROOT / "05_测试与验证" / "03_自动化临时产物" / ("qt-diag-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
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
os.environ["THIMBLE_PORT"] = "20131"
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
def js(page, code, timeout=6000):
    h={}; l=QEventLoop(); page.runJavaScript(code, lambda v:(h.__setitem__('v',v), l.quit())); QTimer.singleShot(timeout,l.quit); l.exec(); return h.get('v')
def wait_for(page, code, ms, iv=400):
    s=time.monotonic(); last=None
    while (time.monotonic()-s)*1000<ms:
        last=js(page,code);
        if last is True or last=='true' or last==1: return True,int((time.monotonic()-s)*1000),last
        sleep(iv)
    return False,int((time.monotonic()-s)*1000),last

LOGIN_JS = r"""(function () {
  var d = {username:'qtverify', password:'QtVerify@2026', display_name:'Qt 诊断账号'};
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

app = QApplication(sys.argv)
log = ServiceLog(); backend = BackendService(log); protect_directory(USER_DATA); backend.start()
import qt_shell.constants as _c, qt_shell.web_profile as _wp
_PROF = TMP/"qtwebengine"; _PROF.mkdir(parents=True, exist_ok=True); _c.WEBENGINE_DIR=_PROF; _wp.WEBENGINE_DIR=_PROF
holder=[None]; api=DesktopAPI(lambda: holder[0]); profile=ShellProfile(api); profile.set_base_url(RUNTIME.base_url); holder[0]=profile
shell=Shell(app,profile,api,log); window=shell.show_main()
res={"base_url":RUNTIME.base_url}
try:
    for _ in range(80):
        if window._load_done: break
        sleep(500)
    res["initial_href"]=js(window.page,"location.href")
    ready0=js(window.page,"document.querySelectorAll('nav button[data-view]').length")
    need="login" in str(res["initial_href"]).lower() or ready0 in (0,None)
    res["need_login"]=need
    if need:
        ok,cost=False,0; err=None
        for a in range(3):
            js(window.page,LOGIN_JS)
            ok,cost,_=wait_for(window.page,"document.querySelectorAll('nav button[data-view]').length >= 5",40000)
            err=js(window.page,"window.__qtLoginError || null")
            if ok: break
            sleep(2000)
        res["login"]={"entered":ok,"wait_ms":cost,"error":err,"cookie":profile.cookie_header()}
    else:
        res["login"]={"entered":True,"reused":True}
    sleep(2000)
    res["after_nav_count"]=js(window.page,"document.querySelectorAll('nav button[data-view]').length")
    res["active_view"]=js(window.page,"(document.querySelector('.view.active')||{}).id||''")
    res["body_head"]=(js(window.page,"(document.body.innerText||'').replace(/\\s+/g,' ').slice(0,200)") or "")
finally:
    print(json.dumps(res, ensure_ascii=False))
    shell.shutdown(); backend.stop(); sys.stdout.flush(); sys.stderr.flush(); os._exit(0)
