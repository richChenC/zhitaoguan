"""Bounded native task history with explicit retry of failed read requests."""
from __future__ import annotations

from datetime import datetime
from time import monotonic

from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QLabel, QPlainTextEdit,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
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
}


class NativeTaskCenter(QObject):
    def __init__(self, client, indicator, parent):
        super().__init__(parent)
        self.client, self.indicator, self.owner = client, indicator, parent
        self.items = {}
        self.dialog = None
        self.unread = 0
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(120)
        self.refresh_timer.timeout.connect(self.render)
        if hasattr(client, "requestStarted"):
            client.requestStarted.connect(self.started)
            client.activityFinished.connect(self.finished)

    def started(self, request_id, method, path):
        self.items[request_id] = {"id": request_id, "method": method, "path": path,
                                  "title": NAMES.get(path.split("?")[0], path.split("?")[0]),
                                  "time": datetime.now().strftime("%H:%M:%S"), "start": monotonic(),
                                  "status": "进行中", "error": "", "retryable": False}
        self.refresh_timer.start()

    def finished(self, request_id, method, path, error):
        item = self.items.get(request_id)
        if item is None:
            return
        if method == "GET" and not error:
            self.items.pop(request_id)
        else:
            item.update(status="失败" if error else "完成", error=error,
                        seconds=monotonic() - item["start"],
                        retryable=bool(error and method == "GET" and not path.startswith("/api/auth/")))
            if not self.dialog or not self.dialog.isVisible():
                self.unread += 1
        while len(self.items) > 200:
            finished = next((key for key, value in self.items.items() if value["status"] != "进行中"), None)
            if finished is None:
                break
            self.items.pop(finished)
        self.indicator.setText(str(self.unread) if self.unread else "")
        self.refresh_timer.start()

    def show(self):
        if self.dialog is None:
            self.dialog = QDialog(self.owner)
            self.dialog.setWindowTitle("通知与任务")
            self.dialog.resize(780, 540)
            layout = QVBoxLayout(self.dialog)
            self.table = QTableWidget(0, 5)
            self.table.setHorizontalHeaderLabels(["时间", "任务", "状态", "耗时（秒）", "请求"])
            self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            self.table.horizontalHeader().setStretchLastSection(True)
            self.table.itemSelectionChanged.connect(self.select)
            layout.addWidget(self.table, 1)
            self.details = QPlainTextEdit()
            self.details.setReadOnly(True)
            self.details.setMaximumHeight(110)
            layout.addWidget(self.details)
            actions = QHBoxLayout()
            self.retry = button("重试读取", "refresh-cw", self.retry_selected)
            actions.addWidget(self.retry)
            actions.addWidget(button("清除已结束任务", "trash-2", self.clear_finished))
            actions.addStretch()
            actions.addWidget(button("关闭", "x", self.dialog.close))
            layout.addLayout(actions)
        self.unread = 0
        self.indicator.setText("")
        self.dialog.show()
        self.render()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def selected(self):
        row = self.table.currentRow()
        cell = self.table.item(row, 0) if row >= 0 else None
        return self.items.get(cell.data(Qt.ItemDataRole.UserRole)) if cell else None

    def select(self):
        item = self.selected() or {}
        self.details.setPlainText(item.get("error") or item.get("path") or "")
        self.retry.setEnabled(bool(item.get("retryable")))

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
        self.table.blockSignals(True)
        rows = list(reversed(self.items.values()))
        self.table.setRowCount(len(rows))
        for row, item in enumerate(rows):
            elapsed = item.get("seconds", monotonic() - item["start"])
            values = [item["time"], item["title"], item["status"], f"{elapsed:.2f}",
                      f"{item['method']} {item['path']}"]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.ItemDataRole.UserRole, item["id"])
                self.table.setItem(row, column, cell)
            if item["id"] == previous:
                self.table.selectRow(row)
        self.table.blockSignals(False)
        self.select()
