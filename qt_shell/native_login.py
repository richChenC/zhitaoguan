"""Native Qt authentication window."""
from __future__ import annotations

from typing import Any
from time import monotonic

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap, QRadialGradient
from PySide6.QtWidgets import (
    QCheckBox,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .constants import APP_ICON, PRODUCT_NAME, UI_DIR
from .native_client import NativeClient
from .native_components import Preferences, workspace_styles


class LoginBackground(QWidget):
    def __init__(self):
        super().__init__()
        self.dark = False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#11191b" if self.dark else "#edf1f1"))
        if self.dark:
            # The reference's final dark stylesheet retains two elliptical gradients.
            for rx, ry, cx, cy, color in ((900, 520, 1.08, 1.12, "#16262a"),
                                          (1100, 520, .08, -.12, "#143332")):
                painter.save()
                painter.scale(1, ry / rx)
                gradient = QRadialGradient(self.width() * cx, self.height() * cy * rx / ry, rx)
                gradient.setColorAt(0, QColor(color))
                transparent = QColor(color)
                transparent.setAlpha(0)
                gradient.setColorAt(.6 if rx == 900 else .58, transparent)
                painter.fillRect(0, 0, self.width(), round(self.height() * rx / ry), gradient)
                painter.restore()


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

        scroll = self.scroll = QScrollArea(self)
        scroll.setObjectName("loginScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setCentralWidget(scroll)
        root = self.root = LoginBackground()
        root.setObjectName("loginRoot")
        scroll.setWidget(root)
        outer = self.outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 24, 18, 24)
        outer.addStretch()
        shell = self.shell = QWidget()
        shell.setObjectName("loginShell")
        shell.setFixedWidth(390)
        outer.addWidget(shell, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch()
        self.brand = QWidget(shell)
        brand = QHBoxLayout(self.brand)
        brand.setContentsMargins(0, 0, 0, 0)
        brand.setSpacing(10)
        brand.addStretch()
        logo_path = UI_DIR / "assets/app-icon.png"
        if logo_path.is_file():
            logo = QLabel()
            logo.setFixedSize(30, 30)
            logo.setPixmap(QPixmap(str(logo_path)).scaled(30, 30,
                Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            brand.addWidget(logo)
        product = QLabel("指套管数据管理工具")
        product.setObjectName("loginProduct")
        brand.addWidget(product)
        brand.addStretch()
        card = self.card = QWidget(shell)
        card.setObjectName("loginCard")
        self.card_shadow = QGraphicsDropShadowEffect(card)
        self.card_shadow.setBlurRadius(32)
        self.card_shadow.setOffset(0, 12)
        card.setGraphicsEffect(self.card_shadow)
        self.subtitle = QLabel("登录", card)
        self.subtitle.setObjectName("loginTitle")
        self.form_labels = []
        self.username = QLineEdit(card)
        self.username.setPlaceholderText("用户名")
        self.username.setAccessibleName("用户名")
        self.username.setMaxLength(64)
        self.username.setText(self.preferences.values["login_username"])
        self.display_name = QLineEdit(card)
        self.display_name.setPlaceholderText("姓名")
        self.display_name.setAccessibleName("姓名")
        self.display_name.setMaxLength(80)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("密码")
        self.password.setMaxLength(128)
        self.confirm_password = QLineEdit()
        self.confirm_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_password.setPlaceholderText("再次输入密码")
        self.confirm_password.setMaxLength(128)
        self.password_field, self.password_reveal = self._password_field(self.password)
        self.confirm_field, self.confirm_reveal = self._password_field(self.confirm_password)
        self.password.setAccessibleName("密码")
        self.confirm_password.setAccessibleName("确认密码")
        self.confirm_reveal.setAccessibleName("显示确认密码")
        self.fields = [self.display_name, self.username, self.password_field, self.confirm_field]
        for text, field in zip(("姓名", "用户名", "密码", "确认密码"), self.fields):
            label = QLabel(text, card)
            label.setObjectName("loginFieldLabel")
            label.setBuddy(self.password if field is self.password_field else (
                self.confirm_password if field is self.confirm_field else field))
            self.form_labels.append(label)
        self.strength_host = QWidget(card)
        strength_layout = QHBoxLayout(self.strength_host)
        strength_layout.setContentsMargins(0, 0, 0, 0)
        strength_layout.setSpacing(9)
        self.strength = QProgressBar()
        self.strength.setRange(0, 4)
        self.strength.setValue(0)
        self.strength.setTextVisible(False)
        self.strength.setFixedHeight(5)
        self.strength_text = QLabel("至少 6 位")
        self.strength_text.setObjectName("loginStrengthText")
        strength_layout.addWidget(self.strength, 1)
        strength_layout.addWidget(self.strength_text)
        self.password.textChanged.connect(self._password_strength)
        self.options = QWidget(card)
        self.remember = QCheckBox("记住登录", self.options)
        self.remember.setChecked(bool(self.preferences.values["login_username"]))
        self.remember.setToolTip("记住用户名并延长本次会话；本机服务重新启动或恢复数据库后需重新登录")
        options = QHBoxLayout(self.options)
        options.setContentsMargins(0, 0, 0, 0)
        options.addWidget(self.remember)
        options.addStretch()
        self.caps = QLabel("大写锁定")
        self.caps.setObjectName("loginCaps")
        self.caps.hide()
        options.addWidget(self.caps)
        for edit in (self.password, self.confirm_password):
            edit.installEventFilter(self)
        self.message = QLabel(card)
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setObjectName("loginMessage")
        self.submit = QPushButton("登录", card)
        self.submit.setDefault(True)
        self.submit.clicked.connect(self._submit)
        self.submit.setProperty("primary", True)
        self.footer = QWidget(card)
        self.footer.setObjectName("loginFooter")
        footer_layout = QHBoxLayout(self.footer)
        footer_layout.setContentsMargins(0, 12, 0, 0)
        footer_layout.setSpacing(6)
        footer_layout.addStretch()
        self.connection_dot = QWidget()
        self.connection_dot.setObjectName("loginConnectionDot")
        self.connection_dot.setFixedSize(6, 6)
        footer_layout.addWidget(self.connection_dot)
        self.service_status = QLabel("正在检查本机服务…")
        self.service_status.setObjectName("loginService")
        footer_layout.addWidget(self.service_status)
        footer_layout.addStretch()
        self._apply_theme()
        self.username.returnPressed.connect(self._submit)
        self.password.returnPressed.connect(self._submit)
        self.confirm_password.returnPressed.connect(self._submit)
        self.display_name.returnPressed.connect(self._submit)
        self.setTabOrder(self.display_name, self.username)
        self.setTabOrder(self.username, self.password)
        self.setTabOrder(self.password, self.password_reveal)
        self.setTabOrder(self.password_reveal, self.confirm_password)
        self.setTabOrder(self.confirm_password, self.confirm_reveal)
        self.setTabOrder(self.confirm_reveal, self.remember)
        self.setTabOrder(self.remember, self.submit)
        self._layout_content()
        self._set_busy(True)
        self.submit.setText("登录")
        self.client.get("/api/auth/status", self._on_status)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "footer"):
            self._layout_content()

    def _layout_content(self):
        small = self.width() <= 520
        padding, bottom = (20, 15) if small else (24, 14)
        self.outer.setContentsMargins(14 if small else 18, 18 if small else 24,
                                     14 if small else 18, 18 if small else 24)
        x, width = padding + 1, 390 - 2 * (padding + 1)
        def place(control, top, height):
            control.setGeometry(x, round(top), width, round(top + height) - round(top))
        title_height = 26 if small else 27.3
        place(self.subtitle, 25, title_height)
        y = 25 + title_height + 18
        for index, (label, field) in enumerate(zip(self.form_labels, self.fields)):
            visible = not self.initialized or index in (1, 2)
            label.setVisible(visible)
            field.setVisible(visible)
            if not visible:
                continue
            place(label, y, 18.6)
            place(field, y + 23.6, 40)
            y += 75.6
        if not self.initialized:
            y -= 4
            place(self.strength_host, y, 15.5)
            y += 27.5
        self.strength_host.setVisible(not self.initialized)
        place(self.options, y, 20)
        self.remember.setVisible(self.initialized)
        y += 32
        message_height = max(17, self.message.fontMetrics().boundingRect(
            0, 0, width, 1000, int(Qt.TextFlag.TextWordWrap), self.message.text()).height())
        place(self.message, y, message_height)
        y += message_height + 12
        place(self.submit, y, 42)
        y += 58
        place(self.footer, y, 27.5)
        card_height = y + 27.5 + bottom + 1
        self.card.setGeometry(0, 62, 390, round(card_height))
        self.brand.setGeometry(0, 0, 390, 48)
        self.shell.setFixedHeight(round(card_height + 62))
        margins = self.outer.contentsMargins()
        self.root.setMinimumHeight(self.shell.height() + margins.top() + margins.bottom())
        self.outer.activate()
        self.subtitle.setStyleSheet(f"font-size:{20 if small else 21}px; font-weight:700;")

    def _set_message(self, text, *, info=False):
        self.message.setText(text)
        self.message.setProperty("info", info)
        self.message.style().unpolish(self.message)
        self.message.style().polish(self.message)
        self._layout_content()

    def _password_field(self, edit):
        host = QWidget(self.card)
        host.setObjectName("loginPasswordField")
        edit.setFixedHeight(38)
        layout = QHBoxLayout(host)
        layout.setContentsMargins(1, 1, 5, 1)
        layout.setSpacing(0)
        reveal = QPushButton("显示")
        reveal.setCheckable(True)
        reveal.setFixedSize(40, 30)
        reveal.setObjectName("loginReveal")
        reveal.setAccessibleName("显示密码")
        def toggle(checked):
            edit.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password)
            reveal.setText("隐藏" if checked else "显示")
            confirmation = edit is self.confirm_password
            reveal.setAccessibleName(("隐藏确认密码" if checked else "显示确认密码") if confirmation else (
                "隐藏密码" if checked else "显示密码"))
            edit.setFocus(Qt.FocusReason.OtherFocusReason)
            edit.setCursorPosition(len(edit.text()))
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
        self.strength_text.setText("至少 6 位" if not text else "强度：" + ("偏弱", "偏弱", "一般", "较强", "很强")[score])
        color = ("#c58a32", "#c58a32", "#b88725", "#16876f", "#0b7773")[score]
        self.strength.setStyleSheet(f"QProgressBar::chunk {{ background:{color}; }}")

    def eventFilter(self, watched, event):
        from PySide6.QtCore import QEvent
        if event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease, QEvent.Type.FocusIn):
            import sys
            if sys.platform == "win32":
                import ctypes
                self.caps.setVisible(bool(ctypes.windll.user32.GetKeyState(0x14) & 1))
        elif event.type() == QEvent.Type.FocusOut:
            self.caps.hide()
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            host = self.password_field if watched is self.password else self.confirm_field
            host.setProperty("focused", event.type() == QEvent.Type.FocusIn)
            host.style().unpolish(host)
            host.style().polish(host)
        return super().eventFilter(watched, event)

    def _apply_theme(self):
        theme = self.preferences.values["theme"]
        if theme == "system":
            from PySide6.QtGui import QGuiApplication
            theme = "dark" if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"
        dark = theme == "dark"
        self.root.dark = dark
        self.root.update()
        self.card_shadow.setColor(QColor(0, 0, 0, 89) if dark else QColor(25, 52, 58, 20))
        self.setStyleSheet(workspace_styles(theme) + f"""
            #loginRoot, #loginScroll {{ background:transparent; border:0; }}
            #loginShell {{ background:{'#1c2628' if dark else 'transparent'}; }}
            #loginScroll QScrollBar:vertical {{ width:15px; }}
            #loginCard {{ background:{'#1c2628' if dark else '#ffffff'};
                border:1px solid {'#3b4c4d' if dark else '#d6e0e2'};
                border-top:3px solid {'#70cbbd' if dark else '#087d79'}; border-radius:10px; }}
            #loginProduct {{ font-size:14px; font-weight:700; }}
            #loginFieldLabel {{ font-size:12px; font-weight:600; }}
            #loginCard, #loginProduct, #loginFieldLabel, #loginTitle {{ color:{'#e5eeec' if dark else '#202e35'}; }}
            #loginPasswordField {{ border:1px solid {'#536663' if dark else '#bfcdd0'}; border-radius:4px; }}
            #loginPasswordField[focused="true"] {{ border-color:#168781; }}
            #loginCard QLineEdit {{ color:{'#e5eeec' if dark else '#202e35'}; background:{'#1c2628' if dark else '#ffffff'};
                border:1px solid {'#536663' if dark else '#bfcdd0'}; border-radius:4px;
                padding:0 11px; min-height:0; max-height:16777215px; font-size:13px; font-weight:400; }}
            #loginPasswordField QLineEdit {{ border:0; padding:0 10px; }}
            #loginCard QLineEdit:focus {{ border-color:#168781; }}
            #loginPasswordField QLineEdit:focus {{ border:0; }}
            #loginReveal {{ border:0; background:transparent; padding:0; min-width:40px; max-width:40px;
                min-height:30px; max-height:30px;
                font-size:11px; font-weight:600; color:{'#9fb4b1' if dark else '#6a7f87'}; }}
            #loginReveal:hover {{ background:{'#243234' if dark else '#eef4f4'}; }}
            #loginCard QCheckBox {{ font-size:11px; font-weight:500; color:{'#a8b8b5' if dark else '#627178'}; spacing:7px; }}
            #loginCard QCheckBox::indicator {{ width:13px; height:13px; }}
            #loginCaps {{ color:{'#e7b966' if dark else '#93631c'}; font-size:10px; }}
            #loginService, #loginStrengthText {{ color:{'#a8b8b5' if dark else '#627178'}; font-size:10px; }}
            #loginFooter {{ border-top:1px solid {'#3b4c4d' if dark else '#d6e0e2'}; }}
            #loginConnectionDot {{ border:0; border-radius:3px; background:#36886c; }}
            #loginCard QProgressBar {{ border:0; background:{'#2b3b3d' if dark else '#e7eef0'}; }}
            #loginCard QPushButton[primary="true"] {{ min-height:0; max-height:16777215px; padding:0; font-size:13px;
                font-weight:700; color:#ffffff; background:#087d79; }}
            #loginCard QPushButton[primary="true"]:hover {{ background:#075d60; border-color:#075d60; }}
            #loginMessage {{ font-size:11px; color:{'#eea2a6' if dark else '#a43d45'}; }}
            #loginMessage[info="true"] {{ color:{'#a8b8b5' if dark else '#627178'}; }}
        """ + """
            #loginTitle { font-size:21px; font-weight:700; }
        """)

    def _set_busy(self, busy: bool) -> None:
        if self._lock_until > monotonic():
            self._update_lock()
            return
        self.submit.setEnabled(not busy)
        self.submit.setText(("正在创建…" if not self.initialized else "正在验证…") if busy else (
            "创建并进入" if not self.initialized else "登录"))

    def _on_status(self, data: dict[str, Any] | None, error: str | None) -> None:
        if error or not data:
            self._set_busy(False)
            self._set_message(error or "无法读取本地账户状态")
            self.service_status.setText("本地服务未就绪")
            return
        self.initialized = bool(data.get("initialized"))
        self.service_status.setText("本地服务已连接")
        self.subtitle.setText("登录" if self.initialized else "创建管理员账户")
        self.username.setPlaceholderText("用户名" if self.initialized else "如 zhangsan")
        self.password.setPlaceholderText("密码" if self.initialized else "至少 6 位")
        self._layout_content()
        self._set_busy(False)
        self.username.setFocus(Qt.FocusReason.OtherFocusReason)

    def _submit(self) -> None:
        if not self.submit.isEnabled():
            return
        username = self.username.text().strip()
        password = self.password.text()
        if not username or not password:
            self._set_message("请填写账户和密码")
            return
        if not self.initialized:
            if not self.display_name.text().strip():
                self._set_message("首次使用请填写姓名")
                return
            if password != self.confirm_password.text():
                self._set_message("两次输入的密码不一致")
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
        self._set_message("")
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
                self._set_message("账户已停用，请联系系统管理员。" if (data or {}).get("account_disabled") else (
                    (error or "登录失败") + (f"，还可尝试 {remaining} 次" if remaining is not None else "")))
            return
        if data.get("user"):
            try:
                self.preferences.save(login_username=self.username.text().strip() if self.remember.isChecked() else "")
            except OSError as exc:
                self._set_message(f"账户偏好保存失败：{exc}")
            self.password.clear()
            self.confirm_password.clear()
            self.password_reveal.setChecked(False)
            self.confirm_reveal.setChecked(False)
            self.authenticated.emit(data["user"])
        elif not self.initialized and data.get("ok"):
            self._on_status({"initialized": True}, None)
            self._set_busy(True)
            self._set_message("账户已创建，正在登录…", info=True)
            self.client.post("/api/auth/login", {"username": self.username.text().strip(),
                                                "password": self.password.text()}, self._on_auth)
        else:
            self._set_message("账户响应缺少登录信息，请重试")

    def _update_lock(self):
        remaining = max(0, int(self._lock_until - monotonic() + .999))
        if not remaining:
            self.lock_timer.stop()
            self._lock_until = 0
            self._set_busy(False)
            self._set_message("锁定已解除，可以重新登录。", info=True)
            return
        text = f"{remaining // 60:02}:{remaining % 60:02}"
        self.submit.setEnabled(False)
        self.submit.setText(f"已锁定 {text}")
        self._set_message(f"登录失败次数过多，账户已锁定。请在 {text} 后重试。")

    def closeEvent(self, event):
        if self.isVisible():
            self.cancelled.emit()
        super().closeEvent(event)
