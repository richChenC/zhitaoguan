"""Qt 版启动入口（python -m qt_shell.main）。

对应 main.cjs 的 app.whenReady() 启动链。环境变量必须在 QApplication
创建之前设置，故模块顶层先做配置。
"""
from __future__ import annotations

import atexit
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

from .constants import APP_ICON, BACKEND_EXE, CHROMIUM_FLAGS, DATA_DIR, PRODUCT_NAME, RUNTIME, USER_DATA

# ---- 必须在 QApplication / QWebEngine 初始化之前 -----------------------
os.environ.setdefault("QT_SCALE_FACTOR", "1")
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "0")
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(CHROMIUM_FLAGS)
# 保证 PyInstaller onefile 后端与 QtWebEngine 的解包目录在可控位置
os.environ.setdefault("TMP", tempfile.gettempdir())
os.environ.setdefault("TEMP", tempfile.gettempdir())

from PySide6.QtCore import QLockFile  # noqa: E402
from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from .backend_service import BackendService, ServiceStartError  # noqa: E402
from .desktop_api import DesktopAPI  # noqa: E402
from .factory_reset import apply as apply_factory_reset  # noqa: E402
from .log_utils import ServiceLog, startup_failure_message  # noqa: E402
from .offline_policy import protect_directory  # noqa: E402
from .single_instance import (  # noqa: E402
    InstanceWakeServer,
    wake_existing_until_ready,
)
from .web_profile import ShellProfile  # noqa: E402
from .windows import Shell  # noqa: E402


def _make_hard_exit(shell, backend, lock):
    """QtWebEngine 的 app.quit() 在本机不返回、也不发 aboutToQuit。

    退出统一由守护线程收尾：留 0.6s 给 WebEngine 落盘 Cookie/缓存，
    再停后端并 os._exit，彻底避开 Qt 内部等待渲染进程的死锁。
    """
    state = {"called": False}

    def hard_exit(code: int = 0) -> None:
        if state["called"]:
            return
        state["called"] = True
        shell.quitting = True
        if shell.tray is not None:
            shell.tray.hide()

        def runner() -> None:
            time.sleep(0.6)
            try:
                backend.stop()
            except Exception:  # noqa: BLE001  退出阶段不再抛错
                pass
            _release_single_instance(lock)
            try:
                if sys.stdout:
                    sys.stdout.flush()
                if sys.stderr:
                    sys.stderr.flush()
            finally:
                os._exit(code)

        threading.Thread(target=runner, name="qt-hard-exit", daemon=True).start()

    return hard_exit


def _single_instance() -> QLockFile | None:
    """Acquire a recoverable per-user lock for the Qt desktop process.

    ``QSharedMemory`` can leave a segment behind after a hard interpreter exit,
    which made a subsequent launch report a running instance even though no
    usable window remained.  ``QLockFile`` stores the owner PID and removes
    stale lock files automatically, while still preventing two live instances.
    """
    if os.environ.get("THIMBLE_ALLOW_MULTI_INSTANCE") == "1":
        return None
    lock_path = Path(tempfile.gettempdir()) / "thimble-qt-single-instance.lock"
    lock = QLockFile(str(lock_path))
    # A zero stale timeout makes QLockFile consult the recorded PID on every
    # launch, so an abandoned lock from a crashed process is recovered at once.
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        # The first process owns the lock before its backend and WebEngine
        # window are ready. Give that normal startup window time to publish
        # the wake server before reporting a real recovery failure.
        if not wake_existing_until_ready():
            QMessageBox.warning(
                None, PRODUCT_NAME,
                "软件已有进程运行，但无法唤醒窗口。请先检查其他桌面或已打开窗口，"
                "保存工作后关闭旧进程，再重新启动软件。",
            )
        return None
    return lock


def _release_single_instance(lock: QLockFile | None) -> None:
    if lock is None:
        return
    try:
        lock.unlock()
    except RuntimeError:
        # The lock may already have been reclaimed by Qt after an abnormal
        # shutdown; releasing it is best-effort during process teardown.
        pass


def _install_staged_backend(log) -> None:
    """Install the verified build only after acquiring the normal instance lock."""
    if os.environ.get("THIMBLE_QT_TEST_DATA_ROOT") or getattr(sys, "frozen", False):
        return
    staged = BACKEND_EXE.parent.parent / "backend-next" / BACKEND_EXE.name
    if not staged.is_file():
        return
    try:
        os.replace(staged, BACKEND_EXE)
        log.write("[desktop] installed staged backend\n")
    except OSError as exc:
        log.write(f"[desktop] staged backend not installed: {exc}\n")


_SMOKE_JS = r"""(function () {
  var nav = document.querySelectorAll('nav button[data-view]');
  return JSON.stringify({
    href: location.href,
    title: document.title,
    desktopAPI: typeof window.desktopAPI,
    apiMethodCount: window.desktopAPI ? Object.keys(window.desktopAPI).length : 0,
    bridgeReady: window.__qtBridgeReady === true,
    channelProbe: window.__qtProbeResult || null,
    navCount: nav.length,
    navLabels: Array.prototype.map.call(nav, function (b) { return b.textContent.trim(); }),
    viewCount: document.querySelectorAll('section.view').length,
    activeView: (document.querySelector('.view.active') || {}).id || '',
    stylesheets: document.styleSheets.length,
    scripts: document.scripts.length,
    bodyFont: getComputedStyle(document.body).fontFamily,
    bodyBg: getComputedStyle(document.body).backgroundColor,
    hasImportmap: !!(window.HTMLScriptElement && HTMLScriptElement.supports('importmap')),
    hasDvh: CSS.supports('height', '100dvh'),
    hasSelector: CSS.supports('selector(:has(*))'),
    randomUUID: typeof crypto.randomUUID
  });
})()"""


def _smoke_check(app, shell) -> None:
    """无人值守启动自检：截图 + 页面状态 + QWebChannel 往返，然后自动退出。"""
    import json
    from datetime import datetime

    from PySide6.QtCore import QTimer

    from .constants import VERIFY_DIR

    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    report = {"generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
              "base_url": RUNTIME.base_url}
    window = shell.main_window
    if window is None:
        report["error"] = "main window missing"
    else:
        report["window"] = {
            "title": window.windowTitle(),
            "width": window.width(), "height": window.height(),
            "url": window.page.url().toString(),
        }
        try:
            window.grab().save(str(VERIFY_DIR / "启动冒烟截图.png"))
            report["screenshot"] = "启动冒烟截图.png"
        except Exception as exc:
            report["screenshot_error"] = str(exc)
        window.page.runJavaScript(
            "window.__qtChannelProbe ? window.__qtChannelProbe()"
            ".then(function(r){window.__qtProbeResult=r;})"
            ".catch(function(e){window.__qtProbeResult={error:String(e)};}) : null;",
            lambda _: None,
        )

    def finish(extra: dict | None = None) -> None:
        if report.get("finished"):
            return
        report["finished"] = True
        if extra:
            report["page"] = extra
        report["blocked_requests"] = shell.profile.blocked_report()
        report["session_cookie_present"] = bool(shell.profile.cookie_header())
        (VERIFY_DIR / "启动冒烟.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if sys.stdout:
            print("SMOKE_REPORT", json.dumps(report, ensure_ascii=False))
            sys.stdout.flush()
        shell.request_exit()

    def collect() -> None:
        if window is None:
            finish()
            return
        window.page.runJavaScript(_SMOKE_JS, lambda raw: finish(
            json.loads(raw) if isinstance(raw, str) and raw.startswith("{") else {"raw": raw}
        ))

    QTimer.singleShot(1500, collect)
    QTimer.singleShot(10000, lambda: finish())


def main() -> int:
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "ThimbleInspection.QtDesktop"
            )
        except (AttributeError, OSError):
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(PRODUCT_NAME)
    app.setOrganizationName("ThimbleInspection")
    if APP_ICON.is_file():
        app.setWindowIcon(QIcon(str(APP_ICON)))
    # 关闭最后一个窗口不再交给 Qt 自动 quit（会卡在 WebEngine 清理），改由 Shell 统一硬退出。
    app.setQuitOnLastWindowClosed(False)
    lock = _single_instance()
    if lock is None and os.environ.get("THIMBLE_ALLOW_MULTI_INSTANCE") != "1":
        return 0
    wake_server = None
    if lock is not None:
        wake_server = InstanceWakeServer(app)
        if not wake_server.listen():
            _release_single_instance(lock)
            QMessageBox.critical(None, PRODUCT_NAME, "无法建立窗口唤醒服务，请重新启动软件。")
            return 1

    log = ServiceLog()
    backend = BackendService(log)
    try:
        protect_directory(USER_DATA)
        apply_factory_reset(USER_DATA)
        _install_staged_backend(log)
        backend.start()
    except ServiceStartError as exc:
        QMessageBox.critical(
            None, PRODUCT_NAME,
            startup_failure_message(
                exc, data_directory=str(DATA_DIR),
                temp_directory=tempfile.gettempdir(), log_path=str(log.path),
            ),
        )
        backend.stop()
        _release_single_instance(lock)
        return 1
    except Exception as exc:  # 目录权限等意外
        QMessageBox.critical(None, PRODUCT_NAME, f"初始化失败：{exc}")
        backend.stop()
        _release_single_instance(lock)
        return 1
    atexit.register(backend.stop)

    profile_holder: list[ShellProfile | None] = [None]
    api = DesktopAPI(lambda: profile_holder[0])
    profile = ShellProfile(api)
    profile.set_base_url(RUNTIME.base_url)
    profile_holder[0] = profile

    shell = Shell(app, profile, api, log)
    shell.request_exit = _make_hard_exit(shell, backend, lock)
    if wake_server is not None:
        wake_server.wake_requested.connect(shell.restore_main)
    shell.show_main()

    smoke_seconds = os.environ.get("THIMBLE_QT_SMOKE")
    if smoke_seconds:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(int(smoke_seconds) * 1000, lambda: _smoke_check(app, shell))

    try:
        code = app.exec()
    finally:
        shell.shutdown()
        backend.stop()
        _release_single_instance(lock)
        if sys.stdout:
            sys.stdout.flush()
        if sys.stderr:
            sys.stderr.flush()
    return code


if __name__ == "__main__":
    # 不走 sys.exit 的解释器析构：QWebEngineProfile/Page 在 Python GC 阶段释放会挂起或崩溃。
    os._exit(main())
