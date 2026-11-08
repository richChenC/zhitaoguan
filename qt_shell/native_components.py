"""Shared native workspace controls and persisted desktop preferences."""
from __future__ import annotations

import json
from pathlib import Path
import hashlib
import re
from functools import lru_cache

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QObject, QPoint, QPointF, QRect, QRectF, QSaveFile, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QLayout, QMessageBox, QPushButton, QSizePolicy, QToolTip, QWidget,
)

from .constants import UI_DIR, USER_DATA

SITE_NAMES = {"D": "大亚湾", "L": "岭澳", "N": "宁德", "H": "红沿河",
              "F": "防城港", "Y": "阳江", "T": "台山", "P": "惠州",
              "LF": "陆丰", "C": "苍南"}
STATE_NAMES = {"normal": "正常", "plugged": "堵管", "shifted": "移位", "replaced": "换管"}
SITE_ALIASES = {"CNPS": "D", "LNPS": "L", "NDNP": "N", "LHNP": "H",
                "BLNP": "F", "YJNP": "Y", "TSNP": "T", "HENP": "P", "CNMP": "C", "LFNP": "LF"}


def canonical_site(value):
    value = str(value or "").strip().upper()
    return SITE_ALIASES.get(value, value)


@lru_cache(maxsize=128)
def icon(name, theme="light"):
    source = QIcon(str(UI_DIR / "assets" / "icons" / f"{name}.svg"))
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


class ToolFlowLayout(QLayout):
    """Wrap command controls at their natural width on smaller workspaces."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []
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
        return size

    def sizeHint(self):
        return self.minimumSize()

    def _arrange(self, rect, apply):
        x, y, height = rect.x(), rect.y(), 0
        for item in self.items:
            if item.isEmpty():
                continue
            size = item.sizeHint()
            if x > rect.x() and x + size.width() > rect.right() + 1:
                x, y, height = rect.x(), y + height + self.spacing(), 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), size))
            x += size.width() + self.spacing()
            height = max(height, size.height())
        return y + height - rect.y()


def export_widget_image(parent, client, widget, title):
    """Recheck the live session and audit the exact image before saving."""
    path, _ = QFileDialog.getSaveFileName(parent, title, "", "PNG (*.png)")
    if not path:
        return
    raw = QByteArray()
    buffer = QBuffer(raw)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
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
                "report_policy": "manual", "source_path": "",
                "depth_levels": [20, 40, 60], "depth_colors": ["#39a78e", "#edbd50", "#df8252", "#c64e53"]}

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
        for key in ("animations", "remember_page"):
            if isinstance(data.get(key), bool):
                values[key] = data[key]
        for key in ("start_page", "last_page"):
            if type(data.get(key)) is int and 0 <= data[key] <= 4:
                values[key] = data[key]
        if isinstance(data.get("source_path"), str):
            values["source_path"] = data["source_path"]
        levels, colors = data.get("depth_levels"), data.get("depth_colors")
        if (isinstance(levels, list) and len(levels) == 3
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

    def __init__(self, client, parent=None, *, allow_all=True):
        super().__init__(parent)
        self.client = client
        self.allow_all = allow_all
        self.combinations = []
        self._requested_scope = {}
        self._loaded_once = False
        self.site, self.unit, self.outage = QComboBox(), QComboBox(), QComboBox()
        self.site.setMinimumWidth(135)
        self.unit.setMinimumWidth(110)
        self.outage.setMinimumWidth(145)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for text, control in (("基地", self.site), ("机组", self.unit), ("大修", self.outage)):
            layout.addWidget(QLabel(text))
            layout.addWidget(control)
        self.reset = button("清除筛选", "rotate-ccw", self.clear)
        self.refresh = button("刷新数据", "refresh-cw", self.reload)
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
        self.combinations = data.get("combinations") or []
        self._loaded_once = True
        self.site.blockSignals(True)
        self.site.clear()
        self.site.addItem("全部基地", "")
        for site in sorted({canonical_site(row["site"]) for row in self.combinations}):
            self.site.addItem(SITE_NAMES.get(site, site), site)
        self.site.blockSignals(False)
        self.set_scope(previous)
        self.loaded.emit(self.values())

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

    def set_scope(self, scope):
        self._requested_scope = {"site": canonical_site(scope.get("site")),
                                 "unit": str(scope.get("unit") or ""), "outage": scope.get("outage") or ""}
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
            return QColor({"plugged": "#c64e53", "shifted": "#e0ad36", "replaced": "#6d64b0",
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


def workspace_styles(theme="light", density="comfortable"):
    dark = theme == "dark"
    bg, surface, text, line, muted = (
        ("#202427", "#292f33", "#e7edef", "#495359", "#a8b6bc") if dark else
        ("#f3f6f7", "#ffffff", "#30434f", "#d8e1e6", "#72848f"))
    height = 26 if density == "compact" else 32
    return f"""
        QWidget {{ color:{text}; font-family:"Microsoft YaHei UI"; font-size:12px; }}
        QMainWindow, QDialog {{ background:{bg}; }}
        QWidget#topNavigation {{ background:{surface}; border-bottom:1px solid {line}; }}
        QLabel#pageTitle {{ font-size:19px; font-weight:600; }}
        QLabel#muted {{ color:{muted}; }}
        QPushButton, QToolButton {{ min-height:{height}px; padding:0 10px;
            background:{surface}; border:1px solid {line}; border-radius:4px; }}
        QPushButton:hover, QToolButton:hover {{ border-color:#168e94; background:{'#344447' if dark else '#eff8f7'}; }}
        QPushButton:checked {{ color:{'#8cdbd5' if dark else '#087780'}; background:{'#304c4e' if dark else '#e5f4f2'}; border-color:#82bdb9; }}
        QPushButton:disabled, QToolButton:disabled {{ color:{muted}; }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ min-height:{height}px;
            background:{surface}; border:1px solid {line}; border-radius:4px; padding:0 6px; }}
        QAbstractItemView, QTextEdit, QPlainTextEdit, QTextBrowser {{ background:{surface};
            alternate-background-color:{bg}; border:1px solid {line}; selection-background-color:#c4e7e2;
            selection-color:#173c40; }}
        QHeaderView::section {{ background:{bg}; border:0; border-bottom:1px solid {line};
            padding:8px 6px; font-weight:500; }}
        QTabWidget::pane {{ border:1px solid {line}; background:{surface}; }}
        QTabBar::tab {{ background:{surface}; padding:9px 18px; border-bottom:2px solid transparent; }}
        QTabBar::tab:selected {{ color:{'#8cdbd5' if dark else '#087780'}; border-bottom-color:#168e94; }}
        QGroupBox {{ border:1px solid {line}; border-radius:4px; margin-top:12px; padding:12px; }}
        QGroupBox::title {{ subcontrol-origin:margin; left:10px; padding:0 5px; }}
        QSplitter::handle {{ background:{bg}; }}
        QStatusBar {{ background:{surface}; border-top:1px solid {line}; }}
    """
