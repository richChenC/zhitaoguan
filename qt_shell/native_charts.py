"""Qt Charts visualization of the backend's reviewed statistical dataset."""
from __future__ import annotations

from collections import Counter, defaultdict
from html import escape
import re

from PySide6.QtCharts import (
    QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QLineSeries,
    QScatterSeries, QValueAxis, QHorizontalStackedBarSeries, QAbstractBarSeries,
)
from PySide6.QtCore import QPointF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QGraphicsSimpleTextItem, QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit, QSpinBox, QSplitter,
    QSizePolicy, QStyle, QScrollArea, QTabWidget, QTableWidget, QTableWidgetItem, QToolTip, QVBoxLayout, QWidget,
)

from .native_components import PlateMap, PositionHeatmap, SITE_NAMES, button, export_widget_image, icon
from .native_analysis_data import channel_frequency, depth_distribution, status_change, valid_depth
from .native_unit_overview import UnitOverview

PALETTE = ["#1874b9", "#b28a22", "#b45e73", "#648743", "#bb7540"]


class ChartPanel(QWidget):
    pointSelected = Signal(int)
    observationSelected = Signal(str, int)
    popoutRequested = Signal()
    def __init__(self, parent=None, *, client=None, permissions=None):
        super().__init__(parent)
        self.client = client
        self.theme = "light"
        self.animations = False
        self.point_labels = False
        layout = QVBoxLayout(self)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        toolbar = QHBoxLayout()
        toolbar.addStretch()
        export = button("导出 PNG", "download", self.export)
        export.setEnabled(client is not None and (permissions is None or "export.create" in permissions))
        toolbar.addWidget(export)
        self.expand_button = button("", callback=self.fullscreen)
        self.expand_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarMaxButton))
        self.expand_button.setToolTip("放大查看")
        self.expand_button.setAccessibleName("放大查看")
        self.expand_button.setFixedSize(32, 32)
        toolbar.addWidget(self.expand_button)
        self.popout_button = button("", "external-link", self.popoutRequested.emit)
        self.popout_button.setToolTip("在独立窗口中对比")
        self.popout_button.setAccessibleName("在独立窗口中对比")
        self.popout_button.setFixedSize(32, 32)
        toolbar.addWidget(self.popout_button)
        layout.addLayout(toolbar)
        self.view = QChartView()
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setMinimumHeight(280)
        layout.addWidget(self.view, 1)
        self.contract = None

    def export(self):
        export_widget_image(self, self.client, self.view, "导出图表")

    def fullscreen(self):
        dialog = QDialog(self.window())
        dialog.setWindowTitle(self.view.chart().title())
        dialog.setModal(True)
        dialog.resize(1200, 800)
        layout = QVBoxLayout(dialog)
        host = QWidget()
        host.setObjectName("workspaceBody")
        host.setLayout(self.layout())
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(host)
        layout.addWidget(scroll)
        close = button("退出放大查看", "chevron-left", dialog.accept)
        close.setIcon(icon("chevron-left", self.theme))
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        self.expand_button.setEnabled(False)
        try:
            dialog.showMaximized()
            dialog.exec()
        finally:
            self.setLayout(host.layout())
            self.expand_button.setEnabled(True)
            dialog.deleteLater()

    def set_theme(self, theme, animations):
        self.theme, self.animations = theme, animations
        maximize = self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarMaxButton).pixmap(16, 16)
        painter = QPainter(maximize)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(maximize.rect(), QColor("#e7edef" if theme == "dark" else "#263b43"))
        painter.end()
        self.expand_button.setIcon(QIcon(maximize))
        chart = self.view.chart()
        # QChart applies its palette to existing series when the theme changes.
        styles = []
        for series in chart.series():
            if isinstance(series, QScatterSeries):
                styles.append((series, series.color(), series.borderColor(), series.markerShape()))
            elif isinstance(series, QLineSeries):
                styles.append((series, series.pen()))
            elif isinstance(series, QAbstractBarSeries):
                styles.extend((bar, bar.color(), bar.borderColor()) for bar in series.barSets())
        legends = [(marker, marker.isVisible()) for marker in chart.legend().markers()]
        chart.setTheme(QChart.ChartTheme.ChartThemeDark if theme == "dark" else QChart.ChartTheme.ChartThemeLight)
        background = QColor("#292f33" if theme == "dark" else "white")
        self.view.setBackgroundBrush(background)
        chart.setBackgroundBrush(background)
        chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations if animations
                                  else QChart.AnimationOption.NoAnimation)
        chart.setAnimationDuration(180)
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
        for label in getattr(chart, "_bar_value_labels", []):
            label.setBrush(QColor("#e5eeec" if theme == "dark" else "#23465b"))

    def set_point_labels(self, enabled):
        self.point_labels = bool(enabled)
        for series in self.view.chart().series():
            if isinstance(series, QScatterSeries):
                series.setPointLabelsFormat("@yPoint")
                series.setPointLabelsVisible(self.point_labels)
                series.setPointLabelsClipping(False)
            elif isinstance(series, QBarSeries):
                series.setLabelsVisible(self.point_labels)

    def _new(self, title, note):
        self.note.setText(note)
        chart = QChart()
        chart.setTitle(title)
        chart.setTheme(QChart.ChartTheme.ChartThemeDark if self.theme == "dark" else QChart.ChartTheme.ChartThemeLight)
        chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations if self.animations
                                  else QChart.AnimationOption.NoAnimation)
        chart.setAnimationDuration(180)
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
                marker.setPointLabelsFormat("@yPoint")
                marker.setPointLabelsVisible(self.point_labels)
                marker.setPointLabelsClipping(False)
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
                        line.setName(name)
                        for x, y in segment:
                            line.append(x, y)
                        chart.addSeries(line)
                        line.setPen(QPen(color, 2, [Qt.PenStyle.SolidLine, Qt.PenStyle.DashLine,
                                                   Qt.PenStyle.DotLine][i % 3]))
                        for item in chart.legend().markers(line):
                            item.setVisible(False)
                    segment = []
                segment.append(value)
        # Scatter markers and line segments must share axes; default axes can
        # create one set per series type and draw overlapping axis titles.
        horizontal, vertical = QValueAxis(), QValueAxis()
        horizontal.setTitleText("实际大修轮次")
        horizontal.setLabelFormat("%g")
        vertical.setTitleText(y_title)
        if points:
            horizontal.setRange(max(0, min(x for x, _ in points) - .5), max(x for x, _ in points) + .5)
            low, high = min(y for _, y in points), max(y for _, y in points)
            padding = max(1, (high - min(0, low)) * .08)
            vertical.setRange(min(0, low - padding if low < 0 else 0), max(1, high + padding))
        chart.addAxis(horizontal, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(vertical, Qt.AlignmentFlag.AlignLeft)
        for series in chart.series():
            series.attachAxis(horizontal)
            series.attachAxis(vertical)
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
        series.setPointLabelsFormat("@yPoint")
        series.setPointLabelsVisible(self.point_labels)
        series.setPointLabelsClipping(False)
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
        series.setLabelsVisible(self.point_labels)
        chart.addSeries(series)
        bar.setColor(QColor(PALETTE[0]))
        axis = QBarCategoryAxis()
        axis.append([escape(str(label)) for label, _ in values])
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

    def horizontal_bars(self, title, values, note):
        chart = self._new(title, note)
        series = QHorizontalStackedBarSeries()
        displayed = list(reversed(values))
        for index, (label, value, color) in enumerate(displayed):
            bar = QBarSet(label)
            bar.append([float(value) if i == index else 0 for i in range(len(values))])
            bar.setColor(QColor(color))
            bar.setBorderColor(QColor("#9bafb9") if color == "#ffffff" else QColor(color))
            series.append(bar)
        chart.addSeries(series)
        for bar, (_, _, color) in zip(series.barSets(), displayed):
            bar.setColor(QColor(color))
            bar.setBorderColor(QColor("#9bafb9") if color == "#ffffff" else QColor(color))
        categories = QBarCategoryAxis()
        categories.append([escape(label) for label, _, _ in displayed])
        chart.addAxis(categories, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(categories)
        axis = QValueAxis()
        axis.setRange(0, max(1, max((value for _, value, _ in values), default=0) * 1.12))
        axis.setTitleText("管数")
        chart.addAxis(axis, Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(axis)
        chart.legend().hide()
        chart._bar_value_labels = []
        for index, (_, value, _) in enumerate(displayed):
            if not value:
                continue
            label = QGraphicsSimpleTextItem(f"{value:g} 根", chart)
            label.setBrush(QColor("#e5eeec" if self.theme == "dark" else "#23465b"))
            chart._bar_value_labels.append(label)
            label.setData(0, index)
            label.setData(1, float(value))

        def position_labels(*_):
            for label in chart._bar_value_labels:
                point = chart.mapToPosition(QPointF(label.data(1), label.data(0)), series)
                label.setPos(point.x() + 6, point.y() - label.boundingRect().height() / 2)

        chart.plotAreaChanged.connect(position_labels)
        position_labels()
        self.contract = {"family": "horizontal-bar", "values": values}


class VisualizationWorkspace(QTabWidget):
    dataChanged = Signal()
    panelRequested = Signal(str)
    scopeChanged = Signal(dict)
    historyRecordsRequested = Signal(dict)

    def __init__(self, parent=None, *, client=None, permissions=None):
        super().__init__(parent)
        self.client = client
        self.permissions = permissions
        self.data = {}
        self._unit_history_rows = {}
        self.severity_levels = [30, 50]
        self.severity_colors = ["#79b98c", "#e5a83b", "#df4b45"]
        self._longitudinal_cache = {}
        self._longitudinal_pending = set()
        self._longitudinal_request = 0
        self.ndd_zero = True
        self._selected_tube = 1
        self._history_outages = None
        self._history_combinations = []
        def panel():
            return ChartPanel(client=client, permissions=permissions)
        self.overview_page = QWidget()
        overview_layout = QVBoxLayout(self.overview_page)
        overview_layout.setContentsMargins(0, 0, 0, 0)
        overview_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.summary_labels = {}
        self.summary_notes = {}
        self._insight_titles = {}
        heading = QLabel("当前范围概况  ·  所选范围各机组最新大修 · 按管统计")
        heading.setObjectName("sectionHeading")
        heading.setFixedHeight(42)
        overview_layout.addWidget(heading)
        metrics = QGridLayout()
        metrics.setSpacing(0)
        self.metrics_layout, self.metric_hosts = metrics, []
        for index, (key, title) in enumerate((("units", "分析机组"), ("coverage", "检测覆盖"),
                                             ("war", "WAR 检出"), ("ndd", "NDD"),
                                             ("review", "结论待核对"), ("missing", "无检测记录"))):
            host = QWidget()
            host.setObjectName("overviewMetric")
            host.setFixedHeight(76)
            box = QHBoxLayout(host)
            box.setContentsMargins(12, 8, 12, 8)
            labels = QVBoxLayout()
            labels.setSpacing(4)
            label = QLabel(title)
            label.setObjectName("muted")
            labels.addWidget(label)
            note = QLabel("当前范围" if key == "units" else "根 · 不等同于 NDD" if key == "missing" else "根")
            note.setObjectName("metricNote")
            labels.addWidget(note)
            self.summary_notes[key] = note
            box.addLayout(labels, 1)
            value = button("0", callback=lambda _=False, name=key: self.open_overview_insight(name))
            value.setObjectName("metricValue")
            value.setProperty("metric", key)
            box.addWidget(value)
            self.summary_labels[key] = value
            self._insight_titles[key] = title
            metrics.addWidget(host, 0, index)
            self.metric_hosts.append(host)
        overview_layout.addLayout(metrics)
        insights = QGridLayout()
        self.insight_buttons = {}
        self._insight_rows = {}
        for index, (key, title) in enumerate((("peak", "最高报告深度"), ("position", "WAR 集中位置"),
                                             ("maintenance", "维护状态覆盖"), ("quality", "检测记录核查"))):
            control = button(f"{title}\n—")
            control.setObjectName("overviewInsight")
            control.setFixedHeight(82)
            control.setProperty("insight", key)
            control.clicked.connect(lambda _=False, name=key: self.open_overview_insight(name))
            self.insight_buttons[key] = control
            self._insight_titles[key] = title
            insights.addWidget(control, 0, index)
        overview_layout.addLayout(insights)
        self.overview = panel()
        self.overview.setMaximumHeight(380)
        overview_charts = QSplitter()
        overview_column = QWidget()
        column_layout = QVBoxLayout(overview_column)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.addWidget(self.overview)
        column_layout.addStretch(1)
        overview_charts.addWidget(overview_column)
        heat_host = QWidget()
        heat_host.setMinimumHeight(520)
        heat_host.setMaximumHeight(620)
        heat_layout = QVBoxLayout(heat_host)
        heat_layout.addWidget(QLabel("历史磨损集中位置"))
        heat_controls = QHBoxLayout()
        heat_controls.addWidget(QLabel("超阈筛选"))
        self.heat_presets = QButtonGroup(self)
        for threshold in (20, 40, 65):
            preset = button(f"> {threshold}%")
            preset.setCheckable(True)
            preset.setChecked(threshold == 20)
            self.heat_presets.addButton(preset, threshold)
            heat_controls.addWidget(preset)
        self.heat_threshold = QDoubleSpinBox()
        self.heat_threshold.setRange(0, 100)
        self.heat_threshold.setValue(20)
        self.heat_threshold.setSuffix(" %")
        self.heat_threshold.valueChanged.connect(self.refresh_overview)
        self.heat_presets.idClicked.connect(self.heat_threshold.setValue)
        self.heat_threshold.valueChanged.connect(self._sync_heat_preset)
        heat_controls.addWidget(self.heat_threshold)
        heat_controls.addStretch()
        heat_layout.addLayout(heat_controls)
        heat_body = QHBoxLayout()
        self.heatmap = PositionHeatmap()
        self.heatmap.positionClicked.connect(self.open_position_history)
        heat_body.addWidget(self.heatmap, 1)
        self.heat_ranking = QTableWidget(0, 2)
        self.heat_ranking.setHorizontalHeaderLabels(["位置", "次数"])
        self.heat_ranking.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.heat_ranking.setMaximumWidth(155)
        self.heat_ranking.verticalHeader().hide()
        self.heat_ranking.setColumnWidth(0, 65)
        self.heat_ranking.setColumnWidth(1, 60)
        heat_body.addWidget(self.heat_ranking)
        heat_layout.addLayout(heat_body, 1)
        overview_charts.addWidget(heat_host)
        overview_charts.setSizes([700, 700])
        overview_layout.addWidget(overview_charts, 1)
        unit_header = QWidget()
        unit_header.setObjectName("unitOverviewHeading")
        unit_header.setFixedHeight(60)
        unit_heading = QHBoxLayout(unit_header)
        unit_heading.setContentsMargins(12, 0, 12, 0)
        unit_heading.addWidget(QLabel("基地机组对照"), 1)
        overview_layout.addWidget(unit_header)
        self.unit_overview = UnitOverview()
        self.unit_overview.plateRequested.connect(self.open_unit_overview)
        self.unit_overview.historyRequested.connect(self.open_unit_history)
        self.unit_overview.recordsRequested.connect(self.open_unit_records)
        self.unit_overview.tubesRequested.connect(self.open_unit_tubes)
        overview_layout.addWidget(self.unit_overview)
        self.addTab(self.overview_page, "总体概况")
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
        self.risk.removeTab(self.risk.indexOf(self.longitudinal))
        self.insertTab(3, self.longitudinal, "单管完整历史")
        self.currentChanged.connect(self._fit_current_page)
        self._fit_current_page()
        self.chart_panels = {key: getattr(self, key) for key in (
            "overview", "total", "position", "increment", "states", "depths", "longitudinal",
            "replacements", "scatter_panel", "frequency")}
        for key, chart in self.chart_panels.items():
            chart.popoutRequested.connect(lambda name=key: self.panelRequested.emit(name))

    def view_state(self):
        state = {}
        for name in ("comparison_mode", "total_metric", "focus_unit", "trend_unit", "trend_metric",
                     "distribution_scope", "curve_mode", "mode", "history_site", "history_unit"):
            state[name] = getattr(self, name).currentData()
        for name in ("frequency_threshold", "heat_threshold", "jump", "tube_number"):
            state[name] = getattr(self, name).value()
        state["all_tubes"] = self.all_tubes.isChecked()
        state["comparison_units"] = None if self.comparison_units is None else set(self.comparison_units)
        state["history_outages"] = None if self._history_outages is None else set(self._history_outages)
        state["selected_tube"] = self._selected_tube
        state["tube_history"] = self.tube_history.view_state()
        current = self.current_snapshot()
        state["snapshot"] = (current["unit"], current["outage"]) if current else None
        return state

    def restore_view_state(self, state):
        from PySide6.QtCore import QSignalBlocker
        self.comparison_units = state["comparison_units"]
        self._history_outages = state["history_outages"]
        site_index = self.history_site.findData(state["history_site"])
        if site_index >= 0:
            self.history_site.setCurrentIndex(site_index)
        for name in ("comparison_mode", "total_metric", "focus_unit", "trend_unit", "trend_metric",
                     "distribution_scope", "curve_mode", "mode", "history_unit"):
            combo = getattr(self, name)
            with QSignalBlocker(combo):
                index = combo.findData(state[name])
                if index >= 0:
                    combo.setCurrentIndex(index)
        for name in ("frequency_threshold", "heat_threshold", "jump", "tube_number"):
            control = getattr(self, name)
            with QSignalBlocker(control):
                control.setValue(state[name])
        with QSignalBlocker(self.all_tubes):
            self.all_tubes.setChecked(state["all_tubes"])
        snapshot = state["snapshot"]
        if snapshot:
            index = next((index for index, row in enumerate(self.data.get("snapshots") or [])
                          if (row["unit"], row["outage"]) == snapshot), -1)
            with QSignalBlocker(self.snapshot):
                self.snapshot.setCurrentIndex(index)
        self._selected_tube = state["selected_tube"]
        self.tube_history.restore_view_state(state["tube_history"])
        self.refresh_total()
        self.refresh_trends()
        self.refresh_distribution()
        self.refresh_frequency()
        self.refresh_snapshot()
        self.load_longitudinal()

    def set_metric_columns(self, columns):
        if columns == getattr(self, "_metric_columns", None):
            return
        self._metric_columns = columns
        for index, host in enumerate(self.metric_hosts):
            self.metrics_layout.removeWidget(host)
            self.metrics_layout.addWidget(host, index // columns, index % columns)
        self.updateGeometry()

    def _fit_current_page(self, *_):
        # QTabWidget normally sizes every page to the largest hidden page.
        for index in range(self.count()):
            policy = QSizePolicy.Policy.Preferred if index == self.currentIndex() else QSizePolicy.Policy.Ignored
            self.widget(index).setSizePolicy(QSizePolicy.Policy.Preferred, policy)
        self.updateGeometry()

    def sizeHint(self):
        page = self.currentWidget()
        if page is None:
            return super().sizeHint()
        hint = page.sizeHint()
        return QSize(max(hint.width(), self.tabBar().sizeHint().width()) + 4,
                     hint.height() + self.tabBar().sizeHint().height() + 4)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        page = self.currentWidget()
        if page is None:
            return super().heightForWidth(width)
        height = page.heightForWidth(max(0, width - 4)) if page.hasHeightForWidth() else page.sizeHint().height()
        return max(height, page.minimumSizeHint().height()) + self.tabBar().sizeHint().height() + 4

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
        current = self.current_snapshot()
        previous_snapshot = (current["unit"], current["outage"]) if current else None
        self.data = data
        self._longitudinal_cache.clear()
        self._longitudinal_pending.clear()
        self._longitudinal_request += 1
        self._baseline_scope = None
        self.refresh_overview()
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
        self.snapshot.clear()
        for i, snapshot in enumerate(data.get("snapshots", [])):
            self.snapshot.addItem(f"{snapshot['unit']} · {snapshot['outage']}", i)
        selected = next((index for index, snapshot in enumerate(data.get("snapshots") or [])
                         if (snapshot["unit"], snapshot["outage"]) == previous_snapshot), 0)
        self.snapshot.setCurrentIndex(selected)
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
        self.load_longitudinal()
        self.dataChanged.emit()

    def _watch_data_dialog(self, dialog, refresh):
        self.dataChanged.connect(refresh)
        dialog.finished.connect(lambda *_: self.dataChanged.disconnect(refresh))

    def _watch_unit_dialog(self, dialog, unit, outage, render, *, require_snapshot=False):
        from urllib.parse import urlencode
        state = {"request": 0, "closed": False}
        dialog.finished.connect(lambda *_: state.update(closed=True))
        retry = button("重试", "refresh-cw")
        retry.hide()
        dialog.layout().insertWidget(dialog.layout().count() - 1, retry)

        def refresh():
            state["request"] += 1
            generation = state["request"]
            retry.hide()
            has_snapshot = any(item["unit"] == unit and item["outage"] == outage
                               for item in self.data.get("snapshots") or [])
            if (self.client is None or ((unit, outage) in self._unit_history_rows
                                        and (not require_snapshot or has_snapshot))):
                render(self._unit_history_rows.get((unit, outage)), self.data, None)
                return
            match = re.fullmatch(r"([A-Z]+)(\d+)", unit)
            if not match:
                return
            render(None, {}, "正在读取当前范围的历史记录...")

            def loaded(data, error):
                if state["closed"] or generation != state["request"]:
                    return
                entry = next((entry for item in (data or {}).get("units") or [] if item["code"] == unit
                              for entry in item.get("history") or [] if entry["outage"] == outage), None)
                failure = error or ("历史记录读取失败" if data is None else None)
                render(entry, data or {}, failure)
                retry.setVisible(bool(failure))
            params = {"site": match[1], "unit": match[2], "outage": outage}
            self.client.get("/api/analysis/visualization?" + urlencode(params), loaded)
        retry.clicked.connect(refresh)
        self._watch_data_dialog(dialog, refresh)
        refresh()

    def refresh_overview(self, *_):
        if not self.data:
            return
        latest = self.latest_snapshots()
        tubes = [tube for snapshot in latest.values() for tube in snapshot.get("tubes") or []]
        counts = Counter()
        mid, high = self.severity_levels[:2]
        for tube in tubes:
            coverage = tube.get("coverage")
            if coverage == "NDD":
                counts["ndd"] += 1
            elif coverage == "missing":
                counts["missing"] += 1
            elif coverage == "defect":
                counts["war"] += 1
                depth = valid_depth(tube)
                if depth is not None:
                    counts["zero" if depth == 0 else "high" if depth >= high
                           else "mid" if depth >= mid else "low"] += 1
                else:
                    counts["unquantified"] += 1
            else:
                counts["review"] += 1
        coverage = (len(tubes) - counts["missing"]) / len(tubes) * 100 if tubes else 0
        self.summary_notes["coverage"].setText(f"{len(tubes) - counts['missing']} / {len(tubes)} 根")
        for key, control in self.summary_labels.items():
            value = len(latest) if key == "units" else f"{coverage:g}%" if key == "coverage" else counts[key]
            control.setText(str(value))
        bands = [
            ("NDD", counts["ndd"], "#ffffff"), ("原记录 0%", counts["zero"], "#818d96"),
            (f">0 且 <{mid}%", counts["low"], self.severity_colors[0]),
            (f"{mid}%-<{high}%", counts["mid"], self.severity_colors[1]),
            (f">={high}%", counts["high"], self.severity_colors[-1]),
            ("无检测记录", counts["missing"], "#9aaeb7"),
            ("待核对", counts["review"], "#d6b674"), ("磨损深度缺失", counts["unquantified"], "#818d96")]
        self.overview.horizontal_bars("最新检测深度分布", [band for band in bands if band[1]],
            f"{len(latest)} 台机组 · 各取所选范围最新轮次 · {len(tubes)} 根管")
        frequency = channel_frequency(self.data.get("snapshots") or [], self.heat_threshold.value())
        self.heatmap.set_counts(frequency)
        current = [(snap, tube) for snap in latest.values() for tube in snap.get("tubes") or []]
        quantified = [(snap, tube) for snap, tube in current if valid_depth(tube) is not None]
        peak = max(quantified, key=lambda row: valid_depth(row[1]), default=None)
        positions = Counter(tube["position"] for tube in tubes
                            if tube.get("coverage") == "defect" and tube.get("position"))
        top_position = min(positions, key=lambda position: (-positions[position], position)) if positions else None
        maintained = [(snap, tube) for snap, tube in current
                      if tube.get("state_badges") or tube.get("state_recorded") or tube.get("state") == "normal"]
        needs_review = lambda tube: (tube.get("coverage") in ("missing", "incomplete")
                                    or tube.get("incomplete_records") or tube.get("missing_depth"))
        review = [(snap, tube) for snap, tube in current if needs_review(tube)]
        breakdown = " · ".join(f"{title} {sum(code in (tube.get('state_badges') or []) for tube in tubes)}"
                               for code, title in (("plugged", "堵管"), ("shifted", "移位"), ("replaced", "换管")))
        facts = {
            "peak": (f"{peak[0]['unit']} · {valid_depth(peak[1]):g}%\n{peak[0]['outage']}"
                     if peak else "暂无有效深度"),
            "position": f"{top_position} · {positions[top_position]} 根" if top_position else "暂无位置记录",
            "maintenance": f"{len(maintained)} 根\n{breakdown}",
            "quality": ("当前范围暂无数据" if not tubes else
                        f"{len(review)} 根待核查" if review else "检测记录齐全"),
        }
        self._insight_rows = {"peak": [peak] if peak else [],
                              "position": [(snap, tube) for snap, tube in current
                                           if top_position and tube.get("coverage") == "defect"
                                           and tube.get("position") == top_position],
                              "maintenance": maintained, "quality": review or current,
                              "units": current, "coverage": [(snap, tube) for snap, tube in current
                                                              if tube.get("coverage") != "missing"],
                              "war": [(snap, tube) for snap, tube in current if tube.get("coverage") == "defect"],
                              "ndd": [(snap, tube) for snap, tube in current if tube.get("coverage") == "NDD"],
                              "review": [(snap, tube) for snap, tube in current
                                         if tube.get("coverage") == "incomplete"],
                              "missing": [(snap, tube) for snap, tube in current
                                          if tube.get("coverage") == "missing"]}
        for key, control in self.insight_buttons.items():
            control.setText(control.text().split("\n")[0] + "\n" + facts[key])
            control.setEnabled(bool(self._insight_rows[key]))
        ranked = sorted(frequency.items(), key=lambda item: (-item[1], item[0]))[:15]
        self.heat_ranking.setRowCount(len(ranked))
        for row, (position, count) in enumerate(ranked):
            self.heat_ranking.setItem(row, 0, QTableWidgetItem(position))
            self.heat_ranking.setItem(row, 1, QTableWidgetItem(str(count)))
        self.refresh_unit_overview(latest)

    def _sync_heat_preset(self, value):
        self.heat_presets.setExclusive(False)
        for preset in self.heat_presets.buttons():
            preset.setChecked(self.heat_presets.id(preset) == value)
        self.heat_presets.setExclusive(True)

    def refresh_unit_overview(self, latest):
        self.unit_overview.set_data(self.data, latest)
        self._unit_history_rows = self.unit_overview.history

    def open_unit_overview(self, unit, outage):
        key = (unit, outage)
        index = next((index for index, snap in enumerate(self.data.get("snapshots") or [])
                      if snap["unit"] == unit and snap["outage"] == outage), None)
        if index is not None:
            self.snapshot.setCurrentIndex(index)
            self.refresh_snapshot()
            self.setCurrentIndex(2)
            self._publish_scope()
        elif key in self._unit_history_rows:
            match = re.fullmatch(r"([A-Z]+)(\d+)", unit)
            if match:
                self.setCurrentIndex(2)
                self.scopeChanged.emit({"site": match[1], "unit": match[2], "outage": outage})

    def open_unit_history(self, unit, outage):
        entry = self._unit_history_rows.get((unit, outage))
        if entry is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{unit} · {outage} · 完整性与维护来源")
        dialog.resize(980, 600)
        layout = QVBoxLayout(dialog)
        tabs = QTabWidget()
        facts = QPlainTextEdit()
        facts.setReadOnly(True)
        names = {"missing_tubes": "无检测记录", "incomplete_tubes": "结论待核对",
                 "unquantified_tubes": "WAR 深度缺失", "state_missing_tubes": "截至本次无维护记录",
                 "state_current_tubes": "本次有维护记录", "state_current_missing_tubes": "本次无维护记录",
                 "state_review_tubes": "维护顺序或状态待核对", "inherited_plug_tubes": "沿用历史堵管"}
        tabs.addTab(facts, "检测与维护完整性")
        table = QTableWidget(0, 6)
        table.setHorizontalHeaderLabels(["管号", "最近维护大修", "截至本次有效状态", "原始备注", "来源", "待核对原因"])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        table.setColumnWidth(3, 300)
        table.setColumnWidth(4, 220)
        tabs.addTab(table, "维护原文与来源")
        layout.addWidget(tabs)
        layout.addWidget(button("关闭", "x", dialog.accept))
        def render(entry, data, error):
            table.setRowCount(0)
            if error or entry is None:
                facts.setPlainText(error or "当前库中没有该次大修的检测或维护记录")
                return
            lines = [f"检测记录：{entry.get('records', 0)} 条"]
            for field, title in names.items():
                numbers = entry.get(field) or []
                lines.append(f"{title}（{len(numbers)} 根）：{'、'.join(map(str, numbers)) or '无'}")
            for field, title in (("defect", "WAR"), ("NDD", "NDD"), ("incomplete", "待核对结论")):
                numbers = (entry.get("detection_tubes") or {}).get(field) or []
                lines.append(f"{title}管号：" + ("、".join(map(str, numbers)) or "无"))
            facts.setPlainText("\n\n".join(lines))
            sources = entry.get("state_sources") or []
            table.setRowCount(len(sources))
            for row, record in enumerate(sources):
                for column, value in enumerate((record["tube"], record["outage"], record["label"],
                                                 record.get("note", ""), record.get("source", ""),
                                                 "；".join(record.get("warnings") or []))):
                    cell = QTableWidgetItem(str(value))
                    cell.setToolTip(str(value))
                    table.setItem(row, column, cell)
        self._watch_unit_dialog(dialog, unit, outage, render)
        dialog.open()
        self.unit_history_dialog = dialog

    def open_unit_tubes(self, unit, outage, numbers, kind):
        if not numbers:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{unit} · {outage} · {'维护状态' if kind == 'state' else '检测记录'}管号明细")
        dialog.resize(900, 560)
        layout = QVBoxLayout(dialog)
        status = QLabel()
        status.setWordWrap(True)
        layout.addWidget(status)
        table = QTableWidget(len(numbers), 5)
        table.setHorizontalHeaderLabels(["管号", "管板位置", "检测结论", "有效维护状态", "原始备注"])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        names = {"defect": "WAR", "NDD": "NDD", "missing": "无检测记录", "incomplete": "待核对"}
        def render(entry, data, error):
            table.setRowCount(0)
            status.setText(error or (f"已更新 · 当前查看 {len(numbers)} 根管" if entry is not None
                                    else "当前库中没有该次大修的检测或维护记录"))
            if error or entry is None:
                return
            snapshots = [snapshot for snapshot in data.get("snapshots") or []
                         if snapshot["unit"] == unit and snapshot["outage"] == outage]
            tubes = {int(tube["tube"]): tube for snapshot in snapshots for tube in snapshot.get("tubes") or []}
            sources = {int(record["tube"]): record for record in entry.get("state_sources") or []}
            conclusions = {int(number): names.get(code, code) for code, values in
                           (entry.get("detection_tubes") or {}).items() for number in values}
            table.setRowCount(len(numbers))
            for row, number in enumerate(numbers):
                tube, source = tubes.get(int(number), {}), sources.get(int(number), {})
                values = (number, tube.get("position", ""),
                          names.get(tube.get("coverage"), conclusions.get(int(number), "无检测记录")),
                          source.get("label") or tube.get("state_label") or "未记录", source.get("note", ""))
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    item.setToolTip(str(value))
                    table.setItem(row, column, item)
        layout.addWidget(table)
        layout.addWidget(button("查看本次管板", "search", lambda: self.open_unit_overview(unit, outage)))
        layout.addWidget(button("关闭", "x", dialog.accept))
        self._watch_unit_dialog(dialog, unit, outage, render, require_snapshot=True)
        dialog.open()
        self.unit_tubes_dialog = dialog

    def open_unit_records(self, unit, outage):
        if self.client is None:
            return
        from urllib.parse import urlencode
        match = re.fullmatch(r"([A-Z]+)(\d+)", unit)
        if not match:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{unit} · {outage} · 原始检测表")
        dialog.resize(1100, 650)
        layout = QVBoxLayout(dialog)
        status = QLabel("正在读取原始检测记录...")
        layout.addWidget(status)
        fields = (("thimble_id", "通道"), ("position", "堆芯位置"), ("indication", "原始结论"),
                  ("percent", "深度%"), ("location", "磨损位置"), ("channel", "测量通道"),
                  ("analysis", "备注"), ("filename", "数据文件"))
        table = QTableWidget(0, len(fields))
        table.setHorizontalHeaderLabels([title for _, title in fields])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)
        controls = QHBoxLayout()
        previous, following = button("上一页", "chevron-left"), button("下一页", "chevron-right")
        for control in (previous, following):
            controls.addWidget(control)
        retry = button("重试", "refresh-cw")
        retry.hide()
        controls.addWidget(retry)
        controls.addStretch()
        controls.addWidget(button("关闭", "x", dialog.accept))
        layout.addLayout(controls)
        state = {"page": 1, "request": 0, "closed": False}
        dialog.finished.connect(lambda *_: state.update(closed=True))

        def load(page):
            state["page"], state["request"] = page, state["request"] + 1
            request = state["request"]
            status.setText(f"正在读取第 {page} 页原始检测记录...")
            table.setEnabled(False)
            retry.hide()
            previous.setEnabled(False)
            following.setEnabled(False)
            params = {"site": match[1], "unit": match[2], "outage": outage, "raw": 1,
                      "core": 0, "size": 100, "page": page, "auto_ndd": 0}

            def loaded(data, error):
                if state["closed"] or request != state["request"]:
                    return
                if error or not data:
                    status.setText(error or "原始检测记录读取失败")
                    table.setRowCount(0)
                    table.setEnabled(True)
                    previous.setEnabled(page > 1)
                    retry.show()
                    return
                rows = data.get("items") or []
                total = data.get("total", 0)
                table.setRowCount(len(rows))
                table.setEnabled(True)
                for row, record in enumerate(rows):
                    for column, (field, _) in enumerate(fields):
                        value = record.get(field)
                        item = QTableWidgetItem("" if value is None else str(value))
                        item.setToolTip(item.text())
                        table.setItem(row, column, item)
                status.setText(f"共 {total} 条原始检测记录 · 第 {page} 页")
                previous.setEnabled(page > 1)
                following.setEnabled(page * 100 < total)
            self.client.get("/api/findings?" + urlencode(params), loaded)
        previous.clicked.connect(lambda: load(state["page"] - 1))
        following.clicked.connect(lambda: load(state["page"] + 1))
        retry.clicked.connect(lambda: load(state["page"]))
        dialog.open()
        self.unit_records_dialog = dialog
        self._watch_data_dialog(dialog, lambda: load(state["page"]))
        load(1)

    def open_overview_insight(self, key):
        rows = list(self._insight_rows.get(key) or [])
        if not rows:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(self._insight_titles[key])
        dialog.resize(900, 560)
        layout = QVBoxLayout(dialog)
        table = QTableWidget(0, 6)
        table.setHorizontalHeaderLabels(["机组", "大修", "管号", "管板位置", "最大报告深度", "有效维护状态"])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.horizontalHeader().setStretchLastSection(True)
        def refresh():
            rows = self._insight_rows.get(key) or []
            table.setRowCount(len(rows))
            for index, (snap, tube) in enumerate(rows):
                depth = valid_depth(tube)
                for column, value in enumerate((snap["unit"], snap["outage"], tube["tube"], tube.get("position", ""),
                                                 f"{depth:g}%" if depth is not None else "—",
                                                 tube.get("state_label") or "未记录")):
                    table.setItem(index, column, QTableWidgetItem(str(value)))
        layout.addWidget(table)
        layout.addWidget(button("关闭", "x", dialog.accept))
        self._watch_data_dialog(dialog, refresh)
        refresh()
        dialog.open()
        self.insight_dialog = dialog

    def open_position_history(self, position):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{position} · 历史超阈记录")
        dialog.resize(760, 480)
        layout = QVBoxLayout(dialog)
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["机组", "大修", "通道", "最大深度"])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        def refresh():
            rows = [(snapshot, tube) for snapshot in self.data.get("snapshots") or []
                    for tube in snapshot.get("tubes") or [] if tube.get("position") == position
                    and valid_depth(tube) is not None and valid_depth(tube) > self.heat_threshold.value()]
            table.setRowCount(len(rows))
            for row, (snapshot, tube) in enumerate(rows):
                for col, value in enumerate((snapshot["unit"], snapshot["outage"], tube["tube"], tube["max_depth"])):
                    table.setItem(row, col, QTableWidgetItem(str(value)))
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)
        layout.addWidget(button("关闭", "x", dialog.accept))
        self._watch_data_dialog(dialog, refresh)
        refresh()
        dialog.exec()

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
        for panel in self.chart_panels.values():
            panel.set_theme(theme, animations)
        self.tube_history.set_theme(theme, animations, self.longitudinal.point_labels)

    def set_analysis_options(self, ndd_zero, point_labels):
        changed = self.ndd_zero != ndd_zero
        self.ndd_zero = bool(ndd_zero)
        for panel in self.chart_panels.values():
            panel.set_point_labels(point_labels)
        self.tube_history.set_theme(self.longitudinal.theme, self.longitudinal.animations, point_labels)
        if changed:
            self._longitudinal_request += 1
            self._longitudinal_cache.clear()
            self._longitudinal_pending.clear()
        return changed

    def set_severity(self, levels, colors):
        if self.severity_levels != levels or self.severity_colors != colors:
            self.severity_levels, self.severity_colors = list(levels), list(colors)
            self.unit_overview.levels, self.unit_overview.colors = list(levels), list(colors)
            self.unit_overview._data = None
            self.refresh_overview()

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
                         + (("相邻轮次可靠 WAR 匹配，保留负增量；"
                             + ("前次明确 NDD 按 0 基线起算（判定值，非实测）。"
                                if self.ndd_zero else "NDD 记 0 已关闭。")) if increment else ""),
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
                                        current.get("percent"),
                                        "NDD 0 基线（非实测）" if match.get("ndd_baseline") else previous.get("percent"),
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
        scope = QHBoxLayout()
        self.history_site, self.history_unit = QComboBox(), QComboBox()
        self.history_site.setAccessibleName("完整历史基地")
        self.history_unit.setAccessibleName("完整历史机组")
        scope.addWidget(QLabel("基地"))
        scope.addWidget(self.history_site)
        scope.addWidget(QLabel("机组"))
        scope.addWidget(self.history_unit)
        self.history_retry = button("刷新历史", "refresh-cw", self.reload_history)
        scope.addWidget(self.history_retry)
        scope.addStretch()
        self.longitudinal.layout().insertLayout(0, scope)
        self.history_site.currentIndexChanged.connect(self._history_site_changed)
        self.history_unit.currentIndexChanged.connect(self.load_longitudinal)
        row = QHBoxLayout()
        self.tube_number = QSpinBox()
        self.tube_number.setRange(1, 50)
        self.tube_number.setPrefix("管号 ")
        self.tube_number.valueChanged.connect(self.draw_longitudinal)
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
        self.longitudinal.layout().insertLayout(1, row)
        self.longitudinal_table = QTableWidget(0, 8)
        self.longitudinal_table.setHorizontalHeaderLabels(
            ["大修", "原始报告", "当前寿期", "变化", "寿期代次", "维护", "突变", "来源/核查"])
        self.longitudinal_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.longitudinal_table.setMaximumHeight(190)
        self.longitudinal_table.hide()
        self.longitudinal.layout().addWidget(self.longitudinal_table)
        from .native_tube_history import TubeHistoryView
        self.tube_history = TubeHistoryView(self.client, self.permissions)
        self.tube_history.recordsRequested.connect(self.historyRecordsRequested.emit)
        self.longitudinal.layout().insertWidget(self.longitudinal.layout().indexOf(self.longitudinal.view),
                                                self.tube_history.intro)
        self.longitudinal.layout().addWidget(self.tube_history)

    def set_history_units(self, combinations):
        self._history_combinations = list(combinations)
        current = self.history_site.currentData()
        snapshot = self.current_snapshot()
        if current is None and snapshot:
            current = re.sub(r"\d+$", "", snapshot["unit"])
        self.history_site.blockSignals(True)
        self.history_site.clear()
        sites = sorted({row["site"] for row in combinations})
        for site in sites:
            self.history_site.addItem(SITE_NAMES.get(site, site), site)
        self.history_site.setCurrentIndex(max(0, self.history_site.findData(current)))
        self.history_site.blockSignals(False)
        self._history_site_changed()

    def _history_site_changed(self, *_):
        current, site = self.history_unit.currentData(), self.history_site.currentData()
        self.history_unit.blockSignals(True)
        self.history_unit.clear()
        for number in sorted({int(row["unit_id"]) for row in self._history_combinations if row["site"] == site}):
            self.history_unit.addItem(f"{number}号机组", f"{site}{number}")
        self.history_unit.setCurrentIndex(max(0, self.history_unit.findData(current)))
        self.history_unit.blockSignals(False)
        self.load_longitudinal()

    def longitudinal_unit(self):
        current = self.current_snapshot()
        return self.history_unit.currentData() or (current["unit"] if current else "")

    def reload_history(self):
        self._longitudinal_request += 1
        self._longitudinal_cache.clear()
        self._longitudinal_pending.clear()
        self.load_longitudinal()

    def current_snapshot(self):
        snapshots = self.data.get("snapshots") or []
        index = self.snapshot.currentData()
        return snapshots[index] if index is not None and 0 <= index < len(snapshots) else None

    def load_longitudinal(self, *_):
        import re
        from urllib.parse import urlencode
        unit = self.longitudinal_unit()
        if not unit:
            self.longitudinal.lines("单管完整历史", {}, "当前没有可读取的机组范围")
            self.tube_history.hide()
            self.tube_history.intro.hide()
            self.longitudinal_table.setRowCount(0)
            return
        match = re.fullmatch(r"([A-Z]+)(\d+)", unit)
        if not match or self.client is None:
            self.longitudinal.lines("单管寿期曲线", {}, "没有可读取的机组范围")
            return
        key = (unit, self.jump.value())
        if key in self._longitudinal_cache:
            self.draw_longitudinal()
            return
        if key in self._longitudinal_pending:
            return
        self._longitudinal_pending.add(key)
        number = self._longitudinal_request
        self.tube_history.hide()
        self.tube_history.intro.hide()
        self.longitudinal.lines(f"{unit} · 单管完整历史", {}, "正在读取完整寿期与维护记录...")
        def loaded(data, error):
            if number != self._longitudinal_request:
                return
            self._longitudinal_pending.discard(key)
            if error or not data:
                if unit == self.longitudinal_unit() and key[1] == self.jump.value():
                    self.longitudinal.lines(f"{unit} · 单管完整历史", {}, error or "读取失败")
                return
            self._longitudinal_cache[key] = data
            if unit == self.longitudinal_unit() and key[1] == self.jump.value():
                self.draw_longitudinal()
        self.client.get("/api/analysis/tube-longitudinal?" + urlencode(
            {"site": match[1], "unit": match[2], "jump": self.jump.value(),
             "ndd_zero": int(self.ndd_zero)}), loaded)

    def draw_longitudinal(self, *_):
        unit = self.longitudinal_unit()
        if not unit:
            return
        data = self._longitudinal_cache.get((unit, self.jump.value())) or {}
        number = self.tube_number.value()
        tube = next((t for t in data.get("tubes") or [] if t["tube"] == number), {})
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
        self.longitudinal.lines(f"{unit} · " +
                                ("全部管寿期曲线" if self.all_tubes.isChecked() else f"{number}号管寿期曲线"), groups,
                                "完整机组历史 · 换管建立新寿期并断线；移位不清零；"
                                + ("NDD 显示 0 基线（判定值，非实测）；" if self.ndd_zero else "NDD 不计深度；")
                                + "缺测不补零",
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
        if tube:
            self.tube_history.set_data(unit, tube, data.get("outages") or [], self.ndd_zero)
        self.tube_history.setVisible(bool(tube))
        self.tube_history.intro.setVisible(bool(tube))

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
