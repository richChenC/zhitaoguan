"""Native Qt authentication window."""
from __future__ import annotations

from typing import Any
from time import monotonic

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
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
        self._lock_until = 0
        self.lock_timer = QTimer(self)
        self.lock_timer.setInterval(1000)
        self.lock_timer.timeout.connect(self._update_lock)
        self.setWindowTitle(f"{PRODUCT_NAME} - 本地登录")
        self.setMinimumSize(460, 620)
        self.resize(1080, 760)
        if APP_ICON.is_file():
            from PySide6.QtGui import QIcon
            self.setWindowIcon(QIcon(str(APP_ICON)))

        root = QWidget(self)
        root.setObjectName("loginRoot")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 24, 18, 24)
        outer.addStretch()
        shell = QWidget()
        shell.setFixedWidth(390)
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(14)
        outer.addWidget(shell, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch()
        brand = QHBoxLayout()
        brand.setSpacing(10)
        brand.addStretch()
        if APP_ICON.is_file():
            from PySide6.QtGui import QIcon
            logo = QLabel()
            logo.setPixmap(QIcon(str(APP_ICON)).pixmap(30, 30))
            brand.addWidget(logo)
        product = QLabel("指套管数据管理工具")
        product.setObjectName("loginProduct")
        brand.addWidget(product)
        brand.addStretch()
        self.theme_toggle = QPushButton()
        self.theme_toggle.setIcon(icon("settings"))
        self.theme_toggle.setToolTip("切换日间/夜间外观")
        self.theme_toggle.setFixedWidth(36)
        self.theme_toggle.clicked.connect(self._toggle_theme)
        brand.addWidget(self.theme_toggle)
        shell_layout.addLayout(brand)
        card = QWidget()
        card.setObjectName("loginCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 22, 24, 14)
        card_layout.setSpacing(12)
        shell_layout.addWidget(card)
        self.subtitle = QLabel("登录")
        self.subtitle.setObjectName("loginTitle")
        card_layout.addWidget(self.subtitle)

        form = self.form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setVerticalSpacing(5)
        self.username = QLineEdit()
        self.username.setPlaceholderText("用户名")
        self.username.setMaxLength(64)
        self.username.setFixedHeight(40)
        self.username.setText(self.preferences.values["login_username"])
        self.display_name = QLineEdit()
        self.display_name.setPlaceholderText("姓名")
        self.display_name.setMaxLength(80)
        self.display_name.setFixedHeight(40)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("密码")
        self.password.setMaxLength(128)
        self.confirm_password = QLineEdit()
        self.confirm_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_password.setPlaceholderText("再次输入密码")
        self.confirm_password.setMaxLength(128)
        form.addRow("姓名", self.display_name)
        form.addRow("用户名", self.username)
        self.password_field, self.password_reveal = self._password_field(self.password)
        self.confirm_field, self.confirm_reveal = self._password_field(self.confirm_password)
        form.addRow("密码", self.password_field)
        form.addRow("确认密码", self.confirm_field)
        card_layout.addLayout(form)
        self.strength_host = QWidget()
        strength_layout = QHBoxLayout(self.strength_host)
        strength_layout.setContentsMargins(0, 0, 0, 0)
        self.strength = QProgressBar()
        self.strength.setRange(0, 4)
        self.strength.setTextVisible(False)
        self.strength.setFixedHeight(5)
        self.strength_text = QLabel("至少 6 位")
        self.strength_text.setObjectName("muted")
        strength_layout.addWidget(self.strength, 1)
        strength_layout.addWidget(self.strength_text)
        self.password.textChanged.connect(self._password_strength)
        card_layout.addWidget(self.strength_host)
        self.remember = QCheckBox("记住账户")
        self.remember.setChecked(bool(self.preferences.values["login_username"]))
        self.remember.setToolTip("记住用户名并延长本次会话；本机服务重新启动或恢复数据库后需重新登录")
        options = QHBoxLayout()
        options.addWidget(self.remember)
        options.addStretch()
        self.caps = QLabel("大写锁定")
        self.caps.setObjectName("loginCaps")
        self.caps.hide()
        options.addWidget(self.caps)
        for edit in (self.password, self.confirm_password):
            edit.installEventFilter(self)
        card_layout.addLayout(options)

        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setObjectName("loginMessage")
        card_layout.addWidget(self.message)
        self.submit = QPushButton("登录")
        self.submit.setDefault(True)
        self.submit.clicked.connect(self._submit)
        self.submit.setProperty("primary", True)
        self.submit.setFixedHeight(42)
        card_layout.addWidget(self.submit)
        self.service_status = QLabel("正在检查本机服务…")
        self.service_status.setObjectName("loginService")
        self.service_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.service_status)
        self._apply_theme()
        self.username.returnPressed.connect(self._submit)
        self.password.returnPressed.connect(self._submit)
        self._set_busy(True)
        self.client.get("/api/auth/status", self._on_status)

    def _password_field(self, edit):
        host = QWidget()
        host.setObjectName("loginPasswordField")
        host.setFixedHeight(40)
        edit.setFixedHeight(38)
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        reveal = QPushButton("显示")
        reveal.setCheckable(True)
        reveal.setFixedWidth(56)
        reveal.setObjectName("loginReveal")
        reveal.setAccessibleName("显示密码")
        def toggle(checked):
            edit.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password)
            reveal.setText("隐藏" if checked else "显示")
            reveal.setAccessibleName("隐藏密码" if checked else "显示密码")
        reveal.toggled.connect(toggle)
        layout.addWidget(edit, 1)
        layout.addWidget(reveal)
        return host, reveal

    def _password_strength(self, text):
        import re
        score = min(4, int(len(text) >= 6) + int(len(text) >= 10)
                    + int(bool(re.search("[a-zA-Z]", text) and re.search("[0-9]", text)))
                    + int(bool(re.search("[^a-zA-Z0-9]", text) and len(text) >= 8)))
        self.strength.setValue(score)
        self.strength_text.setText("至少 6 位" if len(text) < 6 else ("一般", "一般", "较好", "较强", "强")[score])

    def eventFilter(self, watched, event):
        from PySide6.QtCore import QEvent
        if event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease, QEvent.Type.FocusIn):
            import sys
            if sys.platform == "win32":
                import ctypes
                self.caps.setVisible(bool(ctypes.windll.user32.GetKeyState(0x14) & 1))
        elif event.type() == QEvent.Type.FocusOut:
            self.caps.hide()
        return super().eventFilter(watched, event)

    def _apply_theme(self):
        theme = self.preferences.values["theme"]
        if theme == "system":
            from PySide6.QtGui import QGuiApplication
            theme = "dark" if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"
        dark = theme == "dark"
        self.setStyleSheet(workspace_styles(theme) + f"""
            #loginRoot {{ background:{'#11191b' if dark else '#edf1f1'}; }}
            #loginCard {{ background:{'#1c2628' if dark else '#ffffff'};
                border:1px solid {'#3b4c4d' if dark else '#d6e0e2'};
                border-top:3px solid {'#35a99c' if dark else '#087d79'}; border-radius:10px; }}
            #loginProduct {{ font-size:14px; font-weight:600; }}
            #loginPasswordField {{ border:1px solid {'#536663' if dark else '#bfcdd0'}; border-radius:4px; }}
            #loginPasswordField QLineEdit {{ border:0; }}
            #loginReveal {{ border:0; background:transparent; padding:0; font-size:11px; }}
            #loginCaps {{ color:{'#e7b966' if dark else '#93631c'}; font-size:10px; }}
            #loginService {{ color:{'#a8b8b5' if dark else '#627178'}; font-size:10px;
                border-top:1px solid {'#3b4c4d' if dark else '#d6e0e2'}; padding-top:11px; }}
            #loginCard QProgressBar {{ border:0; background:{'#2b3b3d' if dark else '#e7eef0'}; }}
            #loginCard QProgressBar::chunk {{ background:#36886c; }}
        """ + """
            #loginTitle { font-size:21px; font-weight:600; }
            #loginCard QLineEdit { min-height:38px; max-height:38px; }
            #loginCard QPushButton[primary="true"] { min-height:40px; max-height:40px; }
            #loginCard #muted { font-size:10px; }
            #loginMessage { font-size:11px; }
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
        if self._lock_until > monotonic():
            self._update_lock()
            return
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
        self.subtitle.setText("登录" if self.initialized else "创建管理员")
        self.display_name.setVisible(not self.initialized)
        self.confirm_field.setVisible(not self.initialized)
        self.form.labelForField(self.display_name).setVisible(not self.initialized)
        self.form.labelForField(self.confirm_field).setVisible(not self.initialized)
        self.remember.setVisible(self.initialized)
        self.strength_host.setVisible(not self.initialized)
        self._set_busy(False)

    def _submit(self) -> None:
        if not self.submit.isEnabled():
            return
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
            payload = {"username": username, "password": password, "remember": self.remember.isChecked()}
        self._set_busy(True)
        self.message.setText("")
        self.client.post(path, payload, self._on_auth)

    def _on_auth(self, data: dict[str, Any] | None, error: str | None) -> None:
        self._set_busy(False)
        if error or not data:
            if data and data.get("locked_seconds"):
                self._lock_until = monotonic() + min(3600, max(1, int(data["locked_seconds"])))
                self.lock_timer.start()
                self._update_lock()
            else:
                remaining = (data or {}).get("remaining_attempts")
                self.message.setText((error or "登录失败") + (f"；还可尝试 {remaining} 次" if remaining is not None else ""))
            return
        if data.get("user"):
            try:
                self.preferences.save(login_username=self.username.text().strip() if self.remember.isChecked() else "")
            except OSError as exc:
                self.message.setText(f"账户偏好保存失败：{exc}")
            self.password.clear()
            self.confirm_password.clear()
            self.password_reveal.setChecked(False)
            self.confirm_reveal.setChecked(False)
            self.authenticated.emit(data["user"])
        elif not self.initialized and data.get("ok"):
            self._on_status({"initialized": True}, None)
            self._set_busy(True)
            self.message.setText("账户已创建，正在登录…")
            self.client.post("/api/auth/login", {"username": self.username.text().strip(),
                                                "password": self.password.text()}, self._on_auth)
        else:
            self.message.setText("账户响应缺少登录信息，请重试")

    def _update_lock(self):
        remaining = max(0, int(self._lock_until - monotonic() + .999))
        if not remaining:
            self.lock_timer.stop()
            self._lock_until = 0
            self._set_busy(False)
            self.message.setText("锁定已解除，可以重新登录")
            return
        text = f"{remaining // 60:02}:{remaining % 60:02}"
        self.submit.setEnabled(False)
        self.submit.setText(f"已锁定 {text}")
        self.message.setText(f"账户已锁定，请在 {text} 后重试")

    def closeEvent(self, event):
        if self.isVisible():
            self.cancelled.emit()
        super().closeEvent(event)
