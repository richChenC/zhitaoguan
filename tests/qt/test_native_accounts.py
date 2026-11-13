"""Account drafts, permissions, asynchronous refresh and actual native controls."""
import copy
import unittest
from unittest.mock import patch

import native_test_env
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from qt_shell.native_accounts import AccountSecurityDialog, AccountWorkspace, account_styles
from test_native_workflows import Client


ROLES = [
    {"code": "admin", "label": "系统管理员", "permissions": ["data.read", "users.manage"]},
    {"code": "editor", "label": "数据编辑员", "permissions": ["data.read", "data.edit", "state.write"]},
    {"code": "viewer", "label": "只读用户", "permissions": ["data.read"]},
]
USERS = [
    {"id": "admin-id", "username": "admin", "display_name": "管理员", "active": 1, "roles": ["admin"]},
    {"id": "viewer-id", "username": "reader", "display_name": "<原始姓名>", "active": 1, "roles": ["viewer"]},
]


class AccountTests(unittest.TestCase):
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

    def panel(self, allowed=True):
        client = Client()
        user = {**USERS[0], "permissions": ["users.manage", "data.read"] if allowed else ["data.read"]}
        panel = AccountWorkspace(client, user)
        panel.setStyleSheet(account_styles())
        panel.resize(855, 1600)
        panel.show()
        self.app.processEvents()
        return panel, client

    def answer(self, client, data=None, error=None):
        client.requests[-1][3](data or {"users": copy.deepcopy(USERS), "roles": copy.deepcopy(ROLES)}, error)
        self.app.processEvents()

    def fill_new(self, panel):
        for field, value in ((panel.username, "newviewer"), (panel.display_name, "新账户"),
                             (panel.password, "Secret@2026"), (panel.confirm_password, "Secret@2026")):
            field.setText(value)
        panel._edited()

    def test_readonly_does_not_request_or_allow_direct_save(self):
        panel, client = self.panel(False)
        self.assertTrue(panel.admin.isHidden())
        self.assertEqual(client.requests, [])
        self.fill_new(panel)
        panel.save()
        panel.load()
        self.assertEqual(client.requests, [])
        self.assertFalse(panel.current_permissions.isHidden())
        self.assertEqual(panel.current_permissions.values, ["查询数据"])

    def test_directory_filter_and_role_union_are_real_values(self):
        panel, client = self.panel()
        self.answer(client)
        self.assertEqual(len(panel.roster_rows), 2)
        self.assertTrue(panel.role_choices["viewer"].isChecked())
        panel.role_choices["editor"].setChecked(True)
        self.assertEqual(set(panel.preview_chips.values), {"查询数据", "编辑检测记录", "维护管状态"})
        panel.search.setText("viewer")
        self.assertEqual([r.user["id"] for r in panel.roster_rows], ["viewer-id"])
        panel.search.setText("原始姓名")
        with patch.object(panel, "_confirm_discard", return_value=True):
            QTest.mouseClick(panel.roster_rows[0], Qt.MouseButton.LeftButton)
        self.assertEqual(panel.selected_id, "viewer-id")

    def test_switch_and_refresh_require_discard_while_background_keeps_draft(self):
        panel, client = self.panel()
        self.answer(client)
        self.fill_new(panel)
        before = len(client.requests)
        with patch.object(panel, "_confirm_discard", return_value=False):
            panel.choose_user("viewer-id")
            panel.start_new()
            panel.load(preserve_draft=False)
        self.assertEqual(len(client.requests), before)
        self.assertIsNone(panel.selected_id)
        panel.load()
        self.answer(client)
        self.assertEqual(panel.display_name.text(), "新账户")
        self.assertEqual(panel.password.text(), "Secret@2026")
        self.assertTrue(panel.dirty())
        self.assertIn("仍保留", panel.status.text())
        with patch.object(panel, "_confirm_discard", return_value=True):
            panel.choose_user("viewer-id")
        self.assertEqual(panel.selected_id, "viewer-id")
        self.assertTrue(panel.username.isReadOnly())
        self.assertEqual(panel.password.text(), "")
        self.assertEqual(panel.display_name.text(), "<原始姓名>")
        self.assertEqual(panel.roster_rows[-1].name.textFormat(), Qt.TextFormat.PlainText)

    def test_read_order_failure_and_direct_save_gate(self):
        panel, client = self.panel()
        first = client.requests[-1]
        panel.load()
        second = client.requests[-1]
        first[3]({"users": USERS, "roles": ROLES}, None)
        self.assertTrue(panel.reading)
        second[3](None, "<offline>")
        self.assertFalse(panel.fresh)
        self.assertFalse(panel.editor.isEnabled())
        before = len(client.requests)
        panel.save()
        self.assertEqual(len(client.requests), before)
        self.assertIn("刷新", panel.status.text())
        self.assertEqual(panel.status.textFormat(), Qt.TextFormat.PlainText)
        panel.load()
        self.answer(client)
        self.assertTrue(panel.editor.isEnabled())

    def test_validation_requires_confirmation_and_at_least_one_role(self):
        panel, client = self.panel()
        self.answer(client)
        self.fill_new(panel)
        before = len(client.requests)
        panel.confirm_password.setText("mismatch")
        panel.save()
        self.assertIn("不一致", panel.status.text())
        panel.confirm_password.setText("Secret@2026")
        panel.role_choices["viewer"].setChecked(False)
        panel.save()
        self.assertIn("至少", panel.status.text())
        panel.role_choices["viewer"].setChecked(True)
        panel.username.setText("a bad name")
        panel.save()
        self.assertIn("用户名", panel.status.text())
        self.assertEqual(len(client.requests), before)

    def test_save_failure_preserves_secrets_then_success_and_failed_reload_forbid_repeat(self):
        panel, client = self.panel()
        self.answer(client)
        self.fill_new(panel)
        panel.save()
        write = client.requests[-1]
        panel.save()
        self.assertIs(client.requests[-1], write)
        self.assertFalse(panel.editor.isEnabled())
        write[3](None, "账户重名")
        self.assertEqual(panel.password.text(), "Secret@2026")
        self.assertTrue(panel.editor.isEnabled())
        panel.save()
        self.assertEqual(client.requests[-1][2]["roles"], ["viewer"])
        client.requests[-1][3]({"ok": True, "user_id": "new-id"}, None)
        self.assertEqual(panel.password.text(), "")
        self.assertEqual(panel.confirm_password.text(), "")
        self.assertEqual(panel.selected_id, "new-id")
        self.answer(client, error="读取失败")
        self.assertIn("已保存", panel.status.text())
        self.assertIn("无需重复保存", panel.status.text())
        before = len(client.requests)
        panel.save()
        self.assertEqual(len(client.requests), before)

    def test_edit_blank_password_and_current_user_session_invalidation(self):
        panel, client = self.panel()
        self.answer(client)
        panel.choose_user("viewer-id")
        panel.display_name.setText("新显示名称")
        panel.save()
        path, payload = client.requests[-1][1:3]
        self.assertEqual(path, "/api/auth/users/update")
        self.assertNotIn("password", payload)
        self.assertEqual(payload["id"], "viewer-id")
        client.requests[-1][3]({"ok": True}, None)
        self.answer(client)
        with patch.object(panel, "_confirm_discard", return_value=True):
            panel.choose_user("admin-id")
        logged_out = []
        panel.logoutRequested.connect(lambda: logged_out.append(True))
        panel.save()
        client.requests[-1][3]({"ok": True}, None)
        self.assertEqual(logged_out, [True])

    def test_role_change_during_refresh_updates_permission_preview_without_dropping_inputs(self):
        panel, client = self.panel()
        self.answer(client)
        self.fill_new(panel)
        panel.load()
        changed = copy.deepcopy(ROLES)
        changed[-1]["permissions"].append("export.create")
        self.answer(client, {"users": USERS, "roles": changed})
        self.assertEqual(panel.username.text(), "newviewer")
        self.assertEqual(set(panel.preview_chips.values), {"查询数据", "导出报告和数据"})
        self.assertTrue(panel.dirty())

    def test_security_dialog_failure_stays_open_and_success_exits_once(self):
        client = Client()
        dialog = AccountSecurityDialog(client, USERS[0])
        dialog.show()
        emitted = []
        dialog.logoutRequested.connect(lambda: emitted.append(True))
        for edit, value in zip(dialog.fields, ("Old@2026", "NewPass@2026", "NewPass@2026")):
            edit.setText(value)
        dialog.save()
        before = len(client.requests)
        dialog.save()
        dialog.reject()
        self.assertEqual(len(client.requests), before)
        self.assertTrue(dialog.isVisible())
        client.requests[-1][3](None, "当前密码错误")
        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.fields[1].text(), "NewPass@2026")
        dialog.save()
        client.requests[-1][3]({"ok": True}, None)
        self.assertFalse(dialog.isVisible())
        self.assertTrue(all(not edit.text() for edit in dialog.fields))
        self.assertEqual(emitted, [True])

    def test_many_accounts_and_long_roles_fit_native_scroll_area(self):
        panel, client = self.panel()
        users = [{**USERS[1], "id": f"id-{i}", "display_name": "很长的姓名" * 10,
                  "roles": ["admin", "editor", "viewer"]} for i in range(40)]
        self.answer(client, {"users": users, "roles": ROLES})
        panel.resize(569, 1600)
        self.app.processEvents()
        panel.relayout()
        self.assertEqual(panel.roster.height(), 330)
        self.assertGreater(panel.roster.verticalScrollBar().maximum(), 0)
        self.assertLessEqual(panel.submit.geometry().right(), panel.actions.width())
        for row in panel.roster_rows:
            self.assertLessEqual(row.state.geometry().right(), row.width())
            self.assertGreaterEqual(row.height(), 56)

    def test_security_small_window_scroll_and_footer_do_not_overlap(self):
        dialog = AccountSecurityDialog(Client(), USERS[0])
        dialog.setStyleSheet(account_styles(True))
        dialog.resize(360, 380)
        dialog.show()
        self.app.processEvents()
        dialog._layout_content()
        self.assertGreater(dialog.scroll.verticalScrollBar().maximum(), 0)
        controls = [dialog.close_button, dialog.preferences, dialog.logout, dialog.submit]
        for control in controls:
            self.assertGreaterEqual(control.x(), 0)
            self.assertLessEqual(control.geometry().right(), dialog.actions.width())
        for index, control in enumerate(controls):
            for other in controls[index + 1:]:
                self.assertFalse(control.geometry().intersects(other.geometry()))

    def test_navigation_security_preferences_and_reopening_reuses_dialog(self):
        from qt_shell.native_windows import NativeMainWindow
        window = NativeMainWindow(Client(), {**USERS[0], "permissions": ["data.read"]})
        window.show()
        QTest.mouseClick(window.account_button, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        dialog = window._account_security
        self.assertTrue(dialog.isVisible())
        self.assertFalse(window.settings_dialog.isVisible())
        dialog.fields[0].setText("sensitive")
        QTest.mouseClick(dialog.preferences, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertTrue(window.settings_dialog.isVisible())
        self.assertEqual(window.settings_dialog.nav.currentRow(), 4)
        self.assertTrue(all(not edit.text() for edit in dialog.fields))
        window.settings_dialog.hide()
        QTest.mouseClick(window.account_button, Qt.MouseButton.LeftButton)
        self.assertIs(window._account_security, dialog)
        self.assertTrue(dialog.isVisible())
        dialog.reject()


if __name__ == "__main__":
    unittest.main()
