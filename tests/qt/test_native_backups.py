"""Backup controls, write protection and staged native recovery."""
import unittest
from unittest.mock import patch

import native_test_env
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from qt_shell.native_backups import BackupWorkspace, RestoreDialog, backup_styles
from test_native_workflows import Client


ITEM = {"name": "backup.db", "path": "isolated/backup.db", "size_bytes": 1024,
        "created_at": "2026-11-13T12:00:00Z", "sha256": "abc" * 21,
        "kind_label": "手动备份", "note": "<备份原文>"}
LIST = {"dir": "isolated/backups", "items": [ITEM], "db_size_bytes": 10240,
        "current": {"findings": 4517, "outages": 66}}
CHECKED = {"integrity": "ok", "findings": 4517, "hash_verified": True, "sha256": ITEM["sha256"]}


class BackupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def tearDown(self):
        for widget in self.app.topLevelWidgets():
            if isinstance(widget, RestoreDialog):
                widget.restoring = False
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def panel(self, permissions=("backup.manage", "database.restore")):
        client = Client()
        panel = BackupWorkspace(client, {"permissions": permissions})
        panel.resize(855, 500)
        panel.setStyleSheet(backup_styles())
        panel.show()
        self.app.processEvents()
        return panel, client

    def answer(self, client, path, data=None, error=None):
        request = next(r for r in reversed(client.requests) if r[1] == path)
        request[3](data, error)
        self.app.processEvents()

    def ready(self, panel, client):
        self.answer(client, "/api/backups", LIST)
        self.answer(client, "/api/backup-policy", {"automatic_keep": 20})

    def dialog(self):
        client = Client()
        dialog = RestoreDialog(client, ITEM["path"])
        dialog.show()
        dialog.begin()
        self.answer(client, "/api/backups", LIST)
        return dialog, client

    def test_readonly_controls_and_direct_methods_do_not_request(self):
        panel, client = self.panel(("data.read",))
        panel.create()
        panel.load()
        panel.open_restore(ITEM["path"])
        panel.select_external()
        panel.save_policy_value()
        self.assertEqual(client.requests, [])
        self.assertFalse(panel.now.isEnabled())
        self.assertFalse(panel.external.isEnabled())

    def test_list_failure_disables_existing_rows_and_direct_restore(self):
        panel, client = self.panel()
        self.ready(panel, client)
        self.assertTrue(panel.row_widgets[0].restore.isEnabled())
        panel.load()
        self.answer(client, "/api/backups", error="<无法读取>")
        self.assertFalse(panel.row_widgets[0].restore.isEnabled())
        self.assertIn("<无法读取>", panel.status.text())
        before = len(client.requests)
        panel.open_restore(ITEM["path"])
        self.assertEqual(before, len(client.requests))
        self.assertEqual(panel.row_widgets[0].note.textFormat(), Qt.TextFormat.PlainText)

    def test_row_restores_its_own_path_and_revalidates_registry(self):
        panel, client = self.panel()
        other = {**ITEM, "name": "other.db", "path": "isolated/other.db"}
        self.answer(client, "/api/backups", {**LIST, "items": [other, ITEM]})
        QTest.mouseClick(panel.row_widgets[1].restore, Qt.MouseButton.LeftButton)
        dialog = panel.dialog
        self.assertEqual(dialog.path, ITEM["path"])
        self.assertFalse(dialog.confirm.isEnabled())
        self.answer(client, "/api/backups", LIST)
        self.assertEqual(client.requests[-1][2], {"path": ITEM["path"]})
        self.answer(client, "/api/backup-validate", CHECKED)
        self.assertFalse(dialog.confirm.isEnabled())
        dialog.ack.setChecked(True)
        self.assertTrue(dialog.confirm.isEnabled())

    def test_removed_backup_does_not_validate(self):
        dialog, client = self.dialog()
        dialog.reject()
        other = RestoreDialog(client, ITEM["path"])
        other.show()
        other.begin()
        self.answer(client, "/api/backups", {**LIST, "items": []})
        self.assertIn("已不存在", other.message.text())
        self.assertFalse(other.confirm.isEnabled())
        self.assertEqual(client.requests[-1][1], "/api/backups")

    def test_cancel_ignores_late_validation_and_does_not_restore(self):
        dialog, client = self.dialog()
        callback = client.requests[-1][3]
        dialog.reject()
        callback(CHECKED, None)
        dialog.ack.setChecked(True)
        dialog.restore()
        self.assertFalse(dialog.validated)
        self.assertFalse(any(r[1] == "/api/restore" for r in client.requests))

    def test_invalid_validation_and_hash_failure_do_not_enable_ack(self):
        for data, error in (({**CHECKED, "integrity": "bad"}, None),
                            ({**CHECKED, "findings": True}, None),
                            (None, "SHA-256校验失败")):
            dialog, client = self.dialog()
            self.answer(client, "/api/backup-validate", data, error)
            self.assertFalse(dialog.ack.isEnabled())
            dialog.ack.setChecked(True)
            dialog.restore()
            self.assertFalse(any(r[1] == "/api/restore" for r in client.requests))
            dialog.reject()

    def test_restore_pending_cannot_repeat_or_close_then_requires_relogin(self):
        dialog, client = self.dialog()
        completed = []
        dialog.restored.connect(completed.append)
        self.answer(client, "/api/backup-validate", CHECKED)
        dialog.ack.setChecked(True)
        dialog.restore()
        dialog.restore()
        dialog.reject()
        dialog.close()
        self.assertTrue(dialog.isVisible())
        self.assertFalse(dialog.cancel.isEnabled())
        self.assertEqual(len([r for r in client.requests if r[1] == "/api/restore"]), 1)
        self.answer(client, "/api/restore", {"safety_backup": "safety.db", "login_required": True})
        self.assertEqual(len(completed), 1)
        self.assertFalse(dialog.isVisible())

    def test_restore_failure_stays_open_and_shows_service_error(self):
        dialog, client = self.dialog()
        self.answer(client, "/api/backup-validate", CHECKED)
        dialog.ack.setChecked(True)
        dialog.restore()
        self.answer(client, "/api/restore", error="备份在校验后发生变化")
        self.assertTrue(dialog.isVisible())
        self.assertIn("发生变化", dialog.message.text())
        self.assertTrue(dialog.cancel.isEnabled())

    def test_ack_label_click_and_parent_close_are_guarded_during_restore(self):
        from qt_shell.native_windows import NativeMainWindow
        client = Client()
        window = NativeMainWindow(client, {"username": "admin",
                                  "permissions": ["data.read", "backup.manage", "database.restore"]})
        window.show()
        window.open_settings(5)
        panel = window.settings_page.backups
        self.answer(client, "/api/backups", LIST)
        panel.open_restore(ITEM["path"])
        self.answer(client, "/api/backups", LIST)
        self.answer(client, "/api/backup-validate", CHECKED)
        dialog = panel.dialog
        QTest.mouseClick(dialog.ack_text, Qt.MouseButton.LeftButton)
        self.assertTrue(dialog.ack.isChecked())
        dialog.restore()
        window.settings_dialog.close()
        window.close()
        self.assertTrue(window.isVisible())
        self.assertTrue(window.settings_dialog.isVisible())
        self.assertTrue(dialog.isVisible())
        self.answer(client, "/api/restore", error="恢复取消，原库保留")
        dialog.reject()
        window.close()
        self.assertFalse(window.isVisible())

    def test_restore_completion_does_not_refresh_consumers_with_revoked_session(self):
        from qt_shell.native_windows import NativeMainWindow
        window = NativeMainWindow(Client(), {"username": "admin", "permissions": ["data.read"]})
        window._data_refresh.stop()
        window._request_finished("/api/restore", {"login_required": True, "safety_backup": "safe.db"}, "")
        self.assertFalse(window._data_refresh.isActive())

    def test_directory_cancel_and_duplicate_backup_submission(self):
        panel, client = self.panel()
        self.ready(panel, client)
        before = len(client.requests)
        with patch("qt_shell.native_backups.QFileDialog.getExistingDirectory", return_value=""):
            panel.create(True)
        self.assertEqual(before, len(client.requests))
        with patch("qt_shell.native_backups.QFileDialog.getExistingDirectory", return_value="isolated/export"):
            panel.create(True)
        panel.create()
        self.assertEqual(len(client.requests), before + 1)
        self.assertEqual(client.requests[-1][2]["target"], "isolated/export")
        self.answer(client, "/api/backup", error="磁盘空间不足")
        self.assertTrue(panel.now.isEnabled())
        self.assertIn("磁盘空间不足", panel.status.text())

    def test_backup_saved_but_list_failure_is_not_reported_as_write_failure(self):
        panel, client = self.panel()
        self.ready(panel, client)
        panel.create()
        self.answer(client, "/api/backup", {"path": "isolated/saved.db"})
        self.answer(client, "/api/backups", error="读取失败")
        self.assertIn("备份已创建", panel.status.text())
        self.assertIn("无需重复备份", panel.status.text())
        self.assertFalse(panel.external.isEnabled())

    def test_prewrite_list_response_cannot_replace_saved_result(self):
        panel, client = self.panel()
        stale = next(r for r in client.requests if r[1] == "/api/backups")[3]
        panel.create()
        self.answer(client, "/api/backup", {"path": ITEM["path"]})
        self.answer(client, "/api/backups", LIST)
        stale({**LIST, "items": []}, None)
        self.assertEqual(panel.rows, [ITEM])

    def test_policy_failure_keeps_draft_and_failed_initial_read_blocks_save(self):
        panel, client = self.panel()
        self.answer(client, "/api/backup-policy", error="策略不可用")
        before = len(client.requests)
        panel.save_policy_value()
        self.assertEqual(len(client.requests), before)
        panel.load_policy()
        self.answer(client, "/api/backup-policy", {"automatic_keep": 20})
        panel.keep.setValue(35)
        panel.save_policy_value()
        panel.save_policy_value()
        self.assertEqual(client.requests[-1][2], {"automatic_keep": 35})
        self.answer(client, "/api/backup-policy", error="保存失败")
        self.assertEqual(panel.keep.value(), 35)
        self.assertTrue(panel.save_policy.isEnabled())

    def test_narrow_restore_scroll_and_footer_remain_reachable(self):
        dialog, client = self.dialog()
        self.answer(client, "/api/backup-validate", CHECKED)
        dialog.resize(340, 300)
        self.app.processEvents()
        self.assertGreater(dialog.scroll.verticalScrollBar().maximum(), 0)
        self.assertLessEqual(dialog.footer.geometry().bottom(), dialog.height())
        for row, key, value in dialog.compare_rows:
            self.assertGreaterEqual(value.y(), key.geometry().bottom())
            self.assertLessEqual(value.geometry().right(), row.width())


if __name__ == "__main__":
    unittest.main()
