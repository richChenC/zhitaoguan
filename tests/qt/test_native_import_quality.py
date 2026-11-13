"""Audit scope, concurrency, recovery, source history and retryable native export."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import native_test_env
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from qt_shell.native_import_quality import ImportQualityPanel, quality_styles
from test_native_workflows import Client


PERMISSIONS = ("data.read", "data.delete", "review.write", "export.create")


def quality(status="completed", **changes):
    result = {
        "batches": [{"id": 1, "status": status, "rows_parsed": 100, "source_path": "a/b.xlsx"}],
        "batch_total": 1, "issues": [{"batch_id": 1, "code": "MAPPING_ERROR", "severity": "error",
                                   "message": "<b>raw & source</b>", "row_number": 0}],
        "artifacts": [{"batch_id": 1, "path": "a.xlsx", "sha256": "abcd", "parse_status": "parsed"}],
        "versions": [{"batch_id": 1, "outage": "N101", "filename": "v.rpt", "batch_selected": True}],
        "totals": {"issues": 101, "artifacts": 1, "versions": 1}, "legacy_rows": 2,
    }
    result.update(changes)
    return result


def reviews(revision="first", history=None):
    return {"items": [{"group_key": "group-one", "revision": revision, "outage": "N101", "thimble_id": 1,
                       "analyst": "<raw>", "status": "pending", "representative_id": None,
                       "members": [{"id": 10, "calgroup": "CAL1", "percent": 0},
                                   {"id": 20, "calgroup": "CAL2", "percent": 0}],
                       "history": history or []}], "pending": 1}


class ImportQualityTests(unittest.TestCase):
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

    def panel(self, permissions=PERMISSIONS):
        client = Client()
        panel = ImportQualityPanel(client, permissions)
        panel.resize(855, 800)
        panel.setStyleSheet(quality_styles())
        panel.show()
        self.app.processEvents()
        return panel, client

    def answer(self, client, result=None, error=None):
        client.requests[-1][3](result, error)
        self.app.processEvents()

    def select_batch(self, panel, client, status="completed"):
        self.answer(client, quality(status))
        panel.batch.setCurrentIndex(1)
        self.answer(client, quality(status))

    def show_reviews(self, panel, client, data=None):
        self.answer(client, quality())
        panel.tabs.button(4).click()
        self.answer(client, quality())
        self.answer(client, data or reviews())

    def test_read_stale_error_and_direct_write_protection(self):
        panel, client = self.panel()
        first = client.requests[-1]
        panel.refresh()
        fresh = client.requests[-1]
        first[3](quality("rolled_back"), None)
        self.assertFalse(panel.fresh)
        fresh[3](quality(), None)
        self.assertTrue(panel.fresh)
        self.select_batch(panel, client)
        self.assertTrue(panel.rollback.isEnabled())
        panel.refresh()
        self.assertFalse(panel.rollback.isEnabled())
        self.answer(client, error="<b>offline</b>")
        self.assertFalse(panel.fresh)
        self.assertEqual(panel.status.textFormat(), Qt.TextFormat.PlainText)
        before = len(client.requests)
        panel.batch_action("restore")
        panel.batch_action("rollback")
        self.assertEqual(len(client.requests), before)
        self.assertIn("请点击刷新", panel.status.text())

    def test_tabs_paging_scope_and_complete_tooltips(self):
        panel, client = self.panel()
        self.answer(client, quality())
        self.assertEqual(panel.table.item(0, 3).text(), "<b>raw & source</b>")
        self.assertEqual(panel.table.item(0, 6).text(), "0")
        panel.category.setCurrentIndex(panel.category.findData("MAPPING_ERROR"))
        self.answer(client, quality())
        panel.change_page(1)
        query = parse_qs(urlsplit(client.requests[-1][1]).query)
        self.assertEqual(query["page"], ["2"])
        self.assertEqual(query["category"], ["MAPPING_ERROR"])
        self.answer(client, quality())
        for index, column, expected in ((1, 5, "已完成"), (2, 5, "已解析"), (3, 5, "本批次选用")):
            panel.tabs.button(index).click()
            self.answer(client, quality())
            self.assertEqual(panel.page, 1)
            self.assertFalse(panel.category.isEnabled())
            self.assertEqual(panel.table.item(0, column).text(), expected)
        panel.tabs.button(0).click()
        self.answer(client, quality())
        self.assertEqual(panel.category.currentData(), "MAPPING_ERROR")
        self.assertTrue(panel.category.isEnabled())

    def test_last_page_clamps_and_batches_are_limited_without_false_paging(self):
        panel, client = self.panel()
        self.answer(client, quality())
        panel.change_page(1)
        self.answer(client, quality(totals={"issues": 1, "artifacts": 0, "versions": 0}))
        self.assertIn("page=1", client.requests[-1][1])
        self.answer(client, quality(totals={"issues": 1, "artifacts": 0, "versions": 0}))
        self.assertEqual(panel.page, 1)
        panel.tabs.button(1).click()
        self.answer(client, quality(batch_total=250))
        self.assertIn("最近 200", panel.page_label.text())
        self.assertFalse(panel.next.isEnabled())

    def test_restore_success_then_refresh_failure_is_not_reported_as_write_failure(self):
        panel, client = self.panel()
        self.select_batch(panel, client, "rolled_back")
        changed = []
        panel.changed.connect(lambda: changed.append(True))
        panel.batch_action("restore")
        write = client.requests[-1]
        panel.batch_action("restore")
        panel.refresh()
        self.assertIs(client.requests[-1], write)
        self.assertFalse(panel.batch.isEnabled())
        write[3]({"ok": True, "changed": 100}, None)
        self.assertEqual(changed, [True])
        self.answer(client, error="refresh offline")
        self.assertIn("已恢复", panel.status.text())
        self.assertIn("无需重复操作", panel.status.text())
        self.assertFalse(panel.restore.isEnabled())
        self.assertFalse(panel.busy)

    def test_rollback_cancel_and_confirmation_payload(self):
        panel, client = self.panel()
        self.select_batch(panel, client)
        before = len(client.requests)
        with patch.object(QMessageBox, "exec"), patch.object(QMessageBox, "clickedButton", return_value=None):
            panel.batch_action("rollback")
        self.assertEqual(len(client.requests), before)
        def confirm(box):
            accept = next(b for b in box.buttons() if b.text() == "确认回滚")
            box._accepted_test_button = accept
        with patch.object(QMessageBox, "exec", confirm), patch.object(
                QMessageBox, "clickedButton", lambda box: box._accepted_test_button):
            panel.batch_action("rollback")
        self.assertEqual(client.requests[-1][2], {"batch_id": 1, "action": "rollback"})
        self.answer(client, {"ok": True, "changed": 100})
        self.answer(client, quality("rolled_back"))
        self.assertIn("已回滚", panel.status.text())
        self.assertTrue(panel.restore.isEnabled())

    def test_review_requires_selection_and_revision_and_keeps_source_history(self):
        panel, client = self.panel()
        self.show_reviews(panel, client)
        widget = panel.review_widgets[0]
        before = len(client.requests)
        panel.save_review(widget, "representative")
        self.assertEqual(len(client.requests), before)
        QTest.mouseClick(widget.radios.button(20), Qt.MouseButton.LeftButton)
        self.assertEqual(widget.radios.checkedId(), 20)
        widget.reason.setText("<依据>")
        panel.save_review(widget, "representative")
        payload = client.requests[-1][2]
        self.assertEqual(payload, {"group_key": "group-one", "revision": "first", "action": "representative",
                                   "representative_id": 20, "reason": "<依据>"})
        panel.save_review(widget, "keep_all")
        self.assertEqual(client.requests[-1][2], payload)
        self.answer(client, {"ok": True})
        self.answer(client, quality())
        history = [{"created_at": "2026-11-13T10:00:00", "operator": "<reviewer>",
                    "action": "representative", "representative_id": 20, "reason": "<依据>", "active": 1}]
        self.answer(client, reviews("second", history))
        widget = panel.review_widgets[0]
        self.assertEqual(widget.table.rowCount(), 2)
        self.assertEqual(widget.history.item(0, 4).text(), "<依据>")
        self.assertTrue(widget.actions["reset"].isEnabled())
        widget.history_toggle.click()
        self.assertTrue(widget.history.isVisible())
        panel.set_theme("dark")
        self.assertEqual(widget.history_toggle.property("iconName"), "chevron-down")
        self.assertIn("复核已保存", panel.status.text())

    def test_review_failed_refresh_keeps_saved_status_and_forbids_duplicate_save(self):
        panel, client = self.panel()
        self.show_reviews(panel, client)
        widget = panel.review_widgets[0]
        panel.save_review(widget, "keep_all")
        self.answer(client, {"ok": True})
        self.answer(client, error="offline")
        self.assertIn("复核已保存", panel.status.text())
        self.assertIn("无需重复", panel.status.text())
        before = len(client.requests)
        panel.save_review(widget, "keep_all")
        self.assertEqual(len(client.requests), before)
        self.assertFalse(widget.actions["keep_all"].isEnabled())

    def test_review_draft_survives_same_revision_and_conflict_loads_new_revision(self):
        panel, client = self.panel()
        self.show_reviews(panel, client)
        widget = panel.review_widgets[0]
        widget.reason.setText("draft")
        widget.radios.button(10).click()
        panel.refresh()
        self.answer(client, quality())
        self.answer(client, reviews())
        widget = panel.review_widgets[0]
        self.assertEqual(widget.reason.text(), "draft")
        self.assertEqual(widget.radios.checkedId(), 10)
        panel.save_review(widget, "representative")
        self.answer(client, error="来源已变化")
        self.answer(client, quality())
        self.answer(client, reviews("updated"))
        self.assertEqual(panel.review_widgets[0].group["revision"], "updated")
        self.assertIn("来源已变化", panel.status.text())
        self.assertTrue(panel.fresh)

    def test_export_cancel_failure_retry_does_not_regenerate(self):
        panel, client = self.panel()
        self.answer(client, quality())
        source = Path(native_test_env.test_data.name) / "audit.xlsx"
        source.write_bytes(b"test export")
        panel.export_quality()
        write = client.requests[-1]
        panel.export_quality()
        self.assertIs(write, client.requests[-1])
        with patch("qt_shell.native_import_quality.QFileDialog.getSaveFileName", return_value=("", "")):
            self.answer(client, {"file_path": str(source), "filename": "audit.xlsx", "finding_rows": 4517, "rows": 7})
        self.assertIn("已取消保存", panel.status.text())
        before = len(client.requests)
        with patch("qt_shell.native_import_quality.QFileDialog.getSaveFileName", return_value=(
                str(source.parent / "missing-dir/audit.xlsx"), "")):
            panel.save_export()
        self.assertIn("保存失败", panel.status.text())
        target = source.parent / "saved-audit.xlsx"
        with patch("qt_shell.native_import_quality.QFileDialog.getSaveFileName", return_value=(str(target), "")):
            panel.retry.click()
        self.assertEqual(target.read_bytes(), source.read_bytes())
        self.assertEqual(len(client.requests), before)
        self.assertIn("4517", panel.status.text())
        self.assertTrue(panel.export.isEnabled())

    def test_readonly_rejects_direct_mutations_and_export(self):
        panel, client = self.panel(("data.read",))
        self.select_batch(panel, client)
        before = len(client.requests)
        panel.batch_action("rollback")
        panel.export_quality()
        self.assertEqual(len(client.requests), before)
        self.assertFalse(panel.export.isEnabled())
        self.assertFalse(panel.rollback.isEnabled())
        panel.tabs.button(4).click()
        self.answer(client, quality())
        self.answer(client, reviews())
        widget = panel.review_widgets[0]
        panel.save_review(widget, "keep_all")
        self.assertEqual(client.requests[-1][0], "GET")
        self.assertFalse(widget.reason.isEnabled())

    def test_responsive_toolbar_and_large_review_paging_remain_reachable(self):
        panel, client = self.panel()
        self.answer(client, quality())
        for width in (855, 675, 649, 569):
            panel.resize(width, 1000)
            QTest.qWait(20)
            for control in (panel.batch, panel.category, panel.export, panel.restore):
                point = control.mapTo(panel.toolbar, control.rect().topLeft())
                self.assertGreaterEqual(point.x(), 0)
                self.assertLessEqual(point.x() + control.width(), panel.toolbar.width())
                self.assertGreater(control.height(), 0)
        groups = []
        for index in range(23):
            group = copy.deepcopy(reviews()["items"][0])
            group["group_key"] = str(index)
            groups.append(group)
        panel.tabs.button(4).click()
        self.answer(client, quality())
        self.answer(client, {"items": groups, "pending": 23})
        self.assertEqual(len(panel.review_widgets), 10)
        self.assertEqual(panel.pages(), 3)
        panel.change_page(1)
        self.answer(client, quality())
        self.answer(client, {"items": groups, "pending": 23})
        self.assertEqual(panel.page, 2)
        self.assertEqual(len(panel.review_widgets), 10)


if __name__ == "__main__":
    unittest.main()
