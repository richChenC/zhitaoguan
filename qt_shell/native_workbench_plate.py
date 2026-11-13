"""Native workbench plate header, selection statistics and record details."""
from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListView, QSizePolicy, QStyledItemDelegate, QTabBar,
    QVBoxLayout, QWidget,
)

from .native_components import ReferencePlateMap, button
from .native_plate_snapshot import selected_statistics


class PlateModeTabs(QTabBar):
    def tabSizeHint(self, index):
        return QSize(74, 34)


class SelectedRecordsModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        row = self.rows[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            value = "/" if row.get("percent") is None else f"{row['percent']:g}%"
            code = row.get("display_conclusion") or row.get("indication") or "/"
            return (f"#{row.get('thimble_id')} · {row.get('position') or '/'}\n"
                    f"{row.get('outage')} / {row.get('unit_id')}号机 · {row.get('analyst') or '/'}\n"
                    f"{code} · {value}\n{row.get('location') or '/'} · {row.get('channel') or '/'}")
        if role == Qt.ItemDataRole.UserRole:
            return row

    def replace(self, rows):
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()


class SelectedRecordDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(200, 62)

    def paint(self, painter, option, index):
        painter.save()
        dark = bool(option.widget and option.widget.property("dark"))
        text = QColor("#d8e5e2" if dark else "#294957")
        muted = QColor("#a8b8b5" if dark else "#75868e")
        line = QColor("#3b4c4d" if dark else "#e5ecef")
        rect = option.rect.adjusted(0, 0, -1, 0)
        painter.setPen(line)
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        lines = index.data().split("\n")
        font = QFont(option.font)
        font.setPixelSize(11)
        painter.setFont(font)
        painter.setPen(muted)
        painter.drawText(rect.adjusted(0, 0, -rect.width() + 26, 0),
                         Qt.AlignmentFlag.AlignCenter, str(index.row() + 1))
        left = rect.left() + 34
        available = max(0, rect.width() - 42)
        column = available * .5
        for offset, value in enumerate(lines):
            strong = offset % 2 == 0
            font.setWeight(QFont.Weight.DemiBold if strong else QFont.Weight.Normal)
            painter.setFont(font)
            painter.setPen(text if strong else muted)
            area = QRectF(left + (column if offset >= 2 else 0),
                          rect.top() + (10 if strong else 32), column - 6, 18)
            painter.drawText(area, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             painter.fontMetrics().elidedText(value, Qt.TextElideMode.ElideRight, int(area.width())))
        painter.restore()


class PlateDetails(QWidget):
    focusRequested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("workbenchPlateDetails")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._layout.setSpacing(8)
        self.caption = QLabel()
        self.caption.setTextFormat(Qt.TextFormat.PlainText)
        self.caption.setWordWrap(True)
        self.caption.setObjectName("workbenchPlateDetailCaption")
        heading = QHBoxLayout()
        heading.addWidget(self.caption, 1)
        self.focus_button = button("三维定位", "box", lambda: self.focusRequested.emit(dict(self._scope)))
        self.focus_button.setFixedHeight(32)
        self.focus_button.setAccessibleName("所选管位三维定位")
        heading.addWidget(self.focus_button)
        self._layout.addLayout(heading)
        self.model = SelectedRecordsModel(self)
        self.records = QListView()
        self.records.setObjectName("workbenchSelectedRecords")
        self.records.setAccessibleName("勾选记录检测详情")
        self.records.setModel(self.model)
        self.records.setItemDelegate(SelectedRecordDelegate(self.records))
        self.records.setUniformItemSizes(True)
        self.records.setSelectionMode(QListView.SelectionMode.NoSelection)
        self.records.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._layout.addWidget(self.records, 1)
        self.setText("勾选任意记录查看详情；只有有效缺陷参与管板着色")

    def setText(self, text):
        self.caption.setText(str(text))
        self.focus_button.hide()
        self.records.hide()
        self.model.replace([])
        self.setFixedHeight(74)

    def text(self):
        return self.caption.text()

    def show_records(self, rows):
        self.focus_button.hide()
        if not rows:
            self.setText("勾选记录后在此逐条显示检测详情")
            return
        self.caption.setText(f"已勾选 {len(rows)} 条记录    {len({row['thimble_id'] for row in rows})} 根指套管")
        self.model.replace(rows)
        self.records.show()
        self.setFixedHeight(min(260, 60 + 62 * len(rows)))

    def show_tube(self, scope, position, rows):
        self._scope = dict(scope)
        unit, tube = int(scope["unit"]), int(scope["thimble"])
        self.caption.setText(f"{unit}号机 · {tube}号指套管\n"
                             f"{'奇数机组左半圆' if unit % 2 else '偶数机组右半圆'} · {position}\n"
                             f"{len(rows)} 条当前筛选记录")
        self.focus_button.show()
        self.model.replace(rows)
        self.records.setVisible(bool(rows))
        self.setFixedHeight(min(260, 100 + 62 * len(rows)))


class PlateStatistics(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("workbenchPlateStats")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(0)
        self.message = QLabel()
        self.message.setObjectName("workbenchPlateStatsEmpty")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.fields = []
        for caption in ("已选记录", "缺陷管", "最大磨损", "密集区域"):
            host = QWidget()
            host.setObjectName("workbenchPlateStatistic")
            column = QVBoxLayout(host)
            column.setContentsMargins(9, 0, 9, 0)
            column.setSpacing(3)
            label, value = QLabel(caption), QLabel()
            label.setObjectName("workbenchPlateStatisticLabel")
            value.setObjectName("workbenchPlateStatisticValue")
            value.setTextFormat(Qt.TextFormat.PlainText)
            column.addWidget(label)
            column.addWidget(value)
            layout.addWidget(host, 1)
            self.fields.append((host, value))
        self.setText("勾选检测记录后统计缺陷分布")

    def setText(self, text):
        self.message.setText(str(text))
        self.message.show()
        for host, _value in self.fields:
            host.hide()
        self.setFixedHeight(42)

    def text(self):
        return self.message.text() if self.message.isVisible() else " · ".join(
            value.text() for _host, value in self.fields)

    def show_records(self, rows):
        if not rows:
            self.setText("勾选检测记录后统计缺陷分布")
            return
        scopes = {(row.get("site_code"), row.get("unit_id"), row.get("outage")) for row in rows}
        if len(scopes) != 1:
            self.setText("已保留跨机组或大修的勾选；缺陷分布需选择同一机组、同次大修")
            return
        stats = selected_statistics(rows)
        dense, count, maximum = stats["dense"], stats["dense_count"], stats["max_percent"]
        values = (str(len(rows)), str(len(stats["tube_maximums"])),
                  f"{maximum:g}%" if maximum else "/", f"{dense} · {count}条" if count else dense)
        self.message.hide()
        for (host, value), text in zip(self.fields, values):
            value.setText(text)
            value.setToolTip(text)
            host.show()
        self.setFixedHeight(63)


class WorkbenchPlatePanel(QWidget):
    geometryChanged = Signal()

    def __init__(self, export, parent=None):
        super().__init__(parent)
        self.setObjectName("workspacePanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setMinimumWidth(300)
        self.side_by_side = False
        self.heading = QWidget(self)
        self.heading.setObjectName("workbenchPlateHeading")
        self.heading.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        heading = QHBoxLayout(self.heading)
        heading.setContentsMargins(13, 10, 13, 10)
        heading.setSpacing(10)
        labels = QWidget()
        text = QVBoxLayout(labels)
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(3)
        self.title = QLabel("堆芯分布")
        self.title.setObjectName("workbenchPlateTitle")
        self.subtitle = QLabel("筛选后按单管最大磨损着色 · 左奇数 / 右偶数")
        self.subtitle.setObjectName("workbenchPlateSubtitle")
        text.addWidget(self.title)
        text.addWidget(self.subtitle)
        heading.addWidget(labels, 1)
        self.export_button = button("导出图片", "download", export)
        self.export_button.setObjectName("workbenchPlateExport")
        self.export_button.setFixedSize(87, 30)
        self.export_button.setIconSize(QSize(15, 15))
        heading.addWidget(self.export_button)
        self.modes = QWidget(self)
        self.modes.setObjectName("workbenchPlateModes")
        self.modes.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        mode_layout = QHBoxLayout(self.modes)
        mode_layout.setContentsMargins(3, 3, 3, 3)
        mode_layout.setSpacing(0)
        self.tabs = PlateModeTabs()
        self.tabs.setObjectName("workbenchPlateTabs")
        self.tabs.setAccessibleName("管板机组显示")
        self.tabs.setDrawBase(False)
        self.tabs.setExpanding(False)
        self.tabs.setFixedSize(222, 34)
        for label in ("综合显示", "奇数机组", "偶数机组"):
            self.tabs.addTab(label)
        mode_layout.addWidget(self.tabs)
        mode_layout.addStretch()
        self.plate = ReferencePlateMap(self)
        self.stats = PlateStatistics(self)
        self.details = PlateDetails(self)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def set_side_by_side(self, enabled):
        if self.side_by_side != bool(enabled):
            self.side_by_side = bool(enabled)
            self.arrange()

    def set_theme(self, theme):
        self.plate.set_theme(theme)
        self.details.records.setProperty("dark", theme == "dark")
        self.details.records.viewport().update()

    def arrange(self):
        width = self.width()
        inner = max(0, width - 2)
        map_width = min(620, inner / 2 if self.side_by_side else inner)
        map_height = max(0, map_width - 38)
        self.heading.setGeometry(1, 1, inner, 60)
        self.modes.setGeometry(17, 71, max(0, width - 34), 40)
        self.plate.setGeometry(round(1 if self.side_by_side else (width - map_width) / 2),
                               137, round(map_width), round(map_height))
        side = inner / 2 if self.side_by_side else 0
        stats_top = 119 if self.side_by_side else round(137 + map_height + 14)
        self.stats.setGeometry(round(17 + side), stats_top,
                               round(inner - side - 32), self.stats.height())
        self.details.setGeometry(round(13 + side), stats_top + self.stats.height(),
                                 round(inner - side - 24), self.details.height())
        minimum = max(round(137 + map_height + 25),
                      self.details.geometry().bottom() + 24)
        if minimum != self.minimumHeight():
            self.setMinimumHeight(minimum)
            self.geometryChanged.emit()
        self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.arrange()

    def show_records(self, rows):
        self.stats.show_records(rows)
        self.details.show_records(rows)
        self.arrange()
