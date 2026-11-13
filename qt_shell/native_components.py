"""Shared native workspace controls and persisted desktop preferences."""
from __future__ import annotations

import json
from pathlib import Path
import hashlib
import re
from functools import lru_cache

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QObject, QPoint, QPointF, QRect, QRectF, QSaveFile, QSize, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QIcon, QPainter, QPainterPath, QPalette, QPen, QPolygonF
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QLayout, QMessageBox, QPushButton, QSizePolicy, QTabBar, QToolTip, QVBoxLayout, QWidget,
)

from .constants import UI_DIR, USER_DATA

SITE_NAMES = {"D": "大亚湾", "L": "岭澳", "N": "宁德", "H": "红沿河",
              "F": "防城港", "Y": "阳江", "T": "台山", "P": "惠州",
              "LF": "陆丰", "C": "苍南"}
STATE_NAMES = {"normal": "正常", "plugged": "堵管", "shifted": "移位", "replaced": "换管"}
STATE_PALETTE = {
    "normal": ("#d8f0e2", "#218a67", "#14553d"),
    "plugged": ("#f8d7dc", "#c23b52", "#7c2538"),
    "shifted": ("#ffe3b0", "#c47700", "#713f00"),
    "replaced": ("#d7e6fb", "#2e6fb8", "#1b4d91"),
    "missing": ("#edf1f3", "#9baab3", "#44545e"),
}
SITE_ALIASES = {"CNPS": "D", "LNPS": "L", "NDNP": "N", "LHNP": "H",
                "BLNP": "F", "YJNP": "Y", "TSNP": "T", "HENP": "P", "CNMP": "C", "LFNP": "LF"}


def canonical_site(value):
    value = str(value or "").strip().upper()
    return SITE_ALIASES.get(value, value)


@lru_cache(maxsize=128)
def icon(name, theme="light"):
    path = UI_DIR / "assets" / "icons" / f"{name}.svg"
    if not path.is_file():
        path = Path(__file__).parent / "assets" / f"{name}.svg"
    source = QIcon(str(path))
    if theme != "dark" or source.isNull():
        return source
    result = QIcon()
    for size in (16, 20, 24, 32):
        image = source.pixmap(size, size)
        painter = QPainter(image)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(image.rect(), QColor("#e7edef"))
        painter.end()
        result.addPixmap(image)
    return result


def button(text, name=None, callback=None):
    control = QPushButton(text)
    if name:
        control.setIcon(icon(name))
        control.setProperty("iconName", name)
    if callback:
        control.clicked.connect(callback)
    return control


@lru_cache(maxsize=128)
def colored_icon(name, color):
    source = icon(name)
    result = QIcon()
    for size in (16, 18, 20, 24, 32):
        image = source.pixmap(size, size)
        painter = QPainter(image)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(image.rect(), QColor(color))
        painter.end()
        result.addPixmap(image)
    return result


class NativeNavigationBar(QTabBar):
    """Keep native tab semantics while matching the reference's icon spacing."""
    icon_names = ("database", "box", "chart-no-axes-combined", "files", "wrench")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme = "light"
        self.setObjectName("mainNavigation")
        self.setAccessibleName("主要工作区")
        self.setExpanding(False)
        self.setDrawBase(False)
        self.setFixedHeight(38)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _font(self, selected=False):
        font = QFont("Microsoft YaHei")
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.Bold if selected else QFont.Weight.Medium)
        return font

    def tabSizeHint(self, index):
        width = QFontMetrics(self._font()).horizontalAdvance(self.tabText(index)) + 49
        return QSize(width + (3 if index < self.count() - 1 else 0), 38)

    def visual_tab_rect(self, index):
        return self.tabRect(index).adjusted(0, 0, -3 if index < self.count() - 1 else 0, 0)

    def set_theme(self, theme):
        self.theme = theme
        self.update()

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dark = self.theme == "dark"
        hovered = self.tabAt(self.mapFromGlobal(QCursor.pos())) if self.underMouse() else -1
        for index in range(self.count()):
            rect = self.visual_tab_rect(index)
            selected = index == self.currentIndex()
            color = ("#91e2d6" if dark else "#087e7b") if selected else ("#c9d7d4" if dark else "#687786")
            if selected or index == hovered:
                painter.setPen(QPen(QColor("#c6e2de") if selected else QColor("transparent"), 1))
                painter.setBrush(QColor(("#294744" if dark else "#e8f4f2") if selected
                                       else ("#263436" if dark else "#f0f5f7")))
                painter.drawRoundedRect(QRectF(rect).adjusted(.5, .5, -.5, -.5), 4, 4)
            painter.setFont(self._font(selected))
            text_width = painter.fontMetrics().horizontalAdvance(self.tabText(index))
            left = rect.x() + (rect.width() - text_width - 23) / 2
            image = colored_icon(self.icon_names[index], color).pixmap(16, 16)
            painter.drawPixmap(QPointF(left, rect.y() + 11), image)
            painter.setPen(QColor(color))
            painter.drawText(QRectF(left + 23, rect.y(), text_width, 38),
                             Qt.AlignmentFlag.AlignCenter, self.tabText(index))
            if selected and self.hasFocus():
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(color), 1, Qt.PenStyle.DotLine))
                painter.drawRoundedRect(QRectF(rect).adjusted(3, 3, -3, -3), 2, 2)


def status_dot(parent=None):
    dot = QWidget(parent)
    dot.setObjectName("onlineDot")
    dot.setFixedSize(6, 6)
    dot.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    dot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    return dot


class AccountIdentityButton(QPushButton):
    def __init__(self, user, callback, parent=None):
        super().__init__(parent)
        self.display_name = str(user.get("display_name") or user.get("username") or "账户").strip()
        self.setObjectName("accountIdentity")
        self.setAccessibleName(f"{self.display_name}，已登录账户")
        self.setToolTip(f"{self.display_name} · {user.get('username', '')}\n账户与权限 · 已登录")
        self.setFixedHeight(34)
        self.setFixedWidth(154)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 13, 0)
        row.setSpacing(9)
        self.avatar = QLabel(self.display_name[:2] or "账户")
        self.avatar.setObjectName("accountAvatar")
        self.avatar.setFixedSize(28, 28)
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.avatar)
        summary = QVBoxLayout()
        summary.setSpacing(2)
        self.name_label = QLabel()
        self.name_label.setObjectName("accountName")
        self.name_label.setMinimumWidth(0)
        self.name_label.setTextFormat(Qt.TextFormat.PlainText)
        self.name_label.setFixedHeight(15)
        summary.addWidget(self.name_label)
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(5)
        status_row.addWidget(status_dot(), 0, Qt.AlignmentFlag.AlignVCenter)
        status = QLabel("已登录")
        status.setObjectName("accountStatus")
        status.setFixedHeight(12)
        status_row.addWidget(status)
        status_row.addStretch()
        summary.addLayout(status_row)
        row.addLayout(summary, 1)
        for label in (self.avatar, self.name_label, status):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.clicked.connect(callback)
        self._compact = False

    def set_compact(self, compact):
        if compact == self._compact:
            return
        self._compact = compact
        self.setFixedWidth(135 if compact else 154)
        self.layout().setSpacing(7 if compact else 9)
        self.layout().setContentsMargins(0, 0, 9 if compact else 13, 0)
        self._elide_name()

    def _elide_name(self):
        available = max(0, self.width() - 28 - self.layout().spacing() - self.layout().contentsMargins().right())
        self.name_label.setText(self.name_label.fontMetrics().elidedText(
            self.display_name, Qt.TextElideMode.ElideRight, available))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide_name()


class SiteCoverageButton(QPushButton):
    def __init__(self, site, name, parent=None):
        super().__init__(parent)
        self.site, self.site_name = site, name
        self.setObjectName("siteCoverage")
        self.setCheckable(True)
        self.setFixedHeight(38)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 3, 8, 3)
        row.setSpacing(5)
        labels = QVBoxLayout()
        labels.setSpacing(0)
        self.name_label = QLabel(name)
        self.name_label.setObjectName("siteName")
        self.detail_label = QLabel()
        self.detail_label.setObjectName("siteDetail")
        labels.addWidget(self.name_label)
        labels.addWidget(self.detail_label)
        row.addLayout(labels, 1)
        self.coverage_label = QLabel("—")
        self.coverage_label.setObjectName("siteCoverageValue")
        row.addWidget(self.coverage_label)
        for label in (self.name_label, self.detail_label, self.coverage_label):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.set_summary(0, 0, 0)

    def set_summary(self, units, reported, total):
        value = f"{reported / total:.1%}".replace(".0%", "%") if total else "—"
        code = {"P": "HZ", "C": "CN"}.get(self.site, self.site)
        self.detail_label.setText(f"{code + ' · ' if code else ''}{units} 台机组")
        self.coverage_label.setText(value)
        self.setText(f"{self.site_name}\n{units} 台机组 · {value}")
        self.setAccessibleName(f"{self.site_name} · {units} 台机组 · 覆盖 {value}")
        self.setToolTip(f"筛选{self.site_name} · 全库各机组最新大修检测覆盖 {reported}/{total} 根")

    def paintEvent(self, event):
        # Child labels supply the two-column contents; retain QPushButton semantics.
        from PySide6.QtWidgets import QStyle, QStyleOptionButton, QStylePainter
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = ""
        painter = QStylePainter(self)
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)


class ToolFlowLayout(QLayout):
    """Wrap command controls at their natural width on smaller workspaces."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []
        self.bottom_aligned = False
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(6)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index):
        return self.items.pop(index) if 0 <= index < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, True)

    def minimumSize(self):
        size = QSize()
        for item in self.items:
            if not item.isEmpty():
                size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def sizeHint(self):
        return self.minimumSize()

    def _arrange(self, rect, apply):
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, height = area.x(), area.y(), 0
        line = []

        def place():
            if apply:
                for entry, position, size in line:
                    entry.setGeometry(QRect(QPoint(position, y + (height - size.height() if self.bottom_aligned else 0)), size))

        for item in self.items:
            if item.isEmpty():
                continue
            size = item.sizeHint()
            if x > area.x() and x + size.width() > area.right() + 1:
                place()
                line = []
                x, y, height = area.x(), y + height + self.spacing(), 0
            line.append((item, x, size))
            x += size.width() + self.spacing()
            height = max(height, size.height())
        place()
        return y + height - rect.y() + margins.bottom()


def export_widget_image(parent, client, widget, title, *, image=None, default_name=""):
    """Recheck the live session and audit the exact image before saving."""
    path, _ = QFileDialog.getSaveFileName(parent, title, default_name, "PNG (*.png)")
    if not path:
        return
    raw = QByteArray()
    buffer = QBuffer(raw)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if image is None:
        image = widget.grabWindow() if hasattr(widget, "grabWindow") else widget.grab()
    if not image.save(buffer, "PNG"):
        QMessageBox.warning(parent, title, "无法生成图片")
        return
    buffer.close()
    content = bytes(raw)
    if not 0 < len(content) <= 50 * 1024 * 1024:
        QMessageBox.warning(parent, title, "图片大小超出可导出范围")
        return

    def authorized(data, error):
        if error or not data or not data.get("ok"):
            QMessageBox.warning(parent, title, error or "导出校验失败")
            return
        stream = QSaveFile(path)
        if (not stream.open(QIODevice.OpenModeFlag.WriteOnly)
                or stream.write(content) != len(content) or not stream.commit()):
            QMessageBox.warning(parent, title, stream.errorString())
    client.post("/api/security/image-export",
                {"name": Path(path).name, "sha256": hashlib.sha256(content).hexdigest(),
                 "size_bytes": len(content)}, authorized)


class Preferences(QObject):
    changed = Signal()
    defaults = {"theme": "light", "density": "comfortable", "animations": True,
                "start_page": 0, "remember_page": True, "last_page": 0,
                "auto_ndd": True, "notification_duration": 3000, "notification_sound": False,
                "ndd_zero": True, "point_labels": False,
                "report_policy": "manual", "source_path": "", "login_username": "",
                "depth_levels": [30, 50], "depth_colors": ["#79b98c", "#e5a83b", "#df4b45"]}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = USER_DATA / "native-preferences.json"
        self.values = dict(self.defaults)
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self.values = self.validated(data)
        except (OSError, ValueError):
            pass

    def save(self, **changes):
        values = self.validated({**self.values, **{k: v for k, v in changes.items() if k in self.defaults}})
        if values == self.values and self.path.is_file():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        output = QSaveFile(str(self.path))
        raw = json.dumps(values, ensure_ascii=False, indent=2).encode("utf-8")
        if not output.open(QIODevice.OpenModeFlag.WriteOnly):
            raise OSError(output.errorString())
        if output.write(raw) != len(raw) or not output.commit():
            raise OSError(output.errorString())
        self.values = values
        self.changed.emit()

    @classmethod
    def validated(cls, data):
        values = {key: list(value) if isinstance(value, list) else value for key, value in cls.defaults.items()}
        options = {"theme": ("light", "dark", "system"), "density": ("comfortable", "compact"),
                   "report_policy": ("manual", "latest")}
        for key, choices in options.items():
            if data.get(key) in choices:
                values[key] = data[key]
        for key in ("animations", "remember_page", "auto_ndd", "notification_sound", "ndd_zero", "point_labels"):
            if isinstance(data.get(key), bool):
                values[key] = data[key]
        if type(data.get("notification_duration")) is int and data["notification_duration"] in (0, 3000, 5000):
            values["notification_duration"] = data["notification_duration"]
        for key in ("start_page", "last_page"):
            if type(data.get(key)) is int and 0 <= data[key] <= 4:
                values[key] = data[key]
        if isinstance(data.get("source_path"), str):
            values["source_path"] = data["source_path"]
        if isinstance(data.get("login_username"), str) and re.fullmatch(r"[A-Za-z0-9_.-]{0,64}", data["login_username"]):
            values["login_username"] = data["login_username"]
        levels, colors = data.get("depth_levels"), data.get("depth_colors")
        if (isinstance(levels, list) and len(levels) in (2, 3)
                and all(type(value) is int and 0 < value <= 100 for value in levels)
                and sorted(set(levels)) == levels
                and isinstance(colors, list) and len(colors) == len(levels) + 1
                and all(isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value) for value in colors)):
            values.update(depth_levels=list(levels), depth_colors=list(colors))
        return values


class WorkspaceContext(QObject):
    scopeChanged = Signal(dict)
    selectionChanged = Signal(list)
    dataChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scope = {}
        self.selected = {}
        self.preferences = Preferences(self)

    def set_scope(self, scope):
        scope = {key: str(scope.get(key) or "") for key in ("site", "unit", "outage", "thimble")}
        scope["site"] = canonical_site(scope["site"])
        if not scope["thimble"].isdigit() or not 1 <= int(scope["thimble"]) <= 50:
            scope["thimble"] = ""
        if scope != self.scope:
            self.scope = scope
            self.scopeChanged.emit(dict(scope))

    def selection(self, rows):
        self.selected = {row["id"]: row for row in rows if row.get("id") is not None}
        self.selectionChanged.emit(list(self.selected.values()))


class ScopeBar(QWidget):
    changed = Signal(dict)
    loaded = Signal(dict)

    def __init__(self, client, parent=None, *, allow_all=True, stacked=False):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.client = client
        self.allow_all = allow_all
        self.combinations = []
        self.extra_combinations = []
        self._overview_combinations = []
        self._requested_scope = {}
        self._loaded_once = False
        self.site, self.unit, self.outage = QComboBox(), QComboBox(), QComboBox()
        self.site.setMinimumWidth(135)
        self.unit.setMinimumWidth(110)
        self.outage.setMinimumWidth(145)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for text, control in (("基地", self.site), ("机组", self.unit), ("大修", self.outage)):
            if stacked:
                from PySide6.QtWidgets import QVBoxLayout
                field = QWidget()
                field_layout = QVBoxLayout(field)
                field_layout.setContentsMargins(0, 0, 0, 0)
                field_layout.setSpacing(5)
                field_layout.addWidget(QLabel(text))
                field_layout.addWidget(control)
                layout.addWidget(field, 1)
            else:
                layout.addWidget(QLabel(text))
                layout.addWidget(control)
        self.reset = button("清除筛选", "rotate-ccw", self.clear)
        self.refresh = button("刷新数据", "refresh-cw", self.reload)
        if stacked:
            self.setObjectName("filterBand")
            layout.setContentsMargins(12, 10, 12, 10)
            layout.setAlignment(Qt.AlignmentFlag.AlignBottom)
            for control, text in ((self.reset, "清除筛选"), (self.refresh, "刷新数据")):
                control.setText("")
                control.setToolTip(text)
        layout.addWidget(self.reset)
        layout.addWidget(self.refresh)
        layout.addStretch()
        self.site.currentIndexChanged.connect(self._site_changed)
        self.unit.currentIndexChanged.connect(self._unit_changed)
        self.outage.currentIndexChanged.connect(self._emit)
        self.reload()

    def reload(self):
        self.client.get("/api/overview", self._loaded)

    def _loaded(self, data, error):
        if error or not data:
            self.setToolTip(error or "范围读取失败")
            return
        previous = self._requested_scope or self.values()
        self._overview_combinations = data.get("combinations") or []
        self.combinations = list(self._overview_combinations)
        for row in self.extra_combinations:
            if row not in self.combinations:
                self.combinations.append(row)
        self._loaded_once = True
        self.site.blockSignals(True)
        self.site.clear()
        self.site.addItem("全部基地", "")
        for site in sorted({canonical_site(row["site"]) for row in self.combinations}):
            self.site.addItem(SITE_NAMES.get(site, site), site)
        self.site.blockSignals(False)
        self.set_scope(previous, force=True)
        self.loaded.emit(self.values())

    def set_extra_combinations(self, rows):
        self.extra_combinations = list(rows)
        self._loaded({"combinations": self._overview_combinations}, None)

    def values(self):
        if not self._loaded_once and self._requested_scope:
            return dict(self._requested_scope)
        return {"site": self.site.currentData() or "", "unit": self.unit.currentData() or "",
                "outage": self.outage.currentData() or ""}

    def _fill_units(self):
        previous = self.unit.currentData()
        self.unit.blockSignals(True)
        self.unit.clear()
        self.unit.addItem("全部机组", "")
        for unit in sorted({int(row["unit_id"]) for row in self.combinations
                            if not self.site.currentData() or canonical_site(row["site"]) == self.site.currentData()}):
            self.unit.addItem(f"{unit}号机组", str(unit))
        self.unit.setCurrentIndex(max(0, self.unit.findData(previous)))
        self.unit.blockSignals(False)

    def _fill_outages(self):
        previous = self.outage.currentData()
        self.outage.blockSignals(True)
        self.outage.clear()
        self.outage.addItem("全部大修", "")
        for outage in sorted({row["outage"] for row in self.combinations
                              if (not self.site.currentData() or canonical_site(row["site"]) == self.site.currentData())
                              and (not self.unit.currentData() or str(row["unit_id"]) == self.unit.currentData())},
                             reverse=True):
            self.outage.addItem(outage, outage)
        self.outage.setCurrentIndex(max(0, self.outage.findData(previous)))
        self.outage.blockSignals(False)

    def _site_changed(self):
        self._fill_units()
        self._fill_outages()
        self._emit()

    def _unit_changed(self):
        self._fill_outages()
        self._emit()

    def _emit(self, *_):
        self._requested_scope = self.values()
        self.changed.emit(self.values())

    def set_scope(self, scope, *, force=False):
        requested = {"site": canonical_site(scope.get("site")),
                     "unit": str(scope.get("unit") or ""), "outage": scope.get("outage") or ""}
        if not force and self._loaded_once and requested == self.values():
            self._requested_scope = requested
            return
        self._requested_scope = requested
        self.site.blockSignals(True)
        self.site.setCurrentIndex(max(0, self.site.findData(canonical_site(scope.get("site")))))
        self.site.blockSignals(False)
        self._fill_units()
        self.unit.blockSignals(True)
        self.unit.setCurrentIndex(max(0, self.unit.findData(str(scope.get("unit") or ""))))
        self.unit.blockSignals(False)
        self._fill_outages()
        self.outage.blockSignals(True)
        self.outage.setCurrentIndex(max(0, self.outage.findData(scope.get("outage") or "")))
        self.outage.blockSignals(False)

    def clear(self):
        self.set_scope({})
        self._emit()


class AnalyticsScopeBar(ScopeBar):
    """Keep cross-site unit identities distinct while sharing workspace scopes."""
    def __init__(self, client, parent=None):
        self.selected_sites = set()
        super().__init__(client, parent)
        self.site.hide()
        for label in self.findChildren(QLabel):
            if label.text() == "基地":
                label.hide()

    def _loaded(self, data, error):
        if error or not data:
            self.setToolTip(error or "范围读取失败")
            return
        previous = self._requested_scope or self.values()
        self._overview_combinations = data.get("combinations") or []
        self.combinations = list(self._overview_combinations)
        self._loaded_once = True
        self.site.blockSignals(True)
        self.site.clear()
        self.site.addItem("全部基地", "")
        for site in sorted({canonical_site(row["site"]) for row in self.combinations}):
            self.site.addItem(SITE_NAMES.get(site, site), site)
        self.site.blockSignals(False)
        self.set_scope(previous, force=True, keep_sites=True)
        self.loaded.emit(self.values())

    def _available_rows(self):
        return [row for row in self.combinations
                if not self.selected_sites or canonical_site(row["site"]) in self.selected_sites]

    def _fill_units(self):
        previous = self.unit.currentData()
        self.unit.blockSignals(True)
        self.unit.clear()
        self.unit.addItem("全部机组", "")
        codes = {(canonical_site(row["site"]), int(row["unit_id"])) for row in self._available_rows()}
        for site, number in sorted(codes):
            code = f"{site}{number}"
            self.unit.addItem(f"{code}号机组", code)
        self.unit.setCurrentIndex(max(0, self.unit.findData(previous)))
        self.unit.blockSignals(False)

    def _fill_outages(self):
        previous = self.outage.currentData()
        code = self.unit.currentData()
        self.outage.blockSignals(True)
        self.outage.clear()
        self.outage.addItem("全部大修", "")
        rows = [row for row in self._available_rows()
                if not code or f"{canonical_site(row['site'])}{int(row['unit_id'])}" == code]
        for outage in sorted({row["outage"] for row in rows}, reverse=True):
            self.outage.addItem(outage, outage)
        self.outage.setCurrentIndex(max(0, self.outage.findData(previous)))
        self.outage.blockSignals(False)

    def values(self):
        code = self.unit.currentData() or ""
        match = re.fullmatch(r"([A-Z]+)(\d+)", code)
        site = match[1] if match else next(iter(self.selected_sites)) if len(self.selected_sites) == 1 else ""
        return {"site": site, "unit": match[2] if match else "", "outage": self.outage.currentData() or ""}

    def set_sites(self, sites):
        self.selected_sites = set(sites)
        self.set_scope({}, keep_sites=True)
        self._emit()

    def set_scope(self, scope, *, force=False, keep_sites=False):
        site = canonical_site(scope.get("site"))
        if not keep_sites:
            self.selected_sites = {site} if site else set()
        self.site.blockSignals(True)
        single = next(iter(self.selected_sites)) if len(self.selected_sites) == 1 else ""
        self.site.setCurrentIndex(max(0, self.site.findData(single)))
        self.site.blockSignals(False)
        self._fill_units()
        self.unit.blockSignals(True)
        code = f"{site}{scope.get('unit')}" if site and scope.get("unit") else ""
        self.unit.setCurrentIndex(max(0, self.unit.findData(code)))
        self.unit.blockSignals(False)
        self._fill_outages()
        self.outage.blockSignals(True)
        self.outage.setCurrentIndex(max(0, self.outage.findData(scope.get("outage") or "")))
        self.outage.blockSignals(False)
        self._requested_scope = self.values()

    def _site_changed(self):
        self.selected_sites = {self.site.currentData()} if self.site.currentData() else set()
        super()._site_changed()

    def clear(self):
        self.set_sites(set())


class PlateMap(QWidget):
    tubeClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        path = UI_DIR / "visualizations" / "reference-thimble" / "data" / "vessel_layout.json"
        self.channels = json.loads(path.read_text(encoding="utf-8"))["channels"]
        self.unit = 1
        self.rows = {}
        self.selected = set()
        self.mode = "depth"
        self.hit_regions = {}
        self.levels = [20, 40, 60]
        self.colors = ["#39a78e", "#edbd50", "#df8252", "#c64e53"]
        self.setMinimumSize(280, 280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

    def set_data(self, rows, unit=1, selected=(), mode="depth"):
        self.unit, self.mode = int(unit or 1), mode
        self.rows = {}
        for row in rows:
            tube = int(row.get("tube") or row.get("thimble_id") or 0)
            previous = self.rows.get(tube)
            if previous is None or (row.get("max_percent") or row.get("percent") or 0) > (
                    previous.get("max_percent") or previous.get("percent") or 0):
                self.rows[tube] = row
        self.selected = set(selected)
        self.update()

    def _color(self, row):
        if not row:
            return QColor("#e1e7eb")
        if self.mode == "history_replaced":
            return QColor("#b28a22" if row.get("history_count") else "#e1e7eb")
        if self.mode == "state":
            if row.get("state_recorded") in (0, False) or row.get("recorded") in (0, False):
                return QColor("#e1e7eb")
            return QColor({"plugged": "#c64e53", "shifted": "#e0ad36", "replaced": "#5c91ce",
                           "normal": "#39a78e"}.get(row.get("state"), "#e1e7eb"))
        if self.mode == "coverage":
            return QColor({"defect": "#c64e53", "NDD": "#39a78e", "ndd": "#39a78e",
                           "incomplete": "#e0ad36", "missing": "#e1e7eb"}.get(
                row.get("coverage") or row.get("category"), "#39a78e"))
        depth = row.get("max_percent", row.get("percent"))
        if depth is None:
            return QColor("#8da3ad" if row.get("records") else "#e1e7eb")
        return QColor(self.colors[sum(float(depth) >= level for level in self.levels)])

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height()) - 38
        left, top = (self.width() - side) / 2, (self.height() - side) / 2
        painter.setPen(QPen(QColor("#aab9c3"), 1))
        painter.setBrush(QColor("#fafcfd"))
        painter.drawEllipse(QRectF(left, top, side, side))
        self.hit_regions = {}
        diameter = max(13, min(25, side / 17))
        for channel in self.channels:
            tube = int(channel["serialOdd" if self.unit % 2 else "serialEven"])
            x = left + side / 2 + channel["x"] / 3500 * side
            y = top + side / 2 - channel["z"] / 3500 * side
            rect = QRectF(x - diameter / 2, y - diameter / 2, diameter, diameter)
            self.hit_regions[tube] = rect
            painter.setBrush(self._color(self.rows.get(tube)))
            painter.setPen(QPen(QColor("#087f87" if tube in self.selected else "#78909c"),
                                3 if tube in self.selected else 1))
            painter.drawEllipse(rect)
            painter.setPen(QColor("#233b46"))
            font = painter.font()
            font.setPixelSize(10)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(tube))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            for tube, rect in self.hit_regions.items():
                if rect.contains(event.position()):
                    self.selected = {tube}
                    self.update()
                    self.tubeClicked.emit(tube)
                    return

    def mouseMoveEvent(self, event):
        for tube, rect in self.hit_regions.items():
            if rect.contains(event.position()):
                row = self.rows.get(tube) or {}
                channel = next(c for c in self.channels if int(c[
                    "serialOdd" if self.unit % 2 else "serialEven"]) == tube)
                QToolTip.showText(event.globalPosition().toPoint(),
                                 f"{tube}号管 · {channel['pos']}\n"
                                 f"最大磨损：{row.get('max_percent', row.get('percent', '/'))}\n"
                                 + (f"所选 {row.get('history_outages', 0)} 轮明确换管：{row.get('history_count', 0)} 次"
                                    if self.mode.startswith("history_") else
                                    f"维护：{row.get('state_label') or STATE_NAMES.get(row.get('state'), '未记录')}"), self)
                return
        QToolTip.hideText()


class TubeStateGrid(PlateMap):
    """Fifty maintenance selectors in the same ten-column order as TRAE."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.multiselect = False
        self._drag_value = None
        self._drag_last = None
        self.setMinimumSize(400, 320)

    def mousePressEvent(self, event):
        if self.multiselect and event.button() == Qt.MouseButton.LeftButton:
            for tube, rect in self.hit_regions.items():
                if rect.contains(event.position()):
                    self._drag_value = tube not in self.selected
                    self._drag_last = tube
                    self.selected.symmetric_difference_update({tube})
                    self.update()
                    self.tubeClicked.emit(tube)
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        for tube, rect in self.hit_regions.items():
            if not rect.contains(event.position()):
                continue
            if self.multiselect and self._drag_value is not None and event.buttons() & Qt.MouseButton.LeftButton:
                if tube != self._drag_last:
                    self._drag_last = tube
                    if self._drag_value:
                        self.selected.add(tube)
                    else:
                        self.selected.discard(tube)
                    self.update()
                    self.tubeClicked.emit(tube)
                return
            row = self.rows.get(tube) or {}
            events = row.get("events") or row.get("current_events") or [row.get("state")]
            label = row.get("state_label") or " · ".join(STATE_NAMES.get(code, "") for code in events)
            detail = f"{tube:02}号管 · {label or '未维护'}"
            if "shifted" in events:
                distance = row.get("offset_mm", row.get("maintenance_offset_mm"))
                unsigned = row.get("unsigned_offset_mm", row.get("maintenance_unsigned_offset_mm"))
                detail += (f"\n移位距离：{float(distance):+g} mm" if distance is not None else
                           f"\n移位距离：{unsigned} mm（方向待核对）" if unsigned is not None else "\n移位距离待核对")
            QToolTip.showText(event.globalPosition().toPoint(), detail, self)
            return
        QToolTip.hideText()

    def mouseReleaseEvent(self, event):
        self._drag_value = self._drag_last = None
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.hit_regions = {}
        gap = 8
        width = (self.width() - gap * 11) / 10
        height = min(64, (self.height() - gap * 6) / 5)
        dark = self.palette().color(QPalette.ColorRole.WindowText).lightness() > 128
        for tube in range(1, 51):
            row = self.rows.get(tube) or {}
            recorded = bool(row) and row.get("state_recorded", row.get("recorded", True)) not in (False, 0)
            rect = QRectF(gap + (tube - 1) % 10 * (width + gap),
                          gap + (tube - 1) // 10 * (height + gap), width, height)
            self.hit_regions[tube] = rect
            names = row.get("events") or row.get("current_events") or [row.get("state", "normal")]
            active = [code for code in ("plugged", "shifted", "replaced") if code in names] if recorded else []
            colors = [STATE_PALETTE[code] for code in active] or [STATE_PALETTE["normal" if recorded else "missing"]]
            clip = QPainterPath()
            clip.addRoundedRect(rect, 5, 5)
            painter.save()
            painter.setClipPath(clip)
            for index, (fill, _edge, _ink) in enumerate(colors):
                color = QColor(fill)
                if dark:
                    color.setAlpha(42)
                painter.fillRect(QRectF(rect.x() + index * width / len(colors), rect.y(),
                                        width / len(colors), height), color)
            painter.restore()
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#087d79" if tube in self.selected else colors[0][1]),
                                2 if tube in self.selected else 1,
                                Qt.PenStyle.SolidLine if recorded else Qt.PenStyle.DashLine))
            painter.drawRoundedRect(rect, 5, 5)
            painter.setPen(self.palette().color(QPalette.ColorRole.WindowText) if dark else QColor(colors[0][2]))
            font = painter.font()
            font.setPixelSize(13)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(QRectF(rect.x(), rect.y() + 6, width, height / 2 - 3),
                             Qt.AlignmentFlag.AlignCenter, f"{tube:02}")
            font.setPixelSize(10)
            font.setBold(False)
            painter.setFont(font)
            label = row.get("state_label") or ("复合处理" if len(names) > 1 else STATE_NAMES.get(row.get("state"), "正常"))
            if len(label) > 6:
                label = "复合处理" if not row.get("needs_review") else "待核对"
            painter.drawText(QRectF(rect.x(), rect.y() + height / 2, width, height / 2 - 4),
                             Qt.AlignmentFlag.AlignCenter, label if recorded else "未维护")


class PositionHeatmap(QWidget):
    positionClicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.counts = {}
        self.hit_regions = {}
        self.setMinimumSize(300, 320)
        self.setMouseTracking(True)

    def set_counts(self, counts):
        self.counts = dict(counts)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cell = min((self.width() - 42) / 15, (self.height() - 38) / 15)
        left, top = (self.width() - cell * 15) / 2 + 10, 28
        columns = "RPNMLKJHGFEDCBA"
        widths = (3, 7, 9, 11, 13, 13, 15, 15, 15, 13, 13, 11, 9, 7, 3)
        font = painter.font()
        font.setPixelSize(11)
        painter.setFont(font)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        self.hit_regions = {}
        peak = max(self.counts.values(), default=1) or 1
        for column, label in enumerate(columns):
            painter.setPen(QColor("#48647a"))
            painter.drawText(QRectF(left + column * cell, 3, cell, 20), Qt.AlignmentFlag.AlignCenter, label)
        for row, width in enumerate(widths):
            painter.setPen(QColor("#48647a"))
            painter.drawText(QRectF(left - 27, top + row * cell, 24, cell), Qt.AlignmentFlag.AlignCenter, f"{row + 1:02}")
            for column in range((15 - width) // 2, (15 + width) // 2):
                position = f"{columns[column]}{row + 1}"
                count = self.counts.get(position, 0)
                rect = QRectF(left + column * cell, top + row * cell, cell, cell)
                color = QColor("#ffffff")
                if count:
                    color = QColor.fromHsvF(.035, .18 + .62 * count / peak, 1 - .22 * count / peak)
                painter.setBrush(color)
                painter.setPen(QPen(QColor("#d6e2e7"), 1))
                painter.drawRect(rect)
                if count:
                    painter.setPen(QColor("#ffffff" if count / peak > .65 else "#263842"))
                    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(count))
                self.hit_regions[position] = rect

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            for position, rect in self.hit_regions.items():
                if rect.contains(event.position()):
                    self.positionClicked.emit(position)
                    return

    def mouseMoveEvent(self, event):
        for position, rect in self.hit_regions.items():
            if rect.contains(event.position()):
                QToolTip.showText(event.globalPosition().toPoint(), f"{position} · 超阈 {self.counts.get(position, 0)} 次", self)
                return
        QToolTip.hideText()


class ReferencePlateMap(PlateMap):
    """The drawing's 15-row grid, with odd/even channel numbers in each circle."""
    unitChanged = Signal(int)
    interactionRejected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parity = "both"
        self.parity_rows = {1: {}, 0: {}}
        self.theme = "light"
        self.selection_ready = True
        self.allow_parity_switch = True
        self.setMinimumSize(0, 0)

    def set_theme(self, theme):
        self.theme = theme
        self.update()

    def grid_rect(self):
        border = 1 if self.theme == "dark" else 0
        side = max(0, self.width() - 136 - 2 * border)
        return QRectF(68 + border, 52 + border, side, side)

    def set_records(self, rows, unit=1, selected=()):
        self.unit = int(unit or 1)
        self.selected = set(selected)
        self.parity_rows = {1: {}, 0: {}}
        for row in rows:
            parity = int(row.get("unit_id") or self.unit) % 2
            tube = int(row.get("thimble_id") or 0)
            previous = self.parity_rows[parity].get(tube)
            effective = str(row.get("display_conclusion") or row.get("indication") or "").upper() != "NDD" and row.get("detection_status") != "ndd"
            if effective and (previous is None or (row.get("percent") or 0) > (previous.get("percent") or 0)):
                self.parity_rows[parity][tube] = row
        self.update()

    def _record_color(self, parity, tube):
        row = self.parity_rows[parity].get(tube)
        return self._color(row) if row and (row.get("percent") or 0) > 0 else QColor("#ffffff")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dark = self.theme == "dark"
        if dark:
            painter.setPen(QPen(QColor("#405657"), 1))
            painter.setBrush(QColor("#182123"))
            painter.drawRoundedRect(QRectF(.5, .5, self.width() - 1, self.height() - 1), 8, 8)
        else:
            painter.fillRect(self.rect(), QColor("#ffffff"))
        grid = self.grid_rect()
        left, top, cell = grid.left(), grid.top(), grid.width() / 15
        if cell <= 0:
            return
        columns = "RPNMLKJHGFEDCBA"
        widths = (3, 7, 9, 11, 13, 13, 15, 15, 15, 13, 13, 11, 9, 7, 3)
        font = painter.font()
        font.setPixelSize(10)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QPen(QColor("#607475" if dark else "#9aa5ad"), 1))
        painter.setBrush(QColor("#233032" if dark else "#ffffff"))
        for row, width in enumerate(widths):
            for column in range((15 - width) // 2, (15 + width) // 2):
                painter.drawRect(QRectF(left + column * cell + .5, top + row * cell + .5,
                                        max(0, cell - 1), max(0, cell - 1)))
        painter.setPen(QColor("#d5e2df" if dark else "#52616c"))
        for column, label in enumerate(columns):
            painter.drawText(QRectF(left + column * cell, top - 18, cell, 15.5),
                             Qt.AlignmentFlag.AlignCenter, label)
        for row in range(15):
            painter.drawText(QRectF(left - 18, top + row * cell, 15, cell),
                             Qt.AlignmentFlag.AlignCenter, f"{row + 1:02}")
        self.hit_regions = {}
        diameter = min(30, grid.width() * .062)
        font.setPointSizeF(max(6, min(10, grid.width() * .019)) * 72 / self.logicalDpiY())
        font.setWeight(QFont.Weight.ExtraBold)
        painter.setFont(font)
        for channel in self.channels:
            match = re.fullmatch(r"([A-Z])(\d+)", channel["pos"])
            x = left + (columns.index(match[1]) + .5) * cell
            y = top + (int(match[2]) - .5) * cell
            rect = QRectF(x - diameter / 2, y - diameter / 2, diameter, diameter)
            odd, even = int(channel["serialOdd"]), int(channel["serialEven"])
            has_severity = any((self.parity_rows[p].get(tube) or {}).get("percent", 0)
                               for p, tube in ((1, odd), (0, even))
                               if self.parity == "both" or p == (1 if self.parity == "odd" else 0))
            def color(parity, tube):
                return QColor("#334446") if dark and not has_severity else self._record_color(parity, tube)
            painter.setPen(Qt.PenStyle.NoPen)
            if self.parity == "both":
                painter.setBrush(color(1, odd))
                painter.drawPie(rect, 90 * 16, 180 * 16)
                painter.setBrush(color(0, even))
                painter.drawPie(rect, -90 * 16, 180 * 16)
            else:
                parity = 1 if self.parity == "odd" else 0
                painter.setBrush(color(parity, odd if parity else even))
                painter.drawEllipse(rect)
            active = odd if self.unit % 2 else even
            focused = active in self.selected
            if focused:
                painter.setPen(QPen(QColor("#168c87"), 1))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(rect.adjusted(-2, -2, 2, 2))
            painter.setPen(QPen(QColor("#9cb4b0" if dark else "#344b58"), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(rect)
            painter.setPen(QColor("#edf6f4" if dark and not has_severity else "#26343c"))
            if self.parity == "both":
                painter.save()
                painter.setPen(QPen(QColor("#34434c"), 1))
                painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
                painter.restore()
                painter.drawText(QRectF(rect.left(), rect.top(), diameter / 2, diameter),
                                 Qt.AlignmentFlag.AlignCenter, str(odd))
                painter.drawText(QRectF(x, rect.top(), diameter / 2, diameter),
                                 Qt.AlignmentFlag.AlignCenter, str(even))
            else:
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(odd if self.parity == "odd" else even))
            self.hit_regions[(odd, even)] = rect
        flow_color = QColor("#d5e2df" if dark else "#263a43")
        arrow_color = QColor("#c0d1cd" if dark else "#263a43")
        font.setPixelSize(11)
        painter.setFont(font)
        painter.setPen(flow_color)
        for label, rect in (("180°", QRectF(left, top - 42, cell * 15, 17)),
                            ("0°", QRectF(left, top + cell * 15 + 17, cell * 15, 17)),
                            ("90°", QRectF(left - 64, top + 7 * cell + 13, 46, 15.5)),
                            ("270°", QRectF(left + 15 * cell + 17, top + 7 * cell + 13, 46, 15.5)),
                            ("OUTLET", QRectF(left + 15 * cell, top + 7 * cell - 20, 64, 15.5)),
                            ("INLET", QRectF(left + 15 * cell * .87 - 10, top - 4, 40, 15.5))):
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

        def arrow(x1, y1, x2, y2):
            import math
            angle = math.atan2(y2 - y1, x2 - x1)
            painter.setPen(QPen(arrow_color, 2))
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            painter.setBrush(arrow_color)
            painter.drawPolygon(QPolygonF([QPointF(x2, y2),
                QPointF(x2 - 7 * math.cos(angle - .45), y2 - 7 * math.sin(angle - .45)),
                QPointF(x2 - 7 * math.cos(angle + .45), y2 - 7 * math.sin(angle + .45))]))
        arrow(left - 64, top + 7 * cell, left - 18, top + 7 * cell)
        arrow(left + 15 * cell + 17, top + 7 * cell, left + 15 * cell + 63, top + 7 * cell)
        import math
        for x, y, angle in ((left + grid.width() * .13 + 27, top + 17, -126),
                             (left + grid.width() * .87 - 27, top + 17, 124),
                             (left + grid.width() * .13 + 27, grid.bottom() - 17, 110),
                             (left + grid.width() * .87 - 27, grid.bottom() - 17, -117)):
            dx, dy = math.cos(math.radians(angle)) * 17, math.sin(math.radians(angle)) * 17
            arrow(x - dx, y - dy, x + dx, y + dy)

    def _hit(self, point):
        for (odd, even), rect in self.hit_regions.items():
            if rect.contains(point):
                parity = (1 if point.x() < rect.center().x() else 0) if self.parity == "both" else (
                    1 if self.parity == "odd" else 0)
                return odd if parity else even, parity, odd, even
        return None

    def mousePressEvent(self, event):
        hit = self._hit(event.position())
        if hit and event.button() == Qt.MouseButton.LeftButton:
            tube, parity, _, _ = hit
            if not self.selection_ready:
                self.interactionRejected.emit("请先筛选机组或勾选同一机组、同一次大修的数据")
                return
            if self.unit % 2 != parity:
                if not self.allow_parity_switch:
                    self.interactionRejected.emit("当前机组奇偶与所选管板不匹配")
                    return
                self.unit = 1 if parity else 2
                self.unitChanged.emit(self.unit)
            self.selected = {tube}
            self.update()
            self.tubeClicked.emit(tube)

    def mouseMoveEvent(self, event):
        hit = self._hit(event.position())
        if hit:
            tube, parity, odd, even = hit
            channel = next(c for c in self.channels if int(c["serialOdd"]) == odd)
            row = self.parity_rows[parity].get(tube) or {}
            QToolTip.showText(event.globalPosition().toPoint(),
                             f"{channel['pos']} · 奇数 {odd} / 偶数 {even}\n"
                             f"当前 {tube}号管 · 最大磨损 {row.get('percent', '/')}%", self)
        else:
            QToolTip.hideText()


def workspace_styles(theme="light", density="comfortable"):
    dark = theme == "dark"
    bg, surface, text, line, muted = (
        ("#111719", "#1c2527", "#e5eeec", "#3b4c4d", "#a8b8b5") if dark else
        ("#f3f6f7", "#ffffff", "#23465b", "#d4e0e6", "#647c8c"))
    accent = "#3fb3a6" if dark else "#087d79"
    accent_soft = "#1b3234" if dark else "#e9f5f4"
    control = "#2b393b" if dark else "#f8fafb"
    hover = "#283737" if dark else "#f2f8fa"
    selected = "#22404a" if dark else "#e9f5f4"
    table_zebra = "#1d2629" if dark else "#fafcfd"
    height = 28 if density == "compact" else 34
    return f"""
        QWidget {{ color:{text}; font-family:"Microsoft YaHei","Microsoft YaHei UI","Segoe UI",sans-serif; font-size:12px; }}
        QMainWindow, QDialog, QWidget#appRoot, QWidget#workspaceBody {{ background:{bg}; }}
        QDialog#reportChoiceDialog {{ background:{surface}; border:1px solid {line}; }}
        QLabel#reportChoiceTitle {{ font-size:18px; font-weight:600; }}
        QWidget#reportChoiceOptions, QWidget#reportChoiceOverview {{ background:{surface}; }}
        QWidget#reportCandidate {{ background:{surface}; border-bottom:1px solid {line}; }}
        QWidget#reportCandidate[selected="true"] {{ background:{accent_soft}; border-left:3px solid {accent}; }}
        QLabel#reportAnalystHeading {{ color:{muted}; font-size:11px; font-weight:600; }}
        QScrollArea#reportSelectionSummary {{ background:{surface}; border:1px solid {line}; border-radius:6px; }}
        QWidget#reportSummaryBody {{ background:{surface}; }}
        QWidget#reportSummaryRow {{ background:{surface}; border-bottom:1px solid {line}; }}
        QLabel#reportSummaryGroup {{ font-size:11px; font-weight:600; }}
        QLabel#reportSummaryAnalyst {{ padding:2px 7px; border:1px solid transparent;
            border-radius:3px; font-size:10px; font-weight:700; }}
        QLabel#reportSummaryAnalyst[tone="0"] {{ color:#075e58; background:#d9f0ec; border-color:#a7d8cf; }}
        QLabel#reportSummaryAnalyst[tone="1"] {{ color:#245b91; background:#e1edf8; border-color:#bfd4eb; }}
        QLabel#reportSummaryAnalyst[tone="2"] {{ color:#7a5700; background:#f9edc8; border-color:#ead797; }}
        QLabel#reportSummaryAnalyst[tone="3"] {{ color:#9a4634; background:#fae5dc; border-color:#efc4b2; }}
        QLabel#reportSummaryAnalyst[tone="4"] {{ color:#4d6631; background:#e7efd9; border-color:#ceddb7; }}
        QLabel#reportSummaryAnalyst[tone="5"] {{ color:#556374; background:#e7edf2; border-color:#cfd8e0; }}
        QLabel#reportSummaryAnalyst[tone="unlisted"] {{ color:#6c777d; background:#edf0f1; border-color:#d9dfe1; }}
        QLabel#reportSummarySource {{ color:{muted}; font-size:10px; }}
        QLabel#reportCandidateName {{ font-size:13px; font-weight:600; }}
        QLabel#reportCandidateSource {{ color:{muted}; font-size:10px; }}
        QLabel#reportChoiceWarning {{ color:{"#e2bd75" if dark else "#926824"}; font-size:11px; }}
        QToolButton#reportGroupChoice {{ border:1px solid {line}; background:{control}; border-radius:4px;
            padding:0; min-width:0; min-height:0; }}
        QToolButton#reportGroupChoice[confirmed="true"] {{ background:{accent_soft}; color:{accent}; }}
        QToolButton#reportGroupChoice[current="true"] {{ border:2px solid {accent}; }}
        QScrollArea {{ background:{bg}; border:0; }}
        QWidget#topNavigation {{ background:{"#182123" if dark else "#ffffff"};
            border-bottom:1px solid {"#3b4c4d" if dark else "#dce4e9"}; }}
        QWidget#navigationFooter {{ background:{"#182123" if dark else "#ffffff"};
            border-left:1px solid {"#3b4c4d" if dark else "#e1e7eb"}; }}
        QPushButton#navigationUtility {{ background:transparent; border:0; border-radius:4px; padding:4px;
            min-width:0; min-height:0; }}
        QPushButton#navigationUtility:hover {{ background:{hover}; }}
        QLabel#connectionStatus {{ font-size:9px; color:#97a5ac; }}
        QWidget#onlineDot {{ border:0; border-radius:3px; background:#33946c; }}
        QWidget#connectionDot {{ border:0; border-radius:3px; background:#269773; }}
        QPushButton#accountIdentity {{ background:transparent; border:0;
            border-right:1px solid {"#455560" if dark else "#dce5e9"};
            border-radius:0; padding:0; min-height:34px; text-align:left; }}
        QPushButton#accountIdentity:hover {{ background:{hover}; }}
        QLabel#accountAvatar {{ background:{"#203b3a" if dark else "#e9f5f3"}; color:{"#9be0d3" if dark else "#b0bdc1"};
            border:1px solid {"#32625e" if dark else "#c5e2df"}; border-radius:14px;
            font-size:11px; font-weight:700; }}
        QLabel#accountName {{ color:{"#e5eeec" if dark else "#31566b"}; font-size:12px; font-weight:700; }}
        QLabel#accountStatus {{ color:{muted}; font-size:10px; }}
        QPushButton#siteCoverage {{ background:{control}; border:1px solid transparent;
            padding:0; min-height:32px; border-radius:4px; }}
        QPushButton#siteCoverage:checked {{ background:{accent_soft}; border-color:{accent}; }}
        QLabel#siteName {{ font-size:11px; font-weight:600; }}
        QLabel#siteDetail {{ color:{muted}; font-size:10px; }}
        QLabel#siteCoverageValue {{ color:{accent}; font-size:19px; font-weight:700; }}
        QWidget#unitSiteGroup {{ background:{surface}; border:1px solid {line}; border-radius:5px; }}
        QWidget#unitSiteHeading {{ background:{accent_soft}; }}
        QWidget#unitRow {{ border-top:1px solid {line}; }}
        QLabel#unitName {{ font-weight:600; }}
        QLabel#unitDepth {{ font-size:18px; font-weight:700; }}
        QLabel#unitCoverage {{ color:{accent}; font-size:16px; font-weight:600; }}
        QWidget#historyMetrics {{ border-bottom:1px solid {line}; }}
        QLabel#historyMetricValue {{ color:{accent}; font-size:24px; font-weight:600; }}
        QLabel#historyOutage {{ font-weight:600; min-width:55px; }}
        QLabel#historyDepth {{ color:{accent}; font-size:17px; font-weight:600; }}
        QLabel[historyBadge] {{ padding:2px 5px; border-radius:4px;
            color:{"#c9d4dd" if dark else "#5b6b73"}; background:{"#2c3540" if dark else "#e8eef2"}; }}
        QLabel[historyBadge="war"] {{ color:{"#ffd08a" if dark else "#b35a00"};
            background:{"#3d2e12" if dark else "#fff3e0"}; }}
        QLabel[historyBadge="plugged"] {{ color:{"#ffb3ad" if dark else "#b3261e"};
            background:{"#3d1f1f" if dark else "#fde8e8"}; }}
        QLabel[historyBadge="shifted"] {{ color:{"#90caf9" if dark else "#0d47a1"};
            background:{"#1e2f4a" if dark else "#e3f2fd"}; }}
        QLabel[historyBadge="replaced"], QLabel[historyBadge="normal"] {{
            color:{"#a5d6a7" if dark else "#1f6b4a"}; background:{"#1c3a2b" if dark else "#e8f5ee"}; }}
        QWidget#historyRoundBody {{ background:{surface}; border-left:2px solid {line}; }}
        QPushButton#disclosureHeader {{ text-align:left; border:0; border-radius:0; background:transparent;
            padding:0 3px; min-height:25px; font-size:11px; font-weight:400; }}
        QPushButton#disclosureHeader:hover {{ color:{accent}; background:{hover}; }}
        QProgressBar#unitMeter {{ border:0; border-radius:0; background:{control}; min-height:4px; max-height:4px; }}
        QProgressBar#unitMeter::chunk {{ background:{accent}; border:0; border-radius:0; }}
        QWidget#filterBand, QWidget#workspacePanel {{ background:{surface}; border:1px solid {line}; border-radius:6px; }}
        QWidget#workbenchFilterBand {{ background:{surface}; border:1px solid {line}; border-radius:8px; }}
        QScrollArea#workbenchScroll QScrollBar:vertical {{ width:15px; }}
        QWidget#workbenchFilterBand QComboBox, QWidget#workbenchFilterBand QLineEdit,
        QWidget#workbenchFilterBand QPushButton {{ min-height:32px; max-height:32px; }}
        QWidget#workbenchCommands {{ background:{control}; border-top:1px solid {line}; }}
        QWidget#workbenchCommands QPushButton {{ min-height:0; max-height:34px; padding:0 10px; font-size:11px; font-weight:600; }}
        QWidget#workbenchCommands QPushButton[commandHeight="30"] {{ min-height:28px; max-height:28px; }}
        QWidget#workbenchCommands QPushButton[commandHeight="34"] {{ min-height:32px; max-height:32px; }}
        QWidget#workbenchCommands QPushButton#workbenchRefresh {{ min-height:28px; max-height:28px;
            min-width:28px; max-width:28px; padding:0; }}
        QWidget#workbenchActionGroup[separated="true"] {{ border-left:1px solid {line}; }}
        QLabel#workbenchCommandCaption {{ font-size:11px; color:{muted}; }}
        QWidget#workbenchFilterField[active="true"] QLabel {{ color:{accent}; }}
        QWidget#workbenchFilterField[active="true"] QComboBox,
        QWidget#workbenchFilterField[active="true"] QLineEdit {{ border-color:{accent}; }}
        QWidget#workbenchFilterSummary {{ border-top:1px dashed {line}; }}
        QLabel#workbenchFilterLead {{ font-size:11px; color:{muted}; }}
        QLabel#workbenchFilterLead[filtered="true"] {{ color:{accent}; font-weight:600; }}
        QWidget#workbenchFilterChip {{ background:{accent_soft}; border:1px solid {line}; border-radius:11px; }}
        QLabel#filterChipText {{ font-size:11px; color:{accent}; }}
        QToolButton#filterChipRemove {{ min-height:0; min-width:0; padding:0; border:0; background:transparent; }}
        QToolButton#filterChipRemove:hover {{ background:{hover}; }}
        QWidget#workbenchFilterBand QPushButton#workbenchFilterClear {{ min-height:22px; max-height:22px;
            padding:0 4px; border:0; background:transparent;
            color:{accent}; font-size:11px; text-decoration:underline; }}
        QWidget#modelSettingsBody {{ background:{surface}; }}
        QWidget#modelPartInfoBody {{ background:{surface}; }}
        QLabel#modelPartName {{ font-size:13px; font-weight:600; }}
        QTreeWidget#modelPartTree {{ border:0; background:transparent; font-size:12px; }}
        QTreeWidget#modelPartTree::item {{ min-height:26px; padding:2px; border:0; }}
        QTreeWidget#modelPartTree::item:selected {{ background:{hover}; color:{accent}; }}
        QToolButton#modelSectionHeader {{ text-align:left; border:0; border-bottom:1px solid {line};
            border-radius:0; background:transparent; color:{muted}; padding:2px 0; min-height:24px; font-weight:600; }}
        QToolButton#modelSectionHeader:hover {{ color:{accent}; background:{hover}; }}
        QToolButton#modelTypeLegend {{ border:0; border-radius:3px; padding:3px; background:transparent; color:{muted}; }}
        QToolButton#modelTypeLegend:hover, QToolButton#modelTypeLegend:checked {{ color:{accent}; background:{hover}; }}
          QToolButton#columnGroupLegend {{ border:0; border-radius:3px; padding:0 2px;
              background:transparent; color:{muted}; font-size:10px; min-height:20px; }}
          QToolButton#columnGroupLegend:hover {{ background:{hover}; }}
        QWidget#reportScopeBand {{ background:{surface}; border:1px solid {line};
            border-top:3px solid {accent}; border-radius:4px; }}
        QWidget#reportDraftPanel {{ background:{surface}; border-left:1px solid {line}; }}
        QWidget#reportDraftContents {{ background:{surface}; }}
        QWidget#reportDraftEntry {{ border-bottom:1px solid {line}; }}
        QWidget#reportWarnings, QWidget#reportWarningContents {{
            background:{"#302d22" if dark else "#fffaf0"}; }}
        QScrollArea#reportWarningScroll {{ border:0; background:transparent; }}
        QWidget#reportWarningGroup {{ background:{"#343024" if dark else "#fffdf7"};
            border:1px solid {"#675936" if dark else "#eadfbe"}; border-radius:5px; }}
        QPushButton#reportWarningToggle, QPushButton#reportWarningGroupToggle {{
            text-align:left; border:0; background:transparent; color:{"#ebcd91" if dark else "#634d20"};
            padding:2px 6px; }}
        QLabel#reportWarningHeadline {{ color:{"#c7b68f" if dark else "#8a7650"}; font-size:10px; }}
        QLabel#reportWarningReason {{ color:{"#e2cc9e" if dark else "#6b5320"}; font-size:11px; }}
        QLabel#reportWarningEvidence {{ background:{surface}; color:{text}; padding:6px;
            border:1px solid {"#675936" if dark else "#efe3c6"}; border-radius:4px; font-size:10px; }}
        QLabel#reportWarningRequirement {{ background:{"#403821" if dark else "#fdf4e2"};
            color:{"#ebcd91" if dark else "#8a6417"}; border-left:3px solid #c58a22;
            padding:4px 8px; font-size:10px; }}
        QWidget#settingsSidebar {{ background:{surface}; border:1px solid {line}; border-radius:7px; }}
        QListWidget#settingsNav {{ border:0; padding:0; }}
        QListWidget#settingsNav::item {{ padding:0; min-height:66px; }}
        QWidget#settingsSection {{ background:{surface}; border:1px solid {line}; border-radius:6px; }}
        QLabel#settingsSectionTitle {{ font-size:14px; font-weight:600; padding:8px 0 12px;
            border-bottom:1px solid {line}; }}
        QWidget#stateActionBand {{ background:{control}; border:1px solid {line}; border-radius:4px; }}
        QWidget#taskDrawer {{ background:{surface}; border:1px solid {line}; border-radius:6px; }}
        QLabel#drawerTitle {{ font-size:16px; font-weight:600; }}
        QWidget#taskDrawer QTabBar::tab {{ padding:8px 10px; }}
        QLabel#stateEffectiveSummary {{ background:{accent_soft}; border-left:3px solid {accent};
            color:{text}; padding:10px; }}
        QPushButton[stateSummary] {{ text-align:left; background:{control}; min-height:48px; }}
        QPushButton[stateSummary="normal"] {{ border-left:3px solid #79b98c; }}
        QPushButton[stateSummary="plugged"] {{ border-left:3px solid #c64e53; }}
        QPushButton[stateSummary="shifted"] {{ border-left:3px solid #e0ad36; }}
        QPushButton[stateSummary="replaced"] {{ border-left:3px solid #5c91ce; }}
        QLabel#filterLabel {{ color:{muted}; font-size:11px; }}
        QPushButton[primary="true"] {{ background:{accent}; color:white; border-color:{accent}; font-weight:600; }}
        QPushButton[primary="true"]:disabled {{ background:{control}; color:{muted}; border-color:{line}; }}
        QPushButton[danger="true"] {{ color:#c24858; border-color:#dfadb6; }}
        QTabBar#mainNavigation {{ background:transparent; }}
        QLabel#pageTitle {{ color:{text}; font-size:20px; font-weight:600; padding-top:2px; }}
        QLabel#muted {{ color:{muted}; }}
        QDialog#importWorkspace, QDialog#importWorkspace QWizardPage {{ background:{bg}; }}
        QScrollArea#importBody {{ background:{bg}; border:0; }}
        QWidget#importHeading {{ background:{surface}; border-bottom:1px solid {line}; }}
        QLabel#importEyebrow {{ color:{accent}; font-size:10px; }}
        QLabel#importTitle {{ color:{text}; font-size:19px; font-weight:600; }}
        QWidget#importActionDock {{ background:{surface}; border-top:1px solid {line}; }}
        QWidget#importResultMetric {{ background:{surface}; border:1px solid {line}; }}
        QLabel#importMetricValue {{ color:{accent}; font-size:16px; font-weight:600; }}
        QWidget#importSourcePanel {{ background:{surface}; border:1px solid {line}; border-radius:7px; }}
        QLabel#importRouteTitle {{ font-size:13px; font-weight:600; }}
        QTabBar#importSourceTabs::tab {{ min-height:40px; padding:7px 12px; text-align:left; font-size:11px; }}
        QTabBar#importSourceTabs::tab:selected {{ background:{accent_soft}; }}
        QLabel#metricValue {{ font-size:24px; font-weight:600; }}
        QPushButton#metricValue {{ font-size:24px; font-weight:600; border:0; text-align:left; padding:0; }}
        QWidget#overviewMetric {{ border-right:1px solid {line}; border-bottom:1px solid {line}; }}
        QWidget#overviewMetric QLabel#muted {{ font-size:11px; }}
        QLabel#metricNote {{ font-size:10px; color:{muted}; }}
        QLabel#sectionHeading {{ padding:12px; border-bottom:1px solid {line}; font-size:12px; font-weight:600; }}
        QPushButton#metricValue[metric="war"] {{ color:#ba414c; }}
        QPushButton#metricValue[metric="ndd"] {{ color:{muted}; }}
        QPushButton#metricValue[metric="missing"] {{ color:{"#e4b961" if dark else "#946414"}; }}
        QPushButton#overviewInsight {{ text-align:left; min-height:72px; padding:6px 12px; }}
        QPushButton[insight="peak"] {{ border-left:3px solid #c64e53; }}
        QPushButton[insight="position"] {{ border-left:3px solid {accent}; }}
        QPushButton[insight="maintenance"] {{ border-left:3px solid #5a9b78; }}
        QPushButton[insight="quality"] {{ border-left:3px solid #bf942e; }}
        QPushButton, QToolButton {{ min-height:{height}px; padding:0 12px;
            background:{surface}; border:1px solid {line}; border-radius:4px; }}
        QPushButton:hover, QToolButton:hover {{ border-color:{accent}; background:{hover}; }}
        QPushButton:pressed, QToolButton:pressed {{ background:{accent_soft}; }}
        QPushButton:checked {{ color:{accent}; background:{accent_soft}; border-color:{accent}; font-weight:600; }}
        QPushButton:disabled, QToolButton:disabled {{ color:{muted}; background:{control}; }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ min-height:{height}px;
            background:{surface}; border:1px solid {line}; border-radius:4px; padding:0 8px; }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
        QPlainTextEdit:focus, QTextEdit:focus {{ border:1px solid {accent}; }}
        QComboBox::drop-down {{ subcontrol-origin:padding; subcontrol-position:top right; width:24px; border:0; }}
        QComboBox::down-arrow {{ image:url("{(Path(__file__).parent / 'assets' / 'chevron-down.svg').as_posix()}"); width:12px; height:12px; }}
        QComboBox QAbstractItemView {{ background:{surface}; border:1px solid {line};
            selection-background-color:{selected}; selection-color:{text}; padding:4px; }}
        QAbstractItemView, QTextEdit, QPlainTextEdit, QTextBrowser {{ background:{surface};
            alternate-background-color:{table_zebra}; border:1px solid {line};
            selection-background-color:{selected}; selection-color:{text}; }}
        QTableView {{ gridline-color:{line}; border:1px solid {line}; border-radius:5px;
            background:{surface}; alternate-background-color:{table_zebra};
            selection-background-color:{selected}; selection-color:{text}; }}
        QTableView::item {{ padding:5px 7px; border-bottom:1px solid {line}; }}
        QTableView::item:hover {{ background:{hover}; }}
        QHeaderView::section {{ background:{control}; color:{text}; border:0;
            border-bottom:1px solid {line}; padding:8px 7px; font-weight:600; }}
        QTabWidget::pane {{ border:1px solid {line}; border-radius:5px; background:{surface}; top:-1px; }}
        QTabBar::tab {{ background:{surface}; color:{muted}; padding:10px 18px;
            border:0; border-bottom:2px solid transparent; }}
        QTabBar::tab:hover {{ color:{accent}; background:{hover}; }}
        QTabBar::tab:selected {{ color:{accent}; border-bottom-color:{accent}; font-weight:600; }}
        QWidget#workbenchTableHeading {{ background:{control}; border-bottom:1px solid {line}; }}
        QLabel#workbenchTableTitle {{ font-size:14px; font-weight:600; }}
        QLabel#workbenchRecordCount {{ font-size:11px; color:{muted};
            border-left:1px solid {line}; padding-left:9px; margin-left:3px; }}
        QLabel#workbenchSelectionCount {{ font-size:11px; color:{accent}; background:{accent_soft};
            padding:2px 6px; border-radius:3px; }}
        QPushButton#workbenchSelectionButton {{ min-height:32px; max-height:32px;
            min-width:85px; max-width:85px; padding:0; font-size:11px; font-weight:400; }}
        QWidget#workbenchFieldModes {{ background:{control}; border:1px solid {line}; border-radius:4px; }}
        QWidget#workbenchPlateHeading {{ background:{"#1c2527" if dark else "#f8fafb"}; }}
        QLabel#workbenchPlateTitle {{ font-size:14px; font-weight:700; }}
        QLabel#workbenchPlateSubtitle {{ font-size:11px; color:{muted}; }}
        QPushButton#workbenchPlateExport {{ min-width:85px; max-width:85px;
            min-height:28px; max-height:28px; padding:0; font-size:11px; font-weight:600;
            background:{"#1c2527" if dark else "#f7f9fa"}; border-color:{"#3b4c4d" if dark else "#a9b7bd"}; }}
        QWidget#workbenchPlateModes {{ background:{"#1c2527" if dark else "#f3f6f8"}; border:0; border-radius:4px; }}
        QTabBar#workbenchPlateTabs {{ background:transparent; }}
        QTabBar#workbenchPlateTabs::tab {{ padding:0; min-width:74px; max-width:74px;
            min-height:34px; max-height:34px; border:0; border-radius:3px;
            font-size:12px; font-weight:600; color:{"#a8b8b5" if dark else "#6e7c87"};
            background:{"#232f31" if dark else "#ffffff"}; }}
        QTabBar#workbenchPlateTabs::tab:selected {{ background:{"#207e75" if dark else "#087d79"}; color:#ffffff; }}
        QWidget#workbenchPlateStats {{ border:1px solid {"#3b4c4d" if dark else "#e1eaec"};
            border-radius:6px; background:{"#1c2527" if dark else "#f8fafb"}; }}
        QLabel#workbenchPlateStatsEmpty {{ font-size:10px; color:{"#a8b8b5" if dark else "#7a888e"}; }}
        QWidget#workbenchPlateStatistic {{ border:0; border-right:1px solid {line}; }}
        QLabel#workbenchPlateStatisticLabel {{ font-size:9px; color:{muted}; }}
        QLabel#workbenchPlateStatisticValue {{ font-size:13px; font-weight:700; }}
        QWidget#workbenchPlateDetails {{ border:1px solid {"#3b4c4d" if dark else "#e4eaf0"};
            border-radius:4px; background:{surface}; }}
        QLabel#workbenchPlateDetailCaption {{ font-size:12px; color:{muted}; }}
        QListView#workbenchSelectedRecords {{ border:0; background:transparent; padding:0; }}
        QTabBar#workbenchFieldTabs {{ background:transparent; }}
        QTabBar#workbenchFieldTabs::tab {{ min-height:0; padding:0; border:1px solid transparent;
            border-radius:3px; background:transparent; font-size:11px; font-weight:600; }}
        QTabBar#workbenchFieldTabs::tab:selected {{ background:{surface}; border-color:{line}; color:{accent}; }}
        QTableView#workbenchTable {{ border:1px solid {line}; border-radius:0; }}
        QTableView#workbenchTable QHeaderView::section {{ padding:8px 6px; font-size:12px; }}
        QWidget#workbenchPager {{ background:{surface}; border-top:1px solid {line}; }}
        QWidget#workbenchPager QLabel {{ font-size:11px; color:{muted}; }}
        QWidget#workbenchPager QLabel#workbenchPageInfo {{ font-size:12px; color:{text}; }}
        QWidget#workbenchPager QLabel#workbenchPageSizeLabel {{ font-size:12px; }}
        QComboBox#workbenchPageSize {{ min-width:48px; max-width:48px; min-height:32px; max-height:32px;
            padding:0 8px; font-size:11px; }}
        QComboBox#workbenchPageSize::drop-down {{ width:18px; }}
        QPushButton#workbenchPageButton {{ min-width:28px; max-width:28px; min-height:28px; max-height:28px; padding:0; }}
        QLineEdit#workbenchPageJump {{ min-width:44px; max-width:44px; min-height:22px; max-height:22px;
            padding:3px 4px; font-size:11px; }}
        QSplitter#workbenchSplitter::handle {{ background:transparent; }}
        QSplitter#workbenchSplitter::handle:horizontal {{ margin:0 21px; border-left:1px solid {line}; }}
        QSplitter#workbenchSplitter::handle:vertical {{ margin:5px 0; border-top:1px solid {line}; }}
        QGroupBox {{ background:{surface}; border:1px solid {line}; border-radius:5px;
            margin-top:14px; padding:16px 12px 12px; }}
        QGroupBox::title {{ subcontrol-origin:margin; left:10px; padding:0 5px; }}
        QListWidget {{ background:{surface}; border:1px solid {line}; border-radius:6px; padding:6px; }}
        QListWidget::item {{ min-height:34px; padding:7px 10px; border-radius:4px; color:{text}; }}
        QListWidget::item:hover {{ background:{hover}; }}
        QListWidget::item:selected {{ background:{accent_soft}; color:{accent}; font-weight:600;
            border-left:3px solid {accent}; padding-left:7px; }}
        QDialog QWidget#settingsStack {{ background:transparent; border:0; }}
        QDialog QWidget#settingsPage {{ background:{surface}; }}
        QDialog QWidget#settingsPage QLabel {{ color:{text}; }}
        QDialog QWidget#settingsPage QLabel#muted {{ color:{muted}; }}
        QDialog QWidget#settingsPage QFormLayout {{ spacing:12px; }}
        QSplitter::handle {{ background:{line}; }}
        QSplitter::handle:hover {{ background:{accent}; }}
        QCheckBox {{ spacing:7px; }}
        QCheckBox::indicator {{ width:16px; height:16px; border:1px solid {line}; border-radius:3px;
            background:{surface}; }}
        QCheckBox::indicator:checked {{ background:{accent}; border-color:{accent};
            image:url("{(Path(__file__).parent / 'assets' / 'check-white.svg').as_posix()}"); }}
        QScrollBar:vertical {{ width:10px; background:{control}; margin:2px; }}
        QScrollBar::handle:vertical {{ min-height:30px; background:{line}; border-radius:5px; }}
        QScrollBar::handle:vertical:hover {{ background:{accent}; }}
        QStatusBar {{ color:{muted}; background:{surface}; border-top:1px solid {line}; }}
    """
