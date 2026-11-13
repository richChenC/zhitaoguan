"""Native login interaction, credential lifecycle and constrained window regression."""
import unittest

import native_test_env  # noqa: F401
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit

from qt_shell.native_components import Preferences
from qt_shell.native_login import NativeLoginWindow
from test_native_workflows import Client


class NativeLoginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        Preferences().save(theme="light", login_username="")
        self.client = Client()
        self.login = NativeLoginWindow(self.client)
        self.login._on_status({"initialized": False}, None)
        self.login.show()
        self.app.processEvents()

    def tearDown(self):
        self.login.close()
        self.login.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def test_invalid_setup_does_not_request_and_confirm_enter_submits_once(self):
        login = self.login
        before = len(self.client.requests)
        QTest.mouseClick(login.submit, Qt.MouseButton.LeftButton)
        self.assertEqual(len(self.client.requests), before)
        login.username.setText("tester")
        login.display_name.setText("Tester")
        login.password.setText("ValidPass@2026")
        login.confirm_password.setText("Mismatch@2026")
        QTest.keyClick(login.confirm_password, Qt.Key.Key_Return)
        self.assertEqual(login.message.text(), "两次输入的密码不一致")
        self.assertEqual(len(self.client.requests), before)
        login.confirm_password.setText("ValidPass@2026")
        QTest.keyClick(login.confirm_password, Qt.Key.Key_Return)
        QTest.keyClick(login.confirm_password, Qt.Key.Key_Return)
        self.assertEqual(len(self.client.requests), before + 1)
        self.assertEqual(self.client.requests[-1][1], "/api/auth/setup")
        self.assertFalse(login.submit.isEnabled())
        self.assertEqual(login.submit.text(), "正在创建…")
        self.client.requests[-1][3]({"ok": True}, None)
        self.assertEqual(self.client.requests[-1][1], "/api/auth/login")
        self.assertEqual(self.client.requests[-1][2]["password"], "ValidPass@2026")
        self.assertEqual(login.submit.text(), "正在验证…")

    def test_reference_strength_and_both_reveals_keep_input_focus(self):
        login = self.login
        for value, score, label in (("", 0, "至少 6 位"), ("abc", 0, "强度：偏弱"),
                                    ("abcdef", 1, "强度：偏弱"), ("abc123", 2, "强度：一般"),
                                    ("abc1234567", 3, "强度：较强"), ("SecretPass@2026", 4, "强度：很强")):
            login.password.setText(value)
            self.assertEqual((login.strength.value(), login.strength_text.text()), (score, label))
        for edit, reveal, label in ((login.password, login.password_reveal, "密码"),
                                    (login.confirm_password, login.confirm_reveal, "确认密码")):
            QTest.mouseClick(reveal, Qt.MouseButton.LeftButton)
            self.assertEqual(edit.echoMode(), QLineEdit.EchoMode.Normal)
            self.assertEqual(reveal.accessibleName(), "隐藏" + label)
            self.assertTrue(edit.hasFocus())
            self.assertEqual(reveal.size().width(), 40)
            QTest.mouseClick(reveal, Qt.MouseButton.LeftButton)
            self.assertEqual(edit.echoMode(), QLineEdit.EchoMode.Password)
            self.assertEqual(reveal.accessibleName(), "显示" + label)

    def test_locks_disabled_accounts_and_error_markup_stay_safe(self):
        login = self.login
        login._on_status({"initialized": True}, None)
        login._on_auth({"remaining_attempts": 3}, "<b>server message</b>")
        self.assertEqual(login.message.textFormat(), Qt.TextFormat.PlainText)
        self.assertEqual(login.message.text(), "<b>server message</b>，还可尝试 3 次")
        login._on_auth({"account_disabled": True}, "disabled")
        self.assertEqual(login.message.text(), "账户已停用，请联系系统管理员。")
        login._on_auth({"locked_seconds": 120}, "locked")
        self.assertFalse(login.submit.isEnabled())
        before = len(self.client.requests)
        login._submit()
        self.assertEqual(len(self.client.requests), before)
        self.assertIn("02:00", login.submit.text())
        login._lock_until = 0
        login._update_lock()
        self.assertTrue(login.submit.isEnabled())
        self.assertFalse(login.lock_timer.isActive())
        self.assertTrue(login.message.property("info"))
        self.assertEqual(login.message.text(), "锁定已解除，可以重新登录。")

    def test_small_setup_scroll_and_long_errors_remain_reachable(self):
        login = self.login
        for initialized in (False, True):
            login._on_status({"initialized": initialized}, None)
            for width, height, theme in ((1080, 760, "light"), (521, 760, "dark"),
                                         (520, 760, "light"), (460, 620, "dark")):
                login.preferences.save(theme=theme)
                login._apply_theme()
                login.resize(width, height)
                self.app.processEvents()
                self.assertEqual(login.shell.width(), 390)
                self.assertEqual(login.password_field.height(), 40)
                self.assertEqual(login.submit.height(), 42)
                self.assertEqual(login.username.width(), 348 if width <= 520 else 340)
                self.assertEqual(login.confirm_field.isVisible(), not initialized)
                login._set_message("server unavailable " * 20)
                self.app.processEvents()
                self.assertGreater(login.message.height(), 17)
                self.assertGreaterEqual(login.submit.y(), login.message.geometry().bottom() + 12)
                login.scroll.ensureWidgetVisible(login.submit)
                self.app.processEvents()
                bottom = login.submit.mapTo(login.scroll.viewport(), login.submit.rect().bottomRight()).y()
                self.assertLess(bottom, login.scroll.viewport().height())
                login._set_message("")
                self.assertEqual(login.message.height(), 17)

    def test_credentials_cleared_and_only_username_is_remembered(self):
        login = self.login
        login._on_status({"initialized": True}, None)
        login.username.setText("remembered")
        login.password.setText("SecretPass@2026")
        login.confirm_password.setText("SecretPass@2026")
        login.password_reveal.setChecked(True)
        login.confirm_reveal.setChecked(True)
        login.remember.setChecked(True)
        accepted = []
        login.authenticated.connect(accepted.append)
        login._on_auth({"user": {"username": "remembered"}}, None)
        self.assertEqual(accepted, [{"username": "remembered"}])
        self.assertEqual(login.password.text(), "")
        self.assertEqual(login.confirm_password.text(), "")
        self.assertFalse(login.password_reveal.isChecked())
        self.assertFalse(login.confirm_reveal.isChecked())
        self.assertEqual(login.password.echoMode(), QLineEdit.EchoMode.Password)
        self.assertNotIn("SecretPass", login.preferences.path.read_text(encoding="utf-8"))
        self.assertEqual(Preferences().values["login_username"], "remembered")
        login.remember.setChecked(False)
        login._on_auth({"user": {"username": "remembered"}}, None)
        self.assertEqual(Preferences().values["login_username"], "")


if __name__ == "__main__":
    unittest.main()
