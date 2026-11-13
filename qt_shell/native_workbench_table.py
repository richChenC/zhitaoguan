"""Native field selection and paging controls for the detection table."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QEvent, QIODevice, QRect, QSaveFile, QSize, Qt, Signal
from PySide6.QtGui import QFont, QIntValidator
from PySide6.QtWidgets import (
    QApplication, QComboBox, QHBoxLayout, QLabel, QLineEdit, QStyle, QStyledItemDelegate,
    QStyleOptionButton, QStyleOptionViewItem, QTabBar, QWidget,
)

from .constants import USER_DATA
from .native_components import ToolFlowLayout, button


class FieldTabs(QTabBar):
    def tabSizeHint(self, index):
        return QSize(64, 28)


class TabularLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._set_metrics()

    def _set_metrics(self):
        font = self.font()
        tabular = QFont.Tag.fromString("tnum")
        if font.hintingPreference() != QFont.HintingPreference.PreferNoHinting or not font.isFeatureSet(tabular):
            font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
            font.setFeature(tabular, 1)
            self.setFont(font)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._set_metrics()


class PagerLayout(ToolFlowLayout):
    def setGeometry(self, rect):
        super().setGeometry(rect)
        navigation = self.itemAt(1)
        if navigation:
            bounds = navigation.geometry()
            bounds.moveRight(rect.right() - self.contentsMargins().right())
            settings = self.itemAt(0).geometry()
            if bounds.top() == settings.top():
                bounds.moveTop(settings.top() + (settings.height() - bounds.height()) // 2)
            navigation.setGeometry(bounds)


class FindingDelegate(QStyledItemDelegate):
    """Draw a centered native checkbox with the whole cell as its click target."""
    def paint(self, painter, option, index):
        if index.column() != 0:
            return super().paint(painter, option, index)
        cell = QStyleOptionViewItem(option)
        self.initStyleOption(cell, index)
        cell.features &= ~QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        style = cell.widget.style() if cell.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, cell, painter, cell.widget)
        checkbox = QStyleOptionButton()
        checkbox.rect = QRect(0, 0, 14, 14)
        checkbox.rect.moveCenter(option.rect.center())
        checkbox.state = QStyle.StateFlag.State_Enabled if option.state & QStyle.StateFlag.State_Enabled else QStyle.StateFlag.State_None
        checkbox.state |= (QStyle.StateFlag.State_On if index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
                           else QStyle.StateFlag.State_Off)
        style.drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorCheckBox, checkbox, painter, cell.widget)

    def editorEvent(self, event, model, option, index):
        if index.column() != 0:
            return super().editorEvent(event, model, option, index)
        if not option.state & QStyle.StateFlag.State_Enabled:
            return False
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            return True
        toggle = (event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton
                  and option.rect.contains(event.position().toPoint()))
        toggle |= event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Space
        if toggle:
            checked = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
            return model.setData(index, Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked,
                                 Qt.ItemDataRole.CheckStateRole)
        return False


class FieldModeControl(QWidget):
    saveFailed = Signal(str)

    def __init__(self, parent=None, state_path: Path | None = None):
        super().__init__(parent)
        self.path = state_path or USER_DATA / "native-workbench-state.json"
        self.setObjectName("workbenchFieldModes")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setFixedSize(134, 34)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        self.tabs = FieldTabs()
        self.tabs.setObjectName("workbenchFieldTabs")
        self.tabs.setAccessibleName("检测记录字段")
        self.tabs.setDrawBase(False)
        self.tabs.setExpanding(False)
        self.tabs.setFixedSize(128, 28)
        for text, mode in (("重点字段", "key"), ("全部字段", "all")):
            self.tabs.setTabData(self.tabs.addTab(text), mode)
        self.tabs.setTabToolTip(0, "显示管号、结论、深度、位置和维护信息")
        self.tabs.setTabToolTip(1, "显示全部工作台字段")
        layout.addWidget(self.tabs)
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            self.tabs.setCurrentIndex(1 if isinstance(saved, dict) and saved.get("columns") == "all" else 0)
        except (OSError, ValueError):
            pass
        self.tabs.currentChanged.connect(self._save)

    def _save(self, index):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            output = QSaveFile(str(self.path))
            raw = json.dumps({"columns": self.tabs.tabData(index)}).encode("utf-8")
            if (not output.open(QIODevice.OpenModeFlag.WriteOnly)
                    or output.write(raw) != len(raw) or not output.commit()):
                raise OSError(output.errorString())
            self.setToolTip("")
        except OSError as error:
            message = f"字段显示已切换，但未能保存偏好：{error}"
            self.setToolTip(message)
            self.saveFailed.emit(message)


class WorkbenchPager(QWidget):
    pageRequested = Signal(int)
    sizeChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("workbenchPager")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.page = self.pages = 1
        self.busy = False
        layout = PagerLayout(self)
        layout.setContentsMargins(12, 8, 12, 9)
        layout.setSpacing(10)
        settings = QWidget()
        settings_layout = QHBoxLayout(settings)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(8)
        self.status = TabularLabel("准备就绪")
        self.status.setObjectName("workbenchPageRange")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setMaximumWidth(300)
        settings_layout.addWidget(self.status)
        settings_layout.addSpacing(12)
        size_label = QLabel("每页")
        size_label.setObjectName("workbenchPageSizeLabel")
        settings_layout.addWidget(size_label)
        self.size_combo = QComboBox()
        self.size_combo.setObjectName("workbenchPageSize")
        self.size_combo.setAccessibleName("每页显示条数")
        self.size_combo.setFixedSize(66, 34)
        for size in (20, 50, 100, 200, 500):
            self.size_combo.addItem(str(size), size)
        self.size_combo.setCurrentIndex(2)
        self.size_combo.currentIndexChanged.connect(lambda _: self.sizeChanged.emit())
        settings_layout.addWidget(self.size_combo)
        layout.addWidget(settings)
        self.navigation = QWidget()
        navigation = QHBoxLayout(self.navigation)
        navigation.setContentsMargins(0, 0, 0, 0)
        navigation.setSpacing(8)
        self.prev = button("", "chevron-left", lambda: self.pageRequested.emit(self.page - 1))
        self.next = button("", "chevron-right", lambda: self.pageRequested.emit(self.page + 1))
        for control, title in ((self.prev, "上一页"), (self.next, "下一页")):
            control.setObjectName("workbenchPageButton")
            control.setAccessibleName(title)
            control.setToolTip(f"{title}（Alt+{'Left' if control is self.prev else 'Right'}）")
            control.setFixedSize(30, 30)
        self.info = TabularLabel("1 / 1")
        self.info.setObjectName("workbenchPageInfo")
        self.info.setFixedWidth(64)
        self.info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info.setToolTip("当前页 / 总页数")
        navigation.addWidget(self.prev)
        navigation.addWidget(self.info)
        navigation.addWidget(self.next)
        jump_host = QWidget()
        jump = QHBoxLayout(jump_host)
        jump.setContentsMargins(0, 0, 0, 0)
        jump.setSpacing(4)
        jump.addWidget(QLabel("跳至"))
        self.jump = QLineEdit()
        self.jump.setObjectName("workbenchPageJump")
        self.jump.setAccessibleName("跳转到指定页码")
        self.jump.setPlaceholderText("页码")
        self.jump.setToolTip("输入页码后按 Enter 跳转，Esc 取消")
        self.jump.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.jump.setFixedSize(54, 30)
        self.jump.setMaxLength(10)
        self.jump.setValidator(QIntValidator(1, 2147483647, self.jump))
        self.jump.returnPressed.connect(self._jump)
        self.jump.installEventFilter(self)
        jump.addWidget(self.jump)
        jump.addWidget(QLabel("页"))
        navigation.addWidget(jump_host)
        layout.addWidget(self.navigation)

    def set_state(self, page, pages, *, busy=False):
        self.page, self.pages, self.busy = page, pages, busy
        self.info.setText(f"{page} / {pages}")
        self.prev.setEnabled(not busy and page > 1)
        self.next.setEnabled(not busy and page < pages)
        self.jump.setEnabled(not busy and pages > 1)
        self.size_combo.setEnabled(not busy)

    def _jump(self):
        if self.busy:
            return
        text = self.jump.text()
        if not text.isascii() or not text.isdigit() or int(text) < 1:
            self.jump.clear()
            return
        target = max(1, min(self.pages, int(text)))
        if target != self.page:
            self.pageRequested.emit(target)
            self.jump.clear()

    def eventFilter(self, watched, event):
        if watched is self.jump:
            if event.type() == QEvent.Type.KeyPress:
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._jump()
                    return True
                if event.key() == Qt.Key.Key_Escape:
                    self.jump.clear()
                    self.jump.clearFocus()
                    return True
            elif event.type() == QEvent.Type.FocusOut:
                self.jump.clear()
        return super().eventFilter(watched, event)
