"""Qt 版启动入口（python -m qt_shell.main）。

对应 main.cjs 的 app.whenReady() 启动链。环境变量必须在 QApplication
创建之前设置，故模块顶层先做配置。
"""
from __future__ import annotations

import atexit
import os
import sys
import tempfile
from pathlib import Path

from .constants import APP_ICON, BACKEND_EXE, DATA_DIR, PRODUCT_NAME, RUNTIME, USER_DATA

# Configure native graphics before QApplication initialization.
os.environ.setdefault("QT_SCALE_FACTOR", "1")
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "0")
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
os.environ["THIMBLE_NATIVE_QT"] = "1"
if os.name == "nt" and os.environ.get("THIMBLE_NATIVE_QT") == "1":
    # The threaded scene-graph loop can deadlock when an embedded
    # QtQuick3D window is closed on Windows.
    os.environ.setdefault("QSG_RENDER_LOOP", "basic")
# Keep the frozen backend's temporary directory predictable.
os.environ.setdefault("TMP", tempfile.gettempdir())
os.environ.setdefault("TEMP", tempfile.gettempdir())

from PySide6.QtCore import QLockFile  # noqa: E402
from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from .backend_service import BackendService, ServiceStartError  # noqa: E402
from .factory_reset import apply as apply_factory_reset  # noqa: E402
from .log_utils import ServiceLog, startup_failure_message  # noqa: E402
from .directory_security import protect_directory  # noqa: E402
from .single_instance import (  # noqa: E402
    InstanceWakeServer,
    wake_existing_until_ready,
)


def _run_native_qt(app, backend, wake_server=None) -> int:
    """Run the native application and release graphics before stopping its service."""
    from .native_client import NativeClient
    from .native_login import NativeLoginWindow
    from .native_windows import NativeMainWindow

    client = NativeClient(RUNTIME.base_url, app)
    login = NativeLoginWindow(client)
    state = {"main": None, "closing": False}

    def show_login() -> None:
        if state["closing"]:
            return
        previous = state["main"]
        state["main"] = None
        login.password.clear()
        login.confirm_password.clear()
        login.message.clear()
        login.show()
        if previous is not None:
            previous.close()
            previous.deleteLater()
        login._set_busy(True)
        client.get("/api/auth/status", login._on_status)
        login.raise_()
        login.activateWindow()

    def show_main(user: dict) -> None:
        if state["closing"]:
            return
        try:
            window = NativeMainWindow(client, user)
        except Exception as exc:
            import traceback
            ServiceLog().write("[native] main window initialization failed\n" + traceback.format_exc())
            login.show()
            login._set_busy(False)
            login.message.setText(f"工作区初始化失败：{exc}。请查看运行日志后重新登录。")
            return
        state["main"] = window
        window.logoutRequested.connect(show_login)
        window.closed.connect(lambda: app.quit() if state["main"] is window else None)
        login.hide()
        window.showMaximized()

    def restore() -> None:
        window = state["main"] or login
        if window.isMinimized():
            window.showNormal()
        else:
            window.show()
        window.raise_()
        window.activateWindow()

    login.authenticated.connect(show_main)
    login.cancelled.connect(app.quit)
    if wake_server is not None:
        wake_server.wake_requested.connect(restore)
    app.aboutToQuit.connect(lambda: state.__setitem__("closing", True))
    login.show()
    try:
        return app.exec()
    finally:
        client.abort_all()
        if state["main"] is not None:
            state["main"].deleteLater()
        login.deleteLater()
        from PySide6.QtCore import QCoreApplication, QEvent
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        backend.stop()


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
        # The first process owns the lock before its backend and native
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
    # Login/logout deliberately replace the visible top-level window.
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

    try:
        return _run_native_qt(app, backend, wake_server)
    finally:
        backend.stop()
        _release_single_instance(lock)


if __name__ == "__main__":
    sys.exit(main())
