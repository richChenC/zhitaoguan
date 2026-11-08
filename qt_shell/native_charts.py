"""Qt Charts visualization of the backend's reviewed statistical dataset."""
from __future__ import annotations

from collections import Counter, defaultdict

from PySide6.QtCharts import (
    QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QLineSeries,
    QScatterSeries, QValueAxis,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QHBoxLayout, QLabel, QSpinBox, QSplitter, QTabWidget, QTableWidget,
    QTableWidgetItem, QToolTip, QVBoxLayout, QWidget,
)

from .native_components import PlateMap, button, export_widget_image
from .native_analysis_data import channel_frequency, depth_distribution, status_change, valid_depth

PALETTE = ["#1874b9", "#b28a22", "#b45e73", "#648743", "#bb7540"]


class ChartPanel(QWidget):
    pointSelected = Signal(int)
    observationSelected = Signal(str, int)
    def __init__(self, parent=None, *, client=None, permissions=None):
        super().__init__(parent)
        self.client = client
        self.theme = "light"
        self.animations = False
        layout = QVBoxLayout(self)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        toolbar = QHBoxLayout()
        toolbar.addStretch()
        export = button("导出 PNG", "download", self.export)
        export.setEnabled(client is not None and (permissions is None or "export.create" in permissions))
        toolbar.addWidget(export)
        toolbar.addWidget(button("独立窗口", "box", self.fullscreen))
        layout.addLayout(toolbar)
        self.view = QChartView()
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setMinimumHeight(280)
        layout.addWidget(self.view, 1)
        self.contract = None

    def export(self):
        export_widget_image(self, self.client, self.view, "导出图表")

    def fullscreen(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(self.view.chart().title())
        dialog.resize(1200, 800)
        layout = QVBoxLayout(dialog)
        layout.addWidget(self.view)
        dialog.exec()
        self.layout().addWidget(self.view, 1)

    def set_theme(self, theme, animations):
        self.theme, self.animations = theme, animations
        chart = self.view.chart()
        # QChart applies its palette to existing series when the theme changes.
        styles = []
        for series in chart.series():
            if isinstance(series, QScatterSeries):
                styles.append((series, series.color(), series.borderColor(), series.markerShape()))
            elif isinstance(series, QLineSeries):
                styles.append((series, series.pen()))
            elif isinstance(series, QBarSeries):
                styles.extend((bar, bar.color(), bar.borderColor()) for bar in series.barSets())
        legends = [(marker, marker.isVisible()) for marker in chart.legend().markers()]
        chart.setTheme(QChart.ChartTheme.ChartThemeDark if theme == "dark" else QChart.ChartTheme.ChartThemeLight)
        background = QColor("#292f33" if theme == "dark" else "white")
        chart.setBackgroundBrush(background)
        chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations if animations
                                  else QChart.AnimationOption.NoAnimation)
        for style in styles:
            series = style[0]
            if isinstance(series, QScatterSeries):
                series.setColor(background if series.property("partialObservation") else style[1])
                series.setBorderColor(style[2])
                series.setMarkerShape(style[3])
            elif isinstance(series, QLineSeries):
                series.setPen(style[1])
            else:
                series.setColor(style[1])
                series.setBorderColor(style[2])
        for marker, visible in legends:
            marker.setVisible(visible)

    def _new(self, title, note):
        self.note.setText(note)
        chart = QChart()
        chart.setTitle(title)
        chart.setTheme(QChart.ChartTheme.ChartThemeDark if self.theme == "dark" else QChart.ChartTheme.ChartThemeLight)
        chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations if self.animations
                                  else QChart.AnimationOption.NoAnimation)
        chart.setBackgroundBrush(QColor("#292f33" if self.theme == "dark" else "white"))
        chart.setMargins(__import__("PySide6.QtCore", fromlist=["QMargins"]).QMargins(12, 10, 16, 10))
        chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
        previous = self.view.chart()
        self.view.setChart(chart)
        if previous is not None:
            previous.deleteLater()
        return chart

    @staticmethod
    def _hover(point, active, label):
        if active:
            from PySide6.QtGui import QCursor
            QToolTip.showText(QCursor.pos(), f"{label} · 第 {point.x():g} 次 · {point.y():g}")
        else:
            QToolTip.hideText()

    def lines(self, title, groups, note, y_title="报告深度合计（百分点）", *, breaks=None, partial=None):
        if len(groups) > 8:
            note += f"；共 {len(groups)} 组，悬停查看名称与数值"
        chart = self._new(title, note)
        chart.legend().setVisible(len(groups) <= 8)
        points = []
        for i, (name, values) in enumerate(groups.items()):
            values = sorted((float(x), float(y)) for x, y in values if y is not None)
            points.extend(values)
            color = QColor(PALETTE[i % len(PALETTE)])
            for incomplete in (False, True):
                marker = QScatterSeries()
                marker.setName(name)
                marker.setMarkerSize(8)
                marker.setMarkerShape((QScatterSeries.MarkerShape.MarkerShapeCircle,
                                       QScatterSeries.MarkerShape.MarkerShapeRectangle)[i % 2])
                marker.setProperty("partialObservation", incomplete)
                for x, y in values:
                    if (x in (partial or {}).get(name, set())) == incomplete:
                        marker.append(x, y)
                marker.hovered.connect(lambda p, active, label=name: self._hover(p, active, label))
                marker.clicked.connect(lambda p, label=name: self.observationSelected.emit(label, round(p.x())))
                chart.addSeries(marker)
                marker.setColor(QColor("#292f33" if self.theme == "dark" else "white") if incomplete else color)
                marker.setBorderColor(color)
                if incomplete:
                    for legend_marker in chart.legend().markers(marker):
                        legend_marker.setVisible(False)
            # A missing physical outage breaks the line; it is never filled as zero.
            segment = []
            for value in values + [(float("inf"), 0)]:
                if segment and (value[0] != segment[-1][0] + 1
                                or value[0] in (breaks or {}).get(name, set())):
                    if len(segment) > 1:
                        line = QLineSeries()
                        for x, y in segment:
                            line.append(x, y)
                        chart.addSeries(line)
                        line.setPen(QPen(color, 2, [Qt.PenStyle.SolidLine, Qt.PenStyle.DashLine,
                                                   Qt.PenStyle.DotLine][i % 3]))
                        for item in chart.legend().markers(line):
                            item.setVisible(False)
                    segment = []
                segment.append(value)
        chart.createDefaultAxes()
        for axis in chart.axes(Qt.Orientation.Horizontal):
            axis.setTitleText("实际大修轮次")
            if points:
                axis.setRange(max(0, min(x for x, _ in points) - .5), max(x for x, _ in points) + .5)
            if isinstance(axis, QValueAxis):
                axis.setLabelFormat("%g")
        for axis in chart.axes(Qt.Orientation.Vertical):
            axis.setTitleText(y_title)
        self.contract = {"family": "line-with-observed-markers", "points": points, "groups": groups,
                         "breaks": breaks or {}, "partial": partial or {}}

    def scatter(self, title, values, note):
        chart = self._new(title, note)
        series = QScatterSeries()
        series.setName("量化 WAR")
        series.setMarkerSize(8)
        for x, y in values:
            series.append(x, y)
        series.hovered.connect(lambda point, active: QToolTip.showText(
            __import__("PySide6.QtGui", fromlist=["QCursor"]).QCursor.pos(),
            f"{point.x():g}号管 · {point.y():g}%") if active else QToolTip.hideText())
        series.clicked.connect(lambda point: self.pointSelected.emit(round(point.x())))
        chart.addSeries(series)
        series.setColor(QColor(PALETTE[0]))
        series.setBorderColor(QColor("#15527f"))
        chart.createDefaultAxes()
        for axis in chart.axes(Qt.Orientation.Horizontal):
            axis.setTitleText("通道编号")
            axis.setRange(0, 51)
        for axis in chart.axes(Qt.Orientation.Vertical):
            axis.setTitleText("最大报告深度（壁厚%）")
            axis.setRange(0, 100)
        chart.legend().hide()
        self.contract = {"family": "scatter", "points": values}

    def bars(self, title, values, note, y_title="管数"):
        chart = self._new(title, note)
        series = QBarSeries()
        bar = QBarSet(y_title)
        bar.append([float(value or 0) for _, value in values])
        series.append(bar)
        series.setLabelsVisible(len(values) <= 12)
        chart.addSeries(series)
        bar.setColor(QColor(PALETTE[0]))
        axis = QBarCategoryAxis()
        axis.append([str(label) for label, _ in values])
        if len(values) > 12:
            axis.setLabelsAngle(-60)
        chart.addAxis(axis, Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(axis)
        vertical = QValueAxis()
        data = [float(value or 0) for _, value in values] or [0]
        vertical.setRange(min(0, min(data) * 1.15), max(1, max(data) * 1.2))
        vertical.setTitleText(y_title)
        chart.addAxis(vertical, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(vertical)
        chart.legend().hide()
        self.contract = {"family": "bar", "values": values}


class VisualizationWorkspace(QTabWidget):
    scopeChanged = Signal(dict)

    def __init__(self, parent=None, *, client=None, permissions=None):
        super().__init__(parent)
        self.client = client
        self.data = {}
        self._longitudinal_cache = {}
        self._longitudinal_pending = set()
        self._longitudinal_request = 0
        self._selected_tube = 1
        self._history_outages = None
        def panel():
            return ChartPanel(client=client, permissions=permissions)
        self.overview = panel()
        self.addTab(self.overview, "总体概况")
        self.trends = QTabWidget()
        self.total, self.position, self.increment = panel(), panel(), panel()
        self.trends.addTab(self.total, "群厂趋势")
        self.trends.addTab(self.position, "P 位趋势")
        self.trends.addTab(self.increment, "相邻增量")
        total_controls = QHBoxLayout()
        self.comparison_mode = QComboBox()
        for text, value in (("全部机组汇总", "all"), ("单机趋势", "single"), ("自选对比", "compare")):
            self.comparison_mode.addItem(text, value)
        self.total_metric = QComboBox()
        self.total_metric.addItem("报告深度", "report")
        self.total_metric.addItem("匹配增量", "increment")
        self.focus_unit = QComboBox()
        self.comparison_units = None
        self.choose_units = button("选择对比机组", "files", self.select_comparison_units)
        for control in (self.comparison_mode, self.focus_unit, self.choose_units, self.total_metric):
            total_controls.addWidget(control)
        total_controls.addStretch()
        self.total.layout().insertLayout(0, total_controls)
        self.comparison_mode.currentIndexChanged.connect(self.refresh_total)
        self.focus_unit.currentIndexChanged.connect(self.refresh_total)
        self.total_metric.currentIndexChanged.connect(self.refresh_total)
        self.total_metric.currentIndexChanged.connect(self.refresh_trends)
        self.total.observationSelected.connect(self.open_observation)
        trend_controls = QHBoxLayout()
        self.trend_unit = QComboBox()
        self.trend_metric = QComboBox()
        for text, value in (("深度合计", "sum"), ("每管平均", "mean"), ("P 位占比", "share")):
            self.trend_metric.addItem(text, value)
        trend_controls.addWidget(QLabel("机组"))
        trend_controls.addWidget(self.trend_unit)
        trend_controls.addWidget(QLabel("P 位口径"))
        trend_controls.addWidget(self.trend_metric)
        trend_controls.addStretch()
        self.position.layout().insertLayout(0, trend_controls)
        self.trend_unit.currentIndexChanged.connect(self.refresh_trends)
        self.trend_metric.currentIndexChanged.connect(self.refresh_trends)
        self.addTab(self.trends, "磨损趋势")
        plate_page = QWidget()
        layout = QVBoxLayout(plate_page)
        controls = QHBoxLayout()
        self.snapshot = QComboBox()
        self.mode = QComboBox()
        self.mode.addItem("最大报告深度", "depth")
        self.mode.addItem("维护状态", "state")
        self.mode.addItem("检测覆盖", "coverage")
        self.mode.addItem("历次最大深度", "history_depth")
        self.mode.addItem("历次明确换管", "history_replaced")
        controls.addWidget(self.snapshot, 1)
        controls.addWidget(self.mode)
        self.plate_export = button("导出 PNG", "download", self.export_plate)
        self.plate_export.setEnabled(client is not None and (permissions is None or "export.create" in permissions))
        controls.addWidget(button("选择历史范围", "files", self.choose_history))
        controls.addWidget(self.plate_export)
        layout.addLayout(controls)
        body = QSplitter()
        self.plate = PlateMap()
        body.addWidget(self.plate)
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setMinimumWidth(240)
        body.addWidget(self.details)
        body.setSizes([650, 300])
        layout.addWidget(body, 1)
        self.snapshot.currentIndexChanged.connect(self._snapshot_selected)
        self.mode.currentIndexChanged.connect(self.refresh_snapshot)
        self.plate.tubeClicked.connect(self._tube_selected)
        self.addTab(plate_page, "管板分布")
        self.risk = QTabWidget()
        self.states, self.depths, self.longitudinal, self.replacements = panel(), panel(), panel(), panel()
        self.scatter_panel, self.frequency = panel(), panel()
        self.scatter_panel.pointSelected.connect(self._tube_selected)
        for text, panel in (("状态构成", self.states), ("深度分布", self.depths),
                             ("通道散点", self.scatter_panel), ("位置集中度", self.frequency),
                             ("单管历史", self.longitudinal), ("累计换管", self.replacements)):
            self.risk.addTab(panel, text)
        self.addTab(self.risk, "变化与状态")
        distribution_controls = QHBoxLayout()
        self.distribution_scope = QComboBox()
        self.distribution_scope.addItem("各机组最新大修", "latest")
        self.distribution_scope.addItem("全部筛选大修", "all")
        distribution_controls.addWidget(QLabel("统计范围"))
        distribution_controls.addWidget(self.distribution_scope)
        distribution_controls.addStretch()
        self.depths.layout().insertLayout(0, distribution_controls)
        self.distribution_scope.currentIndexChanged.connect(self.refresh_distribution)
        frequency_controls = QHBoxLayout()
        self.frequency_threshold = QDoubleSpinBox()
        self.frequency_threshold.setRange(0, 100)
        self.frequency_threshold.setValue(30)
        self.frequency_threshold.setSuffix(" %")
        frequency_controls.addWidget(QLabel("严格超过阈值"))
        frequency_controls.addWidget(self.frequency_threshold)
        frequency_controls.addStretch()
        self.frequency.layout().insertLayout(0, frequency_controls)
        self.frequency_threshold.valueChanged.connect(self.refresh_frequency)
        self._build_longitudinal_controls()
        self._build_change_page()

    def _publish_scope(self):
        import re
        current = self.current_snapshot()
        match = re.fullmatch(r"([A-Z]+)(\d+)", current["unit"]) if current else None
        if match:
            self.scopeChanged.emit({"site": match[1], "unit": match[2],
                                    "outage": current["outage"], "thimble": self._selected_tube})

    def _snapshot_selected(self, *_):
        self.refresh_snapshot()
        self._publish_scope()

    def _tube_selected(self, number):
        self.select_tube(number)
        self._publish_scope()

    def set_data(self, data):
        self.data = data
        self._longitudinal_cache.clear()
        self._longitudinal_pending.clear()
        self._longitudinal_request += 1
        self._baseline_scope = None
        summary = data.get("summary") or {}
        self.overview.bars("当前范围检测覆盖", [
            ("已检测", summary.get("reported_tubes", 0)), ("缺少检测", summary.get("missing_tubes", 0))],
            f"当前范围 · {summary.get('records', 0)} 条记录 · {summary.get('units', 0)} 台机组 · "
            f"分母 {summary.get('expected_tubes', 0)} 根管；无记录不等于 NDD")
        groups = defaultdict(list)
        for item in data.get("trends", []):
            order = item.get("order")
            if order is None:
                continue
            groups[item["unit"]].append((order, item.get("total")))
        selected_focus = self.focus_unit.currentData()
        self.focus_unit.blockSignals(True)
        self.focus_unit.clear()
        for unit in sorted(groups):
            self.focus_unit.addItem(unit, unit)
        self.focus_unit.setCurrentIndex(max(0, self.focus_unit.findData(selected_focus)))
        self.focus_unit.blockSignals(False)
        self.refresh_total()
        selected_unit = self.trend_unit.currentData()
        self.trend_unit.blockSignals(True)
        self.trend_unit.clear()
        self.trend_unit.addItem("全部机组", "")
        for unit in sorted(groups):
            self.trend_unit.addItem(unit, unit)
        self.trend_unit.setCurrentIndex(max(0, self.trend_unit.findData(selected_unit)))
        self.trend_unit.blockSignals(False)
        self.refresh_trends()
        self.increment.bars("相邻大修匹配磨损增量", [
            (f"{item['unit']}/{item['outage']}", item["total"]) for item in data.get("increments", [])
            if item.get("total") is not None],
            "仅使用后端确认的一对一匹配；缺失前轮、换管新基准和不确定配对不按零计算", "深度变化（百分点）")
        self.snapshot.blockSignals(True)
        previous = self.snapshot.currentData()
        self.snapshot.clear()
        for i, snapshot in enumerate(data.get("snapshots", [])):
            self.snapshot.addItem(f"{snapshot['unit']} · {snapshot['outage']}", i)
        self.snapshot.setCurrentIndex(max(0, self.snapshot.findData(previous)))
        self.snapshot.blockSignals(False)
        self.refresh_snapshot()
        latest = self.latest_snapshots()
        counts = Counter(tube.get("state_label") or "未记录" for snap in latest.values() for tube in snap["tubes"])
        self.states.bars("各机组最新范围维护状态", list(counts.items()),
                         "每台机组取当前范围内最新大修；维护状态与检测覆盖分别统计")
        self.refresh_distribution()
        self.refresh_frequency()
        self.replacements.bars("机组累计明确换管次数", [
            (unit, sum(tube.get("lifetime_replacements", 0) for tube in snap["tubes"]))
            for unit, snap in latest.items()], "按机组全部已记录历史统计；移位不计为换管", "换管次数")

    def refresh_snapshot(self, *_):
        snapshots = self.data.get("snapshots") or []
        index = self.snapshot.currentData()
        if index is None or not snapshots:
            self.plate.set_data([])
            self.details.setText("当前范围没有检测数据")
            return
        snap = snapshots[index]
        import re
        match = re.search(r"(\d+)$", snap["unit"])
        unit = int(match[1]) if match else 1
        mode = self.mode.currentData()
        rows = [{**tube, "max_percent": tube.get("max_depth")} for tube in snap["tubes"]]
        if mode in ("history_depth", "history_replaced"):
            history = self.selected_history(snap["unit"])
            rows = []
            for number in range(1, 51):
                tubes = [tube for item in history for tube in item["tubes"] if tube["tube"] == number]
                depths = [valid_depth(tube) for tube in tubes if valid_depth(tube) is not None]
                count = sum("replaced" in (tube.get("current_events") or []) for tube in tubes)
                rows.append({"tube": number, "records": sum(tube.get("records", 0) for tube in tubes),
                             "max_percent": max(depths) if depths else None,
                             "history_count": count, "history_outages": len(history)})
        self.plate.set_data(rows, unit, selected=[self._selected_tube], mode=mode)
        self.refresh_change()
        self.select_tube(self._selected_tube)

    def select_tube(self, number):
        self._selected_tube = number
        snapshots = self.data.get("snapshots") or []
        if not snapshots:
            return
        current = snapshots[self.snapshot.currentData() or 0]
        selection_key = (self._longitudinal_request, self.snapshot.currentData(), number)
        if getattr(self, "_selection_render_key", None) == selection_key:
            return
        self._selection_render_key = selection_key
        tube = next((row for row in current["tubes"] if row["tube"] == number), {})
        self.details.setText(f"{current['unit']} · {current['outage']} · {number}号管\n"
                             f"管板位置：{tube.get('position', '')}\n"
                             f"检测记录：{tube.get('records', 0)}\n"
                             f"最大深度：{tube.get('max_depth', '/')}\n"
                             f"状态：{tube.get('state_label', '未记录')}\n"
                             f"备注：{tube.get('remarks', '')}\n来源：{tube.get('source', '')}")
        self.tube_number.blockSignals(True)
        self.tube_number.setValue(number)
        self.tube_number.blockSignals(False)
        self.scatter_panel.scatter(f"{current['unit']} · {current['outage']} 通道最大深度",
                                   [(row["tube"], valid_depth(row)) for row in current["tubes"]
                                    if valid_depth(row) is not None],
                                   "每管每轮取量化 WAR 最大值；NDD、无记录及未量化结果不画为零")
        self.load_longitudinal()
        self.plate.selected = {number}
        self.plate.update()

    def export_plate(self):
        export_widget_image(self, self.client, self.plate, "导出管板图")

    def latest_snapshots(self):
        latest = {}
        for snapshot in self.data.get("snapshots") or []:
            if snapshot["unit"] not in latest or snapshot["order"] > latest[snapshot["unit"]]["order"]:
                latest[snapshot["unit"]] = snapshot
        return latest

    def set_theme(self, theme, animations):
        for panel in self.findChildren(ChartPanel):
            panel.set_theme(theme, animations)

    def refresh_trends(self, *_):
        groups = defaultdict(list)
        metric = self.trend_metric.currentData()
        increment = self.total_metric.currentData() == "increment"
        self.trend_metric.setEnabled(not increment)
        selected = self.trend_unit.currentData()
        items = [item for item in self.data.get("increments" if increment else "trends") or []
                 if not selected or item["unit"] == selected]
        if not selected:
            totals = defaultdict(lambda: {"positions": defaultdict(list), "counts": Counter(),
                                         "unit_count": 0, "partial": False, "total": []})
            expected = len({item["unit"] for item in items})
            for item in items:
                aggregate = totals[item["order"]]
                aggregate["unit_count"] += 1
                aggregate["partial"] |= bool(item.get("partial") or item.get("missing_depth"))
                if item.get("total") is not None:
                    aggregate["total"].append(item["total"])
                for zone, value in item.get("positions", {}).items():
                    if value is not None:
                        aggregate["positions"][zone].append(value)
                        aggregate["counts"][zone] += (item.get("position_stats", {}).get(zone) or {}).get("tubes", 0)
            items = [{"unit": "群厂汇总", "order": order,
                      "positions": {zone: sum(values) for zone, values in item["positions"].items()},
                      "position_stats": {zone: {"total": sum(values), "tubes": item["counts"][zone]}
                                         for zone, values in item["positions"].items()},
                      "total": sum(item["total"]) if item["total"] else None,
                      "partial": item["partial"] or item["unit_count"] < expected}
                     for order, item in sorted(totals.items())]
        partial = defaultdict(set)
        for item in items:
            for zone, value in item.get("positions", {}).items():
                if metric == "mean" and not increment:
                    stats = item.get("position_stats", {}).get(zone) or {}
                    count = stats.get("tubes") or 0
                    value = stats.get("total") / count if stats.get("total") is not None and count else None
                elif metric == "share" and not increment:
                    total = item.get("total")
                    value = value / total * 100 if value is not None and total else None
                name = f"{item['unit']} · {zone}"
                groups[name].append((item["order"], value))
                if item.get("partial"):
                    partial[name].add(item["order"])
        self.position.lines("P 位匹配增量趋势" if increment else "P 位报告深度趋势", groups,
                            ("原始 P 位分类；无量化值不补零；单机组范围" if selected else
                             "原始 P 位分类；按实际大修轮次汇总；参与机组随轮次变化；空心标记为不完整数据"),
                            "匹配深度变化（百分点）" if increment else
                            "占比（%）" if metric == "share" else "每管平均（壁厚%）" if metric == "mean" else "深度合计（百分点）",
                            partial=partial)

    def select_comparison_units(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("选择对比机组")
        layout = QVBoxLayout(dialog)
        checks = []
        for index in range(self.focus_unit.count()):
            unit = self.focus_unit.itemData(index)
            check = QCheckBox(unit)
            check.setChecked(self.comparison_units is None or unit in self.comparison_units)
            checks.append((unit, check))
            layout.addWidget(check)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        controls.accepted.connect(dialog.accept)
        controls.rejected.connect(dialog.reject)
        layout.addWidget(controls)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.comparison_units = {unit for unit, check in checks if check.isChecked()}
            self.comparison_mode.setCurrentIndex(2)
            self.refresh_total()

    def refresh_total(self, *_):
        mode = self.comparison_mode.currentData()
        self.focus_unit.setVisible(mode == "single")
        self.choose_units.setVisible(mode == "compare")
        source = self.data.get("increments" if self.total_metric.currentData() == "increment" else "trends") or []
        chosen = [item for item in source if mode == "all"
                  or (mode == "single" and item["unit"] == self.focus_unit.currentData())
                  or (mode == "compare" and (self.comparison_units is None or item["unit"] in self.comparison_units))]
        groups, partial = defaultdict(list), defaultdict(set)
        if mode == "all":
            rounds = defaultdict(list)
            for item in chosen:
                rounds[item["order"]].append(item)
            expected = len({item["unit"] for item in source})
            for order, items in sorted(rounds.items()):
                valid = [item["total"] for item in items if item.get("total") is not None]
                groups["群厂汇总"].append((order, sum(valid) if valid else None))
                if len(items) < expected or any(item.get("partial") or item.get("missing_depth") for item in items):
                    partial["群厂汇总"].add(order)
        else:
            for item in chosen:
                groups[item["unit"]].append((item["order"], item.get("total")))
                if item.get("partial") or item.get("missing_depth"):
                    partial[item["unit"]].add(item["order"])
        increment = self.total_metric.currentData() == "increment"
        self.total.lines(("群厂" if mode == "all" else "机组") +
                         (" WAR 匹配增量趋势" if increment else " WAR 报告深度趋势"), groups,
                         "按大修轮次汇总，不代表同期对比；空心点为部分数据；缺失不补零。"
                         + ("仅计相邻轮次一对一可靠 WAR 匹配，保留负增量。" if increment else ""),
                         "匹配深度变化（百分点）" if increment else "报告深度合计（百分点）", partial=partial)

    def open_observation(self, unit, order):
        if self.total_metric.currentData() == "report" and unit != "群厂汇总":
            index = next((i for i, snap in enumerate(self.data.get("snapshots") or [])
                          if snap["unit"] == unit and snap["order"] == order), None)
            if index is not None:
                self.snapshot.setCurrentIndex(index)
                self.setCurrentIndex(2)
                self._publish_scope()
                return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{unit} · 第 {order} 次大修来源")
        dialog.resize(1000, 620)
        layout = QVBoxLayout(dialog)
        table = QTableWidget(0, 7)
        table.setHorizontalHeaderLabels(["机组/大修", "管号", "结论", "本次深度", "历史深度", "差值/原因", "来源"])
        entries = []
        if self.total_metric.currentData() == "increment":
            for item in self.data.get("increments") or []:
                if item["order"] == order and (unit == "群厂汇总" or item["unit"] == unit):
                    for match in item.get("items") or []:
                        current, previous = match.get("current") or {}, match.get("previous") or {}
                        entries.append([f"{item['unit']}/{item['outage']}", match["tube"], "WAR",
                                        current.get("percent"), previous.get("percent"),
                                        match["delta"] if match.get("delta") is not None else match.get("reason"),
                                        current.get("report_path") or current.get("source")])
        else:
            for snap in self.data.get("snapshots") or []:
                if snap["order"] == order:
                    for tube in snap["tubes"]:
                        for finding in tube.get("findings") or []:
                            if str(finding.get("indication") or "").strip().upper() == "WAR":
                                entries.append([f"{snap['unit']}/{snap['outage']}", tube["tube"], "WAR",
                                                finding.get("percent"), None, None,
                                                finding.get("report_path") or finding.get("source")])
        table.setRowCount(len(entries))
        for row, values in enumerate(entries):
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem("/" if value is None else str(value)))
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)
        layout.addWidget(button("关闭", "x", dialog.accept))
        dialog.exec()

    def refresh_distribution(self, *_):
        snapshots = (list(self.latest_snapshots().values()) if self.distribution_scope.currentData() == "latest"
                     else self.data.get("snapshots") or [])
        result = depth_distribution(snapshots)
        self.depths.bars("每管最大报告深度 · 5% 分箱", [("NDD", result["NDD"])] + result["bins"],
                         f"{len(snapshots)} 个机组/大修范围；量化 WAR {result['quantified']} 根次；"
                         f"NDD {result['NDD']} 根次（单列）；排除未量化/不完整/缺失 {result['excluded']} 根次。区间左闭右开，末箱含100%。")
        self.depths.contract["distribution"] = result

    def refresh_frequency(self, *_):
        threshold = self.frequency_threshold.value()
        counts = channel_frequency(self.data.get("snapshots") or [], threshold)
        self.frequency.bars("物理孔位超阈值频次", sorted(counts.items(), key=lambda item: (-item[1], item[0])),
                            f"量化 WAR 最大值严格 > {threshold:g}%；同机组/大修/通道只计一次，按实际孔位合并", "根次")

    def selected_history(self, unit):
        return [s for s in self.data.get("snapshots") or [] if s["unit"] == unit
                and (self._history_outages is None or (unit, s["outage"]) in self._history_outages)]

    def choose_history(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("选择历次大修")
        layout = QVBoxLayout(dialog)
        checks = []
        for snap in self.data.get("snapshots") or []:
            check = QCheckBox(f"{snap['unit']} · {snap['outage']}")
            key = (snap["unit"], snap["outage"])
            check.setChecked(self._history_outages is None or key in self._history_outages)
            checks.append((check, key))
            layout.addWidget(check)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._history_outages = {key for check, key in checks if check.isChecked()}
            self.refresh_snapshot()

    def _build_longitudinal_controls(self):
        row = QHBoxLayout()
        self.tube_number = QSpinBox()
        self.tube_number.setRange(1, 50)
        self.tube_number.setPrefix("管号 ")
        self.tube_number.valueChanged.connect(self._tube_selected)
        row.addWidget(self.tube_number)
        self.curve_mode = QComboBox()
        self.curve_mode.addItem("当前寿期与原始报告", "both")
        self.curve_mode.addItem("当前寿期", "life")
        self.curve_mode.addItem("原始报告", "raw")
        self.curve_mode.currentIndexChanged.connect(self.draw_longitudinal)
        row.addWidget(self.curve_mode)
        self.all_tubes = QCheckBox("全部管")
        self.all_tubes.toggled.connect(self.draw_longitudinal)
        row.addWidget(self.all_tubes)
        self.jump = QDoubleSpinBox()
        self.jump.setRange(5, 50)
        self.jump.setValue(20)
        self.jump.setSuffix(" 个百分点")
        row.addWidget(QLabel("突变阈值"))
        row.addWidget(self.jump)
        self.jump.valueChanged.connect(self.load_longitudinal)
        row.addStretch()
        self.longitudinal.layout().insertLayout(0, row)
        self.longitudinal_table = QTableWidget(0, 8)
        self.longitudinal_table.setHorizontalHeaderLabels(
            ["大修", "原始报告", "当前寿期", "变化", "寿期代次", "维护", "突变", "来源/核查"])
        self.longitudinal_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.longitudinal_table.setMaximumHeight(190)
        self.longitudinal.layout().addWidget(self.longitudinal_table)

    def current_snapshot(self):
        snapshots = self.data.get("snapshots") or []
        index = self.snapshot.currentData()
        return snapshots[index] if index is not None and 0 <= index < len(snapshots) else None

    def load_longitudinal(self, *_):
        import re
        from urllib.parse import urlencode
        current = self.current_snapshot()
        if not current:
            return
        match = re.fullmatch(r"([A-Z]+)(\d+)", current["unit"])
        if not match or self.client is None:
            self.longitudinal.lines("单管寿期曲线", {}, "没有可读取的机组范围")
            return
        key = (current["unit"], self.jump.value())
        if key in self._longitudinal_cache:
            self.draw_longitudinal()
            return
        if key in self._longitudinal_pending:
            return
        self._longitudinal_pending.add(key)
        number = self._longitudinal_request
        self.longitudinal.note.setText("正在读取完整寿期与维护记录…")
        def loaded(data, error):
            if number != self._longitudinal_request:
                return
            self._longitudinal_pending.discard(key)
            if error or not data:
                self.longitudinal.lines("单管寿期曲线", {}, error or "读取失败")
                return
            self._longitudinal_cache[key] = data
            self.draw_longitudinal()
        self.client.get("/api/analysis/tube-longitudinal?" + urlencode(
            {"site": match[1], "unit": match[2], "jump": self.jump.value()}), loaded)

    def draw_longitudinal(self, *_):
        current = self.current_snapshot()
        if not current:
            return
        data = self._longitudinal_cache.get((current["unit"], self.jump.value())) or {}
        tube = next((t for t in data.get("tubes") or [] if t["tube"] == self._selected_tube), {})
        points = tube.get("series") or []
        groups, breaks = {}, {}
        selected = data.get("tubes") or [] if self.all_tubes.isChecked() else [tube]
        for selected_tube in selected:
            prefix = f"{selected_tube.get('tube')}号 · " if self.all_tubes.isChecked() else ""
            series_points = selected_tube.get("series") or []
            for title, key, modes in (("当前寿期", "max_depth", ("both", "life")),
                                      ("原始报告", "report_max_depth", ("both", "raw"))):
                if self.curve_mode.currentData() in modes:
                    groups[prefix + title] = [(p["order"], p.get(key)) for p in series_points]
                    breaks[prefix + title] = {p["order"] for p in series_points if p.get("break_before")}
        self.longitudinal.lines(f"{current['unit']} · " +
                                ("全部管寿期曲线" if self.all_tubes.isChecked() else f"{self._selected_tube}号管寿期曲线"), groups,
                                "完整机组历史 · 换管建立新寿期并断线；移位不清零；NDD 的零值有原始结论依据；缺测不补零",
                                "最大深度（壁厚%）", breaks=breaks)
        if self.all_tubes.isChecked():
            self.longitudinal.view.chart().legend().hide()
        self.longitudinal_table.setRowCount(len(points))
        for ri, p in enumerate(points):
            source = "；".join(f.get("source") or "" for f in p.get("findings") or [])
            values = [p["outage"], p.get("report_max_depth"), p.get("max_depth"), p.get("delta"),
                      p.get("generation"), p.get("state_label"), "是" if p.get("jump") else "",
                      "；".join(p.get("warnings") or []) or source or p.get("maintenance_source")]
            for ci, value in enumerate(values):
                self.longitudinal_table.setItem(ri, ci, QTableWidgetItem("/" if value is None else str(value)))
        self.longitudinal_table.resizeColumnsToContents()

    def _build_change_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        self.baseline = QComboBox()
        self.change_filter = QComboBox()
        for text, key in (("全部", "all"), ("有变化", "changed"), ("上升", "up"), ("下降", "down"),
                          ("NDD→WAR", "newWar"), ("维护", "maintenance"), ("待复核", "review"),
                          ("无记录", "missing"), ("≥50%", "high")):
            self.change_filter.addItem(text, key)
        row.addWidget(QLabel("历史基线"))
        row.addWidget(self.baseline, 1)
        row.addWidget(self.change_filter)
        layout.addLayout(row)
        self.change_note = QLabel()
        self.change_note.setWordWrap(True)
        layout.addWidget(self.change_note)
        self.change_table = QTableWidget(0, 7)
        self.change_table.setHorizontalHeaderLabels(["管号", "孔位", "基线最大", "本次最大", "差值", "状态", "不可比原因"])
        self.change_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.change_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.change_table.cellClicked.connect(lambda row, _column: self._tube_selected(
            int(self.change_table.item(row, 0).text())))
        layout.addWidget(self.change_table, 1)
        self.risk.addTab(page, "历次变化核查")
        self.baseline.currentIndexChanged.connect(self.refresh_change)
        self.change_filter.currentIndexChanged.connect(self.refresh_change)
        self.change_result = {}

    def refresh_change(self, *_):
        current = self.current_snapshot()
        if not current:
            self.change_table.setRowCount(0)
            self.change_note.setText("当前范围没有可核查数据")
            return
        combined = {(s["unit"], s["outage"]): s for s in
                    (self.data.get("comparison_baselines") or []) + (self.data.get("snapshots") or [])}
        history = list(combined.values())
        earlier = sorted((s for s in history if s["unit"] == current["unit"] and s["order"] < current["order"]),
                         key=lambda s: s["order"])
        scope = (current["unit"], current["outage"])
        if getattr(self, "_baseline_scope", None) != scope:
            self._baseline_scope = scope
            self.baseline.blockSignals(True)
            self.baseline.clear()
            self.baseline.addItem("无历史基线", "")
            for s in earlier:
                self.baseline.addItem(s["outage"], s["outage"])
            self.baseline.setCurrentIndex(self.baseline.count() - 1)
            self.baseline.blockSignals(False)
        result = status_change(history, current["unit"], current["outage"], baseline=self.baseline.currentData())
        self.change_result = result
        counts = result["counts"]
        self.change_note.setText(f"50通道核查 · 可比 {counts.get('comparable', 0)} · 变化 {counts.get('changed', 0)} · "
                                 f"NDD→WAR {counts.get('newWar', 0)} · 待复核 {counts.get('review', 0)}。"
                                 "差值为通道最大报告深度变化，不能解释为同一缺陷增长；区间换管、移位及位置变化均排除。")
        key = self.change_filter.currentData()
        rows = [r for r in result["rows"] if key == "all" or
                (key == "up" and r["delta"] is not None and r["delta"] > 0) or
                (key == "down" and r["delta"] is not None and r["delta"] < 0) or r.get(key)]
        self.change_table.setRowCount(len(rows))
        for ri, r in enumerate(rows):
            values = [r["tube"], r["current"].get("position"), r["oldDepth"], r["depth"],
                      r["delta"], r["current"].get("state_label"), r["exclusion"]]
            for ci, value in enumerate(values):
                self.change_table.setItem(ri, ci, QTableWidgetItem("/" if value is None else str(value)))
        self.change_table.resizeColumnsToContents()
        self.change_table.horizontalHeader().setStretchLastSection(True)
