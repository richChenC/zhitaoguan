"""Native settings navigation and local database presentation."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QTextBlockFormat, QTextCursor, QTextLayout, QTextOption
from PySide6.QtWidgets import (
    QCheckBox, QLabel, QListWidget, QMenu, QPlainTextEdit, QPushButton, QSizePolicy,
    QStyledItemDelegate, QStyle, QWidget,
)

class SettingsNavigation(QListWidget):
    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Left,
                   Qt.Key.Key_Home, Qt.Key.Key_End) and self.count():
            row = self.currentRow()
            if key == Qt.Key.Key_Home:
                row = 0
            elif key == Qt.Key.Key_End:
                row = self.count() - 1
            else:
                row = (row + (1 if key in (Qt.Key.Key_Down, Qt.Key.Key_Right) else -1)) % self.count()
            self.setCurrentRow(row)
            event.accept()
            return
        super().keyPressEvent(event)


class SettingsNavigationDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        top = round(index.row() * 68.4375)
        bottom = round(index.row() * 68.4375 + 64.4375 + (4 if index.row() < 5 else 0))
        return QSize(1, bottom - top)

    def paint(self, painter, option, index):
        dark = bool(self.parent().property("dark"))
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(.5, .5, -.5, -(.5 if index.row() == 5 else 4.5))
        if selected or hover:
            painter.setPen(QColor(("#344547" if dark else "#bccbd0") if selected else (
                "#344547" if dark else "#d9e3e8")))
            painter.setBrush(QColor(("#254542" if dark else "#e9f5f4") if selected else (
                "#2a3738" if dark else "#f2f8fa")))
            painter.drawRoundedRect(rect, 8, 8)
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#78cfc1" if dark else "#087d79"))
            painter.drawRoundedRect(rect.adjusted(0, 10, -(rect.width() - 4), -10), 2, 2)
        font = QFont(option.font)
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(("#8ed7cc" if dark else "#155d63") if selected else (
            "#e4efed" if dark else "#263d49")))
        painter.drawText(QRectF(rect.left() + 16, rect.top() + 10, rect.width() - 24, 20),
                         Qt.AlignmentFlag.AlignVCenter, index.data(Qt.ItemDataRole.DisplayRole))
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor("#a6b8b5" if dark else "#71818b"))
        painter.drawText(QRectF(rect.left() + 16, rect.top() + 36, rect.width() - 24, 18),
                         Qt.AlignmentFlag.AlignVCenter, index.data(Qt.ItemDataRole.UserRole) or "")
        if option.state & QStyle.StateFlag.State_HasFocus:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#78cfc1" if dark else "#4d9a9f"), 1, Qt.PenStyle.DotLine))
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 6, 6)
        painter.restore()


class StoragePath(QPlainTextEdit):
    textChangedForLayout = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("settingsStoragePath")
        self.setReadOnly(True)
        self.setAccessibleName("数据库文件位置")
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.document().setDocumentMargin(0)
        option = self.document().defaultTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAnywhere)
        self.document().setDefaultTextOption(option)

    def setText(self, text):
        self.setPlainText(str(text))
        cursor = self.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        block = QTextBlockFormat()
        block.setLineHeight(18.7, QTextBlockFormat.LineHeightTypes.FixedHeight.value)
        cursor.mergeBlockFormat(block)
        self.setToolTip(str(text))
        self.textChangedForLayout.emit()

    def text(self):
        return self.toPlainText()

    def height_for_width(self, width):
        text = QTextLayout(self.text(), self.font())
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAnywhere)
        text.setTextOption(option)
        text.beginLayout()
        count = 0
        while True:
            line = text.createLine()
            if not line.isValid():
                break
            line.setLineWidth(max(1, width - 26))
            count += 1
        text.endLayout()
        return max(1, count) * 18.7 + 22


class SettingsStoragePanel(QWidget):
    def __init__(self, page):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setObjectName("settingsStoragePanel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.header = QWidget(self)
        self.header.setObjectName("settingsStorageHeader")
        title = self.title = QLabel("当前数据库", self.header)
        title.setObjectName("settingsStorageTitle")
        page.source_badge = QLabel("读取中", self.header)
        page.source_badge.setObjectName("settingsStorageBadge")
        page.source_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        page.source_badge.setTextFormat(Qt.TextFormat.PlainText)
        self.stats = []
        page.source_fields = {}
        for key, caption in (("engine", "存储引擎"), ("size", "数据库大小"), ("path", "文件位置")):
            host = QWidget(self)
            host.setObjectName("settingsStorageValue")
            label = QLabel(caption, host)
            label.setObjectName("settingsStorageCaption")
            value = StoragePath(host) if key == "path" else QLabel("正在读取…", host)
            if key != "path":
                value.setTextFormat(Qt.TextFormat.PlainText)
                value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                value.setObjectName("settingsStorageText")
            page.source_fields[key] = value
            self.stats.append((host, label, value))
        for key in ("exists", "integrity"):
            page.source_fields[key] = QLabel(self)
            page.source_fields[key].hide()
        page.source_fields["path"].textChangedForLayout.connect(self._layout_content)
        page.source_copy = QPushButton("复制路径", self.stats[2][0])
        page.source_copy.setAccessibleName("复制数据库文件路径")
        page.source_copy.setObjectName("settingsStorageCopy")
        page.source_copy.setEnabled(False)
        page.source_copy.clicked.connect(page.copy_source_path)
        self.actions = QWidget(self)
        self.actions.setObjectName("settingsStorageActions")
        page.source_status = QLabel("正在读取本地数据库", self.actions)
        page.source_status.setObjectName("settingsStorageStatus")
        page.source_status.setTextFormat(Qt.TextFormat.PlainText)
        page.source_status.setWordWrap(True)
        page.source_refresh = QPushButton("刷新状态", self.actions)
        page.source_refresh.clicked.connect(page.load_source)
        page.source_validate = QPushButton("校验数据库", self.actions)
        page.source_validate.clicked.connect(page.validate_source)
        page.source_validate.setEnabled("settings.manage" in page.user.get("permissions", []))
        page.source_text = QPlainTextEdit(self)
        page.source_text.setReadOnly(True)
        page.source_text.hide()
        self.page = page
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._diagnostics_menu)

    def _diagnostics_menu(self, point):
        menu = QMenu(self)
        action = menu.addAction("诊断详情")
        if menu.exec(self.mapToGlobal(point)) is action:
            from PySide6.QtWidgets import QDialog, QVBoxLayout
            dialog = QDialog(self)
            dialog.setWindowTitle("数据库诊断详情")
            dialog.resize(680, 440)
            layout = QVBoxLayout(dialog)
            details = QPlainTextEdit(self.page.source_text.toPlainText())
            details.setReadOnly(True)
            layout.addWidget(details)
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            dialog.show()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_content()

    def _layout_content(self):
        if not hasattr(self, "page"):
            return
        width = self.width()
        self.header.setGeometry(1, 1, width - 2, 58)
        self.title.setGeometry(23, 0, max(0, width - 150), 58)
        badge_width = max(77, self.page.source_badge.fontMetrics().horizontalAdvance(self.page.source_badge.text()) + 22)
        self.page.source_badge.setGeometry(width - badge_width - 21, 14, badge_width, 29)
        inner = width - 42
        split = (inner - 10) / 2
        for index, (host, caption, value) in enumerate(self.stats[:2]):
            host.setGeometry(round(21 + index * (split + 10)), 97, round(split), 73)
            caption.setGeometry(15, 13, round(split) - 30, 17)
            value.setGeometry(15, 40, round(split) - 30, 20)
        host, caption, value = self.stats[2]
        path_width = inner - 30 - 78
        path_height = value.height_for_width(path_width)
        host_height = 40.05 + path_height + 13
        host.setGeometry(21, 180, inner, round(host_height))
        caption.setGeometry(15, 13, inner - 30, 17)
        value.setGeometry(15, 40, path_width, round(path_height))
        self.page.source_copy.setGeometry(inner - 83, 40, 68, 30)
        action_top = 180 + host_height + 38
        status_width = max(40, inner - 180)
        status_height = max(19, self.page.source_status.fontMetrics().boundingRect(
            0, 0, status_width, 1000, int(Qt.TextFlag.TextWordWrap), self.page.source_status.text()).height())
        action_height = max(36, status_height)
        self.actions.setGeometry(21, round(action_top - 17), inner, action_height + 17)
        self.page.source_status.setGeometry(0, 17 + (action_height - status_height) // 2, status_width, status_height)
        self.page.source_refresh.setGeometry(inner - 171, 17, 75, 36)
        self.page.source_validate.setGeometry(inner - 87, 17, 87, 36)
        self.setFixedHeight(round(action_top + action_height + 21))


class SettingsQuickAction(QPushButton):
    def __init__(self, title, description, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsQuickAction")
        self.setAccessibleName(title + " " + description)
        self.title = QLabel(title, self)
        self.title.setObjectName("settingsQuickTitle")
        self.description = QLabel(description, self)
        self.description.setObjectName("settingsQuickDescription")
        self.description.setWordWrap(True)
        self.arrow = QLabel(self)
        self.arrow.setObjectName("settingsQuickArrow")
        self.arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.arrow.setText("\u2192")
        for child in (self.title, self.description, self.arrow):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def height_for_width(self, width):
        text = QTextLayout(self.description.text(), self.description.font())
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        text.setTextOption(option)
        text.beginLayout()
        count = 0
        while True:
            line = text.createLine()
            if not line.isValid():
                break
            line.setLineWidth(max(1, width - 62))
            count += 1
        text.endLayout()
        return max(88, 55.2 + max(1, count) * 17.6)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        text_width = max(1, self.width() - 62)
        description_height = max(18, self.description.fontMetrics().boundingRect(
            0, 0, text_width, 1000, int(Qt.TextFlag.TextWordWrap), self.description.text()).height())
        top = round((self.height() - 25.2 - description_height) / 2)
        self.title.setGeometry(17, top, text_width, 20)
        self.description.setGeometry(17, top + 25, text_width, description_height)
        self.arrow.setGeometry(self.width() - 39, (self.height() - 24) // 2, 24, 24)

    def set_theme(self, dark):
        self.setProperty("dark", dark)


class SettingsQuickActions(QWidget):
    jumpRequested = Signal(int)

    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setObjectName("settingsQuickActions")
        self.heading_row = QWidget(self)
        self.heading = QLabel("常用操作", self.heading_row)
        self.heading.setObjectName("settingsQuickHeading")
        self.hint = QLabel("按业务流程快速进入对应设置", self.heading_row)
        self.hint.setObjectName("settingsQuickHint")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.buttons = {}
        for title, description, index in (
            ("导入与显示", "维护检测来源、Report 策略和颜色阈值", 2),
            ("对比规则", "查看或建立历次大修匹配规则", 3),
            ("备份与维护", "备份数据库、去重并查看审计", 5),
        ):
            control = SettingsQuickAction(title, description, self)
            control.clicked.connect(lambda _checked=False, target=index: self.jumpRequested.emit(target))
            self.buttons[index] = control

    def resizeEvent(self, event):
        super().resizeEvent(event)
        inner = self.width() - 42
        width = (inner - 24) / 3
        height = max(control.height_for_width(round(width)) for control in self.buttons.values())
        self.heading_row.setGeometry(21, 19, inner, 19)
        self.heading.setGeometry(0, 0, min(100, inner), 19)
        self.hint.setGeometry(100, 0, max(0, inner - 100), 19)
        for index, control in enumerate(self.buttons.values()):
            left = round(21 + index * (width + 12))
            right = round(21 + index * (width + 12) + width)
            control.setGeometry(left, 50, right - left, round(height))
        self.setFixedHeight(round(70.6 + height))


class SettingsToggle(QCheckBox):
    def __init__(self, name):
        super().__init__()
        self.setAccessibleName(name)
        self.setFixedSize(85, 24)
        self.dark = False

    def hitButton(self, point):
        return self.rect().contains(point)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = QColor("#78cfc1" if self.dark else "#087d79")
        track = QRectF(.5, .5, 43, 23)
        painter.setPen(accent if self.isChecked() else QColor("#344547" if self.dark else "#d9e3e8"))
        painter.setBrush(accent if self.isChecked() else QColor("#2a3738" if self.dark else "#eef3f3"))
        painter.drawRoundedRect(track, 12, 12)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(21 if self.isChecked() else 3, 3, 18, 18))
        font = self.font()
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.DemiBold if self.isChecked() else QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(accent if self.isChecked() else QColor("#a6b8b5" if self.dark else "#71818b"))
        painter.drawText(QRectF(52, 0, 33, 24), Qt.AlignmentFlag.AlignVCenter,
                         "已启用" if self.isChecked() else "未启用")
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(accent, 1, Qt.PenStyle.DotLine))
            painter.drawRoundedRect(track.adjusted(1, 1, -1, -1), 11, 11)


class SettingsHint(QLabel):
    def __init__(self, text, parent):
        super().__init__(text, parent)
        self.setObjectName("settingsPreferenceHint")
        self.setTextFormat(Qt.TextFormat.PlainText)
        font = self.font()
        font.setPointSizeF(8.625)
        self.setFont(font)

    def text_layout(self, width):
        font = QFont(self.font())
        # Measure at four times the reference size to retain its half-pixel advance.
        font.setPixelSize(46)
        font.setWeight(QFont.Weight.Medium)
        layout = QTextLayout(self.text(), font)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        layout.beginLayout()
        count = 0
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(max(1, width) * 4)
            line.setPosition(QPointF(0, count * 19.546875 * 4))
            count += 1
        layout.endLayout()
        return layout, max(1, count) * 19.546875

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        layout, _height = self.text_layout(self.width())
        painter.scale(.25, .25)
        layout.draw(painter, QPointF(0, 4))


class SettingsPreferenceRow(QWidget):
    def __init__(self, title, hint, control, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setObjectName("settingsPreferenceRow")
        self.title = QLabel(title, self)
        self.title.setObjectName("settingsPreferenceTitle")
        self.hint = SettingsHint(hint, self)
        self.control = control
        control.setParent(self)
        control.setAccessibleName(title)
        control.setMinimumWidth(0)
        self.title.setBuddy(control)
        self.dark = False

    def layout_for_width(self, inner, narrow, gap, last):
        control_height = 24 if isinstance(self.control, SettingsToggle) else (
            40 if self.control.objectName() == "settingsThemeSwitch" else 34)
        label_width = inner if narrow else inner - 340 - gap
        _layout, hint_height = self.hint.text_layout(label_width)
        label_height = 20.8 + 4 + hint_height
        content_height = label_height + gap + control_height if narrow else max(label_height, control_height)
        height = 28 + content_height + (0 if last else 1)
        self.title.setGeometry(12, 14, label_width, 21)
        self.hint.setGeometry(12, 39, label_width, round(hint_height))
        control_width = 85 if isinstance(self.control, SettingsToggle) else (
            274 if self.control.objectName() == "settingsThemeSwitch" else inner if narrow else 340)
        left = 12 if narrow else 12 + inner - (85 if isinstance(self.control, SettingsToggle) else 340)
        top = 14 + label_height + gap if narrow else 14 + (content_height - control_height) / 2
        self.control.setGeometry(left, round(top), control_width, control_height)
        self.setProperty("last", last)
        return height

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.property("last"):
            painter = QPainter(self)
            painter.setPen(QColor("#2b393b" if self.dark else "#e8eef1"))
            painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)


class SettingsPreferencePanel(QWidget):
    def __init__(self, groups, saved, status, reset):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setObjectName("settingsPreferencePanel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.header = QWidget(self)
        self.header.setObjectName("settingsStorageHeader")
        self.title = QLabel("界面与工作流", self.header)
        self.title.setObjectName("settingsPreferencePanelTitle")
        self.subtitle = QLabel("界面偏好存本机；移位默认方向存数据库并随备份保存", self.header)
        self.subtitle.setObjectName("settingsPreferenceSubtitle")
        self.saved = saved
        saved.setParent(self.header)
        saved.setObjectName("settingsPreferenceSaved")
        saved.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.groups, self.rows = [], []
        for title, rows in groups:
            legend = QLabel(title, self)
            legend.setObjectName("settingsPreferenceLegend")
            controls = [SettingsPreferenceRow(*row, self) for row in rows]
            self.groups.append((legend, controls))
            self.rows.extend(controls)
        self.actions = QWidget(self)
        self.actions.setObjectName("settingsPreferenceActions")
        self.status, self.reset = status, reset
        status.setParent(self.actions)
        status.setObjectName("settingsPreferenceStatus")
        status.setTextFormat(Qt.TextFormat.PlainText)
        reset.setParent(self.actions)
        self.narrow = False
        self.window_width = 1180

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.relayout()

    def relayout(self):
        width, inner = self.width(), self.width() - 42
        self.header.setGeometry(1, 1, width - 2, 72)
        self.title.setGeometry(23, 14, max(1, width - 150), 23)
        self.subtitle.setGeometry(23, 40, max(1, width - 150), 18)
        self.saved.setGeometry(width - 85, 22, 64, 27)
        top = 77.09375
        for legend, rows in self.groups:
            legend.setGeometry(21, round(top), inner, 27)
            top += 38.59375
            for index, row in enumerate(rows):
                height = row.layout_for_width(inner, self.narrow, 9 if self.window_width <= 1000 else 14,
                                              index == len(rows) - 1)
                row.setGeometry(9, round(top), inner + 24, round(top + height) - round(top))
                top += height
        top += 2
        self.actions.setGeometry(21, round(top), inner, 53)
        self.status.setGeometry(0, 26, max(1, inner - 108), 18)
        self.reset.setGeometry(inner - 99, 17, 99, 36)
        self.setFixedHeight(round(top + 74))

    def set_theme(self, dark):
        for row in self.rows:
            row.dark = dark
            if isinstance(row.control, SettingsToggle):
                row.control.dark = dark
                row.control.update()
            row.update()


def settings_styles(theme):
    dark = theme == "dark"
    bg, panel, muted_panel, line, subtle, text, muted = (
        ("#101718", "#1b2526", "#202d2e", "#344547", "#2b393b", "#e4efed", "#a6b8b5") if dark else
        ("#f4f7f8", "#ffffff", "#f8fafb", "#d9e3e8", "#e8eef1", "#263d49", "#71818b"))
    return f"""
        QDialog#nativeSettings {{ background:{bg}; }}
        QWidget#settingsSidebar {{ background:{panel}; border:1px solid {line}; border-radius:12px; }}
        QLabel#settingsSidebarCaption {{ color:{muted}; font-size:11px; font-weight:700; padding:0 10px 12px; }}
        QListWidget#settingsNav {{ background:transparent; border:0; padding:0; outline:0; }}
        QListWidget#settingsNav::item {{ border:0; padding:0; min-height:0; background:transparent; }}
        QWidget#settingsLocal {{ border-top:1px solid {subtle}; }}
        QWidget#settingsLocal QLabel {{ font-size:11px; color:{muted}; }}
        QWidget#settingsLocalDot {{ border:0; border-radius:4px; background:#2f8a6d; }}
        QScrollArea#settingsPageScroll, QScrollArea#settingsPageScroll > QWidget > QWidget {{
            border:0; background:{bg}; }}
        QDialog QWidget#settingsUnframedSection, QDialog QWidget#settingsUnframedPage {{
            background:{bg}; border:0; }}
        QScrollArea#settingsPageScroll QScrollBar:vertical {{ width:15px; margin:0; background:{bg}; }}
        QScrollArea#settingsPageScroll QScrollBar::handle:vertical {{
            background:{"#445653" if dark else "#d5e1e7"}; min-height:28px; border-radius:7px; }}
        QScrollArea#settingsPageScroll QScrollBar::add-line:vertical,
        QScrollArea#settingsPageScroll QScrollBar::sub-line:vertical {{ height:0; }}
        QScrollArea#settingsPageScroll QScrollBar::add-page:vertical,
        QScrollArea#settingsPageScroll QScrollBar::sub-page:vertical {{ background:{bg}; }}
        QWidget#settingsStoragePanel, QWidget#settingsQuickActions {{ background:{panel};
            border:1px solid {line}; border-radius:12px; }}
        QWidget#settingsStorageHeader {{ background:{muted_panel}; border:0; border-left:3px solid {"#78cfc1" if dark else "#176f76"};
            border-bottom:1px solid {subtle}; border-top-left-radius:10px; border-top-right-radius:10px; }}
        QLabel#settingsStorageTitle {{ color:{text}; font-size:13px; font-weight:700; }}
        QLabel#settingsStorageBadge {{ color:{"#a6c9ba" if dark else "#648271"};
            background:{"#243a32" if dark else "#edf4f0"}; border:1px solid {"#3c5c4b" if dark else "#c9ded2"};
            border-radius:14px; font-size:11px; }}
        QLabel#settingsStorageBadge[state="error"] {{ color:#bd535a; background:{"#38292b" if dark else "#fbf0f1"}; }}
        QWidget#settingsStorageValue {{ background:{muted_panel}; border:1px solid {subtle}; border-radius:9px; }}
        QLabel#settingsStorageCaption {{ color:{muted}; font-size:11px; border:0; }}
        QLabel#settingsStorageText {{ color:{text}; font-size:13px; font-weight:600; border:0; }}
        QPlainTextEdit#settingsStoragePath {{ background:{"#202c2e" if dark else "#f7f9fb"}; color:{text};
            border:1px solid {"#344547" if dark else "#e2e8ed"}; border-radius:4px; padding:10px 12px;
            font-family:Consolas; font-size:11px; font-weight:600; }}
        QWidget#settingsStorageActions {{ border-top:1px solid {subtle}; }}
        QLabel#settingsStorageStatus {{ font-size:11px; color:{muted}; border:0; }}
        QWidget#settingsStoragePanel QPushButton {{ min-height:0; min-width:0; padding:0; font-size:12px;
            border:1px solid {"#536663" if dark else "#c5d4df"}; background:{panel}; }}
        QPushButton#settingsStorageCopy {{ font-size:11px; }}
        QWidget#settingsQuickActions QLabel#settingsQuickHeading {{ color:{"#8ed7cc" if dark else "#355865"};
            font-size:12px; font-weight:700; }}
        QLabel#settingsQuickHint {{ color:{muted}; font-size:11px; }}
        QPushButton#settingsQuickAction {{ min-width:0; min-height:0; padding:0; border:1px solid {line};
            border-radius:10px; background:{muted_panel}; }}
        QLabel#settingsQuickTitle {{ color:{text}; font-size:13px; font-weight:700; }}
        QPushButton#settingsQuickAction:hover {{ background:{panel}; border-color:{"#78cfc1" if dark else "#087d79"}; }}
        QLabel#settingsQuickDescription {{ color:{muted}; font-size:11px; font-weight:600; }}
        QLabel#settingsQuickArrow {{ background:{"#254542" if dark else "#e9f5f4"}; color:{"#8ed7cc" if dark else "#155d63"};
            border:0; border-radius:12px; font-size:13px; }}
        QWidget#settingsPreferencePanel {{ background:{panel}; border:1px solid {line}; border-radius:12px; }}
        QLabel#settingsPreferencePanelTitle {{ color:{text}; font-size:15px; font-weight:700; }}
        QLabel#settingsPreferenceSubtitle, QLabel#settingsPreferenceSaved, QLabel#settingsPreferenceStatus {{
            color:{muted}; font-size:11px; }}
        QLabel#settingsPreferenceLegend {{ color:{"#8ed7cc" if dark else "#176f76"}; font-size:12px;
            font-weight:700; padding-bottom:7px; border-bottom:1px solid {subtle}; }}
        QLabel#settingsPreferenceTitle {{ color:{text}; font-size:13px; font-weight:600; }}
        QLabel#settingsPreferenceHint {{ color:{"#a6b8b5" if dark else "#64757f"}; }}
        QWidget#settingsPreferenceRow {{ border:0; border-radius:8px; background:transparent; }}
        QWidget#settingsPreferenceRow:hover {{ background:{muted_panel}; }}
        QWidget#settingsPreferenceActions {{ border-top:1px solid {subtle}; }}
        QWidget#settingsPreferencePanel QComboBox {{ min-width:0; min-height:0; max-height:34px;
            padding:0 28px 0 10px; border:1px solid {line}; border-radius:8px;
            background:{panel}; color:{text}; font-size:12px; }}
        QWidget#settingsPreferencePanel QComboBox:hover {{ border-color:#9dbec2; }}
        QWidget#settingsPreferencePanel QComboBox:focus {{ border-color:{"#82d8cb" if dark else "#4d9a9f"}; }}
        QWidget#settingsThemeSwitch {{ background:{"#202d2e" if dark else "#eef3f3"};
            border:1px solid {"#344547" if dark else "#cbd9dc"}; border-radius:4px; }}
        QWidget#settingsThemeSwitch QPushButton {{ min-height:0; min-width:0; padding:0; border:1px solid transparent;
            border-radius:5px; background:transparent; color:{muted}; font-size:12px; font-weight:600; }}
        QWidget#settingsThemeSwitch QPushButton:checked {{ background:{panel};
            border-color:{"#4e8179" if dark else "#c6d8d7"}; color:{"#8ed7cc" if dark else "#176c69"}; }}
        QWidget#settingsPreferenceActions QPushButton {{ min-height:0; min-width:0; padding:0; font-size:12px;
            border:1px solid {"#536663" if dark else "#cbd6dc"}; background:{panel}; }}
    """
