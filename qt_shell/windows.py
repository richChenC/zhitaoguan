"""Qt 窗口层：主窗口 / 独立设置窗 / 可视化弹出窗 / 加载重试 / 关闭守卫。

对应 main.cjs:228-430、window-close-guard.cjs、window-loading.cjs、
download-feedback.cjs 与 observeWindow() 的渲染进程恢复逻辑。
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QEventLoop, QTimer, QUrl
from PySide6.QtGui import QIcon
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QMainWindow, QMenu, QMessageBox, QSystemTrayIcon

from .constants import (
    APP_ICON, BACKGROUND, MAIN_WINDOW_MIN, MAIN_WINDOW_SIZE, PRODUCT_NAME,
    RUNTIME, SETTINGS_BACKGROUND, SETTINGS_WINDOW_MIN, SETTINGS_WINDOW_SIZE,
    VISUALIZATION_WINDOW_MIN, VISUALIZATION_WINDOW_SIZE,
)
from .offline_policy import allowed_url


def _permission_denied() -> QWebEnginePage.PermissionPolicy:
    policy = getattr(QWebEnginePage, "PermissionPolicy", QWebEnginePage)
    return getattr(policy, "PermissionDeniedByUser", 0)


class OfflinePage(QWebEnginePage):
    """同源导航白名单 + 禁止新窗口 + 权限请求一律拒绝。"""

    def acceptNavigationRequest(self, url: QUrl, nav_type, is_main_frame: bool) -> bool:  # noqa: N802
        if allowed_url(url.toString(), RUNTIME.base_url):
            return super().acceptNavigationRequest(url, nav_type, is_main_frame)
        return False

    def createWindow(self, window_type):  # noqa: N802
        return None


class BaseWindow(QMainWindow):
    def __init__(self, shell, *, title: str, size: tuple[int, int],
                 min_size: tuple[int, int], background: str, kind: str) -> None:
        super().__init__()
        self.shell = shell
        self.kind = kind
        self._close_allowed = False
        self._close_pending = False
        self._load_attempt = 0
        self._load_done = False
        self.setWindowTitle(title)
        if APP_ICON.is_file():
            self.setWindowIcon(QIcon(str(APP_ICON)))
        self.resize(*size)
        self.setMinimumSize(*min_size)
        self.setStyleSheet(f"QMainWindow{{background:{background};}}")

        self.view = QWebEngineView(self)
        self.page = OfflinePage(shell.profile.profile, self.view)
        self.page.setWebChannel(shell.profile.channel)
        self.view.setPage(self.page)
        self.setCentralWidget(self.view)

        self.page.loadFinished.connect(self._on_load_finished)
        self.page.renderProcessTerminated.connect(self._on_renderer_terminated)
        self.page.featurePermissionRequested.connect(self._on_feature_permission)
        self.page.setBackgroundColor(background)

    # ---- 页面加载（window-loading.cjs:3-35） ---------------------------
    def load_url(self, url: str) -> None:
        self._target_url = url
        self._load_attempt = 0
        self._load_done = False
        QTimer.singleShot(0, lambda: self._attempt_load(url))

    def _attempt_load(self, url: str) -> None:
        self._load_attempt += 1
        self.page.load(QUrl(url))
        QTimer.singleShot(30000, self._on_load_timeout)

    def _on_load_finished(self, ok: bool) -> None:
        if self._load_done:
            return
        if ok:
            self._load_done = True
            self.show()
            self.raise_()
            self.activateWindow()
            return
        self.shell.log.window(self.kind, f"load attempt {self._load_attempt}: failed")
        if self._load_attempt >= 3:
            self._load_done = True
            QMessageBox.critical(
                self, PRODUCT_NAME,
                f"界面加载失败，请关闭后重启软件。\n日志：{self.shell.log.path}",
            )
            return
        QTimer.singleShot(250 * self._load_attempt, lambda: self._attempt_load(self._target_url))

    def _on_load_timeout(self) -> None:
        if self._load_done:
            return
        self.page.triggerAction(QWebEnginePage.WebAction.Stop)

    def _on_feature_permission(self, origin, feature) -> None:
        self.page.setFeaturePermission(origin, feature, _permission_denied())

    def _on_renderer_terminated(self, termination_status, exit_code: int) -> None:
        self.shell.log.window(self.kind, f"renderer exited: {termination_status}, code={exit_code}")
        # app.quit() 会先终止渲染进程；此时属于正常收尾，不能弹窗阻塞事件循环。
        if self.shell.quitting or self._close_allowed or not self.isVisible():
            return
        choice = QMessageBox.critical(
            self, PRODUCT_NAME,
            "界面显示已中断\n\n已保存的数据不受影响。重新加载会丢弃尚未保存的界面修改。",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Ok,
        )
        if choice == QMessageBox.StandardButton.Ok:
            self._load_done = False
            self._attempt_load(self._target_url)
        else:
            self.close()

    # ---- 关闭守卫（window-close-guard.cjs） ---------------------------
    def _check_dirty(self) -> bool:
        holder = {"value": False}
        loop = QEventLoop()
        self.page.runJavaScript(
            "window.__thimbleUnsavedEdits?.() === true",
            lambda value: (holder.__setitem__("value", value is True), loop.quit()),
        )
        QTimer.singleShot(1500, loop.quit)
        loop.exec()
        return holder["value"]

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._close_allowed or self.shell.quitting:
            event.accept()
            super().closeEvent(event)
            # 主窗口关闭即退出应用；设置窗/可视化弹出窗关闭不影响主流程。
            if self.kind == "main":
                self.shell.request_exit()
            return
        event.ignore()
        if self._close_pending:
            return
        self._close_pending = True
        try:
            dirty = self._check_dirty()
            if dirty:
                choice = QMessageBox.warning(
                    self, PRODUCT_NAME,
                    "有未提交的修改\n\n关闭窗口将丢弃正在编辑但尚未保存的内容；已保存的数据不受影响。",
                    QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                )
                if choice != QMessageBox.StandardButton.Ok:
                    return
            self._close_allowed = True
            self.close()
        finally:
            self._close_pending = False


class Shell:
    """窗口管理器，同时充当 desktopAPI 的 shell 回调目标。"""

    def __init__(self, app, profile, desktop_api, log) -> None:
        self.app = app
        self.profile = profile
        self.desktop_api = desktop_api
        self.log = log
        self.quitting = False
        # 默认空实现；main.py 注入硬退出回调，独立测试脚本可安全直接构造 Shell。
        self.request_exit = lambda code=0: None
        self.main_window: BaseWindow | None = None
        self.settings_window: BaseWindow | None = None
        self.visualization_windows: list[BaseWindow] = []
        self._requested_settings_section = "settingsDataPane"
        desktop_api.set_shell(self)
        self._install_download_observer()
        self.tray = None
        self._tray_attempts = 0
        self._install_tray()

    def _install_tray(self) -> None:
        if self.quitting or self.tray is not None:
            return
        self._tray_attempts += 1
        icon = QIcon(str(APP_ICON))
        if icon.isNull():
            self.log.window("tray", f"application icon unavailable: {APP_ICON}")
            return
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.log.window("tray", f"notification area unavailable (attempt {self._tray_attempts})")
            if self._tray_attempts < 6:
                QTimer.singleShot(2000, self._install_tray)
            return
        tray = QSystemTrayIcon(icon, self.app)
        tray.setToolTip(PRODUCT_NAME)
        menu = QMenu()
        menu.addAction("显示主窗口", self.restore_main)
        menu.addAction("退出软件", self._close_from_tray)
        tray.setContextMenu(menu)
        tray.activated.connect(self._tray_activated)
        tray.show()
        self.tray = tray
        self.tray_menu = menu
        self.log.window("tray", "notification icon registered")

    def _tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.restore_main()

    def _close_from_tray(self) -> None:
        if self.main_window is not None:
            self.main_window.close()

    def restore_main(self) -> None:
        window = self.main_window
        if window is None:
            return
        if window.isMinimized():
            window.showNormal()
        else:
            window.show()
        window.raise_()
        window.activateWindow()

    def _install_download_observer(self) -> None:
        """download-feedback.cjs 的三态通知（QWebEngineDownloadRequest）。"""
        def on_download(download):
            filename = download.suggestedFileName() or "导出文件"
            interrupted = {"value": False}

            def on_state(state):
                name = str(state).lower()
                if "interrupted" in name:
                    if not interrupted["value"]:
                        interrupted["value"] = True
                        self.profile.emit_download_status("interrupted", filename)
                elif "completed" in name:
                    self.profile.emit_download_status("completed", filename)
                elif "cancelled" in name or "canceled" in name:
                    self.profile.emit_download_status("cancelled", filename)

            download.stateChanged.connect(on_state)
            download.accept()

        self.profile.profile.downloadRequested.connect(on_download)

    # ---- 主窗口 -------------------------------------------------------
    def show_main(self) -> BaseWindow:
        window = BaseWindow(
            self, title=PRODUCT_NAME, size=MAIN_WINDOW_SIZE,
            min_size=MAIN_WINDOW_MIN, background=BACKGROUND, kind="main",
        )
        self.main_window = window
        window.load_url(RUNTIME.start_url)
        window.showMaximized()
        return window

    # ---- 设置窗（main.cjs:352-403） -----------------------------------
    def open_settings_window(self, section: str) -> None:
        self._requested_settings_section = section
        existing = self.settings_window
        if existing and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            self.profile.emit_settings_section(section)
            return
        window = BaseWindow(
            self, title=f"{PRODUCT_NAME} - 软件设置", size=SETTINGS_WINDOW_SIZE,
            min_size=SETTINGS_WINDOW_MIN, background=SETTINGS_BACKGROUND, kind="settings",
        )
        self.settings_window = window
        window.destroyed.connect(lambda _object=None, token=id(window): self._on_settings_destroyed(token))
        window.load_url(RUNTIME.settings_url(section))
        QTimer.singleShot(600, lambda: self.profile.emit_settings_section(section))

    def _on_settings_destroyed(self, window_id: int) -> None:
        if self.settings_window is not None and id(self.settings_window) == window_id:
            self.settings_window = None

    def close_settings_window(self) -> None:
        if self.settings_window:
            self.settings_window._close_allowed = True
            self.settings_window.close()

    # ---- 可视化弹出窗（main.cjs:405-430） -----------------------------
    def open_visualization_window(self, panel: str, state_json: str) -> None:
        window = BaseWindow(
            self, title=f"{PRODUCT_NAME} - 图表对比", size=VISUALIZATION_WINDOW_SIZE,
            min_size=VISUALIZATION_WINDOW_MIN, background=BACKGROUND, kind="visualization",
        )
        self.visualization_windows.append(window)
        window.destroyed.connect(lambda *_: self.visualization_windows.remove(window)
                                 if window in self.visualization_windows else None)
        window.load_url(RUNTIME.visualization_url(panel, state_json))

    def shutdown(self) -> None:
        self.quitting = True
        if self.tray is not None:
            self.tray.hide()
        for window in [self.main_window, self.settings_window, *self.visualization_windows]:
            if window is not None:
                window._close_allowed = True
        # 不调用 app.quit()：QtWebEngine 下 quit 会停在渲染进程清理阶段。
        # 正式入口的退出由 request_exit 守护线程 os._exit 完成。
