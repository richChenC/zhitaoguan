"""Native online snapshots, backup directory and validated restore confirmation."""
from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QEvent, QRect, Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from .native_import_quality import timestamp
from .native_settings_business import SettingsBusinessPanel, label


def size_text(size):
    size = max(0, int(size or 0))
    return f"{size / 1048576:.2f} MB" if size >= 1048576 else f"{size / 1024:.1f} KB"


def height(control, width, line=18.6):
    metrics = QFontMetrics(control.font())
    bounds = metrics.boundingRect(QRect(0, 0, max(1, round(width)), 100000),
                                  Qt.TextFlag.TextWordWrap, control.text() or " ")
    return math.ceil(max(1, math.ceil(bounds.height() / max(1, metrics.height()))) * line)


def box(name, parent):
    widget = QWidget(parent)
    widget.setObjectName(name)
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    return widget


def command(text, parent, callback, *, primary=False, width=None):
    widget = QPushButton(text, parent)
    widget.setObjectName("backupPrimary" if primary else "backupCommand")
    widget.setFixedHeight(36)
    if width is not None:
        widget.setFixedWidth(width)
    widget.clicked.connect(callback)
    return widget


class BackupRow(QWidget):
    def __init__(self, item, callback, parent):
        super().__init__(parent)
        self.item = dict(item)
        self.setObjectName("backupRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.name = label(str(item.get("name") or ""), "backupName")
        self.info = label(
            f"{timestamp(item.get('created_at'))} · {item.get('kind_label') or '历史备份（未登记）'}", "backupSmall")
        self.note = label(str(item.get("note") or ""), "backupSmall")
        self.size = label(size_text(item.get("size_bytes")), "backupMeta")
        digest = str(item.get("sha256") or "")
        self.digest = label(digest[:12] + "…" if digest else "", "backupMeta")
        self.digest.setToolTip(digest)
        for control in (self.name, self.info, self.note, self.size, self.digest):
            control.setParent(self)
        self.name.setWordWrap(False)
        self.name.setToolTip(str(item.get("name") or ""))
        self.restore = command("恢复", self, lambda: callback(str(item.get("path") or "")), width=50)
        self.restore.setAccessibleName("恢复备份 " + str(item.get("name") or ""))
        self.setToolTip(str(item.get("path") or ""))

    def layout_for_width(self, width, narrow):
        meta = max(self.size.fontMetrics().horizontalAdvance(self.size.text()),
                   self.digest.fontMetrics().horizontalAdvance(self.digest.text()))
        content = max(1, width - 22 - 60 - (0 if narrow else meta + 10))
        self.name.setText(self.name.fontMetrics().elidedText(
            str(self.item.get("name") or ""), Qt.TextElideMode.ElideRight, content))
        self.name.setGeometry(11, 11, content, 18)
        y = 30.6
        for control in (self.info, self.note):
            control.setVisible(bool(control.text()))
            if control.text():
                h = height(control, content, 15.5)
                control.setGeometry(11, round(y), content, h)
                y += h + 2
        info_height = y - 13
        meta_height = 36.1 if self.digest.text() else 17.05
        row_height = max(info_height, meta_height, 36) + 22
        if narrow:
            self.size.setGeometry(11, round(y + 6), meta, 18)
            self.digest.setGeometry(21 + meta, round(y + 6), meta, 18)
            row_height = y + 35
        else:
            top = (row_height - meta_height) / 2
            self.size.setGeometry(width - 81 - meta, round(top), meta, 18)
            self.digest.setGeometry(width - 81 - meta, round(top + 19), meta, 18)
        self.digest.setVisible(bool(self.digest.text()))
        self.restore.setGeometry(width - 61, round((row_height - 36) / 2), 50, 36)
        self.setFixedHeight(round(row_height))
        return row_height


class RestoreDialog(QDialog):
    restored = Signal(dict)

    def __init__(self, client, path, parent=None, *, external=False):
        super().__init__(parent)
        self.client, self.path, self.external = client, path, external
        self.serial, self.validated, self.restoring, self.active = 0, False, False, False
        self.setObjectName("backupRestoreDialog")
        self.setWindowTitle("确认从备份恢复")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(520, 420)
        self.setMinimumWidth(300)
        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)
        self.header = box("backupRestoreHeader", self)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(18, 16, 18, 13)
        words = QVBoxLayout()
        words.setSpacing(1)
        words.addWidget(label("恢复数据库", "backupSmall"))
        words.addWidget(label("确认从备份恢复", "backupDialogTitle"))
        header_layout.addLayout(words, 1)
        self.cancel = command("取消", self.header, self.reject, width=52)
        self.cancel.setFixedHeight(34)
        header_layout.addWidget(self.cancel)
        root.addWidget(self.header)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(16, 12, 16, 12)
        self.body_layout.setSpacing(12)
        self.danger = box("backupRestoreDanger", self.body)
        danger_layout = QVBoxLayout(self.danger)
        danger_layout.setContentsMargins(14, 12, 14, 12)
        danger_layout.setSpacing(6)
        danger_layout.addWidget(label("高风险操作", "backupDangerTitle"))
        danger_layout.addWidget(label(
            "恢复将覆盖当前数据库的业务数据（检测记录、管状态、报告导出记录、对比规则等）。"
            "恢复前系统会自动创建一份当前库的备份，请确认以下信息无误后再继续。", "backupDangerText"))
        self.body_layout.addWidget(self.danger)
        self.compare = QWidget()
        self.compare.installEventFilter(self)
        self.compare_layout = QVBoxLayout(self.compare)
        self.compare_layout.setContentsMargins(0, 0, 0, 0)
        self.compare_layout.setSpacing(8)
        self.compare_rows = []
        for title, text in (("当前数据库", "读取中…"), ("将恢复的备份", path),
                            ("安全备份", "恢复前自动创建至默认备份目录，可再恢复回去")):
            row, key, value = QWidget(), label(title, "backupCompareKey"), label(text, "backupCompareValue")
            key.setParent(row)
            value.setParent(row)
            value.setToolTip(text)
            self.compare_layout.addWidget(row)
            self.compare_rows.append((row, key, value))
        self.body_layout.addWidget(self.compare)
        self.ack_host = QWidget()
        ack_layout = QHBoxLayout(self.ack_host)
        ack_layout.setContentsMargins(0, 0, 0, 0)
        ack_layout.setSpacing(8)
        self.ack = QCheckBox()
        self.ack.setObjectName("backupRestoreAck")
        self.ack.setAccessibleName("我已理解：此操作覆盖当前数据，且恢复前会自动创建安全备份。")
        ack_layout.addWidget(self.ack, 0, Qt.AlignmentFlag.AlignTop)
        self.ack_text = label(self.ack.accessibleName(), "backupAckText")
        self.ack_text.setBuddy(self.ack)
        self.ack_text.installEventFilter(self)
        ack_layout.addWidget(self.ack_text, 1)
        self.body_layout.addWidget(self.ack_host)
        self.scroll.setWidget(self.body)
        root.addWidget(self.scroll, 1)
        self.footer = box("backupRestoreFooter", self)
        footer_layout = QHBoxLayout(self.footer)
        footer_layout.setContentsMargins(18, 14, 18, 14)
        footer_layout.setSpacing(8)
        self.message = label("正在校验备份…", "backupRestoreMessage")
        footer_layout.addWidget(self.message, 1)
        self.confirm = command("确认恢复", self.footer, self.restore, primary=True, width=76)
        self.confirm.setObjectName("backupRestoreConfirm")
        self.confirm.setFixedHeight(34)
        self.confirm.setAutoDefault(False)
        self.cancel.setAutoDefault(False)
        footer_layout.addWidget(self.confirm)
        root.addWidget(self.footer)
        self.ack.toggled.connect(self._controls)
        self._controls()

    def begin(self):
        if self.active or self.restoring:
            return
        self.active = True
        self.serial += 1
        serial = self.serial
        self.client.get("/api/backups", lambda data, error: self._listed(serial, data, error))
        self.cancel.setFocus()

    def _current(self, serial):
        return self.active and serial == self.serial

    def _listed(self, serial, data, error):
        if not self._current(serial):
            return
        items = (data or {}).get("items") or []
        self.item = next((item for item in items if item.get("path") == self.path), None)
        if error or not data or (not self.external and not self.item):
            self._error(error or "备份已不存在，请刷新列表后重新选择")
            return
        current = data.get("current") or {}
        self.compare_rows[0][2].setText(f"{current.get('findings', '/')} 条记录 · {current.get('outages', '/')} 次大修")
        self.client.post("/api/backup-validate", {"path": self.path},
                         lambda checked, issue: self._checked(serial, checked, issue))
        self._layout_rows()

    def _checked(self, serial, data, error):
        if not self._current(serial):
            return
        if error or not data or data.get("integrity") != "ok" or type(data.get("findings")) is not int:
            self._error(error or "备份校验结果无效，请重新选择")
            return
        self.validated = True
        item = self.item or data
        self.compare_rows[1][2].setText(
            f"{item.get('name') or Path(self.path).name} · {data['findings']} 条记录 · {timestamp(item.get('created_at'))}")
        self.compare_rows[1][2].setToolTip(self.path + "\nSHA-256: " + str(data.get("sha256") or ""))
        self.message.setText("校验通过，请核对后确认。" if data.get("hash_verified") else
                             "完整性通过；此历史备份没有SHA-256校验清单，请核对来源。")
        self._controls()
        self._layout_rows()

    def _error(self, text):
        self.validated = False
        self.message.setText("无法恢复：" + str(text))
        self._controls()

    def _controls(self, *_):
        self.ack.setEnabled(self.validated and not self.restoring)
        self.confirm.setEnabled(self.active and self.validated and self.ack.isChecked() and not self.restoring)
        self.cancel.setEnabled(not self.restoring)

    def restore(self):
        if not self.confirm.isEnabled() or self.restoring:
            return
        self.restoring = True
        self.message.setText("正在恢复…")
        self._controls()
        serial = self.serial
        self.client.post("/api/restore", {"path": self.path},
                         lambda data, error: self._restored(serial, data, error))

    def _restored(self, serial, data, error):
        if not self._current(serial):
            return
        self.restoring = False
        if error or not data:
            self.message.setText(str(error or "数据库恢复失败"))
            self._controls()
            return
        self.validated = False
        self._controls()
        self.active = False
        self.serial += 1
        self.accept()
        self.restored.emit(data)

    def reject(self):
        if self.restoring:
            return
        self.active = False
        self.validated = False
        self.serial += 1
        super().reject()

    def closeEvent(self, event):
        if self.restoring:
            event.ignore()
        else:
            self.active = False
            self.serial += 1
            super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_rows()

    def eventFilter(self, watched, event):
        if watched is getattr(self, "ack_text", None) and event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton and self.ack.isEnabled():
                self.ack.toggle()
                return True
        if watched is self.compare and event.type() == QEvent.Type.Resize:
            if event.size().width() != event.oldSize().width():
                self._layout_rows()
        return super().eventFilter(watched, event)

    def _layout_rows(self):
        if not hasattr(self, "compare_rows"):
            return
        width = max(1, self.compare.width())
        narrow = self.width() <= 430
        for row, key, value in self.compare_rows:
            value_width = width if narrow else max(1, width - 106)
            h = height(value, value_width, 20.15)
            key.setGeometry(0, 0, width if narrow else 96, 20)
            value.setGeometry(0 if narrow else 106, 24 if narrow else 0, value_width, h)
            row.setFixedHeight(h + (24 if narrow else 0))
        self.body_layout.activate()
        self.body.setMinimumHeight(self.body_layout.sizeHint().height())


class BackupWorkspace(SettingsBusinessPanel):
    logoutRequested = Signal()

    def __init__(self, client, user, parent=None):
        super().__init__("数据库备份与恢复", "整库在线备份（WAL 安全）；恢复前自动创建安全备份")
        if parent:
            self.setParent(parent)
        self.client, self.permissions = client, set(user.get("permissions") or [])
        self.serial, self.reading, self.busy, self.loaded = 0, False, False, False
        self.rows, self.row_widgets, self.data = [], [], {}
        self.dialog, self.dark = None, False
        self.content.setContentsMargins(0, 0, 0, 0)
        self.canvas = QWidget()
        self.content.addWidget(self.canvas)
        self.summary = box("backupSummary", self.canvas)
        self.summary_titles, self.summary_values = [], []
        for text in ("当前数据库", "有效检测记录", "覆盖大修", "备份目录"):
            title, value = label(text, "backupSmall"), label("--", "backupStat")
            title.setParent(self.summary)
            value.setParent(self.summary)
            self.summary_titles.append(title)
            self.summary_values.append(value)
        self.summary_values[-1].setObjectName("backupDirectory")
        self.actions = box("backupActions", self.canvas)
        self.now = command("立即备份（默认目录）", self.actions, self.create, primary=True, width=146)
        self.to_folder = command("备份到指定文件夹…", self.actions, lambda: self.create(True), width=134)
        self.refresh = command("刷新列表", self.actions, self.load, width=74)
        self.list_head = box("backupListHead", self.canvas)
        self.list_title = label("备份列表", "backupListTitle")
        self.list_hint = label("点击「恢复」前需二次确认", "backupSmall")
        self.list_title.setParent(self.list_head)
        self.list_hint.setParent(self.list_head)
        self.list_hint.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.list_host = QWidget(self.canvas)
        self.empty = label("正在读取备份…", "backupEmpty")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setParent(self.list_host)
        self.status = label("", "backupStatus")
        self.status.setParent(self.canvas)
        self.options = QWidget()
        options = QVBoxLayout(self.options)
        options.setContentsMargins(12, 12, 12, 12)
        policy = QHBoxLayout()
        policy.addWidget(label("自动备份保留数量"))
        self.keep = QSpinBox()
        self.keep.setRange(5, 200)
        self.keep.setValue(20)
        self.keep.setAccessibleName("自动备份保留数量")
        policy.addWidget(self.keep)
        self.save_policy = command("保存备份策略", self.options, self.save_policy_value)
        policy.addWidget(self.save_policy)
        policy.addStretch()
        options.addLayout(policy)
        self.policy_status = label("正在读取备份策略…", "backupStatus")
        options.addWidget(self.policy_status)
        self.external = command("选择外部备份恢复", self.options, self.select_external)
        options.addWidget(self.external, 0, Qt.AlignmentFlag.AlignLeft)
        self.options.hide()
        self.policy_serial, self.policy_ready, self.policy_busy = 0, False, False
        self.resized.connect(self.relayout)
        self._controls()
        self.load()
        self.load_policy()
        if "backup.manage" not in self.permissions:
            self.empty.setText("当前账户没有备份管理权限")
            self.policy_status.setText("当前账户没有备份管理权限")

    def _controls(self):
        allowed = "backup.manage" in self.permissions
        for control in (self.now, self.to_folder):
            control.setEnabled(allowed and not self.busy)
        self.refresh.setEnabled(allowed and not self.reading and not self.busy)
        can_restore = allowed and "database.restore" in self.permissions and self.loaded and not self.busy
        for row in self.row_widgets:
            row.restore.setEnabled(can_restore and not self.reading)
        self.external.setEnabled(can_restore and not self.reading)
        self.keep.setEnabled(allowed and self.policy_ready and not self.policy_busy)
        self.save_policy.setEnabled(allowed and self.policy_ready and not self.policy_busy)

    def load(self, _checked=False, *, saved=None, force=False):
        if "backup.manage" not in self.permissions or (self.reading and not force):
            return
        self.serial += 1
        serial = self.serial
        self.reading = True
        self.loaded = False
        self._controls()
        self.client.get("/api/backups", lambda data, error: self._loaded(serial, data, error, saved))

    def _loaded(self, serial, data, error, saved=None):
        if serial != self.serial:
            return
        self.reading = False
        self.loaded = not error and isinstance(data, dict)
        self.status.setText((f"备份已创建：{saved}。列表刷新失败，请刷新列表，无需重复备份。"
                             if saved and not self.loaded else f"已创建备份：{saved}" if saved else str(error or "")))
        if self.loaded:
            self.data = dict(data)
            self.rows = [dict(row) for row in data.get("items", []) if isinstance(row, dict)]
            current = data.get("current") or {}
            values = (size_text(data.get("db_size_bytes")), current.get("findings", "/"),
                      current.get("outages", "/"), data.get("dir") or "")
            for control, value in zip(self.summary_values, values):
                control.setText(str(value))
                control.setToolTip(str(value))
            self._render_rows()
        self.empty.setText("暂无备份" if self.loaded else str(error or "无法读取备份"))
        self._controls()
        self.relayout()

    def _render_rows(self):
        for row in self.row_widgets:
            row.hide()
            row.deleteLater()
        self.row_widgets = [BackupRow(item, self.open_restore, self.list_host) for item in self.rows]
        for row in self.row_widgets:
            row.show()

    def create(self, to_folder=False):
        if self.busy or "backup.manage" not in self.permissions:
            return
        self.busy = True
        self._controls()
        target = QFileDialog.getExistingDirectory(self, "选择备份文件夹") if to_folder else ""
        if to_folder and not target:
            self.busy = False
            self._controls()
            return
        payload = {"note": "导出备份" if to_folder else "软件设置手动备份"}
        if target:
            payload["target"] = target
        self.client.post("/api/backup", payload, self._created)

    def _created(self, data, error):
        self.busy = False
        if error or not data:
            self.status.setText(str(error or "备份失败"))
            self._controls()
            self.relayout()
            return
        # Invalidate any pre-write list response before reading the saved result.
        self.serial += 1
        self.reading = False
        self.load(saved=data.get("path") or data.get("name") or "已完成")

    def select_external(self):
        if not self.external.isEnabled():
            return
        path, _ = QFileDialog.getOpenFileName(self, "选择数据库备份", "", "数据库备份 (*.db)")
        if path:
            self.open_restore(path, external=True)

    def open_restore(self, path, *, external=False):
        if not ({"backup.manage", "database.restore"} <= self.permissions) or not self.loaded or self.busy or self.reading:
            return
        if self.dialog and self.dialog.isVisible():
            self.dialog.raise_()
            return
        if not external and not any(row.get("path") == path for row in self.rows):
            return
        if self.dialog:
            self.dialog.deleteLater()
        dialog = self.dialog = RestoreDialog(self.client, path, self.window(), external=external)
        dialog.setStyleSheet(backup_styles(self.dark))
        dialog.restored.connect(self._restored)
        dialog.show()
        dialog.begin()

    def _restored(self, data):
        self.status.setText("数据库已恢复。恢复前安全备份：" + str(data.get("safety_backup") or "未返回") + "。请重新登录。")
        self.relayout()
        self.logoutRequested.emit()

    def load_policy(self):
        if "backup.manage" not in self.permissions or self.policy_busy:
            return
        self.policy_serial += 1
        serial = self.policy_serial
        self.client.get("/api/backup-policy", lambda data, error: self._policy_loaded(serial, data, error))

    def _policy_loaded(self, serial, data, error, *, saving=False):
        if serial != self.policy_serial:
            return
        self.policy_busy = False
        value = (data or {}).get("automatic_keep")
        if error or type(value) is not int or not 5 <= value <= 200:
            self.policy_status.setText(str(error or "备份策略读取失败"))
            if not saving:
                self.policy_ready = False
        else:
            self.keep.setValue(value)
            self.policy_ready = True
            self.policy_status.setText("备份策略已保存。" if saving else "")
        self._controls()

    def save_policy_value(self):
        if not self.save_policy.isEnabled():
            return
        self.policy_busy = True
        self.policy_serial += 1
        serial = self.policy_serial
        self._controls()
        self.client.post("/api/backup-policy", {"automatic_keep": self.keep.value()},
                         lambda data, error: self._policy_loaded(serial, data, error, saving=True))

    def set_theme(self, dark):
        self.dark = dark
        if self.dialog:
            self.dialog.setStyleSheet(backup_styles(dark))
        self.relayout()

    def relayout(self):
        width = max(1, self.width() - 42)
        narrow = self.window().width() <= 900
        column = (width - 24) / 3
        for i in range(3):
            x = round(i * (column + 12))
            self.summary_titles[i].setGeometry(x, 16, round(column), 16)
            self.summary_values[i].setGeometry(x, 35, round(column), 28)
        self.summary_titles[3].setGeometry(0, 74, width, 16)
        directory_height = height(self.summary_values[3], width, 18.15)
        self.summary_values[3].setGeometry(0, 93, width, directory_height)
        summary_height = 109 + directory_height
        self.summary.setGeometry(21, 4, width, summary_height)
        y = 4 + summary_height
        action_rows = 1 if width >= 370 else 2
        self.actions.setGeometry(21, round(y), width, action_rows * 44 + 20)
        x, row_y = 0, 15
        for control in (self.now, self.to_folder, self.refresh):
            if x and x + control.width() > width:
                x, row_y = 0, row_y + 44
            control.move(x, row_y)
            x += control.width() + 8
        action_height = row_y + 36 + 13
        self.actions.setFixedHeight(action_height)
        y += action_height
        self.list_head.setGeometry(21, round(y), width, 47)
        self.list_title.setGeometry(0, 15, min(100, width), 19)
        self.list_hint.setGeometry(min(100, width), 15, max(1, width - 100), 19)
        y += 53.6
        rows_y = 0
        for row in self.row_widgets:
            row_height = row.layout_for_width(width, narrow)
            row.setGeometry(0, round(rows_y), width, round(row_height))
            rows_y += row_height + 6
        self.empty.setVisible(not self.row_widgets)
        self.empty.setGeometry(0, 0, width, 60)
        list_height = rows_y + 2 if self.row_widgets else 68
        self.list_host.setGeometry(21, round(y), width, round(list_height))
        y += list_height
        self.status.setVisible(bool(self.status.text()))
        if self.status.text():
            h = height(self.status, width)
            self.status.setGeometry(21, round(y + 8), width, h)
            y += h + 8
        self.canvas.setFixedHeight(round(y + 20))
        self.setFixedHeight(self.header.height() + self.canvas.height() + 2)


def backup_styles(dark=False):
    text, muted, line, surface, head = (
        ("#dbe6ed", "#a3b1bc", "#3a4c5b", "#192734", "#22313f") if dark else
        ("#263d49", "#647580", "#d9e3e8", "#ffffff", "#f8fafb"))
    return f"""
    QWidget#backupSummary, QWidget#backupActions, QWidget#backupListHead {{border-bottom:1px solid {line};}}
    QLabel#backupSmall, QLabel#backupDirectory {{font-size:10px;color:{muted};background:transparent;}}
    QLabel#backupDirectory {{font-size:11px;}}
    QLabel#backupStat {{font-size:18px;font-weight:700;color:{text};background:transparent;}}
    QLabel#backupName {{font-size:11px;font-weight:700;color:{text};background:transparent;}}
    QLabel#backupMeta {{font-size:11px;color:{muted};background:transparent;}}
    QLabel#backupListTitle {{font-size:12px;font-weight:700;color:{text};background:transparent;}}
    QLabel#backupEmpty, QLabel#backupStatus {{font-size:12px;color:{muted};background:transparent;}}
    QWidget#backupRow {{background:{surface};border:1px solid {line};border-radius:4px;}}
    QPushButton#backupCommand, QPushButton#backupPrimary {{
        min-height:0px;max-height:36px;height:36px;padding:0px 12px;
        font-size:12px;font-weight:600;border:1px solid {line};border-radius:8px;
        color:{text};background:{surface};
    }}
    QPushButton#backupPrimary {{background:#115d63;border-color:#176f76;color:white;}}
    QPushButton#backupCommand:hover {{border-color:#087d79;}}
    QPushButton#backupCommand:disabled, QPushButton#backupPrimary:disabled {{color:{muted};background:{head};}}
    QDialog#backupRestoreDialog {{background:{surface};color:{text};font-family:"Microsoft YaHei";}}
    QWidget#backupRestoreHeader, QWidget#backupRestoreFooter {{background:{head};}}
    QLabel#backupDialogTitle {{font-size:18px;font-weight:700;color:{text};}}
    QWidget#backupRestoreDanger {{background:{'#422e33' if dark else '#fdf1ef'};border:1px solid #f0b4ad;border-radius:6px;}}
    QLabel#backupDangerTitle {{font-size:13px;font-weight:700;color:{'#f5a7a7' if dark else '#a8444c'};}}
    QLabel#backupDangerText, QLabel#backupAckText {{font-size:12px;color:{'#e2bdbd' if dark else '#5a3a36'};}}
    QLabel#backupCompareKey {{font-size:12px;color:{muted};}}
    QLabel#backupCompareValue {{font-size:13px;color:{text};}}
    QLabel#backupRestoreMessage {{font-size:12px;color:{muted};}}
    QPushButton#backupRestoreConfirm {{
        min-height:0px;max-height:34px;height:34px;padding:0px;
        font-size:12px;font-weight:700;color:white;background:#a8444c;
        border:1px solid #a8444c;border-radius:6px;
    }}
    QPushButton#backupRestoreConfirm:disabled {{color:{muted};background:{head};border-color:{line};}}
    QCheckBox#backupRestoreAck {{padding:0px;spacing:0px;background:transparent;}}
    """
