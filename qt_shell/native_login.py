"""Native Qt authentication window."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .constants import APP_ICON, PRODUCT_NAME
from .native_client import NativeClient
from .native_components import Preferences, icon, workspace_styles


class NativeLoginWindow(QMainWindow):
    authenticated = Signal(dict)
    cancelled = Signal()

    def __init__(self, client: NativeClient, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.preferences = Preferences(self)
        self.initialized = True
        self.setWindowTitle(f"{PRODUCT_NAME} - 本地登录")
        self.setMinimumSize(460, 360)
        self.resize(620, 510)
        if APP_ICON.is_file():
            from PySide6.QtGui import QIcon
            self.setWindowIcon(QIcon(str(APP_ICON)))

        root = QWidget(self)
        root.setObjectName("loginRoot")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(46, 36, 46, 36)
        outer.setSpacing(16)
        brand = QHBoxLayout()
        if APP_ICON.is_file():
            from PySide6.QtGui import QIcon
            logo = QLabel()
            logo.setPixmap(QIcon(str(APP_ICON)).pixmap(46, 46))
            brand.addWidget(logo)
        brand.addStretch()
        self.theme_toggle = QPushButton()
        self.theme_toggle.setIcon(icon("settings"))
        self.theme_toggle.setToolTip("切换日间/夜间外观")
        self.theme_toggle.setFixedWidth(36)
        self.theme_toggle.clicked.connect(self._toggle_theme)
        brand.addWidget(self.theme_toggle)
        outer.addLayout(brand)
        title = QLabel(PRODUCT_NAME)
        title.setWordWrap(True)
        title.setObjectName("loginTitle")
        subtitle = QLabel("本地账户登录")
        subtitle.setObjectName("loginSubtitle")
        outer.addWidget(title)
        outer.addWidget(subtitle)
        self.subtitle = subtitle

        form = self.form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.username = QLineEdit()
        self.username.setPlaceholderText("2-64 位字母、数字、点、下划线或短横线")
        self.display_name = QLineEdit()
        self.display_name.setPlaceholderText("首次初始化时填写")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_password = QLineEdit()
        self.confirm_password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("账户", self.username)
        form.addRow("显示名称", self.display_name)
        form.addRow("密码", self.password)
        form.addRow("确认密码", self.confirm_password)
        outer.addLayout(form)

        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setObjectName("loginMessage")
        outer.addWidget(self.message)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.submit = QPushButton("登录")
        self.submit.setDefault(True)
        self.submit.clicked.connect(self._submit)
        buttons.addWidget(self.submit)
        outer.addLayout(buttons)
        outer.addStretch(1)
        self.service_status = QLabel("正在检查本机服务…")
        self.service_status.setObjectName("muted")
        outer.addWidget(self.service_status)
        self._apply_theme()
        self.username.returnPressed.connect(self._submit)
        self.password.returnPressed.connect(self._submit)
        self._set_busy(True)
        self.client.get("/api/auth/status", self._on_status)

    def _apply_theme(self):
        theme = self.preferences.values["theme"]
        if theme == "system":
            from PySide6.QtGui import QGuiApplication
            theme = "dark" if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"
        self.setStyleSheet(workspace_styles(theme) + """
            #loginTitle { font-size:21px; font-weight:600; }
            #loginSubtitle { font-size:13px; }
            QLineEdit { min-height:34px; }
        """)
        self.theme_toggle.setText("")
        self.theme_toggle.setIcon(icon("settings", theme))
        self.theme_toggle.setToolTip("切换为日间外观" if theme == "dark" else "切换为夜间外观")

    def _toggle_theme(self):
        dark = self.preferences.values["theme"] == "dark"
        try:
            self.preferences.save(theme="light" if dark else "dark")
            self._apply_theme()
        except OSError as exc:
            self.message.setText(str(exc))

    def _set_busy(self, busy: bool) -> None:
        self.submit.setEnabled(not busy)
        self.submit.setText("检查中..." if busy else ("创建管理员并进入" if not self.initialized else "登录"))

    def _on_status(self, data: dict[str, Any] | None, error: str | None) -> None:
        if error or not data:
            self._set_busy(False)
            self.message.setText(error or "无法读取本地账户状态")
            self.service_status.setText("本机服务连接失败")
            return
        self.initialized = bool(data.get("initialized"))
        self.service_status.setText("本机服务已连接 · 本地账户")
        self.subtitle.setText("本地账户登录" if self.initialized else "首次使用 · 创建管理员")
        self.display_name.setVisible(not self.initialized)
        self.confirm_password.setVisible(not self.initialized)
        self.form.labelForField(self.display_name).setVisible(not self.initialized)
        self.form.labelForField(self.confirm_password).setVisible(not self.initialized)
        self._set_busy(False)

    def _submit(self) -> None:
        username = self.username.text().strip()
        password = self.password.text()
        if not username or not password:
            self.message.setText("请填写账户和密码")
            return
        if not self.initialized:
            if not self.display_name.text().strip():
                self.message.setText("首次使用请填写显示名称")
                return
            if password != self.confirm_password.text():
                self.message.setText("两次输入的密码不一致")
                return
            path = "/api/auth/setup"
            payload = {
                "username": username,
                "display_name": self.display_name.text().strip(),
                "password": password,
            }
        else:
            path = "/api/auth/login"
            payload = {"username": username, "password": password}
        self._set_busy(True)
        self.message.setText("")
        self.client.post(path, payload, self._on_auth)

    def _on_auth(self, data: dict[str, Any] | None, error: str | None) -> None:
        self._set_busy(False)
        if error or not data:
            self.message.setText(error or "登录失败")
            return
        if data.get("user"):
            self.authenticated.emit(data["user"])
        elif not self.initialized and data.get("ok"):
            self._on_status({"initialized": True}, None)
            self._set_busy(True)
            self.message.setText("账户已创建，正在登录…")
            self.client.post("/api/auth/login", {"username": self.username.text().strip(),
                                                "password": self.password.text()}, self._on_auth)
        else:
            self.message.setText("账户响应缺少登录信息，请重试")

    def closeEvent(self, event):
        if self.isVisible():
            self.cancelled.emit()
        super().closeEvent(event)
