"""Wrapping native filter chips with individually accessible clear actions."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QToolButton, QWidget

from .native_components import ToolFlowLayout, colored_icon, icon


class FilterChip(QWidget):
    removed = Signal(str)

    def __init__(self, key, text, parent=None):
        super().__init__(parent)
        self.key, self.full_text = key, text
        self.setObjectName("workbenchFilterChip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setFixedHeight(22)
        self.setMaximumWidth(300)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout(self)
        row.setContentsMargins(9, 0, 2, 0)
        row.setSpacing(2)
        self.label = QLabel()
        self.label.setObjectName("filterChipText")
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setMinimumWidth(0)
        row.addWidget(self.label, 1)
        self.remove_button = QToolButton()
        self.remove_button.setObjectName("filterChipRemove")
        self.remove_button.setIcon(icon("x"))
        self.remove_button.setIconSize(QSize(12, 12))
        self.remove_button.setFixedSize(18, 18)
        self.remove_button.setToolTip(f"清除条件：{text}")
        self.remove_button.setAccessibleName(f"清除条件：{text}")
        self.remove_button.clicked.connect(lambda: self.removed.emit(self.key))
        row.addWidget(self.remove_button)
        self.setToolTip(text)
        self.setAccessibleName(text)

    def sizeHint(self):
        return QSize(min(300, self.label.fontMetrics().horizontalAdvance(self.full_text) + 31), 22)

    def minimumSizeHint(self):
        return self.sizeHint()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.label.setText(self.label.fontMetrics().elidedText(
            self.full_text, Qt.TextElideMode.ElideRight, max(0, self.width() - 31)))

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "remove_button"):
            self.remove_button.setIcon(colored_icon("x", self.palette().color(QPalette.ColorRole.WindowText).name()))


class FilterSummary(QWidget):
    removed = Signal(str)
    cleared = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("workbenchFilterSummary")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setAccessibleName("检测记录筛选摘要")
        self.flow = ToolFlowLayout(self)
        self.flow.setContentsMargins(0, 10, 0, 0)
        self.flow.setSpacing(6)
        self.lead = QLabel("未设置筛选条件，当前显示全部检测记录")
        self.lead.setObjectName("workbenchFilterLead")
        self.lead.setTextFormat(Qt.TextFormat.PlainText)
        self.lead.setFixedHeight(17)
        self.flow.addWidget(self.lead)
        self.clear_all = QPushButton("清除全部")
        self.clear_all.setObjectName("workbenchFilterClear")
        self.clear_all.setFixedHeight(22)
        self.clear_all.setToolTip("清除全部筛选条件，包括列筛选")
        self.clear_all.clicked.connect(self.cleared)
        self.clear_all.hide()
        self.chips = {}
        self.entries = []

    def set_entries(self, entries, busy=False):
        entries = list(entries)
        if entries != self.entries:
            self.entries = entries
            while self.flow.count() > 1:
                item = self.flow.takeAt(1)
                widget = item.widget()
                if widget is not self.clear_all:
                    widget.hide()
                    widget.deleteLater()
            self.chips = {}
            for key, text in entries:
                chip = FilterChip(key, text, self)
                chip.removed.connect(self.removed)
                self.chips[key] = chip
                self.flow.addWidget(chip)
                chip.show()
            if entries:
                self.flow.addWidget(self.clear_all)
                self.clear_all.show()
            else:
                self.clear_all.hide()
            self.flow.invalidate()
            self.updateGeometry()
        self.lead.setText("正在筛选…" if busy else (
            f"已设置 {len(entries)} 项筛选条件" if entries else "未设置筛选条件，当前显示全部检测记录"))
        self.lead.setProperty("filtered", bool(entries))
        self.lead.style().unpolish(self.lead)
        self.lead.style().polish(self.lead)
        self.setAccessibleDescription(self.lead.text() + "；" + "；".join(text for _, text in entries))
