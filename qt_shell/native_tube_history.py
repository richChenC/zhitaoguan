"""Native, lazily expanded original records for a single physical tube."""
from __future__ import annotations

import math
import re
from html import escape
from pathlib import Path

from PySide6.QtCharts import QCategoryAxis, QScatterSeries
from PySide6.QtCore import QIODevice, QSaveFile, Qt, Signal
from PySide6.QtGui import QCursor, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFileDialog, QHBoxLayout, QPushButton, QSizePolicy,
    QTableWidget, QTableWidgetItem, QToolTip, QVBoxLayout, QWidget,
)

from .native_components import STATE_NAMES, ToolFlowLayout, button, icon
from .native_unit_overview import Disclosure, plain_label


def valid_depth(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 100


def detection(point):
    codes = {str(row.get("indication") or "").strip().upper() for row in point.get("findings") or []}
    if "WAR" in codes or point.get("conclusion") == "WAR":
        return "WAR"
    if "NDD" in codes or point.get("ndd") or point.get("conclusion") == "NDD":
        return "NDD"
    return "无结论"


def report_depth(point, ndd_zero):
    if detection(point) == "NDD":
        return 0 if ndd_zero else None
    value = point.get("report_max_depth")
    if valid_depth(value):
        return value
    depths = [row["percent"] for row in point.get("findings") or []
              if str(row.get("indication") or "").strip().upper() == "WAR" and valid_depth(row.get("percent"))]
    return max(depths) if depths else None


def maintenance(point):
    events = set(point.get("current_events") or [])
    if point.get("replaced"):
        events.add("replaced")
    current = [key for key in ("replaced", "plugged", "shifted", "normal") if key in events]
    if current:
        return " / ".join(STATE_NAMES[key] for key in current)
    inherited = [key for key in ("plugged", "shifted") if point.get(key) or point.get("state") == key]
    return " / ".join(STATE_NAMES[key] + "（沿用）" for key in inherited) or "维护未记录"


def position_key(value):
    raw = str(value or "").strip()
    match = re.match(r"^(P\d+)(?=$|[\s+-])", raw, re.I)
    return match[1].upper() if match else raw


def position_series(points, ndd_zero):
    locations = {position_key(row.get("location")) for point in points for row in point.get("findings") or []
                 if str(row.get("indication") or "").strip().upper() == "WAR" and row.get("location")}
    locations = sorted(locations, key=lambda text: tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold()) for part in re.split(r"(\d+)", text)))
    groups, breaks, evidence = {}, {}, {}
    for location in locations:
        values, reset, previous = [], set(), None
        for point in points:
            rows = [row for row in point.get("findings") or []
                    if str(row.get("indication") or "").strip().upper() == "WAR"
                    and position_key(row.get("location")) == location and valid_depth(row.get("percent"))]
            depth = max((row["percent"] for row in rows), default=None)
            if depth is None and detection(point) == "NDD" and ndd_zero:
                depth = 0
            order = point["order"]
            values.append((order, depth))
            evidence[(location, order)] = (point, rows)
            if (point.get("replaced") or point.get("break_before")
                    or previous and point.get("generation") and previous.get("generation")
                    and point["generation"] != previous["generation"]):
                reset.add(order)
            previous = point if depth is not None else None
        groups[location], breaks[location] = values, reset
    return groups, breaks, evidence


class HistoryRound(Disclosure):
    def __init__(self, point, title, depth, factory, *, expanded=False):
        super().__init__(title, factory, expanded=expanded)
        self.header.setText("")
        self.header.setAccessibleName(title)
        self.header.setMinimumHeight(44)
        self.header.setIcon(QIcon())
        self.header.setProperty("iconName", "")
        row = QHBoxLayout(self.header)
        row.setContentsMargins(5, 4, 5, 4)
        row.setSpacing(8)
        self.indicator = plain_label("-" if expanded else "+")
        self.indicator.setFixedWidth(12)
        row.addWidget(self.indicator)
        row.addWidget(plain_label(point["outage"], "historyOutage"))
        code = detection(point)
        badge = plain_label(code)
        badge.setProperty("historyBadge", "war" if code == "WAR" else "ndd" if code == "NDD" else "blank")
        row.addWidget(badge)
        events = set(point.get("current_events") or [])
        if point.get("replaced"):
            events.add("replaced")
        current = [key for key in ("replaced", "plugged", "shifted", "normal") if key in events]
        inherited = [] if current else [key for key in ("plugged", "shifted")
                                       if point.get(key) or point.get("state") == key]
        for key in current or inherited or ["unrecorded"]:
            badge = plain_label(STATE_NAMES.get(key, "未记录") + ("（沿用）" if key in inherited else ""))
            badge.setProperty("historyBadge", key)
            row.addWidget(badge)
        if point.get("generation", 1) > 1:
            row.addWidget(plain_label(f"第 {point['generation']} 代", "muted"))
        row.addStretch()
        row.addWidget(plain_label(depth, "historyDepth"))

    def set_expanded(self, expanded):
        super().set_expanded(expanded)
        self.header.setIcon(QIcon())
        self.header.setProperty("iconName", "")
        if hasattr(self, "indicator"):
            self.indicator.setText("-" if expanded else "+")


class TubeHistoryView(QWidget):
    recordsRequested = Signal(dict)

    def __init__(self, client=None, permissions=None, parent=None):
        super().__init__(parent)
        self.client, self.permissions = client, permissions
        self.theme, self.animations, self.point_labels = "light", False, False
        self._signature = self._scope = None
        self._hidden_positions = set()
        self._export_busy = False
        self._restored_state = None
        self.rounds, self.points = {}, []
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(10)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.intro = QWidget()
        intro = QVBoxLayout(self.intro)
        intro.setContentsMargins(0, 0, 0, 0)
        self.box.addWidget(self.intro)
        self.subject = plain_label("单管完整历史", "sectionHeading")
        intro.addWidget(self.subject)
        controls = QHBoxLayout()
        controls.addWidget(button("全部展开", "chevron-down", lambda: self.expand_all(True)))
        controls.addWidget(button("全部折叠", "chevron-right", lambda: self.expand_all(False)))
        self.export = button("导出 CSV", "download", self.export_csv)
        self.export.setEnabled(False)
        self.export.setToolTip("按导出时的数据库记录生成完整历史 CSV")
        controls.addWidget(self.export)
        controls.addStretch()
        intro.addLayout(controls)
        self.metrics = QWidget()
        self.metrics.setObjectName("historyMetrics")
        self.metrics.setFixedHeight(76)
        metrics = QHBoxLayout(self.metrics)
        metrics.setContentsMargins(0, 8, 0, 8)
        self.metric_labels = {}
        for key, title in (("records", "有检测记录"), ("peak", "历史峰值"), ("replacements", "明确换管")):
            column = QVBoxLayout()
            column.addWidget(plain_label(title, "muted"))
            self.metric_labels[key] = plain_label("/", "historyMetricValue")
            column.addWidget(self.metric_labels[key])
            metrics.addLayout(column, 1)
        intro.addWidget(self.metrics)
        from .native_charts import ChartPanel
        self.position_chart = ChartPanel(client=client, permissions=permissions)
        self.position_chart.popout_button.hide()
        self.position_chart.view.setMinimumHeight(260)
        self.toggles = QWidget()
        self.toggle_layout = ToolFlowLayout(self.toggles)
        self.position_chart.layout().insertWidget(0, self.toggles)
        self.box.addWidget(self.position_chart)
        self.events = plain_label("")
        self.box.addWidget(self.events)
        method = Disclosure("历史口径", lambda: plain_label(
            "检测与维护独立展示；不同大修不自动推断缺陷一一对应。"
            "NDD零基线为判定值，非实测。换管、缺测和代次变化断线；无维护资料不能推断换管次数完整。"))
        method.header.toggled.connect(lambda *_: method.header.setIcon(
            icon(method.header.property("iconName"), self.theme)))
        self.box.addWidget(method)
        self.timeline = QWidget()
        self.timeline_box = QVBoxLayout(self.timeline)
        self.timeline_box.setContentsMargins(0, 0, 0, 0)
        self.timeline_box.setSpacing(5)
        self.timeline_box.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.box.addWidget(self.timeline)
        self.status = plain_label("")
        self.box.addWidget(self.status)

    def set_theme(self, theme, animations, point_labels=False):
        self.theme, self.animations, self.point_labels = theme, animations, point_labels
        self.position_chart.set_theme(theme, animations)
        self.position_chart.set_point_labels(point_labels)
        for control in self.findChildren(QPushButton) + self.intro.findChildren(QPushButton):
            if control.property("iconName"):
                control.setIcon(icon(control.property("iconName"), theme))

    def expand_all(self, expanded):
        for disclosure in self.rounds.values():
            disclosure.header.setChecked(expanded)

    def view_state(self):
        return {"scope": self._scope,
                "opened": {key for key, row in self.rounds.items() if row.header.isChecked()},
                "hidden_positions": set(self._hidden_positions)}

    def restore_view_state(self, state):
        self._restored_state = state
        if state.get("scope") == self._scope:
            for key, row in self.rounds.items():
                row.header.setChecked(key in state["opened"])
            self._hidden_positions = set(state["hidden_positions"])
            for index in range(self.toggle_layout.count()):
                toggle = self.toggle_layout.itemAt(index).widget()
                toggle.setChecked(toggle.text() not in self._hidden_positions)
            self._restored_state = None

    def set_data(self, unit, tube, outages, ndd_zero):
        signature = (unit, id(tube), tuple((row["outage"], row["order"]) for row in outages), bool(ndd_zero))
        if signature == self._signature:
            return
        self._signature = signature
        scope = (unit, tube.get("tube"))
        opened = {key for key, row in self.rounds.items() if row.header.isChecked()} if scope == self._scope else set()
        if scope != self._scope:
            self._hidden_positions.clear()
        if self._restored_state and self._restored_state.get("scope") == scope:
            opened = set(self._restored_state["opened"])
            self._hidden_positions = set(self._restored_state["hidden_positions"])
            self._restored_state = None
        self._scope, self.unit, self.tube, self.ndd_zero = scope, unit, tube, ndd_zero
        available = {row["outage"]: row for row in tube.get("series") or []}
        self.points = [available.get(row["outage"], {
            **row, "conclusion": "无检测或维护记录", "records": 0, "findings": [],
        }) for row in outages] if outages else list(tube.get("series") or [])
        self.subject.setText(f"{unit} · {tube.get('tube', '/')}号管 · {tube.get('position') or '位置未记录'}"
                             f" · 完整历史 · {len(self.points)} 次大修")
        depths = [value for point in self.points if (value := report_depth(point, ndd_zero)) is not None]
        self.metric_labels["records"].setText(f"{sum(bool(row.get('records')) for row in self.points)} 次大修")
        self.metric_labels["peak"].setText(f"{max(depths):g}%" if depths else "/")
        self.metric_labels["replacements"].setText(
            f"{sum(bool(row.get('replaced') or 'replaced' in (row.get('current_events') or [])) for row in self.points)} 次")
        self.events.setText("；".join(
            f"{point['outage']}：{maintenance(point)}"
            + (f" · {point.get('maintenance_note')}" if point.get("maintenance_note") else "")
            for point in self.points if any(event != "normal" for event in point.get("current_events") or [])
            or point.get("replaced")))
        self.events.setVisible(bool(self.events.text()))
        while self.timeline_box.count():
            widget = self.timeline_box.takeAt(0).widget()
            if widget:
                widget.hide()
                widget.deleteLater()
        self.rounds = {}
        previous = None
        for point in self.points:
            if previous is not None and point["order"] > previous + 1:
                self.timeline_box.addWidget(plain_label(
                    f"第 {previous + 1} 至 {point['order'] - 1} 次大修：当前机组数据中未找到检测或维护记录，无法判断该管状态。"))
            previous = point["order"]
            value = report_depth(point, ndd_zero)
            depth = "NDD" if detection(point) == "NDD" else f"{value:g}%" if value is not None else "无有效深度"
            if "shifted" in (point.get("current_events") or []):
                signed, unsigned = point.get("maintenance_offset_mm"), point.get("maintenance_unsigned_offset_mm")
                depth = f"{signed:+g} mm" if signed is not None else f"{unsigned:g} mm · 方向待确认" if unsigned is not None else "距离待核对"
            title = f"{point['outage']}  ·  {detection(point)}  ·  {maintenance(point)}"
            if point.get("generation", 1) > 1:
                title += f"  ·  第 {point['generation']} 代"
            title += f"  ·  {depth}"
            disclosure = HistoryRound(point, title, depth, lambda row=point: self._round_body(row),
                                      expanded=point["outage"] in opened)
            self.rounds[point["outage"]] = disclosure
            self.timeline_box.addWidget(disclosure)
        self.export.setEnabled(not self._export_busy and self.client is not None and bool(tube.get("tube"))
                               and (self.permissions is None or "export.create" in self.permissions))
        self.status.clear()
        self._draw_positions()
        self.set_theme(self.theme, self.animations, self.point_labels)

    def _round_body(self, point):
        body = QWidget()
        body.setObjectName("historyRoundBody")
        layout = QVBoxLayout(body)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setContentsMargins(12, 8, 12, 12)
        source = point.get("maintenance_source") or "未提供"
        layout.addWidget(plain_label(f"检测结论：{point.get('conclusion') or '无结论'}"
                                    f" · 检测 {point.get('records', 0)} 条"
                                    f" · WAR {sum(str(row.get('indication') or '').strip().upper() == 'WAR' for row in point.get('findings') or [])} 条"))
        current_maintenance = bool(point.get("current_events") or point.get("replaced"))
        layout.addWidget(plain_label(("本轮维护：" if current_maintenance else "本轮未找到维护记录；状态：")
                                    + maintenance(point)))
        layout.addWidget(plain_label("截至本次有效状态：" + str(point.get("state_label") or "未提供")))
        layout.addWidget(plain_label("原始检测记录", "sectionHeading"))
        findings = point.get("findings") or []
        if findings:
            table = QTableWidget(len(findings), 5)
            table.setObjectName("historyOriginalRecords")
            table.setHorizontalHeaderLabels(["磨损位置", "三字符", "磨损深度", "测量通道", "数据文件"])
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.verticalHeader().hide()
            table.horizontalHeader().setStretchLastSection(True)
            table.setColumnWidth(0, 140)
            table.setColumnWidth(1, 70)
            table.setColumnWidth(2, 90)
            table.setColumnWidth(3, 120)
            table.setFixedHeight(min(360, table.horizontalHeader().sizeHint().height()
                                     + len(findings) * table.verticalHeader().defaultSectionSize() + 22))
            for index, row in enumerate(findings):
                values = (row.get("location") or "/", row.get("indication") or "待核对",
                          f"{row['percent']:g}%" if valid_depth(row.get("percent")) else "/",
                          row.get("channel") or "/", re.split(r"[/\\]", row.get("source") or "")[-1] or "/")
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    item.setToolTip(str(row.get("source") or "") if column == 4 else str(value))
                    table.setItem(index, column, item)
            layout.addWidget(table)
        else:
            layout.addWidget(plain_label("本轮有检测记录但明细未提供" if point.get("records") else "本轮无检测记录"))
        if point.get("maintenance_note"):
            layout.addWidget(plain_label("维护原文：" + str(point["maintenance_note"])))
        if point.get("current_events"):
            layout.addWidget(plain_label("维护来源：" + source))
        if point.get("replaced") and point.get("records"):
            layout.addWidget(plain_label("本次检测与换管先后未推定，检测记录的管子代次须核对。"))
        if point.get("needs_review") or point.get("warnings"):
            layout.addWidget(plain_label("待核对：" + "；".join(point.get("warnings") or ["维护信息待核对"])))
        if point.get("records"):
            jump = button("在工作台查看原始记录", "database", lambda: self._open_records(point["outage"]))
            layout.addWidget(jump, 0, Qt.AlignmentFlag.AlignLeft)
        return body

    def _open_records(self, outage):
        match = re.fullmatch(r"([A-Z]+)(\d+)", self.unit)
        if match:
            self.recordsRequested.emit({"site": match[1], "unit": match[2],
                                        "outage": outage, "thimble": str(self.tube["tube"])})

    def _draw_positions(self):
        groups, breaks, evidence = position_series(self.points, self.ndd_zero)
        self.position_chart.setVisible(bool(groups))
        self.position_chart.lines("按磨损位置变化", groups,
            "同一P位逐次取最大报告深度，原始位置和来源保留在记录中；不推断跨次缺陷一一对应。"
            + ("明确NDD按0基线显示，非实测；" if self.ndd_zero else "NDD不计深度；")
            + "换管、代次变化和缺测断线。", "磨损深度（壁厚%）", breaks=breaks)
        chart = self.position_chart.view.chart()
        chart.legend().hide()
        while self.toggle_layout.count():
            item = self.toggle_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        for location in groups:
            toggle = QCheckBox(location)
            toggle.setChecked(location not in self._hidden_positions)
            toggle.toggled.connect(lambda checked, name=location: self._toggle_position(name, checked))
            self.toggle_layout.addWidget(toggle)
            self._toggle_position(location, toggle.isChecked())
        if self.points:
            old_axes = chart.axes(Qt.Orientation.Horizontal)
            axis = QCategoryAxis()
            axis.setLabelsPosition(QCategoryAxis.AxisLabelsPosition.AxisLabelsPositionOnValue)
            axis.setStartValue(self.points[0]["order"] - .5)
            stride = max(1, math.ceil(len(self.points) / 12))
            for index, point in enumerate(self.points):
                if index % stride == 0 or index == len(self.points) - 1:
                    axis.append(point["outage"], point["order"])
            chart.addAxis(axis, Qt.AlignmentFlag.AlignBottom)
            axis.setRange(self.points[0]["order"] - .5, self.points[-1]["order"] + .5)
            for series in chart.series():
                for old in old_axes:
                    series.detachAxis(old)
                series.attachAxis(axis)
                if isinstance(series, QScatterSeries):
                    series.hovered.connect(lambda point, active, name=series.name(): self._hover_position(
                        name, round(point.x()), evidence, active))
            for old in old_axes:
                chart.removeAxis(old)
                old.deleteLater()

    def _toggle_position(self, location, checked):
        if checked:
            self._hidden_positions.discard(location)
        else:
            self._hidden_positions.add(location)
        for series in self.position_chart.view.chart().series():
            if series.name() == location:
                series.setVisible(checked)

    def _hover_position(self, location, order, evidence, active):
        if not active:
            QToolTip.hideText()
            return
        point, rows = evidence.get((location, order), ({}, []))
        lines = [f"{point.get('outage', '')} · {location} · {maintenance(point)}"]
        lines += [f"{row.get('location')} · {row.get('percent')}% · {row.get('channel') or '/'}\n{row.get('source') or '/'}"
                  for row in rows]
        if not rows:
            lines.append("NDD 0 基线（判定值，非实测）")
        QToolTip.showText(QCursor.pos(), "<qt>" + "<br>".join(escape(line) for line in lines) + "</qt>")

    def export_csv(self):
        if not self.export.isEnabled():
            return
        match = re.fullmatch(r"([A-Z]+)(\d+)", self.unit)
        if not match:
            return
        target, _ = QFileDialog.getSaveFileName(
            self, "导出完整历史 CSV", f"{self.unit}_{self.tube['tube']}号管_完整历史.csv", "CSV (*.csv)")
        if not target:
            return
        self.export.setEnabled(False)
        self._export_busy = True
        exported_scope = f"{self.unit} · {self.tube['tube']}号管"
        self.status.setText("正在生成完整历史 CSV...")
        def complete(data, error):
            self._export_busy = False
            self.export.setEnabled(self.permissions is None or "export.create" in self.permissions)
            if error or not data:
                self.status.setText(error or "完整历史导出失败")
                return
            try:
                content = Path(data["file_path"]).read_bytes()
                output = QSaveFile(target)
                if (not output.open(QIODevice.OpenModeFlag.WriteOnly)
                        or output.write(content) != len(content) or not output.commit()):
                    raise OSError(output.errorString())
                self.status.setText(f"{exported_scope} · 已保存 {data.get('rows', 0)} 行：{target}")
            except (KeyError, OSError) as exc:
                self.status.setText(f"完整历史导出失败：{exc}")
        self.client.post("/api/analysis/tube-history/export", {
            "site": match[1], "unit": int(match[2]), "tube": self.tube["tube"], "ndd_zero": self.ndd_zero,
        }, complete)
