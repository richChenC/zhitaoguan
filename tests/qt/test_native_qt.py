"""Focused regression tests for the native Qt migration slice."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from qt_shell.native_client import NativeClient  # noqa: E402
from qt_shell.native_windows import FindingsModel, NativeMainWindow  # noqa: E402


class NativeQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_findings_model_has_stable_columns_and_rows(self):
        model = FindingsModel()
        self.assertEqual(model.columnCount(), 9)
        model.replace([{
            "site_code": "N",
            "outage": "N101",
            "unit_id": 1,
            "thimble_id": 7,
            "position": "P2-07",
            "display_conclusion": "NDD",
            "percent": 0,
            "state": "normal",
            "analyst": "tester",
        }])
        self.assertEqual(model.rowCount(), 1)
        self.assertEqual(model.data(model.index(0, 1)), "N101")
        self.assertEqual(model.data(model.index(0, 6)), "0%")

    def test_native_window_builds_without_webengine(self):
        client = NativeClient("http://127.0.0.1:18767")
        window = NativeMainWindow(client, {"username": "tester", "permissions": []})
        self.assertEqual(window.nav.count(), 5)
        self.assertEqual(window.stack.count(), 5)
        self.assertEqual(window.workbench.model.columnCount(), 9)
        window.close()


if __name__ == "__main__":
    unittest.main()
