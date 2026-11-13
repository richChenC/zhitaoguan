"""Native navigation dimensions, focus and account label containment."""
from __future__ import annotations

import unittest

import native_test_env  # noqa: F401
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication
from qt_shell.native_components import AccountIdentityButton, NativeNavigationBar, icon, workspace_styles


class NavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        for widget in self.app.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def test_reference_tab_bounds_and_keyboard_selection_remain_stable(self):
        nav = NativeNavigationBar()
        for name, label in zip(nav.icon_names, ("数据工作台", "三维缺陷模型", "数据可视化", "报告中心", "状态处理")):
            nav.addTab(icon(name), label)
        nav.resize(545, 38)
        nav.setStyleSheet(workspace_styles())
        nav.show()
        nav.setFocus()
        QTest.qWait(20)
        expected = [(0, 109), (112, 121), (236, 109), (348, 97), (448, 97)]
        self.assertEqual([(nav.visual_tab_rect(i).x(), nav.visual_tab_rect(i).width())
                          for i in range(5)], expected)
        changed = QSignalSpy(nav.currentChanged)
        for theme in ("light", "dark"):
            nav.set_theme(theme)
            nav.setStyleSheet(workspace_styles(theme))
            for index in range(1, 5):
                QTest.keyClick(nav, Qt.Key.Key_Right)
                self.assertEqual(nav.currentIndex(), index)
                self.assertEqual([(nav.visual_tab_rect(i).x(), nav.visual_tab_rect(i).width())
                                  for i in range(5)], expected)
            for index in range(3, -1, -1):
                QTest.keyClick(nav, Qt.Key.Key_Left)
                self.assertEqual(nav.currentIndex(), index)
        self.assertEqual(changed.count(), 16)
        self.assertEqual(nav.accessibleName(), "主要工作区")

    def test_long_account_name_elides_and_nested_labels_keep_button_click(self):
        clicked = []
        account = AccountIdentityButton({"display_name": "A very long account name for testing",
                                         "username": "test"}, lambda: clicked.append(True))
        account.setStyleSheet(workspace_styles())
        account.show()
        for compact, width, gap in ((False, 154, 9), (True, 135, 7), (False, 154, 9)):
            account.set_compact(compact)
            self.app.processEvents()
            self.assertEqual((account.width(), account.height(), account.layout().spacing()), (width, 34, gap))
            self.assertLessEqual(account.name_label.fontMetrics().horizontalAdvance(account.name_label.text()),
                                 account.name_label.width())
            self.assertTrue(account.name_label.text().endswith("…"))
            QTest.mouseClick(account, Qt.MouseButton.LeftButton, pos=account.avatar.geometry().center())
        self.assertEqual(len(clicked), 3)
        self.assertIn("A very long account name", account.accessibleName())


if __name__ == "__main__":
    unittest.main()
