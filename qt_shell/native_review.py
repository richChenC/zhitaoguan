"""Native cross-group review, retaining all original source records."""
import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QSplitter, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .native_components import button


class CrossGroupReviewPage(QWidget):
    changed = Signal()

    def __init__(self, client, permissions=None, parent=None):
        super().__init__(parent)
        self.client, self.permissions = client, permissions
        self.groups = []
        self.current = None
        self.sequence = 0
        layout = QVBoxLayout(self)
        tools = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("大修、通道或分析人员")
        self.filter.textChanged.connect(self.show_groups)
        tools.addWidget(self.filter, 1)
        tools.addWidget(button("刷新复核组", "refresh-cw", self.load))
        layout.addLayout(tools)
        split = QSplitter()
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self.select_group)
        split.addWidget(self.list)
        self.members = QTableWidget(0, 8)
        self.members.setHorizontalHeaderLabels(["编号", "数据组", "三字符", "深度", "位置", "分析人员", "来源", "统计"])
        self.members.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.members.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.members.horizontalHeader().setStretchLastSection(True)
        split.addWidget(self.members)
        split.setSizes([300, 800])
        layout.addWidget(split, 1)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("复核依据")
        layout.addWidget(self.reason)
        actions = QHBoxLayout()
        self.actions = []
        for label, action in (("将所选记录作为统计代表", "representative"), ("保留全部参与统计", "keep_all"),
                              ("撤销复核", "reset")):
            control = button(label, "check-check", lambda _, value=action: self.save(value))
            control.setEnabled(permissions is None or "review.write" in permissions)
            self.actions.append(control)
            actions.addWidget(control)
        layout.addLayout(actions)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.load()

    def load(self):
        self.sequence += 1
        sequence = self.sequence
        self.client.get("/api/cross-group-reviews",
                        lambda data, error: self.loaded(data, error) if sequence == self.sequence else None)

    def loaded(self, data, error):
        if error or not data:
            self.status.setText(error or "复核组读取失败")
            return
        self.groups = data.get("items") or []
        self.show_groups()
        self.status.setText(f"{data.get('total', 0)} 组，{data.get('pending', 0)} 组待复核；原始来源全部保留")

    def show_groups(self, *_):
        previous = (self.current or {}).get("group_key")
        self.list.clear()
        text = self.filter.text().strip().casefold()
        for group in self.groups:
            if text and text not in json.dumps(group, ensure_ascii=False).casefold():
                continue
            label = f"{group['outage']} · {group['thimble_id']}号管 · {group.get('analyst') or '/'}"
            status = {"pending": "待复核", "representative": "已选统计代表", "keep_all": "保留全部", "reset": "已撤销"}
            item = QListWidgetItem(label + "\n" + status.get(group["status"], group["status"]))
            item.setData(Qt.ItemDataRole.UserRole, group)
            self.list.addItem(item)
            if group["group_key"] == previous:
                self.list.setCurrentItem(item)
        if self.list.currentRow() < 0 and self.list.count():
            self.list.setCurrentRow(0)
        if not self.list.count():
            self.current = None
            self.members.setRowCount(0)

    def select_group(self, item, _previous):
        if item is None:
            return
        self.current = item.data(Qt.ItemDataRole.UserRole)
        rows = self.current["members"]
        self.members.setRowCount(len(rows))
        for row, record in enumerate(rows):
            values = (record["id"], record.get("calgroup"), record.get("indication"), record.get("percent"),
                      record.get("location"), record.get("analyst"), record.get("report_path"),
                      "代表" if record["id"] == self.current.get("representative_id") else "")
            for column, value in enumerate(values):
                self.members.setItem(row, column, QTableWidgetItem("" if value is None else str(value)))
        self.members.resizeColumnsToContents()
        self.reason.clear()

    def save(self, action):
        if not self.current:
            return
        payload = {"group_key": self.current["group_key"], "revision": self.current["revision"],
                   "action": action, "reason": self.reason.text().strip()}
        if action == "representative":
            index = self.members.currentRow()
            if index < 0:
                QMessageBox.warning(self, "跨组复核", "请选择一条统计代表记录")
                return
            payload["representative_id"] = self.current["members"][index]["id"]
        for control in self.actions:
            control.setEnabled(False)
        self.client.post("/api/cross-group-reviews", payload, self.saved)

    def saved(self, data, error):
        for control in self.actions:
            control.setEnabled(self.permissions is None or "review.write" in self.permissions)
        if error or not data:
            self.status.setText(error or "复核保存失败")
            return
        self.changed.emit()
        self.load()
