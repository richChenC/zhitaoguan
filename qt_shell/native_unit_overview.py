"""Grouped unit rows and lazy historical disclosures for the native overview."""
from __future__ import annotations

from collections import Counter, defaultdict
import re

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QSizePolicy,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .native_analysis_data import valid_depth
from .native_components import SITE_NAMES, STATE_NAMES, button, icon


def plain_label(text, name=None):
    label = QLabel(str(text))
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    if name:
        label.setObjectName(name)
    return label


class Disclosure(QWidget):
    def __init__(self, title, factory, parent=None, *, expanded=False):
        super().__init__(parent)
        self.factory, self.body = factory, None
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(4)
        self.header = button(title, "chevron-right")
        self.header.setObjectName("disclosureHeader")
        self.header.setCheckable(True)
        self.header.setToolTip(title)
        self.header.setMinimumWidth(0)
        self.header.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.header.toggled.connect(self.set_expanded)
        self.box.addWidget(self.header)
        self.header.setChecked(expanded)

    def set_expanded(self, expanded):
        if expanded and self.body is None:
            self.body = self.factory()
            self.box.addWidget(self.body)
        if self.body is not None:
            self.body.setVisible(expanded)
        self.header.setProperty("expanded", expanded)
        self.header.setProperty("iconName", "chevron-down" if expanded else "chevron-right")
        self.header.setIcon(icon(self.header.property("iconName")))
        self.header.setAccessibleDescription("已展开" if expanded else "已折叠")
        self.updateGeometry()


class CompositionStrip(QWidget):
    colors = {"defect": "#d38794", "NDD": "#ffffff", "incomplete": "#e2bd75", "missing": "#9aaeb7"}

    def __init__(self, counts, parent=None, *, none_color="#ffffff"):
        super().__init__(parent)
        self.counts = counts
        self.colors = {**self.colors, "NDD": none_color}
        self.setFixedHeight(11)
        self.setMinimumWidth(145)
        self.setToolTip(" · ".join(f"{label} {counts[key]} 根" for key, label in
            (("defect", "WAR"), ("NDD", "NDD"), ("incomplete", "待核对"), ("missing", "无检测记录"))))

    def paintEvent(self, event):
        painter = QPainter(self)
        total = sum(self.counts.values())
        left = 0.0
        for key, color in self.colors.items():
            count = self.counts[key]
            width = self.width() * count / total if total else 0
            if width:
                rect = QRectF(left, 0, width, self.height() - 1)
                painter.fillRect(rect, QColor(color))
                if count >= 5:
                    painter.setPen(QColor("#263e46"))
                    font = painter.font()
                    font.setPixelSize(9)
                    painter.setFont(font)
                    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(count))
                left += width
        painter.setPen(QColor("#cbdde1"))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))


class UnitOverview(QWidget):
    plateRequested = Signal(str, str)
    recordsRequested = Signal(str, str)
    historyRequested = Signal(str, str)
    tubesRequested = Signal(str, str, list, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(10)
        self.box.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.groups, self.rows, self.disclosures, self.history = {}, {}, {}, {}
        self.collapsed_sites = set()
        self.levels, self.colors = [30, 50], ["#79b98c", "#e5a83b", "#df4b45"]
        self.none_color = "#ffffff"
        self._data = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def set_data(self, data, latest):
        if self._data is data:
            return
        opened = {key for key, item in self.disclosures.items() if item.header.isChecked()}
        self._data = data
        while self.box.count():
            item = self.box.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.groups, self.rows, self.disclosures, self.history = {}, {}, {}, {}
        units = {item["code"]: item for item in data.get("units") or []}
        grouped = defaultdict(list)
        for code, snapshot in sorted(latest.items(), key=lambda item: (
                re.match(r"^[A-Z]+", item[0])[0], int(re.search(r"\d+$", item[0])[0]))):
            site = snapshot.get("site") or re.match(r"^[A-Z]+", code)[0]
            grouped[site].append(snapshot)
        for site in sorted(grouped, key=lambda code: list(SITE_NAMES).index(code) if code in SITE_NAMES else 100):
            snapshots = grouped[site]
            group = QWidget()
            group.setObjectName("unitSiteGroup")
            layout = QVBoxLayout(group)
            layout.setContentsMargins(12, 8, 12, 8)
            layout.setSpacing(3)
            tubes = [tube for snapshot in snapshots for tube in snapshot.get("tubes") or []]
            counts = Counter(tube.get("coverage") for tube in tubes)
            depths = [valid_depth(tube) for tube in tubes if valid_depth(tube) is not None]
            reported = len(tubes) - counts["missing"]
            plugged_count = sum(1 for tube in tubes
                                if tube.get("state") == "plugged" or "plugged" in (tube.get("state_badges") or []))
            # 计划分母：所有 snapshots 有一致 plan_denominator 时使用；否则回退 len(tubes)
            denom_candidates = [snap.get("plan_denominator") for snap in snapshots
                                if snap.get("plan_denominator") is not None]
            plan_denom = denom_candidates[0] if denom_candidates and all(d == denom_candidates[0]
                                                                         for d in denom_candidates) else None
            denominator = plan_denom or len(tubes)
            coverage = f"{reported / denominator:.0%}" if denominator else "—"
            title = QWidget()
            title.setObjectName("unitSiteHeading")
            title_layout = QHBoxLayout(title)
            title_layout.setContentsMargins(8, 6, 8, 6)
            title_layout.addWidget(plain_label(f"{site}  {SITE_NAMES.get(site, site)}\n{len(snapshots)} 台机组", "unitName"), 1)
            denom_tag = f"（计划 {denominator} 根）" if plan_denom else ""
            plug_value = f"{plugged_count}" if plugged_count else "/"
            for value, label in ((coverage, f"检测覆盖 {reported}/{denominator}{denom_tag}"),
                                 (counts["defect"], "WAR 检出"),
                                 (plug_value, "堵管"),
                                 (f"{max(depths):g}%" if depths else "/", "峰值深度"),
                                 (counts["missing"], "无检测记录")):
                title_layout.addWidget(plain_label(f"{value}\n{label}"), 1)
            layout.addWidget(title)
            body = QWidget()
            body_layout = QVBoxLayout(body)
            body_layout.setContentsMargins(0, 0, 0, 0)
            body_layout.setSpacing(0)
            headings = QWidget()
            header = self._row_grid(headings)
            for column, label in enumerate(("机组 / 大修", "峰值深度", "检测覆盖", "通道构成", "操作")):
                header.addWidget(plain_label(label, "muted"), 0, column)
            body_layout.addWidget(headings)
            for snapshot in snapshots:
                body_layout.addWidget(self._unit_row(snapshot, units.get(snapshot["unit"], {}), opened))
            layout.addWidget(body)
            toggle = button("", "chevron-right")
            toggle.setToolTip("展开或收起基地机组")
            toggle.setCheckable(True)
            toggle.setChecked(site in self.collapsed_sites)
            toggle.setFixedWidth(30)
            title_layout.addWidget(toggle)
            toggle.toggled.connect(lambda collapsed, area=body: area.setVisible(not collapsed))
            toggle.toggled.connect(lambda collapsed, code=site: self.collapsed_sites.add(code)
                                   if collapsed else self.collapsed_sites.discard(code))
            body.setVisible(not toggle.isChecked())
            self.groups[site] = group
            self.box.addWidget(group)
        if not grouped:
            self.box.addWidget(plain_label("所选范围暂无检测数据", "muted"))
        self.updateGeometry()

    @staticmethod
    def _row_grid(host):
        grid = QGridLayout(host)
        grid.setContentsMargins(4, 7, 4, 7)
        grid.setHorizontalSpacing(16)
        for column, minimum, stretch in ((0, 125, 10), (1, 104, 7), (2, 175, 11), (3, 210, 13), (4, 76, 0)):
            grid.setColumnMinimumWidth(column, minimum)
            grid.setColumnStretch(column, stretch)
        return grid

    def _unit_row(self, snapshot, info, opened):
        unit, outage = snapshot["unit"], snapshot["outage"]
        row = QWidget()
        row.setObjectName("unitRow")
        grid = self._row_grid(row)
        grid.addWidget(plain_label(f"{unit}号机组\n第{snapshot.get('order', '—')}次大修 · {outage}", "unitName"), 0, 0)
        tubes = snapshot.get("tubes") or []
        counts = Counter(tube.get("coverage") for tube in tubes)
        depths = [valid_depth(tube) for tube in tubes if valid_depth(tube) is not None]
        maximum = max(depths) if depths else None
        depth = QWidget()
        depth_box = QVBoxLayout(depth)
        depth_box.setContentsMargins(0, 0, 0, 0)
        depth_box.setSpacing(5)
        peak = plain_label(f"{maximum:g}%" if maximum is not None else "/", "unitDepth")
        color = self.colors[sum(maximum >= level for level in self.levels)] if maximum is not None else "#9aaeb7"
        peak.setStyleSheet(f"color:{color};")
        depth_box.addWidget(peak)
        meter = self._meter(maximum or 0)
        meter.setStyleSheet(f"QProgressBar::chunk {{ background:{color}; }}")
        depth_box.addWidget(meter)
        grid.addWidget(depth, 0, 1)
        reported = len(tubes) - counts["missing"]
        plugged_count = sum(1 for tube in tubes
                            if tube.get("state") == "plugged" or "plugged" in (tube.get("state_badges") or []))
        denom = snapshot.get("plan_denominator") or len(tubes)
        denom_tag = f"（计划）" if snapshot.get("plan_denominator") else ""
        coverage = QWidget()
        coverage_box = QVBoxLayout(coverage)
        coverage_box.setContentsMargins(0, 0, 0, 0)
        coverage_box.setSpacing(5)
        rate = reported / denom * 100 if denom else 0
        plug_note = f"，其中堵管 {plugged_count} 根" if plugged_count else ""
        coverage_box.addWidget(plain_label(f"{rate:g}%{denom_tag}  ·  {reported}/{denom} 根有检测记录{plug_note}",
                                           "unitCoverage"))
        coverage_box.addWidget(self._meter(rate))
        grid.addWidget(coverage, 0, 2)
        composition = QWidget()
        composition_box = QVBoxLayout(composition)
        composition_box.setContentsMargins(0, 0, 0, 0)
        composition_box.setSpacing(4)
        composition_heading = QHBoxLayout()
        composition_heading.addWidget(plain_label(f"WAR {counts['defect']} 根"), 1)
        missing = button(f"无记录 {counts['missing']} 根")
        missing.setObjectName("disclosureHeader")
        numbers = [int(tube["tube"]) for tube in tubes if tube.get("coverage") == "missing"]
        missing.clicked.connect(lambda: self.tubesRequested.emit(unit, outage, numbers, "detection"))
        composition_heading.addWidget(missing)
        composition_box.addLayout(composition_heading)
        composition_box.addWidget(CompositionStrip(counts, none_color=self.none_color))
        grid.addWidget(composition, 0, 3)
        view = button("查看管板", "search", lambda: self.plateRequested.emit(unit, outage))
        view.setMinimumWidth(0)
        grid.addWidget(view, 0, 4)
        history = list(info.get("history") or [])
        for entry in history:
            self.history[(unit, entry["outage"])] = entry
        detected = sum(bool(entry.get("records")) for entry in history)
        gaps = list(info.get("missing_outages") or [])
        maintenance_only = [entry["outage"] for entry in history if not entry.get("records")]
        key = ("unit", unit)
        disclosure = Disclosure(
            f"历次大修记录与完整性 · 检测 {detected} 次 · 缺口 {len(gaps) + len(maintenance_only)} 次",
            lambda: self._unit_history(unit, history, gaps, maintenance_only, opened),
            expanded=key in opened)
        self.disclosures[key] = disclosure
        grid.addWidget(disclosure, 1, 0, 1, 5)
        self.rows[unit] = row
        return row

    @staticmethod
    def _meter(value):
        meter = QProgressBar()
        meter.setObjectName("unitMeter")
        meter.setRange(0, 1000)
        meter.setValue(round(value * 10))
        meter.setTextVisible(False)
        meter.setFixedHeight(4)
        return meter

    def _unit_history(self, unit, entries, gaps, maintenance_only, opened):
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(12, 2, 2, 8)
        if gaps:
            layout.addWidget(plain_label("本库编号缺口（无检测及维护记录）：" + "、".join(gaps)))
        if maintenance_only:
            layout.addWidget(plain_label("仅有维护、无检测记录的大修：" + "、".join(maintenance_only)))
        layout.addWidget(plain_label("此处列全库该机组历史；编号缺口不代表实际未大修。无维护记录不代表正常。", "muted"))
        for entry in sorted(entries, key=lambda item: item.get("order", 0)):
            outage = entry["outage"]
            counts = entry.get("counts") or {}
            reported = 50 - len(entry["missing_tubes"]) if "missing_tubes" in entry else sum(
                value for key, value in counts.items() if key != "missing")
            states = " · ".join(f"{STATE_NAMES.get(key, key)} {len(numbers)}" for key, numbers in
                                (entry.get("state_tubes") or {}).items() if numbers)
            title = (f"{outage} · 检测 {reported}/50 · WAR {counts.get('defect', 0)}"
                     f" · NDD {counts.get('NDD', 0)} · {states or '无维护记录'}")
            key = ("outage", unit, outage)
            disclosure = Disclosure(title, lambda value=entry: self._outage_details(unit, value, opened),
                                    expanded=key in opened)
            self.disclosures[key] = disclosure
            layout.addWidget(disclosure)
        return host

    def _outage_details(self, unit, entry, opened):
        outage = entry["outage"]
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(16, 2, 4, 8)
        actions = QHBoxLayout()
        actions.addWidget(button("原始检测表", "files", lambda: self.recordsRequested.emit(unit, outage)))
        actions.addWidget(button("查看本次管板", "search", lambda: self.plateRequested.emit(unit, outage)))
        actions.addWidget(button("完整性与维护来源", "history", lambda: self.historyRequested.emit(unit, outage)))
        actions.addStretch()
        layout.addLayout(actions)
        layout.addWidget(plain_label(f"检测记录 · 统计采用 {entry.get('records', 0)} 条检测记录", "unitName"))
        for key, title in (("defect", "WAR"), ("NDD", "NDD"), ("incomplete", "待核对")):
            layout.addWidget(plain_label(f"{title}管号：" + self._numbers((entry.get("detection_tubes") or {}).get(key))))
        for key, title, kind in (
            ("missing_tubes", "缺检测记录", "detection"),
            ("incomplete_tubes", "结论待核对", "detection"),
            ("unquantified_tubes", "缺有效磨损深度", "detection"),
            ("state_missing_tubes", "截至本次无维护记录", "state"),
            ("state_current_missing_tubes", "本次无维护记录", "state"),
            ("state_review_tubes", "状态或维护顺序待核对", "state"),
        ):
            numbers = list(entry.get(key) or [])
            line = QHBoxLayout()
            line.addWidget(plain_label(f"{title}管号：{self._numbers(numbers)}"), 1)
            control = button("查看管号", "search")
            control.setObjectName("disclosureHeader")
            control.setToolTip(f"{title}管号：{self._numbers(numbers)}")
            control.setEnabled(bool(numbers))
            control.clicked.connect(lambda _=False, values=numbers, mode=kind:
                                    self.tubesRequested.emit(unit, outage, values, mode))
            line.addWidget(control)
            layout.addLayout(line)
        for key, numbers in (entry.get("state_tubes") or {}).items():
            if numbers:
                layout.addWidget(plain_label(f"截至本次有效{STATE_NAMES.get(key, key)}管号：{self._numbers(numbers)}"))
        if entry.get("inherited_plug_tubes"):
            layout.addWidget(plain_label("沿用历史堵管：" + self._numbers(entry["inherited_plug_tubes"])))
        sources = entry.get("state_sources") or []
        if sources:
            key = ("sources", unit, outage)
            disclosure = Disclosure(f"最近维护原文与来源 · {len(sources)} 根", lambda: self._sources(sources),
                                    expanded=key in opened)
            self.disclosures[key] = disclosure
            layout.addWidget(disclosure)
        return host

    @staticmethod
    def _numbers(numbers):
        return "全部 50 根（1–50）" if len(numbers or []) == 50 else "、".join(map(str, numbers or [])) or "无"

    @staticmethod
    def _sources(sources):
        table = QTableWidget(len(sources), 6)
        table.setHorizontalHeaderLabels(["管号", "最近维护大修", "有效状态", "原始备注", "来源", "待核对原因"])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().hide()
        table.horizontalHeader().setStretchLastSection(True)
        table.setMinimumHeight(180)
        table.setMaximumHeight(350)
        table.setColumnWidth(3, 280)
        table.setColumnWidth(4, 220)
        for row, record in enumerate(sources):
            for column, value in enumerate((record.get("tube", ""), record.get("outage", ""), record.get("label", ""),
                                            record.get("note", ""), record.get("source", ""),
                                            "；".join(record.get("warnings") or []))):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                table.setItem(row, column, item)
        return table
