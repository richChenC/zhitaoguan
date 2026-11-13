"""Native import settings panels and versioned comparison rule workspace."""
from __future__ import annotations

import math
from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QRadioButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)


def label(text="", name="settingsBusinessText"):
    control = QLabel(text)
    control.setObjectName(name)
    control.setTextFormat(Qt.TextFormat.PlainText)
    control.setWordWrap(True)
    control.setMinimumWidth(0)
    return control


class SettingsBusinessPanel(QWidget):
    resized = Signal()
    def __init__(self, title, subtitle="", badge=None):
        super().__init__()
        self.setObjectName("settingsBusinessPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        self.header = QWidget()
        self.header.setObjectName("settingsStorageHeader")
        heading = QHBoxLayout(self.header)
        heading.setContentsMargins(23, 14, 20, 14)
        heading.setSpacing(12)
        words = QVBoxLayout()
        words.setSpacing(3)
        self.title = label(title, "settingsBusinessTitle")
        words.addWidget(self.title)
        if subtitle:
            words.addWidget(label(subtitle, "settingsBusinessHint"))
        heading.addLayout(words, 1)
        if badge:
            badge.setObjectName("settingsBusinessHint")
            heading.addWidget(badge)
        self.header.setMinimumHeight(72 if subtitle else 58)
        layout.addWidget(self.header)
        self.body = QWidget()
        self.content = QVBoxLayout(self.body)
        self.content.setContentsMargins(20, 4, 20, 20)
        self.content.setSpacing(0)
        layout.addWidget(self.body)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()


class ColorSwatch(QPushButton):
    def __init__(self, color):
        super().__init__()
        self.setObjectName("settingsColorSwatch")
        self.color = color
        self.setFixedSize(48, 30)
        self.setStyleSheet("QPushButton {height:28px;min-height:28px;max-height:28px;"
                           "min-width:46px;max-width:46px;padding:0;}")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor("#cbd7df"))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 4, 4)
        painter.fillRect(self.rect().adjusted(6, 8, -6, -8), QColor(self.color))
        painter.setPen(QColor("#71818b"))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.rect().adjusted(6, 8, -6, -8))
        if self.hasFocus():
            painter.setPen(QPen(QColor("#087d79"), 1, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.rect().adjusted(2, 2, -3, -3))


class SourceChoice(QPushButton):
    def __init__(self, item, callback):
        super().__init__()
        self.item = dict(item)
        self.setObjectName("settingsSourceChoice")
        title = f"{item.get('station') or item.get('site', '')} · {item.get('outage', '')}"
        self.setAccessibleName(f"{title} {item.get('path', '')}")
        self.setToolTip(item.get("path", ""))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(3)
        for text, name in ((title, "settingsSourceTitle"),
                           (" · ".join(str(item.get(key) or "") for key in
                                       ("project", "unit_folder", "folder")), "settingsBusinessText"),
                           (str(item.get("path") or ""), "settingsBusinessHint")):
            child = label(text, name)
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(child)
        self.setMinimumHeight(70)
        self.clicked.connect(lambda: callback(self.item))


class SourceResults(QScrollArea):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.setObjectName("settingsSourceResults")
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.host = QWidget()
        self.grid = QGridLayout(self.host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(8)
        self.setWidget(self.host)
        self.buttons = []
        self.setFixedHeight(0)

    def set_items(self, items):
        for control in self.buttons:
            self.grid.removeWidget(control)
            control.deleteLater()
        self.buttons = [SourceChoice(item, self.callback) for item in items]
        self.relayout()

    def relayout(self):
        columns = 1 if self.window().width() <= 900 else 2
        for control in self.buttons:
            self.grid.removeWidget(control)
        for index, control in enumerate(self.buttons):
            self.grid.addWidget(control, index // columns, index % columns)
        for column in range(2):
            self.grid.setColumnStretch(column, 1 if column < columns else 0)
        height = self.grid.sizeHint().height()
        self.setFixedHeight(min(340, height) if self.buttons else 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.relayout()


class RuleActive(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("settingsRulesActive")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(16, 12, 16, 12)
        self.box.setSpacing(4)
        self.heading = QHBoxLayout()
        self.heading.setSpacing(14)
        self.caption = label("当前生效", "settingsRuleActiveCaption")
        self.caption.setWordWrap(False)
        self.summary = label("读取中…")
        self.heading.addWidget(self.caption)
        self.heading.addWidget(self.summary, 1)
        self.box.addLayout(self.heading)
        self.metadata = label("", "settingsBusinessHint")
        self.note = label("", "settingsBusinessHint")
        self.box.addWidget(self.metadata)
        self.box.addWidget(self.note)

    def set_rule(self, rule):
        self.caption.setText("当前生效")
        parent = f" · 基于 v{rule['parent_version']}" if rule.get("parent_version") else ""
        self.summary.setText(f"v{rule.get('version', 0)} · {rule.get('name') or '初始规则'} · "
                             f"容差 {rule.get('match_tolerance_mm', .01):g} mm{parent}")
        self.metadata.setText(" · ".join(str(rule.get(key) or "").replace("T", " ") for key in
                                         ("created_by", "created_at")).strip(" ·"))
        self.note.setText(str(rule.get("note") or ""))
        self.metadata.setVisible(bool(self.metadata.text()))
        self.note.setVisible(bool(self.note.text()))

    def setText(self, text):
        self.caption.setText(text.split("\n", 1)[0])
        self.summary.setText(text.partition("\n")[2])
        self.metadata.hide()
        self.note.hide()

    def text(self):
        return "\n".join(control.text() for control in
                         (self.caption, self.summary, self.metadata, self.note) if control.text())


class RuleVersion(QRadioButton):
    def __init__(self, rule):
        super().__init__()
        self.setObjectName("settingsRuleVersion")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        self.setMinimumWidth(0)
        grid = QGridLayout(self)
        grid.setContentsMargins(35, 8, 12, 8)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)
        grid.setRowMinimumHeight(0, 40)
        self.words = []
        name = label(f"v{rule['version']} {rule['name']}", "settingsRuleName")
        tolerance = label(f"容差 {rule['match_tolerance_mm']:g} mm"
                          + (" · 当前生效" if rule.get("is_active") else ""), "settingsRuleTolerance")
        tolerance.setWordWrap(False)
        grid.addWidget(name, 0, 0, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(tolerance, 0, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        metadata = " · ".join(str(rule.get(key) or "").replace("T", " ") for key in
                              ("created_by", "created_at")).strip(" ·")
        if rule.get("parent_version"):
            metadata += f" · 基于 v{rule['parent_version']}"
        for row, text in enumerate((metadata, str(rule.get("note") or "")), 1):
            if text:
                grid.addWidget(label(text, "settingsBusinessHint"), row, 0, 1, 2)
        for child in self.findChildren(QLabel):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        grid.setColumnStretch(0, 1)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop)

    def sizeHint(self):
        return self.layout().sizeHint().expandedTo(QSize(0, 94))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dark = bool(self.property("dark"))
        accent = QColor("#78cfc1" if dark else "#087d79")
        highlighted = self.isChecked() or bool(self.property("active"))
        painter.setPen(QPen(accent if highlighted else QColor("#344547" if dark else "#d9e3e8"), 1))
        painter.setBrush(QColor(("#243a38" if dark else "#e8f0f2") if highlighted else
                                ("#1b2526" if dark else "#ffffff")))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 4, 4)
        painter.setPen(QPen(accent if self.isChecked() else QColor("#9aadb6"), 1))
        painter.setBrush(QColor("#1b2526" if dark else "#ffffff"))
        painter.drawEllipse(QRectF(13, 22, 12, 12))
        if self.isChecked():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawEllipse(QRectF(16, 25, 6, 6))
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(accent, 1, Qt.PenStyle.DotLine))
            painter.drawRect(self.rect().adjusted(3, 3, -4, -4))


class RulesSettingsPanel(SettingsBusinessPanel):
    rulesChanged = Signal(dict)

    def __init__(self, client, permissions):
        super().__init__("对比规则版本", "仅用于历次大修结果的缺陷位置匹配。")
        self.client, self.can_write = client, "settings.manage" in permissions
        self.content.setContentsMargins(20, 14, 20, 20)
        self.content.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.rules, self.base_version, self.filled_version = [], 0, None
        self.loaded, self.busy, self.serial = False, False, 0
        compact_note = label("修改规则不会改变原始检测数据、单次报告或已导出的文件。",
                             "settingsRulesNote")
        compact_note.setMinimumHeight(36)
        self.content.addWidget(compact_note)
        self.content.addSpacing(12)
        self.active = RuleActive()
        self.content.addWidget(self.active)
        self.content.addSpacing(12)
        head = QHBoxLayout()
        head.addWidget(label("历史版本（勾选一个作为新版本基础）", "settingsBusinessTitle"), 1)
        self.refresh = QPushButton("刷新")
        self.refresh.clicked.connect(self.load)
        head.addWidget(self.refresh)
        self.content.addLayout(head)
        self.content.addSpacing(6)
        self.history = QScrollArea()
        self.history.setObjectName("settingsRulesHistory")
        self.history.setWidgetResizable(True)
        self.history.setFrameShape(QScrollArea.Shape.NoFrame)
        self.history.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.history_host = QWidget()
        self.history_layout = QVBoxLayout(self.history_host)
        self.history_layout.setContentsMargins(0, 0, 0, 0)
        self.history_layout.setSpacing(6)
        self.history.setWidget(self.history_host)
        self.group = QButtonGroup(self)
        self.group.idClicked.connect(self.select_base)
        self.content.addWidget(self.history)
        self.content.addSpacing(14)
        self.new_heading = QWidget()
        self.new_heading.setObjectName("settingsRulesNewHeading")
        new_layout = QHBoxLayout(self.new_heading)
        new_layout.setContentsMargins(0, 25, 0, 5)
        new_layout.addWidget(label("建立新版本", "settingsRuleNewTitle"), 1)
        new_hint = label("新版本建立后立即生效，旧版本保留用于追溯。", "settingsRuleNewHint")
        new_hint.setWordWrap(False)
        new_layout.addWidget(new_hint, 0, Qt.AlignmentFlag.AlignRight)
        self.new_heading.setMinimumHeight(50)
        self.content.addWidget(self.new_heading)
        self.content.addSpacing(4)
        self.base_hint = label("读取历史版本…", "settingsRulesBase")
        self.base_hint.setMinimumHeight(37)
        self.content.addWidget(self.base_hint)
        self.content.addSpacing(10)
        from .native_settings_layout import SettingsPreferenceRow
        self.name = QLineEdit()
        self.name.setPlaceholderText("例如：2026 秋检容差调整")
        self.tolerance = QLineEdit("0.01")
        self.note = QLineEdit()
        self.note.setPlaceholderText("例如：依据 2026 秋检复核结果调整")
        self.rows = []
        for title, hint, control in (
            ("新规则名称", "用于报告和审计记录", self.name),
            ("匹配容差 (mm)", "轴向位置匹配允许的最大偏差；大于 0，且不超过 5 mm", self.tolerance),
            ("备注", "填写调整依据，便于复核", self.note),
        ):
            control.setProperty("settingsControlHeight", 38)
            row = SettingsPreferenceRow(title, hint, control, self.body)
            self.rows.append(row)
            self.content.addWidget(row)
        self.error = label("", "settingsRulesError")
        self.error.hide()
        self.content.addWidget(self.error)
        self.content.addSpacing(12)
        self.create = QPushButton("建立并激活新版本")
        self.create.setProperty("primary", True)
        self.create.clicked.connect(self.create_version)
        self.content.addWidget(self.create, 0, Qt.AlignmentFlag.AlignLeft)
        self.content.addSpacing(16)
        self._sync_enabled()
        self.load()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.relayout()

    def relayout(self):
        inner = max(1, self.width() - 42)
        for index, row in enumerate(self.rows):
            height = row.layout_for_width(max(1, inner - 24), self.window().width() <= 900,
                                          9 if self.window().width() <= 1000 else 14,
                                          False)
            row.setFixedHeight(round(height))
        controls = self.group.buttons()
        for control in controls:
            height = control.layout().heightForWidth(inner)
            control.setFixedHeight(max(94, height))
        # New layout children can remain hidden until the next event, so a
        # layout sizeHint here can be zero immediately after an async refresh.
        height = sum(control.height() for control in controls) + max(0, len(controls) - 1) * 6 if controls else 36
        self.history_host.setMinimumHeight(height)
        self.history.setFixedHeight(min(260, height))
        self.active.setMinimumHeight(88)

    def _sync_enabled(self):
        self.refresh.setEnabled(not self.busy)
        self.create.setEnabled(self.can_write and self.loaded and not self.busy)
        for control in (self.name, self.tolerance, self.note, self.history_host):
            control.setEnabled(not self.busy)

    def load(self):
        if self.busy:
            return
        self.serial += 1
        serial = self.serial
        self.client.get("/api/analysis-rules", lambda data, error: self._loaded(serial, data, error))

    def _loaded(self, serial, data, error):
        if serial != self.serial:
            return
        if error or not data:
            self.loaded = False
            self.active.setText(f"读取失败\n{error or '服务未返回有效规则'}")
            self.base_hint.setText("读取历史版本失败，暂不能建立新版本。")
            self._sync_enabled()
            return
        self.loaded = True
        active = data.get("active") or data.get("defaults") or {}
        self.active.set_rule(active)
        self.rules = data.get("items") or []
        if not any(row["version"] == self.base_version for row in self.rules):
            self.base_version = active.get("version") or (self.rules[0]["version"] if self.rules else 0)
        while self.history_layout.count():
            child = self.history_layout.takeAt(0).widget()
            if isinstance(child, QRadioButton):
                self.group.removeButton(child)
            child.hide()
            child.deleteLater()
        for row in self.rules:
            control = RuleVersion(row)
            control.setAccessibleName(f"以 v{row['version']} 作为新版本基础")
            control.setProperty("active", bool(row.get("is_active")))
            control.setProperty("dark", bool(self.property("dark")))
            control.setChecked(row["version"] == self.base_version)
            control.setToolTip(self.describe(row))
            self.group.addButton(control, row["version"])
            self.history_layout.addWidget(control)
            control.show()
        if not self.rules:
            self.history_layout.addWidget(label("暂无历史版本", "settingsBusinessHint"))
        self._sync_base(fill=self.filled_version != self.base_version, fill_note=False)
        self.filled_version = self.base_version
        self._sync_enabled()
        self.relayout()

    @staticmethod
    def describe(rule, history=False):
        parent = f" · 基于 v{rule['parent_version']}" if rule.get("parent_version") else ""
        first = f"v{rule.get('version', 0)} · {rule.get('name') or '初始规则'} · 容差 {rule.get('match_tolerance_mm', .01):g} mm"
        if history and rule.get("is_active"):
            first += " · 当前生效"
        metadata = " · ".join(str(rule.get(key) or "").replace("T", " ") for key in ("created_by", "created_at")).strip(" ·")
        return "\n".join(value for value in (first + parent, metadata, str(rule.get("note") or "")) if value)

    def select_base(self, version):
        if self.busy or not self.loaded:
            return
        self.base_version = version
        self._sync_base(fill=True, fill_note=True)
        self.filled_version = version
        self.error.hide()

    def _sync_base(self, *, fill, fill_note):
        rule = next((row for row in self.rules if row["version"] == self.base_version), None)
        if not rule:
            self.base_hint.setText("当前没有历史版本，可直接建立首个版本。")
            return
        if fill:
            self.tolerance.setText(f"{rule['match_tolerance_mm']:g}")
            if fill_note:
                self.note.setText(rule.get("note") or "")
        self.base_hint.setText(f"基于 v{rule['version']} {rule['name']} 建立，可修改下方名称、容差和备注。")

    def create_version(self):
        if self.busy or not self.loaded or not self.can_write:
            return
        name = self.name.text().strip()
        try:
            tolerance = float(self.tolerance.text())
            valid = math.isfinite(tolerance) and 0 < tolerance <= 5
        except ValueError:
            valid = False
        error = "请输入规则名称" if not name else (
            "匹配容差需大于 0 且不超过 5 mm" if not valid else "")
        if self.rules and not any(row["version"] == self.base_version for row in self.rules):
            error = "请先在历史版本中勾选一个版本作为新版本基础"
        if error:
            self.error.setText(error)
            self.error.show()
            return
        self.serial += 1
        serial = self.serial
        self.busy = True
        self.error.hide()
        self.create.setText("正在建立…")
        self._sync_enabled()
        self.client.post("/api/analysis-rules",
                         {"name": name, "match_tolerance_mm": tolerance, "note": self.note.text().strip(),
                          "parent_version": self.base_version},
                         lambda data, error: self._created(serial, data, error))

    def _created(self, serial, data, error):
        if serial != self.serial:
            return
        self.busy = False
        self.create.setText("建立并激活新版本")
        self._sync_enabled()
        if error or not data:
            self.error.setText(error or "建立规则失败")
            self.error.show()
            return
        self.name.clear()
        self.note.clear()
        self.base_version, self.filled_version = 0, None
        self.rulesChanged.emit(data)
        self.load()


def business_styles(dark):
    panel, text, muted, line, fill, accent = (
        ("#1b2526", "#e4efed", "#a6b8b5", "#344547", "#202d2e", "#78cfc1") if dark else
        ("#ffffff", "#263d49", "#71818b", "#d9e3e8", "#f8fafb", "#087d79"))
    return f"""
        QWidget#settingsBusinessPanel {{ background:{panel}; border:1px solid {line}; border-radius:8px; }}
        QLabel#settingsBusinessTitle {{ font-size:13px; font-weight:700; color:{text}; }}
        QLabel#settingsBusinessText {{ font-size:12px; color:{text}; }}
        QLabel#settingsBusinessHint {{ font-size:11px; color:{muted}; }}
        QLabel#settingsSeverityLegend {{ font-size:12px; font-weight:700; color:{muted};
            border-top:1px solid {line}; padding-top:7px; }}
        QWidget#settingsSeverityRow {{ border-bottom:1px solid {line}; }}
        QWidget#settingsBusinessPanel QLineEdit, QWidget#settingsBusinessPanel QSpinBox,
        QWidget#settingsBusinessPanel QComboBox {{ min-width:0; min-height:0; padding:0 10px;
            border:1px solid {line}; border-radius:4px; background:{panel}; color:{text}; font-size:12px; }}
        QWidget#settingsBusinessPanel QPushButton {{ min-width:0; min-height:0; padding:0 12px;
            height:34px; font-size:12px; border:1px solid {line}; background:{panel}; }}
        QWidget#settingsBusinessPanel QPushButton#settingsSourceBrowse {{ min-width:60px; max-width:60px;
            min-height:36px; max-height:36px; padding:0; }}
        QWidget#settingsBusinessPanel QPushButton#settingsSourceSave {{ min-width:73px; max-width:73px;
            min-height:34px; max-height:34px; padding:0; }}
        QWidget#settingsBusinessPanel QPushButton#settingsSourceScan {{ min-width:116px; max-width:116px;
            min-height:34px; max-height:34px; padding:0; }}
        QWidget#settingsBusinessPanel QPushButton#settingsColorSwatch {{ min-width:46px; max-width:46px;
            min-height:28px; max-height:28px; padding:0; }}
        QWidget#settingsBusinessPanel QLineEdit#settingsSourcePath {{ min-height:36px; max-height:36px; }}
        QWidget#settingsBusinessPanel QPushButton[primary="true"] {{ background:{accent};
            color:{"#132724" if dark else "#ffffff"}; border-color:{accent}; }}
        QWidget#settingsBusinessPanel QPushButton:disabled {{ color:{muted}; background:{fill}; }}
        QLabel#settingsRulesNote {{ font-size:11px; color:{muted}; background:{fill};
            border:1px solid {line}; border-radius:6px; padding:9px 10px; }}
        QLabel#settingsPolicyNote {{ font-size:11px; color:{muted}; background:{fill};
            border:1px solid {line}; border-left:3px solid {accent}; border-radius:6px; padding:10px 11px; }}
        QWidget#settingsRulesActive {{ font-size:13px; color:{text}; background:{fill};
            border:1px solid {line}; border-left:3px solid {accent}; }}
        QLabel#settingsRuleActiveCaption, QLabel#settingsRuleTolerance {{ color:{accent}; font-size:12px; }}
        QLabel#settingsRuleActiveCaption, QLabel#settingsRuleName {{ font-weight:700; }}
        QLabel#settingsRuleNewTitle {{ color:{text}; font-size:12px; font-weight:700; }}
        QLabel#settingsRuleNewHint {{ color:{muted}; font-size:10px; }}
        QLabel#settingsRulesBase {{ font-size:12px; color:{text}; background:{fill};
            border:1px dashed {line}; border-radius:4px; padding:8px 12px; }}
        QWidget#settingsRulesNewHeading {{ border-top:1px dashed {line}; border-bottom:1px solid {line}; }}
        QLabel#settingsRulesError {{ color:{"#ef9298" if dark else "#bd535a"}; font-size:12px; padding:8px; }}
        QScrollArea#settingsRulesHistory, QScrollArea#settingsSourceResults,
        QScrollArea#settingsRulesHistory > QWidget > QWidget,
        QScrollArea#settingsSourceResults > QWidget > QWidget {{ border:0; background:{panel}; }}
        QRadioButton#settingsRuleVersion {{ padding:0 12px; border:1px solid {line};
            border-radius:4px; background:{panel}; font-size:12px; color:{text}; spacing:10px; }}
        QRadioButton#settingsRuleVersion:checked {{ border-color:{accent}; background:{fill}; }}
        QRadioButton#settingsRuleVersion::indicator {{ width:12px; height:12px; border-radius:7px;
            border:1px solid {line}; background:{panel}; }}
        QRadioButton#settingsRuleVersion::indicator:checked {{ border:3px solid {accent}; }}
        QPushButton#settingsSourceChoice {{ background:{fill}; border:1px solid {line}; padding:0; }}
        QLabel#settingsSourceTitle {{ color:{"#ef9298" if dark else "#a8353d"}; font-size:14px; font-weight:700; }}
        QLabel#settingsSourceEmpty {{ color:{muted}; background:{fill}; border:1px dashed {line};
            padding:18px 12px; font-size:11px; }}
    """
