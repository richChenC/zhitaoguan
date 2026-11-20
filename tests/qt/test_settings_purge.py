"""System-maintenance purge entry: permission gate and double confirmation."""
import unittest
from unittest.mock import patch

import native_test_env  # noqa: F401
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QLineEdit

from qt_shell.native_windows import NativeMainWindow
from test_native_workflows import Client


class SettingsPurgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def tearDown(self):
        for widget in self.app.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def _dialog(self, permissions):
        client = Client()
        window = NativeMainWindow(client, {"username": "admin", "permissions": permissions})
        return window.settings_dialog, client

    def test_purge_panel_hidden_without_permission(self):
        dialog, _ = self._dialog(["data.read", "settings.manage"])
        self.assertTrue(dialog.maintenance_panel.isHidden())

    def test_purge_panel_visible_with_permission(self):
        dialog, _ = self._dialog(["data.read", "settings.manage", "data.purge"])
        self.assertFalse(dialog.maintenance_panel.isHidden())

    def test_purge_aborts_without_exact_phrase(self):
        dialog, client = self._dialog(["settings.manage", "data.purge"])
        before = len(client.requests)
        with patch("qt_shell.native_settings.QInputDialog.getText", return_value=("清空", True)):
            dialog.purge_all()
        self.assertEqual(len(client.requests), before)

    def test_purge_requires_password(self):
        dialog, client = self._dialog(["settings.manage", "data.purge"])
        before = len(client.requests)
        with patch("qt_shell.native_settings.QInputDialog.getText",
                   side_effect=[("恢复出厂", True), ("", True)]):
            dialog.purge_all()
        self.assertEqual(len(client.requests), before)

    def test_purge_posts_confirmed_with_password(self):
        dialog, client = self._dialog(["settings.manage", "data.purge"])
        with patch("qt_shell.native_settings.QInputDialog.getText",
                   side_effect=[("恢复出厂", True), ("secret123", True)]) as prompt:
            dialog.purge_all()
        clears = [row for row in client.requests if row[1] == "/api/clear"]
        self.assertEqual(clears[-1][2], {"confirmed": True, "password": "secret123"})
        self.assertEqual(prompt.call_args_list[-1][0][3], QLineEdit.EchoMode.Password)
        self.assertFalse(dialog.purge_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
