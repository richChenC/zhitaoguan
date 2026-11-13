"""Native account directory, role editor and current-account security."""
from __future__ import annotations

import copy
import math
import re

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from .native_components import ToolFlowLayout, icon
from .native_import_quality import timestamp


ROLE_NAMES = {
    "admin": "系统管理员", "importer": "数据导入员", "editor": "数据编辑员",
    "reviewer": "审核员", "reporter": "报告用户", "viewer": "只读用户",
}
ROLE_HELP = {
    "admin": "账户、权限、备份和系统维护", "importer": "检测数据导入与查询",
    "editor": "检测记录编辑与管状态维护", "reviewer": "数据复核与操作审计",
    "reporter": "报告查看与结果导出", "viewer": "业务数据只读查阅",
}
ROLE_TASKS = {
    "admin": "管理账户与角色、专业设置、备份恢复和安全审计。",
    "importer": "查询现有数据并导入检测数据；不负责维护结论或系统配置。",
    "editor": "编辑检测记录并维护指套管状态；不负责账户管理和审核。",
    "reviewer": "复核数据、处理审核事项并查看操作审计。",
    "reporter": "查看检测数据、数据可视化并导出报告。",
    "viewer": "只读查看检测数据、状态和分析结果。",
}
PERMISSION_NAMES = {
    "data.read": "查询数据", "data.import": "导入数据", "data.edit": "编辑检测记录",
    "state.write": "维护管状态", "review.write": "审核数据", "export.create": "导出报告和数据",
    "audit.read": "查看操作审计", "backup.manage": "管理备份", "database.restore": "恢复数据库",
    "data.delete": "删除与回收站恢复", "data.purge": "永久删除",
    "settings.manage": "管理专业设置", "users.manage": "管理本地账户",
}


def label(value="", name="accountText", parent=None):
    control = QLabel(str(value), parent)
    control.setObjectName(name)
    control.setTextFormat(Qt.TextFormat.PlainText)
    control.setWordWrap(True)
    control.setMinimumWidth(0)
    control.setToolTip(str(value))
    return control


def frame(name, parent):
    control = QWidget(parent)
    control.setObjectName(name)
    control.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    return control


def command(text, parent, callback, name="accountCommand", height=36):
    control = QPushButton(text, parent)
    control.setObjectName(name)
    control.setFixedHeight(height)
    control.clicked.connect(callback)
    return control


def text_lines(control, width):
    metrics = QFontMetrics(control.font())
    bounds = metrics.boundingRect(QRect(0, 0, max(1, int(width)), 100000),
                                  Qt.TextFlag.TextWordWrap, control.text() or " ")
    return max(1, math.ceil(bounds.height() / max(1, metrics.height())))


def text_height(control, width, line_height=18.6):
    return math.ceil(text_lines(control, width) * line_height)


class Chips(QWidget):
    def __init__(self, parent, *, name="accountChip", size=9, gap=4, height=None):
        super().__init__(parent)
        self.name, self.size = name, size
        self.chip_height = height or (22 if size == 9 else 27)
        self.flow = ToolFlowLayout(self)
        self.flow.setSpacing(gap)
        self.flow.setContentsMargins(0, 0, 0, 0)
        self.values = []

    def set_values(self, values):
        if self.values == list(values):
            return
        self.values = list(values)
        while self.flow.count():
            item = self.flow.takeAt(0)
            item.widget().hide()
            item.widget().deleteLater()
        font = QFont("Microsoft YaHei")
        font.setPixelSize(self.size)
        metrics = QFontMetrics(font)
        for value in values:
            chip = label(value, self.name)
            chip.setFont(font)
            chip.setWordWrap(False)
            chip.setFixedSize(metrics.horizontalAdvance(value) + 18, self.chip_height)
            self.flow.addWidget(chip)
            chip.show()

    def height_for_width(self, width):
        return self.flow.heightForWidth(max(1, width)) if self.values else 0


class RoleChoice(QCheckBox):
    def __init__(self, role, parent):
        super().__init__(parent)
        self.code = str(role["code"])
        self.setObjectName("accountRoleChoice")
        self.setAccessibleName(str(role.get("label") or ROLE_NAMES.get(self.code, self.code)))
        self.title = label(self.accessibleName(), "accountRoleTitle", self)
        self.hint = label(ROLE_HELP.get(self.code, "按职责授予业务权限"), "accountSmall", self)
        for control in (self.title, self.hint):
            control.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.toggled.connect(self._style)

    def hitButton(self, point):
        return self.rect().contains(point)

    def _style(self, *_):
        self.setProperty("selected", self.isChecked())
        self.style().unpolish(self)
        self.style().polish(self)

    def height_for_width(self, width):
        return max(54, 22 + text_lines(self.title, width - 44) * 15.4
                   + text_lines(self.hint, width - 44) * 14)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = max(1, self.width() - 44)
        first = text_height(self.title, width, 15.4)
        self.title.setGeometry(34, 9, width, first)
        self.hint.setGeometry(34, 9 + first, width, text_height(self.hint, width, 14))


class RoleGuide(QWidget):
    resized = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("accountGuide")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.toggle = command("", self, self._toggle, "accountGuideToggle", 40)
        self.toggle.setAccessibleName("岗位与权限矩阵")
        self.toggle.setCheckable(True)
        self.caption = label("岗位与权限矩阵", "accountGuideCaption", self.toggle)
        self.arrow = QLabel(self.toggle)
        self.note = label("每个岗位对应一组最小必要权限，可多选组合", "accountSmall", self.toggle)
        for control in (self.caption, self.arrow, self.note):
            control.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.note.setWordWrap(False)
        self.cards = []
        self.theme = "light"
        self._toggle()

    def _toggle(self):
        self.arrow.setPixmap(icon("chevron-up" if self.toggle.isChecked() else "chevron-down", self.theme).pixmap(12, 12))
        self.resized.emit()

    def set_roles(self, definitions):
        for card, *_ in self.cards:
            card.hide()
            card.deleteLater()
        self.cards = []
        for role in definitions:
            code = str(role.get("code") or "")
            card = frame("accountRoleCard", self)
            title = label(role.get("label") or ROLE_NAMES.get(code, code), "accountRoleTitle", card)
            hint = label(ROLE_TASKS.get(code, ROLE_HELP.get(code, "")), "accountSmall", card)
            chips = Chips(card, gap=4)
            chips.set_values([PERMISSION_NAMES.get(p, p) for p in role.get("permissions", [])])
            self.cards.append((card, title, hint, chips))
        self.resized.emit()

    def arrange(self, width, columns):
        self.toggle.setGeometry(1, 1, width - 2, 40)
        self.caption.setGeometry(12, 0, 132, 40)
        self.arrow.setGeometry(width - 27, 14, 12, 12)
        note_width = min(self.note.fontMetrics().horizontalAdvance(self.note.text()), max(0, width - 195))
        self.note.setGeometry(width - 39 - note_width, 0, note_width, 40)
        y, card_width = 41, (width - 22 - (columns - 1) * 9) // columns
        for start in range(0, len(self.cards), columns):
            row_height = 0
            entries = self.cards[start:start + columns]
            for index, (card, title, hint, chips) in enumerate(entries):
                card.setVisible(self.toggle.isChecked())
                inner = max(1, card_width - 22)
                th, hh = text_height(title, inner, 17), text_height(hint, inner, 15)
                ch = chips.height_for_width(inner)
                h = 22 + th + 4 + hh + (5 + ch if ch else 0)
                card.setGeometry(11 + index * (card_width + 9), y, card_width, h)
                title.setGeometry(11, 11, inner, th)
                hint.setGeometry(11, 15 + th, inner, hh)
                chips.setGeometry(11, 20 + th + hh, inner, ch)
                row_height = max(row_height, h)
            for card, *_ in entries:
                card.resize(card_width, row_height)
            y += row_height + 9
        return y + 2 if self.toggle.isChecked() and self.cards else 42


class AccountRosterRow(QPushButton):
    def __init__(self, workspace, user):
        super().__init__(workspace.roster_body)
        self.workspace, self.user = workspace, user
        self.setObjectName("accountRosterRow")
        self.setAccessibleName(f"{user.get('display_name') or user.get('username')}，"
                               f"{user.get('username')}，"
                               f"{'启用' if user.get('active') else '已停用'}")
        self.setToolTip(self.accessibleName() + "\n" + " / ".join(
            ROLE_NAMES.get(r, r) for r in user.get("roles", [])))
        name = str(user.get("display_name") or user.get("username") or "")
        self.avatar = label(name.strip()[:2], "accountRosterAvatar", self)
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name = label(name, "accountRosterName", self)
        self.name.setWordWrap(False)
        self.current = label("当前", "accountCurrentChip", self)
        self.current.setWordWrap(False)
        self.current.setVisible(user.get("id") == workspace.user.get("id"))
        self.login_name = label(user.get("username", ""), "accountSmall", self)
        self.login_name.setWordWrap(False)
        self.login_name.setVisible(name.casefold() != str(user.get("username", "")).casefold())
        self.roles = Chips(self, height=18)
        self.roles.set_values([ROLE_NAMES.get(r, r) for r in user.get("roles", [])] or ["未分配岗位"])
        self.state = label("启用" if user.get("active") else "已停用", "accountState", self)
        self.state.setProperty("active", bool(user.get("active")))
        self.state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for control in self.findChildren(QWidget):
            control.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.clicked.connect(lambda: workspace.choose_user(user["id"]))
        self.setProperty("selected", user.get("id") == workspace.selected_id)

    def arrange(self, width):
        state_width = 36 if self.user.get("active") else 46
        main_width = max(20, width - 64 - state_width - 20)
        rh = self.roles.height_for_width(main_width)
        height = max(56, 18 + 17 + 3 + rh)
        self.setFixedHeight(height)
        self.avatar.setGeometry(11, (height - 32) // 2, 32, 32)
        self.state.setGeometry(width - state_width - 11, (height - 20) // 2, state_width, 20)
        current_width = 30 if not self.current.isHidden() else 0
        login_width = min(50, max(0, main_width // 3)) if not self.login_name.isHidden() else 0
        name_width = max(10, main_width - current_width - login_width - (6 if current_width else 0)
                         - (6 if login_width else 0))
        value = str(self.user.get("display_name") or self.user.get("username") or "")
        self.name.setText(self.name.fontMetrics().elidedText(value, Qt.TextElideMode.ElideRight, name_width))
        self.name.setGeometry(53, 10, name_width, 17)
        self.current.setGeometry(53 + name_width + 6, 10, current_width, 17)
        self.login_name.setGeometry(53 + main_width - login_width, 10, login_width, 17)
        self.roles.setGeometry(53, 30, main_width, rh)
        return height


class AccountWorkspace(QWidget):
    logoutRequested = Signal()
    storageRequested = Signal()
    changed = Signal()

    def __init__(self, client, user, parent=None):
        super().__init__(parent)
        self.setObjectName("nativeAccountWorkspace")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.client, self.user = client, user
        self.permissions = set(user.get("permissions") or [])
        self.users, self.definitions, self.selected_id = [], [], None
        self._baseline = None
        self._serial = 0
        self.reading = self.saving = self.fresh = self._filling = False
        self._pending_refresh = False
        self._saved_message = ""
        self._suggested = ""
        self.profile = frame("accountPanel", self)
        self.profile_header = frame("accountPanelHeader", self.profile)
        self.profile_title = label("当前账户", "accountPanelTitle", self.profile_header)
        self.profile_note = label("当前登录身份与可用权限", "accountHeaderNote", self.profile_header)
        values = [("显示名称", user.get("display_name", "")), ("用户名", user.get("username", "")),
                  ("角色", " / ".join(ROLE_NAMES.get(r, r) for r in user.get("roles", []))),
                  ("登录状态", "已登录")]
        self.profile_fields = []
        for caption, value in values:
            host = frame("accountProfileField", self.profile)
            self.profile_fields.append((host, label(caption, "accountProfileCaption", host),
                                        label(value, "accountProfileValue", host)))
        self.profile_fields[-1][0].setProperty("last", True)
        self.security = command("账户安全与退出", self.profile, self.open_security, height=35)
        self.current_permissions = Chips(self.profile, size=11, gap=6)
        self.permissions_caption = label("当前账户可执行", "accountInnerTitle", self.profile)
        self.current_permissions.set_values([PERMISSION_NAMES.get(p, p) for p in user.get("permissions", [])])
        self.own_guide = RoleGuide(self.profile)
        self.own_guide.set_roles([{"code": r, "label": ROLE_NAMES.get(r, r)} for r in user.get("roles", [])])
        self.own_guide.resized.connect(self.relayout)
        self.admin = frame("accountPanel", self)
        self.admin_header = frame("accountPanelHeader", self.admin)
        self.admin_title = label("账户与角色管理", "accountPanelTitle", self.admin_header)
        self.admin_note = label("创建本地账户、分配岗位，并以最小权限控制数据导入、编辑、审核与系统维护。",
                                "accountHeaderNote", self.admin_header)
        self.count = label("读取中", "accountCount", self.admin_header)
        self.count.setWordWrap(False)
        self.stats = []
        for caption, note in [("账户总数", "本机账户"), ("启用账户", "可正常登录"),
                              ("管理员", "系统维护岗位"), ("最近登录", "按登录审计")]:
            card = frame("accountStat", self.admin)
            self.stats.append((card, label(caption, "accountStatCaption", card),
                               label("—", "accountStatValue", card), label(note, "accountSmall", card)))
        self.stats[-1][2].setProperty("last", True)
        self.storage = frame("accountStorageNote", self.admin)
        self.storage_note = label("本机 SQLite · 密码 PBKDF2 加盐 · 连续 5 次失败锁定 5 分钟 · 账户变更即时下线",
                                  "accountHeaderNote", self.storage)
        self.storage_button = command("查看数据库位置", self.storage, self.storageRequested.emit, height=30)
        self.guide = RoleGuide(self.admin)
        self.guide.resized.connect(self.relayout)
        self.directory = frame("accountDirectory", self.admin)
        self.directory_header = frame("accountInnerHeader", self.directory)
        self.directory_title = label("账户目录", "accountInnerTitle", self.directory_header)
        self.directory_note = label("按姓名、用户名或岗位检索", "accountSmall", self.directory_header)
        self.refresh_button = command("刷新", self.directory_header, lambda: self.load(preserve_draft=False),
                                       "accountCompactCommand", 28)
        self.search = QLineEdit(self.directory)
        self.search.setPlaceholderText("搜索账户…")
        self.search.setAccessibleName("搜索账户")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.render_roster)
        self.roster = QScrollArea(self.directory)
        self.roster.setObjectName("accountRoster")
        self.roster.setFrameShape(QScrollArea.Shape.NoFrame)
        self.roster.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.roster_body = QWidget()
        self.roster.setWidget(self.roster_body)
        self.roster_rows = []
        self.roster_empty = label("尚未创建任何账户。", "accountEmpty", self.roster_body)
        self.editor = frame("accountEditor", self.admin)
        self.editor_header = frame("accountInnerHeader", self.editor)
        self.editor_title = label("账户资料", "accountInnerTitle", self.editor_header)
        self.editor_note = label("用户名创建后不可修改；保存后该账户现有会话立即失效", "accountSmall", self.editor_header)
        self.new = command("新建账户", self.editor_header, self.start_new, "accountCompactCommand", 28)
        self.fields = []
        for caption, name, maximum in [
            ("用户名（建议姓名完整拼音，创建后不可更改）", "username", 64),
            ("姓名或显示名称", "display_name", 80),
            ("密码（至少 6 位；编辑时留空保持不变）", "password", 128),
            ("确认密码", "confirm_password", 128),
        ]:
            host = QWidget(self.editor)
            title, edit = label(caption, "accountFieldLabel", host), QLineEdit(host)
            edit.setAccessibleName(caption)
            edit.setMaxLength(maximum)
            edit.setObjectName("accountInput")
            if name in {"password", "confirm_password"}:
                edit.setEchoMode(QLineEdit.EchoMode.Password)
            edit.textEdited.connect(self._edited)
            edit.returnPressed.connect(self.save)
            setattr(self, name, edit)
            self.fields.append((host, title, edit))
        self.display_name.setPlaceholderText("例如：张三")
        self.username.textEdited.connect(self._suggest_name)
        self.display_name.textEdited.connect(lambda: setattr(self, "_suggested", ""))
        self.roles_host = frame("accountRoles", self.editor)
        self.roles_caption = label("岗位角色（可多选）", "accountSmall", self.roles_host)
        self.role_choices = {}
        self.preview = frame("accountPermissionPreview", self.editor)
        self.preview_title = label("此岗位组合授予的权限", "accountPreviewTitle", self.preview)
        self.preview_chips = Chips(self.preview)
        self.active = QCheckBox("启用账户", self.editor)
        self.active.setObjectName("accountActive")
        self.active.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.active.toggled.connect(self._edited)
        self.actions = QWidget(self.editor)
        self.status = label("", "accountStatus", self.actions)
        self.status.setAccessibleName("账户保存状态")
        self.discard = command("放弃编辑", self.actions, self.fill_selection, height=30)
        self.submit = command("创建账户", self.actions, self.save, "accountSubmit")
        self.admin.setVisible("users.manage" in self.permissions)
        self.fill_selection()
        if "users.manage" in self.permissions:
            self.load()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.relayout()

    def _header(self, host, title, note, width, height, badge=None):
        host.setGeometry(1, 1, width - 2, height)
        title_width = QFontMetrics(title.font()).horizontalAdvance(title.text())
        title.setGeometry(23, 0, title_width + 1, height)
        right = 20
        if badge:
            badge_width = badge.fontMetrics().horizontalAdvance(badge.text()) + 24
            badge.setGeometry(width - badge_width - 22, (height - 28) // 2, badge_width, 28)
            right += badge_width + 14
        note.setGeometry(34 + title_width, 0, max(1, width - 36 - title_width - right), height)

    def relayout(self):
        if not hasattr(self, "submit"):
            return
        width = max(150, self.width())
        window_width = self.window().width()
        narrow, compact = window_width <= 900, window_width <= 1100
        self._header(self.profile_header, self.profile_title, self.profile_note, width, 62)
        columns, y, inner = (2 if narrow else 4), 81, width - 42
        value_height = max(43, *(23 + text_height(
            value, round(inner / columns) - (0 if index % columns == 0 else 16) - 16, 20)
            for index, (_, _, value) in enumerate(self.profile_fields)))
        for index, (host, caption, value) in enumerate(self.profile_fields):
            edge = index % columns == columns - 1
            if host.property("edge") != edge:
                host.setProperty("edge", edge)
                host.style().unpolish(host)
                host.style().polish(host)
            col_width = inner / columns
            x = 21 + round((index % columns) * col_width)
            offset = 0 if index % columns == 0 else 16
            field_width = round(col_width)
            host.setGeometry(x, y + (index // columns) * (value_height + 14), field_width, value_height)
            caption.setGeometry(offset, 0, max(1, field_width - offset - 16), 17)
            value.setGeometry(offset, 23, max(1, field_width - offset - 16), value_height - 23)
        y += (2 if narrow else 1) * value_height + (14 if narrow else 0) + 12
        self.security.setGeometry(21, y, 110, 35)
        y += 53
        manager = "users.manage" in self.permissions
        self.current_permissions.setVisible(not manager)
        self.permissions_caption.setVisible(not manager)
        self.own_guide.setVisible(not manager)
        if not manager:
            self.permissions_caption.setGeometry(21, y, inner, 20)
            y += 30
            ch = self.current_permissions.height_for_width(inner - 28)
            self.current_permissions.setGeometry(35, y, inner - 28, ch)
            y += ch + 18
            gh = self.own_guide.arrange(inner, 2 if narrow else 3)
            self.own_guide.setGeometry(21, y, inner, gh)
            y += gh + 18
        self.profile.setGeometry(0, 0, width, y + 1)
        if not manager:
            self.setFixedHeight(y + 1)
            return
        admin_y = y + 17
        self._header(self.admin_header, self.admin_title, self.admin_note, width, 72, self.count)
        cols, stat_y = (2 if compact else 4), 89
        sw = (inner - (cols - 1) * 10) / cols
        for index, (card, caption, value, note) in enumerate(self.stats):
            card.setGeometry(21 + round((index % cols) * (sw + 10)), stat_y + (index // cols) * 94,
                             round(sw), 84)
            caption.setGeometry(14, 12, round(sw) - 28, 16)
            value.setGeometry(14, 31, round(sw) - 28, 24 if index != 3 else 21)
            note.setGeometry(14, 58, round(sw) - 28, 15)
        y = stat_y + (2 if compact else 1) * 84 + (10 if compact else 0) + 16
        note_h = max(52, text_height(self.storage_note, inner - 134, 17.05) + 22)
        self.storage.setGeometry(21, y, inner, note_h)
        self.storage_note.setGeometry(13, 11, max(1, inner - 134), note_h - 22)
        self.storage_button.setGeometry(inner - 108, (note_h - 30) // 2, 95, 30)
        y += note_h + 14
        gh = self.guide.arrange(inner, 2 if narrow else 3)
        self.guide.setGeometry(21, y, inner, gh)
        y += gh
        dw = inner if narrow else max(190, round((inner - 14) * .36))
        ew = inner if narrow else inner - dw - 14
        dh, eh = self._directory_layout(dw), self._editor_layout(ew)
        self.directory.setGeometry(21, y, dw, dh)
        self.editor.setGeometry(21 if narrow else 21 + dw + 14,
                                y + dh + 14 if narrow else y, ew, eh)
        height = y + (dh + 14 + eh if narrow else max(dh, eh)) + 21
        self.admin.setGeometry(0, admin_y, width, height)
        self.setFixedHeight(admin_y + height)

    def _inner_header(self, host, title, note, action, width, command_width):
        host.setGeometry(15, 15, width - 30, 72)
        available = max(1, width - 50 - command_width)
        title.setGeometry(0, 13, available, 18)
        note.setGeometry(0, 33, available, 28)
        action.setGeometry(width - 30 - command_width, 16, command_width, 28)

    def _directory_layout(self, width):
        self._inner_header(self.directory_header, self.directory_title, self.directory_note,
                           self.refresh_button, width, 40)
        inner, y = max(1, width - 30), 99
        self.search.setGeometry(15, y, inner, 38)
        y += 47
        content_height = 0
        for row in self.roster_rows:
            h = row.arrange(inner)
            row.setGeometry(0, content_height, inner, h)
            content_height += h + 7
        if self.roster_rows:
            content_height -= 7
        else:
            content_height = 60
            self.roster_empty.setGeometry(0, 0, inner, 60)
        height = min(330, content_height)
        self.roster.setGeometry(15, y, inner, height)
        scrollbar = self.roster.verticalScrollBar().sizeHint().width() if content_height > height else 0
        self.roster_body.resize(inner - scrollbar, content_height)
        if scrollbar:
            y_row = 0
            for row in self.roster_rows:
                h = row.arrange(inner - scrollbar)
                row.setGeometry(0, y_row, inner - scrollbar, h)
                y_row += h + 7
            self.roster_body.resize(inner - scrollbar, max(1, y_row - 7))
        return y + height + 15

    def _editor_layout(self, width):
        self._inner_header(self.editor_header, self.editor_title, self.editor_note, self.new, width, 62)
        inner, y, col_width = max(1, width - 30), 99, max(1, (width - 44) // 2)
        for start in (0, 2):
            lh = max(text_lines(title, col_width) for _, title, _ in self.fields[start:start + 2]) * 18.6
            height = lh + 6 + 38
            for col, (host, title, edit) in enumerate(self.fields[start:start + 2]):
                host.setGeometry(15 + col * (col_width + 14), round(y), col_width, round(height))
                title.setGeometry(0, 0, col_width, round(lh))
                edit.setGeometry(0, round(lh + 6), col_width, 38)
            y += height + 12
        role_width = max(1, (inner - 40) // 2)
        ry = 29
        choices = list(self.role_choices.values())
        for start in range(0, len(choices), 2):
            height = max(choice.height_for_width(role_width) for choice in choices[start:start + 2])
            for col, choice in enumerate(choices[start:start + 2]):
                choice.setGeometry(13 + col * (role_width + 14), round(ry), role_width, round(height))
            ry += height + 8
        role_height = ry + 5
        self.roles_host.setGeometry(15, round(y), inner, round(role_height))
        self.roles_caption.setGeometry(13, -1, 130, 20)
        y += role_height + 12
        ch = self.preview_chips.height_for_width(max(1, inner - 24))
        ph = 40.8 + ch
        self.preview.setGeometry(15, round(y), inner, round(ph))
        self.preview_title.setGeometry(12, 10, inner - 24, 16)
        self.preview_chips.setGeometry(12, 32, inner - 24, ch)
        y += ph + 12
        self.active.setGeometry(15, round(y), 86, 28)
        y += 40
        discard_width = 92 if not self.discard.isHidden() else 0
        status_width = max(1, inner - 140 - discard_width - (12 if discard_width else 0))
        height = max(41, text_height(self.status, status_width, 17.05) + 5)
        self.actions.setGeometry(15, round(y), inner, height)
        self.status.setGeometry(0, 5, status_width, height - 5)
        self.submit.setGeometry(inner - 128, 5 + (height - 41) // 2, 128, 36)
        self.discard.setGeometry(inner - 140 - discard_width, 8 + (height - 41) // 2, discard_width, 30)
        return round(y + height + 15)

    def _sync_enabled(self):
        allowed = "users.manage" in self.permissions
        editable = allowed and self.fresh and not self.saving
        self.editor.setEnabled(editable)
        self.refresh_button.setEnabled(allowed and not self.reading and not self.saving)
        self.search.setEnabled(allowed and not self.saving)
        self.roster.setEnabled(allowed and not self.saving)

    def _state(self):
        return {"username": self.username.text(), "display_name": self.display_name.text(),
                "password": self.password.text(), "confirm": self.confirm_password.text(),
                "roles": sorted(k for k, choice in self.role_choices.items() if choice.isChecked()),
                "active": self.active.isChecked()}

    def dirty(self):
        return self._baseline is not None and self._state() != self._baseline

    def _feedback(self, value, state=""):
        self.status.setText(value)
        self.status.setToolTip(value)
        self.status.setProperty("state", state)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.relayout()

    def _edited(self, *_):
        if self._filling:
            return
        self.update_preview()
        dirty = self.dirty()
        self.discard.setVisible(dirty)
        if dirty:
            self._feedback("有未保存更改，请保存或放弃后再切换账户。", "dirty")
        self.relayout()

    def _suggest_name(self, value):
        if self.selected_id is None and (not self._suggested or self.display_name.text() == self._suggested):
            self._suggested = value.strip().lower()
            self.display_name.setText(self._suggested)
            self._edited()

    def _confirm_discard(self):
        if not self.dirty():
            return True
        dialog = QMessageBox(self)
        dialog.setWindowTitle("放弃未保存更改？")
        dialog.setText("当前账户资料尚未保存。放弃后无法恢复这些输入内容。")
        keep = dialog.addButton("继续编辑", QMessageBox.ButtonRole.RejectRole)
        discard = dialog.addButton("放弃更改", QMessageBox.ButtonRole.DestructiveRole)
        dialog.setDefaultButton(keep)
        dialog.exec()
        return dialog.clickedButton() == discard

    def start_new(self):
        if self.saving or not self._confirm_discard():
            return
        self.selected_id = None
        self.fill_selection()
        self.username.setFocus()

    def choose_user(self, user_id):
        if self.saving or user_id == self.selected_id or not self._confirm_discard():
            return
        if not any(u.get("id") == user_id for u in self.users):
            return
        self.selected_id = user_id
        self.fill_selection()

    def fill_selection(self):
        self._filling = True
        selected = next((u for u in self.users if u.get("id") == self.selected_id), {})
        self.username.setText(str(selected.get("username") or ""))
        self.username.setReadOnly(bool(selected))
        self.display_name.setText(str(selected.get("display_name") or ""))
        self._suggested = ""
        self.password.clear()
        self.confirm_password.clear()
        self.active.setChecked(bool(selected.get("active", True)))
        for code, choice in self.role_choices.items():
            choice.setChecked(code in selected.get("roles", ["viewer"]))
        self.submit.setText("保存账户变更" if selected else "创建账户")
        self.new.setProperty("selected", not bool(selected))
        self.new.style().unpolish(self.new)
        self.new.style().polish(self.new)
        self._baseline = self._state()
        self._filling = False
        self.discard.hide()
        self.update_preview()
        self.render_roster()
        last = f"最近登录：{timestamp(selected['last_login'])}。" if selected.get("last_login") else ""
        self._feedback(last + "密码留空则保留原密码；保存后该账户现有会话立即失效。" if selected else
                       "填写姓名、用户名和初始密码，并选择岗位角色；用户首次登录后可自行修改密码。")
        self._sync_enabled()

    def update_preview(self):
        codes = {k for k, choice in self.role_choices.items() if choice.isChecked()}
        granted = sorted({p for role in self.definitions if role.get("code") in codes
                          for p in role.get("permissions", [])})
        self.preview_chips.set_values([PERMISSION_NAMES.get(p, p) for p in granted] or ["尚未授予任何权限"])

    def render_roster(self):
        for row in self.roster_rows:
            row.hide()
            row.deleteLater()
        term = self.search.text().strip().casefold()
        users = [u for u in self.users if not term or term in " ".join([
            str(u.get("display_name") or ""), str(u.get("username") or ""),
            *[f"{r} {ROLE_NAMES.get(r, '')}" for r in u.get("roles", [])]]).casefold()]
        self.roster_rows = [AccountRosterRow(self, u) for u in users]
        for row in self.roster_rows:
            row.show()
        self.roster_empty.setVisible(not users)
        self.roster_empty.setText("没有匹配的账户。" if self.users else "尚未创建任何账户。")
        self.relayout()

    def load(self, *, preserve_draft=True):
        if "users.manage" not in self.permissions:
            return
        if self.saving:
            self._pending_refresh = True
            return
        if not preserve_draft and not self._confirm_discard():
            return
        self._serial += 1
        serial = self._serial
        self.reading, self.fresh = True, False
        self._sync_enabled()
        self.client.get("/api/auth/users", lambda data, error: self._loaded(serial, data, error, preserve_draft))

    def _loaded(self, serial, data, error, preserve_draft):
        if serial != self._serial:
            return
        self.reading = False
        if error or not data or not isinstance(data.get("users"), list) or not isinstance(data.get("roles"), list):
            self.fresh = False
            self._feedback((self._saved_message + "，无需重复保存；" if self._saved_message else "") +
                           "无法读取账户目录：" + (error or "返回数据不完整") + "。请点击刷新。", "error")
            self._sync_enabled()
            return
        keep = preserve_draft and self.dirty()
        self.users = [copy.deepcopy(u) for u in data["users"] if isinstance(u, dict)]
        definitions = [copy.deepcopy(r) for r in data["roles"] if isinstance(r, dict) and r.get("code")]
        checked = {k for k, v in self.role_choices.items() if v.isChecked()}
        if definitions != self.definitions:
            for choice in self.role_choices.values():
                choice.hide()
                choice.deleteLater()
            self.definitions, self.role_choices = definitions, {}
            for role in definitions:
                choice = RoleChoice(role, self.roles_host)
                self.role_choices[choice.code] = choice
                choice.setChecked(choice.code in checked)
                choice.toggled.connect(self._edited)
                choice.show()
            self.guide.set_roles(definitions)
        active = [u for u in self.users if u.get("active")]
        self.count.setText(f"{len(self.users)} 个账户 · {len(active)} 个启用")
        values = [len(self.users), len(active), sum("admin" in u.get("roles", []) for u in active),
                  timestamp(max((u.get("last_login") for u in self.users if u.get("last_login")), default=""))]
        for (_, _, value, _), new_value in zip(self.stats, values):
            value.setText(str(new_value))
        self.fresh = True
        if keep:
            self.update_preview()
            self.render_roster()
            self._feedback("账户目录已更新，当前未保存的编辑仍保留，请核对后保存。", "dirty")
        else:
            if not any(u.get("id") == self.selected_id for u in self.users):
                self.selected_id = None
            self.fill_selection()
            if self._saved_message:
                self._feedback(self._saved_message + "，变更已生效。", "success")
        self._saved_message = ""
        self._sync_enabled()
        self.relayout()

    def save(self):
        if "users.manage" not in self.permissions or self.saving:
            return
        if not self.fresh or self.reading:
            self._feedback("账户目录尚未读取成功，请刷新后再保存。", "error")
            return
        state = self._state()
        username, display = state["username"].strip(), state["display_name"].strip()
        password, confirm = state["password"], state["confirm"]
        error = ""
        if self.selected_id is None and not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.\-]{1,63}", username):
            error = "用户名需为 2–64 位字母、数字、下划线、点或连字符，首位为字母或数字。"
        elif not display:
            error = "请填写姓名或显示名称。"
        elif not state["roles"]:
            error = "请至少分配一个岗位角色。"
        elif (self.selected_id is None or password or confirm) and len(password) < 6:
            error = "密码至少 6 位。"
        elif password != confirm:
            error = "两次输入的新密码不一致。"
        elif self.selected_id is not None and not any(u.get("id") == self.selected_id for u in self.users):
            error = "此账户已不在最新目录中，请放弃编辑并重新选择。"
        if error:
            self._feedback(error, "error")
            return
        payload = {"display_name": display, "roles": state["roles"], "active": state["active"]}
        existing_id = self.selected_id
        if existing_id is None:
            payload["username"] = username
        else:
            payload["id"] = existing_id
        if password:
            payload["password"] = password
        self.saving = True
        self._serial += 1
        serial = self._serial
        self._sync_enabled()
        self._feedback("正在保存账户变更…")
        self.client.post("/api/auth/users/update" if existing_id is not None else "/api/auth/users", payload,
                         lambda data, error: self._saved(serial, existing_id, data, error))

    def _saved(self, serial, existing_id, data, error):
        if serial != self._serial:
            return
        self.saving = False
        pending, self._pending_refresh = self._pending_refresh, False
        if error or not data:
            self._feedback(error or "账户保存失败", "error")
            self._sync_enabled()
            if pending:
                self.load()
            return
        self.password.clear()
        self.confirm_password.clear()
        self._baseline = self._state()
        self.discard.hide()
        self.changed.emit()
        if existing_id is not None and existing_id == self.user.get("id"):
            self.logoutRequested.emit()
            return
        self.selected_id = existing_id if existing_id is not None else data.get("user_id")
        self._saved_message = "账户已保存"
        self.fresh = False
        self.load()

    def open_security(self):
        dialog = AccountSecurityDialog(self.client, self.user, self)
        dialog.logoutRequested.connect(self.logoutRequested)
        dialog.preferencesRequested.connect(self._show_permissions)
        dialog.exec()
        dialog.deleteLater()

    def _show_permissions(self):
        self.security.setFocus()

    def set_theme(self, theme):
        for guide in (self.guide, self.own_guide):
            guide.theme = theme
            guide._toggle()


class SecurityBody(QWidget):
    resized = Signal()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()


class AccountSecurityDialog(QDialog):
    logoutRequested = Signal()
    preferencesRequested = Signal()

    def __init__(self, client, user, parent=None):
        super().__init__(parent)
        self.client, self.busy = client, False
        self.setObjectName("accountSecurityDialog")
        self.setWindowTitle("账户")
        self.resize(480, 527)
        self.setMinimumSize(360, 380)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll = self.scroll = QScrollArea()
        scroll.setObjectName("accountSecurityScroll")
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(scroll)
        content = self.content = SecurityBody()
        content.setObjectName("accountSecurityBody")
        scroll.setWidget(content)
        self.title = label("当前账户", "accountSecurityTitle", content)
        display, username = str(user.get("display_name") or ""), str(user.get("username") or "")
        self.identity = label(f"{display} · {username}" if display.casefold() != username.casefold()
                              else username, "accountSecurityIdentity", content)
        self.role = label(" / ".join(ROLE_NAMES.get(r, r) for r in user.get("roles", [])), "accountSecurityRole", content)
        duties = [ROLE_TASKS[r] for r in user.get("roles", []) if r in ROLE_TASKS]
        self.duties = command("岗位职责说明", content, self._toggle_duties, "accountDuties", 19)
        self.duties.setCheckable(True)
        self.duties_note = label(" ".join(duties), "accountSecurityRole", content)
        self.duties_note.hide()
        self.duties.setVisible(bool(duties))
        self.fields, self.captions = [], []
        for caption in ("当前密码", "新密码（至少 6 位）", "确认新密码"):
            edit = QLineEdit(content)
            edit.setAccessibleName(caption)
            edit.setEchoMode(QLineEdit.EchoMode.Password)
            edit.setMaxLength(128)
            edit.setFixedHeight(40)
            edit.returnPressed.connect(self.save)
            self.captions.append(label(caption, "accountFieldLabel", content))
            self.fields.append(edit)
        self.status = label("", "accountStatus", content)
        self.actions = QWidget(content)
        self.close_button = command("关闭", self.actions, self.reject, height=34)
        self.preferences = command("账户与权限", self.actions, self._preferences, height=34)
        self.logout = command("退出登录", self.actions, self._logout, height=34)
        self.submit = command("修改密码", self.actions, self.save, "accountCommand", 34)
        self.content.resized.connect(self._layout_content)
        self._layout_content()
        self.fields[0].setFocus()

    def _toggle_duties(self):
        self.duties_note.setVisible(self.duties.isChecked())
        height = self._layout_content()
        center = self.geometry().center()
        available = self.screen().availableGeometry().height() - 80
        self.resize(self.width(), min(height, max(380, available)))
        self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)

    def _layout_content(self):
        width = max(1, self.content.width() - 98)
        self.title.setGeometry(49, 49, width, 28)
        identity_h = round(text_lines(self.identity, width) * 20.15)
        self.identity.setGeometry(49, 90, width, identity_h)
        y = 90 + identity_h + 13
        role_h = text_height(self.role, width, 18.6)
        self.role.setGeometry(49, y, width, role_h)
        y += role_h + 12
        self.duties.setGeometry(49, y, width, 19)
        self.duties.setIcon(icon("chevron-down" if self.duties.isChecked() else "chevron-right"))
        if not self.duties.isHidden():
            y += 19
        if self.duties.isChecked():
            height = text_height(self.duties_note, width, 18.6)
            self.duties_note.setGeometry(49, y + 6, width, height)
            y += height + 6
        y += 13
        for index, (caption, edit) in enumerate(zip(self.captions, self.fields)):
            caption.setGeometry(49, round(y + index * 70.6), width, 19)
            edit.setGeometry(49, round(y + index * 70.6 + 30.6), width, 40)
        y = round(y + len(self.fields) * 70.6)
        status_h = max(20, text_height(self.status, width, 18))
        self.status.setGeometry(49, y, width, status_h)
        y += status_h + 13
        rows, row, used = [], [], 0
        for control, button_width in ((self.close_button, 46), (self.preferences, 82),
                                      (self.logout, 70), (self.submit, 70)):
            if row and used + 8 + button_width > width:
                rows.append((row, used))
                row, used = [], 0
            used += (8 if row else 0) + button_width
            row.append((control, button_width))
        rows.append((row, used))
        action_height = len(rows) * 42 - 8
        self.actions.setGeometry(49, y, width, action_height)
        for index, (row, used) in enumerate(rows):
            x = width - used
            for control, button_width in row:
                control.setGeometry(x, index * 42, button_width, 34)
                x += button_width + 8
        height = y + action_height + 62
        self.content.setFixedHeight(height)
        return height

    def _preferences(self):
        if not self.busy:
            self.reject()
            self.preferencesRequested.emit()

    def _logout(self):
        if not self.busy:
            for edit in self.fields:
                edit.clear()
            self.accept()
            self.logoutRequested.emit()

    def save(self):
        if self.busy:
            return
        old, password, confirm = [edit.text() for edit in self.fields]
        if not old or len(password) < 6 or password != confirm:
            self.status.setText("请填写当前密码；新密码至少 6 位且两次输入一致。")
            self._layout_content()
            return
        self.busy = True
        for control in (*self.fields, self.submit, self.logout, self.close_button, self.preferences):
            control.setEnabled(False)
        self.status.setText("正在修改密码…")
        self._layout_content()
        self.client.post("/api/auth/password", {"current_password": old, "password": password}, self._saved)

    def _saved(self, data, error):
        self.busy = False
        for control in (*self.fields, self.submit, self.logout, self.close_button, self.preferences):
            control.setEnabled(True)
        if error or not data:
            self.status.setText(error or "密码修改失败")
            self._layout_content()
            return
        for edit in self.fields:
            edit.clear()
        self.accept()
        self.logoutRequested.emit()

    def reject(self):
        if not self.busy:
            for edit in self.fields:
                edit.clear()
            super().reject()


def account_styles(dark=False):
    panel, fill, text, muted, line, soft, accent, tint = (
        ("#1b2526", "#202d2e", "#e4efed", "#a6b8b5", "#344547", "#304043", "#78cfc1", "#233d3a") if dark else
        ("#ffffff", "#f8fafb", "#263d49", "#71818b", "#d9e3e8", "#e8eef1", "#087d79", "#e7f3f2"))
    return f"""
        QWidget#nativeAccountWorkspace {{ background:transparent; }}
        QWidget#nativeAccountWorkspace QLabel, QDialog#accountSecurityDialog QLabel {{
            font-family:"Microsoft YaHei"; font-size:12px; color:{text}; background:transparent; border:0; padding:0; }}
        QWidget#accountPanel {{ background:{panel}; border:1px solid {line}; border-radius:8px; }}
        QWidget#accountPanelHeader {{ background:{fill}; border:0; border-left:4px solid {accent};
            border-bottom:1px solid {soft}; border-top-right-radius:8px; }}
        QWidget#nativeAccountWorkspace QLabel#accountPanelTitle, QDialog#accountSecurityDialog QLabel#accountPanelTitle {{
            font-size:15px; font-weight:700; }}
        QWidget#nativeAccountWorkspace QLabel#accountSmall, QDialog#accountSecurityDialog QLabel#accountSmall {{
            color:{muted}; font-size:10px; }}
        QWidget#nativeAccountWorkspace QLabel#accountHeaderNote {{ color:{muted}; font-size:11px; }}
        QWidget#nativeAccountWorkspace QLabel#accountProfileValue {{ font-size:13px; font-weight:700; }}
        QWidget#nativeAccountWorkspace QLabel#accountProfileCaption {{ font-size:11px; color:{muted}; }}
        QWidget#accountProfileField {{ border:0; border-right:1px solid {soft}; }}
        QWidget#accountProfileField[edge="true"] {{ border:0; }}
        QWidget#nativeAccountWorkspace QLabel#accountCount {{ font-size:11px; font-weight:600; color:{accent};
            border:1px solid {line}; border-radius:14px; background:{tint}; padding:0 9px; }}
        QWidget#accountStat, QWidget#accountStorageNote, QWidget#accountGuide, QWidget#accountRoleCard {{
            background:{fill}; border:1px solid {line}; border-radius:7px; }}
        QWidget#accountRoleCard {{ background:{panel}; }}
        QWidget#accountGuide QLabel#accountRoleTitle {{ font-size:12px; }}
        QWidget#nativeAccountWorkspace QLabel#accountStatCaption {{ font-size:10px; color:{muted}; font-weight:600; }}
        QWidget#nativeAccountWorkspace QLabel#accountStatValue {{ font-size:19px; font-weight:700; }}
        QWidget#nativeAccountWorkspace QLabel#accountStatValue[last="true"] {{ font-size:13px; }}
        QWidget#accountDirectory, QWidget#accountEditor, QWidget#accountRoles {{
            background:{panel}; border:1px solid {line}; border-radius:8px; }}
        QWidget#accountInnerHeader {{ border:0; border-bottom:1px solid {soft}; }}
        QWidget#nativeAccountWorkspace QLabel#accountInnerTitle {{ font-size:12px; font-weight:700; }}
        QWidget#nativeAccountWorkspace QLineEdit, QDialog#accountSecurityDialog QLineEdit {{
            background:{panel}; color:{text}; border:1px solid {line}; border-radius:8px;
            font-size:12px; padding:0 10px; min-width:0; min-height:0; }}
        QWidget#nativeAccountWorkspace QLineEdit:focus, QDialog#accountSecurityDialog QLineEdit:focus {{
            border:1px solid {accent}; }}
        QWidget#nativeAccountWorkspace QLineEdit:read-only {{ background:{fill}; }}
        QWidget#nativeAccountWorkspace QPushButton, QDialog#accountSecurityDialog QPushButton {{
            min-width:0; min-height:0; padding:0 8px; border:1px solid {line}; border-radius:6px;
            font-size:12px; color:{text}; background:{panel}; }}
        QWidget#nativeAccountWorkspace QPushButton:hover {{ border-color:{accent}; background:{tint}; }}
        QWidget#nativeAccountWorkspace QPushButton#accountCompactCommand {{ font-size:11px; }}
        QWidget#nativeAccountWorkspace QPushButton#accountSubmit, QDialog#accountSecurityDialog QPushButton#accountSubmit,
        QWidget#nativeAccountWorkspace QPushButton#accountCompactCommand[selected="true"] {{
            background:{"#176c69" if dark else "#087d79"}; color:white; border-color:{accent}; }}
        QWidget#nativeAccountWorkspace QPushButton:disabled, QWidget#nativeAccountWorkspace QLineEdit:disabled {{
            color:{muted}; background:{fill}; }}
        QWidget#nativeAccountWorkspace QPushButton#accountGuideToggle {{
            border:0; background:transparent; text-align:left; padding-left:12px; font-size:12px; font-weight:700; }}
        QWidget#nativeAccountWorkspace QLabel#accountFieldLabel {{ font-size:12px; font-weight:600; }}
        QWidget#nativeAccountWorkspace QCheckBox#accountRoleChoice {{
            spacing:0; padding:0; background:{fill}; border:1px solid {soft}; border-radius:6px; }}
        QWidget#nativeAccountWorkspace QCheckBox#accountRoleChoice[selected="true"] {{
            background:{tint}; border-color:{"#4b8b83" if dark else "#80b8b1"}; }}
        QWidget#nativeAccountWorkspace QCheckBox#accountRoleChoice::indicator {{
            subcontrol-origin:padding; subcontrol-position:left center; left:10px; width:14px; height:14px; }}
        QWidget#nativeAccountWorkspace QLabel#accountRoleTitle {{ font-size:11px; font-weight:700; }}
        QWidget#accountPermissionPreview {{ background:{fill}; border:1px solid {line}; border-radius:6px; }}
        QWidget#nativeAccountWorkspace QLabel#accountPreviewTitle {{ font-size:10px; font-weight:700; color:{muted}; }}
        QWidget#nativeAccountWorkspace QLabel#accountChip, QWidget#nativeAccountWorkspace QLabel#accountCurrentChip {{
            border:1px solid {line}; border-radius:10px; background:{tint}; color:{accent}; font-size:9px; padding:0 7px; }}
        QWidget#nativeAccountWorkspace QLabel#accountCurrentChip {{ padding:0 5px; }}
        QWidget#nativeAccountWorkspace QLabel#accountGuideCaption {{ font-size:12px; font-weight:700; }}
        QWidget#nativeAccountWorkspace QCheckBox#accountActive {{
            background:{fill}; border:1px solid {line}; border-radius:4px; font-size:11px; padding:0 8px; }}
        QWidget#nativeAccountWorkspace QLabel#accountStatus, QDialog#accountSecurityDialog QLabel#accountStatus {{
            color:{muted}; font-size:11px; }}
        QDialog#accountSecurityDialog QLabel#accountSecurityTitle {{ font-size:18px; font-weight:700; }}
        QDialog#accountSecurityDialog QLabel#accountSecurityIdentity {{ font-size:13px; font-weight:700; }}
        QDialog#accountSecurityDialog QLabel#accountSecurityRole {{ font-size:12px; color:{muted}; }}
        QDialog#accountSecurityDialog QLabel#accountFieldLabel {{ font-size:12px; font-weight:600; }}
        QDialog#accountSecurityDialog QLabel#accountStatus {{ font-size:12px; color:{"#f3a4ab" if dark else "#a43d45"}; }}
        QDialog#accountSecurityDialog QPushButton#accountDuties {{
            border:0; padding:0; background:transparent; text-align:left; color:{muted}; font-size:12px; }}
        QDialog#accountSecurityDialog, QScrollArea#accountSecurityScroll,
        QWidget#accountSecurityBody, QScrollArea#accountSecurityScroll > QWidget {{ background:{panel}; border:0; }}
        QWidget#nativeAccountWorkspace QLabel#accountStatus[state="error"] {{ color:{"#f3a4ab" if dark else "#ad394a"}; }}
        QWidget#nativeAccountWorkspace QLabel#accountStatus[state="success"] {{ color:{accent}; }}
        QScrollArea#accountRoster, QScrollArea#accountRoster > QWidget > QWidget {{ background:{panel}; border:0; }}
        QWidget#nativeAccountWorkspace QPushButton#accountRosterRow {{ border-radius:7px; padding:0; }}
        QWidget#nativeAccountWorkspace QPushButton#accountRosterRow[selected="true"] {{
            background:{tint}; border-color:{accent}; border-left:3px solid {accent}; }}
        QWidget#nativeAccountWorkspace QLabel#accountRosterAvatar {{
            border-radius:8px; background:{tint}; color:{accent}; font-size:11px; font-weight:700; }}
        QWidget#nativeAccountWorkspace QLabel#accountRosterName {{ font-size:12px; font-weight:700; }}
        QWidget#nativeAccountWorkspace QLabel#accountState {{
            border:1px solid {line}; border-radius:9px; font-size:10px; color:{"#8ed7cc" if dark else "#317253"}; }}
        QWidget#nativeAccountWorkspace QLabel#accountState[active="false"] {{ color:{"#f3a4ab" if dark else "#90545a"}; }}
        QWidget#nativeAccountWorkspace QLabel#accountEmpty {{
            border:1px dashed {line}; border-radius:7px; color:{muted}; font-size:11px; padding:10px; }}
    """
