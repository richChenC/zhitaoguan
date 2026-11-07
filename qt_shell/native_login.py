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


class NativeLoginWindow(QMainWindow):
    authenticated = Signal(dict)
    cancelled = Signal()

    def __init__(self, client: NativeClient, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.initialized = True
        self.setWindowTitle(f"{PRODUCT_NAME} - 本地登录")
        self.setMinimumSize(460, 360)
        self.resize(560, 430)
        if APP_ICON.is_file():
            from PySide6.QtGui import QIcon
            self.setWindowIcon(QIcon(str(APP_ICON)))

        root = QWidget(self)
        root.setObjectName("loginRoot")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(46, 36, 46, 36)
        outer.setSpacing(16)
        title = QLabel(PRODUCT_NAME)
        title.setObjectName("loginTitle")
        subtitle = QLabel("原生 Qt 工作区")
        subtitle.setObjectName("loginSubtitle")
        outer.addWidget(title)
        outer.addWidget(subtitle)

        form = QFormLayout()
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
        self.setStyleSheet(
            """
            QMainWindow { background: #f4f7f8; }
            #loginRoot { background: #f4f7f8; }
            #loginTitle { color: #16324f; font-size: 22px; font-weight: 700; }
            #loginSubtitle { color: #5b6b7a; font-size: 13px; }
            QLabel { color: #2c3e50; }
            QLineEdit { min-height: 34px; border: 1px solid #c7d1da; border-radius: 4px; padding: 0 10px; background: white; }
            QPushButton { min-height: 36px; padding: 0 24px; border-radius: 4px; background: #1769aa; color: white; font-weight: 600; }
            QPushButton:hover { background: #12568d; }
            """
        )
        self.username.returnPressed.connect(self._submit)
        self.password.returnPressed.connect(self._submit)
        self._set_busy(True)
        self.client.get("/api/auth/status", self._on_status)

    def _set_busy(self, busy: bool) -> None:
        self.submit.setEnabled(not busy)
        self.submit.setText("检查中..." if busy else ("创建管理员并进入" if not self.initialized else "登录"))

    def _on_status(self, data: dict[str, Any] | None, error: str | None) -> None:
        if error or not data:
            self._set_busy(False)
            self.message.setText(error or "无法读取本地账户状态")
            return
        self.initialized = bool(data.get("initialized"))
        self.display_name.setVisible(not self.initialized)
        self.confirm_password.setVisible(not self.initialized)
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
            self.close()
        else:
            QMessageBox.warning(self, PRODUCT_NAME, "账户初始化完成，请重新登录。")
