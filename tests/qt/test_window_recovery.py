import os
import sys
import unittest
import uuid
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QProcess, QTimer
from PySide6.QtWidgets import QApplication

from qt_shell import single_instance
from qt_shell.windows import Shell


class WindowRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_existing_instance_receives_wake_request(self):
        name = "thimble-test-" + uuid.uuid4().hex
        with patch.object(single_instance, "server_name", return_value=name):
            server = single_instance.InstanceWakeServer()
            self.assertTrue(server.listen(), server.server.errorString())
            loop = QEventLoop()
            received = []
            server.wake_requested.connect(
                lambda: (received.append(True), QTimer.singleShot(100, loop.quit))
            )
            worker = QProcess()
            worker.start(sys.executable, [
                "-c",
                "from qt_shell import single_instance as s; "
                f"s.server_name=lambda: {name!r}; "
                "raise SystemExit(0 if s.wake_existing(3000) else 1)",
            ])
            self.assertTrue(worker.waitForStarted(5000))
            QTimer.singleShot(5000, loop.quit)
            loop.exec()
            if worker.state() != QProcess.ProcessState.NotRunning:
                self.assertTrue(worker.waitForFinished(5000))
            server.server.close()
            self.assertEqual(worker.exitCode(), 0, bytes(worker.readAllStandardError()))
            self.assertEqual(received, [True])

    def test_missing_wake_server_is_reported(self):
        with patch.object(single_instance, "server_name", return_value="thimble-test-" + uuid.uuid4().hex):
            self.assertFalse(single_instance.wake_existing(50))

    def test_existing_instance_startup_is_retried(self):
        with patch.object(
            single_instance,
            "wake_existing",
            side_effect=[False, False, True],
        ) as wake:
            with patch.object(single_instance.time, "sleep"):
                self.assertTrue(
                    single_instance.wake_existing_until_ready(
                        total_timeout_ms=100,
                        attempt_timeout_ms=5,
                        retry_delay_ms=1,
                    )
                )
        self.assertEqual(wake.call_count, 3)

    def test_minimized_window_is_restored_and_activated(self):
        shell = Shell.__new__(Shell)
        shell.main_window = Mock()
        shell.main_window.isMinimized.return_value = True
        shell.restore_main()
        shell.main_window.showNormal.assert_called_once()
        shell.main_window.raise_.assert_called_once()
        shell.main_window.activateWindow.assert_called_once()

    def test_tray_exit_uses_normal_close_guard(self):
        shell = Shell.__new__(Shell)
        shell.main_window = Mock()
        shell._close_from_tray()
        shell.main_window.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
