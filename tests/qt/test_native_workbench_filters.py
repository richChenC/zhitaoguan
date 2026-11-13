"""Filter chips, query boundaries and responsive native workbench controls."""
from __future__ import annotations

import unittest

import native_test_env  # noqa: F401
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qt_shell.native_components import workspace_styles
from qt_shell.native_windows import DataWorkbench
from test_native_workflows import Client


class WorkbenchFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        for widget in self.app.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def page(self, permissions=None):
        page = DataWorkbench(Client(), {"permissions": permissions or ["data.read"]})
        page.resize(1480, 940)
        page.setStyleSheet(workspace_styles())
        page.show()
        page.scope_bar._loaded({"combinations": [
            {"site": "N", "unit_id": 1, "outage": "N101"},
            {"site": "N", "unit_id": 1, "outage": "N102"},
            {"site": "H", "unit_id": 2, "outage": "H201"},
        ]}, None)
        self.respond(page)
        self.app.processEvents()
        return page

    def queries(self, page):
        return [row for row in page.client.requests if row[1].startswith("/api/findings?")]

    def respond(self, page):
        self.queries(page)[-1][3]({"page": 1, "pages": 5, "total": 4517, "items": [
            {"id": 7, "outage": "N101", "unit_id": 1, "thimble_id": 6, "position": "B2",
             "indication": "WAR", "percent": 10}], "core_items": []}, None)

    def test_seven_chips_match_reference_and_clear_one_or_all_once(self):
        page = self.page()
        self.assertEqual(page.summary.text(), "未设置筛选条件，当前显示全部检测记录")
        self.assertFalse(page.reset_filters.isEnabled())
        page.scope_bar.set_scope({"site": "N", "unit": "1", "outage": "N101"})
        page.detection_status.setCurrentIndex(page.detection_status.findData("war"))
        page.maintenance_status.setCurrentIndex(page.maintenance_status.findData("plugged"))
        page.analyst.setText("张三")
        page.channel.setText("6")
        page.apply_filters()
        self.respond(page)
        texts = [text for _, text in page.filter_summary.entries]
        self.assertEqual(texts, ["基地：宁德（N）", "机组：1 号", "大修批次：N101", "检测结论：WAR",
                                 "维护状态：堵管", "分析人员：张三", "通道编号：#6"])
        self.assertEqual(page.summary.text(), "已设置 7 项筛选条件")
        count = len(self.queries(page))
        QTest.mouseClick(page.filter_summary.chips["detection_status"].remove_button, Qt.MouseButton.LeftButton)
        self.assertEqual(len(self.queries(page)), count + 1)
        self.assertNotIn("detection_status=", self.queries(page)[-1][1])
        self.assertIn("maintenance_status=plugged", self.queries(page)[-1][1])
        self.assertEqual(len(page.filter_summary.entries), 6)
        count = len(self.queries(page))
        page.reset_query()
        self.assertEqual(len(self.queries(page)), count + 1)
        self.respond(page)
        self.assertFalse(page.filter_summary.chips)
        self.assertFalse(page.reset_filters.isEnabled())
        self.assertEqual(page.summary.text(), "未设置筛选条件，当前显示全部检测记录")

    def test_clearing_scope_retains_independent_text_and_column_filters(self):
        page = self.page()
        page.scope_bar.set_scope({"site": "N", "unit": "1", "outage": "N101"})
        page.analyst.setText("<b>张三</b>")
        page.channel.setText("6")
        page.column_filters["analysis"] = "原文"
        page.apply_filters()
        for key in ("site", "unit", "outage"):
            count = len(self.queries(page))
            page.clear_filter(key)
            self.assertEqual(len(self.queries(page)), count + 1)
            self.assertEqual(page.analyst.text(), "<b>张三</b>")
            self.assertEqual(page.channel.text(), "6")
        self.respond(page)
        chip = page.filter_summary.chips["analyst"]
        self.assertEqual(chip.label.textFormat(), Qt.TextFormat.PlainText)
        self.assertIn("<b>张三</b>", chip.remove_button.accessibleName())
        page.clear_filter("column:analysis")
        self.assertNotIn("column_analysis=", self.queries(page)[-1][1])
        self.assertEqual(page.column_filters, {})

    def test_user_typing_debounces_enter_and_escape_cancel_pending_query(self):
        page = self.page()
        count = len(self.queries(page))
        QTest.keyClicks(page.analyst, "abc")
        self.assertEqual(len(self.queries(page)), count)
        QTest.qWait(390)
        self.assertEqual(len(self.queries(page)), count + 1)
        self.assertIn("analyst=abc", self.queries(page)[-1][1])
        QTest.keyClicks(page.analyst, "def")
        QTest.keyClick(page.analyst, Qt.Key.Key_Return)
        self.assertEqual(len(self.queries(page)), count + 2)
        QTest.qWait(390)
        self.assertEqual(len(self.queries(page)), count + 2)
        QTest.keyClick(page.analyst, Qt.Key.Key_Escape)
        self.assertEqual(page.analyst.text(), "")
        self.assertEqual(len(self.queries(page)), count + 3)
        page.channel.setText("51")
        page.apply_filters()
        self.assertEqual(len(self.queries(page)), count + 3)
        self.assertIn("1-50", page.status.text())

    def test_only_latest_result_releases_loading_and_permissions_stay_enforced(self):
        page = self.page()
        page.model.selected[7] = page.model.rows[0]
        page._selection_changed()
        self.assertFalse(page.delete.isEnabled())
        page.apply_filters()
        first = self.queries(page)[-1][3]
        page.apply_filters()
        second = self.queries(page)[-1][3]
        self.assertFalse(page.select_page_button.isEnabled())
        self.assertFalse(page.prev.isEnabled())
        self.assertFalse(page.next.isEnabled())
        self.assertEqual(page.summary.text(), "正在筛选…")
        first({"page": 1, "items": []}, None)
        self.assertTrue(page._filter_busy)
        second(None, "test failure")
        self.assertFalse(page._filter_busy)
        self.assertEqual(page.status.text(), "test failure")
        self.assertFalse(page.delete.isEnabled())
        self.assertFalse(page.select_page_button.isEnabled())
        page.apply_filters()
        self.respond(page)
        self.assertTrue(page.select_page_button.isEnabled())
        self.assertTrue(page.clear_selection_button.isEnabled())
        self.assertTrue(page.next.isEnabled())
        self.assertFalse(page.delete.isEnabled())

    def test_grid_and_long_plain_text_chip_fit_without_horizontal_overflow(self):
        page = self.page()
        page.analyst.setText("<b>" + "Long analyst " * 30 + "</b>")
        for width, theme, columns in ((1480, "light", 9), (1024, "dark", 6), (980, "light", 6)):
            page.setStyleSheet(workspace_styles(theme))
            page.resize(width, 940)
            QTest.qWait(40)
            self.assertEqual(page._filter_columns, columns)
            self.assertEqual(page.scroll.horizontalScrollBar().maximum(), 0)
            self.assertLessEqual(page.reset_filters.mapTo(page, page.reset_filters.rect().topRight()).x(), width - 18)
            chip = page.filter_summary.chips["analyst"]
            self.assertLessEqual(chip.width(), 300)
            self.assertLessEqual(chip.label.fontMetrics().horizontalAdvance(chip.label.text()), chip.label.width())
            self.assertEqual(page.filter_fields[0].height(), 56)
            self.assertEqual(page.search.height(), 34)
            self.assertEqual(page.reset_filters.height(), 34)
            self.assertEqual(page.refresh_button.size().toTuple(), (30, 30))
            self.assertEqual(page.import_button.height(), 34)
            self.assertEqual(page.ledger.height(), 30)
            if width == 1480:
                self.assertEqual(page.filter_fields[-1].mapTo(page, page.filter_fields[-1].rect().topLeft()).y(),
                                 page.filter_fields[0].mapTo(page, page.filter_fields[0].rect().topLeft()).y())
            else:
                self.assertGreater(page.filter_fields[-1].mapTo(page, page.filter_fields[-1].rect().topLeft()).y(),
                                   page.filter_fields[0].mapTo(page, page.filter_fields[0].rect().topLeft()).y())


if __name__ == "__main__":
    unittest.main()
