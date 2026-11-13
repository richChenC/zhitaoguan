"""Native Qt Widgets workspaces, with Qt Charts and Qt Quick 3D."""
from __future__ import annotations

import json
import math
import os
import uuid
import base64
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QEvent, QIODevice, QModelIndex, QObject, QSaveFile, QSize, QUrl, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QBrush, QCloseEvent, QColor, QCursor, QIcon, QImage, QKeySequence, QPainter, QPixmap, QShortcut, QVector3D
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QComboBox,
    QCompleter,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QMenu,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QGridLayout,
    QGraphicsOpacityEffect,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSlider,
    QSizePolicy,
    QScrollArea,
    QStackedWidget,
    QSplitter,
    QStyledItemDelegate,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QToolTip,
    QTreeWidget,
    QTreeWidgetItem,
    QHeaderView,
    QTabWidget,
    QTabBar,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from .constants import APP_ICON, OUTPUT_DIR, PRODUCT_NAME, REPORT_DIR, USER_DATA
from .native_client import NativeClient
from .native_components import (
    AccountIdentityButton, AnalyticsScopeBar, NativeNavigationBar, PlateMap, ReferencePlateMap, SiteCoverageButton, TubeStateGrid,
    ScopeBar, STATE_NAMES, STATE_PALETTE, ToolFlowLayout, WorkspaceContext, button, canonical_site, colored_icon, export_widget_image, icon, status_dot, workspace_styles,
)


class FindingsModel(QAbstractTableModel):
    editRequested = Signal(int, str, object, object)
    selectionChanged = Signal()
    selectionRejected = Signal(str)
    headers = ["选择", "序号", "大修", "机组", "通道编号", "堆芯位置", "三字符", "幅值（V）",
               "相位", "磨损深度\n（壁厚%）", "磨损位置", "测量通道", "探头类型",
               "分析人员", "数据", "数据组", "维护状态", "备注", "堵管移位信息"]
    fields = ["_checked", "_number", "outage", "unit_id", "thimble_id", "position",
              "indication", "volts", "degrees", "percent", "location", "channel",
              "probe", "analyst", "filename", "calgroup", "maintenance_status", "analysis", "maintenance_text"]
    editable_fields = set(fields[4:]) - {"maintenance_status"}

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.rows: list[dict[str, Any]] = []
        self.selected = {}
        self.editable = False
        self.page_offset = 0
        self.pending = set()
        self.dark = False

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.rows):
            return None
        row = self.rows[index.row()]
        field = self.fields[index.column()]
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 0:
            return Qt.CheckState.Checked if row.get("id") in self.selected else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.BackgroundRole and row.get("id") in self.selected:
            return QBrush(QColor("#31524e" if self.dark else "#e9f5f4"))
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if index.column() == 0:
                return ""
            if index.column() == 1:
                return self.page_offset + index.row() + 1
            value = row.get(field, "")
            if role == Qt.ItemDataRole.EditRole and field == "location":
                value = row.get("location_raw", value)
            if role == Qt.ItemDataRole.DisplayRole and field == "indication":
                value = row.get("display_conclusion", value) or "未标注"
            if field == "maintenance_status":
                return " · ".join(STATE_NAMES.get(state, "未记录") for state in
                                  row.get("maintenance_statuses", ["unrecorded"]))
            if value is None:
                return ""
            if field == "percent" and role == Qt.ItemDataRole.DisplayRole:
                return f"{value:g}%" if isinstance(value, (int, float)) else str(value)
            return str(value)
        if role == Qt.ItemDataRole.ToolTipRole:
            if field == "maintenance_status":
                return row.get("maintenance_status_source") or "未找到维护记录"
            return str(row.get(field) or "")
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignCenter)
        return None

    def flags(self, index):
        flags = super().flags(index)
        if index.column() == 0:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        elif self.editable and self.fields[index.column()] in self.editable_fields:
            row = self.rows[index.row()]
            if (row.get("id"), self.fields[index.column()]) not in self.pending:
                flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid():
            return False
        row = self.rows[index.row()]
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 0:
            applied, skipped = self.set_checked_rows([index.row()],
                value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value))
            return bool(applied and not skipped)
        field = self.fields[index.column()]
        if role == Qt.ItemDataRole.EditRole and self.editable and field in self.editable_fields:
            original = row.get("location_raw", row.get(field)) if field == "location" else row.get(field)
            key = (row["id"], field)
            if key in self.pending:
                return False
            if str("" if original is None else original) == str(value):
                return False
            self.pending.add(key)
            self.editRequested.emit(row["id"], field, value, original)
            return True
        return False

    def set_checked_rows(self, indices, checked, anchor=None):
        from .native_workbench_table import finding_scope
        indices = [number for number in indices if 0 <= number < len(self.rows)]
        first = next(iter(self.selected.values()), None) or anchor
        if first is None and indices:
            first = self.rows[indices[0]]
        applied = skipped = 0
        for number in indices:
            row = self.rows[number]
            if checked and first and finding_scope(first) != finding_scope(row):
                skipped += 1
                continue
            if checked:
                self.selected[row["id"]] = dict(row)
            else:
                self.selected.pop(row["id"], None)
            applied += 1
        if applied:
            self.dataChanged.emit(self.index(min(indices), 0), self.index(max(indices), self.columnCount() - 1),
                                  [Qt.ItemDataRole.CheckStateRole, Qt.ItemDataRole.BackgroundRole])
            self.selectionChanged.emit()
        if skipped:
            self.selectionRejected.emit(
                f"不能同时选择不同基地、机组或大修的数据；当前范围为 {first.get('outage')} · {first.get('unit_id')}号机"
                if len(indices) == 1 else f"已按同一基地、机组和大修处理 {applied} 条；跳过其他范围 {skipped} 条")
        return applied, skipped

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.headers[section]
        return section + 1

    def replace(self, rows: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def row(self, index: QModelIndex) -> dict[str, Any] | None:
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        return self.rows[index.row()]


class DataWorkbench(QWidget):
    scopeChanged = Signal(dict)
    tubeFocusRequested = Signal(dict)
    dataChanged = Signal()
    selectionChanged = Signal(list)
    recycleRequested = Signal()
    MAPPING_FIELDS = (
        ("机组号", "机组号", True),
        ("通道编号", "通道编号", True),
        ("在堆芯内的位置", "堆芯位置", False),
        ("幅值", "幅值", False),
        ("相位", "相位", False),
        ("磨损深度", "磨损深度", False),
        ("三字码", "三字码", False),
        ("测量通道", "测量通道", False),
        ("磨损位置", "磨损位置", False),
        ("分析人员", "分析人员", False),
        ("数据", "数据文件", False),
        ("数据组", "数据组", False),
        ("大修号", "大修号", False),
        ("数据点", "数据点", False),
    )

    def __init__(self, client: NativeClient, user: dict[str, Any] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.permissions = None if user is None else set(user.get("permissions", []))
        self.model = FindingsModel(self)
        self.model.editable = self.permissions is None or "data.edit" in self.permissions
        self.model.editRequested.connect(self._edit_cell)
        self.model.selectionChanged.connect(self._selection_changed)
        self._query_number = 0
        self._filter_busy = False
        self._loaded_page = 1
        self._loaded_scope = None
        self._selection_scope = None
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(350)
        self._filter_timer.timeout.connect(self.apply_filters)
        from .native_workbench_table import WorkbenchSortPreference
        self.sort_preference = WorkbenchSortPreference((user or {}).get("username"), self.model.fields)
        self.sort_field, self.sort_order = self.sort_preference.load()
        self.column_filters = {}
        self.auto_ndd = True
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("workbenchScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        content = QWidget()
        self.scroll.setWidget(content)
        outer.addWidget(self.scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(18, 12, 18, 18)
        layout.setSpacing(12)
        band = QWidget()
        band.setObjectName("workbenchFilterBand")
        band.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        band_layout = QVBoxLayout(band)
        band_layout.setContentsMargins(1, 1, 1, 1)
        band_layout.setSpacing(0)
        filters_host = QWidget()
        filters_layout = QVBoxLayout(filters_host)
        filters_layout.setContentsMargins(14, 12, 14, 12)
        filters_layout.setSpacing(12)
        self.filter_flow = QGridLayout()
        self.filter_flow.setHorizontalSpacing(12)
        self.filter_flow.setVerticalSpacing(10)
        self.filter_fields = []
        filters_layout.addLayout(self.filter_flow)
        from .native_workbench_filters import FilterSummary
        self.filter_summary = FilterSummary()
        self.filter_summary.removed.connect(self.clear_filter)
        self.filter_summary.cleared.connect(self.reset_query)
        self.summary = self.filter_summary.lead
        filters_layout.addWidget(self.filter_summary)
        band_layout.addWidget(filters_host)
        commands = QWidget()
        commands.setObjectName("workbenchCommands")
        commands.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        actions = ToolFlowLayout(commands)
        actions.setContentsMargins(14, 8, 14, 8)
        actions.setSpacing(8)
        self.ledger = button("导出综合台账", "upload", self.export_ledger)
        self.delete = button("删除所选", "trash-2", self.delete_selected)
        self.clear = button("清空业务数据", None, self.clear_records)
        self.clear.setProperty("danger", True)
        self.scope_bar = ScopeBar(client, self)
        self.site, self.unit, self.outage = self.scope_bar.site, self.scope_bar.unit, self.scope_bar.outage
        self.scope_bar.changed.connect(self._apply_scope)
        self.scope_bar.hide()
        self.detection_status = QComboBox()
        for label, value in (("全部结论", ""), ("NDD", "ndd"), ("WAR", "war"), ("未标注", "blank")):
            self.detection_status.addItem(label, value)
        self.maintenance_status = QComboBox()
        for label, value in (("全部维护状态", ""), ("正常", "normal"), ("堵管", "plugged"),
                             ("换管", "replaced"), ("移位", "shifted"), ("未记录", "unrecorded")):
            self.maintenance_status.addItem(label, value)
        self.analyst = QLineEdit()
        self.analyst.setPlaceholderText("输入姓名，如 张三")
        self.channel = QLineEdit()
        self.channel.setPlaceholderText("如 6")
        from PySide6.QtGui import QIntValidator
        self.channel.setValidator(QIntValidator(1, 50, self.channel))
        from .native_workbench_table import FieldModeControl, FindingDelegate, FindingTable, WorkbenchPager
        self.pager = WorkbenchPager()
        self.page_size = self.pager.size_combo
        self.search = button("应用筛选", "funnel")
        self.search.setProperty("primary", True)
        self.search.clicked.connect(self.apply_filters)
        self.import_button = button("导入数据", "download")
        self.import_button.setProperty("primary", True)
        self.import_button.clicked.connect(self.import_excel)
        self.import_folder_button = QPushButton("导入 RPT 文件夹")
        self.import_folder_button.clicked.connect(self.import_rpt_folder)
        self.import_folder_button.hide()
        if self.permissions is not None and "data.import" not in self.permissions:
            self.import_button.setEnabled(False)
            self.import_folder_button.setEnabled(False)
            self.import_button.setToolTip("当前账户没有导入数据权限")
            self.import_folder_button.setToolTip("当前账户没有导入数据权限")
        for label, control in (("基地", self.site), ("机组", self.unit), ("大修批次", self.outage),
                               ("检测结论", self.detection_status), ("维护状态", self.maintenance_status),
                               ("分析人员", self.analyst), ("通道编号", self.channel)):
            field = QWidget()
            field.setObjectName("workbenchFilterField")
            field.setMinimumWidth(0)
            field.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            field.setFixedHeight(56)
            self.filter_fields.append(field)
            field_layout = QVBoxLayout(field)
            field_layout.setContentsMargins(0, 0, 0, 0)
            field_layout.setSpacing(5)
            caption = QLabel(label)
            caption.setObjectName("filterLabel")
            caption.setFixedHeight(17)
            field_layout.addWidget(caption)
            control.setMinimumWidth(0)
            control.setFixedHeight(34)
            control.setAccessibleName(label)
            field_layout.addWidget(control)
        self.reset_filters = button("清除条件", "rotate-ccw", self.reset_query)
        self.search.setFixedHeight(34)
        self.reset_filters.setFixedHeight(34)
        self._filter_columns = 0
        self._arrange_filters(1480)
        self.analyst.returnPressed.connect(self.apply_filters)
        self.channel.returnPressed.connect(self.apply_filters)
        self.recycle_button = button("回收站", "archive-restore", self.recycleRequested.emit)
        self.recycle_button.setEnabled(self.permissions is None or "data.delete" in self.permissions)
        for title, controls in (("数据文件", (self.import_button, self.ledger)),
                                ("记录维护", (self.delete, self.recycle_button, self.clear))):
            group = QWidget()
            group.setObjectName("workbenchActionGroup")
            group_layout = QHBoxLayout(group)
            group_layout.setContentsMargins(0 if title == "数据文件" else 13, 0, 0, 0)
            group_layout.setSpacing(6)
            caption = QLabel(title)
            caption.setObjectName("workbenchCommandCaption")
            group_layout.addWidget(caption)
            for control in controls:
                control.setFixedHeight(34 if control in (self.import_button, self.clear) else 30)
                control.setProperty("commandHeight", 34 if control in (self.import_button, self.clear) else 30)
                group_layout.addWidget(control)
            group.setProperty("separated", title != "数据文件")
            group.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
            actions.addWidget(group)
        self.refresh_button = button("", "refresh-cw", self.load_findings)
        self.refresh_button.setFixedSize(30, 30)
        self.refresh_button.setObjectName("workbenchRefresh")
        self.refresh_button.setToolTip("刷新检测记录")
        self.refresh_button.setAccessibleName("刷新检测记录")
        actions.addWidget(self.refresh_button)
        band_layout.addWidget(commands)
        layout.addWidget(band)
        for control, permission in ((self.ledger, "export.create"), (self.delete, "data.delete"),
                                    (self.clear, "data.purge")):
            control.setEnabled(self.permissions is None or permission in self.permissions)

        self.table = FindingTable()
        self.table.setObjectName("workbenchTable")
        self.table.setModel(self.model)
        self.table.setItemDelegate(FindingDelegate(self.table))
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setMinimumSectionSize(40)
        self.table.horizontalHeader().setFixedHeight(51)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.verticalHeader().hide()
        self.table.setColumnWidth(0, 45)
        self.table.setColumnWidth(1, 50)
        self.table.checkRequested.connect(self._check_rows)
        self.table.editSelectionUndoRequested.connect(self._undo_edit_selection)
        self.table.selectPageRequested.connect(self.toggle_page)
        self.model.selectionRejected.connect(self.pager.status.setText)
        self.table.horizontalHeader().setSectionsClickable(True)
        self.table.horizontalHeader().sectionClicked.connect(self.sort_column)
        self._paint_sort()
        self.table.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.horizontalHeader().customContextMenuRequested.connect(self.filter_column)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("workbenchSplitter")
        self.splitter.setHandleWidth(44)
        self.splitter.setChildrenCollapsible(False)
        table_host = QWidget()
        self.table_host = table_host
        table_host.setMinimumHeight(350)
        table_host.setObjectName("workspacePanel")
        table_layout = QVBoxLayout(table_host)
        table_layout.setContentsMargins(1, 1, 1, 1)
        table_layout.setSpacing(0)
        self.table_heading = QWidget()
        self.table_heading.setObjectName("workbenchTableHeading")
        self.table_heading.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.table_heading.setFixedHeight(55)
        table_heading = QHBoxLayout(self.table_heading)
        table_heading.setContentsMargins(14, 10, 14, 11)
        table_heading.setSpacing(9)
        self.records_title = QLabel("检测记录")
        self.records_title.setObjectName("workbenchTableTitle")
        table_heading.addWidget(self.records_title)
        self.record_count = QLabel("共 0 条")
        self.record_count.setObjectName("workbenchRecordCount")
        table_heading.addWidget(self.record_count)
        self.selection_info = QLabel("已勾选 0 条")
        self.selection_info.setObjectName("workbenchSelectionCount")
        table_heading.addWidget(self.selection_info)
        table_heading.addStretch()
        self.select_page_button = button("全选本页", "check-check", self.toggle_page)
        self.clear_selection_button = button("清除勾选", "x", self.clear_selection)
        for control in (self.select_page_button, self.clear_selection_button):
            control.setObjectName("workbenchSelectionButton")
            control.setFixedSize(87, 34)
            control.setIconSize(QSize(15, 15))
        table_heading.addWidget(self.select_page_button)
        table_heading.setSpacing(6)
        table_heading.addWidget(self.clear_selection_button)
        table_heading.addSpacing(10)
        self.field_modes = FieldModeControl()
        self.field_mode = self.field_modes.tabs
        self.field_mode.currentChanged.connect(self._set_field_mode)
        table_heading.addWidget(self.field_modes)
        table_layout.addWidget(self.table_heading)
        table_layout.addWidget(self.table, 1)
        self.splitter.addWidget(table_host)
        from .native_workbench_plate import WorkbenchPlatePanel
        self.map_panel = map_host = WorkbenchPlatePanel(self.export_plate)
        self.map_unit = QSpinBox(map_host)
        self.map_unit.setRange(1, 99)
        self.map_unit.setPrefix("机组 ")
        self.map_unit.valueChanged.connect(self._update_plate)
        self.map_unit.hide()
        self.parity_tabs = map_host.tabs
        self.parity_tabs.currentChanged.connect(self._set_plate_parity)
        self.plate = map_host.plate
        self.plate.allow_parity_switch = False
        self.plate.interactionRejected.connect(self.pager.status.setText)
        self.plate.tubeClicked.connect(self._tube_clicked)
        self.plate.unitChanged.connect(self.map_unit.setValue)
        self.plate_detail = map_host.details
        self.plate_detail.focusRequested.connect(self.tubeFocusRequested.emit)
        self.plate_stats = map_host.stats
        map_host.export_button.setEnabled(self.permissions is None or "export.create" in self.permissions)
        self.splitter.addWidget(map_host)
        map_host.geometryChanged.connect(self._sync_splitter_height)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([854, 531])
        layout.addWidget(self.splitter, 1)
        self.core_rows = []
        self.status = self.pager.status
        self.edit_action = QAction("编辑选中记录", self.table)
        self.edit_action.triggered.connect(self.edit_selected_finding)
        self.edit_action.setEnabled(self.permissions is None or "data.edit" in self.permissions)
        self.table.addAction(self.edit_action)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        self.prev, self.next = self.pager.prev, self.pager.next
        self.page_info, self.page_jump = self.pager.info, self.pager.jump
        self.pager.pageRequested.connect(self.go_to_page)
        self._page_shortcuts = []
        for key, delta in (("Alt+Left", -1), ("Alt+Right", 1)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda step=delta: self._change_page(step))
            self._page_shortcuts.append(shortcut)
        table_layout.addWidget(self.pager)
        self.page = 1
        self.pages = 1
        self._import_task: str | None = None
        self._import_mode = "excel"
        self._import_path = ""
        self._import_mapping: dict[str, Any] | None = None
        self._import_reports: list[str] = []
        self._import_confirmation: dict[str, Any] | None = None
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(400)
        self._progress_timer.timeout.connect(self._poll_import_progress)
        self._set_field_mode()
        self.pager.sizeChanged.connect(self.apply_filters)
        self.field_modes.saveFailed.connect(self.status.setText)
        for control in (self.site, self.unit, self.outage, self.detection_status, self.maintenance_status):
            control.currentIndexChanged.connect(self._sync_filter_summary)
        for control in (self.detection_status, self.maintenance_status):
            control.currentIndexChanged.connect(self.apply_filters)
        for control in (self.analyst, self.channel):
            control.textChanged.connect(self._sync_filter_summary)
            control.textEdited.connect(lambda _text: self._filter_timer.start())
            control.installEventFilter(self)
        self.scope_bar.loaded.connect(self._sync_filter_summary)
        self._sync_filter_summary()
        self.load_overview()
        self.load_findings()

    def _set_field_mode(self, *_):
        important = {"_checked", "_number", "outage", "unit_id", "thimble_id", "position",
                     "indication", "percent", "location", "maintenance_status", "analysis", "maintenance_text"}
        focus_widths = (58, 58, 81, 70, 104, 104, 93, 72, 72, 128, 128, 104, 104, 104, 160, 160, 139, 197, 174)
        all_widths = (54, 54, 72, 72, 104, 104, 72, 72, 72, 104, 104, 104, 104, 104, 160, 160, 160, 160, 160)
        widths = focus_widths if self.field_mode.currentIndex() == 0 else all_widths
        for column, field in enumerate(self.model.fields):
            self.table.setColumnHidden(column, self.field_mode.currentIndex() == 0 and field not in important)
            self.table.setColumnWidth(column, widths[column])

    def _set_plate_parity(self, index):
        self.plate.parity = ("both", "odd", "even")[index]
        self.plate.update()

    def reset_query(self):
        self._filter_timer.stop()
        for control in (self.analyst, self.channel, self.detection_status, self.maintenance_status):
            control.blockSignals(True)
        try:
            self.analyst.clear()
            self.channel.clear()
            self.detection_status.setCurrentIndex(0)
            self.maintenance_status.setCurrentIndex(0)
        finally:
            for control in (self.analyst, self.channel, self.detection_status, self.maintenance_status):
                control.blockSignals(False)
        self.column_filters.clear()
        self.scope_bar.clear()

    def _arrange_filters(self, width):
        columns = 6 if width <= 1279 else 9
        if self._filter_columns == columns:
            return
        self._filter_columns = columns
        while self.filter_flow.count():
            self.filter_flow.takeAt(0)
        for column in range(9):
            self.filter_flow.setColumnMinimumWidth(column, 0)
            self.filter_flow.setColumnStretch(column, 0)
        if columns == 9:
            for column in range(7):
                self.filter_flow.setColumnStretch(column, 1)
            for column in (7, 8):
                self.filter_flow.setColumnMinimumWidth(column, 96)
        else:
            for column in range(4):
                self.filter_flow.setColumnStretch(column, 1)
            self.filter_flow.setColumnMinimumWidth(4, 92)
            self.filter_flow.setColumnMinimumWidth(5, 155)
        for index, widget in enumerate([*self.filter_fields, self.search, self.reset_filters]):
            widget.setMaximumWidth(16777215)
            self.filter_flow.addWidget(widget, index // columns, index % columns,
                                       Qt.AlignmentFlag.AlignBottom)
        self.filter_flow.invalidate()

    def _active_filters(self):
        from .native_components import SITE_NAMES
        entries = []
        controls = (("site", "基地", self.site), ("unit", "机组", self.unit),
                    ("outage", "大修批次", self.outage), ("detection_status", "检测结论", self.detection_status),
                    ("maintenance_status", "维护状态", self.maintenance_status),
                    ("analyst", "分析人员", self.analyst), ("thimble", "通道编号", self.channel))
        for key, title, control in controls:
            value = str(control.currentData() or "") if isinstance(control, QComboBox) else control.text().strip()
            if not value:
                continue
            if key == "site":
                display_code = {"P": "HZ", "C": "CN"}.get(value, value)
                text = f"{SITE_NAMES.get(value, value)}（{display_code}）"
            elif key == "unit":
                text = f"{value} 号"
            elif key == "thimble":
                text = f"#{value}"
            else:
                text = control.currentText() if isinstance(control, QComboBox) else value
            entries.append((key, f"{title}：{text}"))
        for field, value in self.column_filters.items():
            label = self.model.headers[self.model.fields.index(field)].replace("\n", "") if field in self.model.fields else field
            entries.append((f"column:{field}", f"{label}：{value}"))
        return entries

    def _sync_filter_summary(self, *_):
        entries = self._active_filters()
        self.filter_summary.set_entries(entries, self._filter_busy)
        self.reset_filters.setEnabled(bool(entries))
        self.reset_filters.setToolTip("清除全部筛选条件（含列筛选）" if entries else "当前没有筛选条件")
        active_keys = {key for key, _ in entries}
        for key, field in zip(("site", "unit", "outage", "detection_status", "maintenance_status", "analyst", "thimble"),
                              self.filter_fields):
            active = key in active_keys
            if field.property("active") != active:
                field.setProperty("active", active)
                for control in [field, *field.findChildren(QWidget)]:
                    control.style().unpolish(control)
                    control.style().polish(control)
        self._update_workbench_actions()

    def clear_filter(self, key):
        self._filter_timer.stop()
        if key.startswith("column:"):
            self.column_filters.pop(key[7:], None)
        else:
            control = {"site": self.site, "unit": self.unit, "outage": self.outage,
                       "detection_status": self.detection_status, "maintenance_status": self.maintenance_status,
                       "analyst": self.analyst, "thimble": self.channel}.get(key)
            if control is None:
                return
            if isinstance(control, QComboBox):
                if control.currentIndex() > 0:
                    control.setCurrentIndex(0)
                    return
            else:
                control.clear()
        self.apply_filters()

    def _update_workbench_actions(self):
        busy = self._filter_busy
        selected = bool(self.model.selected)
        self.select_page_button.setEnabled(not busy and self.model.rowCount() > 0)
        self.clear_selection_button.setEnabled(not busy and selected)
        self.selection_info.setVisible(selected)
        self.delete.setEnabled(not busy and selected and (self.permissions is None or "data.delete" in self.permissions))
        self.pager.set_state(self.page, self.pages, busy=busy)
        self.refresh_button.setEnabled(not busy)

    def eventFilter(self, watched, event):
        if (watched in (self.analyst, self.channel) and event.type() == QEvent.Type.KeyPress
                and event.key() == Qt.Key.Key_Escape and watched.text()):
            watched.clear()
            self.apply_filters()
            return True
        return super().eventFilter(watched, event)

    def sort_column(self, section):
        field = self.model.fields[section]
        if field.startswith("_"):
            return
        if self.sort_field != field:
            self.sort_field, self.sort_order = field, "asc"
        elif self.sort_order == "asc":
            self.sort_order = "desc"
        else:
            self.sort_field, self.sort_order = "", "asc"
        self._paint_sort()
        self.apply_filters()
        try:
            self.sort_preference.save(self.sort_field, self.sort_order)
        except OSError as error:
            self.status.setText(f"排序已切换，但未能保存偏好：{error}")

    def _paint_sort(self):
        header = self.table.horizontalHeader()
        header.setSortIndicatorShown(bool(self.sort_field))
        if self.sort_field:
            header.setSortIndicator(self.model.fields.index(self.sort_field),
                                    Qt.SortOrder.DescendingOrder if self.sort_order == "desc"
                                    else Qt.SortOrder.AscendingOrder)

    def filter_column(self, point):
        section = self.table.horizontalHeader().logicalIndexAt(point)
        if section < 0:
            return
        field = self.model.fields[section]
        if field.startswith("_") or field == "maintenance_status":
            return
        value, accepted = QInputDialog.getText(self, "筛选列", self.model.headers[section],
                                               text=self.column_filters.get(field, ""))
        if accepted:
            if value.strip():
                self.column_filters[field] = value.strip()
            else:
                self.column_filters.pop(field, None)
            self.apply_filters()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange_filters(event.size().width())
        width = event.size().width()
        vertical = width <= 1120
        self.map_panel.set_side_by_side(vertical)
        self.splitter.setOrientation(Qt.Orientation.Vertical if vertical else Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(16 if vertical else 44)
        first = self.map_panel if width <= 1100 else self.table_host
        if self.splitter.widget(0) is not first:
            self.splitter.insertWidget(0, first)
        self.table_host.setMinimumHeight(718 if vertical else 350)
        self._sync_splitter_height()

    def _sync_splitter_height(self):
        if self.splitter.orientation() == Qt.Orientation.Vertical:
            height = self.table_host.minimumHeight() + self.map_panel.minimumHeight() + self.splitter.handleWidth()
        else:
            height = max(self.table_host.minimumHeight(), self.map_panel.minimumHeight())
        self.splitter.setMinimumHeight(height)

    def _params(self) -> str:
        from urllib.parse import urlencode
        values = {
            "page": self.page, "size": self.page_size.currentData(),
            **self.scope_bar.values(), "analyst": self.analyst.text().strip(),
            "thimble": self.channel.text().strip(),
            "detection_status": self.detection_status.currentData(),
            "maintenance_status": self.maintenance_status.currentData(),
            "auto_ndd": "1" if self.auto_ndd else "0",
            "sort": self.sort_field, "order": self.sort_order,
            **{f"column_{key}": value for key, value in self.column_filters.items()},
        }
        return "?" + urlencode({key: value for key, value in values.items() if value != ""})

    def load_overview(self) -> None:
        self.client.get("/api/overview", self._on_overview)

    def _on_overview(self, data: dict[str, Any] | None, error: str | None) -> None:
        if error or not data:
            self.summary.setToolTip(error or "概况读取失败")
            return
        stats = data.get("stats") or {}
        self.summary.setToolTip(
            f"检测记录 {stats.get('findings', 0):,} 条  |  大修 {stats.get('outages', 0)} 个  |  "
            f"机组 {stats.get('units', 0)} 个  |  分析人员 {stats.get('analysts', 0)} 人"
        )
        self.overview_data = data
        selected = self.detection_status.currentData()
        self.detection_status.blockSignals(True)
        while self.detection_status.count() > 4:
            self.detection_status.removeItem(4)
        known = {"", "ndd", "war", "blank", "none", "no defect"}
        for value in data.get("indications") or []:
            code = str(value).strip()
            if code and code != "/" and code.casefold() not in known:
                self.detection_status.addItem(code, code.casefold())
                known.add(code.casefold())
        index = self.detection_status.findData(selected)
        self.detection_status.setCurrentIndex(max(0, index))
        self.detection_status.blockSignals(False)
        analysts = [str(value) for value in data.get("analysts") or []]
        completer = self.analyst.completer()
        if completer is None:
            completer = QCompleter(analysts, self.analyst)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            self.analyst.setCompleter(completer)
        else:
            completer.model().setStringList(analysts)
        if selected and index < 0:
            self.load_findings()

    def apply_filters(self):
        self._filter_timer.stop()
        if self.channel.text() and not self.channel.hasAcceptableInput():
            self.status.setText("通道号应为 1-50 的整数")
            return
        self.page = 1
        self.scopeChanged.emit({**self.scope_bar.values(), "thimble": self.channel.text().strip()})
        self.load_findings()

    def _apply_scope(self, scope):
        self.map_unit.setValue(int(scope.get("unit") or 1))
        self.apply_filters()

    def set_workspace_scope(self, scope):
        normalized = {key: str(scope.get(key) or "") for key in ("site", "unit", "outage")}
        self._workspace_tube = int(scope.get("thimble") or 0)
        self.map_unit.setValue(int(normalized.get("unit") or 1))
        self._update_plate()
        if normalized == {key: str(value) for key, value in self.scope_bar.values().items()}:
            return
        self.scope_bar.set_scope(normalized)
        self.page = 1
        self.load_findings()

    def load_findings(self, *, page_only=False) -> None:
        from urllib.parse import parse_qsl, urlencode
        params = dict(parse_qsl(self._params()[1:]))
        selection_scope = tuple(sorted((key, value) for key, value in params.items()
                                      if key not in {"page", "size", "sort", "order"}))
        if selection_scope != self._selection_scope:
            self._selection_scope = selection_scope
            self.clear_selection()
        scope = tuple(sorted((key, value) for key, value in params.items() if key != "page"))
        keep_page = page_only and scope == self._loaded_scope and bool(self.model.rows)
        if keep_page:
            params["core"] = "0"
        self.status.setText("正在加载...")
        self._filter_busy = True
        self._sync_filter_summary()
        self._query_number += 1
        number = self._query_number
        def loaded(data, error):
            if number != self._query_number:
                return
            self._on_findings(data, error, page_only=keep_page)
            if not error and data:
                self._loaded_scope = scope
        self.client.get(f"/api/findings?{urlencode(params)}", loaded)

    def _on_findings(self, data: dict[str, Any] | None, error: str | None, *, page_only=False) -> None:
        self._filter_busy = False
        if error or not data:
            self.status.setText(error or "数据读取失败")
            if page_only:
                self.page = self._loaded_page
            else:
                self.page = self.pages = 1
                self.model.replace([])
                self.record_count.setText("加载失败")
                self.core_rows = []
                self._loaded_scope = None
                self._update_plate()
            self._sync_filter_summary()
            return
        self.page = int(data.get("page") or 1)
        self._loaded_page = self.page
        size = int(data.get("size") or self.page_size.currentData())
        self.model.page_offset = (self.page - 1) * size
        self.model.replace(data.get("items") or [])
        total = int(data.get("total") or 0)
        if not total:
            self.clear_selection()
        self.record_count.setText(f"共 {total} 条")
        if not page_only:
            self.core_rows = data.get("core_items") or []
            self._update_plate()
        self.pages = max(1, int(data.get("pages") or 1))
        start = (self.page - 1) * size + 1
        self.status.setText(f"第 {start}\u2013{min(self.page * size, total)} 条，共 {total} 条" if total else "共 0 条")
        self._sync_filter_summary()

    def _change_page(self, delta: int) -> None:
        self.go_to_page(self.page + delta)

    def go_to_page(self, page: int) -> bool:
        if self._filter_busy:
            return False
        if self._filter_timer.isActive():
            self.apply_filters()
            return False
        target = max(1, min(self.pages, page))
        if target == self.page:
            return False
        self.page = target
        self.table.scrollToTop()
        self.load_findings(page_only=True)
        return True

    def edit_selected_finding(self, index: QModelIndex | None = None) -> None:
        """Start native inline editing; the model submits an audited update."""
        if self.permissions is not None and "data.edit" not in self.permissions:
            QMessageBox.information(self, PRODUCT_NAME, "当前账户没有检测记录编辑权限")
            return
        if index is None or not isinstance(index, QModelIndex) or not index.isValid():
            index = self.table.currentIndex()
        if index.isValid() and self.model.fields[index.column()] in self.model.editable_fields:
            self.table.edit(index)
        else:
            QMessageBox.information(self, PRODUCT_NAME, "请选择可编辑的检测字段")

    def _finding_edited(self, label: str, data: dict[str, Any] | None,
                        error: str | None) -> None:
        self.edit_action.setEnabled(self.permissions is None or "data.edit" in self.permissions)
        if error or not data:
            self.status.setText("保存失败")
            QMessageBox.warning(self, PRODUCT_NAME, error or f"{label}保存失败")
            return
        self.status.setText(f"{label}已保存，正在刷新...")
        self.load_overview()
        self.load_findings()
        self.dataChanged.emit()

    def _edit_cell(self, finding_id, field, value, expected):
        self.status.setText("正在保存...")
        def done(data, error):
            self.model.pending.discard((finding_id, field))
            if error or not data:
                self.status.setText(error or "保存失败")
                QMessageBox.warning(self, PRODUCT_NAME, error or "保存失败")
                self.load_findings()
                return
            if finding_id in self.model.selected:
                self.model.selected.pop(finding_id)
                self._selection_changed()
            self.status.setText("已保存，审计已记录")
            self.load_findings()
            self.dataChanged.emit()
        self.client.post("/api/findings/edit",
                         {"id": finding_id, "field": field, "value": value, "expected_value": expected}, done)

    def _selection_changed(self):
        self.selection_info.setText(f"已勾选 {len(self.model.selected):,} 条")
        self._update_workbench_actions()
        self._update_plate()
        self.selectionChanged.emit(list(self.model.selected.values()))

    def clear_selection(self):
        self.model.selected.clear()
        self.model.layoutChanged.emit()
        self._selection_changed()

    def refresh_selection(self):
        ids = list(self.model.selected)
        if not ids:
            return
        generation = getattr(self, "_selection_refresh", 0) + 1
        self._selection_refresh = generation
        chunks = [ids[start:start + 400] for start in range(0, len(ids), 400)]
        refreshed = {}
        pending = len(chunks)
        failed = False

        def loaded(data, error):
            nonlocal pending, failed
            if generation != self._selection_refresh:
                return
            failed |= bool(error or not data)
            for row in (data or {}).get("items") or []:
                refreshed[row["id"]] = row
            pending -= 1
            if pending:
                return
            if failed:
                self.status.setText("所选记录刷新失败，导出前请重新核对选择范围")
                return
            for finding_id in ids:
                if finding_id in self.model.selected:
                    if finding_id in refreshed:
                        self.model.selected[finding_id] = refreshed[finding_id]
                    else:
                        self.model.selected.pop(finding_id)
            self.model.layoutChanged.emit()
            self._selection_changed()
        for chunk in chunks:
            self.client.get("/api/findings?raw=1&sources=1&core=0&size=500&ids="
                            + ",".join(map(str, chunk)), loaded)

    def toggle_page(self):
        if not self._filter_busy:
            self.model.set_checked_rows(range(self.model.rowCount()), True)

    def _check_rows(self, number, extend, checked, anchor_index):
        if self._filter_busy:
            return
        self._last_click_presentation = (self.map_unit.value(), self.parity_tabs.currentIndex())
        anchor = self.model.rows[anchor_index] if 0 <= anchor_index < self.model.rowCount() else None
        indices = range(min(anchor_index, number), max(anchor_index, number) + 1) if extend and anchor else [number]
        self.model.set_checked_rows(indices, checked, anchor if extend else None)

    def _undo_edit_selection(self, number, checked):
        presentation = getattr(self, "_last_click_presentation", None)
        self.model.set_checked_rows([number], checked)
        if presentation:
            self.map_unit.setValue(presentation[0])
            self.parity_tabs.setCurrentIndex(presentation[1])

    def _update_plate(self, *_):
        if not hasattr(self, "plate"):
            return
        self._plate_detail_request = getattr(self, "_plate_detail_request", 0) + 1
        rows = list(self.model.selected.values())
        scopes = {(row.get("site_code"), row.get("outage"), row.get("unit_id")) for row in rows}
        if rows and len(scopes) == 1:
            self.map_unit.blockSignals(True)
            self.map_unit.setValue(int(rows[0]["unit_id"]))
            self.map_unit.blockSignals(False)
            self.parity_tabs.setCurrentIndex(1 if int(rows[0]["unit_id"]) % 2 else 2)
        unit = self.map_unit.value()
        selected = [row["thimble_id"] for row in self.model.selected.values() if int(row["unit_id"]) == unit]
        if getattr(self, "_workspace_tube", 0):
            selected.append(self._workspace_tube)
        self.plate.set_records(rows if len(scopes) == 1 else [], unit, selected)
        self.plate.selection_ready = bool(self.unit.currentData() or (rows and len(scopes) == 1))
        self.map_panel.show_records(rows)

    def _record_clicked(self, index):
        self._plate_detail_request = getattr(self, "_plate_detail_request", 0) + 1
        row = self.model.row(index)
        if row:
            self.scopeChanged.emit({"site": canonical_site(row.get("site_code") or re.sub(r"\d.*", "", row["outage"])),
                                    "unit": str(row["unit_id"]), "outage": row["outage"],
                                    "thimble": str(row["thimble_id"])})
            self.map_unit.setValue(int(row["unit_id"]))
            self.plate.selected = {int(row["thimble_id"])}
            self.plate.update()
            self.plate_detail.setText(f"{row['outage']} · {row['thimble_id']}号管 · {row.get('position') or ''}\n"
                                      f"{row.get('analysis') or ''}\n{row.get('report_path') or ''}")
            self.map_panel.arrange()

    def _tube_clicked(self, tube):
        from urllib.parse import urlencode
        values = self.scope_bar.values()
        rows = list(self.model.selected.values())
        scopes = {(row.get("site_code"), row.get("unit_id"), row.get("outage")) for row in rows}
        anchor = rows[0] if rows and len(scopes) == 1 else {}
        unit = values.get("unit") or anchor.get("unit_id")
        if not unit:
            self.status.setText("请先筛选机组或勾选同一机组、同一次大修的数据")
            return
        scope = {"site": values.get("site") or anchor.get("site_code") or "",
                 "unit": str(unit), "outage": values.get("outage") or anchor.get("outage") or "",
                 "thimble": str(tube)}
        self._plate_detail_request = getattr(self, "_plate_detail_request", 0) + 1
        serial = self._plate_detail_request
        self.plate_detail.setText("正在读取管位检测记录...")
        self.map_panel.arrange()
        def loaded(data, error):
            if serial != self._plate_detail_request:
                return
            if error or not data:
                self.plate_detail.setText(error or "管位记录读取失败")
            else:
                records = data.get("items") or []
                channel = next(item for item in self.plate.channels if
                               int(item["serialOdd" if int(unit) % 2 else "serialEven"]) == tube)
                self.plate_detail.show_tube(scope, channel["pos"], records)
            self.map_panel.arrange()
        self.client.get("/api/findings?" + urlencode({**scope, "page": 1, "size": 200}), loaded)

    def export_plate(self):
        if self.permissions is not None and "export.create" not in self.permissions:
            self.status.setText("当前账户没有图片导出权限")
            return
        from .artifact_save import artifact_name
        from .native_plate_snapshot import create_plate_snapshot
        try:
            image, scope = create_plate_snapshot(list(self.model.selected.values()), self.plate.channels,
                                                 self.plate.levels, self.plate.colors)
        except ValueError as error:
            self.status.setText(str(error))
            return
        site = {"P": "HZ", "C": "CN"}.get(scope["site"], scope["site"])
        outage = re.sub(r"^[A-Za-z]+", lambda match: {"P": "HZ", "C": "CN"}.get(match[0], match[0]),
                        scope["outage"])
        name = artifact_name("管板缺陷分布", f"{site}_{scope['unit']}号机组_{outage}", "png")
        export_widget_image(self, self.client, None, "导出管板图片", image=image, default_name=name)

    def export_ledger(self):
        from urllib.parse import parse_qs
        payload = {key: values[0] for key, values in parse_qs(self._params()[1:]).items()
                   if key not in {"page", "size"}}
        self.ledger.setEnabled(False)
        def done(data, error):
            self.ledger.setEnabled(True)
            self.status.setText(error or f"台账已导出：{(data or {}).get('file_path', '')}")
        self.client.post("/api/data-ledger/export", payload, done)

    def delete_selected(self):
        ids = list(self.model.selected)
        if not ids:
            QMessageBox.information(self, PRODUCT_NAME, "请先勾选记录")
            return
        self.client.post("/api/data/delete-preview", {"scope": "selected", "data": {"findingIds": ids}},
                         lambda data, error: self._delete_preview(ids, data, error))

    def _delete_preview(self, ids, data, error):
        if error:
            QMessageBox.warning(self, PRODUCT_NAME, error)
            return
        preview = (data or {}).get("preview") or {}
        if QMessageBox.question(self, "删除所选记录",
                               f"将删除 {preview.get('findings', len(ids))} 条记录，可在回收站恢复。是否继续？") != QMessageBox.StandardButton.Yes:
            return
        self.client.post("/api/data/delete", {"scope": "selected", "data": {"findingIds": ids}},
                         self._data_action_done)

    def clear_records(self):
        text, accepted = QInputDialog.getText(self, "清空业务数据", "输入“清空记录”以确认。操作前自动备份，账户保留。")
        if accepted and text == "清空记录":
            self.client.post("/api/clear", {"confirmed": True}, self._data_action_done)

    def _data_action_done(self, data, error):
        if error or not data:
            QMessageBox.warning(self, PRODUCT_NAME, error or "操作失败")
            return
        self.clear_selection()
        self.page = 1
        self.load_overview()
        self.scope_bar.reload()
        self.load_findings()
        self.dataChanged.emit()

    def import_excel(self) -> None:
        self._open_import_wizard("excel")

    def _open_import_wizard(self, mode, source_path=None):
        if self.permissions is not None and "data.import" not in self.permissions:
            return
        from .native_import import ImportWizard
        from .native_components import Preferences
        context = getattr(self.window(), "context", None)
        preferences = context.preferences.values if context else Preferences().values
        wizard = ImportWizard(self.client, self.MAPPING_FIELDS, preferences, self, mode=mode)
        wizard.imported.connect(self._wizard_imported)
        if source_path:
            wizard.path.setText(source_path)
            QTimer.singleShot(0, wizard.next)
        wizard.exec()
        wizard.deleteLater()

    def _wizard_imported(self, result):
        self.page = 1
        self.scope_bar.reload()
        self.load_overview()
        self.load_findings()
        self.dataChanged.emit()
        self.status.setText(f"导入完成：新增 {result.get('inserted', 0)} 条，跳过 {result.get('skipped', 0)} 条")

    @staticmethod
    def _report_group_key(option: dict[str, Any]) -> tuple[str, int, str, str]:
        """Return the same group identity enforced by the backend."""
        return (
            str(option.get("site_code") or "").upper(),
            int(option.get("unit_id") or 0),
            str(option.get("outage") or "").upper(),
            str(option.get("group") or ""),
        )

    def import_rpt_folder(self) -> None:
        self._open_import_wizard("directory")

    def _after_report_options(self, path: str, data: dict[str, Any] | None,
                              error: str | None) -> None:
        if error or not data:
            self.import_folder_button.setEnabled(True)
            self.status.setText("RPT 扫描失败")
            QMessageBox.warning(self, PRODUCT_NAME, error or "RPT 扫描失败")
            return
        options = [item for item in (data.get("reports") or []) if isinstance(item, dict)]
        valid = [item for item in options if not item.get("error") and item.get("path")]
        groups: dict[tuple[str, int, str, str], list[dict[str, Any]]] = {}
        for item in valid:
            groups.setdefault(self._report_group_key(item), []).append(item)
        if not groups:
            self.import_folder_button.setEnabled(True)
            self.status.setText("未找到可用 RPT 数据组")
            QMessageBox.warning(self, PRODUCT_NAME, "所选目录中未找到可解析的指套管 RPT 数据组。")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("RPT 报告选择与导入确认")
        dialog.resize(980, 700)
        layout = QVBoxLayout(dialog)
        intro = QLabel(
            f"已扫描 {len(valid)} 份候选报告，分为 {len(groups)} 个数据组。"
            "每个数据组必须选择唯一一份 RPT；文件哈希会随确认信息提交并由后端复核。"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        if len(valid) != len(options):
            warning = QLabel(f"另有 {len(options) - len(valid)} 份报告解析失败，已排除并保留在质量审计中。")
            warning.setWordWrap(True)
            warning.setObjectName("muted")
            layout.addWidget(warning)

        group_rows: list[tuple[tuple[str, int, str, str], QComboBox]] = []
        table = QTableWidget(len(groups), 5, dialog)
        table.setHorizontalHeaderLabels(["基地/机组", "大修", "数据组", "候选报告", "记录数"])
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        for row, (key, candidates) in enumerate(sorted(groups.items(), key=lambda item: item[0])):
            candidates.sort(key=lambda item: int(item.get("modified_ns") or 0), reverse=True)
            site, unit, outage, group = key
            table.setItem(row, 0, QTableWidgetItem(f"{site or '未标注'} / {unit}号机"))
            table.setItem(row, 1, QTableWidgetItem(outage or "未标注"))
            table.setItem(row, 2, QTableWidgetItem(group))
            combo = QComboBox(table)
            for candidate in candidates:
                label = (
                    f"{candidate.get('name') or Path(str(candidate['path'])).name} · "
                    f"{candidate.get('records', 0):,} 条 · "
                    f"{candidate.get('modified_at') or '时间未知'}"
                )
                combo.addItem(label, candidate)
            table.setCellWidget(row, 3, combo)
            table.setItem(row, 4, QTableWidgetItem(str(candidates[0].get("records", 0))))
            group_rows.append((key, combo))
        table.resizeColumnsToContents()
        table.setColumnWidth(3, 500)
        layout.addWidget(table, 1)

        policy = QComboBox()
        policy.addItem("空三字符先进入待复核", "review")
        policy.addItem("空三字符按 WAR 填充", "fill_war")
        policy_form = QFormLayout()
        policy_form.addRow("缺失三字符处理", policy)
        layout.addLayout(policy_form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.import_folder_button.setEnabled(True)
            self.status.setText("已取消 RPT 导入")
            return

        selected: list[str] = []
        for _key, combo in group_rows:
            option = combo.currentData() or {}
            selected.append(str(option.get("path") or ""))
        if len(selected) != len(set(selected)) or any(not item for item in selected):
            self.import_folder_button.setEnabled(True)
            QMessageBox.warning(self, PRODUCT_NAME, "每个数据组必须选择一份唯一的 RPT。")
            return
        confirmation = {
            "confirmed": True,
            "candidates": [
                {
                    "path": str(item.get("path") or ""),
                    "sha256": str(item.get("sha256") or ""),
                    "sum_sha256": str(item.get("sum_sha256") or ""),
                }
                for item in valid
            ],
        }
        self._import_reports = selected
        self._import_confirmation = confirmation
        self.import_policy = str(policy.currentData() or "review")
        self._run_directory_import()

    def _run_directory_import(self) -> None:
        self.status.setText("正在导入 RPT 数据，请勿关闭软件...")
        token = self._new_import_task()
        self._start_import_progress(token)
        self.client.post("/api/import", {
            "path": self._import_path,
            "reports": self._import_reports,
            "blank_indication_policy": self.import_policy,
            "report_confirmation": self._import_confirmation,
        }, self._on_import, task_token=token)

    @staticmethod
    def _mapping_payload(sheet: dict[str, Any], header_row: int,
                         column_boxes: dict[str, QComboBox]) -> dict[str, Any]:
        return {
            "sheet": str(sheet.get("name") or ""),
            "header_row": int(header_row),
            "columns": {
                key: box.currentData()
                for key, box in column_boxes.items()
                if box.currentData() is not None
            },
        }

    def _after_inspect(self, path: str, data: dict[str, Any] | None, error: str | None) -> None:
        if error or not data:
            self.import_button.setEnabled(True)
            QMessageBox.warning(self, PRODUCT_NAME, error or "Excel 检查失败")
            self.status.setText("检查失败")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("导入前检查")
        dialog.resize(820, 650)
        form = QVBoxLayout(dialog)
        sheets = data.get("sheets") or []
        sheet_summary = "\n".join(
            f"{item.get('name', '')}：{'已识别' if item.get('recognized') else '未识别'}，表头第 {item.get('header_row', 1)} 行"
            for item in sheets if isinstance(item, dict)
        )
        summary = QLabel(f"文件：{path}\n请核对工作表识别结果；如自动识别不正确，可启用手动字段映射。")
        summary.setWordWrap(True)
        form.addWidget(summary)
        sheet_list = QPlainTextEdit()
        sheet_list.setReadOnly(True)
        sheet_list.setMaximumHeight(120)
        sheet_list.setPlainText(sheet_summary or "未找到工作表")
        form.addWidget(sheet_list)
        manual = QCheckBox("使用手动字段映射（只导入选中的工作表）")
        form.addWidget(manual)
        sheet_combo = QComboBox()
        for sheet in sheets:
            if isinstance(sheet, dict):
                label = f"{sheet.get('name', '')} · {'自动识别' if sheet.get('recognized') else '需映射'}"
                sheet_combo.addItem(label, sheet)
        form.addWidget(sheet_combo)
        mapping_form = QFormLayout()
        header_row = QSpinBox()
        header_row.setRange(1, 9999)
        mapping_form.addRow("表头行", header_row)
        column_boxes: dict[str, QComboBox] = {}
        for key, label, required in self.MAPPING_FIELDS:
            box = QComboBox()
            box.setMinimumWidth(360)
            column_boxes[key] = box
            mapping_form.addRow(f"{label}{' *' if required else ''}", box)
        mapping_host = QWidget()
        mapping_host.setLayout(mapping_form)
        form.addWidget(mapping_host, 1)

        def update_mapping(index: int) -> None:
            sheet = sheet_combo.itemData(index) or {}
            header_row.setValue(int(sheet.get("header_row") or 1))
            columns = sheet.get("columns") or []
            for key, box in column_boxes.items():
                box.clear()
                box.addItem("未指定", None)
                for column in columns:
                    if isinstance(column, dict):
                        number = int(column.get("column") or 0)
                        text = str(column.get("header") or "").strip() or "（空列）"
                        box.addItem(f"{number}: {text}", number)
                detected = (sheet.get("mapping") or {}).get(key)
                if detected is not None:
                    box.setCurrentIndex(box.findData(int(detected) + 1))
            mapping_host.setEnabled(manual.isChecked())

        sheet_combo.currentIndexChanged.connect(update_mapping)
        manual.toggled.connect(mapping_host.setEnabled)
        update_mapping(0)
        policy = QComboBox()
        policy.addItem("发现空三字符时先进入待复核", "review")
        policy.addItem("空三字符按 WAR 填充", "fill_war")
        policy.addItem("只检查，不写入数据库", "check")
        form.addWidget(policy)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.import_button.setEnabled(True)
            self.status.setText("已取消导入")
            return
        selected_sheet = sheet_combo.currentData() or {}
        mapping = (self._mapping_payload(selected_sheet, header_row.value(), column_boxes)
                   if manual.isChecked() else None)
        self.import_policy = policy.currentData()
        self._import_path = path
        self._import_mapping = mapping
        self._run_import_check()

    def _new_import_task(self) -> str:
        return uuid.uuid4().hex

    def _start_import_progress(self, token: str) -> None:
        self._import_task = token
        self._progress_timer.start()

    def _stop_import_progress(self) -> None:
        self._progress_timer.stop()
        self._import_task = None

    def _poll_import_progress(self) -> None:
        token = self._import_task
        if not token:
            return
        self.client.get(f"/api/import-progress?id={token}", self._on_import_progress)

    def _on_import_progress(self, data: dict[str, Any] | None, error: str | None) -> None:
        if error or not data:
            return
        percent = data.get("percent")
        stage = data.get("stage") or "正在处理"
        if isinstance(percent, (int, float)):
            self.status.setText(f"{stage} · {percent:.0f}%")
        else:
            self.status.setText(str(stage))
        if data.get("status") in {"succeeded", "failed", "awaiting_confirmation"}:
            self._stop_import_progress()

    def _run_import_check(self) -> None:
        self.status.setText("正在预检导入内容...")
        token = self._new_import_task()
        self._start_import_progress(token)
        self.client.post("/api/import-excel", {
            "path": self._import_path,
            "blank_indication_policy": "check",
            "mapping": self._import_mapping,
        }, self._on_preflight, task_token=token)

    def _on_preflight(self, data: dict[str, Any] | None, error: str | None) -> None:
        self._stop_import_progress()
        if error or not data:
            self.import_button.setEnabled(True)
            QMessageBox.warning(self, PRODUCT_NAME, error or "导入预检失败")
            self.status.setText("预检失败")
            return
        blank = (data.get("blank_indication") or {}).get("count", 0)
        problems = data.get("error_count", 0) or data.get("error_total", 0) or 0
        parsed = data.get("parsed", data.get("parsed_total", 0))
        if self.import_policy == "check":
            self._on_import(data, None)
            return
        answer = QMessageBox.question(
            self, PRODUCT_NAME,
            f"预检完成：预计处理 {parsed} 条记录。\n"
            f"空三字符记录：{blank} 条；已发现质量问题：{problems} 条。\n\n"
            "是否继续写入数据库？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.import_button.setEnabled(True)
            self.status.setText("已取消导入")
            return
        self.status.setText("正在写入数据库，完成前请勿关闭软件...")
        token = self._new_import_task()
        self._start_import_progress(token)
        self.client.post("/api/import-excel", {
            "path": self._import_path,
            "blank_indication_policy": self.import_policy,
            "mapping": self._import_mapping,
        }, self._on_import, task_token=token)

    def _on_import(self, data: dict[str, Any] | None, error: str | None) -> None:
        self._stop_import_progress()
        self.import_button.setEnabled(True)
        self.import_folder_button.setEnabled(True)
        if error or not data:
            QMessageBox.warning(self, PRODUCT_NAME, error or "导入失败")
            self.status.setText("导入失败")
            return
        if getattr(self, "import_policy", None) == "check":
            blank = (data.get("blank_indication") or {}).get("count", 0)
            QMessageBox.information(self, PRODUCT_NAME, f"预检完成，未写入数据库。\n空三字符记录：{blank} 条")
            self.status.setText("预检完成，未写入数据库")
            return
        if data.get("requires_indication_decision"):
            self.status.setText("导入已暂停，等待三字符处理选择")
            QMessageBox.warning(
                self, PRODUCT_NAME,
                "检测到缺失三字符记录，导入未写入数据库；请选择“待复核”或“WAR”后重新导入。",
            )
            return
        inserted = data.get("inserted", data.get("rows", 0))
        problems = data.get("error_count", 0) or 0
        message = (f"新增 {inserted} 条，更新 {data.get('updated', 0)} 条，"
                   f"跳过 {data.get('skipped', 0)} 条。")
        if problems:
            QMessageBox.warning(self, PRODUCT_NAME,
                                f"{message}\n导入批次记录了 {problems} 条质量问题，请到质量与维护中核查。")
        else:
            QMessageBox.information(self, PRODUCT_NAME, f"导入完成：{message}")
        self.page = 1
        self.load_overview()
        self.load_findings()


class SimpleApiPage(QWidget):
    def __init__(self, client: NativeClient, title: str, endpoint: str, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.endpoint = endpoint
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        self.content = QLabel("正在加载...")
        self.content.setWordWrap(True)
        layout.addWidget(self.content)
        self.refresh = QPushButton("刷新")
        self.refresh.clicked.connect(self.load)
        layout.addWidget(self.refresh, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        self.load()

    def load(self) -> None:
        self.client.get(self.endpoint, self._on_data)

    def _on_data(self, data: dict[str, Any] | None, error: str | None) -> None:
        if error:
            self.content.setText(error)
            return
        if self.endpoint == "/api/states":
            items = (data or {}).get("items", [])
            self.content.setText(f"已记录管状态 {len(items):,} 条\n\n" + "\n".join(
                f"{row.get('outage', '')} / {row.get('unit_id', '')}号机 / {row.get('thimble_id', '')}号管：{row.get('state', 'normal')}"
                for row in items[:80]
            ))
        else:
            self.content.setText(str(data or {}))


class StateModel(QAbstractTableModel):
    validationError = Signal(str)
    headers = ["选择", "大修", "机组", "管号", "状态", "位移 mm", "备注", "来源", "更新时间", "操作"]
    fields = ["_checked", "outage", "unit_id", "thimble_id", "state", "offset_mm", "note", "source", "updated_at", "_actions"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[dict[str, Any]] = []
        self.editable = False
        self.drafts = {}
        self.selected = set()

    @staticmethod
    def key(row):
        return (row["outage"], row["unit_id"], row["thimble_id"])

    def displayed(self, row):
        return self.drafts.get(self.key(row), row)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.fields)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.rows):
            return None
        field = self.fields[index.column()]
        source = self.rows[index.row()]
        row = self.displayed(source)
        if role == Qt.ItemDataRole.CheckStateRole and field == "_checked":
            return Qt.CheckState.Checked if self.key(source) in self.selected else Qt.CheckState.Unchecked
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole, Qt.ItemDataRole.ToolTipRole):
            value = row.get(field, "")
            if field == "state" and role != Qt.ItemDataRole.EditRole:
                return row.get("event_label") or STATE_NAMES.get(value, value)
            if field == "_actions":
                return "保存     撤销" if self.editable else ""
            if field == "offset_mm" and value is None and role != Qt.ItemDataRole.EditRole:
                unsigned = row.get("unsigned_offset_mm")
                return f"{unsigned}（方向待核对）" if unsigned is not None else ""
            return "" if value is None else str(value)
        if role == Qt.ItemDataRole.TextAlignmentRole and field in {"unit_id", "thimble_id", "offset_mm"}:
            return int(Qt.AlignmentFlag.AlignCenter)
        return None

    def flags(self, index):
        flags = super().flags(index)
        if not index.isValid():
            return flags
        field = self.fields[index.column()]
        if field == "_checked":
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        if self.editable and field in {"state", "note", "offset_mm"}:
            row = self.displayed(self.rows[index.row()])
            if field != "offset_mm" or "shifted" in (row.get("events") or [row.get("state")]):
                flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid():
            return False
        source = self.rows[index.row()]
        key, field = self.key(source), self.fields[index.column()]
        if field == "_checked" and role == Qt.ItemDataRole.CheckStateRole:
            if value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value):
                self.selected.add(key)
            else:
                self.selected.discard(key)
            self.dataChanged.emit(index, index, [role])
            return True
        if not self.flags(index) & Qt.ItemFlag.ItemIsEditable or role != Qt.ItemDataRole.EditRole:
            return False
        draft = dict(self.displayed(source))
        draft.setdefault("expected_updated_at", source.get("updated_at"))
        if field == "state":
            if value not in STATE_NAMES:
                return False
            draft.update(state=value, events=[] if value == "normal" else [value], event_label=STATE_NAMES[value])
            draft["_state_changed"] = True
            if value != "shifted":
                draft["offset_mm"] = 0
                draft.pop("_offset_input", None)
            if value != "replaced":
                draft["replacement_stage"] = "unknown"
        elif field == "offset_mm":
            import math
            raw = str(value).strip()
            try:
                distance = float(raw) if raw else None
                if distance is not None and not math.isfinite(distance):
                    raise ValueError()
            except ValueError:
                self.validationError.emit("位移量必须是有限数字。")
                return False
            if source.get("unsigned_offset_mm") is not None and raw and raw[0] not in "+-":
                self.validationError.emit("原记录方向未确认，请填写带正负号的位移量。")
                return False
            draft.update(offset_mm=distance, _offset_input=raw)
        else:
            draft["note"] = str(value)
        self.drafts[key] = draft
        self.dataChanged.emit(self.index(index.row(), 0), self.index(index.row(), self.columnCount() - 1))
        return True

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        return self.headers[section] if orientation == Qt.Orientation.Horizontal else section + 1

    def replace(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()


class StateRowDelegate(QStyledItemDelegate):
    actionRequested = Signal(int, str)

    def createEditor(self, parent, option, index):
        if index.model().fields[index.column()] == "state":
            editor = QComboBox(parent)
            row = index.model().displayed(index.model().rows[index.row()])
            if len(row.get("events") or []) > 1:
                editor.addItem(row.get("event_label") or "保持复合处理", "__compound__")
            for code, name in STATE_NAMES.items():
                editor.addItem(name, code)
            return editor
        return QLineEdit(parent)

    def setEditorData(self, editor, index):
        if isinstance(editor, QComboBox):
            row = index.model().displayed(index.model().rows[index.row()])
            value = "__compound__" if len(row.get("events") or []) > 1 else row.get("state")
            editor.setCurrentIndex(max(0, editor.findData(value)))
        else:
            editor.setText(str(index.data(Qt.ItemDataRole.EditRole) or ""))

    def setModelData(self, editor, model, index):
        value = editor.currentData() if isinstance(editor, QComboBox) else editor.text()
        if value != "__compound__":
            model.setData(index, value)

    def editorEvent(self, event, model, option, index):
        if model.fields[index.column()] == "_actions":
            if not model.editable:
                return False
            if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                action = "save" if event.position().x() < option.rect.center().x() else "delete"
                self.actionRequested.emit(index.row(), action)
                return True
            if event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.actionRequested.emit(index.row(), "save")
                return True
        return super().editorEvent(event, model, option, index)


class StateImportModel(QAbstractTableModel):
    headers = ["导入", "大修", "机组", "管号", "维护事件", "换管顺序", "位移 (mm)", "方向", "备注", "来源/已有记录"]
    directions = ("待确认", "正向 (+)", "负向 (-)")

    def __init__(self, rows: list[dict[str, Any]], parent=None):
        super().__init__(parent)
        self.rows = [dict(row) for row in rows]
        self.checked = [not row.get("existing_status") for row in rows]
        self.directions_by_row = ["待确认"] * len(rows)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        return self.headers[section] if orientation == Qt.Orientation.Horizontal else section + 1

    @staticmethod
    def needs_direction(row):
        return row.get("offset_mm") is None and row.get("unsigned_offset_mm") is not None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        row = self.rows[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.CheckStateRole and column == 0:
            return Qt.CheckState.Checked if self.checked[index.row()] else Qt.CheckState.Unchecked
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole, Qt.ItemDataRole.ToolTipRole):
            return None
        status = {"same": "已有相同记录", "different": "已有不同记录", "revoked": "已撤销，不能导入"}.get(
            row.get("existing_status"), "")
        source = str(row.get("source") or "")
        if status:
            source += ("\n" if source else "") + status
            if row.get("existing_state"):
                source += "；已有状态：" + str(row["existing_state"])
            if row.get("existing_offset_mm") is not None:
                source += "；已有位移：" + str(row["existing_offset_mm"]) + " mm"
            if row.get("existing_note"):
                source += "；已有备注：" + str(row["existing_note"])
        names = {"plugged": "堵管", "shifted": "移位", "replaced": "换管"}
        event_names = "、".join(names.get(event, str(event)) for event in row.get("events") or [])
        stages = {"unknown": "待核对", "before_replacement": "其他处理在换管前",
                  "after_replacement": "其他处理在换管后"}
        value = (
            status, row.get("outage"), row.get("unit_id"), row.get("thimble_id"),
            row.get("event_label") or event_names or row.get("state"),
            stages.get(row.get("replacement_stage"), ""),
            row.get("offset_mm") if row.get("offset_mm") is not None else row.get("unsigned_offset_mm"),
            self.directions_by_row[index.row()] if self.needs_direction(row) else "",
            row.get("note"), source,
        )[column]
        return "" if value is None else str(value)

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = super().flags(index)
        row = self.rows[index.row()]
        if index.column() == 0 and row.get("existing_status") != "revoked":
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        if index.column() == 8 or (index.column() == 7 and self.needs_direction(row)):
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return False
        row = index.row()
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 0 and self.rows[row].get("existing_status") != "revoked":
            self.checked[row] = value == Qt.CheckState.Checked or value == Qt.CheckState.Checked.value
        elif role == Qt.ItemDataRole.EditRole and index.column() == 7 and self.needs_direction(self.rows[row]) and value in self.directions:
            self.directions_by_row[row] = value
        elif role == Qt.ItemDataRole.EditRole and index.column() == 8:
            self.rows[row]["note"] = str(value)
        else:
            return False
        self.dataChanged.emit(index, index, [role])
        return True

    def selected_rows(self):
        selected = []
        keys = set()
        for index, row in enumerate(self.rows):
            if not self.checked[index]:
                continue
            key = (str(row.get("outage") or "").strip().upper(),
                   str(row.get("unit_id") or ""), str(row.get("thimble_id") or ""))
            if key in keys:
                raise ValueError(f"{key[0]} 机组{key[1]} 管{key[2]}存在重复记录，请只选择一条。")
            keys.add(key)
            result = {**row, "overwrite_existing": row.get("existing_status") in {"same", "different"}}
            if self.needs_direction(row):
                direction = self.directions_by_row[index]
                if direction == "待确认":
                    raise ValueError(f"{row.get('outage', '')} 管{row.get('thimble_id', '')}的移位方向尚未确认。")
                result["offset_mm"] = (1 if direction == "正向 (+)" else -1) * float(row["unsigned_offset_mm"])
                result["unsigned_offset_mm"] = None
            selected.append(result)
        return selected

    def select_new_rows(self, checked):
        for index, row in enumerate(self.rows):
            if not row.get("existing_status"):
                self.checked[index] = checked
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, 0),
                                  [Qt.ItemDataRole.CheckStateRole])

    def set_selected_direction(self, direction):
        if direction not in self.directions:
            return
        for index, row in enumerate(self.rows):
            if self.checked[index] and self.needs_direction(row):
                self.directions_by_row[index] = direction
        if self.rows:
            self.dataChanged.emit(self.index(0, 7), self.index(len(self.rows) - 1, 7),
                                  [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole])


class StateDirectionDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        editor = QComboBox(parent)
        editor.addItems(StateImportModel.directions)
        return editor

    def setEditorData(self, editor, index):
        editor.setCurrentText(index.data(Qt.ItemDataRole.EditRole))

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)


class StateNoteEdit(QPlainTextEdit):
    def text(self):
        return self.toPlainText()

    def setText(self, value):
        self.setPlainText(value)


class NativeStatePage(QWidget):
    def __init__(self, client: NativeClient, user: dict[str, Any] | None = None, parent=None):
        super().__init__(parent)
        self.client = client
        self.permissions = None if user is None else set(user.get("permissions", []))
        self.model = StateModel(self)
        self.model.editable = self.permissions is None or "state.write" in self.permissions
        self.model.validationError.connect(lambda text: self.message.setText(text))
        self.record_page = 1
        self.record_size = 50
        self._inline_inflight = set()
        self.current: dict[str, Any] | None = None
        self._scope_items = []
        self.pending_rows = []
        self._state_filter = ""
        self._load_request = 0
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        body.setObjectName("workspaceBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(18, 16, 18, 16)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        self.scope_bar = ScopeBar(client, stacked=True)
        self.add_scope = button("新增大修", "database", self._add_scope)
        self.scope_bar.layout().insertWidget(self.scope_bar.layout().count() - 1, self.add_scope)
        scope_band = QWidget()
        scope_band.setObjectName("filterBand")
        scope_layout = QVBoxLayout(scope_band)
        scope_layout.setContentsMargins(12, 10, 12, 10)
        self.scope_bar.setObjectName("stateScope")
        scope_layout.addWidget(self.scope_bar)
        layout.addWidget(scope_band)
        self.scope_bar.changed.connect(self._filter_scope)
        summary_heading = QHBoxLayout()
        summary_heading.addWidget(QLabel("状态概览  ·  本次维护 50 根"), 1)
        self.review_pending = button("待核对 0", "clipboard-check", self._review_pending)
        summary_heading.addWidget(self.review_pending)
        scope_layout.addLayout(summary_heading)
        summary = QHBoxLayout()
        self.summary_buttons = {}
        for code, name, glyph in (("maintained", "已维护", "clipboard-check"), ("unmaintained", "未维护", "circle-dashed"),
                                  ("normal", "正常", "check"), ("plugged", "堵管", "ban"),
                                  ("shifted", "移位", "move-horizontal"), ("replaced", "换管", "arrow-right-left")):
            control = button(name + "  —", glyph)
            control.setProperty("stateSummary", code)
            control.setMinimumHeight(48)
            control.setCheckable(True)
            control.clicked.connect(lambda checked, key=code: self._show_state_summary(key))
            self.summary_buttons[code] = control
            summary.addWidget(control, 1)
        scope_layout.addLayout(summary)
        self.filter_text = QLineEdit()
        self.filter_text.setPlaceholderText("管号或备注")
        self.filter_text.textChanged.connect(self._record_scope_changed)
        self.message = QLabel("选择一条管状态记录进行维护")
        self.message.setObjectName("muted")
        layout.addWidget(self.message)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                   | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.row_delegate = StateRowDelegate(self.table)
        self.row_delegate.actionRequested.connect(self._inline_state_action)
        self.table.setItemDelegate(self.row_delegate)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(210)
        self.table.horizontalHeader().setStretchLastSection(True)
        for field, width in (("_checked", 42), ("outage", 90), ("unit_id", 64), ("thimble_id", 64),
                             ("state", 150), ("offset_mm", 130), ("note", 260), ("source", 200),
                             ("updated_at", 200), ("_actions", 156)):
            self.table.setColumnWidth(self.model.fields.index(field), width)
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.clicked.connect(self._select)
        self.state_split = QSplitter()
        map_host = QWidget()
        map_host.setObjectName("workspacePanel")
        map_layout = QVBoxLayout(map_host)
        map_layout.setContentsMargins(16, 16, 16, 16)
        map_layout.setSpacing(12)
        map_title = QHBoxLayout()
        map_title.addWidget(QLabel("管板"), 1)
        map_layout.addLayout(map_title)
        grid_modes = QHBoxLayout()
        grid_modes.addWidget(QLabel("管位显示"))
        self.grid_mode = QTabBar()
        self.grid_mode.addTab("本次记录")
        self.grid_mode.addTab("截至本次有效")
        self.grid_mode.setCurrentIndex(1)
        self.grid_mode.currentChanged.connect(lambda _: self._update_grid())
        grid_modes.addWidget(self.grid_mode)
        grid_modes.addStretch()
        map_layout.addLayout(grid_modes)
        self.plate = TubeStateGrid()
        self.plate.tubeClicked.connect(self._select_grid_tube)
        self.plate.setMaximumHeight(390)
        map_layout.addWidget(self.plate)
        legend = QLabel("  ".join(
            f'<span style="color:{STATE_PALETTE[code][1]}">&#9633;</span> {name}'
            for code, name in (("missing", "未维护"), *STATE_NAMES.items()))
            + '  <span style="color:#875078">&#9635;</span> 复合处理')
        legend.setObjectName("muted")
        map_layout.addWidget(legend)
        self.history = QPlainTextEdit()
        self.history.setReadOnly(True)
        self.history.setMaximumHeight(150)
        history_toggle = button("单管历次维护", "history", lambda: self.history.setVisible(self.history.isHidden()))
        map_layout.addWidget(history_toggle)
        map_layout.addWidget(self.history)
        self.history.hide()
        map_layout.addStretch()
        self.state_split.addWidget(map_host)
        self.editor_host = QWidget()
        self.editor_host.setObjectName("workspacePanel")
        editor_layout = QVBoxLayout(self.editor_host)
        editor_layout.setContentsMargins(16, 16, 16, 16)
        editor_layout.setSpacing(12)
        editor_layout.addWidget(QLabel("管状态处理"))
        self.batch_actions_host = QWidget()
        self.batch_actions_host.setObjectName("stateActionBand")
        batch_actions = ToolFlowLayout(self.batch_actions_host)
        batch_actions.setContentsMargins(10, 8, 10, 8)
        self.batch_mode = QCheckBox("批量选择")
        self.batch_mode.toggled.connect(self._batch_mode_changed)
        self.batch_count = QLabel("已选 0 根")
        self.batch_all = button("全选50根", "check-check", lambda: self._select_batch(True))
        self.batch_clear = button("清除", "x", lambda: self._select_batch(False))
        self.batch_apply = button("处理所选", "check", self._apply_selected_states)
        for control in (self.batch_mode, self.batch_count, self.batch_clear, self.batch_apply, self.batch_all):
            batch_actions.addWidget(control)
        editor_layout.addWidget(self.batch_actions_host)
        self._batch_busy = False
        self._batch_offset_touched = False
        self.batch_editor = self._build_batch_editor()
        editor_layout.addWidget(self.batch_editor)
        self.file_actions_host = QWidget()
        file_actions = QVBoxLayout(self.file_actions_host)
        file_actions.setContentsMargins(8, 8, 8, 8)
        file_actions.addWidget(QLabel("维护表文件"))
        self.file_actions_host.setObjectName("stateActionBand")
        editor_layout.addWidget(self.file_actions_host)
        self.bulk_actions_host = QWidget()
        bulk_layout = QVBoxLayout(self.bulk_actions_host)
        bulk_layout.setContentsMargins(10, 10, 10, 10)
        bulk_layout.addWidget(QLabel("批量维护"))
        bulk_actions = ToolFlowLayout()
        bulk_layout.addLayout(bulk_actions)
        self.bulk_actions_host.setObjectName("stateActionBand")
        editor_layout.addWidget(self.bulk_actions_host)
        self.single_editor = QWidget()
        single_layout = QVBoxLayout(self.single_editor)
        single_layout.setContentsMargins(0, 0, 0, 0)
        single_layout.setSpacing(12)
        editor_layout.addWidget(self.single_editor)
        self.editor_title = QLabel("管号与处理")
        single_layout.addWidget(self.editor_title)
        self.editor_tube = QSpinBox()
        self.editor_tube.setRange(0, 50)
        self.editor_tube.setSpecialValueText(" ")
        self.editor_tube.valueChanged.connect(self._select_grid_tube)
        self.state_split.addWidget(self.editor_host)
        self.state_split.setSizes([780, 600])
        layout.addWidget(self.state_split, 3)
        self.all_rows = []
        self._state_scope = {}
        self._scope_request = 0
        form = QFormLayout()
        self.editor_form = form
        self.state = QComboBox()
        self.state.addItem("正常", "normal")
        self.state.addItem("堵管", "plugged")
        self.state.addItem("移位", "shifted")
        self.state.addItem("换管", "replaced")
        self.state.addItem("复合处理（多选）", "composite")
        self.state.currentIndexChanged.connect(self._simple_state_changed)
        self.event_checks = {}
        self.event_host = QWidget()
        event_row = QHBoxLayout(self.event_host)
        event_row.setContentsMargins(0, 0, 0, 0)
        for code, name in (("plugged", "堵管"), ("shifted", "移位"), ("replaced", "换管")):
            control = QCheckBox(name)
            control.toggled.connect(self._events_changed)
            self.event_checks[code] = control
            event_row.addWidget(control)
        self.replacement_stage = QComboBox()
        for name, code in (("待核对", "unknown"), ("其他处理在换管前", "before_replacement"),
                           ("其他处理在换管后", "after_replacement")):
            self.replacement_stage.addItem(name, code)
        self.offset = QLineEdit()
        self.offset.setPlaceholderText("位移量（mm）")
        self.note = StateNoteEdit()
        self.note.setPlaceholderText("状态备注")
        self.note.setMinimumHeight(80)
        self.note.setMaximumHeight(110)
        self.save = QPushButton("保存状态")
        self.save.clicked.connect(self._save)
        self.advanced = QPushButton("新建/复合维护")
        self.advanced.clicked.connect(self._edit_advanced)
        self.new_state = QPushButton("新建维护")
        self.new_state.clicked.connect(lambda: self._edit_advanced(new=True))
        if self.permissions is not None and "state.write" not in self.permissions:
            self.save.setEnabled(False)
            self.save.setToolTip("当前账户没有管状态维护权限")
            self.advanced.setEnabled(False)
            self.new_state.setEnabled(False)
        self.refresh = QPushButton("刷新")
        self.refresh.clicked.connect(self.load)
        tube_fields = QGridLayout()
        tube_fields.addWidget(QLabel("通道编号"), 0, 0)
        tube_fields.addWidget(QLabel("管状态"), 0, 1)
        tube_fields.addWidget(self.editor_tube, 1, 0)
        tube_fields.addWidget(self.state, 1, 1)
        tube_fields.setColumnStretch(0, 1)
        tube_fields.setColumnStretch(1, 1)
        single_layout.addLayout(tube_fields)
        form.addRow("本次同时发生", self.event_host)
        form.addRow("换管顺序", self.replacement_stage)
        form.addRow("移位距离（mm）", self.offset)
        self.effective_summary = QLabel("请选择管号")
        self.effective_summary.setWordWrap(True)
        self.effective_summary.setObjectName("stateEffectiveSummary")
        single_layout.addLayout(form)
        single_layout.addWidget(self.effective_summary)
        single_layout.addWidget(QLabel("维护依据"))
        note_actions = QHBoxLayout()
        self.recognize_note = button("识别维护说明", "search", self._recognize_note)
        self.generate_note = button("生成备注", "files", self._generate_note)
        note_actions.addWidget(QLabel("备注"), 1)
        note_actions.addWidget(self.recognize_note)
        note_actions.addWidget(self.generate_note)
        single_layout.addLayout(note_actions)
        single_layout.addWidget(self.note)
        self.editor_source = QLabel()
        self.editor_source.setWordWrap(True)
        self.editor_source.setObjectName("muted")
        single_layout.addWidget(self.editor_source)
        single_layout.addStretch()
        editor_actions = ToolFlowLayout()
        for control in (self.advanced, self.new_state, self.refresh, self.save):
            editor_actions.addWidget(control)
        self.save.setProperty("primary", True)
        single_layout.addLayout(editor_actions)
        table_heading = QHBoxLayout()
        table_heading.addWidget(QLabel("已维护记录"), 1)
        self.record_selection = QLabel("筛选 0 条 · 已选 0 条")
        table_heading.addWidget(self.record_selection)
        layout.addLayout(table_heading)
        self.record_scope = ScopeBar(client, self)
        self.record_scope.hide()
        record_filters = ToolFlowLayout()
        for control, name in ((self.record_scope.site, "筛选基地"), (self.record_scope.unit, "筛选机组"),
                              (self.record_scope.outage, "筛选大修")):
            control.setAccessibleName(name)
            record_filters.addWidget(control)
        self.record_type = QComboBox()
        for text, code in (("全部状态", ""), *[(name, code) for code, name in STATE_NAMES.items()],
                           ("复合处理", "composite")):
            self.record_type.addItem(text, code)
        self.record_type.setAccessibleName("筛选状态")
        record_filters.addWidget(self.record_type)
        self.record_latest = button("选最新", "history", self._latest_record_scope)
        self.record_clear = button("清除", "rotate-ccw", self._clear_record_filters)
        for control in (self.record_latest, self.record_clear, self.filter_text):
            record_filters.addWidget(control)
        layout.addLayout(record_filters)
        self.record_categories = QTabBar()
        self.record_categories.setExpanding(False)
        for index in range(self.record_type.count()):
            self.record_categories.addTab("全部" if index == 0 else self.record_type.itemText(index))
        layout.addWidget(self.record_categories)
        self.record_scope.changed.connect(self._record_scope_changed)
        self.record_type.currentIndexChanged.connect(self._record_type_changed)
        self.record_categories.currentChanged.connect(self.record_type.setCurrentIndex)
        self.model.dataChanged.connect(self._record_selection_changed)
        layout.addWidget(self.table, 2)
        pager = QHBoxLayout()
        pager.addWidget(QLabel("每页"))
        self.record_size_box = QComboBox()
        for size in (50, 100):
            self.record_size_box.addItem(str(size), size)
        self.record_size_box.currentIndexChanged.connect(self._record_size_changed)
        pager.addWidget(self.record_size_box)
        pager.addStretch()
        self.record_previous = button("上一页", "chevron-left", lambda: self._change_record_page(-1))
        self.record_next = button("下一页", "chevron-right", lambda: self._change_record_page(1))
        self.record_page_label = QLabel()
        self.record_jump = QSpinBox()
        self.record_jump.setMinimumWidth(68)
        self.record_jump.editingFinished.connect(self._jump_record_page)
        for control in (self.record_previous, self.record_page_label, self.record_next,
                        QLabel("跳至"), self.record_jump, QLabel("页")):
            pager.addWidget(control)
        layout.addLayout(pager)
        self.bulk_scope = QLabel("批量操作以当前选中记录的大修/机组为范围")
        self.bulk_scope.setObjectName("muted")
        self.bulk_normal = button("补齐正常", "check-check")
        self.bulk_normal.clicked.connect(self._bulk_normal)
        self.import_button = button("选择文件", "upload")
        self.import_button.clicked.connect(self._import_state_file)
        self.export_format = QComboBox()
        self.export_format.addItem("Excel 明细及历次汇总", "xlsx")
        self.export_format.addItem("Excel 历次统计", "summary")
        self.export_format.addItem("Word 维护统计", "docx")
        self.export_button = button("导出", "file-down")
        self.export_button.setFixedWidth(76)
        self.export_button.clicked.connect(self._export_states)
        self.delete_button = QPushButton("删除选中状态")
        self.delete_button.clicked.connect(self._delete_selected)
        if self.permissions is not None:
            writable = "state.write" in self.permissions
            exportable = "export.create" in self.permissions
            self.bulk_normal.setEnabled(writable)
            self.import_button.setEnabled(writable)
            self.delete_button.setEnabled(writable)
            self.export_button.setEnabled(exportable)
            if not writable:
                self.bulk_normal.setToolTip("当前账户没有管状态维护权限")
                self.import_button.setToolTip("当前账户没有管状态维护权限")
                self.delete_button.setToolTip("当前账户没有管状态维护权限")
            if not exportable:
                self.export_button.setToolTip("当前账户没有导出权限")
        writable = self.permissions is None or "state.write" in self.permissions
        for control in (self.add_scope, self.batch_apply, self.recognize_note, self.generate_note):
            control.setEnabled(writable)
        file_row = QGridLayout()
        file_row.addWidget(QLabel("导入维护表"), 0, 0)
        file_row.addWidget(QLabel("导出维护表"), 0, 1)
        file_row.addWidget(self.import_button, 1, 0)
        file_row.addWidget(self.export_format, 1, 1)
        file_row.addWidget(self.export_button, 1, 2)
        file_row.setColumnStretch(1, 1)
        self.import_button.setFixedWidth(148)
        file_actions.addLayout(file_row)
        bulk_actions.addWidget(self.bulk_normal)
        bulk_actions.addWidget(QLabel("移位"))
        self.default_direction = QComboBox()
        for text, value in (("默认正向（+）", "1"), ("默认负向（-）", "-1"), ("方向待核对", "pending")):
            self.default_direction.addItem(text, value)
        self.default_direction.setToolTip("明确正负号优先；已确认的历史记录保持原值")
        self.default_direction.activated.connect(self._save_direction)
        bulk_actions.addWidget(self.default_direction)
        self.use_default_offset = button("套用默认方向", "move-horizontal", self._use_default_offset)
        self.use_default_offset.hide()
        form.addRow("", self.use_default_offset)
        table_actions = ToolFlowLayout()
        table_actions.addWidget(self.bulk_scope)
        table_actions.addWidget(self.delete_button)
        layout.addLayout(table_actions)
        self.state_split.setStretchFactor(0, 48)
        self.state_split.setStretchFactor(1, 52)
        self.state_split.setSizes([660, 740])
        self._clear_editor()
        self._batch_selection_changed()
        client.get("/api/settings/state-direction", self._direction_loaded)
        self.load()

    def _clear_editor(self):
        self.current = None
        self._recognized_unsigned = None
        self.editor_title.setText("管号与处理")
        self.editor_tube.blockSignals(True)
        self.editor_tube.setValue(0)
        self.editor_tube.blockSignals(False)
        self.state.setCurrentIndex(0)
        for control in self.event_checks.values():
            control.blockSignals(True)
            control.setChecked(False)
            control.blockSignals(False)
        self.offset.clear()
        self.note.clear()
        self.replacement_stage.setCurrentIndex(0)
        self.editor_source.clear()
        self.history.clear()
        self.effective_summary.setText("请选择管号")
        self.save.setEnabled(False)
        self._update_event_fields()

    def _direction_loaded(self, data, error):
        self.default_direction.setEnabled(bool(not error and data and data.get("writable")))
        if data and not error:
            self.default_direction.setCurrentIndex(max(0, self.default_direction.findData(data.get("shift_direction"))))

    def _save_direction(self):
        self.default_direction.setEnabled(False)
        self.client.post("/api/settings/state-direction",
                         {"shift_direction": self.default_direction.currentData()}, self._direction_saved)

    def _direction_saved(self, data, error):
        if error:
            self.message.setText(error)
            self.client.get("/api/settings/state-direction", self._direction_loaded)
        else:
            self._direction_loaded(data, error)

    def _use_default_offset(self):
        unsigned = getattr(self, "_recognized_unsigned", None)
        if unsigned is None:
            unsigned = (self.current or {}).get("unsigned_offset_mm")
        if unsigned is None:
            return
        direction = self.default_direction.currentData()
        if direction == "pending":
            self.message.setText("请先确认正向或负向，再套用已识别距离")
            self.default_direction.setFocus()
            return
        self.offset.setText(f"{float(unsigned) * int(direction):+g}")

    def load(self):
        self.message.setText("正在读取状态记录...")
        self._load_request += 1
        number = self._load_request
        self.client.get("/api/states", lambda data, error: self._loaded(data, error)
                        if number == self._load_request else None)

    def _loaded(self, data, error):
        editing = self.current
        dirty = self._editor_dirty()
        if not dirty:
            self.current = None
        self.bulk_scope.setText("批量操作以当前选中记录的大修/机组为范围")
        if error or not data:
            self.message.setText(error or "状态读取失败")
            self.model.replace([])
            return
        rows = data.get("items") or []
        for row in rows:
            events = row.get("events") or []
            row["needs_review"] = bool(
                ("shifted" in events and row.get("offset_mm") is None)
                or ("replaced" in events and len(events) > 1
                    and (row.get("replacement_stage") or "unknown") == "unknown"))
        self.all_rows = rows
        self.pending_rows = data.get("pending") or []
        extra = list(data.get("scopes") or [])
        extra.extend({"site": re.match(r"^[A-Z]+", row["outage"])[0],
                      "unit_id": row["unit_id"], "outage": row["outage"]} for row in rows)
        self.scope_bar.set_extra_combinations(extra)
        self.record_scope.extra_combinations = list(extra)
        self.record_scope._loaded({"combinations": self.scope_bar.combinations}, None)
        self.review_pending.setText(f"待核对 {len(self._review_items())}")
        self.review_pending.setEnabled(bool(self.pending_rows) or any(row.get("needs_review") for row in rows))
        self._show_filtered()
        self._request_scope()
        if dirty:
            self.message.setText("数据已更新，当前未保存的编辑已保留；保存时将核验原记录版本")
        elif editing:
            latest = next((row for row in rows if all(row.get(key) == editing.get(key)
                          for key in ("outage", "unit_id", "thimble_id"))), None)
            if latest:
                self.current = latest
                self._populate_editor()
        if not dirty:
            self.message.setText(f"已加载 {len(rows):,} 条状态记录；保存操作会写入审计历史")
        saved_key = getattr(self, "_select_after_load", None)
        if saved_key:
            latest = next((row for row in rows if tuple(row.get(key) for key in
                          ("outage", "unit_id", "thimble_id")) == saved_key), None)
            if latest:
                self.current = latest
                self._populate_editor()
                self._select_after_load = None
        if not self.current:
            self._clear_editor()

    def set_workspace_scope(self, scope):
        normalized = {key: str(scope.get(key) or "") for key in ("site", "unit", "outage")}
        if normalized != self._state_scope and self._editor_dirty():
            self.message.setText("其他工作区范围已变化，当前维护草稿已保留；保存或放弃编辑后再切换范围")
            return
        self.scope_bar.set_scope(normalized)
        if normalized != self._state_scope:
            self._filter_scope(normalized)
        if scope.get("thimble"):
            self.plate.selected = {int(scope["thimble"])}
            self.plate.update()
            self._select_grid_tube(int(scope["thimble"]))

    def _filter_scope(self, scope):
        if scope != self._state_scope:
            if not self._allow_editor_change():
                self.scope_bar.set_scope(self._state_scope)
                return
            self._clear_editor()
            self.plate.selected.clear()
            self._batch_offset_touched = False
            self._scope_items = []
        self._state_scope = scope
        self._show_filtered()
        self._batch_selection_changed()
        self._request_scope()

    def _request_scope(self):
        scope = self._state_scope
        self._scope_request += 1
        number = self._scope_request
        if scope.get("outage") and scope.get("unit"):
            from urllib.parse import urlencode
            self.client.get("/api/states/scope?" + urlencode({
                "outage": scope["outage"], "unit_id": scope["unit"], "details": "maintenance"}),
                lambda data, error: self._scope_loaded(data)
                if number == self._scope_request and not error else None)

    def _scope_loaded(self, data):
        self._scope_items = (data or {}).get("items") or []
        self._update_grid()
        self._update_effective_summary()
        self._batch_selection_changed()

    def _scope_rows(self):
        scope = self._state_scope
        return [row for row in self.all_rows
                if (not scope.get("site") or canonical_site(re.match(r"^[A-Z]+", row["outage"])[0]) == scope["site"])
                and (not scope.get("unit") or str(row.get("unit_id")) == str(scope["unit"]))
                and (not scope.get("outage") or row.get("outage") == scope["outage"])]

    def _set_state_filter(self, code):
        code = "" if self._state_filter == code else code
        index = self.record_type.findData(code)
        if index >= 0:
            self.record_type.setCurrentIndex(index)
        else:
            self._state_filter = code
            self._reset_record_page()

    def _record_scope_changed(self, *_):
        self.model.selected.clear()
        self._reset_record_page()

    def _record_type_changed(self, index):
        self._state_filter = self.record_type.currentData() or ""
        self.record_categories.setCurrentIndex(index)
        self._record_scope_changed()

    def _clear_record_filters(self):
        self.record_scope.set_scope({})
        self.record_type.setCurrentIndex(0)
        self.filter_text.blockSignals(True)
        self.filter_text.clear()
        self.filter_text.blockSignals(False)
        self._record_scope_changed()

    def _latest_record_scope(self):
        scope = self.record_scope.values()
        candidates = [row for row in self.record_scope.combinations
                      if (not scope.get("site") or canonical_site(row["site"]) == scope["site"])
                      and (not scope.get("unit") or str(row["unit_id"]) == scope["unit"])]
        if not candidates:
            return
        latest = max(candidates, key=lambda row: (
            int(re.search(r"(\d{2})$", row["outage"])[1]), row["outage"], int(row["unit_id"])))
        selected = {"site": canonical_site(latest["site"]), "unit": str(latest["unit_id"]),
                    "outage": latest["outage"]}
        if not self._allow_editor_change():
            return
        self._clear_editor()
        self.scope_bar.set_scope(selected)
        self.scope_bar.changed.emit(selected)
        self.record_scope.set_scope(selected)
        self._record_scope_changed()

    def _record_selection_changed(self, *_):
        self.record_selection.setText(
            f"筛选 {getattr(self, '_record_total', 0)} 条 · 已选 {len(self.model.selected)} 条"
            + (f" · 未保存 {len(self.model.drafts)} 条" if self.model.drafts else ""))

    def _reset_record_page(self, *_):
        self.record_page = 1
        self._show_filtered()

    def _show_state_summary(self, code):
        self.summary_buttons[code].setChecked(code == self._state_filter)
        scope = dict(self._state_scope)
        if not scope.get("unit") or not scope.get("outage"):
            self.message.setText("请选择具体机组和大修")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{scope['outage']} · {self.summary_buttons[code].text().split()[0]}明细")
        dialog.resize(960, 600)
        layout = QVBoxLayout(dialog)
        heading = QLabel()
        layout.addWidget(heading)
        table = QTableWidget(0, 6)
        table.setHorizontalHeaderLabels(["管号", "本次状态", "移位 (mm)", "原始备注", "来源", ""])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setWordWrap(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.setColumnWidth(3, 270)
        layout.addWidget(table, 1)
        status = QLabel()
        status.setObjectName("muted")
        layout.addWidget(status)
        actions = QHBoxLayout()
        refresh = button("刷新明细", "refresh-cw")
        actions.addWidget(refresh)
        actions.addStretch()
        actions.addWidget(button("关闭", "x", dialog.close))
        layout.addLayout(actions)
        request_number = [0]

        def choose(tube):
            if self._state_scope != scope:
                self.message.setText("维护范围已变化，请重新打开当前范围明细")
                dialog.close()
                return
            self._select_grid_tube(tube)
            dialog.accept()

        def loaded(number, data, error):
            if number != request_number[0] or not dialog.isVisible():
                return
            refresh.setEnabled(True)
            if error:
                status.setText(f"维护明细读取失败：{error}")
                return
            current = {int(row["thimble_id"]): row for row in (data or {}).get("items", [])
                       if row.get("outage") == scope["outage"] and str(row.get("unit_id")) == scope["unit"]}
            rows = [(tube, current.get(tube)) for tube in range(1, 51)]
            rows = [(tube, row) for tube, row in rows if (
                bool(row) if code == "maintained" else not row if code == "unmaintained" else
                bool(row and code in (row.get("events") or [row.get("state")])))]
            heading.setText(f"{scope['outage']} · {self.summary_buttons[code].text().split()[0]} · {len(rows)} 根")
            table.setRowCount(len(rows))
            for index, (tube, row) in enumerate(rows):
                row = row or {}
                events = row.get("events") or [row.get("state")]
                distance = row.get("offset_mm")
                offset = (f"{float(distance):+g}" if distance is not None else
                          f"{row['unsigned_offset_mm']}（方向待核对）" if row.get("unsigned_offset_mm") is not None else
                          "距离待核对") if "shifted" in events else "/"
                values = (f"#{tube}", row.get("event_label") or STATE_NAMES.get(row.get("state"), "未维护"),
                          offset, row.get("note") or "/", row.get("source") or "/")
                for column, value in enumerate(values):
                    cell = QTableWidgetItem(str(value))
                    cell.setToolTip(str(value))
                    table.setItem(index, column, cell)
                table.setCellWidget(index, 5, button("查看管号", "search", lambda _=False, t=tube: choose(t)))
            status.setText("本次维护记录；历史有效状态见管板。")

        def reload():
            request_number[0] += 1
            number = request_number[0]
            refresh.setEnabled(False)
            status.setText("正在重新读取维护明细...")
            self.client.get("/api/states", lambda data, error: loaded(number, data, error))

        refresh.clicked.connect(reload)
        dialog.finished.connect(lambda _: request_number.__setitem__(0, request_number[0] + 1))
        dialog.open()
        self.summary_dialog = dialog
        reload()

    def _update_grid(self):
        scope = self._state_scope
        rows = self._scope_rows() if scope.get("unit") and scope.get("outage") else []
        if self.grid_mode.currentIndex() == 1:
            rows = [{**row, "recorded": bool(row.get("last_maintenance")),
                     "events": ([code for code, active in (("plugged", row.get("plugged")),
                                  ("shifted", row.get("shifted")),
                                  ("replaced", "replaced" in (row.get("current_events") or []))) if active]
                                or ([row["state"]] if row.get("state") in ("plugged", "shifted", "replaced") else [])),
                     "offset_mm": row.get("cumulative_offset_mm")}
                    for row in self._scope_items] if rows or self._scope_items else []
        selected = set(self.plate.selected)
        self.plate.set_data(rows, int(scope.get("unit") or 1), mode="state")
        self.plate.selected = selected
        self.plate.update()

    def _show_filtered(self):
        scope = getattr(self, "_state_scope", {})
        text = self.filter_text.text().strip().casefold()
        scoped = self._scope_rows()
        counts = {"maintained": len(scoped), "unmaintained": max(0, 50 - len(scoped))}
        for code in ("normal", "plugged", "shifted", "replaced"):
            counts[code] = sum(code in (row.get("events") or [row.get("state")]) for row in scoped)
        for code, control in self.summary_buttons.items():
            name = {"maintained": "已维护", "unmaintained": "未维护", **STATE_NAMES}[code]
            control.setText(f"{name}  {counts[code] if scope.get('unit') and scope.get('outage') else '—'}")
        record_scope = self.record_scope.values()
        rows = [row for row in self.all_rows
                if (not record_scope.get("site") or canonical_site(
                    re.match(r"^[A-Z]+", row["outage"])[0]) == record_scope["site"])
                and (not record_scope.get("unit") or str(row.get("unit_id")) == record_scope["unit"])
                and (not record_scope.get("outage") or row["outage"] == record_scope["outage"])
                and (not text or any(text in str(value or "").casefold() for value in (
                    row["outage"], f"#{row['thimble_id']}", row.get("position"), row.get("note"),
                    row.get("source"), row.get("event_label"))))]
        if self._state_filter == "unmaintained":
            rows = []
        elif self._state_filter == "composite":
            rows = [row for row in rows if len(row.get("events") or []) > 1]
        elif self._state_filter not in ("", "maintained"):
            rows = [row for row in rows if self._state_filter in (row.get("events") or [row.get("state")])]
        self._record_total = len(rows)
        self._record_selection_changed()
        pages = max(1, (len(rows) + self.record_size - 1) // self.record_size)
        self.record_page = min(self.record_page, pages)
        offset = (self.record_page - 1) * self.record_size
        self.model.replace(rows[offset:offset + self.record_size])
        self.record_page_label.setText(f"{self.record_page} / {pages} · {len(rows)} 条")
        self.record_previous.setEnabled(self.record_page > 1)
        self.record_next.setEnabled(self.record_page < pages)
        self.record_jump.setRange(1, pages)
        self.record_jump.setValue(self.record_page)
        if self.model.editable:
            for index, row in enumerate(self.model.rows):
                host = QWidget()
                actions = QHBoxLayout(host)
                actions.setContentsMargins(2, 2, 2, 2)
                actions.setSpacing(4)
                for text, action in (("保存", "save"), ("撤销", "delete")):
                    control = QPushButton(text)
                    control.setAccessibleName(f"{text} {row['outage']} 通道{row['thimble_id']} 的维护记录")
                    control.clicked.connect(lambda _=False, r=dict(row), a=action: self._inline_state_action(r, a))
                    actions.addWidget(control)
                self.table.setIndexWidget(self.model.index(index, self.model.fields.index("_actions")), host)
        self._update_grid()

    def _record_size_changed(self, *_):
        self.model.selected.clear()
        self.record_size = self.record_size_box.currentData()
        self._reset_record_page()

    def _change_record_page(self, delta):
        self.model.selected.clear()
        self.record_page = max(1, self.record_page + delta)
        self._show_filtered()

    def _jump_record_page(self):
        self.model.selected.clear()
        self.record_page = self.record_jump.value()
        self._show_filtered()

    def _inline_state_action(self, row, action):
        if not self.model.editable:
            return
        source = self.model.rows[row] if isinstance(row, int) else row
        if action == "delete":
            self._delete_state_rows([source])
            return
        key = self.model.key(source)
        if key in self._inline_inflight:
            self.message.setText("该记录正在保存，请稍候")
            return
        draft = self.model.drafts.get(key)
        if draft is None:
            self.message.setText("该记录没有行内修改")
            return
        if source.get("unsigned_offset_mm") is not None and draft.get("offset_mm") is None:
            self.message.setText("原记录方向待核对，请先填写带正负号的位移量；当前修改已保留")
            return
        if draft.get("_state_changed") and len(source.get("events") or []) > 1:
            if QMessageBox.question(self, "确认复合维护变更", "本次行内修改将用单一状态替换原复合事件，是否继续？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
        payload = {field: draft.get(field) for field in (
            "outage", "unit_id", "thimble_id", "state", "events", "offset_mm", "note",
            "source", "replacement_stage", "expected_updated_at")}
        self._inline_inflight.add(key)
        self.client.post("/api/state", payload, lambda data, error: self._inline_state_saved(key, data, error))

    def _inline_state_saved(self, key, data, error):
        self._inline_inflight.discard(key)
        if error or not data:
            self.message.setText(error or "行内修改保存失败，草稿已保留")
            return
        self.model.drafts.pop(key, None)
        self.message.setText("行内修改已保存")
        self.load()

    def _select_grid_tube(self, tube):
        if not 1 <= tube <= 50:
            return
        if self.batch_mode.isChecked():
            self._batch_selection_changed()
            return
        if self.current and self.current["thimble_id"] == tube:
            return
        if not self._allow_editor_change():
            if self.current:
                self.plate.selected = {self.current["thimble_id"]}
                self.plate.update()
            return
        for row in self._scope_rows():
            if row["thimble_id"] == tube:
                self.current = row
                self._populate_editor()
                return
        scope = self._state_scope
        if not scope.get("unit") or not scope.get("outage"):
            self.message.setText("请选择具体机组和大修")
            return
        self.current = {"outage": scope["outage"], "unit_id": int(scope["unit"]),
                        "thimble_id": tube, "state": "normal", "events": [], "note": ""}
        self.message.setText(f"{tube}号管 · 本次尚未维护")
        self._populate_editor()

    def _select(self, index):
        if self.batch_mode.isChecked():
            return
        if not self._allow_editor_change():
            return
        selected = dict(self.model.displayed(self.model.rows[index.row()]))
        scope = {"site": canonical_site(re.match(r"^[A-Z]+", selected["outage"])[0]),
                 "unit": str(selected["unit_id"]), "outage": selected["outage"]}
        if scope != self._state_scope:
            self._clear_editor()
            self.scope_bar.set_scope(scope)
            self.scope_bar.changed.emit(scope)
        self.current = selected
        self._populate_editor()

    def _populate_editor(self):
        if not self.current:
            return
        self._recognized_unsigned = None
        self.editor_tube.blockSignals(True)
        self.editor_tube.setValue(int(self.current["thimble_id"]))
        self.editor_tube.blockSignals(False)
        self.save.setEnabled(self.permissions is None or "state.write" in self.permissions)
        if not self.batch_mode.isChecked():
            self.plate.selected = {int(self.current["thimble_id"])}
            self.plate.update()
        self.editor_title.setText(f"{self.current['thimble_id']}号管 · {self.current.get('outage', '')} · 管号与处理")
        self.editor_source.setText(str(self.current.get("source") or ""))
        self.bulk_scope.setText(
            f"当前范围：{self.current.get('outage', '')} · {self.current.get('unit_id', '')}号机组"
        )
        state = str(self.current.get("state") or "normal")
        idx = self.state.findData(state)
        self.state.setCurrentIndex(max(0, idx))
        self.offset.setText("" if self.current.get("offset_mm") is None else str(self.current.get("offset_mm")))
        self.note.setText(str(self.current.get("note") or ""))
        for code, control in self.event_checks.items():
            control.blockSignals(True)
            control.setChecked(code in (self.current.get("events") or [state]))
            control.blockSignals(False)
        if len(self._editor_events()) > 1:
            self.state.setCurrentIndex(self.state.findData("composite"))
        self.replacement_stage.setCurrentIndex(max(0, self.replacement_stage.findData(
            self.current.get("replacement_stage") or "unknown")))
        self.use_default_offset.setVisible(self.current.get("unsigned_offset_mm") is not None)
        self._update_event_fields()
        self._update_effective_summary()
        from urllib.parse import urlencode
        self.client.get("/api/state-history?" + urlencode({
            "site": canonical_site(str(self.current["outage"]).rstrip("0123456789")),
            "unit_id": self.current["unit_id"], "thimble_id": self.current["thimble_id"]}),
            lambda data, error, selected=self.current: self._history_loaded(data, error)
            if self.current is selected else None)

    def _history_loaded(self, data, error):
        if error:
            self.history.setPlainText(error)
            return
        entries = []
        for row in (data or {}).get("timeline", []):
            distance = row.get("offset_mm")
            unsigned = row.get("unsigned_offset_mm")
            movement = (f"{float(distance):+g} mm" if distance is not None else
                        f"{unsigned} mm（方向待核对）" if unsigned is not None else "距离待核对")
            events = row.get("events") or [row.get("state")]
            label = row.get("event_label") or " · ".join(STATE_NAMES.get(code, str(code)) for code in events)
            effective = row.get("effective") or {}
            entries.append(f"{row.get('outage', '')} · {label}"
                           + (f" · 移位 {movement}" if "shifted" in events else "")
                           + f" · 第 {effective.get('generation', 1)} 代管\n"
                           + f"备注：{row.get('note') or '/'}\n来源：{row.get('source') or '/'}")
        if not entries:
            for row in (data or {}).get("items", []):
                action = {"create": "新增维护", "update": "修订维护", "revoke": "撤销维护"}.get(row.get("action"), "维护操作")
                entries.append(f"{row.get('created_at', '')} · {row.get('operator', '')} · {action}")
        self.history.setPlainText("\n\n".join(entries) or "该管暂无维护历史")

    def _save(self):
        if self._batch_busy or self.batch_mode.isChecked():
            return
        if not self.current:
            QMessageBox.information(self, PRODUCT_NAME, "请先选择状态记录")
            return
        try:
            payload = self._editor_payload()
        except ValueError as exc:
            QMessageBox.warning(self, PRODUCT_NAME, str(exc))
            return
        self.save.setEnabled(False)
        self._saving_key = tuple(payload[key] for key in ("outage", "unit_id", "thimble_id"))
        if self.current.get("recognition_id") is not None:
            self.client.post("/api/states/batch", {"rows": [payload], "confirmed": True}, self._saved)
            return
        self.client.post("/api/state", payload, self._saved)

    def _editor_events(self):
        return [code for code, control in self.event_checks.items() if control.isChecked()]

    def _editor_dirty(self):
        if not self.current:
            return False
        original = self.current.get("events") or (
            [self.current["state"]] if self.current.get("state") in self.event_checks else [])
        return (set(self._editor_events()) != set(original)
                or self.offset.text().strip() != ("" if self.current.get("offset_mm") is None else str(self.current["offset_mm"]))
                or self.note.text() != str(self.current.get("note") or "")
                or self.replacement_stage.currentData() != (self.current.get("replacement_stage") or "unknown"))

    def _allow_editor_change(self):
        if not self._editor_dirty():
            return True
        return QMessageBox.question(
            self, "未保存的维护编辑", "当前编辑尚未保存，是否放弃并切换？",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Discard

    def _simple_state_changed(self, *_):
        if self.state.currentData() == "composite":
            self._update_event_fields()
            return
        for code, control in getattr(self, "event_checks", {}).items():
            control.blockSignals(True)
            control.setChecked(code == self.state.currentData())
            control.blockSignals(False)
        self._update_event_fields()

    def _events_changed(self, *_):
        events = self._editor_events()
        state = ("composite" if len(events) > 1 or self.state.currentData() == "composite" else
                 next((code for code in ("plugged", "replaced", "shifted") if code in events), "normal"))
        self.state.blockSignals(True)
        self.state.setCurrentIndex(max(0, self.state.findData(state)))
        self.state.blockSignals(False)
        self._update_event_fields()

    def _update_event_fields(self):
        if not hasattr(self, "use_default_offset"):
            return
        events = self._editor_events()
        self.editor_form.setRowVisible(self.event_host, self.state.currentData() == "composite")
        self.editor_form.setRowVisible(self.replacement_stage, "replaced" in events and len(events) > 1)
        self.editor_form.setRowVisible(self.offset, "shifted" in events)
        self.use_default_offset.setVisible("shifted" in events and (
            getattr(self, "_recognized_unsigned", None) is not None
            or (self.current or {}).get("unsigned_offset_mm") is not None))

    def _editor_payload(self):
        import math
        scope = self._state_scope
        current = self.current or {"outage": scope.get("outage"), "unit_id": scope.get("unit")}
        events = self._editor_events()
        if self.state.currentData() == "composite" and len(events) < 2:
            raise ValueError("复合处理请至少选择两项；单项处理请直接选择对应状态。")
        raw = self.offset.text().strip() if "shifted" in events else ""
        try:
            offset = float(raw) if raw else None
        except ValueError:
            raise ValueError("位移量必须是数字。")
        if offset is not None and not math.isfinite(offset):
            raise ValueError("位移量必须是有限数字。")
        unsigned = getattr(self, "_recognized_unsigned", None)
        if unsigned is None:
            unsigned = current.get("unsigned_offset_mm")
        if "shifted" in events and unsigned is not None and (not raw or raw[0] not in "+-"):
            raise ValueError("原记录方向未确认，请填写带正负号的位移量。")
        return {"outage": current.get("outage"), "unit_id": current.get("unit_id"),
                "thimble_id": current.get("thimble_id", self.editor_tube.value()),
                "state": next((code for code in ("plugged", "replaced", "shifted") if code in events), "normal"),
                "events": events,
                "replacement_stage": self.replacement_stage.currentData(),
                "offset_mm": offset if "shifted" in events else 0,
                "note": self.note.text(), "source": str(current.get("source") or ""),
                "expected_updated_at": current.get("updated_at"),
                **({key: current[key] for key in ("recognition_id", "expected_state") if key in current})}

    def _update_effective_summary(self):
        tube = (self.current or {}).get("thimble_id")
        row = next((item for item in self._scope_items if item["thimble_id"] == tube), None)
        if not row:
            self.effective_summary.setText("正常表示本次有明确依据确认正常；未维护不等于正常。")
            return
        distance = row.get("cumulative_offset_mm")
        self.effective_summary.setText(
            f"截至本次有效：{row.get('state_label', '未维护')} · 第 {row.get('generation', 1)} 代管 · "
            f"累计位移 {distance if distance is not None else '待核对'} mm"
            + ("\n" + "；".join(row.get("warnings") or []) if row.get("warnings") else ""))

    def _recognize_note(self):
        if not self.current:
            self.message.setText("请先选择管号")
            return
        selected, original = self.current, self.note.text()
        self.recognize_note.setEnabled(False)
        self.client.post("/api/states/recognize-note",
                         {**selected, "note": original},
                         lambda data, error: self._note_recognized(selected, original, data, error))

    def _note_recognized(self, selected, original, data, error):
        self.recognize_note.setEnabled(self.permissions is None or "state.write" in self.permissions)
        if error:
            QMessageBox.warning(self, PRODUCT_NAME, error)
            return
        if self.current is not selected or self.note.text() != original:
            self.message.setText("编辑已变化，未应用先前的识别结果")
            return
        row = ((data or {}).get("rows") or [{}])[0]
        self._recognized_unsigned = row.get("unsigned_offset_mm")
        for code, control in self.event_checks.items():
            control.blockSignals(True)
            control.setChecked(code in (row.get("events") or [row.get("state")]))
            control.blockSignals(False)
        self._events_changed()
        self.replacement_stage.setCurrentIndex(max(0, self.replacement_stage.findData(row.get("replacement_stage") or "unknown")))
        offset = row.get("offset_mm")
        self.offset.setText("" if offset is None else f"{offset:+g}")
        self.message.setText("已识别到编辑区，请核对后保存" + (
            f"；原始位移 {row.get('unsigned_offset_mm')} mm，方向待确认" if data.get("requires_direction") else ""))

    def _generate_note(self):
        try:
            row = self._editor_payload()
        except ValueError as exc:
            QMessageBox.warning(self, PRODUCT_NAME, str(exc))
            return
        labels = [STATE_NAMES[code] for code in row["events"]] or ["正常"]
        text = f"{row.get('outage') or ''} {row['thimble_id']}号管：" + "、".join(labels)
        if "shifted" in row["events"]:
            text += f"，位移 {row['offset_mm']:+g} mm" if row["offset_mm"] is not None else "，位移距离待核对"
        if "replaced" in row["events"] and len(row["events"]) > 1:
            text += "，" + self.replacement_stage.currentText()
        existing = self.note.text()
        self.note.setText(existing + ("\n" if existing else "") + text)

    def _build_batch_editor(self):
        host = QWidget()
        form = self.batch_form = QFormLayout(host)
        form.setContentsMargins(0, 0, 0, 0)
        self.batch_selection = QLabel("已选管号：—")
        self.batch_selection.setWordWrap(True)
        form.addRow(self.batch_selection)
        self.batch_state = QComboBox()
        for name, code in (("正常", "normal"), ("堵管", "plugged"), ("移位", "shifted"),
                           ("换管", "replaced"), ("复合处理", "composite")):
            self.batch_state.addItem(name, code)
        form.addRow("统一处理状态", self.batch_state)
        self.batch_events_host = QWidget()
        events = QHBoxLayout(self.batch_events_host)
        events.setContentsMargins(0, 0, 0, 0)
        self.batch_events = {}
        for code, name in (("plugged", "堵管"), ("shifted", "移位"), ("replaced", "换管")):
            control = QCheckBox(name)
            self.batch_events[code] = control
            events.addWidget(control)
            control.toggled.connect(self._batch_selection_changed)
        form.addRow("本次同时发生", self.batch_events_host)
        self.batch_offset = QLineEdit()
        self.batch_offset.setPlaceholderText("正数正向，负数反向；未知可留空")
        self.batch_offset.textEdited.connect(self._batch_offset_edited)
        form.addRow("移位距离（mm）", self.batch_offset)
        self.batch_offset_hint = QLabel()
        self.batch_offset_hint.setWordWrap(True)
        self.batch_offset_hint.setObjectName("muted")
        form.addRow(self.batch_offset_hint)
        self.batch_stage = QComboBox()
        for name, code in (("未确认，标记待核对", "unknown"), ("其他处理在换管前", "before_replacement"),
                           ("其他处理在换管后", "after_replacement")):
            self.batch_stage.addItem(name, code)
        form.addRow("与换管的先后顺序", self.batch_stage)
        self.batch_note = QPlainTextEdit()
        self.batch_note.setPlaceholderText("填写本批处理依据或维护说明；原有备注和来源会保留")
        self.batch_note.setMaximumHeight(100)
        form.addRow("统一追加备注", self.batch_note)
        self.batch_state.currentIndexChanged.connect(self._batch_selection_changed)
        host.hide()
        return host

    def _batch_event_values(self):
        state = self.batch_state.currentData()
        return ([code for code, control in self.batch_events.items() if control.isChecked()]
                if state == "composite" else [] if state == "normal" else [state])

    def _batch_offset_edited(self, *_):
        self._batch_offset_touched = True
        self._batch_selection_changed()

    def _batch_selection_changed(self, *_):
        active = self.batch_mode.isChecked()
        selected = self.plate.selected
        self.batch_count.setText(f"已选 {len(selected)} 根")
        self.batch_selection.setText("已选管号：" + ("、".join(f"{tube:02}" for tube in sorted(selected)) or "—"))
        self.batch_apply.setText(f"处理所选（{len(selected)}）" if selected else "处理所选")
        writable = self.permissions is None or "state.write" in self.permissions
        self.batch_apply.setEnabled(writable and active and bool(selected) and not self._batch_busy)
        events = self._batch_event_values()
        shifted = "shifted" in events
        self.batch_form.setRowVisible(self.batch_events_host, self.batch_state.currentData() == "composite")
        self.batch_form.setRowVisible(self.batch_offset, shifted)
        self.batch_form.setRowVisible(self.batch_offset_hint, shifted)
        self.batch_form.setRowVisible(self.batch_stage, "replaced" in events and len(events) > 1)
        if not shifted:
            return
        rows = {row["thimble_id"]: row for row in self._scope_rows()}
        chosen = [rows.get(tube, {}) for tube in sorted(selected)]
        confirmed = [row.get("offset_mm") for row in chosen
                     if "shifted" in (row.get("events") or [row.get("state")])
                     and row.get("offset_mm") is not None and row.get("offset_confirmed", 1)]
        common = bool(chosen) and len(confirmed) == len(chosen) and len(set(confirmed)) == 1
        if self._batch_offset_touched:
            self.batch_offset_hint.setText("已保留手动填写的统一距离，请确认适用于全部所选管。")
        elif common:
            self.batch_offset.setText(f"{confirmed[0]:+g}")
            self.batch_offset_hint.setText(f"已同步共同距离 {confirmed[0]:+g} mm。")
        else:
            self.batch_offset.clear()
            self.batch_offset_hint.setText("所选管的本次距离不一致或待核对，未自动带入；请填写统一距离，或留空标记待核对。")

    def _batch_mode_changed(self, enabled):
        self.plate.multiselect = enabled
        self.plate.selected.clear()
        if enabled and self.current:
            self.plate.selected.add(int(self.current["thimble_id"]))
        if not enabled:
            self._batch_offset_touched = False
        self.single_editor.setVisible(not enabled)
        self.batch_editor.setVisible(enabled)
        self._batch_selection_changed()
        self.plate.update()

    def _select_batch(self, selected):
        self.batch_mode.setChecked(True)
        self.plate.selected = set(range(1, 51)) if selected else set()
        self._batch_selection_changed()
        self.plate.update()

    def _apply_selected_states(self):
        if self._batch_busy or not self.batch_mode.isChecked():
            return
        scope = self._state_scope
        if not scope.get("outage") or not scope.get("unit") or not self.plate.selected:
            self.message.setText("请选择具体机组、大修及要处理的管号")
            return
        try:
            import math
            events = self._batch_event_values()
            if self.batch_state.currentData() == "composite" and len(events) < 2:
                raise ValueError("复合处理请至少选择两项。")
            raw = self.batch_offset.text().strip()
            offset = float(raw) if raw and "shifted" in events else None
            if offset is not None and (not math.isfinite(offset) or abs(offset) > 1000):
                raise ValueError("位移量必须是 -1000 至 1000 mm 范围内的有限数字。")
            note = self.batch_note.toPlainText()
            if len(note) > 2000:
                raise ValueError("统一追加备注不能超过 2000 字。")
            template = {"events": events, "state": next((code for code in ("plugged", "replaced", "shifted")
                        if code in events), "normal"), "replacement_stage": self.batch_stage.currentData(),
                        "offset_mm": offset if "shifted" in events else 0, "unsigned_offset_mm": None,
                        "direction": "pending", "note": note}
        except ValueError as exc:
            QMessageBox.warning(self, PRODUCT_NAME, "位移量必须是数字。" if "could not convert" in str(exc) else str(exc))
            return
        existing = {row["thimble_id"]: row for row in self._scope_rows()}
        rows = [{**template, "outage": scope["outage"], "unit_id": int(scope["unit"]), "thimble_id": tube,
                 "source": "",
                 "expected_updated_at": existing.get(tube, {}).get("updated_at")}
                for tube in sorted(self.plate.selected)]
        payload = {"rows": rows, "mode": "append", "bulk_edit": True, "only_unmaintained": False}
        self._set_batch_busy(True)
        self.client.post("/api/states/batch-preview", payload,
                         lambda data, error: self._selected_preview(payload, data, error))

    def _set_batch_busy(self, busy):
        self._batch_busy = busy
        controls = (self.batch_mode, self.batch_all, self.batch_clear, self.batch_editor,
                    self.scope_bar, self.plate, self.import_button, self.bulk_normal,
                    self.default_direction, self.table)
        if busy:
            self._batch_enabled_before = [(control, control.isEnabled()) for control in controls]
            for control in controls:
                control.setEnabled(False)
        else:
            for control, enabled in getattr(self, "_batch_enabled_before", []):
                control.setEnabled(enabled)
        self._batch_selection_changed()

    def _selected_preview(self, payload, data, error):
        if error or not data:
            self._set_batch_busy(False)
            QMessageBox.warning(self, PRODUCT_NAME, error or "批量预览失败")
            return
        if not data.get("affected"):
            self._set_batch_busy(False)
            self.message.setText(f"没有可写入的记录；跳过 {data.get('skipped', 0)} 条")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("批量维护影响预览")
        dialog.resize(900, 500)
        layout = QVBoxLayout(dialog)
        summary = QLabel(f"已选 {len(payload['rows'])} 根 · 可保存 {data['affected']} 根 · "
                         f"跳过 {data.get('skipped', 0)} 根 · 待核对 {data.get('warnings', 0)} 根\n"
                         "确认后追加本次处理及备注，保留各管原有记录、来源和历史审计。")
        summary.setWordWrap(True)
        layout.addWidget(summary)
        table = QTableWidget(len(data.get("rows") or []), 5)
        table.setHorizontalHeaderLabels(["管号", "当前有效状态", "保存后有效状态", "累计位移 mm", "提示"])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        for index, row in enumerate(data.get("rows") or []):
            before, after = row.get("before") or {}, row.get("after") or {}
            for column, value in enumerate((row["thimble_id"], before.get("state_label", ""),
                    after.get("state_label", ""), after.get("cumulative_offset_mm"),
                    "；".join(after.get("warnings") or []))):
                table.setItem(index, column, QTableWidgetItem("待核对" if value is None else str(value)))
        table.resizeColumnsToContents()
        layout.addWidget(table)
        actions = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        actions.button(QDialogButtonBox.StandardButton.Ok).setText(f"确认保存 {data['affected']} 根")
        actions.button(QDialogButtonBox.StandardButton.Cancel).setText("返回修改")
        actions.accepted.connect(dialog.accept)
        actions.rejected.connect(dialog.reject)
        layout.addWidget(actions)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._set_batch_busy(False)
            return
        self.client.post("/api/states/batch", {**payload, "revision": data["revision"], "confirmed": True},
                         self._selected_batch_saved)

    def _selected_batch_saved(self, data, error):
        self._set_batch_busy(False)
        if not error and data:
            self.plate.selected.clear()
            self.batch_note.clear()
            self._batch_offset_touched = False
            self._batch_selection_changed()
            self.plate.update()
        self._batch_saved(data, error)

    def _review_pending(self):
        review_items = self._review_items()
        dialog = QDialog(self)
        dialog.setWindowTitle("导入待核对清单")
        dialog.resize(1000, 530)
        layout = QVBoxLayout(dialog)
        table = QTableWidget(len(review_items), 6)
        table.setHorizontalHeaderLabels(["大修", "机组", "管号", "识别状态", "待核对原因", "原始说明"])
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        for index, row in enumerate(review_items):
            for column, value in enumerate((row["outage"], row["unit_id"], row["thimble_id"],
                                           row.get("event_label") or STATE_NAMES.get(row.get("state"), "待核对"),
                                           row.get("review_reason", ""), row.get("note", ""))):
                table.setItem(index, column, QTableWidgetItem(str(value)))
        layout.addWidget(table)
        actions = QHBoxLayout()
        edit = button("核对所选记录", "wrench")
        dismiss = button("忽略所选识别", "x")
        close = button("关闭", "x", dialog.reject)
        writable = self.permissions is None or "state.write" in self.permissions
        edit.setEnabled(writable)
        dismiss.setEnabled(writable)
        for control in (edit, dismiss, close):
            actions.addWidget(control)
        layout.addLayout(actions)
        def selected_rows():
            return [review_items[index.row()] for index in table.selectionModel().selectedRows()]
        def edit_selected():
            rows = selected_rows()
            if len(rows) != 1 or not self._allow_editor_change():
                return
            row = dict(rows[0])
            self.current = None
            self._filter_scope({"site": canonical_site(re.match(r"^[A-Z]+", row["outage"])[0]),
                                "unit": str(row["unit_id"]), "outage": row["outage"]})
            self.scope_bar.set_scope(self._state_scope)
            self.current = row
            self._populate_editor()
            self.message.setText(row.get("review_reason") or "核对后保存")
            dialog.accept()
        def dismiss_selected():
            rows = selected_rows()
            if not rows:
                return
            if any(row.get("recognition_id") is None for row in rows):
                QMessageBox.information(dialog, PRODUCT_NAME, "所选项含已保存的维护记录，请核对编辑；仅待识别结果可忽略。")
                return
            if QMessageBox.question(dialog, "忽略识别", f"确认忽略所选 {len(rows)} 条识别结果？",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
            self.client.post("/api/states/dismiss-recognition",
                             {"ids": [row["recognition_id"] for row in rows], "confirmed": True},
                             lambda data, error: QMessageBox.warning(dialog, PRODUCT_NAME, error)
                             if error else (dialog.accept(), self.load()))
        edit.clicked.connect(edit_selected)
        dismiss.clicked.connect(dismiss_selected)
        dialog.exec()

    def _review_items(self):
        return self.pending_rows + [{**row, "review_reason": "维护距离、方向或换管前后顺序待核对"}
                                    for row in self.all_rows if row.get("needs_review")]

    def _add_scope(self):
        from .native_components import SITE_NAMES
        dialog = QDialog(self)
        dialog.setWindowTitle("新增大修范围")
        form = QFormLayout(dialog)
        site = QComboBox()
        for code, name in SITE_NAMES.items():
            site.addItem(name, code)
        site.setCurrentIndex(max(0, site.findData(self._state_scope.get("site"))))
        unit = QSpinBox()
        unit.setRange(1, 9)
        unit.setValue(int(self._state_scope.get("unit") or 1))
        outage = QLineEdit()
        outage.setMaxLength(5)
        outage.setPlaceholderText("如 N103、LF198")
        form.addRow("基地", site)
        form.addRow("机组", unit)
        form.addRow("大修编号", outage)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        form.addRow(buttons)
        buttons.rejected.connect(dialog.reject)
        def save():
            code = outage.text().strip().upper()
            if not re.fullmatch(re.escape(site.currentData()) + str(unit.value()) + r"\d{2}", code):
                QMessageBox.warning(dialog, PRODUCT_NAME, "大修编号必须与基地和机组一致，例如 N103。")
                return
            if not self._allow_editor_change():
                return
            buttons.setEnabled(False)
            def saved(data, error):
                buttons.setEnabled(True)
                if error:
                    QMessageBox.warning(dialog, PRODUCT_NAME, error)
                    return
                self.current = None
                self._state_scope = {"site": site.currentData(), "unit": str(unit.value()), "outage": code}
                self.scope_bar.set_scope(self._state_scope)
                self.load()
                dialog.accept()
            self.client.post("/api/states/scopes", {"site": site.currentData(), "unit_id": unit.value(), "outage": code}, saved)
        buttons.accepted.connect(save)
        dialog.exec()

    def resizeEvent(self, event):
        self.state_split.setOrientation(Qt.Orientation.Vertical if self.width() < 1120 else Qt.Orientation.Horizontal)
        super().resizeEvent(event)

    def _saved(self, data, error):
        self.save.setEnabled(self.permissions is None or "state.write" in self.permissions)
        self.advanced.setEnabled(self.permissions is None or "state.write" in self.permissions)
        self.new_state.setEnabled(self.permissions is None or "state.write" in self.permissions)
        if error:
            QMessageBox.warning(self, PRODUCT_NAME, error)
            return
        QMessageBox.information(self, PRODUCT_NAME, "状态已保存，审计记录已生成")
        self._select_after_load = getattr(self, "_saving_key", None)
        if self._select_after_load:
            self.model.drafts.pop(self._select_after_load, None)
        self.current = None
        self.load()

    def _edit_advanced(self, new: bool = False) -> None:
        current = None if new else self.current
        defaults = current or {"outage": self._state_scope.get("outage") or "",
                               "unit_id": self._state_scope.get("unit") or 1}
        dialog = QDialog(self)
        dialog.setWindowTitle("复合维护记录" if current else "新建维护记录")
        form = QFormLayout(dialog)
        outage = QLineEdit(str(defaults.get("outage") or ""))
        outage.setObjectName("maintenanceOutage")
        unit = QSpinBox()
        unit.setObjectName("maintenanceUnit")
        unit.setRange(1, 9)
        unit.setValue(int(defaults.get("unit_id") or 1))
        tube = QSpinBox()
        tube.setObjectName("maintenanceTube")
        tube.setRange(1, 50)
        tube.setValue(int((current or {}).get("thimble_id") or 1))
        for widget in (outage, unit, tube):
            widget.setEnabled(current is None)
        form.addRow("大修编号", outage)
        form.addRow("机组", unit)
        form.addRow("管号", tube)
        events = set((current or {}).get("events") or [])
        checks = {}
        for code, label in (("plugged", "堵管"), ("shifted", "移位"), ("replaced", "换管")):
            check = QCheckBox(label)
            check.setObjectName("maintenance_" + code)
            check.setChecked(code in events)
            checks[code] = check
            form.addRow("", check)
        stage = QComboBox()
        stage.setObjectName("maintenanceStage")
        stage.addItem("待核对", "unknown")
        stage.addItem("其他处理在换管前", "before_replacement")
        stage.addItem("其他处理在换管后", "after_replacement")
        stage.setCurrentIndex(max(0, stage.findData((current or {}).get("replacement_stage") or "unknown")))
        form.addRow("换管顺序", stage)
        offset = QLineEdit()
        offset.setObjectName("maintenanceOffset")
        saved_offset = (current or {}).get("offset_mm")
        if saved_offset is not None:
            offset.setText(str(saved_offset))
        unsigned = (current or {}).get("unsigned_offset_mm")
        if unsigned is not None:
            offset.setPlaceholderText(f"原始距离 {unsigned} mm，须填写正负号确认方向")
        else:
            offset.setPlaceholderText("有符号毫米值；距离未记录可留空")
        form.addRow("移位量 (mm)", offset)
        note = QPlainTextEdit(str((current or {}).get("note") or ""))
        note.setObjectName("maintenanceNote")
        note.setMaximumHeight(120)
        form.addRow("备注", note)
        if current and current.get("source"):
            source = QLabel(str(current["source"]))
            source.setWordWrap(True)
            form.addRow("原始来源", source)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected = [code for code in ("plugged", "shifted", "replaced") if checks[code].isChecked()]
        raw = offset.text().strip()
        if unsigned is not None and "shifted" in selected and (not raw or raw[0] not in "+-"):
            QMessageBox.warning(self, PRODUCT_NAME, "原记录方向未确认，请填写带正负号的位移量后保存。")
            return
        try:
            distance = float(raw) if raw else None
        except ValueError:
            QMessageBox.warning(self, PRODUCT_NAME, "位移量必须是数字。")
            return
        if "shifted" not in selected and distance not in (None, 0):
            QMessageBox.warning(self, PRODUCT_NAME, "未选择移位事件时不能填写位移量。")
            return
        state = next((code for code in ("plugged", "replaced", "shifted") if code in selected), "normal")
        payload = {
            "outage": outage.text().strip().upper(), "unit_id": unit.value(), "thimble_id": tube.value(),
            "state": state, "events": selected, "replacement_stage": stage.currentData(),
            "offset_mm": distance if "shifted" in selected else 0, "note": note.toPlainText(),
            "expected_updated_at": current.get("updated_at") if current else None,
        }
        self.save.setEnabled(False)
        self.advanced.setEnabled(False)
        self.new_state.setEnabled(False)
        self._saving_key = tuple(payload[key] for key in ("outage", "unit_id", "thimble_id"))
        self.client.post("/api/state", payload, self._saved)

    def _scope_from_current(self) -> dict[str, Any] | None:
        selected_scope = getattr(self, "_state_scope", {})
        if selected_scope.get("outage") and selected_scope.get("unit"):
            return {"outage": selected_scope["outage"], "unit_id": int(selected_scope["unit"])}
        if not self.current:
            outage, ok = QInputDialog.getText(self, "选择维护范围", "大修编号（例如 N101）")
            if not ok or not outage.strip():
                return None
            unit, ok = QInputDialog.getInt(self, "选择维护范围", "机组号", 1, 1, 9)
            if not ok:
                return None
            return {"outage": outage.strip().upper(), "unit_id": unit}
        return {
            "outage": self.current.get("outage"),
            "unit_id": self.current.get("unit_id"),
        }

    def _bulk_normal(self) -> None:
        scope = self._scope_from_current()
        if not scope:
            return
        rows = [
            {**scope, "thimble_id": tube, "state": "normal", "offset_mm": 0,
             "note": "人工批量确认正常", "source": "native-qt"}
            for tube in range(1, 51)
        ]
        self.bulk_normal.setEnabled(False)
        self.client.post(
            "/api/states/batch-preview",
            {"rows": rows, "only_unmaintained": True},
            lambda data, error: self._bulk_preview_loaded("补齐未维护管为正常", rows, data, error),
        )

    def _bulk_preview_loaded(self, title: str, rows: list[dict[str, Any]],
                             data: dict[str, Any] | None, error: str | None) -> None:
        self.bulk_normal.setEnabled(self.permissions is None or "state.write" in self.permissions)
        if error or not data:
            QMessageBox.warning(self, PRODUCT_NAME, error or "批量预览失败")
            return
        affected = int(data.get("affected", 0) or 0)
        skipped = int(data.get("skipped", 0) or 0)
        if affected <= 0:
            QMessageBox.information(self, PRODUCT_NAME, f"没有可处理的记录（跳过 {skipped} 条）")
            return
        answer = QMessageBox.question(
            self, title,
            f"预览将写入 {affected} 条记录，跳过 {skipped} 条已有或待核查记录。是否确认？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        payload = {"rows": rows, "confirmed": True, "only_unmaintained": True,
                   "revision": data.get("revision")}
        self.client.post("/api/states/batch", payload, self._batch_saved)

    def _batch_saved(self, data: dict[str, Any] | None, error: str | None) -> None:
        if error or not data:
            QMessageBox.warning(self, PRODUCT_NAME, error or "批量保存失败")
            return
        QMessageBox.information(
            self, PRODUCT_NAME,
            f"批量维护完成：更新 {data.get('changed', 0)} 条，跳过 {data.get('skipped', 0)} 条",
        )
        self.load()

    def _import_state_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择管状态表", "",
            "状态表 (*.xlsx *.xlsm *.xls *.docx *.csv);;所有文件 (*)",
        )
        if not path:
            return
        try:
            if Path(path).stat().st_size > 12_000_000:
                raise ValueError("状态表格不可超过 12 MB")
            content = base64.b64encode(Path(path).read_bytes()).decode("ascii")
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, PRODUCT_NAME, f"读取状态表失败：{exc}")
            return
        self.import_button.setEnabled(False)
        self.client.post(
            "/api/states/import-preview",
            {"filename": Path(path).name, "content": content, "direction_policy": "pending"},
            lambda data, error: self._state_import_preview(Path(path).name, data, error, content),
        )

    def _state_import_preview(self, filename: str, data: dict[str, Any] | None,
                              error: str | None, content: str | None = None) -> None:
        self.import_button.setEnabled(self.permissions is None or "state.write" in self.permissions)
        if error or not data:
            QMessageBox.warning(self, PRODUCT_NAME, error or "状态表识别失败")
            return
        if not isinstance(data.get("revision"), str) or not data["revision"]:
            QMessageBox.warning(self, PRODUCT_NAME, "状态表预览缺少数据库版本，无法安全导入。请重新识别。")
            return
        rows = [row for row in data.get("rows", []) if isinstance(row, dict)]
        missing = [group for group in data.get("missing_scopes", []) if isinstance(group, dict)]
        if missing and content is not None:
            answer = QMessageBox.question(
                self, "补充大修编号",
                f"有 {len(missing)} 组维护信息缺少大修编号。是否补充后重新识别？"
                + ("选择“否”仅预览已识别记录。" if rows else "选择“否”将不导入任何记录。"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return
            if answer == QMessageBox.StandardButton.Yes:
                overrides = {}
                for group in missing:
                    title = str(group.get("title") or group.get("key") or "工作表")
                    while True:
                        value, ok = QInputDialog.getText(
                            self, "补充大修编号",
                            f"{title}（{group.get('rows', 0)} 条）的大修编号：",
                        )
                        if not ok:
                            return
                        value = value.strip().upper()
                        match = re.fullmatch(r"([A-Z]{1,2})([1-9])\d{2}", value)
                        if (match and (not group.get("site") or match.group(1) == str(group["site"]).upper())
                                and (not group.get("unit_id") or int(match.group(2)) == int(group["unit_id"]))):
                            overrides[str(group["key"])] = value
                            break
                        QMessageBox.warning(self, PRODUCT_NAME, "大修编号格式无效或与识别出的基地、机组不一致。")
                self.import_button.setEnabled(False)
                self.client.post(
                    "/api/states/import-preview",
                    {"filename": filename, "content": content, "scope_overrides": overrides,
                     "direction_policy": "pending"},
                    lambda result, problem: self._state_import_preview(filename, result, problem, content),
                )
                return
        if not rows:
            QMessageBox.information(self, PRODUCT_NAME, f"{filename} 未识别到可导入的维护记录")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"状态表导入预览：{filename}")
        dialog.resize(980, 620)
        layout = QVBoxLayout(dialog)
        info = QLabel(
            f"识别 {len(rows)} 条，警告 {len(data.get('warnings') or [])} 条。"
            f"未识别范围 {len(data.get('missing_scopes') or [])} 组。"
            "已有记录默认不覆盖；请逐行确认未注明的方向，可编辑备注。"
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        table = QTableView(dialog)
        table.setObjectName("stateImportTable")
        model = StateImportModel(rows, table)
        table.setModel(model)
        table.setItemDelegateForColumn(7, StateDirectionDelegate(table))
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.horizontalHeader().setStretchLastSection(True)
        controls = QHBoxLayout()
        select_new = QPushButton("选择新增记录")
        select_new.clicked.connect(lambda: model.select_new_rows(True))
        clear_new = QPushButton("取消选择新增记录")
        clear_new.clicked.connect(lambda: model.select_new_rows(False))
        directions = QComboBox()
        directions.addItems(StateImportModel.directions)
        apply_direction = QPushButton("应用到所选记录")
        apply_direction.clicked.connect(lambda: model.set_selected_direction(directions.currentText()))
        controls.addWidget(select_new)
        controls.addWidget(clear_new)
        controls.addStretch(1)
        controls.addWidget(QLabel("批量方向"))
        controls.addWidget(directions)
        controls.addWidget(apply_direction)
        layout.addLayout(controls)
        layout.addWidget(table, 1)
        if data.get("warnings"):
            warning = QPlainTextEdit()
            warning.setReadOnly(True)
            warning.setMaximumHeight(100)
            warning.setPlainText("\n".join(map(str, data["warnings"])))
            layout.addWidget(warning)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确认导入")
        def confirm_preview():
            try:
                chosen = model.selected_rows()
            except ValueError as exc:
                QMessageBox.warning(dialog, PRODUCT_NAME, str(exc))
                return
            if not chosen:
                QMessageBox.information(dialog, PRODUCT_NAME, "未选择任何导入记录")
                return
            dialog.accept()

        buttons.accepted.connect(confirm_preview)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            selected = model.selected_rows()
        except ValueError as exc:
            QMessageBox.warning(self, PRODUCT_NAME, str(exc) + " 本次未导入，请重新预览。")
            return
        if not selected:
            QMessageBox.information(self, PRODUCT_NAME, "未选择任何导入记录")
            return
        self.client.post(
            "/api/states/batch",
            {"rows": selected, "confirmed": True, "import_revision": data.get("revision")},
            self._batch_saved,
        )

    def _export_states(self) -> None:
        scope = self._scope_from_current()
        if not scope:
            return
        fmt = self.export_format.currentData()
        self.export_button.setEnabled(False)
        self.client.post("/api/states/export", {**scope, "format": fmt}, self._export_done)

    def _export_done(self, data: dict[str, Any] | None, error: str | None) -> None:
        self.export_button.setEnabled(self.permissions is None or "export.create" in self.permissions)
        if error or not data:
            QMessageBox.warning(self, PRODUCT_NAME, error or "状态导出失败")
            return
        filename = data.get("filename") or "状态导出文件"
        QMessageBox.information(
            self, PRODUCT_NAME,
            f"已生成 {filename}，共 {data.get('rows', 0)} 条记录。\n"
            f"保存目录：{REPORT_DIR if str(filename).lower().endswith('.docx') else OUTPUT_DIR}",
        )

    def _delete_selected(self) -> None:
        indexes = self.table.selectionModel().selectedRows()
        checked = [row for row in self.all_rows if self.model.key(row) in self.model.selected]
        if not indexes and not checked:
            QMessageBox.information(self, PRODUCT_NAME, "请先选择要删除的状态记录")
            return
        rows = checked or [self.model.rows[index.row()] for index in indexes if 0 <= index.row() < len(self.model.rows)]
        self._delete_state_rows(rows)

    def _delete_state_rows(self, rows):
        if QMessageBox.warning(
            self, PRODUCT_NAME,
            f"将撤销 {len(rows)} 条维护记录（检测数据不会删除），是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self.delete_button.setEnabled(False)
        self.client.post(
            "/api/states/delete-batch",
            {"rows": [{**row, "expected_updated_at": row.get("updated_at")} for row in rows], "confirmed": True},
            lambda data, error, keys=[self.model.key(row) for row in rows]: self._delete_done(data, error, keys),
        )

    def _delete_done(self, data: dict[str, Any] | None, error: str | None, keys=()) -> None:
        self.delete_button.setEnabled(self.permissions is None or "state.write" in self.permissions)
        if error or not data:
            QMessageBox.warning(self, PRODUCT_NAME, error or "状态撤销失败")
            return
        for key in keys:
            self.model.drafts.pop(key, None)
            self.model.selected.discard(key)
        QMessageBox.information(self, PRODUCT_NAME, f"已撤销 {data.get('deleted', 0)} 条维护记录")
        self.load()


class NativeAnalyticsPage(QWidget):
    def __init__(self, client: NativeClient, user: dict[str, Any] | None = None, parent=None):
        super().__init__(parent)
        self.client = client
        self.user = user
        self._chart_windows = []
        self.permissions = None if user is None else set(user.get("permissions", []))
        self._analysis_request = 0
        self._coverage_request = 0
        self._coverage_snapshots = {}
        self._workspace_scope = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        self.scroll.setWidget(body)
        outer.addWidget(self.scroll)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(18, 8, 18, 16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.site_coverage_host = QWidget()
        self.site_coverage_host.setObjectName("siteCoverageHost")
        self.site_coverage_host.installEventFilter(self)
        self.site_coverage = QGridLayout(self.site_coverage_host)
        self.site_coverage.setContentsMargins(0, 0, 0, 0)
        self.site_coverage.setSpacing(7)
        self.site_coverage_buttons = {}
        from .native_components import SITE_NAMES
        for index, (site, name) in enumerate((("", "全部基地"), *SITE_NAMES.items())):
            control = SiteCoverageButton(site, name)
            control.clicked.connect(lambda _, value=site: self._select_site(value))
            self.site_coverage_buttons[site] = control
            self.site_coverage.addWidget(control, index // 8, index % 8)
        band = QWidget()
        self.filter_band = band
        band.setObjectName("filterBand")
        band.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        band_layout = QVBoxLayout(band)
        band_layout.setContentsMargins(14, 12, 14, 12)
        top = QHBoxLayout()
        top.setSpacing(14)
        heading = QLabel("基地范围")
        heading.setFixedWidth(150)
        top.addWidget(heading)
        top.addWidget(self.site_coverage_host, 1)
        band_layout.addLayout(top)
        self.scope_bar = AnalyticsScopeBar(client)
        band_layout.addWidget(self.scope_bar)
        layout.addWidget(band)
        self.scope_bar.changed.connect(self._scope_selected)
        scope = QHBoxLayout()
        self.analysis_site = QLineEdit()
        self.analysis_site.setPlaceholderText("例如 N")
        self.analysis_unit = QSpinBox()
        self.analysis_unit.setRange(1, 99)
        self.analysis_outage = QLineEdit()
        self.analysis_outage.setPlaceholderText("例如 N101")
        self.analysis_old = QLineEdit()
        self.analysis_old.setPlaceholderText("对比时填写历史大修")
        for widget in (self.analysis_site, self.analysis_unit, self.analysis_outage):
            widget.hide()
        history_label = QLabel("历史大修")
        history_label.hide()
        scope.addWidget(history_label)
        scope.addWidget(self.analysis_old)
        self.analysis_old.hide()
        layout.addLayout(scope)
        analysis_actions = QHBoxLayout()
        self.live_button = QPushButton("加载真实管板分析")
        self.compare_button = QPushButton("加载历次对比")
        self.complex_button = QPushButton("复杂分析")
        self.rules_button = QPushButton("分析规则")
        self.live_button.clicked.connect(self.load_live_analysis)
        self.compare_button.clicked.connect(self.load_comparison)
        self.complex_button.clicked.connect(self.load_complex_analysis)
        self.rules_button.clicked.connect(self.manage_analysis_rules)
        if self.permissions is not None and "data.read" not in self.permissions:
            self.complex_button.setEnabled(False)
        if self.permissions is not None and "settings.manage" not in self.permissions:
            self.rules_button.setEnabled(False)
            self.rules_button.setToolTip("当前账户没有分析规则管理权限")
        analysis_actions.addWidget(self.live_button)
        analysis_actions.addWidget(self.compare_button)
        analysis_actions.addWidget(self.complex_button)
        analysis_actions.addWidget(self.rules_button)
        analysis_actions.addStretch(1)
        self.advanced_analysis_controls = QWidget()
        self.advanced_analysis_controls.setLayout(analysis_actions)
        self.advanced_analysis_controls.hide()
        layout.addWidget(self.advanced_analysis_controls)
        self.cards = QGridLayout()
        self.labels: dict[str, QLabel] = {}
        for index, (key, caption) in enumerate((
            ("totalTubes", "涉及套管"), ("activeDefects", "检测记录"),
            ("runningUnits", "机组数量"), ("activeOutages", "大修数量"),
            ("maxWear", "最大磨损"),
        )):
            box = QWidget()
            box.setObjectName("metricCard")
            box_layout = QVBoxLayout(box)
            value = QLabel("—")
            value.setObjectName("metricValue")
            box_layout.addWidget(value)
            box_layout.addWidget(QLabel(caption))
            self.labels[key] = value
            self.cards.addWidget(box, 0, index)
            box.hide()
        layout.addLayout(self.cards)
        self.analysis_status = QLabel("输入分析范围后加载真实数据。")
        self.analysis_status.setWordWrap(True)
        layout.addWidget(self.analysis_status)
        self.plate_table = QTableWidget(0, 6)
        self.plate_table.setHorizontalHeaderLabels(["管号", "管板位置", "检测记录", "状态", "最大磨损", "维护状态"])
        self.plate_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.plate_table.horizontalHeader().setStretchLastSection(True)
        self.plate_table.setMinimumHeight(260)
        self.plate_table.hide()
        from .native_charts import VisualizationWorkspace
        self.visualization = VisualizationWorkspace(client=client, permissions=self.permissions)
        self.visualization.panelRequested.connect(self.open_chart_window)
        self.scope_bar.loaded.connect(lambda *_: self.visualization.set_history_units(self.scope_bar.combinations))
        layout.addWidget(self.visualization, 1)
        self.detail = QLabel("正在加载统计摘要...")
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)
        self.complex_tabs = QTabWidget()
        self.trend_table = QTableWidget(0, 7)
        self.trend_table.setHorizontalHeaderLabels(
            ["机组", "大修", "记录", "WAR", "有效磨损合计", "缺失管", "质量状态"]
        )
        self.increment_table = QTableWidget(0, 6)
        self.increment_table.setHorizontalHeaderLabels(
            ["机组", "本次大修", "历史大修", "匹配数", "磨损增量", "核查"]
        )
        self.coverage_table = QTableWidget(0, 5)
        self.coverage_table.setHorizontalHeaderLabels(
            ["机组", "大修", "缺陷", "NDD", "待复核/缺失"]
        )
        self.quality_text = QPlainTextEdit()
        self.quality_text.setReadOnly(True)
        self.complex_tabs.addTab(self.trend_table, "磨损趋势")
        self.complex_tabs.addTab(self.increment_table, "相邻增量")
        self.complex_tabs.addTab(self.coverage_table, "覆盖与状态")
        self.complex_tabs.addTab(self.quality_text, "质量诊断")
        self.complex_tabs.setVisible(False)
        self.analysis_details = QCheckBox("数据核查与高级分析")
        self.analysis_details.toggled.connect(self.complex_tabs.setVisible)
        self.analysis_details.toggled.connect(self.advanced_analysis_controls.setVisible)
        self.analysis_details.toggled.connect(self.analysis_old.setVisible)
        self.analysis_details.toggled.connect(history_label.setVisible)
        layout.addWidget(self.analysis_details)
        layout.addWidget(self.complex_tabs, 1)
        refresh = QPushButton("刷新统计")
        refresh.clicked.connect(self.load)
        refresh.hide()
        self.scope_bar.refresh.clicked.connect(self.load_complex_analysis)
        self.load()

    def open_chart_window(self, key):
        owner = getattr(self.window(), "analytics_owner", self)
        dialog = NativeChartWindow(self, owner, key)
        owner._chart_windows.append(dialog)
        dialog.finished.connect(lambda *_: owner._chart_windows.remove(dialog)
                                if dialog in owner._chart_windows else None)
        dialog.show()
        return dialog

    def _select_site(self, site):
        selected = set(self.scope_bar.selected_sites)
        if not site:
            selected.clear()
        elif site in selected:
            selected.remove(site)
        else:
            selected.add(site)
        self.scope_bar.set_sites(selected)

    def _scope_selected(self, scope):
        self._workspace_scope = {key: str(scope.get(key) or "") for key in ("site", "unit", "outage")}
        self.analysis_site.setText(scope.get("site") or "")
        self.analysis_unit.setValue(int(scope.get("unit") or 1))
        self.analysis_outage.setText(scope.get("outage") or "")
        self._update_coverage()
        self.load_complex_analysis()

    def set_workspace_scope(self, scope):
        requested = {key: str(scope.get(key) or "") for key in ("site", "unit", "outage")}
        if requested == self._workspace_scope and (self.visualization.data or self._analysis_request):
            if scope.get("thimble"):
                self.visualization.select_tube(int(scope["thimble"]))
            return
        self._workspace_scope = requested
        previous = (self.analysis_site.text(), self.analysis_unit.value(), self.analysis_outage.text())
        self.scope_bar.set_scope(scope)
        current = (scope.get("site") or "", int(scope.get("unit") or 1), scope.get("outage") or "")
        if previous != current or not self.visualization.data:
            self._scope_selected(scope)
        if scope.get("thimble"):
            self.visualization.select_tube(int(scope["thimble"]))

    def load(self):
        self.client.get("/api/analytics/summary", self._loaded)
        self._coverage_request += 1
        self._coverage_pending = True
        number = self._coverage_request
        self.client.get("/api/analysis/visualization" + ("" if self.visualization.ndd_zero else "?ndd_zero=0"),
                        lambda data, error: self._coverage_loaded(data, error)
                        if number == self._coverage_request else None)

    def _coverage_loaded(self, data, error):
        self._coverage_pending = False
        waiting = getattr(self, "_unfiltered_analysis_number", None)
        self._unfiltered_analysis_number = None
        if waiting is not None and waiting == self._analysis_request:
            self._complex_loaded(data, error)
        if error or not data:
            self.site_coverage_host.setToolTip(error or "基地覆盖读取失败")
            return
        self._coverage_snapshots = {}
        for item in data.get("snapshots") or []:
            previous = self._coverage_snapshots.get(item["unit"])
            if previous is None or item["order"] > previous["order"]:
                self._coverage_snapshots[item["unit"]] = item
        self._update_coverage()

    def _update_coverage(self):
        for site, control in self.site_coverage_buttons.items():
            snapshots = [snapshot for snapshot in self._coverage_snapshots.values()
                         if not site or re.match(r"^[A-Z]+", snapshot["unit"])[0] == site]
            tubes = [tube for snapshot in snapshots for tube in snapshot.get("tubes") or []]
            reported = sum(tube.get("coverage") != "missing" for tube in tubes)
            control.set_summary(len(snapshots), reported, len(tubes))
            control.setChecked(site in self.scope_bar.selected_sites if site else not self.scope_bar.selected_sites)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "visualization"):
            self.visualization.set_metric_columns(3 if event.size().width() < 1180 else 6)
        self._arrange_site_filters()

    def eventFilter(self, watched, event):
        if watched is getattr(self, "site_coverage_host", None) and event.type() == QEvent.Type.Resize:
            self._arrange_site_filters(event.size().width())
        return super().eventFilter(watched, event)

    def _arrange_site_filters(self, width=None):
        if not hasattr(self, "site_coverage_buttons"):
            return
        width = max(0, self.site_coverage_host.width() if width is None else width)
        columns = max(2, min(8, (width + 7) // 152))
        if columns == getattr(self, "_site_columns", None):
            return
        self._site_columns = columns
        for index, control in enumerate(self.site_coverage_buttons.values()):
            self.site_coverage.removeWidget(control)
            self.site_coverage.addWidget(control, index // columns, index % columns)
        for column in range(8):
            self.site_coverage.setColumnStretch(column, 1 if column < columns else 0)

    def _loaded(self, data, error):
        if error or not data:
            self.detail.setText(error or "统计读取失败")
            return
        for key, label in self.labels.items():
            value = data.get(key, 0)
            label.setText(f"{value:,}" if isinstance(value, (int, float)) else str(value))
        top = data.get("topTube") or {}
        self.detail.setText(
            "风险摘要："
            + (f"{top.get('siteName') or top.get('siteCode') or ''} "
               f"{top.get('outage') or ''} · {top.get('unitId') or ''}号机 · "
               f"{top.get('tubeNumber') or ''}号管，磨损 {top.get('wearDepth', 0)}%"
               if top else "当前没有可展示的磨损记录")
        )

    def _analysis_params(self) -> str:
        from urllib.parse import urlencode
        values = {
            "site": self.analysis_site.text().strip().upper(),
            "unit": self.analysis_unit.value(),
            "outage": self.analysis_outage.text().strip().upper(),
        }
        return "?" + urlencode(values)

    def load_live_analysis(self) -> None:
        if not self.analysis_site.text().strip() or not self.analysis_outage.text().strip():
            self.analysis_status.setText("请填写基地、机组和当前大修。")
            return
        self.analysis_status.setText("正在读取真实管板分析...")
        self.live_button.setEnabled(False)
        self.client.get("/api/analysis/live" + self._analysis_params(), self._live_loaded)

    def _live_loaded(self, data: dict[str, Any] | None, error: str | None) -> None:
        self.live_button.setEnabled(True)
        if error or not data:
            self.analysis_status.setText(error or "管板分析读取失败")
            return
        summary = data.get("summary") or {}
        self.analysis_status.setText(
            f"记录 {summary.get('records', 0)} 条，缺陷管 {summary.get('defect_tubes', 0)} 根，"
            f"NDD 管 {summary.get('ndd_tubes', 0)} 根，待复核 {summary.get('incomplete', 0)} 根，"
            f"缺失管 {summary.get('missing_tubes', 0)} 根，最大磨损 {summary.get('max_percent', '未提供')}"
        )
        rows = [row for row in data.get("plate", []) if isinstance(row, dict)]
        self.plate_table.setRowCount(len(rows))
        for row, item in enumerate(rows):
            category = ("存在缺陷" if item.get("defects") else
                        "NDD" if item.get("ndd") else
                        "待复核" if item.get("records") else "无记录")
            values = (
                item.get("tube", ""),
                item.get("position", ""),
                item.get("records", 0),
                category,
                item.get("max_percent") if item.get("max_percent") is not None else "未提供",
                item.get("state") or item.get("state_label") or "未记录",
            )
            for column, value in enumerate(values):
                self.plate_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.detail.setText(
            "分析规则：" + str(data.get("rule_note") or "结果遵循后端当前分析规则；缺失、待复核和人工维护状态不等同于确认缺陷。")
        )

    def load_comparison(self) -> None:
        old = self.analysis_old.text().strip().upper()
        new = self.analysis_outage.text().strip().upper()
        if not old or not new:
            self.analysis_status.setText("历次对比需要填写历史大修和当前大修。")
            return
        from urllib.parse import urlencode
        query = urlencode({"old": old, "new": new, "unit": self.analysis_unit.value()})
        self.compare_button.setEnabled(False)
        self.analysis_status.setText("正在读取历次对比...")
        self.client.get("/api/compare?" + query, self._comparison_loaded)

    def _comparison_loaded(self, data: dict[str, Any] | None, error: str | None) -> None:
        self.compare_button.setEnabled(True)
        if error or not data:
            self.analysis_status.setText(error or "历次对比读取失败")
            return
        summary = data.get("summary") or {}
        self.analysis_status.setText(
            f"对比完成：新增 {summary.get('new', 0)}，持续 {summary.get('continued', 0)}，"
            f"消失 {summary.get('resolved', 0)}，变化 {summary.get('changed', 0)}；"
            f"完整性：{'通过' if data.get('coverage_complete', True) else '未通过'}"
        )

    def load_complex_analysis(self) -> None:
        from urllib.parse import urlencode
        sites = ",".join(sorted(self.scope_bar.selected_sites))
        selected_unit = self.scope_bar.unit.currentData() or ""
        outage = self.analysis_outage.text().strip().upper()
        params = {
            "sites": sites,
            "unit": selected_unit,
            "outage": outage,
            "ndd_zero": int(self.visualization.ndd_zero),
        }
        self.complex_button.setEnabled(False)
        self.analysis_status.setText("正在计算趋势、相邻增量和覆盖质量...")
        self._analysis_request += 1
        number = self._analysis_request
        if not any((sites, selected_unit, outage)) and getattr(self, "_coverage_pending", False):
            self._unfiltered_analysis_number = number
            return
        self.client.get("/api/analysis/visualization?" + urlencode(params),
                        lambda data, error: self._complex_loaded(data, error)
                        if number == self._analysis_request else None)

    @staticmethod
    def _fill_table(table: QTableWidget, rows: list[list[Any]]) -> None:
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column, value in enumerate(row):
                table.setItem(row_index, column, QTableWidgetItem(
                    "" if value is None else str(value)
                ))
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)

    def _complex_loaded(self, data: dict[str, Any] | None, error: str | None) -> None:
        self.complex_button.setEnabled(self.permissions is None or "data.read" in self.permissions)
        if error or not data:
            self.analysis_status.setText(error or "复杂分析失败")
            self.complex_tabs.setVisible(False)
            return
        self.visualization.set_data(data)
        self._update_coverage()
        trends = data.get("trends") or []
        self._fill_table(self.trend_table, [[
            item.get("unit"), item.get("outage"), item.get("records", 0),
            item.get("wear_records", 0),
            item.get("total") if item.get("total") is not None else "未量化",
            item.get("missing_tubes", 0),
            "需核查" if item.get("partial") else "完整",
        ] for item in trends if isinstance(item, dict)])
        increments = data.get("increments") or []
        self._fill_table(self.increment_table, [[
            item.get("unit"), item.get("outage"), item.get("old_outage"),
            item.get("matched", 0),
            item.get("total") if item.get("total") is not None else "未计算",
            "需核查" if item.get("partial") else "可用",
        ] for item in increments if isinstance(item, dict)])
        coverage_rows = []
        for item in data.get("coverage") or []:
            counts = item.get("counts") or {}
            coverage_rows.append([
                item.get("unit"), item.get("outage"), counts.get("defect", 0),
                counts.get("NDD", 0),
                (counts.get("incomplete", 0) + counts.get("missing", 0)),
            ])
        self._fill_table(self.coverage_table, coverage_rows)
        quality = data.get("quality") or {}
        rule_versions = sorted({
            str((item.get("rules") or {}).get("version"))
            for item in increments if isinstance(item, dict) and (item.get("rules") or {}).get("version") is not None
        })
        self.quality_text.setPlainText(
            "数据来源："
            + str(data.get("source") or "当前数据库")
            + "\n\n"
            + "\n".join([
                f"无效大修号记录：{quality.get('invalid_outage_rows', 0)}",
                f"未解析磨损位置：{quality.get('unparsed_wear_positions', 0)}",
                f"磨损深度缺失/无效：{quality.get('unquantified_wear_rows', 0)}",
                f"跨数据组重复组：{quality.get('cross_group_duplicate_sets', 0)}",
                f"增量分析规则版本：{', '.join(rule_versions) if rule_versions else '无增量结果'}",
            ])
        )
        summary = data.get("summary") or {}
        self.analysis_status.setText(
            f"复杂分析完成：{summary.get('records', 0):,} 条记录，"
            f"{summary.get('units', 0)} 个机组，{summary.get('outages', 0)} 个大修，"
            f"缺失管 {summary.get('missing_tubes', 0)} 根。"
        )
        values = {"totalTubes": summary.get("expected_tubes", 0), "activeDefects": summary.get("records", 0),
                  "runningUnits": summary.get("units", 0), "activeOutages": summary.get("outages", 0)}
        depths = [tube["max_depth"] for snapshot in data.get("snapshots") or [] for tube in snapshot.get("tubes") or []
                  if isinstance(tube.get("max_depth"), (float, int))]
        values["maxWear"] = max(depths, default=0)
        for key, value in values.items():
            self.labels[key].setText(f"{value:,}")
        self.complex_tabs.setVisible(self.analysis_details.isChecked())

    def manage_analysis_rules(self) -> None:
        host = self.window()
        if hasattr(host, "open_settings"):
            host.open_settings(3)
            return
        self.client.get("/api/analysis-rules", self._rules_loaded)

    def _rules_loaded(self, data: dict[str, Any] | None, error: str | None) -> None:
        if error or not data:
            QMessageBox.warning(self, PRODUCT_NAME, error or "分析规则读取失败")
            return
        active = data.get("active") or {}
        history = data.get("items") or []
        text = (
            f"当前规则：v{active.get('version', 0)} · {active.get('name', '系统初始规则')}\n"
            f"轴向匹配容差：{active.get('match_tolerance_mm', 0.01)} mm\n"
            f"历史版本：{len(history)} 个\n\n"
            "规则只影响历次缺陷匹配和增量分析，不会修改原始检测记录。"
        )
        answer = QMessageBox.question(
            self, "分析规则", text + "\n\n是否建立新的规则版本？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        name, ok = QInputDialog.getText(self, "新规则版本", "规则名称", text="现场复核规则")
        if not ok or not name.strip():
            return
        tolerance, ok = QInputDialog.getDouble(
            self, "新规则版本", "轴向匹配容差（mm）", float(active.get("match_tolerance_mm", 0.01)),
            0.0001, 5.0, 4,
        )
        if not ok:
            return
        note, ok = QInputDialog.getText(self, "新规则版本", "规则备注", text="")
        if not ok:
            return
        self.client.post("/api/analysis-rules", {
            "name": name.strip(), "match_tolerance_mm": tolerance, "note": note.strip(),
        }, self._rule_saved)

    def _rule_saved(self, data: dict[str, Any] | None, error: str | None) -> None:
        if error or not data:
            QMessageBox.warning(self, PRODUCT_NAME, error or "分析规则保存失败")
            return
        settings = getattr(self.window(), "settings_dialog", None)
        if settings:
            self.client.get("/api/analysis-rules", settings._rules_loaded)
        self.load_complex_analysis()
        QMessageBox.information(
            self, PRODUCT_NAME,
            f"分析规则 v{data.get('version', '?')} 已启用；后续对比和复杂分析将使用新规则。",
        )


class NativeChartWindow(QDialog):
    def __init__(self, source, owner, key):
        from copy import deepcopy
        super().__init__(owner.window())
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.analytics_owner = owner
        self.client = source.client.fork(self)
        self.page = NativeAnalyticsPage(self.client, source.user, self)
        self.page.hide()
        self.panel = self.page.visualization.chart_panels[key]
        self.setWindowTitle(source.visualization.chart_panels[key].view.chart().title() or "独立图表")
        self.resize(1200, 800)
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        body.setObjectName("workspaceBody")
        content = QVBoxLayout(body)
        content.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(body)
        layout.addWidget(scroll)
        content.addWidget(self.page.filter_band)
        content.addWidget(self.page.analysis_status)
        content.addWidget(self.panel, 1)
        self.page.filter_band.show()
        self.panel.show()
        self.panel.setMaximumHeight(16777215)
        self.panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        history_handler = getattr(owner.window(), "_open_history_records", None)
        if history_handler:
            self.page.visualization.historyRecordsRequested.connect(history_handler)
        self.page.scope_bar.selected_sites = set(source.scope_bar.selected_sites)
        self.page.scope_bar._loaded({"combinations": deepcopy(source.scope_bar.combinations)}, None)
        scope = source.scope_bar.values()
        self.page.scope_bar.set_scope(scope, keep_sites=True)
        self.page.analysis_site.setText(scope.get("site") or "")
        self.page.analysis_unit.setValue(int(scope.get("unit") or 1))
        self.page.analysis_outage.setText(scope.get("outage") or "")
        self.page.visualization.ndd_zero = source.visualization.ndd_zero
        self.page.visualization.set_data(deepcopy(source.visualization.data))
        self.page.visualization.restore_view_state(source.visualization.view_state())
        self.page.analysis_status.setText(source.analysis_status.text())
        self._closed = False
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(80)
        self._refresh_timer.timeout.connect(self._reload)
        context = getattr(owner.window(), "context", None)
        if context:
            context.dataChanged.connect(self.refresh)
        self.apply_preferences()

    def apply_preferences(self):
        source = self.analytics_owner.visualization
        theme, animations = source.total.theme, source.total.animations
        self.page.visualization.set_theme(theme, animations)
        self.page.visualization.set_severity(source.severity_levels, source.severity_colors, source.severity_none)
        changed = self.page.visualization.set_analysis_options(source.ndd_zero, source.total.point_labels)
        for control in self.findChildren(QPushButton):
            if control.property("iconName"):
                control.setIcon(icon(control.property("iconName"), theme))
        if changed:
            self.refresh()

    def refresh(self):
        if not self._closed:
            self._refresh_timer.start()

    def _reload(self):
        if self._closed:
            return
        self.page.scope_bar.reload()
        self.page.load()
        self.page.load_complex_analysis()

    def done(self, result):
        self._closed = True
        self._refresh_timer.stop()
        self.client.abort_all()
        super().done(result)


class NativeReportsPage(QWidget):
    HEADER_FIELDS = (
        ("reportComponentNo", "设备/部件编号"), ("reportNo", "报告单编码"),
        ("reportPlant", "电厂名称"), ("reportInspection", "检查类型"),
        ("reportComponent", "设备/部件名称"), ("reportSafety", "安全等级"),
        ("reportRoom", "房间号"), ("reportScope", "检验范围"),
        ("reportMaterial", "材料"), ("reportSize", "尺寸"),
        ("reportInstrumentModel", "涡流仪型号"), ("reportInstrumentSerial", "涡流仪出厂编号"),
        ("reportCalibrationNo", "标定管编号"), ("reportProbeType", "探头类型"),
        ("reportProbeModel", "探头型号"), ("reportProbeSpec", "探头规格"),
        ("reportSpeed", "检验速度"), ("reportSampleRate", "采样率"),
        ("reportFrequency", "检验频率"), ("reportProcedure", "检验程序/版次"),
    )

    def __init__(self, client: NativeClient, user: dict[str, Any] | None = None, parent=None):
        super().__init__(parent)
        self.client = client
        self.permissions = None if user is None else set(user.get("permissions", []))
        self.snapshot_id: str | None = None
        self.preview_payload: dict[str, Any] | None = None
        self.template_catalog: list[dict[str, Any]] = []
        self.header_values = self._load_saved_header()
        self.draft_edits: list[dict[str, str]] = []
        self.editable_cells: list[dict[str, Any]] = []
        self._draft_history = []
        self._draft_source_changed = False
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(400)
        self._preview_timer.timeout.connect(self.preview_report)
        self._preview_number = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        self.report_tabs = QTabBar()
        self.report_tabs.addTab("检验报告单")
        self.report_tabs.addTab("检验结果比对表")
        report_top = QHBoxLayout()
        report_top.addWidget(self.report_tabs)
        report_top.addStretch()
        self.workbench_scope = button("工作台范围", "database", self._use_workbench_scope)
        report_top.addWidget(self.workbench_scope)
        layout.addLayout(report_top)
        self.scope_bar = ScopeBar(client, stacked=True)
        self.scope_bar.setObjectName("reportScopeBand")
        self.scope_bar.reset.hide()
        self.scope_bar.refresh.hide()
        for label in self.scope_bar.findChildren(QLabel):
            if label.text() == "大修":
                label.setText("本次大修")
        self.scope_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout.addWidget(self.scope_bar)
        self.scope_bar.changed.connect(self._scope_selected)
        self.site = QLineEdit()
        self.site.setPlaceholderText("例如 N")
        self.unit = QSpinBox()
        self.unit.setRange(0, 99)
        self.outage = QLineEdit()
        self.outage.setPlaceholderText("例如 N101")
        self.old_outage = QLineEdit()
        self.old_outage.setPlaceholderText("对比报告填写历史大修")
        self.kind = QComboBox()
        self.kind.addItem("检验报告单", "inspection")
        self.kind.addItem("检验结果比对表", "comparison")
        self.kind.currentIndexChanged.connect(self._select_template_for_kind)
        self.kind.hide()
        self.report_tabs.currentChanged.connect(self.kind.setCurrentIndex)
        self.kind.currentIndexChanged.connect(self.report_tabs.setCurrentIndex)
        self.history_combo = QComboBox()
        self.history_combo.setMinimumWidth(110)
        self.history_combo.setEditable(False)
        self.history_combo.currentTextChanged.connect(self.old_outage.setText)
        self.old_outage.hide()
        self.history_label = QLabel("历史大修")
        self.history_field = QWidget()
        history_layout = QVBoxLayout(self.history_field)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.setSpacing(5)
        history_layout.addWidget(self.history_label)
        history_layout.addWidget(self.history_combo)
        scope_layout = self.scope_bar.layout()
        scope_layout.insertWidget(3, self.history_field, 1)
        self.latest_outage = button("最新大修", None, self._latest_report_outage)
        self.latest_outage.setEnabled(False)
        scope_layout.insertWidget(4, self.latest_outage)
        for control in (self.site, self.unit, self.outage):
            control.hide()
        self.status = QLabel("正在读取报告模板...")
        self.status.setWordWrap(True)
        self.status.setObjectName("muted")
        layout.addWidget(self.status)
        self.count_toggle = button("数据库检测统计", "chevron-right")
        self.count_toggle.setCheckable(True)
        self.count_toggle.setEnabled(False)
        layout.addWidget(self.count_toggle)
        self.count_panel = QWidget()
        count_layout = QVBoxLayout(self.count_panel)
        count_layout.setContentsMargins(0, 0, 0, 0)
        self.count_table = QTableWidget(0, 5)
        self.count_table.setHorizontalHeaderLabels(
            ["数据库统计", "全部", "WAR", "仅 NDD 管 / NDD 记录", "其他 / 待确认"])
        self.count_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.count_table.verticalHeader().hide()
        self.count_table.horizontalHeader().setSectionResizeMode(
            self.count_table.horizontalHeader().ResizeMode.Stretch)
        self.count_table.setAccessibleName("数据库检测结论统计")
        count_layout.addWidget(self.count_table)
        self.count_note = QLabel()
        self.count_note.setWordWrap(True)
        self.count_note.setObjectName("muted")
        count_layout.addWidget(self.count_note)
        self.count_panel.hide()
        self.count_toggle.toggled.connect(self.count_panel.setVisible)
        layout.addWidget(self.count_panel)
        actions = QHBoxLayout()
        self.preview_heading = QLabel("检验报告单预览")
        actions.addWidget(self.preview_heading)
        actions.addStretch()
        self.preview = button("", "refresh-cw")
        self.preview.setToolTip("刷新报告")
        report_top.addWidget(self.preview)
        self.export = button("导出检验报告单", "file-down")
        self.export.setProperty("primary", True)
        self.export_format = QComboBox()
        self.export_format.addItem("Word (.docx)", "docx")
        self.export_format.addItem("Excel (.xlsx)", "xlsx")
        header = button("表头与设备信息", "clipboard-check")
        self.header_button = header
        self.edit_draft = QPushButton("修改草稿")
        self.edit_draft.setEnabled(False)
        self.edit_draft.clicked.connect(self.edit_report)
        self.use_selected = QCheckBox("仅使用工作台勾选记录")
        header.clicked.connect(self.edit_header)
        self.preview.clicked.connect(self.preview_report)
        self.export.clicked.connect(self.export_report)
        self.export_copy = button("另存副本", "file-down", self.save_export_copy)
        self.export_copy.setEnabled(False)
        self._last_export_path = None
        if self.permissions is not None and "export.create" not in self.permissions:
            self.export.setEnabled(False)
            self.export.setToolTip("当前账户没有报告导出权限")
        actions.addWidget(header)
        actions.addWidget(self.export_format)
        actions.addWidget(self.export)
        layout.addLayout(actions)
        self.header_panel = QScrollArea()
        self.header_panel.setWidgetResizable(True)
        self.header_panel.setMaximumHeight(300)
        header_host = QWidget()
        header_layout = QVBoxLayout(header_host)
        self.header_edits = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)
        for index, (key, caption) in enumerate(self.HEADER_FIELDS):
            field = QWidget()
            field_layout = QVBoxLayout(field)
            field_layout.setContentsMargins(0, 0, 0, 0)
            field_layout.setSpacing(4)
            field_layout.addWidget(QLabel(caption))
            edit = QLineEdit(self.header_values.get(key, ""))
            edit.setObjectName(key)
            edit.editingFinished.connect(self._save_inline_header)
            field_layout.addWidget(edit)
            self.header_edits[key] = edit
            grid.addWidget(field, index // 3, index % 3)
        header_layout.addLayout(grid)
        header_actions = QHBoxLayout()
        self.import_header_button = button("导入表头设置", "upload", self.import_header_settings)
        header_actions.addWidget(self.import_header_button)
        header_actions.addWidget(button("导出表头设置", "download", self.export_header_settings))
        header_actions.addStretch()
        header_layout.addLayout(header_actions)
        self.header_panel.setWidget(header_host)
        self.header_panel.hide()
        layout.addWidget(self.header_panel)
        self.templates = QListWidget()
        self.templates.currentItemChanged.connect(self._template_changed)
        self.templates.hide()
        tools = QHBoxLayout()
        from .native_report_view import ReportPreview, ReportWarnings
        self.preview_text = ReportPreview()
        self.preview_text.cellEdited.connect(self._inline_report_edit)
        tools.addWidget(button("", "chevron-left", lambda: self.preview_text.horizontalScrollBar().triggerAction(
            self.preview_text.horizontalScrollBar().SliderAction.SliderPageStepSub)))
        zoom_out = button("-", None, lambda: self.preview_text.set_zoom(self.preview_text.zoom - .1))
        zoom_out.setToolTip("缩小预览")
        tools.addWidget(zoom_out)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setMinimumWidth(42)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_text.zoomChanged.connect(lambda value: self.zoom_label.setText(f"{value:.0%}"))
        tools.addWidget(self.zoom_label)
        zoom_in = button("+", None, lambda: self.preview_text.set_zoom(self.preview_text.zoom + .1))
        zoom_in.setToolTip("放大预览")
        tools.addWidget(zoom_in)
        tools.addWidget(button("适宽", None, self.preview_text.fit_width))
        tools.addWidget(button("", "chevron-right", lambda: self.preview_text.horizontalScrollBar().triggerAction(
            self.preview_text.horizontalScrollBar().SliderAction.SliderPageStepAdd)))
        tools.addStretch()
        tools.addWidget(self.edit_draft)
        layout.addLayout(tools)
        document = QSplitter(Qt.Orientation.Horizontal)
        document.addWidget(self.preview_text)
        self.draft_panel = QWidget()
        self.draft_panel.setObjectName("reportDraftPanel")
        self.draft_panel.setMinimumWidth(250)
        draft_layout = QVBoxLayout(self.draft_panel)
        draft_layout.setContentsMargins(12, 12, 12, 12)
        draft_layout.addWidget(QLabel("报告修改草稿"))
        draft_actions = QHBoxLayout()
        self.draft_count = QLabel("人工修改 0 项")
        draft_actions.addWidget(self.draft_count, 1)
        self.draft_undo = button("", "rotate-ccw", self.undo_report_draft)
        self.draft_undo.setToolTip("撤销上次草稿修改")
        self.draft_reset = button("", "rotate-ccw", self.clear_report_draft)
        self.draft_reset.setToolTip("全部恢复")
        draft_actions.addWidget(self.draft_undo)
        draft_actions.addWidget(self.draft_reset)
        draft_layout.addLayout(draft_actions)
        self.draft_entries = QScrollArea()
        self.draft_entries.setWidgetResizable(True)
        draft_layout.addWidget(self.draft_entries, 1)
        self.draft_panel.hide()
        document.addWidget(self.draft_panel)
        document.setSizes([900, 300])
        document.setCollapsible(0, False)
        document.setCollapsible(1, False)
        self._render_report_draft()
        layout.addWidget(document, 1)
        self.sources_text = QPlainTextEdit()
        self.sources_text.setReadOnly(True)
        self.sources_text.setMaximumHeight(90)
        self.sources_text.hide()
        footer = ToolFlowLayout()
        footer.addWidget(button("来源追溯", "files", lambda: self.sources_text.setVisible(self.sources_text.isHidden())))
        footer.addWidget(self.use_selected)
        footer.addWidget(self.export_copy)
        layout.addLayout(footer)
        layout.addWidget(self.sources_text)
        self.warnings = ReportWarnings()
        layout.insertWidget(layout.indexOf(self.count_toggle), self.warnings)
        refresh = QPushButton("刷新模板")
        refresh.clicked.connect(self.load)
        refresh.hide()
        self.load()
        self.kind.currentIndexChanged.connect(self._report_mode_changed)
        self.scope_bar.loaded.connect(lambda _scope: self._populate_history())
        self.old_outage.textChanged.connect(self._report_history_changed)
        self.use_selected.toggled.connect(self._report_history_changed)
        self._report_mode_changed()

    def _invalidate_report(self):
        self._preview_timer.stop()
        self._preview_number += 1
        self.snapshot_id = None
        self.export.setEnabled(False)
        self.preview.setEnabled(True)
        self.edit_draft.setEnabled(False)
        self.draft_edits = []
        self._draft_history.clear()
        self.editable_cells = []
        self._render_report_draft()
        self.preview_text.clear_sources()
        self.preview_text.setPlainText("选择范围后生成报告预览")
        self._draft_source_changed = False

    def source_data_changed(self):
        self._preview_timer.stop()
        self._preview_number += 1
        self.snapshot_id = None
        self.export.setEnabled(False)
        self.preview.setEnabled(True)
        self._draft_source_changed = bool(self.draft_edits)
        self.status.setText("业务数据已更新；报告草稿已保留，请核对来源后更新预览" if self.draft_edits
                            else "业务数据已更新，请重新生成报告预览")

    def _report_mode_changed(self, *_):
        comparison = self.kind.currentData() == "comparison"
        self.use_selected.setEnabled(not comparison)
        self.use_selected.setVisible(not comparison)
        if comparison:
            self.use_selected.setChecked(False)
        self.header_button.setVisible(not comparison)
        if comparison:
            self.header_panel.hide()
        self.history_field.setVisible(comparison)
        self.export.setText("导出检验结果比对表" if comparison else "导出检验报告单")
        self.preview_heading.setText("检验结果比对表预览" if comparison else "检验报告单预览")
        self.history_combo.setEnabled(comparison and self.history_combo.count() > 1)
        self._invalidate_report()
        self._queue_report_preview()

    def _use_workbench_scope(self):
        owner = self.window()
        if hasattr(owner, "context"):
            self.set_workspace_scope(owner.context.scope)

    def _scope_selected(self, scope):
        before = (self.site.text(), self.unit.value(), self.outage.text())
        self.site.setText(str(scope.get("site") or ""))
        self.unit.setValue(int(scope.get("unit") or 0))
        self.outage.setText(str(scope.get("outage") or ""))
        if before == (self.site.text(), self.unit.value(), self.outage.text()):
            return
        self._populate_history()
        self._invalidate_report()
        self.status.setText("报告范围已更新，请生成预览")
        self._queue_report_preview()

    def _populate_history(self):
        scope = {"site": self.site.text(), "unit": self.unit.value(), "outage": self.outage.text()}
        previous = self.history_combo.currentText()
        self.history_combo.blockSignals(True)
        self.history_combo.clear()
        self.history_combo.addItem("")
        current_order = int(re.search(r"\d+$", scope["outage"])[0]) if re.search(r"\d+$", scope["outage"]) else 0
        for row in self.scope_bar.combinations:
            if (canonical_site(row.get("site")) == canonical_site(scope.get("site"))
                    and str(row.get("unit_id")) == str(scope.get("unit"))
                    and re.search(r"\d+$", row.get("outage", ""))
                    and int(re.search(r"\d+$", row["outage"])[0]) < current_order):
                self.history_combo.addItem(row["outage"])
        self.history_combo.setCurrentText(previous if self.history_combo.findText(previous) >= 0 else "")
        self.history_combo.blockSignals(False)
        self.old_outage.setText(self.history_combo.currentText())
        self.history_combo.setEnabled(self.kind.currentData() == "comparison" and self.history_combo.count() > 1)
        self.latest_outage.setEnabled(bool(scope["site"] and scope["unit"]
                                          and self.scope_bar.outage.count() > 1))

    def set_workspace_scope(self, scope):
        self.scope_bar.set_scope(scope)
        self._scope_selected(scope)

    def _inline_report_edit(self, key, value):
        original = next((cell for cell in self.editable_cells if cell["key"] == key), None)
        if original is None:
            self.status.setText("当前单元格已变化，请刷新报告")
            return
        changes = {edit["key"]: edit["value"] for edit in self.draft_edits}
        source = self._report_source_text(original)
        try:
            value = self._normalise_report_value(original, value)
        except ValueError as exc:
            self.preview_text.set_cell_value(key, changes.get(key, source), changed=key in changes)
            self.status.setText(str(exc))
            return
        remove = value == source
        if original.get("type") == "number":
            if value.strip() in {"", "/"} and source.strip() in {"", "/"}:
                remove = True
            elif re.fullmatch(r"[-+]?\d+(?:\.\d+)?", source.strip()) and value.strip() not in {"", "/", "-"}:
                remove = Decimal(value.strip()) == Decimal(source.strip())
        if remove:
            changes.pop(key, None)
        else:
            changes[key] = value
        edits = [{"key": k, "value": v} for k, v in sorted(changes.items())]
        if edits != self.draft_edits:
            self._remember_report_draft()
            self.draft_edits = edits
            self._report_draft_changed()
        else:
            self.preview_text.set_cell_value(key, changes.get(key, source), changed=key in changes)

    @staticmethod
    def _report_source_text(cell):
        value = cell.get("source_value", cell.get("value"))
        return "" if value is None else str(value)

    @staticmethod
    def _normalise_report_value(cell, value):
        value = "" if value is None else str(value)
        if len(value) > 2000:
            raise ValueError("单元格内容不能超过2000个字符")
        if cell.get("type") == "number":
            value = value.strip()
            if value not in {"", "/", "-"}:
                if not re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", value):
                    raise ValueError("请输入有效数字；缺失值使用 /")
                value = format(Decimal(value), "f")
                if "." in value:
                    value = value.rstrip("0").rstrip(".")
        return value

    def _remember_report_draft(self):
        self._draft_history.append([dict(edit) for edit in self.draft_edits])
        del self._draft_history[:-100]

    def _render_report_draft(self):
        self.draft_count.setText(f"人工修改 {len(self.draft_edits)} 项")
        self.draft_undo.setEnabled(bool(self._draft_history))
        self.draft_reset.setEnabled(bool(self.draft_edits))
        host = QWidget()
        host.setObjectName("reportDraftContents")
        host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        entries = QVBoxLayout(host)
        entries.setContentsMargins(0, 0, 0, 0)
        cells = {cell["key"]: cell for cell in self.editable_cells}
        for edit in self.draft_edits:
            key = edit["key"]
            cell = cells.get(key, {})
            entry = QWidget()
            entry.setObjectName("reportDraftEntry")
            body = QVBoxLayout(entry)
            body.setContentsMargins(4, 8, 4, 8)
            caption = QLabel(str(cell.get("label") or key))
            caption.setWordWrap(True)
            body.addWidget(caption)
            before = QLabel(self._report_source_text(cell) or "/")
            before.setTextFormat(Qt.TextFormat.PlainText)
            before.setObjectName("muted")
            font = before.font()
            font.setStrikeOut(True)
            before.setFont(font)
            before.setWordWrap(True)
            body.addWidget(before)
            after = QLabel(str(edit["value"]) if edit["value"] not in (None, "") else "/")
            after.setTextFormat(Qt.TextFormat.PlainText)
            after.setWordWrap(True)
            body.addWidget(after)
            actions = QHBoxLayout()
            locate = button("", "search", lambda _checked=False, k=key: self.preview_text.locate_cell(k))
            locate.setToolTip("定位到报告中的单元格")
            restore = button("", "rotate-ccw", lambda _checked=False, k=key: self.restore_report_cell(k))
            restore.setToolTip("恢复该单元格原值")
            actions.addWidget(locate)
            actions.addWidget(restore)
            actions.addStretch()
            body.addLayout(actions)
            entries.addWidget(entry)
        entries.addStretch()
        previous = self.draft_entries.takeWidget()
        self.draft_entries.setWidget(host)
        if previous is not None:
            previous.deleteLater()

    def _report_draft_changed(self):
        self.snapshot_id = None
        self.export.setEnabled(False)
        self._preview_number += 1
        self.preview.setEnabled(True)
        changes = {edit["key"]: edit["value"] for edit in self.draft_edits}
        for cell in self.editable_cells:
            key = cell["key"]
            self.preview_text.set_cell_value(key, changes.get(key, self._report_source_text(cell)),
                                             changed=key in changes)
        self._render_report_draft()
        self.status.setText(f"已修改 {len(changes)} 个单元格，正在同步报告草稿")
        self._queue_report_preview()

    def _queue_report_preview(self):
        if self._draft_source_changed:
            self.status.setText("来源数据已变化，草稿已保留；请核对来源后刷新报告")
        elif (self.site.text() and self.unit.value() and self.outage.text()
              and (self.kind.currentData() != "comparison" or self.old_outage.text())):
            self._preview_timer.start()

    def _report_history_changed(self, *_):
        self._invalidate_report()
        self._queue_report_preview()

    def _latest_report_outage(self):
        outages = [self.scope_bar.outage.itemData(i) for i in range(self.scope_bar.outage.count())
                   if self.scope_bar.outage.itemData(i)]
        if outages:
            latest = max(outages, key=lambda code: int(re.search(r"\d+$", code)[0])
                         if re.search(r"\d+$", code) else -1)
            self.scope_bar.outage.setCurrentIndex(self.scope_bar.outage.findData(latest))

    def undo_report_draft(self):
        if self._draft_history:
            self.draft_edits = self._draft_history.pop()
            self._report_draft_changed()

    def restore_report_cell(self, key):
        if any(edit["key"] == key for edit in self.draft_edits):
            self._remember_report_draft()
            self.draft_edits = [edit for edit in self.draft_edits if edit["key"] != key]
            self._report_draft_changed()

    @classmethod
    def _header_file(cls) -> Path:
        return USER_DATA / "report-header-settings.json"

    @classmethod
    def _load_saved_header(cls) -> dict[str, str]:
        values = {"reportComponent": "指套管"}
        try:
            payload = json.loads(cls._header_file().read_text(encoding="utf-8-sig"))
            fields = payload.get("fields")
            if payload.get("schema") != "thimble-report-header" or payload.get("version") != 1:
                return values
            if not isinstance(fields, dict):
                return values
            allowed = {key for key, _label in cls.HEADER_FIELDS}
            for key, value in fields.items():
                if key in allowed and isinstance(value, str):
                    values[key] = value
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return values

    def _save_header(self, values: dict[str, str]) -> None:
        payload = {
            "schema": "thimble-report-header",
            "version": 1,
            "fields": values,
        }
        try:
            USER_DATA.mkdir(parents=True, exist_ok=True)
            self._write_json(self._header_file(), payload)
        except OSError as exc:
            raise OSError(f"无法保存到 Qt 用户数据目录：{exc}") from exc

    @staticmethod
    def _write_json(path, payload):
        stream = QSaveFile(str(path))
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        if not stream.open(QIODevice.OpenModeFlag.WriteOnly):
            raise OSError(stream.errorString())
        if stream.write(raw) != len(raw) or not stream.commit():
            raise OSError(stream.errorString())

    def edit_header(self) -> None:
        self.header_panel.setVisible(self.header_panel.isHidden())

    def _save_inline_header(self):
        values = {key: edit.text() for key, edit in self.header_edits.items()}
        if values == self.header_values:
            return True
        try:
            self._save_header(values)
        except OSError as exc:
            self.status.setText(str(exc))
            return False
        self.header_values = values
        self.snapshot_id = None
        self._preview_number += 1
        self.status.setText("表头已保存，请更新预览")
        self._queue_report_preview()
        return True

    def import_header_settings(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择报告表头设置", "", "JSON (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            fields = data.get("fields")
            if data.get("schema") != "thimble-report-header" or data.get("version") != 1 or not isinstance(fields, dict):
                raise ValueError("不是受支持的报告表头设置文件")
            values = {key: fields.get(key, "") for key, _ in self.HEADER_FIELDS}
            if not all(isinstance(value, str) for value in values.values()):
                raise ValueError("表头字段必须是文本")
            self._save_header(values)
            self.header_values = values
            for key, edit in self.header_edits.items():
                edit.setText(values[key])
            self.snapshot_id = None
            self._preview_number += 1
            self.status.setText("表头设置已导入并保存，请更新预览")
            self._queue_report_preview()
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            QMessageBox.warning(self, PRODUCT_NAME, f"导入表头失败：{exc}")

    def export_header_settings(self):
        if not self._save_inline_header():
            return
        path, _ = QFileDialog.getSaveFileName(self, "保存报告表头设置", "报告表头设置.json", "JSON (*.json)")
        if path:
            try:
                self._write_json(path, {"schema": "thimble-report-header", "version": 1, "fields": self.header_values})
                self.status.setText("报告表头设置已导出")
            except OSError as exc:
                QMessageBox.warning(self, PRODUCT_NAME, str(exc))

    def edit_header_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("报告表头")
        dialog.resize(720, 760)
        layout = QVBoxLayout(dialog)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        groups = QVBoxLayout(host)
        scroll.setWidget(host)
        layout.addWidget(scroll, 1)
        edits = {}
        for title, fields in (("报告与部件", self.HEADER_FIELDS[:10]),
                              ("仪器与探头", self.HEADER_FIELDS[10:16]),
                              ("检验参数与程序", self.HEADER_FIELDS[16:])):
            group = QGroupBox(title)
            group.setCheckable(True)
            form = QFormLayout()
            body = QWidget()
            body.setLayout(form)
            QVBoxLayout(group).addWidget(body)
            group.toggled.connect(body.setVisible)
            for key, label in fields:
                edit = QLineEdit(self.header_values.get(key, ""))
                edits[key] = edit
                form.addRow(label, edit)
            groups.addWidget(group)
        import_button = QPushButton("导入表头设置")
        layout.addWidget(import_button)
        save_button = QPushButton("保存表头设置")
        layout.addWidget(save_button)

        def import_header() -> None:
            path, _ = QFileDialog.getOpenFileName(dialog, "选择报告表头设置", "", "JSON (*.json)")
            if not path:
                return
            try:
                data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
                fields = data.get("fields")
                if data.get("schema") != "thimble-report-header" or data.get("version") != 1 or not isinstance(fields, dict):
                    raise ValueError("不是受支持的报告表头设置文件")
                values = {}
                for key, edit in edits.items():
                    value = fields.get(key, "")
                    if not isinstance(value, str):
                        raise ValueError(f"表头字段 {key} 必须是文本")
                    values[key] = value
                for key, edit in edits.items():
                    value = values[key]
                    edit.setText(value)
            except (OSError, ValueError, TypeError, AttributeError) as exc:
                QMessageBox.warning(dialog, PRODUCT_NAME, f"导入表头失败：{exc}")

        import_button.clicked.connect(import_header)

        def save_header() -> None:
            path, _ = QFileDialog.getSaveFileName(
                dialog, "保存报告表头设置", "报告表头设置.json", "JSON (*.json)"
            )
            if not path:
                return
            payload = {
                "schema": "thimble-report-header",
                "version": 1,
                "fields": {key: edit.text() for key, edit in edits.items()},
            }
            try:
                self._write_json(path, payload)
                QMessageBox.information(dialog, PRODUCT_NAME, "报告表头设置已保存")
            except OSError as exc:
                QMessageBox.warning(dialog, PRODUCT_NAME, f"保存表头失败：{exc}")

        save_button.clicked.connect(save_header)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            values = {key: edit.text() for key, edit in edits.items()}
            try:
                self._save_header(values)
            except OSError as exc:
                QMessageBox.warning(dialog, PRODUCT_NAME, f"报告表头已应用到当前预览，但持久化失败：{exc}")
            self.header_values = values
            self.snapshot_id = None
            self._preview_number += 1
            self.status.setText("表头已保存，请更新预览")

    def load(self) -> None:
        self.status.setText("正在读取报告模板...")
        self.client.get("/api/reports/templates", self._templates_loaded)

    def _templates_loaded(self, data: dict[str, Any] | None, error: str | None) -> None:
        self.templates.clear()
        if error or not data:
            self.status.setText(error or "模板读取失败")
            return
        rows = data.get("items") or data.get("reports") or data.get("templates") or []
        if isinstance(rows, dict):
            rows = list(rows.values())
        for item in rows:
            if isinstance(item, dict):
                label = item.get("name") or item.get("title") or item.get("id") or item
                entry = QListWidgetItem(str(label))
                entry.setData(Qt.ItemDataRole.UserRole, item)
                self.templates.addItem(entry)
            else:
                label = item
                self.templates.addItem(str(label))
        self.template_catalog = [item for item in rows if isinstance(item, dict)]
        self._select_template_for_kind()
        self.status.setText(f"已加载 {len(rows)} 个报告模板")

    def _selected_template(self) -> dict[str, Any] | None:
        item = self.templates.currentItem()
        if item is not None:
            value = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(value, dict):
                return value
        wanted = self.kind.currentData()
        return next((item for item in self.template_catalog
                     if item.get("id") == wanted or item.get("mode") == wanted), None)

    def _template_changed(self, item: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        value = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(value, dict):
            return
        mode_index = self.kind.findData(value.get("mode"))
        if mode_index >= 0 and self.kind.currentIndex() != mode_index:
            self.kind.setCurrentIndex(mode_index)
            return
        formats = value.get("formats") or ["docx", "xlsx"]
        current = self.export_format.currentData()
        self.export_format.clear()
        for fmt in formats:
            self.export_format.addItem({"docx": "Word (.docx)", "xlsx": "Excel (.xlsx)"}.get(fmt, str(fmt).upper()), str(fmt))
        self.export_format.setCurrentIndex(max(0, self.export_format.findData(current)))

    def _select_template_for_kind(self, _index: int = -1) -> None:
        wanted = self.kind.currentData()
        for index in range(self.templates.count()):
            item = self.templates.item(index)
            value = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(value, dict) and (value.get("id") == wanted or value.get("mode") == wanted):
                self.templates.setCurrentRow(index)
                formats = value.get("formats") or ["docx", "xlsx"]
                current = self.export_format.currentData()
                self.export_format.blockSignals(True)
                self.export_format.clear()
                for fmt in formats:
                    self.export_format.addItem({"docx": "Word (.docx)", "xlsx": "Excel (.xlsx)"}.get(fmt, str(fmt).upper()), str(fmt))
                preferred = current if current in formats else formats[0]
                self.export_format.setCurrentIndex(max(0, self.export_format.findData(preferred)))
                self.export_format.blockSignals(False)
                return

    def _payload(self) -> dict[str, Any]:
        template = self._selected_template()
        template_id = (template or {}).get("id") or self.kind.currentData()
        payload = {
            "site": self.site.text().strip().upper(),
            "unit": self.unit.value(),
            "outage": self.outage.text().strip().upper(),
            "kind": self.kind.currentData(),
            "template_id": template_id,
            "metadata": {label: self.header_values.get(key, "") for key, label in self.HEADER_FIELDS},
            "draft_edits": self.draft_edits.copy(),
        }
        if self.kind.currentData() == "comparison":
            payload["old"] = self.old_outage.text().strip().upper()
            payload["metadata"] = {}
        if self.use_selected.isChecked():
            context = getattr(self.window(), "context", None)
            payload["finding_ids"] = list(context.selected) if context else []
            if not payload["finding_ids"]:
                payload["finding_ids"] = [-1]
        return payload

    def preview_report(self) -> None:
        self._preview_timer.stop()
        if getattr(self, "_draft_source_changed", False):
            answer = QMessageBox.question(self, "核对报告草稿",
                "来源数据已变化，当前草稿仍保留。确认将这些修改应用到当前来源并生成预览？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
            self._draft_source_changed = False
        if self.use_selected.isChecked():
            context = getattr(self.window(), "context", None)
            if not context or not context.selected:
                QMessageBox.warning(self, PRODUCT_NAME, "请先在工作台勾选当前范围的检测记录")
                return
        self.preview.setEnabled(False)
        self.snapshot_id = None
        self.export.setEnabled(False)
        self.edit_draft.setEnabled(False)
        self.preview_payload = self._payload()
        self._preview_number += 1
        number = self._preview_number
        self.status.setText("正在生成预览...")
        self.client.post("/api/reports/preview", self.preview_payload,
                         lambda data, error: self._accept_report_preview(number, data, error))

    def _accept_report_preview(self, number, data, error):
        if number != self._preview_number:
            return
        from PySide6.QtWidgets import QApplication
        focus = QApplication.focusWidget()
        if isinstance(focus, QPlainTextEdit) and self.preview_text.isAncestorOf(focus):
            QTimer.singleShot(80, self, lambda: self._accept_report_preview(number, data, error))
            return
        self._on_preview(data, error)

    def _on_preview(self, data: dict[str, Any] | None, error: str | None) -> None:
        self.preview.setEnabled(True)
        if error or not data:
            self.status.setText(error or "报告预览失败")
            self.preview_text.setPlainText(error or "报告预览失败")
            return
        self.snapshot_id = data.get("snapshot_id")
        self.export.setEnabled(data.get("coverage_complete") is not False
                               and (self.permissions is None or "export.create" in self.permissions))
        self.editable_cells = [cell for cell in data.get("editable_cells", [])
                               if isinstance(cell, dict) and cell.get("editable") and cell.get("key")]
        self.edit_draft.setEnabled(bool(self.editable_cells))
        self.preview_text.editable_keys = {cell["key"] for cell in self.editable_cells}
        self.preview_text.setHtml(str(data.get("html") or ""),
                                  source_values={cell["key"]: self._report_source_text(cell)
                                                 for cell in self.editable_cells},
                                  changed_keys={edit["key"] for edit in self.draft_edits})
        self._render_report_draft()
        counts = data.get("detection_counts") or []
        self.count_toggle.setEnabled(bool(counts))
        self.count_toggle.setText(f"数据库检测统计  {len(counts)} 次大修")
        self.count_table.setRowCount(len(counts))
        for index, scope in enumerate(counts):
            values = [f"{'本次' if index == 0 else '历史'} {scope.get('outage', '')}",
                      f"{scope.get('tubes', 0)} 根 / {scope.get('records', 0)} 条"]
            values.extend(f"{scope.get(kind + '_tubes', 0)} 根 / {scope.get(kind + '_records', 0)} 条"
                          for kind in ("war", "ndd", "other"))
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column >= 2:
                    kind = ("war", "ndd", "other")[column - 2]
                    cell.setToolTip("、".join(map(str, (scope.get("tube_ids") or {}).get(kind, []))))
                self.count_table.setItem(index, column, cell)
        self.count_table.setFixedHeight(34 + 30 * len(counts))
        mixed = "；".join(f"{scope['outage']}：{'、'.join(map(str, scope['mixed_ndd_tubes']))}号管同时含 NDD 与其他记录"
                         for scope in counts if scope.get("mixed_ndd_tubes"))
        rules = data.get("rules") or {}
        rule_note = (f"；匹配规则 v{rules.get('version', 0)}（{rules.get('name', '')}），"
                     f"容差 ±{rules.get('match_tolerance_mm', '')} mm" if data.get("kind") == "comparison" else "")
        self.count_note.setText("管数按 WAR、其他、仅 NDD 依次归类；记录数逐条统计"
                                + ("；" + mixed if mixed else "") + rule_note
                                + ("。报告草稿另有人工修改，以上统计以数据库为准。" if self.draft_edits else "。"))
        self.count_panel.setVisible(bool(counts) and self.count_toggle.isChecked())
        self.sources_text.setPlainText("\n".join(" | ".join("" if value is None else str(value) for value in row)
                                                for row in data.get("sources", [])))
        warnings = data.get("warnings") or []
        self.warnings.set_warnings(warnings, scope=(self.kind.currentData(), self.site.text(),
                                                  self.unit.value(), self.outage.text(), self.old_outage.text()))
        self.status.setText(
            f"报告预览已生成，{data.get('rows', 0)} 行，{len(warnings)} 条核查提示"
            + ("；50根管完整性未通过，不能导出" if data.get("coverage_complete") is False else "")
        )

    def edit_report(self) -> None:
        opened = self.draft_panel.isHidden()
        self.draft_panel.setVisible(opened)
        self.edit_draft.setText("收起草稿" if opened else "修改草稿")

    def clear_report_draft(self) -> None:
        if self.draft_edits:
            self._remember_report_draft()
            self.draft_edits = []
            self._report_draft_changed()

    def export_report(self) -> None:
        if not self.snapshot_id or self.preview_payload != self._payload():
            QMessageBox.warning(self, PRODUCT_NAME, "请先按当前条件生成报告预览，再执行导出。")
            return
        self.export.setEnabled(False)
        self.status.setText("正在导出报告...")
        self.client.post("/api/reports/export",
                         {**self.preview_payload, "snapshot_id": self.snapshot_id,
                          "format": self.export_format.currentData()},
                         self._on_export)

    def _on_export(self, data: dict[str, Any] | None, error: str | None) -> None:
        self.export.setEnabled(self.permissions is None or "export.create" in self.permissions)
        if error or not data:
            self.status.setText(error or "报告导出失败")
            QMessageBox.warning(self, PRODUCT_NAME, error or "报告导出失败")
            return
        path = data.get("file_path") or data.get("path") or data.get("file") or data.get("output")
        self._last_export_path = Path(path) if isinstance(path, str) and Path(path).is_file() else None
        self.export_copy.setEnabled(self._last_export_path is not None)
        self.status.setText(f"报告已导出：{path or '已生成'}")
        QMessageBox.information(self, PRODUCT_NAME, f"报告已导出\n{path or data}")

    def save_export_copy(self):
        source = self._last_export_path
        if source is None or not source.is_file():
            self.status.setText("请先导出报告")
            return
        target, _ = QFileDialog.getSaveFileName(self, "另存报告副本", source.name,
                                               f"{source.suffix[1:].upper()} (*{source.suffix})")
        if not target:
            return
        def authorized(data, error):
            user = (data or {}).get("user") or {}
            if error or "export.create" not in user.get("permissions", []):
                self.status.setText(error or "当前账户没有导出权限")
                return
            try:
                content = source.read_bytes()
                output = QSaveFile(target)
                if (not output.open(QIODevice.OpenModeFlag.WriteOnly)
                        or output.write(content) != len(content) or not output.commit()):
                    raise OSError(output.errorString())
                self.status.setText(f"报告副本已保存：{target}")
            except OSError as exc:
                self.status.setText(f"报告另存失败：{exc}")
        self.client.get("/api/auth/me", authorized)


class RecordTableModel(QAbstractTableModel):
    """Read-only API records; independent of workbench selection/edit columns."""

    def __init__(self, columns, parent=None):
        super().__init__(parent)
        self.columns, self.rows = columns, []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            value = self.rows[index.row()].get(self.columns[index.column()][0])
            return "" if value is None else str(value)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            return self.columns[section][1] if orientation == Qt.Orientation.Horizontal else section + 1
        return None

    def replace(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()


class JsonTablePage(QWidget):
    """Small native table adapter for API-backed maintenance views."""
    contextRequested = Signal(dict)

    def __init__(self, client: NativeClient, title: str, endpoint: str, columns: list[tuple[str, str]], parent=None,
                 *, permissions=None):
        super().__init__(parent)
        self.client = client
        self.endpoint = endpoint
        required = {"/api/backups": "backup.manage", "/api/recycle-bin/list": "data.delete",
                    "/api/operation-logs": "audit.read", "/api/logs/recent": "audit.read",
                    "/api/security/events": "audit.read", "/api/security/exports": "audit.read",
                    "/api/schema-migrations": "audit.read"}.get(endpoint.split("?")[0], "data.read")
        self.allowed = permissions is None or required in permissions
        self.columns = columns
        self.rows: list[dict[str, Any]] = []
        self.page = 1
        self.page_size = 100
        self.total = 0
        self._request_number = 0
        self.paged = endpoint.split("?")[0] in {
            "/api/data-quality", "/api/recycle-bin/list", "/api/operation-logs",
            "/api/import-batches", "/api/validation-issues", "/api/security/events",
            "/api/security/exports", "/api/schema-migrations"}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        actions = QHBoxLayout()
        self.refresh = QPushButton("刷新")
        self.refresh.clicked.connect(self.load)
        actions.addWidget(self.refresh)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索当前页")
        self.search.textChanged.connect(self._filter_rows)
        actions.addWidget(self.search)
        if endpoint.startswith("/api/data-quality"):
            self.batch_filter = QLineEdit()
            self.batch_filter.setPlaceholderText("批次编号")
            self.batch_filter.setMaximumWidth(100)
            self.category_filter = QComboBox()
            self.category_filter.addItem("全部类别", "")
            self.batch_filter.returnPressed.connect(self._apply_filter)
            self.category_filter.currentIndexChanged.connect(self._apply_filter)
            actions.addWidget(self.batch_filter)
            actions.addWidget(self.category_filter)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.table = QTableView()
        self.model = RecordTableModel(columns, self)
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        self.table.doubleClicked.connect(self.show_detail)
        pager = QHBoxLayout()
        self.previous = button("上一页", "chevron-left", lambda: self.change_page(-1))
        self.next_page = button("下一页", "chevron-right", lambda: self.change_page(1))
        self.page_label = QLabel()
        pager.addStretch()
        pager.addWidget(self.previous)
        pager.addWidget(self.page_label)
        pager.addWidget(self.next_page)
        layout.addLayout(pager)
        self.status = QLabel("正在加载...")
        self.status.setObjectName("muted")
        layout.addWidget(self.status)
        self.load()

    def load(self) -> None:
        from urllib.parse import parse_qs, urlencode, urlsplit
        if not self.allowed:
            self.status.setText("当前账户没有读取权限")
            self.refresh.setEnabled(False)
            self.previous.setEnabled(False)
            self.next_page.setEnabled(False)
            return
        self.status.setText("正在加载...")
        url = urlsplit(self.endpoint)
        params = {key: values[0] for key, values in parse_qs(url.query).items()}
        if self.paged:
            params.update(page=self.page, size=self.page_size)
        if hasattr(self, "batch_filter"):
            batch = self.batch_filter.text().strip()
            if batch and not batch.isdigit():
                self.status.setText("批次编号必须是正整数")
                return
            params.update(batch_id=batch, category=self.category_filter.currentData() or "")
        self._request_number += 1
        number = self._request_number
        self.client.get(url.path + ("?" + urlencode(params) if params else ""),
                        lambda data, error: self._loaded(data, error) if number == self._request_number else None)

    def _apply_filter(self, *_):
        self.page = 1
        self.load()

    def change_page(self, delta):
        self.page = max(1, min(max(1, (self.total + self.page_size - 1) // self.page_size), self.page + delta))
        self.load()

    def _filter_rows(self, *_):
        text = self.search.text().strip().casefold()
        rows = [row for row in self.rows if not text or text in json.dumps(row, ensure_ascii=False).casefold()]
        self.model.replace(rows)

    def show_detail(self, index):
        if not index.isValid() or index.row() >= len(self.model.rows):
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("记录详情与来源")
        dialog.resize(780, 560)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        record = self.model.rows[index.row()]
        text.setPlainText(json.dumps(record, ensure_ascii=False, indent=2))
        layout.addWidget(text)
        actions = QHBoxLayout()
        scope = self.record_scope(record)
        contexts = record.get("contexts") or []
        if not scope and len(contexts) > 1:
            targets = QComboBox()
            for item in contexts:
                target = self.record_scope(item)
                if target:
                    targets.addItem(f"{target['site']} · {target['unit']}号机 · {target['outage']}", target)
            if targets.count():
                actions.addWidget(targets)
                actions.addWidget(button("定位检测范围", "database",
                                         lambda: (dialog.accept(), self.contextRequested.emit(targets.currentData()))))
        if scope:
            actions.addWidget(button("定位检测范围", "database",
                                     lambda: (dialog.accept(), self.contextRequested.emit(scope))))
        source = record.get("source_path") or record.get("report_path")
        if isinstance(source, str) and Path(source).is_file():
            from PySide6.QtGui import QDesktopServices
            actions.addWidget(button("打开来源文件", "files",
                                     lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(source))))
        actions.addStretch()
        actions.addWidget(button("关闭", "x", dialog.accept))
        layout.addLayout(actions)
        dialog.exec()

    @staticmethod
    def record_scope(record):
        candidates = [record]
        if isinstance(record.get("contexts"), list) and len(record["contexts"]) == 1:
            candidates.extend(record["contexts"])
        for key in ("after_json", "before_json", "details_json", "details"):
            value = record.get(key)
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except ValueError:
                    continue
            if isinstance(value, dict):
                candidates.append(value)
        for row in candidates:
            outage = row.get("outage")
            unit = row.get("unit_id") or row.get("unit")
            if outage and unit:
                return {"site": canonical_site(row.get("site") or re.sub(r"\d.*", "", str(outage))),
                        "unit": str(unit), "outage": str(outage),
                        "thimble": str(row.get("thimble_id") or row.get("tube") or "")}
        return None

    def _loaded(self, data: dict[str, Any] | None, error: str | None) -> None:
        if error or not data:
            self.status.setText(error or "读取失败")
            self.model.replace([])
            return
        rows = data.get("issues") if self.endpoint.startswith("/api/data-quality") else data.get("items")
        rows = rows or data.get("logs") or []
        if isinstance(rows, dict):
            rows = list(rows.values())
        self.rows = [row for row in rows if isinstance(row, dict)]
        self._filter_rows()
        total = (data.get("totals") or {}).get("issues", data.get("total", data.get("count", len(self.rows))))
        self.total = int(total or 0)
        pages = max(1, (self.total + self.page_size - 1) // self.page_size)
        self.page_label.setText(f"{self.page} / {pages}")
        self.previous.setEnabled(self.paged and self.page > 1)
        self.next_page.setEnabled(self.paged and self.page < pages)
        if hasattr(self, "category_filter"):
            previous = self.category_filter.currentData()
            self.category_filter.blockSignals(True)
            self.category_filter.clear()
            self.category_filter.addItem("全部类别", "")
            for code in data.get("codes") or []:
                self.category_filter.addItem(code, code)
            self.category_filter.setCurrentIndex(max(0, self.category_filter.findData(previous)))
            self.category_filter.blockSignals(False)
        self.status.setText(f"已加载 {len(self.rows):,} 条，共 {total:,} 条")


class NativeMaintenancePage(QWidget):
    """Native replacement for data-quality, recycle-bin, audit and backups."""

    def __init__(self, client: NativeClient, user: dict[str, Any] | None = None, parent=None):
        super().__init__(parent)
        self.client = client
        self.permissions = None if user is None else set(user.get("permissions", []))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        title = QLabel("数据质量与维护")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        self.tabs = QTabWidget()
        self.quality = JsonTablePage(client, "数据质量", "/api/data-quality?page=1&size=100",
                                     [("id", "编号"), ("code", "类别"), ("message", "说明"), ("sheet_name", "工作表")])
        self.batches = JsonTablePage(client, "导入批次", "/api/import-batches",
                                     [("id", "批次"), ("started_at", "时间"), ("source_path", "来源"),
                                      ("rows_inserted", "新增"), ("rows_skipped", "跳过"),
                                      ("error_count", "问题"), ("status", "状态")])
        self.recycle = JsonTablePage(client, "回收站", "/api/recycle-bin/list?page=1&size=100",
                                     [("id", "批次"), ("scope_label", "范围"), ("record_count", "记录数"), ("deleted_at", "删除时间"), ("backup_file", "备份")],
                                     permissions=self.permissions)
        self.audit = JsonTablePage(client, "操作审计", "/api/operation-logs?page=1&size=100",
                                   [("id", "编号"), ("operation_type", "操作"), ("scope_detail", "范围"), ("record_count", "记录数"), ("operator", "操作人"), ("created_at", "时间")],
                                   permissions=self.permissions)
        self.validation = JsonTablePage(client, "校验问题", "/api/validation-issues",
                                        [("code", "类别"), ("severity", "级别"), ("message", "说明"),
                                         ("source_path", "来源"), ("sheet_name", "工作表"), ("row_number", "原始行")])
        self.tabs.addTab(self.quality, "数据质量")
        self.tabs.addTab(self.batches, "导入批次")
        self.tabs.addTab(self.recycle, "回收站")
        self.tabs.addTab(self.audit, "操作审计")
        self.tabs.addTab(self.validation, "校验问题")
        from .native_review import CrossGroupReviewPage
        self.cross_review = CrossGroupReviewPage(client, self.permissions)
        self.tabs.addTab(self.cross_review, "跨组复核")
        self.security_events = JsonTablePage(client, "账户与访问审计", "/api/security/events",
                                            [("created_at", "时间"), ("operator", "账户"), ("event_type", "事件"),
                                             ("outcome", "结果"), ("resource", "资源")], permissions=self.permissions)
        self.export_audits = JsonTablePage(client, "导出校验台账", "/api/security/exports",
                                          [("created_at", "时间"), ("operator", "账户"), ("resource", "资源"),
                                           ("sha256", "SHA-256"), ("size_bytes", "大小")], permissions=self.permissions)
        self.tabs.addTab(self.security_events, "安全审计")
        self.tabs.addTab(self.export_audits, "导出校验")
        layout.addWidget(self.tabs, 1)
        actions = ToolFlowLayout()
        self.restore = QPushButton("恢复选中回收批次")
        self.purge = QPushButton("永久删除选中回收批次")
        self.restore.clicked.connect(lambda: self._recycle_action("restore"))
        self.purge.clicked.connect(lambda: self._recycle_action("purge"))
        if self.permissions is not None:
            self.restore.setEnabled("data.delete" in self.permissions)
            self.purge.setEnabled("data.purge" in self.permissions)
            if "data.delete" not in self.permissions:
                self.restore.setToolTip("当前账户没有回收站恢复权限")
            if "data.purge" not in self.permissions:
                self.purge.setToolTip("当前账户没有永久删除权限")
        actions.addWidget(self.restore)
        actions.addWidget(self.purge)
        self.quality_export = button("导出质量与来源台账", "file-down", self.export_quality)
        self.quality_export.setEnabled(self.permissions is None or "export.create" in self.permissions)
        actions.addWidget(self.quality_export)
        self.audit_export = button("导出完整审计台账", "file-down", self.export_audit)
        self.audit_export.setEnabled(self.permissions is None or {"audit.read", "export.create"} <= self.permissions)
        actions.addWidget(self.audit_export)
        for label, action in (("回滚导入批次", "rollback"), ("恢复导入批次", "restore")):
            control = button(label, "archive-restore", lambda _, value=action: self.batch_action(value))
            control.setEnabled(self.permissions is None or "data.delete" in self.permissions)
            actions.addWidget(control)
        self.batches.table.clicked.connect(self._select_batch)
        layout.addLayout(actions)

    def _select_batch(self, index):
        if index.isValid() and index.row() < len(self.batches.model.rows):
            self.quality.batch_filter.setText(str(self.batches.model.rows[index.row()]["id"]))

    def export_quality(self):
        batch = self.quality.batch_filter.text().strip()
        if batch and not batch.isdigit():
            self.quality.status.setText("批次编号必须是正整数")
            return
        self.client.post("/api/data-quality/export", {"batch_id": int(batch) if batch else None,
                         "category": self.quality.category_filter.currentData() or ""},
                         lambda data, error: self.quality.status.setText(
                             error or f"质量台账已导出：{(data or {}).get('file_path') or (data or {}).get('path') or ''}"))

    def export_audit(self):
        self.client.post("/api/audits/export", {}, lambda data, error: self.audit.status.setText(
            error or f"完整审计已导出：{(data or {}).get('file_path') or ''}"))

    def batch_action(self, action):
        index = self.batches.table.currentIndex()
        if not index.isValid() or index.row() >= len(self.batches.model.rows):
            QMessageBox.information(self, PRODUCT_NAME, "请先选择导入批次")
            return
        batch = self.batches.model.rows[index.row()]
        if QMessageBox.question(self, PRODUCT_NAME, f"确认{'回滚' if action == 'rollback' else '恢复'}批次 {batch['id']}？"
                                 "操作前自动备份，存在后续修改时将拒绝执行。") != QMessageBox.StandardButton.Yes:
            return
        self.client.post("/api/import-batches/action", {"batch_id": batch["id"], "action": action},
                         self._batch_done)

    def _batch_done(self, data, error):
        if error:
            QMessageBox.warning(self, PRODUCT_NAME, error)
            return
        for page in (self.batches, self.quality, self.audit, self.validation):
            page.load()

    def _recycle_action(self, action: str) -> None:
        index = self.recycle.table.currentIndex()
        if not index.isValid() or index.row() >= len(self.recycle.rows):
            QMessageBox.information(self, PRODUCT_NAME, "请先在回收站选择一个批次")
            return
        selected = self.recycle.model.rows[index.row()]
        batch_id = selected.get("batch_id") or selected.get("id")
        if action == "purge" and QMessageBox.warning(
            self, PRODUCT_NAME, "永久删除后无法恢复，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        endpoint = f"/api/recycle-bin/{action}"
        button = self.restore if action == "restore" else self.purge
        button.setEnabled(False)
        self.client.post(endpoint, {"batchId": batch_id}, lambda data, error: self._after_recycle(action, data, error))

    def _after_recycle(self, action: str, data: dict[str, Any] | None, error: str | None) -> None:
        self.restore.setEnabled(self.permissions is None or "data.delete" in self.permissions)
        self.purge.setEnabled(self.permissions is None or "data.purge" in self.permissions)
        if error:
            QMessageBox.warning(self, PRODUCT_NAME, error)
            return
        QMessageBox.information(self, PRODUCT_NAME, "回收站操作已完成")
        self.recycle.load()
        self.audit.load()


class NativeSettingsPage(QWidget):
    logoutRequested = Signal()

    def __init__(self, client: NativeClient, user: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.user = user
        permissions = set(user.get("permissions", []))
        self.roles: list[dict[str, str]] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        title = QLabel("设置与系统维护")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        self.tabs = QTabWidget()
        self.account = QWidget()
        account_layout = QFormLayout(self.account)
        account_layout.addRow("当前账户", QLabel(str(user.get("username", ""))))
        account_layout.addRow("显示名称", QLabel(str(user.get("display_name", ""))))
        account_layout.addRow("权限", QLabel("、".join(user.get("permissions", [])) or "无"))
        self.logout = QPushButton("退出登录")
        self.logout.clicked.connect(self.logoutRequested)
        account_layout.addRow("", self.logout)
        self.change_password = QPushButton("修改当前密码")
        self.change_password.clicked.connect(self.change_current_password)
        account_layout.addRow("", self.change_password)
        self.users_table = QTableWidget(0, 5)
        self.users_table.setHorizontalHeaderLabels(["用户名", "显示名称", "角色", "状态", "最近登录"])
        self.users_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.users_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.users_table.horizontalHeader().setStretchLastSection(True)
        account_layout.addRow("本地账户", self.users_table)
        user_actions = QHBoxLayout()
        self.user_add = QPushButton("新建账户")
        self.user_edit = QPushButton("编辑选中账户")
        self.user_add.clicked.connect(lambda: self.edit_user())
        self.user_edit.clicked.connect(self.edit_selected_user)
        user_actions.addWidget(self.user_add)
        user_actions.addWidget(self.user_edit)
        user_actions.addStretch(1)
        account_layout.addRow("", user_actions)
        self.user_hint = QLabel("")
        self.user_hint.setObjectName("muted")
        account_layout.addRow("", self.user_hint)
        from .native_settings_layout import SettingsStoragePanel
        self.source = SettingsStoragePanel(self)
        self._source_serial = 0
        self._source_busy = False
        self.backups = JsonTablePage(client, "数据库备份", "/api/backups",
                                     [("name", "备份名称"), ("created_at", "时间"), ("size_bytes", "大小"), ("path", "路径"), ("note", "备注")],
                                     permissions=permissions)
        backup_actions = QHBoxLayout()
        self.backup_now = QPushButton("立即备份")
        self.backup_now.clicked.connect(self.create_backup)
        self.restore_backup = QPushButton("恢复选中备份")
        self.restore_backup.clicked.connect(self.validate_backup)
        backup_actions.addWidget(self.backup_now)
        backup_actions.addWidget(self.restore_backup)
        self.backup_now.setEnabled("backup.manage" in user.get("permissions", []))
        self.restore_backup.setEnabled("database.restore" in user.get("permissions", []))
        if not self.backup_now.isEnabled():
            self.backup_now.setToolTip("当前账户没有备份管理权限")
        if not self.restore_backup.isEnabled():
            self.restore_backup.setToolTip("当前账户没有恢复数据库权限")
        backup_actions.addStretch(1)
        backup_host = QWidget()
        backup_layout = QVBoxLayout(backup_host)
        backup_layout.addWidget(self.backups)
        backup_layout.addLayout(backup_actions)
        self.logs = JsonTablePage(client, "服务日志", "/api/logs/recent?limit=200",
                                  [("time", "时间"), ("level", "级别"), ("message", "消息")], permissions=permissions)
        self.tabs.addTab(self.account, "账户与权限")
        self.tabs.addTab(self.source, "数据存储")
        self.tabs.addTab(backup_host, "备份与恢复")
        self.tabs.addTab(self.logs, "运行日志")
        layout.addWidget(self.tabs, 1)
        self.load_source()
        self._set_user_management_enabled("users.manage" in user.get("permissions", []))
        if "users.manage" in user.get("permissions", []):
            self.load_users()

    def _set_user_management_enabled(self, enabled: bool) -> None:
        self.users_table.setVisible(enabled)
        self.user_add.setVisible(enabled)
        self.user_edit.setVisible(enabled)
        self.user_hint.setText("" if enabled else "当前账户没有本地账户管理权限。")

    def change_current_password(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("修改当前密码")
        form = QFormLayout(dialog)
        current = QLineEdit()
        new = QLineEdit()
        confirm = QLineEdit()
        for edit in (current, new, confirm):
            edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("当前密码", current)
        form.addRow("新密码", new)
        form.addRow("确认新密码", confirm)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if not current.text() or len(new.text()) < 6 or new.text() != confirm.text():
            QMessageBox.warning(self, PRODUCT_NAME, "新密码至少 6 位，且两次输入必须一致")
            return
        self.change_password.setEnabled(False)
        self.client.post("/api/auth/password", {
            "current_password": current.text(),
            "password": new.text(),
        }, self._password_changed)

    def _password_changed(self, data: dict[str, Any] | None, error: str | None) -> None:
        self.change_password.setEnabled(True)
        if error or not data:
            QMessageBox.warning(self, PRODUCT_NAME, error or "密码修改失败")
            return
        QMessageBox.information(self, PRODUCT_NAME, "密码已修改，请使用新密码重新登录。")
        self.logoutRequested.emit()

    def load_users(self) -> None:
        self.client.get("/api/auth/users", self._users_loaded)

    def _users_loaded(self, data: dict[str, Any] | None, error: str | None) -> None:
        if error or not data:
            self.user_hint.setText(error or "账户列表读取失败")
            return
        self.roles = [item for item in data.get("roles", []) if isinstance(item, dict)]
        users = [item for item in data.get("users", []) if isinstance(item, dict)]
        self.users_table.setRowCount(len(users))
        for row, item in enumerate(users):
            values = (
                item.get("username", ""),
                item.get("display_name", ""),
                "、".join(item.get("roles", [])),
                "启用" if item.get("active") else "停用",
                item.get("last_login") or "尚未登录",
            )
            for column, value in enumerate(values):
                self.users_table.setItem(row, column, QTableWidgetItem(str(value)))
            self.users_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, item)
        self.user_hint.setText(f"共 {len(users)} 个本地账户")

    def _role_codes(self) -> list[str]:
        return [str(item.get("code")) for item in self.roles if item.get("code")]

    def edit_selected_user(self) -> None:
        index = self.users_table.currentRow()
        if index < 0 or not self.users_table.item(index, 0):
            QMessageBox.information(self, PRODUCT_NAME, "请先选择账户")
            return
        user = self.users_table.item(index, 0).data(Qt.ItemDataRole.UserRole) or {}
        self.edit_user(user)

    def edit_user(self, existing: dict[str, Any] | None = None) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("编辑本地账户" if existing else "新建本地账户")
        dialog.resize(500, 480)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        username = QLineEdit(str((existing or {}).get("username", "")))
        username.setReadOnly(existing is not None)
        display = QLineEdit(str((existing or {}).get("display_name", "")))
        password = QLineEdit()
        password.setEchoMode(QLineEdit.EchoMode.Password)
        password.setPlaceholderText("新建必填；编辑时留空表示不修改")
        active = QCheckBox("账户启用")
        active.setChecked(bool((existing or {}).get("active", True)))
        form.addRow("用户名", username)
        form.addRow("显示名称", display)
        form.addRow("密码", password)
        form.addRow("", active)
        layout.addLayout(form)
        roles = QListWidget()
        selected_roles = set((existing or {}).get("roles", []))
        role_items = self.roles or [
            {"code": "admin", "label": "系统管理员"},
            {"code": "importer", "label": "数据导入员"},
            {"code": "editor", "label": "数据编辑员"},
            {"code": "reviewer", "label": "审核员"},
            {"code": "reporter", "label": "报告用户"},
            {"code": "viewer", "label": "只读用户"},
        ]
        for item in role_items:
            code = str(item.get("code") or "")
            entry = QListWidgetItem(f"{item.get('label', code)} ({code})")
            entry.setData(Qt.ItemDataRole.UserRole, code)
            entry.setFlags(entry.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            entry.setCheckState(Qt.CheckState.Checked if code in selected_roles else Qt.CheckState.Unchecked)
            roles.addItem(entry)
        layout.addWidget(QLabel("角色（至少选择一个）"))
        layout.addWidget(roles, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected = [
            roles.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(roles.count())
            if roles.item(index).checkState() == Qt.CheckState.Checked
        ]
        if not selected or not display.text().strip() or (not existing and not password.text()):
            QMessageBox.warning(self, PRODUCT_NAME, "请填写显示名称、密码并至少选择一个角色")
            return
        payload: dict[str, Any] = {
            "username": username.text().strip(),
            "display_name": display.text().strip(),
            "roles": selected,
            "active": active.isChecked(),
        }
        if password.text():
            payload["password"] = password.text()
        endpoint = "/api/auth/users/update" if existing else "/api/auth/users"
        if existing:
            payload["id"] = existing.get("id")
        self.client.post(endpoint, payload, self._user_saved)

    def _user_saved(self, data: dict[str, Any] | None, error: str | None) -> None:
        if error or not data:
            QMessageBox.warning(self, PRODUCT_NAME, error or "账户保存失败")
            return
        self.load_users()

    def load_source(self) -> None:
        if self._source_busy:
            return
        self._source_busy = True
        self._source_serial += 1
        serial = self._source_serial
        self.source_refresh.setEnabled(False)
        self.source_validate.setEnabled(False)
        self.source_status.setText("正在读取本地数据库")
        self.client.get("/api/settings/data-source", lambda data, error: self._source_loaded(data, error, serial))

    def _source_loaded(self, data: dict[str, Any] | None, error: str | None, serial=None, *, validated=False) -> None:
        if serial is not None and serial != self._source_serial:
            return
        self._source_busy = False
        self.source_refresh.setEnabled(True)
        self.source_validate.setEnabled("settings.manage" in self.user.get("permissions", []))
        self.source_validate.setText("校验数据库")
        if error:
            self.source_text.setPlainText(error)
            self.source_status.setText(error)
            self.source_badge.setText("状态不可用")
            self.source_badge.setProperty("state", "error")
            self.source_badge.style().unpolish(self.source_badge)
            self.source_badge.style().polish(self.source_badge)
            self.source._layout_content()
            return
        import json
        self.source_text.setPlainText(json.dumps(data or {}, ensure_ascii=False, indent=2))
        active = (data or {}).get("active") or {}
        self._source_path = active.get("path")
        self.source_copy.setEnabled(bool(self._source_path))
        self.source_status.setText((data or {}).get("message") or "所有业务数据保存在此本地数据库。")
        local = active.get("mode", "local") == "local" and str(active.get("engine") or "").lower() == "sqlite"
        available = local and active.get("exists")
        self.source_badge.setText(("本地使用中 · 校验通过" if validated and (data or {}).get("ok") else
                                  "本地使用中") if available else "文件不可用" if local else "状态异常")
        self.source_badge.setProperty("state", "success" if available else "error")
        self.source_badge.style().unpolish(self.source_badge)
        self.source_badge.style().polish(self.source_badge)
        size = active.get("size_bytes", 0)
        values = {"engine": "SQLite · 本地文件" if str(active.get("engine") or "").lower() == "sqlite"
                  else str(active.get("engine") or "").upper(),
                  "path": active.get("path") or "未提供",
                  "exists": "已存在" if active.get("exists") else "未找到",
                  "size": f"{size / 1024:.1f} KB" if size < 1048576 else f"{size / 1048576:.2f} MB",
                  "integrity": (data or {}).get("message") or "尚未校验"}
        for key, value in values.items():
            self.source_fields[key].setText(value)
        self.source._layout_content()

    def validate_source(self) -> None:
        if self._source_busy or "settings.manage" not in self.user.get("permissions", []):
            return
        self._source_busy = True
        self._source_serial += 1
        serial = self._source_serial
        self.source_refresh.setEnabled(False)
        self.source_validate.setEnabled(False)
        self.source_validate.setText("正在校验…")
        self.source_status.setText("正在校验数据库")
        self.client.post("/api/settings/data-source/validate", {"target": "local"},
                         lambda data, error: self._source_loaded(data, error, serial, validated=True))

    def copy_source_path(self):
        if getattr(self, "_source_path", None):
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(self._source_path)
            self.source_status.setText("数据库路径已复制到剪贴板。")
            self.source_copy.setText("已复制")
            QTimer.singleShot(1500, self.source_copy, lambda: self.source_copy.setText("复制路径"))

    def create_backup(self) -> None:
        self.client.post("/api/backup", {"note": "原生 Qt 手动备份"}, lambda data, error: self._backup_done(data, error))

    def _backup_done(self, data: dict[str, Any] | None, error: str | None) -> None:
        if error:
            QMessageBox.warning(self, PRODUCT_NAME, error)
            return
        QMessageBox.information(self, PRODUCT_NAME, f"备份完成\n{(data or {}).get('path', data)}")
        self.backups.load()

    def validate_backup(self) -> None:
        index = self.backups.table.currentIndex()
        if not index.isValid() or index.row() >= len(self.backups.model.rows):
            QMessageBox.information(self, PRODUCT_NAME, "请先选择备份文件")
            return
        path = self.backups.model.rows[index.row()].get("path")
        if not isinstance(path, str) or not path:
            QMessageBox.warning(self, PRODUCT_NAME, "所选备份路径无效")
            return
        self.client.post("/api/backup-validate", {"path": path},
                         lambda data, error: self._backup_validated(path, data, error))

    def _backup_validated(self, path: str, data: dict[str, Any] | None, error: str | None) -> None:
        if error or not data or data.get("integrity") != "ok" or not isinstance(data.get("findings"), int):
            QMessageBox.warning(self, PRODUCT_NAME, error or "备份校验失败，不能恢复")
            return
        verification = "SHA-256 已核对" if data.get("hash_verified") else "仅数据库完整性检查，缺少校验清单"
        phrase, accepted = QInputDialog.getText(
            self, "确认恢复数据库",
            f"备份：{path}\n检测记录：{data['findings']} 条\n校验：{verification}\n\n"
            "恢复会替换当前业务数据，系统会先创建安全备份并要求重新登录。\n请输入“恢复数据库”确认：",
        )
        if not accepted or phrase != "恢复数据库":
            return
        self.tabs.setEnabled(False)
        self.client.post("/api/restore", {"path": path}, self._restore_done)

    def _restore_done(self, data: dict[str, Any] | None, error: str | None) -> None:
        self.tabs.setEnabled(True)
        if error or not data:
            QMessageBox.warning(self, PRODUCT_NAME, error or "数据库恢复失败")
            return
        QMessageBox.information(
            self, PRODUCT_NAME,
            f"数据库已恢复。\n恢复前安全备份：{data.get('safety_backup', '未返回')}\n请重新登录。",
        )
        self.logoutRequested.emit()

def _three_d_iso_angles(mode="assembly"):
    x, y, z = {
        "assembly": (.52, .40, .76), "joint": (.55, .38, .74),
        "full": (.45, .12, .45), "socket": (.6, .35, .7),
        "plate": (0, 1, 0),
    }.get(mode, (.52, .40, .76))
    return math.degrees(math.atan2(x, z)), -math.degrees(math.atan2(y, math.hypot(x, z)))


class _HeadlessThreeDRoot(QObject):
    """Small property/signal adapter used when no scene graph is available."""

    tubeSelected = Signal(int)
    partSelected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._values = {
            "tubes": [], "yaw": _three_d_iso_angles()[0], "pitch": _three_d_iso_angles()[1], "zoomFactor": 1,
            "orthographicView": False, "mirrorTop": False, "standardAligned": True,
            "showDefect": True, "showReview": True,
            "showNdd": True, "showMissing": True,
        }

    def property(self, name: str):
        return self._values.get(name)

    def setProperty(self, name: str, value):
        self._values[name] = value
        return True


class _HeadlessThreeDView(QWidget):
    """Deterministic visual fallback for CI, RDP and no-GPU environments.

    The production Windows path remains QtQuick3D. This QWidget keeps the
    same root-object properties and renders the same data categories into a
    QImage so isolated UI regression can run without a native scene-graph
    provider, which is known to crash intermittently during teardown.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root = _HeadlessThreeDRoot(self)
        self.setMinimumSize(320, 280)
        self.setAutoFillBackground(True)

    def rootObject(self):
        return self._root

    def status(self):
        # Keep the same truthy ready state without importing QtQuick in
        # offscreen tests. The production branch imports Qt Quick lazily.
        return 0

    def errors(self):
        return []

    def releaseResources(self):
        return None

    def setSource(self, _url):
        return None

    def grabWindow(self):
        image = QImage(max(1, self.width()), max(1, self.height()), QImage.Format.Format_ARGB32)
        image.fill(QColor("#e8eef0"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        tubes = self._root.property("tubes") or []
        visible = {
            "defect": bool(self._root.property("showDefect")),
            "incomplete": bool(self._root.property("showReview")),
            "ndd": bool(self._root.property("showNdd")),
            "missing": bool(self._root.property("showMissing")),
        }
        for tube in tubes:
            category = str(tube.get("category") or "missing")
            if not visible.get(category, True):
                continue
            scale = min(self.width(), self.height()) / 3900
            x = self.width() / 2 + float(tube.get("x") or 0) * scale
            y = self.height() / 2 + float(tube.get("z") or 0) * scale
            painter.setBrush(QColor(str(tube.get("color") or "#87949a")))
            painter.setPen(QColor("#ffffff"))
            painter.drawEllipse(int(x - 8), int(y - 8), 16, 16)
        painter.end()
        return image


class NativeThreeDPage(QWidget):
    scopeChanged = Signal(dict)

    def __init__(self, client: NativeClient, parent=None):
        super().__init__(parent)
        self.client = client
        self._view_shutdown = False
        self._plate_overlay_enabled = False
        self.request_number = 0
        self.rows: dict[int, dict[str, Any]] = {}
        self.record_details = {}
        self._scope_data = None
        self._scene_tubes = []
        self._selected_part = None
        self._column_visibility = {}
        self._enlarge_auto = True
        self.severity_levels = [30, 50]
        self.severity_colors = ["#79b98c", "#e5a83b", "#df4b45"]
        self._pending_scope = {}
        self._syncing_scope = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        toolbar = ToolFlowLayout()
        self.scene_settings_button = button("", "settings")
        self.scene_settings_button.setToolTip("三维显示设置")
        self.scene_settings_button.setAccessibleName("三维显示设置")
        self.scene_settings_button.setCheckable(True)
        toolbar.addWidget(self.scene_settings_button)
        self.mode_tabs = QTabBar()
        for label in ("整体布置", "接口详图", "整管视图", "管座剖视"):
            self.mode_tabs.addTab(label)
        self.mode_tabs.setExpanding(False)
        toolbar.addWidget(self.mode_tabs)
        self.detection_filter_button = button("检测筛选", "funnel")
        self.detection_filter_button.setCheckable(True)
        toolbar.addWidget(self.detection_filter_button)
        self.plate_view = button("管板图：关", "tube-plate-grid")
        self.plate_view.setCheckable(True)
        self.plate_view.toggled.connect(self._plate_view_changed)
        toolbar.addWidget(self.plate_view)
        toolbar.addWidget(button("默认视角", "rotate-ccw", self._reset_three_d_view))
        layout.addLayout(toolbar)
        controls = ToolFlowLayout()
        controls.addWidget(QLabel("检测范围"))
        self.scope = QComboBox()
        self.scope.setMinimumWidth(280)
        self.scope.addItem("请选择基地、机组和大修", None)
        self.scope.currentIndexChanged.connect(self._scope_selected_ui)
        controls.addWidget(self.scope)
        refresh = QPushButton("刷新范围")
        refresh.clicked.connect(self.load_overview)
        controls.addWidget(refresh)
        self.filter_defect = QCheckBox("缺陷")
        self.filter_review = QCheckBox("待复核")
        self.filter_ndd = QCheckBox("NDD")
        self.filter_missing = QCheckBox("无记录")
        for check in (self.filter_defect, self.filter_review, self.filter_ndd, self.filter_missing):
            check.setChecked(True)
            check.toggled.connect(self._update_three_d_filters)
            controls.addWidget(check)
        reset_view = QPushButton("重置视角")
        reset_view.clicked.connect(self._reset_three_d_view)
        controls.addWidget(reset_view)
        scope_host = QWidget()
        scope_host.setLayout(controls)
        scope_host.hide()
        self.detection_filter_button.toggled.connect(scope_host.setVisible)
        layout.addWidget(scope_host)
        self.display_mode = QComboBox(self)
        for label, mode in (("整体布置", "assembly"), ("管板俯视", "plate"),
                            ("单管全长", "full"), ("管座剖视", "socket"), ("接口详图", "joint")):
            self.display_mode.addItem(label, mode)
        self.display_mode.currentIndexChanged.connect(self._display_changed)
        self.display_mode.hide()
        self.mode_tabs.currentChanged.connect(self._mode_tab_changed)
        self.tube_selector = QSpinBox()
        self.tube_selector.setRange(1, 50)
        self.tube_selector.setPrefix("管号 ")
        self.tube_selector.valueChanged.connect(self.show_tube)
        self.scene_settings_host = QScrollArea()
        self.scene_settings_host.setObjectName("workspacePanel")
        self.scene_settings_host.setAccessibleName("三维模型设置")
        self.scene_settings_host.setFixedWidth(330)
        self.scene_settings_host.setWidgetResizable(True)
        self.scene_settings_host.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        settings_body = QWidget()
        settings_body.setObjectName("modelSettingsBody")
        settings_layout = QVBoxLayout(settings_body)
        settings_layout.setContentsMargins(12, 6, 12, 10)
        settings_layout.setSpacing(6)
        self.scene_settings_host.setWidget(settings_body)
        self.scene_sections = {}

        def section(title):
            heading = QToolButton()
            heading.setObjectName("modelSectionHeader")
            heading.setText(title)
            heading.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            heading.setArrowType(Qt.ArrowType.DownArrow)
            heading.setCheckable(True)
            heading.setChecked(True)
            heading.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            body = QWidget()
            body_layout = QVBoxLayout(body)
            body_layout.setContentsMargins(2, 0, 2, 8)
            body_layout.setSpacing(7)
            heading.toggled.connect(body.setVisible)
            heading.toggled.connect(lambda expanded, control=heading: control.setArrowType(
                Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow))
            heading.toggled.connect(lambda _expanded: self._camera_layout_timer.start())
            settings_layout.addWidget(heading)
            settings_layout.addWidget(body)
            self.scene_sections[title] = (heading, body)
            return body_layout

        from .native_model_data import reference_parts
        self._parts = {part["id"]: part for part in reference_parts()}
        self._part_visibility = {key: part["visible"] for key, part in self._parts.items()}
        part_settings = section("零件（点击查看）")
        self.part_tree = QTreeWidget()
        self.part_tree.setObjectName("modelPartTree")
        self.part_tree.setAccessibleName("三维零件树")
        self.part_tree.setColumnCount(3)
        self.part_tree.setHeaderHidden(True)
        self.part_tree.setRootIsDecorated(False)
        self.part_tree.setUniformRowHeights(True)
        self.part_tree.setIndentation(0)
        self.part_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.part_tree.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.part_tree.header().setStretchLastSection(False)
        self.part_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.part_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.part_tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.part_tree.setColumnWidth(1, 50)
        self.part_tree.setColumnWidth(2, 20)
        self.part_items = {}
        for key, part in self._parts.items():
            source = {"step": "STEP", "context": "环境"}.get(part["kind"], "参数化")
            item = QTreeWidgetItem([part["cn"], source, ""])
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            swatch = QPixmap(9, 9)
            swatch.fill(QColor(part["color"]))
            item.setIcon(0, QIcon(swatch))
            for column in range(3):
                item.setToolTip(column, f"{key} · {part['cn']} · {source}")
            self.part_tree.addTopLevelItem(item)
            self.part_items[key] = item
        self.part_tree.itemClicked.connect(
            lambda item, _column: self.show_part(item.data(0, Qt.ItemDataRole.UserRole)))
        self.part_tree.itemActivated.connect(
            lambda item, _column: self.show_part(item.data(0, Qt.ItemDataRole.UserRole)))
        self.part_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.part_tree.customContextMenuRequested.connect(self._part_context)
        part_settings.addWidget(self.part_tree)
        self._sync_part_tree()
        assembly_settings = section("整体布置")
        self.visibility_checks = {}
        for label, prop, checked in (("容器包络", "showVessel", True), ("下封头", "showDome", True),
                                     ("支承板", "showPlates", True), ("支承柱", "showSupports", True),
                                     ("管座", "showSockets", True), ("贯穿管", "showPenetrations", True),
                                     ("管径放大", "enlargeTubes", True)):
            check = QCheckBox(label)
            check.setChecked(checked)
            check.toggled.connect(lambda value, name=prop: self._set_scene_property(name, value))
            self.visibility_checks[prop] = check
            assembly_settings.addWidget(check)
        self.maintenance_preview = QCheckBox("维护后位置预览")
        self.maintenance_preview.toggled.connect(self._rebuild_scene)
        assembly_settings.addWidget(self.maintenance_preview)
        self.scene_settings_host.hide()
        self.scene_settings_button.toggled.connect(self.scene_settings_host.setVisible)
        self.camera_preset = QComboBox(settings_body)
        # Keep the seven standard engineering views available as explicit
        # camera presets.  The old four-entry selector made it impossible to
        # reproduce the rear/left/bottom inspection orientations without
        # manually dragging the model.
        for label, angles in (
            ("等轴视角", _three_d_iso_angles()),
            ("正视", (0, 0)),
            ("后视", (180, 0)),
            ("左视", (-90, 0)),
            ("右视", (90, 0)),
            ("俯视", (0, -90)),
            ("仰视", (0, 90)),
        ):
            self.camera_preset.addItem(label, angles)
        self.camera_preset.currentIndexChanged.connect(self._camera_changed)
        self.camera_preset.hide()
        self.type_filter = QComboBox()
        self.type_filter.addItem("全部管型", "")
        from .native_model_data import reference_layout, reference_specs
        for kind in sorted({str(c["type"]) for c in reference_layout()["channels"]}):
            self.type_filter.addItem(kind, kind)
        self.type_filter.setAccessibleName("三维型号筛选")
        self.type_filter.currentIndexChanged.connect(self._tube_type_changed)
        self.column_legend = QWidget()
        self.column_legend.setAccessibleName("支承柱分类图例")
        column_layout = QGridLayout(self.column_legend)
        column_layout.setContentsMargins(22, 1, 0, 4)
        column_layout.setHorizontalSpacing(8)
        column_layout.setVerticalSpacing(1)
        self.column_buttons = {}
        column_colors = {"core-hollow": "#5f87a8", "core-solid": "#4f9d9d",
                         "sec-hollow": "#8a7fb8", "sec-solid": "#9fb4c9"}
        column_names = {"core-hollow": "空心柱 A", "core-solid": "实心柱 B",
                        "sec-hollow": "二次空心", "sec-solid": "二次实心"}
        for index, group in enumerate(reference_layout()["structure"]["columnGroups"]):
            kind = group["id"]
            control = QToolButton()
            control.setObjectName("columnGroupLegend")
            control.setText(f"{column_names.get(kind, group['cn'])} {group['count']}")
            control.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            control.setIconSize(QSize(9, 9))
            legend_font = control.font()
            legend_font.setPixelSize(10)
            control.setFont(legend_font)
            control.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            control.setCheckable(True)
            control.setChecked(True)
            control.setAccessibleName(f"显示{group['cn']}，{group['count']} 根")
            control.setToolTip(f"{group['cn']}　共 {group['count']} 根　点击切换显隐")
            swatch = QPixmap(9, 9)
            swatch.fill(QColor(column_colors.get(kind, "#8fa6bb")))
            control.setIcon(QIcon(swatch))
            effect = QGraphicsOpacityEffect(control)
            effect.setOpacity(1)
            control.setGraphicsEffect(effect)
            control.toggled.connect(lambda visible, name=kind: self._column_group_changed(name, visible))
            self.column_buttons[kind] = control
            column_layout.addWidget(control, index // 2, index % 2)
        self.visibility_checks["showSupports"].toggled.connect(self.column_legend.setVisible)
        assembly_settings.addWidget(self.column_legend)
        assembly_settings.addWidget(self.type_filter)
        model_legend = ToolFlowLayout()
        model_legend.setContentsMargins(0, 0, 0, 0)
        model_legend.setSpacing(3)
        specs = reference_specs()
        models = [*specs["models"], {"type": "空心柱", "cn": "空心柱", "count": 2, "color": "#8d8d8d"}]
        self.type_buttons = {}
        for model in models:
            control = QToolButton()
            control.setObjectName("modelTypeLegend")
            control.setText(f"{model['cn']} {model['count']}")
            control.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            control.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            control.setCheckable(True)
            control.setAccessibleName(f"筛选{model['cn']}")
            control.setToolTip(f"{model['cn']} · {model['count']} 根；再次点击恢复全部")
            swatch = QPixmap(10, 10)
            swatch.fill(QColor(model["color"]))
            control.setIcon(QIcon(swatch))
            control.clicked.connect(lambda _checked, kind=model["type"]: self.type_filter.setCurrentIndex(
                0 if self.type_filter.currentData() == kind else self.type_filter.findData(kind)))
            self.type_buttons[model["type"]] = control
            model_legend.addWidget(control)
        assembly_settings.addLayout(model_legend)
        self.color_checks = {}
        color_row = ToolFlowLayout()
        for label, mode in (("按管长着色", "length"), ("按型号着色", "type")):
            control = QCheckBox(label)
            control.toggled.connect(lambda checked, name=mode: self._tube_color_changed(name, checked))
            self.color_checks[mode] = control
            color_row.addWidget(control)
        assembly_settings.addLayout(color_row)
        self.color_checks["depth"] = QCheckBox("按检测数据着色（最大磨损）")
        self.color_checks["depth"].toggled.connect(lambda checked: self._tube_color_changed("depth", checked))
        assembly_settings.addWidget(self.color_checks["depth"])
        self.color_legend = QWidget()
        self.color_legend.setAccessibleName("三维着色图例")
        self.color_legend_layout = ToolFlowLayout(self.color_legend)
        assembly_settings.addWidget(self.color_legend)
        self._sync_color_legend()
        self.axes = QCheckBox("XYZ 坐标轴")
        self.axes.setChecked(True)
        self.axes.setToolTip("X 红 / Y 绿 / Z 蓝，随视角旋转")
        self.axes.toggled.connect(lambda v: self._set_scene_property("showAxes", v))
        assembly_settings.addWidget(self.axes)
        display_settings = section("显示")
        self.detail_axis = QCheckBox("轴线 / 坐标")
        self.detail_axis.toggled.connect(lambda v: self._set_scene_property("showDetailAxis", v))
        display_settings.addWidget(self.detail_axis)
        self.dimensions = QCheckBox("尺寸标注")
        self.dimensions.setChecked(True)
        self.dimensions.toggled.connect(lambda checked: self._update_model_annotations())
        display_settings.addWidget(self.dimensions)
        self.stations = QCheckBox("P1–P6 轴向标记")
        self.stations.setChecked(True)
        self.stations.toggled.connect(lambda checked: self._set_scene_property("showStations", checked))
        display_settings.addWidget(self.stations)
        enlarge = self.visibility_checks["enlargeTubes"]
        display_settings.addWidget(enlarge)
        enlarge.clicked.connect(lambda _checked: setattr(self, "_enlarge_auto", False))
        self.ghost = QCheckBox("环境件半透明")
        self.ghost.setChecked(True)
        self.ghost.toggled.connect(lambda value: self._set_scene_property("ghostContext", value))
        display_settings.addWidget(self.ghost)
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(10, 100)
        self.opacity.setValue(100)
        self.opacity.valueChanged.connect(lambda v: self._set_scene_property("modelOpacity", v / 100))
        display_settings.addWidget(QLabel("管身透明度"))
        display_settings.addWidget(self.opacity)
        cut_settings = section("剖切")
        self.explode = QSlider(Qt.Orientation.Horizontal)
        self.explode.setRange(0, 100)
        self.explode.valueChanged.connect(lambda v: self._set_scene_property("explode", v / 100))
        self.section = QCheckBox("剖切")
        self.section.toggled.connect(lambda v: self._set_scene_property("clipEnabled", v))
        cut_settings.addWidget(self.section)
        cut_form = QFormLayout()
        cut_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.section_axis = QComboBox()
        for axis in ("x", "y", "z"):
            self.section_axis.addItem(axis.upper(), axis)
        self.section_axis.currentIndexChanged.connect(
            lambda: self._set_scene_property("clipAxis", self.section_axis.currentData()))
        cut_form.addRow("剖切轴", self.section_axis)
        self.section_offset = QSpinBox()
        self.section_offset.setRange(-10000, 10000)
        self.section_offset.setSingleStep(100)
        self.section_offset.setSuffix(" mm")
        self.section_offset.valueChanged.connect(lambda v: self._set_scene_property("clipOffset", v))
        cut_form.addRow("位置", self.section_offset)
        cut_settings.addLayout(cut_form)
        self.measurement = QCheckBox("两点测距")
        self.measurement.toggled.connect(lambda v: self._set_scene_property("measurementEnabled", v))
        cut_settings.addWidget(self.measurement)
        self.measurement_value = QLabel()
        self.measurement_value.setWordWrap(True)
        cut_settings.addWidget(self.measurement_value)
        explode_settings = section("爆炸")
        explode_settings.addWidget(self.explode)
        self.image_export = button("导出 PNG", "download",
                                   lambda: export_widget_image(self, self.client, self.view, "导出三维视图"))
        settings_layout.addWidget(self.image_export)
        settings_layout.addStretch(1)
        self.status = QLabel("正在读取检测范围...")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        # QtQuick3D is kept for the real desktop runtime. Headless/offscreen
        # runs use a QWidget adapter to avoid driver teardown crashes while
        # preserving the same data, filters and root-object contract.
        self._headless_view = os.environ.get("QT_QPA_PLATFORM", "").lower() in {
            "offscreen", "minimal", "minimalegl"
        }
        if self._headless_view:
            self.view = _HeadlessThreeDView(self)
            self.view_container = self.view
        else:
            from PySide6.QtQuickWidgets import QQuickWidget
            from .native_geometry import register_geometry
            register_geometry()

            class SceneWidget(QQuickWidget):
                def grabWindow(self):
                    return self.grabFramebuffer()

                def releaseResources(self):
                    self.quickWindow().releaseResources()

            self.view = SceneWidget(self)
            self.view.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
            self.view.quickWindow().setPersistentSceneGraph(True)
            self.view.quickWindow().setPersistentGraphics(True)
            qml = Path(__file__).with_name("native_model.qml")
            self.view.setSource(QUrl.fromLocalFile(str(qml)))
            self.view_container = self.view
        root = self.view.rootObject()
        if root is not None:
            root.tubeSelected.connect(self.show_tube)
            root.partSelected.connect(self.show_part)
            if hasattr(root, "stationSelected"):
                root.stationSelected.connect(self._station_selected)
            root.setProperty("partVisibility", self._part_visibility)
            root.setProperty("partColors", {key: part["color"] for key, part in self._parts.items()})
            root.setProperty("partMetalness", {key: part["metalness"] for key, part in self._parts.items()})
            if hasattr(root, "viewManipulated"):
                root.viewManipulated.connect(lambda: self.camera_preset.setCurrentIndex(-1))
                root.viewReset.connect(self._reset_three_d_view)
            if hasattr(root, "measurementChanged"):
                root.measurementChanged.connect(self.measurement_value.setText)
            from .native_model_data import reference_layout
            from .native_geometry import assembly_caps, geometry_data
            vessel = reference_layout()["vessel"]
            radius = vessel["outerRadius"]
            root.setProperty("assemblyMinimum", QVector3D(-radius, vessel["headBottomY"], -radius))
            root.setProperty("assemblyMaximum", QVector3D(radius, vessel["cylinderTopY"], radius))
            root.setProperty("geometryBounds", {
                part: list(geometry_data(part)[2]) for part in ("vessel", "dome", "ucsPlate", "secondaryGrid", "P01", "P02", "P05")
            })
            root.setProperty("columns", [{**row, "meshId": f"column-{index}",
                                          "bounds": list(geometry_data(f"column-{index}")[2])}
                                         for index, row in enumerate(reference_layout()["structure"]["columns"])])
            root.setProperty("assemblyCaps", [
                {key: part[key] for key in ("id", "target", "columnType", "explodeOffset", "material")}
                for part in assembly_caps()])
        self.view_container.setMinimumSize(320, 280)
        self.scene_host = QWidget()
        self.scene_host.setMinimumSize(320, 280)
        scene_layout = QGridLayout(self.scene_host)
        scene_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        scene_layout.setContentsMargins(0, 0, 0, 0)
        scene_layout.addWidget(self.view_container, 0, 0)
        scene_layout.addWidget(self.scene_settings_host, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        detail_host = QWidget()
        self.scene_detail_host = detail_host
        detail_host.setObjectName("workspacePanel")
        detail_host.setFixedWidth(322)
        detail_layout = QVBoxLayout(detail_host)
        self.part_info_host = QScrollArea()
        self.part_info_host.setAccessibleName("三维零件详情")
        self.part_info_host.setWidgetResizable(True)
        self.part_info_host.setFrameShape(QScrollArea.Shape.NoFrame)
        self.part_info_host.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.part_info_body = QWidget()
        self.part_info_body.setObjectName("modelPartInfoBody")
        info_layout = QVBoxLayout(self.part_info_body)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(7)
        title_row = QHBoxLayout()
        self.part_name = QLabel()
        self.part_name.setObjectName("modelPartName")
        self.part_name.setWordWrap(True)
        self.part_name.setTextFormat(Qt.TextFormat.PlainText)
        title_row.addWidget(self.part_name, 1)
        close_part = button("", "x", self._hide_part_info)
        close_part.setToolTip("关闭零件详情")
        close_part.setAccessibleName("关闭零件详情")
        title_row.addWidget(close_part, 0, Qt.AlignmentFlag.AlignTop)
        info_layout.addLayout(title_row)
        self.part_tags = QLabel()
        self.part_tags.setWordWrap(True)
        self.part_tags.setTextFormat(Qt.TextFormat.PlainText)
        info_layout.addWidget(self.part_tags)
        self.part_fields = QFormLayout()
        self.part_fields.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.part_fields.setHorizontalSpacing(10)
        self.part_fields.setVerticalSpacing(7)
        info_layout.addLayout(self.part_fields)
        self.part_note = QLabel()
        self.part_note.setWordWrap(True)
        self.part_note.setTextFormat(Qt.TextFormat.PlainText)
        info_layout.addWidget(self.part_note)
        info_layout.addStretch(1)
        self.part_info_host.setWidget(self.part_info_body)
        self.part_info_host.hide()
        detail_layout.addWidget(self.part_info_host, 1)
        self.data_details_button = button("检测数据", "files")
        self.data_details_button.setCheckable(True)
        detail_layout.addWidget(self.data_details_button)
        details_body = QWidget()
        details_body_layout = QVBoxLayout(details_body)
        details_body_layout.setContentsMargins(0, 0, 0, 0)
        self.detail = QLabel("选择管子查看检测记录与维护状态")
        self.detail.setWordWrap(True)
        details_body_layout.addWidget(self.detail)
        self.records = QListWidget()
        self.records.currentRowChanged.connect(self._record_selected)
        details_body_layout.addWidget(self.records, 1)
        self.record_detail = QPlainTextEdit()
        self.record_detail.setReadOnly(True)
        details_body_layout.addWidget(self.record_detail, 1)
        details_body.setMaximumHeight(450)
        details_body.hide()
        detail_layout.addWidget(details_body)
        self.data_details_button.toggled.connect(details_body.setVisible)
        scene_layout.addWidget(detail_host, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        footer = QWidget()
        self.scene_footer = footer
        footer.setObjectName("workspacePanel")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(8, 5, 8, 5)
        footer_layout.setSpacing(4)
        camera_row = QHBoxLayout()
        self.camera_buttons = []
        for index in range(self.camera_preset.count()):
            control = QPushButton(self.camera_preset.itemText(index))
            control.setCheckable(True)
            control.setChecked(index == 0)
            control.clicked.connect(lambda _, value=index: self._select_camera(value))
            self.camera_buttons.append(control)
            camera_row.addWidget(control)
        camera_row.addWidget(button("适配", None, self._fit_scene))
        self.auto_rotate = QCheckBox("自动旋转")
        self.auto_rotate.toggled.connect(self._rotation_changed)
        camera_row.addWidget(self.auto_rotate)
        footer_layout.addLayout(camera_row)
        tube_row = QHBoxLayout()
        previous_tube = button("", "chevron-left", lambda: self.tube_selector.setValue(max(1, self.tube_selector.value() - 1)))
        previous_tube.setToolTip("上一根管")
        tube_row.addWidget(previous_tube)
        tube_row.addWidget(self.tube_selector)
        self.tube_slider = QSlider(Qt.Orientation.Horizontal)
        self.tube_slider.setRange(1, 50)
        self.tube_slider.setValue(1)
        self.tube_slider.valueChanged.connect(self.tube_selector.setValue)
        self.tube_selector.valueChanged.connect(self.tube_slider.setValue)
        tube_row.addWidget(self.tube_slider, 1)
        tube_row.addWidget(QLabel("/ 50"))
        next_tube = button("", "chevron-right", lambda: self.tube_selector.setValue(min(50, self.tube_selector.value() + 1)))
        next_tube.setToolTip("下一根管")
        tube_row.addWidget(next_tube)
        tube_row.addWidget(button("管子详情", "files", self.data_details_button.toggle))
        footer_layout.addLayout(tube_row)
        scene_layout.addWidget(footer, 0, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.scene_host, 1)
        self._rotation_timer = QTimer(self)
        self._rotation_timer.setInterval(33)
        self._rotation_timer.timeout.connect(self._rotate_scene)
        self._camera_layout_timer = QTimer(self)
        self._camera_layout_timer.setSingleShot(True)
        self._camera_layout_timer.timeout.connect(self._sync_camera_space)
        from .native_model_panel import ModelPanelGroups
        keys = {"asm": "整体布置", "disp": "显示", "cut": "剖切", "explode": "爆炸", "parts": "零件（点击查看）"}
        self.scene_sections = {title: self.scene_sections[title] for title in keys.values()}
        self.model_groups = ModelPanelGroups(
            self.scene_settings_host, {key: self.scene_sections[title] for key, title in keys.items()},
            self._camera_layout_timer.start)
        self.model_groups.saveFailed.connect(self.status.setText)
        self.detection_filter_button.toggled.connect(lambda _checked: self._camera_layout_timer.start())
        self.data_details_button.toggled.connect(lambda _checked: self._camera_layout_timer.start())
        self.visibility_checks["enlargeTubes"].toggled.connect(lambda _checked: self._update_model_annotations())
        detail_host.installEventFilter(self)
        footer.installEventFilter(self)
        self.scene_settings_host.installEventFilter(self)
        self.scene_host.installEventFilter(self)
        self._camera_layout_timer.start()
        self._sync_detail_channel()
        self._sync_mode_controls()
        self.load_overview()

    def eventFilter(self, watched, event):
        if (not self._view_shutdown and hasattr(self, "_camera_layout_timer")
                and watched in (self.scene_detail_host, self.scene_footer, self.scene_settings_host, self.scene_host)
                and event.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.Hide)):
            self._camera_layout_timer.start()
        return super().eventFilter(watched, event)

    def _sync_camera_space(self):
        if self._view_shutdown:
            return
        settings = self.scene_settings_host
        available_height = max(150, self.scene_host.height() - self.scene_footer.height() - 16)
        self.model_groups.fit(available_height)
        content = settings.widget()
        content_height = (content.heightForWidth(settings.viewport().width()) if content.hasHeightForWidth()
                          else content.sizeHint().height())
        expanded_detail = self.part_info_host.isVisible() or self.data_details_button.isChecked()
        margins = self.scene_detail_host.layout().contentsMargins()
        self.scene_detail_host.setFixedWidth(322 if expanded_detail else
                                             self.data_details_button.sizeHint().width()+margins.left()+margins.right())
        self.scene_detail_host.setMaximumHeight(available_height)
        if self.part_info_host.isVisible():
            body = self.part_info_body
            desired = body.heightForWidth(self.part_info_host.viewport().width()) if body.hasHeightForWidth() else body.sizeHint().height()
            self.part_info_host.setMinimumHeight(min(max(80, available_height - 70), max(80, desired)))
        self.part_tree.setFixedHeight(sum(self.part_tree.sizeHintForRow(i)
                                         for i in range(self.part_tree.topLevelItemCount())) + 4)
        settings.setFixedHeight(min(available_height, max(1, content_height) + 2 * settings.frameWidth()))
        self._set_scene_property("coveredLeft", self.scene_settings_host.width() + 16
                                 if self.scene_settings_host.isVisible() else 0)
        self._set_scene_property("coveredRight", self.scene_detail_host.width() + 16
                                 if self.scene_detail_host.isVisible() else 0)
        self._set_scene_property("coveredBottom", self.scene_footer.height() + 16
                                 if self.scene_footer.isVisible() else 0)
        footer = self.scene_footer.geometry()
        self._set_scene_property("footerBounds", [footer.left(), footer.top(), footer.right(), footer.bottom()]
                                 if self.scene_footer.isVisible() else [0, 0, 0, 0])
        self._set_scene_property("suppressScale", self.scene_settings_host.isVisible()
                                 or self.part_info_host.isVisible() or self.data_details_button.isChecked()
                                 or self.detection_filter_button.isChecked())

    def _refit_camera(self):
        root = self.view.rootObject()
        if root is not None and hasattr(root, "fitView"):
            root.fitView()

    def _fit_scene(self):
        for name, value in (("zoomFactor", 1), ("panX", 0), ("panY", 0)):
            self._set_scene_property(name, value)
        self._refit_camera()

    def _rotation_changed(self, checked):
        if checked and self.isVisible():
            root = self.view.rootObject()
            if root is None or self._view_shutdown:
                self._rotation_timer.stop()
                return
            if root.property("orthographicView"):
                self._reset_three_d_view()
            self._rotation_timer.start()
        else:
            self._rotation_timer.stop()

    def _rotate_scene(self):
        root = self.view.rootObject()
        if root:
            self._set_scene_property("standardAligned", False)
            self.camera_preset.setCurrentIndex(-1)
            self._set_scene_property("yaw", (float(root.property("yaw") or 0) + .6) % 360)

    def showEvent(self, event):
        super().showEvent(event)
        self._rotation_changed(self.auto_rotate.isChecked())

    def hideEvent(self, event):
        self._rotation_timer.stop()
        super().hideEvent(event)

    def _set_scene_property(self, name, value):
        root = self.view.rootObject()
        if root is not None:
            root.setProperty(name, value)

    def _sync_part_tree(self):
        for key, item in self.part_items.items():
            visible = self._part_visibility[key]
            item.setText(2, "●" if visible else "○")
            item.setData(0, Qt.ItemDataRole.AccessibleTextRole,
                         f"{self._parts[key]['cn']}，{'显示' if visible else '隐藏'}")
            for column in range(3):
                item.setForeground(column, QBrush() if visible else
                                   QBrush(QColor("#a8b8b5" if getattr(self, "_model_dark_theme", False)
                                                 else "#647c8c")))
        if hasattr(self, "view"):
            self._set_scene_property("partVisibility", dict(self._part_visibility))
            self._update_model_annotations()

    def _part_context(self, point):
        item = self.part_tree.itemAt(point)
        if item is not None:
            self.toggle_part(item.data(0, Qt.ItemDataRole.UserRole))

    def toggle_part(self, part_id):
        if part_id not in self._parts:
            return
        self._part_visibility[part_id] = not self._part_visibility[part_id]
        self._sync_part_tree()
        if self._selected_part == part_id:
            self._hide_part_info()

    def _hide_part_info(self):
        self.part_info_host.hide()
        self._camera_layout_timer.start()

    def show_part(self, part_id):
        if part_id not in self._parts:
            return
        if self.display_mode.currentData() in ("assembly", "plate"):
            self.mode_tabs.setCurrentIndex(1)
            self.display_mode.setCurrentIndex(self.display_mode.findData("joint"))
        self._part_visibility[part_id] = True
        self._sync_part_tree()
        self._selected_part = part_id
        self.part_tree.setCurrentItem(self.part_items[part_id])
        self._render_part_info()
        self.part_info_host.show()
        self.part_info_host.verticalScrollBar().setValue(0)
        self._camera_layout_timer.start()

    def _detail_channel(self):
        from .native_model_data import reference_channel, reference_layout
        row = self.rows.get(self.tube_selector.value()) or {}
        if row.get("position"):
            channel = next((channel for channel in reference_layout()["channels"]
                            if channel["pos"] == row["position"]), None)
            if channel:
                return channel
        return reference_channel(self.tube_selector.value(), (self.scope.currentData() or {}).get("unit", 1))

    def _sync_detail_channel(self):
        self._set_scene_property("selectedTube", self.tube_selector.value())
        self._set_scene_property("detailLength", self._detail_channel()["L"])
        self._update_model_annotations()
        if self._selected_part:
            self._render_part_info()

    def _render_part_info(self):
        from .native_model_data import part_info
        part = self._parts[self._selected_part]
        self.part_name.setText(f"{part['cn']}　{part['en'] or ''}")
        source = {"step": "原始 STEP B-rep", "context": "环境件"}.get(part["kind"], "参数化重建")
        self.part_tags.setText(f"{part['id']} · {source} · {part['triCount'] or 0:,} 三角面")
        while self.part_fields.rowCount():
            self.part_fields.removeRow(0)
        for name, text, provenance in part_info(self._selected_part, self._detail_channel()):
            label, value = QLabel(name), QLabel(text)
            for control in (label, value):
                control.setTextFormat(Qt.TextFormat.PlainText)
                control.setWordWrap(True)
                control.setToolTip(provenance)
            label.setFixedWidth(110)
            self.part_fields.addRow(label, value)
        self.part_note.setText(part["note"] or "")

    def _sync_mode_controls(self):
        assembly = self.display_mode.currentData() in ("assembly", "plate")
        for heading, body in (self.scene_sections["整体布置"],):
            heading.setVisible(assembly)
            body.setVisible(assembly and heading.isChecked())
        self.ghost.setEnabled(not assembly)
        self.dimensions.setEnabled(not assembly)
        self.stations.setEnabled(not assembly)
        self.detail_axis.setEnabled(not assembly)
        enlarge = self.visibility_checks["enlargeTubes"]
        mode = self.display_mode.currentData()
        if mode in ("assembly", "full") and not enlarge.isChecked():
            self._enlarge_auto = True
            enlarge.setChecked(True)
        elif mode not in ("assembly", "full") and self._enlarge_auto:
            enlarge.setChecked(False)
            self._enlarge_auto = False
        self._update_model_annotations()
        self._camera_layout_timer.start()

    def _update_model_annotations(self):
        if not hasattr(self, "view"):
            return
        from .native_model_data import dimension_annotations, station_marks
        length = self._detail_channel()["L"]
        self._set_scene_property("stations", station_marks(length))
        self._set_scene_property("showStations", self.stations.isChecked())
        self._set_scene_property("dimensionLabels", dimension_annotations(
            self.display_mode.currentData(), length, self._part_visibility,
            self.visibility_checks["enlargeTubes"].isChecked()) if self.dimensions.isChecked() else [])

    def _station_selected(self, station_id):
        from .native_model_data import reference_stations
        station = reference_stations().get(station_id)
        if station:
            QToolTip.showText(QCursor.pos(), f"{station_id}：{station['desc']}（{station['status']}）\n"
                              f"{station['basis']}\n工程参考基面，非电厂实测标定", self.view)

    def set_severity(self, levels, colors):
        self.severity_levels = list(levels)
        self.severity_colors = list(colors)
        self._update_tube_colors()

    def set_theme(self, theme):
        self._model_dark_theme = theme == "dark"
        self._set_scene_property("darkTheme", self._model_dark_theme)
        self._sync_part_tree()

    def _tube_color_changed(self, mode, checked):
        # The reference clears length/type when depth is enabled; depth keeps
        # priority if a geometric color option is subsequently selected.
        if checked:
            others = ("length", "type") if mode == "depth" else ("type" if mode == "length" else "length",)
            for name in others:
                self.color_checks[name].blockSignals(True)
                self.color_checks[name].setChecked(False)
                self.color_checks[name].blockSignals(False)
        self._update_tube_colors()

    def _tube_type_changed(self):
        kind = self.type_filter.currentData() or ""
        self._set_scene_property("tubeType", kind)
        for name, control in self.type_buttons.items():
            control.setChecked(name == kind)
        self._update_tube_colors()

    def _column_group_changed(self, kind, visible):
        self._column_visibility[kind] = visible
        self.column_buttons[kind].graphicsEffect().setOpacity(1 if visible else .4)
        self._set_scene_property("columnVisibility", dict(self._column_visibility))

    def _tube_color_mode(self):
        return next((name for name in ("depth", "type", "length") if self.color_checks[name].isChecked()), "base")

    def _update_tube_colors(self):
        from .native_model_data import color_tubes
        tubes = color_tubes(
            self._scene_tubes, (self._scope_data or {}).get("records") or [],
            mode=self._tube_color_mode(), type_filter=self.type_filter.currentData() or "",
            levels=self.severity_levels, colors=self.severity_colors)
        self._set_scene_property("tubeColors", {str(tube["tube"]): tube["color"] for tube in tubes})
        self._sync_color_legend()

    def _sync_color_legend(self):
        while self.color_legend_layout.count():
            item = self.color_legend_layout.takeAt(0)
            item.widget().deleteLater()
        mode = self._tube_color_mode()
        entries = []
        if mode == "depth":
            levels = self.severity_levels
            entries = [(f"< {levels[0]}%", self.severity_colors[0])]
            entries.extend((f"{low} – {high}%", self.severity_colors[index + 1])
                           for index, (low, high) in enumerate(zip(levels, levels[1:])))
            entries.extend([(f"≥ {levels[-1]}%", self.severity_colors[-1]),
                            ("无有效缺陷记录", "#667c8c")])
        elif mode == "length" and self._scene_tubes:
            from .native_model_data import color_tubes
            ends = sorted(color_tubes(self._scene_tubes, [], mode="length"), key=lambda tube: tube["length"])
            entries = [(f"{tube['length']:g} mm", tube["color"]) for tube in (ends[0], ends[-1])]
        for text, color in entries:
            entry = QWidget()
            row = QHBoxLayout(entry)
            row.setContentsMargins(0, 0, 4, 0)
            row.setSpacing(5)
            swatch = QLabel()
            swatch.setFixedSize(10, 10)
            swatch.setStyleSheet(f"background:{color};border:1px solid #70808a;")
            label = QLabel(text)
            label.setTextFormat(Qt.TextFormat.PlainText)
            row.addWidget(swatch)
            row.addWidget(label)
            self.color_legend_layout.addWidget(entry)
        self.color_legend.setVisible(bool(entries))
        if hasattr(self, "_camera_layout_timer"):
            self._camera_layout_timer.start()

    def _display_changed(self):
        tab = {"assembly": 0, "plate": 0, "joint": 1, "full": 2, "socket": 3}.get(
            self.display_mode.currentData(), 0)
        self.mode_tabs.blockSignals(True)
        self.mode_tabs.setCurrentIndex(tab)
        self.mode_tabs.blockSignals(False)
        self.camera_preset.setItemData(0, _three_d_iso_angles(self.display_mode.currentData()))
        self._set_scene_property("displayMode", self.display_mode.currentData())
        self._set_scene_property("selectedTube", self.tube_selector.value())
        self._set_scene_property("measurementCount", 0)
        self.measurement_value.clear()
        self._sync_plate_overlay_button()
        self._hide_part_info()
        self._sync_detail_channel()
        self._sync_mode_controls()
        self._reset_three_d_view()

    def _mode_tab_changed(self, index):
        self.display_mode.setCurrentIndex((0, 4, 2, 3)[index])

    def _plate_view_changed(self, enabled):
        self._plate_overlay_enabled = enabled
        if enabled and self.display_mode.currentData() != "assembly":
            self.mode_tabs.setCurrentIndex(0)
            self.display_mode.setCurrentIndex(self.display_mode.findData("assembly"))
        self._sync_plate_overlay_button()

    def _sync_plate_overlay_button(self):
        enabled = self._plate_overlay_enabled
        active = enabled and self.display_mode.currentData() == "assembly"
        self.plate_view.blockSignals(True)
        self.plate_view.setChecked(active)
        self.plate_view.blockSignals(False)
        self.plate_view.setText("管板图：开" if active else "管板图：关")
        self._set_scene_property("showPlateOverlay", enabled)

    def _camera_changed(self):
        angles = self.camera_preset.currentData()
        for index, control in enumerate(self.camera_buttons):
            control.setChecked(index == self.camera_preset.currentIndex())
        if angles is None:
            return
        yaw, pitch = angles
        self._set_scene_property("orthographicView", self.camera_preset.currentIndex() > 0)
        self._set_scene_property("mirrorTop", self.camera_preset.currentIndex() == 5)
        self._set_scene_property("standardAligned", True)
        self._set_scene_property("yaw", yaw)
        self._set_scene_property("pitch", pitch)
        self._fit_scene()

    def _select_camera(self, index):
        self.auto_rotate.setChecked(False)
        if self.camera_preset.currentIndex() == index:
            self._camera_changed()
        else:
            self.camera_preset.setCurrentIndex(index)

    def _scope_selected_ui(self):
        self.load_scope()
        if not self._syncing_scope and self.scope.currentData():
            self.scopeChanged.emit({**self.scope.currentData(), "thimble": self.tube_selector.value()})

    def set_workspace_scope(self, scope):
        self._syncing_scope = True
        try:
            self._set_workspace_scope(scope)
        finally:
            self._syncing_scope = False

    def _set_workspace_scope(self, scope):
        self._pending_scope = dict(scope)
        if not all(scope.get(key) for key in ("site", "unit", "outage")):
            if self.scope.currentIndex() != 0:
                self.scope.setCurrentIndex(0)
            return
        for index in range(1, self.scope.count()):
            item = self.scope.itemData(index)
            if (canonical_site(item["site"]) == canonical_site(scope["site"])
                    and str(item["unit"]) == str(scope["unit"]) and item["outage"] == scope["outage"]):
                if self.scope.currentIndex() != index:
                    self.scope.setCurrentIndex(index)
                if scope.get("thimble"):
                    self.tube_selector.setValue(int(scope["thimble"]))
                return

    def load_overview(self) -> None:
        self.client.get("/api/overview", self._overview_loaded)

    def _overview_loaded(self, data: dict[str, Any] | None, error: str | None) -> None:
        if error or not data:
            self.status.setText(error or "无法读取检测范围")
            return
        previous = self.scope.currentData()
        self.scope.blockSignals(True)
        self.scope.clear()
        self.scope.addItem("请选择基地、机组和大修", None)
        for item in data.get("combinations") or []:
            site = str(item.get("site") or "")
            unit = item.get("unit_id")
            outage = str(item.get("outage") or "")
            if site and unit and outage:
                scope = {"site": site, "unit": int(unit), "outage": outage}
                self.scope.addItem(f"{site}  ·  {unit}号机  ·  {outage}", scope)
                if scope == previous:
                    self.scope.setCurrentIndex(self.scope.count() - 1)
        self.scope.blockSignals(False)
        if self._pending_scope:
            self.set_workspace_scope(self._pending_scope)
        self.load_scope()

    def load_scope(self) -> None:
        from urllib.parse import urlencode

        self.request_number += 1
        request_number = self.request_number
        self.rows = {}
        self._scope_data = None
        self._scene_tubes = []
        self.record_details = {}
        self.records.clear()
        self.record_detail.clear()
        self._sync_color_legend()
        root = self.view.rootObject()
        if root is not None:
            root.setProperty("tubes", [])
            root.setProperty("tubeColors", {})
            root.setProperty("defects", [])
        self.detail.setText("选择管子查看检测记录与维护状态")
        self._sync_detail_channel()
        scope = self.scope.currentData()
        if not scope:
            self.status.setText("请选择检测范围")
            return
        self.status.setText("正在读取检测记录...")
        self.client.get("/api/analysis/live?" + urlencode(scope),
                        lambda data, error: self._scope_loaded(request_number, scope, data, error))

    def _scope_loaded(self, request_number: int, scope: dict[str, Any],
                      data: dict[str, Any] | None, error: str | None) -> None:
        if request_number != self.request_number:
            return
        if error or not data:
            self.status.setText(error or "检测数据读取失败")
            return
        if data.get("scope") != scope:
            self.status.setText("返回的检测范围不一致，未显示数据")
            return
        self._scope_data = data
        self._rebuild_scene()

    def _rebuild_scene(self, *_):
        if not self._scope_data:
            return
        from .native_model_data import scene_data
        try:
            rows, tubes, defects, details, unresolved = scene_data(
                self._scope_data, maintenance_preview=self.maintenance_preview.isChecked())
        except (ValueError, TypeError) as exc:
            self.rows = {}
            self._scene_tubes = []
            self._set_scene_property("tubes", [])
            self._set_scene_property("tubeColors", {})
            self._set_scene_property("defects", [])
            self.status.setText(str(exc))
            return
        root = self.view.rootObject()
        if root is None:
            self.status.setText("三维场景无法初始化")
            return
        self.rows = rows
        self._scene_tubes = tubes
        self._set_scene_property("plateUnit", int((self.scope.currentData() or {}).get("unit") or 0))
        self.record_details = details
        root.setProperty("tubes", tubes)
        self._update_tube_colors()
        root.setProperty("defects", defects)
        scope = self.scope.currentData() or {}
        self.status.setText(f"{scope.get('outage', '')} · {scope.get('unit', '')}号机组 · "
                            f"缺陷 {len(defects)} 处已定位 · {len(unresolved)} 处位置待确认")
        self.status.setToolTip("原工程参考管长与布置；P 位包含推导/推定基面，非电厂实测标定。")
        self.data_details_button.setText(f"检测数据 · {sum(len(items) for items in details.values())} 条记录")
        self._update_three_d_filters()
        self.show_tube(self.tube_selector.value())

    def _update_three_d_filters(self) -> None:
        root = self.view.rootObject()
        if root is None:
            return
        root.setProperty("showDefect", self.filter_defect.isChecked())
        root.setProperty("showReview", self.filter_review.isChecked())
        root.setProperty("showNdd", self.filter_ndd.isChecked())
        root.setProperty("showMissing", self.filter_missing.isChecked())

    def _reset_three_d_view(self) -> None:
        self.camera_preset.setCurrentIndex(0)
        self._camera_changed()
        root = self.view.rootObject()
        if root is not None:
            root.setProperty("orthographicView", False)
            root.setProperty("mirrorTop", False)
            root.setProperty("standardAligned", True)
            mode = self.display_mode.currentData()
            yaw, pitch = _three_d_iso_angles(mode)
            root.setProperty("yaw", yaw)
            root.setProperty("pitch", pitch)
            root.setProperty("zoomFactor", 1.8 if mode == "plate" else 1)
            root.setProperty("panX", 0)
            root.setProperty("panY", 0)
            self._refit_camera()

    def show_tube(self, number: int) -> None:
        row = self.rows.get(number)
        self.tube_selector.blockSignals(True)
        self.tube_selector.setValue(number)
        self.tube_selector.blockSignals(False)
        self.tube_slider.blockSignals(True)
        self.tube_slider.setValue(number)
        self.tube_slider.blockSignals(False)
        self._set_scene_property("selectedTube", number)
        self._sync_detail_channel()
        if not row:
            return
        scope = self.scope.currentData()
        if scope and not self._syncing_scope:
            self.scopeChanged.emit({**scope, "thimble": number})
        depth = row.get("max_percent")
        self.detail.setText(
            f"{number}号管  ·  管板位置 {row.get('position', '')}  ·  {row['category_label']}"
            f"  ·  检测记录 {row.get('records', 0)} 条  ·  最大磨损 {depth if depth is not None else '未提供'}"
            f"  ·  维护状态 {row.get('state_label') or '未记录'}"
            + ("  ·  管板位置存在不一致，请核查" if row.get("mapping_warning") else "")
        )
        self.records.clear()
        for record in self.record_details.get(number, []):
            item = QListWidgetItem(f"{record.get('indication') or '待复核'} · "
                                   f"{record.get('location_raw') or record.get('location') or '/'} · "
                                   f"{record.get('percent') if record.get('percent') is not None else '/'}%")
            item.setData(Qt.ItemDataRole.UserRole, record)
            self.records.addItem(item)
        if self.records.count():
            self.records.setCurrentRow(0)
        else:
            self.record_detail.setPlainText("当前管无检测记录")

    def _record_selected(self, index):
        item = self.records.item(index)
        if item is None:
            return
        row = item.data(Qt.ItemDataRole.UserRole)
        placement = row.get("placement")
        fields = (("模型定位", placement["note"] if placement else "位置待确认，未生成空间点"),
                  ("幅值 V", row.get("volts")), ("相位", row.get("degrees")),
                  ("测量通道", row.get("channel")), ("探头", row.get("probe")),
                  ("分析人员", row.get("analyst")), ("数据组", row.get("calgroup")),
                  ("来源文件", row.get("report_path") or row.get("filename")),
                  ("备注", row.get("analysis") or row.get("comment")))
        self.record_detail.setPlainText("\n\n".join(f"{label}：{value if value is not None else '/'}"
                                                    for label, value in fields))

    def shutdown(self) -> None:
        """Release the native scene before Qt tears down the widget tree."""
        if self._view_shutdown:
            return
        self._view_shutdown = True
        self._rotation_timer.stop()
        self._camera_layout_timer.stop()
        view = self.view
        try:
            if not self._headless_view:
                view.quickWindow().setPersistentSceneGraph(False)
                view.quickWindow().setPersistentGraphics(False)
            view.setSource(QUrl())
            view.hide()
            view.releaseResources()
            view.close()
            if view is not self.view_container:
                view.deleteLater()
            self.view_container.deleteLater()
        except RuntimeError:
            # The native window may already have been reclaimed during app exit.
            pass

    def closeEvent(self, event: QCloseEvent) -> None:
        self.shutdown()
        super().closeEvent(event)


class SettingsPage(QWidget):
    logoutRequested = Signal()

    def __init__(self, user: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        title = QLabel("设置")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        form = QFormLayout()
        form.addRow("当前账户", QLabel(str(user.get("username", ""))))
        form.addRow("显示名称", QLabel(str(user.get("display_name", ""))))
        form.addRow("权限", QLabel("、".join(user.get("permissions", [])) or "无"))
        layout.addLayout(form)
        logout = QPushButton("退出登录")
        logout.clicked.connect(self.logoutRequested)
        layout.addWidget(logout, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)


class NativeMainWindow(QMainWindow):
    logoutRequested = Signal()
    closed = Signal()

    def __init__(self, client: NativeClient, user: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.user = user
        self.context = WorkspaceContext(self)
        self.setWindowTitle(PRODUCT_NAME)
        self.resize(1480, 940)
        self.setMinimumSize(980, 680)
        if APP_ICON.is_file():
            from PySide6.QtGui import QIcon
            self.setWindowIcon(QIcon(str(APP_ICON)))

        root = QWidget(self)
        root.setObjectName("appRoot")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        top = QWidget()
        top.setObjectName("topNavigation")
        top.setFixedHeight(58)
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(4, 0, 12, 0)
        top_layout.setSpacing(8)
        self.nav = NativeNavigationBar()
        for label, name in (("数据工作台", "database"), ("三维缺陷模型", "box"),
                            ("数据可视化", "chart-no-axes-combined"), ("报告中心", "files"),
                            ("状态处理", "wrench")):
            self.nav.addTab(icon(name), label)
        top_layout.addWidget(self.nav)
        top_layout.addStretch()
        self.account_button = AccountIdentityButton(user, lambda: self.open_settings(4))
        self.connection_status = QLabel("本机服务已连接")
        self.connection_status.setObjectName("connectionStatus")
        self.connection_status.setFixedHeight(14)
        self.notifications_button = button("", "bell", self.show_notifications)
        self.notifications_button.setToolTip("操作通知")
        self.notifications_button.setAccessibleName("操作通知")
        self.settings_button = button("", "settings", lambda: self.open_settings(0))
        self.settings_button.setToolTip("软件设置")
        self.settings_button.setAccessibleName("软件设置")
        for control in (self.notifications_button, self.settings_button):
            control.setObjectName("navigationUtility")
            control.setFixedSize(30, 28)
            control.setIconSize(QSize(18, 18))
        self.utilities = QWidget()
        self.utilities.setObjectName("navigationFooter")
        self.utilities.setFixedWidth(256)
        self.utilities.setFixedHeight(58)
        utilities_layout = QVBoxLayout(self.utilities)
        utilities_layout.setContentsMargins(9, 5, 0, 4)
        utilities_layout.setSpacing(1)
        utilities_row = QHBoxLayout()
        utilities_row.setSpacing(0)
        utilities_row.addWidget(self.account_button)
        utilities_row.addSpacing(25)
        self._account_spacing = utilities_row.itemAt(1).spacerItem()
        utilities_row.addWidget(self.notifications_button)
        utilities_row.addSpacing(8)
        utilities_row.addWidget(self.settings_button)
        utilities_layout.addLayout(utilities_row)
        status_row = QHBoxLayout()
        status_row.setSpacing(5)
        status_row.addStretch()
        connection_dot = status_dot()
        connection_dot.setObjectName("connectionDot")
        status_row.addWidget(connection_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        status_row.addWidget(self.connection_status)
        status_row.addStretch()
        utilities_layout.addLayout(status_row)
        top_layout.addWidget(self.utilities)
        layout.addWidget(top)
        self.stack = QStackedWidget()
        self.workbench = DataWorkbench(client, user)
        self.stack.addWidget(self.workbench)
        self.stack.addWidget(NativeStatePage(client, user))
        self.stack.addWidget(NativeThreeDPage(client))
        self.stack.addWidget(NativeAnalyticsPage(client, user))
        self.stack.addWidget(NativeReportsPage(client, user))
        self.maintenance = NativeMaintenancePage(client, user)
        settings = NativeSettingsPage(client, user)
        settings.logoutRequested.connect(self._logout)
        self.settings_page = settings
        from .native_settings import SettingsDialog
        self.settings_dialog = SettingsDialog(client, self.context.preferences, settings,
                                              self.maintenance, self.stack.widget(3).manage_analysis_rules, self)
        self.settings_dialog.preferencesChanged.connect(self.apply_preferences)
        self.settings_dialog.sourceImportRequested.connect(
            lambda path: self.workbench._open_import_wizard("directory", path))
        self.workbench.recycleRequested.connect(self._open_recycle)
        for page in self.maintenance.findChildren(JsonTablePage):
            page.contextRequested.connect(self._open_record_context)
        layout.addWidget(self.stack, 1)
        self._navigation_indices = [0, 2, 3, 4, 1]
        self._navigation_save = QTimer(self)
        self._navigation_save.setSingleShot(True)
        self._navigation_save.setInterval(350)
        self._navigation_save.timeout.connect(self._save_navigation)
        self.nav.currentChanged.connect(self._navigate)
        self.workbench.scopeChanged.connect(self.context.set_scope)
        self.workbench.tubeFocusRequested.connect(self._focus_plate_tube)
        self.stack.widget(2).scopeChanged.connect(self.context.set_scope)
        self.stack.widget(3).visualization.scopeChanged.connect(self.context.set_scope)
        self.stack.widget(3).visualization.historyRecordsRequested.connect(self._open_history_records)
        self.stack.widget(2).image_export.setEnabled("export.create" in user.get("permissions", []))
        self.workbench.selectionChanged.connect(self.context.selection)
        self.workbench.dataChanged.connect(lambda: self._refresh_data(workbench_fresh=True))
        for index in (1, 3, 4):
            self.stack.widget(index).scope_bar.changed.connect(self.context.set_scope)
        self.context.scopeChanged.connect(self._sync_scope)
        self._data_refresh = QTimer(self)
        self._data_refresh.setSingleShot(True)
        self._data_refresh.setInterval(60)
        self._data_refresh.timeout.connect(self._reload_data)
        self.context.dataChanged.connect(self._refresh_data)
        from .native_notifications import NativeTaskCenter
        self.task_center = NativeTaskCenter(client, self.notifications_button, self)
        if hasattr(client, "requestFailed"):
            client.requestFailed.connect(self._notify_error)
        if hasattr(client, "mutationFinished"):
            client.mutationFinished.connect(self._request_finished)
        self.apply_preferences()
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._system_theme_changed)
        prefs = self.context.preferences.values
        start = prefs["last_page"] if prefs["remember_page"] else prefs["start_page"]
        self.nav.setCurrentIndex(max(0, min(4, int(start))))
        self._navigate(self.nav.currentIndex())
        self.statusBar().hide()

    def _focus_plate_tube(self, scope):
        self.context.set_scope(scope)
        self.nav.setCurrentIndex(1)

    def _navigate(self, index):
        if not 0 <= index < 5:
            return
        self.stack.setCurrentIndex(self._navigation_indices[index])
        page = self.stack.currentWidget()
        if hasattr(page, "set_workspace_scope"):
            page.set_workspace_scope(self.context.scope)
        self._navigation_save.start()

    def _save_navigation(self):
        try:
            self.context.preferences.save(last_page=self.nav.currentIndex())
        except OSError as exc:
            self.statusBar().showMessage(str(exc))

    def _system_theme_changed(self, *_):
        if self.context.preferences.values["theme"] == "system":
            self.apply_preferences()

    def open_settings(self, index=0):
        self.settings_dialog.maintenance_tabs.setCurrentIndex(1 if index == 6 else 0)
        index = 5 if index == 6 else index
        self.settings_dialog.nav.setCurrentRow(index)
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def _open_recycle(self):
        self.maintenance.tabs.setCurrentWidget(self.maintenance.recycle)
        self.maintenance.recycle.load()
        self.open_settings(6)

    def _open_record_context(self, scope):
        self.settings_dialog.hide()
        self.context.set_scope(scope)
        self.nav.setCurrentIndex(0)

    def _open_history_records(self, scope):
        self.settings_dialog.hide()
        self.workbench.scope_bar.set_scope(scope)
        self.workbench.analyst.clear()
        self.workbench.channel.setText(str(scope.get("thimble") or ""))
        self.workbench.column_filters.clear()
        self.workbench.detection_status.setCurrentIndex(0)
        self.workbench.maintenance_status.setCurrentIndex(0)
        self.workbench.apply_filters()
        self.nav.setCurrentIndex(0)

    def _sync_scope(self, scope):
        for index in (0, 1, 2, 3, 4):
            page = self.stack.widget(index)
            if hasattr(page, "set_workspace_scope"):
                page.set_workspace_scope(scope)

    def _refresh_data(self, *, workbench_fresh=False):
        if self._data_refresh.isActive():
            self._refresh_workbench |= not workbench_fresh
        else:
            self._refresh_workbench = not workbench_fresh
        self._data_refresh.start()

    def _reload_data(self):
        def overview_loaded(data, error):
            self.workbench._on_overview(data, error)
            for index in (0, 1, 3, 4):
                self.stack.widget(index).scope_bar._loaded(data, error)
            self.stack.widget(2)._overview_loaded(data, error)
        self.client.get("/api/overview", overview_loaded)
        if self._refresh_workbench:
            self.workbench.load_findings()
        self.workbench.refresh_selection()
        self.stack.widget(1).load()
        self.client.get("/api/settings/state-direction", self.stack.widget(1)._direction_loaded)
        self.client.get("/api/settings/state-direction", self.settings_dialog._direction_loaded)
        self.settings_dialog.rules_panel.load()
        self.settings_dialog.quality_panel.refresh_if_visible()
        analytics = self.stack.widget(3)
        analytics.load()
        analytics.load_complex_analysis()
        for page in (self.maintenance.audit, self.maintenance.quality, self.maintenance.batches,
                     self.maintenance.validation, self.maintenance.recycle):
            page.load()
        reports = self.stack.widget(4)
        reports.source_data_changed()

    def apply_preferences(self):
        prefs = self.context.preferences.values
        theme = prefs["theme"]
        if theme == "system":
            from PySide6.QtGui import QGuiApplication
            theme = "dark" if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"
        previous = getattr(self, "_applied_preferences", {})
        theme_changed = previous.get("theme") != theme
        density_changed = previous.get("density") != prefs["density"]
        severity_changed = any(previous.get(key) != prefs[key] for key in ("depth_levels", "depth_colors"))
        none_changed = previous.get("ndd_color") != prefs["ndd_color"]
        motion_changed = previous.get("animations") != prefs["animations"]
        analysis_changed = any(previous.get(key) != prefs[key] for key in ("ndd_zero", "point_labels"))
        if theme_changed or density_changed:
            self.setStyleSheet(workspace_styles(theme, prefs["density"]))
        if theme_changed:
            self.settings_dialog.set_theme(theme)
            for control in self.findChildren(QPushButton):
                if control.property("iconName"):
                    control.setIcon(icon(control.property("iconName"), theme))
            self.nav.set_theme(theme)
            for control, name in ((self.notifications_button, "bell"), (self.settings_button, "settings")):
                control.setIcon(colored_icon(name, "#a8b8b5" if theme == "dark" else "#b0bdc1"))
            self.workbench.map_panel.set_theme(theme)
            self.workbench.model.dark = theme == "dark"
            self.workbench.table.viewport().update()
            self.stack.widget(2).set_theme(theme)
        if severity_changed or none_changed:
            for plate in (self.workbench.plate, self.stack.widget(1).plate, self.stack.widget(3).visualization.plate):
                plate.levels = list(prefs["depth_levels"])
                plate.colors = list(prefs["depth_colors"])
                plate.none_color = prefs["ndd_color"]
                plate.update()
            if severity_changed:
                self.stack.widget(2).set_severity(prefs["depth_levels"], prefs["depth_colors"])
        visualization = self.stack.widget(3).visualization
        if theme_changed or motion_changed:
            visualization.set_theme(theme, prefs["animations"])
        if severity_changed or none_changed:
            visualization.set_severity(prefs["depth_levels"], prefs["depth_colors"], prefs["ndd_color"])
        if analysis_changed and visualization.set_analysis_options(prefs["ndd_zero"], prefs["point_labels"]):
            self.stack.widget(3).load()
            self.stack.widget(3).load_complex_analysis()
        if theme_changed or motion_changed or severity_changed or none_changed or analysis_changed:
            for dialog in self.stack.widget(3)._chart_windows:
                dialog.apply_preferences()
        if density_changed:
            self.workbench.table.verticalHeader().setDefaultSectionSize(28 if prefs["density"] == "compact" else 37)
        if self.workbench.auto_ndd != prefs["auto_ndd"]:
            self.workbench.auto_ndd = prefs["auto_ndd"]
            self.workbench.apply_filters()
        self._applied_preferences = {**prefs, "theme": theme, "depth_levels": list(prefs["depth_levels"]),
                                     "depth_colors": list(prefs["depth_colors"])}

    def _notify_error(self, path, error):
        self.statusBar().showMessage(error)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "utilities"):
            compact = self.width() <= 1100
            self.utilities.setFixedWidth(224 if compact else 256)
            self.account_button.set_compact(compact)
            self._account_spacing.changeSize(12 if compact else 25, 0)
            self.utilities.layout().invalidate()

    def _request_finished(self, path, data, error):
        if (error or not data or data.get("ok") is False or data.get("success") is False
                or any(data.get(key) for key in ("dry_run", "check_only", "requires_indication_decision", "unchanged"))):
            return
        read_only = {"/api/data-ledger/export", "/api/analysis/tube-history/export",
                     "/api/settings/data-source/validate", "/api/reports/preview",
                     "/api/reports/export", "/api/report-options", "/api/discover-server", "/api/import-excel-inspect",
                     "/api/data-quality/export", "/api/export-indication-warnings", "/api/backup-validate",
                     "/api/export-comparison", "/api/export-evolution", "/api/export-report", "/api/report-preview",
                     "/api/data/delete-preview", "/api/export-folder-excel", "/api/states/batch-preview",
                     "/api/states/import-preview", "/api/states/export", "/api/states/recognize-note",
                     "/api/import-directory-preview", "/api/security/image-export", "/api/audits/export",
                     "/api/backup", "/api/backup-policy", "/api/settings/data-source"}
        if path.startswith("/api/auth/") or path in read_only:
            return
        if self._data_refresh.isActive() and not self._refresh_workbench:
            return
        self.context.dataChanged.emit()

    def show_notifications(self):
        self.task_center.show()

    def _logout(self) -> None:
        self.client.post("/api/auth/logout", {}, lambda _data, _error: self.logoutRequested.emit())

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._navigation_save.isActive():
            self._navigation_save.stop()
            self._save_navigation()
        self.settings_dialog.close()
        for dialog in list(self.stack.widget(3)._chart_windows):
            dialog.close()
        three_d = self.stack.widget(2)
        if isinstance(three_d, NativeThreeDPage):
            three_d.shutdown()
        abort_all = getattr(self.client, "abort_all", None)
        if callable(abort_all):
            abort_all()
        self.closed.emit()
        super().closeEvent(event)
