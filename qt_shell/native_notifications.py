"""Bounded native task history with explicit retry of failed read requests."""
from __future__ import annotations

from datetime import datetime
from time import monotonic

from PySide6.QtCore import QEvent, QObject, QSize, QTimer, Qt
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit,
    QTabBar, QVBoxLayout, QWidget,
)

from .native_components import button


NAMES = {
    "/api/import-excel": "Excel 导入", "/api/import": "RPT 导入",
    "/api/import-progress": "导入进度", "/api/import-excel-inspect": "Excel 来源识别",
    "/api/import-preflight": "导入预检", "/api/analysis/visualization": "可视化分析",
    "/api/analysis/tube-longitudinal": "单管历史分析", "/api/analysis/live": "实时管板分析",
    "/api/findings": "检测记录查询", "/api/findings/edit": "检测记录修订",
    "/api/state": "状态保存", "/api/states/import": "维护表导入",
    "/api/states/batch": "批量维护", "/api/states/delete-batch": "删除维护记录",
    "/api/backup": "数据库备份", "/api/restore": "数据库恢复",
    "/api/reports/preview": "报告预览", "/api/reports/export": "报告导出",
    "/api/data/delete": "删除检测记录", "/api/data-ledger/export": "综合台账导出",
    "/api/audits/export": "审计台账导出", "/api/data-quality/export": "质量台账导出",
    "/api/export-folder-excel": "生成标准 Excel", "/api/states/scopes": "新增大修范围",
    "/api/states/dismiss-recognition": "忽略待核对识别", "/api/states/recognize-note": "识别维护说明",
    "/api/states/batch-preview": "批量维护预览", "/api/states/import-preview": "状态表导入预览",
}


class NativeTaskCenter(QObject):
    def __init__(self, client, indicator, parent):
        super().__init__(parent)
        self.client, self.indicator, self.owner = client, indicator, parent
        self.items = {}
        self.dialog = None
        self.history_filter = "all"
        self.unread = 0
        self.toast = None
        self.toast_timer = QTimer(self)
        self.toast_timer.setSingleShot(True)
        self.toast_timer.timeout.connect(self._hide_toast)
        QApplication.instance().installEventFilter(self)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(120)
        self.refresh_timer.timeout.connect(self.render)
        if hasattr(client, "requestStarted"):
            client.requestStarted.connect(self.started)
            client.activityFinished.connect(self.finished)

    def started(self, request_id, method, path):
        self.items[request_id] = {"id": request_id, "method": method, "path": path,
                                  "title": NAMES.get(path.split("?")[0], "本机数据操作"),
                                  "time": datetime.now().strftime("%H:%M:%S"), "start": monotonic(),
                                  "status": "进行中", "error": "", "retryable": False}
        self.refresh_timer.start()

    def finished(self, request_id, method, path, error):
        item = self.items.get(request_id)
        if item is None:
            return
        quiet = path.split("?")[0] in {"/api/import-excel-inspect", "/api/report-options",
                                       "/api/discover-server", "/api/import-directory-preview",
                                       "/api/backup-validate", "/api/reports/preview",
                                       "/api/states/batch-preview", "/api/states/import-preview",
                                       "/api/states/recognize-note"}
        if not error and (method == "GET" or quiet):
            self.items.pop(request_id)
        else:
            item.update(status="失败" if error else "完成", error=error,
                        seconds=monotonic() - item["start"],
                        retryable=bool(error and method == "GET" and not path.startswith("/api/auth/")))
            if not self.dialog or not self.dialog.isVisible():
                self.unread += 1
            self._show_toast(item)
        while len(self.items) > 200:
            finished = next((key for key, value in self.items.items() if value["status"] != "进行中"), None)
            if finished is None:
                break
            self.items.pop(finished)
        self.indicator.setText(str(self.unread) if self.unread else "")
        self.refresh_timer.start()

    def show(self):
        if self.dialog is not None and self.dialog.isVisible():
            self.dialog.hide()
            return
        if self.dialog is None:
            self.dialog = QWidget(self.owner)
            self.dialog.setObjectName("taskDrawer")
            self.dialog.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            self.dialog.setAccessibleName("操作通知")
            layout = QVBoxLayout(self.dialog)
            layout.setContentsMargins(16, 16, 16, 16)
            heading = QHBoxLayout()
            title = QLabel("操作通知")
            title.setObjectName("drawerTitle")
            heading.addWidget(title, 1)
            clear = button("", "trash-2", self.clear_finished)
            clear.setToolTip("清除已结束的通知记录")
            clear.setAccessibleName("清除通知记录")
            close = button("", "x", self.dialog.close)
            close.setToolTip("关闭操作通知")
            close.setAccessibleName("关闭操作通知")
            for control in (clear, close):
                control.setFixedWidth(34)
                heading.addWidget(control)
            layout.addLayout(heading)
            self.summary = QLabel()
            self.summary.setObjectName("muted")
            layout.addWidget(self.summary)
            self.filters = QTabBar()
            self.filters.setExpanding(True)
            for text, category in (("全部", "all"), ("失败", "error"), ("提醒", "warning"),
                                   ("完成", "success"), ("信息", "info")):
                index = self.filters.addTab(text)
                self.filters.setTabData(index, category)
            self.filters.currentChanged.connect(self.filter_changed)
            layout.addWidget(self.filters)
            self.history = QListWidget()
            self.history.setAccessibleName("通知记录")
            self.history.setWordWrap(True)
            self.history.itemSelectionChanged.connect(self.select)
            layout.addWidget(self.history, 1)
            self.empty = QLabel("暂无通知")
            self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.empty.setObjectName("muted")
            layout.addWidget(self.empty, 1)
            self.details = QPlainTextEdit()
            self.details.setReadOnly(True)
            self.details.setMaximumHeight(110)
            layout.addWidget(self.details)
            actions = QHBoxLayout()
            self.retry = button("重试读取", "refresh-cw", self.retry_selected)
            actions.addWidget(self.retry)
            actions.addStretch()
            layout.addLayout(actions)
        self.unread = 0
        self.indicator.setText("")
        self._position_drawer()
        self.dialog.show()
        self.render()
        self.dialog.raise_()
        self.filters.setFocus()

    def selected(self):
        item = self.history.currentItem()
        return self.items.get(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def select(self):
        item = self.selected() or {}
        self.details.setPlainText(item.get("error") or "")
        self.details.setVisible(bool(item.get("error")))
        self.retry.setEnabled(bool(item.get("retryable")))
        self.retry.setVisible(bool(item.get("retryable")))

    def filter_changed(self, index):
        self.history_filter = self.filters.tabData(index)
        self.render()

    def retry_selected(self):
        item = self.selected()
        if item and item["retryable"]:
            item["retryable"] = False
            self.client.retry_read(item["id"])
            self.select()

    def clear_finished(self):
        self.items = {key: item for key, item in self.items.items() if item["status"] == "进行中"}
        self.render()

    def render(self):
        if self.dialog is None or not self.dialog.isVisible():
            return
        previous = (self.selected() or {}).get("id")
        self.history.blockSignals(True)
        self.history.clear()
        rows = []
        for item in reversed(self.items.values()):
            category = "error" if item["error"] else "success" if item["status"] == "完成" else "info"
            if self.history_filter in ("all", category):
                rows.append(item)
        for item in rows:
            elapsed = item.get("seconds", monotonic() - item["start"])
            message = item["error"][:120] if item["error"] else item["status"]
            cell = QListWidgetItem(f"{item['title']}\n{message}\n{item['time']}  ·  {elapsed:.2f} 秒")
            cell.setData(Qt.ItemDataRole.UserRole, item["id"])
            cell.setSizeHint(QSize(0, 100 if len(message) > 36 else 84))
            cell.setToolTip(item["error"] or item["title"])
            self.history.addItem(cell)
            if item["id"] == previous:
                self.history.setCurrentItem(cell)
        self.history.blockSignals(False)
        self.summary.setText(f"{len(self.items)} 条记录 · {sum(bool(item['error']) for item in self.items.values())} 条失败")
        self.history.setVisible(bool(rows))
        self.empty.setVisible(not rows)
        self.select()

    def _hide_toast(self):
        if self.toast:
            self.toast.hide()

    def _show_toast(self, item):
        if not self.owner.isVisible() or item["path"].startswith("/api/auth/"):
            return
        if self.toast is None:
            self.toast = QWidget(self.owner)
            self.toast.setObjectName("taskToast")
            layout = QHBoxLayout(self.toast)
            self.toast_message = QLabel()
            self.toast_message.setWordWrap(True)
            layout.addWidget(self.toast_message, 1)
            close = button("", "x", self._hide_toast)
            close.setToolTip("关闭通知")
            close.setFixedWidth(34)
            layout.addWidget(close)
        from PySide6.QtGui import QGuiApplication
        theme = self.owner.context.preferences.values["theme"]
        dark = theme == "dark" or (theme == "system" and QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark)
        background, foreground, border = ("#292f33", "#e7edef", "#465057") if dark else ("#ffffff", "#23465b", "#d4e0e6")
        accent = "#c64e53" if item["error"] else "#20836b"
        self.toast.setStyleSheet(f"QWidget#taskToast{{background:{background};border:1px solid {border};"
                                f"border-left:3px solid {accent};border-radius:6px;}}"
                                f"QLabel{{background:transparent;color:{foreground};}}")
        self.toast_message.setText(f"{'操作失败' if item['error'] else '操作完成'}\n"
                                   f"{item['title']}" + (f"：{item['error']}" if item["error"] else ""))
        self.toast.setFixedSize(350, 90 if item["error"] else 76)
        self._position_toast()
        self.toast.show()
        self.toast.raise_()
        prefs = self.owner.context.preferences.values
        self.toast_timer.stop()
        if prefs["notification_duration"]:
            self.toast_timer.start(prefs["notification_duration"])
        if prefs["notification_sound"]:
            QApplication.beep()

    def _position_toast(self):
        if self.toast:
            self.toast.move(max(0, self.owner.width() - self.toast.width() - 20),
                            max(0, self.owner.height() - self.toast.height() - 20))

    def _position_drawer(self):
        if self.dialog:
            width = min(440, max(240, self.owner.width() - 24))
            top = min(66, max(0, self.owner.height() - 280))
            self.dialog.setGeometry(max(0, self.owner.width() - width - 12), top,
                                    width, max(200, self.owner.height() - top - 12))

    def eventFilter(self, watched, event):
        if watched is self.owner and event.type() == QEvent.Type.Resize:
            self._position_toast()
            self._position_drawer()
        if self.dialog is not None and self.dialog.isVisible():
            if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
                self.dialog.hide()
                self.indicator.setFocus()
                return True
            if event.type() == QEvent.Type.MouseButtonPress:
                inside = isinstance(watched, QWidget) and (
                    watched is self.dialog or self.dialog.isAncestorOf(watched)
                    or watched is self.indicator or self.indicator.isAncestorOf(watched))
                if not inside:
                    self.dialog.hide()
        return super().eventFilter(watched, event)
