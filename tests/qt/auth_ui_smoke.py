"""Isolated Qt authentication and layout smoke test."""
import json
import os
import sys
import time
import traceback
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))
if not os.environ.get("THIMBLE_QT_TEST_DATA_ROOT"):
    raise SystemExit("THIMBLE_QT_TEST_DATA_ROOT is required")
os.environ["THIMBLE_ALLOW_MULTI_INSTANCE"] = "1"

import qt_shell.main  # noqa: E402,F401
import qt_shell.backend_service as backend_module  # noqa: E402
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QInputDialog  # noqa: E402
from qt_shell.backend_service import BackendService  # noqa: E402
from qt_shell.constants import RUNTIME, USER_DATA  # noqa: E402
from qt_shell.desktop_api import DesktopAPI  # noqa: E402
from qt_shell.log_utils import ServiceLog  # noqa: E402
from qt_shell.web_profile import ShellProfile  # noqa: E402
from qt_shell.windows import Shell  # noqa: E402

if os.environ.get("THIMBLE_TEST_BACKEND_EXE"):
    backend_module.BACKEND_EXE = Path(os.environ["THIMBLE_TEST_BACKEND_EXE"])
    backend_module.BACKEND_SOURCE = Path("__no_source_backend__")


def pause(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def js(page, expression):
    result = []
    loop = QEventLoop()
    page.runJavaScript(expression, lambda value: (result.append(value), loop.quit()))
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    if not result:
        raise RuntimeError("JavaScript callback timed out")
    return result[0]


def wait(page, expression, seconds=30):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if js(page, expression):
            return
        pause(200)
    raise AssertionError(f"timed out: {expression}")


def main():
    app = QApplication(sys.argv)
    backend = BackendService(ServiceLog(USER_DATA / "auth-smoke.log"))
    backend.start()
    holder = [None]
    api = DesktopAPI(lambda: holder[0])
    profile = ShellProfile(api)
    profile.set_base_url(RUNTIME.base_url)
    holder[0] = profile
    shell = Shell(app, profile, api, ServiceLog(USER_DATA / "auth-smoke.log"))
    window = shell.show_main()
    report = {}
    try:
        page = window.page
        wait(page, "document.querySelector('#loginTitle')?.textContent === '建立管理员账户'")
        window.showNormal()
        window.resize(1100, 800)
        pause(500)
        report["setup"] = json.loads(js(page, """JSON.stringify({
          title:document.querySelector('#loginTitle').textContent,
          imageLoaded:document.querySelector('.login-mark').naturalWidth,
          overflow:document.documentElement.scrollWidth>innerWidth,
          formVisible:!document.querySelector('#confirmPasswordField').hidden,
          placeholder:document.querySelector('#loginUsername').placeholder})"""))
        assert report["setup"]["imageLoaded"] > 0 and not report["setup"]["overflow"]
        assert report["setup"]["formVisible"] and "完整拼音" in report["setup"]["placeholder"]
        window.grab().save(str(USER_DATA / "setup.png"))
        js(page, """(() => {
          document.querySelector('#loginUsername').value='ZhangSan';
          document.querySelector('#loginPassword').value='testpass123';
          document.querySelector('#loginConfirmPassword').value='different';
          document.querySelector('#localLoginForm').requestSubmit();
        })()""")
        wait(page, "document.querySelector('#loginMessage')?.textContent.includes('两次输入')")
        js(page, """(() => {
          document.querySelector('#loginConfirmPassword').value='testpass123';
          document.querySelector('#localLoginForm').requestSubmit();
        })()""")
        wait(page, "location.pathname==='/' && !!document.querySelector('#workspace')")
        wait(page, "!!document.querySelector('#localAccountButton') && typeof window.openSoftwareSettings === 'function'")
        js(page, "document.querySelector('#openImportFlow').click()")
        wait(page, "document.querySelector('#importDialog')?.open")
        assert js(page, "getComputedStyle(document.querySelector('#importDialog')).backgroundColor !== 'rgba(0, 0, 0, 0)'")
        js(page, "document.querySelector('#importDialog').close()")
        js(page, "document.querySelector('#localAccountButton').click()")
        wait(page, "!!document.querySelector('.local-account-dialog[open]')")
        assert js(page, "getComputedStyle(document.querySelector('.local-account-dialog')).backgroundColor === 'rgb(255, 255, 255)'")
        js(page, "Array.from(document.querySelectorAll('.local-account-dialog button')).find(b=>b.textContent==='账户与权限').click()")
        end = time.monotonic() + 20
        while time.monotonic() < end and (not shell.settings_window or not shell.settings_window.isVisible()):
            pause(200)
        assert shell.settings_window and shell.settings_window.isVisible(), "account settings window did not open"
        settings_page = shell.settings_window.page
        wait(settings_page, "document.querySelector('#settingsAccountsTab')?.getAttribute('aria-selected') === 'true'")
        js(settings_page, "document.querySelector('#settingsPreferencesTab').click()")
        wait(settings_page, "document.querySelector('#settingsPreferencesTab')?.getAttribute('aria-selected') === 'true'")
        shell.close_settings_window()
        pause(300)
        js(page, "document.querySelector('[data-open-settings]').click()")
        end = time.monotonic() + 20
        while time.monotonic() < end and (not shell.settings_window or not shell.settings_window.isVisible()):
            pause(200)
        assert shell.settings_window and shell.settings_window.isVisible(), "settings button did not open a window"
        wait(shell.settings_window.page, "document.querySelector('#settingsDataTab')?.getAttribute('aria-selected') === 'true'")
        shell.close_settings_window()
        js(page, "window.appAppearance.setTheme('dark');document.querySelector('#localAccountButton').click()")
        wait(page, "!!document.querySelector('.local-account-dialog[open]')")
        assert js(page, "getComputedStyle(document.querySelector('.local-account-dialog')).backgroundColor !== 'rgba(0, 0, 0, 0)'")
        js(page, "document.querySelector('.local-account-dialog').close();window.appAppearance.setTheme('light')")
        report["dialogs_and_settings"] = "passed"
        js(page, "fetch('/api/auth/me').then(r=>r.json()).then(x=>window.__authSmokeUser=x.user)")
        wait(page, "!!window.__authSmokeUser")
        assert js(page, "window.__authSmokeUser.username === 'zhangsan' && window.__authSmokeUser.display_name === 'zhangsan'")
        js(page, f"location.assign({json.dumps(RUNTIME.settings_url('settingsAccountsPane'))})")
        wait(page, "document.querySelector('#localAccountsPanel [name=display_name]')?.closest('label').hidden")
        js(page, """(() => {
          const form=document.querySelector('#localAccountsPanel form');
          const username=form.querySelector('[name=username]');
          username.value='LiSi';username.dispatchEvent(new Event('input',{bubbles:true}));
          form.querySelector('[name=password]').value='testpass123';
          form.querySelector('[name=confirm_password]').value='testpass123';
        })()""")
        assert js(page, "document.querySelector('#localAccountsPanel [name=display_name]').value === 'lisi'")
        js(page, "document.querySelector('#localAccountsPanel form').requestSubmit()")
        wait(page, "document.querySelector('#localAccountsPanel .auth-message')?.textContent.includes('账户已保存')")
        js(page, "fetch('/api/auth/users').then(r=>r.json()).then(x=>window.__smokeUsers=x.users)")
        wait(page, "!!window.__smokeUsers")
        assert js(page, "window.__smokeUsers.some(u=>u.username==='lisi' && u.display_name==='lisi')")
        assert js(page, "!document.querySelector('#localAccountsPanel [name=display_name]').closest('label').hidden")
        js(page, """(() => {
          const display=document.querySelector('#localAccountsPanel [name=display_name]');
          display.value='原有显示名称';display.dispatchEvent(new Event('input',{bubbles:true}));
          document.querySelector('#localAccountsPanel form').requestSubmit();
        })()""")
        wait(page, "document.querySelector('#localAccountsPanel .auth-message')?.textContent.includes('账户已保存')")
        js(page, "fetch('/api/auth/users').then(r=>r.json()).then(x=>window.__editedUsers=x.users)")
        wait(page, "!!window.__editedUsers")
        assert js(page, "window.__editedUsers.some(u=>u.username==='lisi' && u.display_name==='原有显示名称')")
        report["accounts"] = "passed"
        js(page, """fetch('/api/auth/logout',{method:'POST',headers:{
          'Content-Type':'application/json','X-Thimble-Request':'1'},body:'{}'})
          .then(()=>location.assign('/login.html'))""")
        wait(page, "document.querySelector('#loginTitle')?.textContent === '登录本地工作区'")
        window.resize(820, 620)
        pause(500)
        report["login"] = json.loads(js(page, """JSON.stringify({
          title:document.querySelector('#loginTitle').textContent,
          imageLoaded:document.querySelector('.login-mark').naturalWidth,
          overflow:document.documentElement.scrollWidth>innerWidth,
          setupHidden:document.querySelector('#confirmPasswordField').hidden})"""))
        assert report["login"]["imageLoaded"] > 0 and not report["login"]["overflow"]
        assert report["login"]["setupHidden"]
        assert js(page, "!document.querySelector('#loginFactoryReset')")
        window.grab().save(str(USER_DATA / "login.png"))
        js(page, """(() => {
          document.querySelector('#loginUsername').value='zhangsan';
          document.querySelector('#loginPassword').value='incorrect';
          document.querySelector('#localLoginForm').requestSubmit();
        })()""")
        wait(page, "document.querySelector('#loginMessage')?.dataset.state === 'error'")
        js(page, "window.appAppearance.setTheme('dark')")
        pause(300)
        window.grab().save(str(USER_DATA / "login-dark.png"))
        js(page, """(() => {
          document.querySelector('#loginPassword').value='testpass123';
          document.querySelector('#localLoginForm').requestSubmit();
        })()""")
        wait(page, "location.pathname==='/' && !!document.querySelector('#workspace')")
        report["tray"] = bool(shell.tray and shell.tray.isVisible())
        js(page, """fetch('/api/auth/logout',{method:'POST',headers:{
          'Content-Type':'application/json','X-Thimble-Request':'1'},body:'{}'})
          .then(()=>location.assign('/login.html'))""")
        wait(page, "document.querySelector('#loginTitle')?.textContent === '登录本地工作区'")
        js(page, """(() => {
          document.querySelector('#loginUsername').value='lisi';
          document.querySelector('#loginPassword').value='testpass123';
          document.querySelector('#localLoginForm').requestSubmit();
        })()""")
        wait(page, "location.pathname==='/' && !!window.localAccount?.user")
        js(page, """(() => {
          const node=document.createElement('button');
          node.id='testPermissionBtn';node.dataset.runDedup='1';document.body.append(node);
        })()""")
        wait(page, "document.querySelector('#testPermissionBtn')?.disabled === true")
        js(page, "document.querySelector('#testPermissionBtn').disabled=false")
        wait(page, "document.querySelector('#testPermissionBtn')?.disabled === true")
        js(page, """window.desktopAPI.factoryReset().catch(e=>window.__resetError=e.message)""")
        wait(page, "!!window.__resetError")
        assert js(page, "window.__resetError.includes('只有管理员')")
        assert not (USER_DATA / "factory-reset.json").exists()
        js(page, """fetch('/api/auth/logout',{method:'POST',headers:{
          'Content-Type':'application/json','X-Thimble-Request':'1'},body:'{}'})
          .then(()=>location.assign('/login.html'))""")
        wait(page, "document.querySelector('#loginTitle')?.textContent === '登录本地工作区'")
        js(page, """(() => {
          document.querySelector('#loginUsername').value='zhangsan';
          document.querySelector('#loginPassword').value='testpass123';
          document.querySelector('#localLoginForm').requestSubmit();
        })()""")
        wait(page, "location.pathname==='/' && !!window.localAccount?.user")
        js(page, f"location.assign({json.dumps(RUNTIME.settings_url('settingsMaintenancePane'))})")
        wait(page, "!!document.querySelector('#factoryResetPanel button')")
        QInputDialog.getText = staticmethod(lambda *args: ("恢复出厂", True))
        js(page, "document.querySelector('#factoryResetPanel button').click()")
        pause(1200)
        assert (USER_DATA / "factory-reset.json").exists()
        report["factory_reset"] = "passed"
        report["status"] = "passed"
        print(json.dumps(report, ensure_ascii=False), flush=True)
    finally:
        shell.shutdown()
        backend.stop()
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception as error:
        traceback.print_exc()
        print(f"AUTH_SMOKE_FAILED: {error}", file=sys.stderr, flush=True)
        code = 1
    os._exit(code)
