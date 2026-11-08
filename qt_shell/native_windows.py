"""Native Qt Widgets workspaces, with Qt Charts and Qt Quick 3D."""
from __future__ import annotations

import json
import os
import uuid
import base64
import re
from pathlib import Path
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QIODevice, QModelIndex, QObject, QSaveFile, QUrl, QTimer, Qt, Signal
from PySide6.QtGui import QCloseEvent, QColor, QImage, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QComboBox,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QGridLayout,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSlider,
    QScrollArea,
    QStackedWidget,
    QSplitter,
    QStyledItemDelegate,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTabBar,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from .constants import APP_ICON, OUTPUT_DIR, PRODUCT_NAME, REPORT_DIR, USER_DATA
from .native_client import NativeClient
from .native_components import (
    PlateMap, ScopeBar, STATE_NAMES, ToolFlowLayout, WorkspaceContext, button, canonical_site, export_widget_image, icon, workspace_styles,
)


class FindingsModel(QAbstractTableModel):
    editRequested = Signal(int, str, object, object)
    selectionChanged = Signal()
    headers = ["选择", "序号", "大修", "机组", "通道编号", "堆芯位置", "三字符", "幅值（V）",
               "相位", "磨损深度（壁厚%）", "磨损位置", "测量通道", "探头类型",
               "分析人员", "数据", "数据组", "备注", "堵管移位信息"]
    fields = ["_checked", "_number", "outage", "unit_id", "thimble_id", "position",
              "indication", "volts", "degrees", "percent", "location", "channel",
              "probe", "analyst", "filename", "calgroup", "analysis", "maintenance_text"]
    editable_fields = set(fields[4:])

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.rows: list[dict[str, Any]] = []
        self.selected = {}
        self.editable = False
        self.page_offset = 0
        self.pending = set()

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
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if index.column() == 0:
                return ""
            if index.column() == 1:
                return self.page_offset + index.row() + 1
            value = row.get(field, "")
            if role == Qt.ItemDataRole.DisplayRole and field == "indication":
                value = row.get("display_conclusion") or value
            if value is None:
                return ""
            if field == "percent" and role == Qt.ItemDataRole.DisplayRole:
                return f"{value:g}%" if isinstance(value, (int, float)) else str(value)
            return str(value)
        if role == Qt.ItemDataRole.ToolTipRole:
            return str(row.get(field) or "")
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() in {1, 3, 4, 7, 8, 9}:
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
            if value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value):
                self.selected[row["id"]] = dict(row)
            else:
                self.selected.pop(row["id"], None)
            self.dataChanged.emit(index, index, [role])
            self.selectionChanged.emit()
            return True
        field = self.fields[index.column()]
        if role == Qt.ItemDataRole.EditRole and self.editable and field in self.editable_fields:
            key = (row["id"], field)
            if key in self.pending:
                return False
            if str(row.get(field) or "") == str(value):
                return False
            self.pending.add(key)
            self.editRequested.emit(row["id"], field, value, row.get(field))
            return True
        return False

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
    dataChanged = Signal()
    selectionChanged = Signal(list)
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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        title = QLabel("数据工作台")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        self.summary = QLabel("正在读取数据概况...")
        self.summary.setObjectName("muted")
        layout.addWidget(self.summary)

        actions = QHBoxLayout()
        self.ledger = button("导出综合台账", "file-down", self.export_ledger)
        self.delete = button("删除所选", "trash-2", self.delete_selected)
        self.clear = button("清空记录", "trash-2", self.clear_records)
        self.scope_bar = ScopeBar(client)
        self.site, self.unit, self.outage = self.scope_bar.site, self.scope_bar.unit, self.scope_bar.outage
        self.scope_bar.changed.connect(self._apply_scope)
        layout.addWidget(self.scope_bar)
        filters = QHBoxLayout()
        self.analyst = QLineEdit()
        self.analyst.setPlaceholderText("分析人员")
        self.channel = QLineEdit()
        self.channel.setPlaceholderText("通道号")
        from PySide6.QtGui import QIntValidator
        self.channel.setValidator(QIntValidator(1, 50, self.channel))
        self.page_size = QSpinBox()
        self.page_size.setRange(20, 500)
        self.page_size.setValue(100)
        self.search = QPushButton("查询")
        self.search.clicked.connect(self.apply_filters)
        self.import_button = QPushButton("导入 Excel")
        self.import_button.clicked.connect(self.import_excel)
        self.import_folder_button = QPushButton("导入 RPT 文件夹")
        self.import_folder_button.clicked.connect(self.import_rpt_folder)
        if self.permissions is not None and "data.import" not in self.permissions:
            self.import_button.setEnabled(False)
            self.import_folder_button.setEnabled(False)
            self.import_button.setToolTip("当前账户没有导入数据权限")
            self.import_folder_button.setToolTip("当前账户没有导入数据权限")
        for widget in (self.analyst, self.channel, self.page_size, self.search):
            filters.addWidget(widget)
        filters.addStretch()
        for widget in (self.import_button, self.import_folder_button, self.ledger, self.delete, self.clear):
            actions.addWidget(widget)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addLayout(filters)
        for control, permission in ((self.ledger, "export.create"), (self.delete, "data.delete"),
                                    (self.clear, "data.purge")):
            control.setEnabled(self.permissions is None or permission in self.permissions)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setColumnWidth(0, 45)
        self.table.setColumnWidth(1, 50)
        self.table.clicked.connect(self._record_clicked)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.table)
        map_host = QWidget()
        map_layout = QVBoxLayout(map_host)
        map_heading = QHBoxLayout()
        map_heading.addWidget(QLabel("堆芯分布"))
        self.map_unit = QSpinBox()
        self.map_unit.setRange(1, 99)
        self.map_unit.setPrefix("机组 ")
        self.map_unit.valueChanged.connect(self._update_plate)
        map_heading.addWidget(self.map_unit)
        map_heading.addWidget(button("导出图片", "download", self.export_plate))
        map_layout.addLayout(map_heading)
        self.plate = PlateMap()
        self.plate.tubeClicked.connect(self._tube_clicked)
        map_layout.addWidget(self.plate, 1)
        self.plate_detail = QLabel(" ")
        self.plate_detail.setWordWrap(True)
        map_layout.addWidget(self.plate_detail)
        self.selection_info = QLabel("已勾选 0 条")
        map_layout.addWidget(self.selection_info)
        map_layout.addWidget(button("勾选本页 / 取消本页", "check-check", self.toggle_page))
        map_layout.addWidget(button("清除全部勾选", "x", self.clear_selection))
        self.splitter.addWidget(map_host)
        self.splitter.setSizes([940, 380])
        layout.addWidget(self.splitter, 1)
        self.core_rows = []
        bottom = QHBoxLayout()
        self.status = QLabel("准备就绪")
        self.edit_hint = QLabel("双击可编辑字段")
        self.edit_hint.setObjectName("muted")
        self.edit_hint.setVisible(self.permissions is None or "data.edit" in self.permissions)
        self.edit_button = QPushButton("编辑选中记录")
        self.edit_button.clicked.connect(self.edit_selected_finding)
        if self.permissions is not None and "data.edit" not in self.permissions:
            self.edit_button.setEnabled(False)
            self.edit_button.setToolTip("当前账户没有检测记录编辑权限")
        self.prev = QPushButton("上一页")
        self.next = QPushButton("下一页")
        self.prev.clicked.connect(lambda: self._change_page(-1))
        self.next.clicked.connect(lambda: self._change_page(1))
        bottom.addWidget(self.status)
        bottom.addWidget(self.edit_hint)
        bottom.addStretch(1)
        bottom.addWidget(self.edit_button)
        bottom.addWidget(self.prev)
        bottom.addWidget(self.next)
        layout.addLayout(bottom)
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
        self.load_overview()
        self.load_findings()

    def _params(self) -> str:
        from urllib.parse import urlencode
        values = {
            "page": self.page, "size": self.page_size.value(),
            **self.scope_bar.values(), "analyst": self.analyst.text().strip(),
            "thimble": self.channel.text().strip(),
        }
        return "?" + urlencode({key: value for key, value in values.items() if value != ""})

    def load_overview(self) -> None:
        self.client.get("/api/overview", self._on_overview)

    def _on_overview(self, data: dict[str, Any] | None, error: str | None) -> None:
        if error or not data:
            self.summary.setText(error or "概况读取失败")
            return
        stats = data.get("stats") or {}
        self.summary.setText(
            f"检测记录 {stats.get('findings', 0):,} 条  |  大修 {stats.get('outages', 0)} 个  |  "
            f"机组 {stats.get('units', 0)} 个  |  分析人员 {stats.get('analysts', 0)} 人"
        )
        self.overview_data = data

    def apply_filters(self):
        if self.channel.text() and not self.channel.hasAcceptableInput():
            self.status.setText("通道号应为 1-50 的整数")
            return
        self.page = 1
        self.scopeChanged.emit({**self.scope_bar.values(), "thimble": self.channel.text().strip()})
        self.load_findings()

    def _apply_scope(self, scope):
        if not any(scope.values()):
            self.analyst.clear()
            self.channel.clear()
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

    def load_findings(self) -> None:
        self.status.setText("正在加载...")
        self._query_number += 1
        number = self._query_number
        self.client.get(f"/api/findings{self._params()}",
                        lambda data, error: self._on_findings(data, error) if number == self._query_number else None)

    def _on_findings(self, data: dict[str, Any] | None, error: str | None) -> None:
        if error or not data:
            self.status.setText(error or "数据读取失败")
            self.model.replace([])
            return
        self.page = int(data.get("page") or 1)
        self.model.page_offset = (self.page - 1) * self.page_size.value()
        self.model.replace(data.get("items") or [])
        self.core_rows = data.get("core_items") or []
        self._update_plate()
        self.pages = max(1, int(data.get("pages") or 1))
        self.status.setText(f"第 {data.get('page', 1)} / {self.pages} 页，共 {data.get('total', 0):,} 条")
        self.prev.setEnabled(self.page > 1)
        self.next.setEnabled(self.page < self.pages)

    def _change_page(self, delta: int) -> None:
        self.page = max(1, min(self.pages, self.page + delta))
        self.load_findings()

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
        self.edit_button.setEnabled(self.permissions is None or "data.edit" in self.permissions)
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
                self.model.selected[finding_id][field] = data.get("value")
                if field == "thimble_id":
                    from .native_model_data import reference_layout
                    unit = int(self.model.selected[finding_id]["unit_id"])
                    channel = next(c for c in reference_layout()["channels"]
                                   if int(c["serialOdd" if unit % 2 else "serialEven"]) == int(data["value"]))
                    self.model.selected[finding_id]["position"] = channel["pos"]
                self._selection_changed()
            self.status.setText("已保存，审计已记录")
            self.load_findings()
            self.dataChanged.emit()
        self.client.post("/api/findings/edit",
                         {"id": finding_id, "field": field, "value": value, "expected_value": expected}, done)

    def _selection_changed(self):
        self.selection_info.setText(f"已勾选 {len(self.model.selected):,} 条")
        self._update_plate()
        self.selectionChanged.emit(list(self.model.selected.values()))

    def clear_selection(self):
        self.model.selected.clear()
        self.model.layoutChanged.emit()
        self._selection_changed()

    def toggle_page(self):
        checked = not all(row["id"] in self.model.selected for row in self.model.rows)
        for row in self.model.rows:
            if checked:
                self.model.selected[row["id"]] = dict(row)
            else:
                self.model.selected.pop(row["id"], None)
        self.model.layoutChanged.emit()
        self._selection_changed()

    def _update_plate(self, *_):
        if not hasattr(self, "plate"):
            return
        unit = self.map_unit.value()
        selected = [row["thimble_id"] for row in self.model.selected.values() if int(row["unit_id"]) == unit]
        if getattr(self, "_workspace_tube", 0):
            selected.append(self._workspace_tube)
        self.plate.set_data([row for row in self.core_rows if int(row.get("unit_id") or 0) == unit],
                            unit, selected)

    def _record_clicked(self, index):
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

    def _tube_clicked(self, tube):
        rows = [row for row in self.core_rows if int(row.get("unit_id") or 0) == self.map_unit.value()
                and int(row.get("thimble_id") or 0) == tube]
        self.plate_detail.setText(f"{tube}号管 · 范围内 {len(rows)} 组检测结果\n" + "\n".join(
            f"{row.get('outage')} · {row.get('position')} · {row.get('percent', '/')}%" for row in rows[:8]))
        for number, row in enumerate(self.model.rows):
            if row["thimble_id"] == tube and row["unit_id"] == self.map_unit.value():
                self.table.selectRow(number)
                self.table.scrollTo(self.model.index(number, 4))
                break
        values = self.scope_bar.values()
        if values.get("unit") and values.get("outage"):
            self.scopeChanged.emit({**values, "thimble": str(tube)})

    def export_plate(self):
        export_widget_image(self, self.client, self.plate, "导出管板图片")

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

    def _open_import_wizard(self, mode):
        from .native_import import ImportWizard
        from .native_components import Preferences
        context = getattr(self.window(), "context", None)
        preferences = context.preferences.values if context else Preferences().values
        wizard = ImportWizard(self.client, self.MAPPING_FIELDS, preferences, self, mode=mode)
        wizard.imported.connect(self._wizard_imported)
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
        layout.setContentsMargins(22, 20, 22, 20)
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
    headers = ["基地", "大修号", "机组", "通道", "位置", "状态", "位移 mm", "备注", "更新时间"]
    fields = ["site_code", "outage", "unit_id", "thimble_id", "position", "state", "offset_mm", "note", "updated_at"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[dict[str, Any]] = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.fields)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.rows):
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            value = self.rows[index.row()].get(self.fields[index.column()], "")
            return "" if value is None else str(value)
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() in {2, 3, 6}:
            return int(Qt.AlignmentFlag.AlignCenter)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        return self.headers[section] if orientation == Qt.Orientation.Horizontal else section + 1

    def replace(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()


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


class NativeStatePage(QWidget):
    def __init__(self, client: NativeClient, user: dict[str, Any] | None = None, parent=None):
        super().__init__(parent)
        self.client = client
        self.permissions = None if user is None else set(user.get("permissions", []))
        self.model = StateModel(self)
        self.current: dict[str, Any] | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        title = QLabel("状态处理")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        self.scope_bar = ScopeBar(client)
        layout.addWidget(self.scope_bar)
        self.scope_bar.changed.connect(self._filter_scope)
        self.filter_text = QLineEdit()
        self.filter_text.setPlaceholderText("管号或备注")
        self.filter_text.textChanged.connect(lambda _: self._show_filtered())
        layout.addWidget(self.filter_text)
        self.message = QLabel("选择一条管状态记录进行维护")
        self.message.setObjectName("muted")
        layout.addWidget(self.message)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.clicked.connect(self._select)
        state_split = QSplitter()
        state_split.addWidget(self.table)
        map_host = QWidget()
        map_layout = QVBoxLayout(map_host)
        self.plate = PlateMap()
        self.plate.tubeClicked.connect(self._select_grid_tube)
        map_layout.addWidget(self.plate, 1)
        self.history = QPlainTextEdit()
        self.history.setReadOnly(True)
        self.history.setMaximumHeight(150)
        map_layout.addWidget(self.history)
        state_split.addWidget(map_host)
        state_split.setSizes([800, 360])
        layout.addWidget(state_split, 1)
        self.all_rows = []
        self._state_scope = {}
        self._scope_request = 0
        form = QHBoxLayout()
        self.state = QComboBox()
        self.state.addItem("正常", "normal")
        self.state.addItem("堵管", "plugged")
        self.state.addItem("移位", "shifted")
        self.state.addItem("换管", "replaced")
        self.offset = QLineEdit()
        self.offset.setPlaceholderText("位移量（mm）")
        self.note = QLineEdit()
        self.note.setPlaceholderText("状态备注")
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
        form.addWidget(self.state)
        form.addWidget(self.offset)
        form.addWidget(self.note, 1)
        form.addWidget(self.save)
        form.addWidget(self.advanced)
        form.addWidget(self.new_state)
        form.addWidget(self.refresh)
        layout.addLayout(form)
        bulk = QHBoxLayout()
        self.bulk_scope = QLabel("批量操作以当前选中记录的大修/机组为范围")
        self.bulk_scope.setObjectName("muted")
        self.bulk_normal = QPushButton("补齐未维护为正常")
        self.bulk_normal.clicked.connect(self._bulk_normal)
        self.import_button = QPushButton("导入状态表")
        self.import_button.clicked.connect(self._import_state_file)
        self.export_format = QComboBox()
        self.export_format.addItem("Excel", "xlsx")
        self.export_format.addItem("Word", "docx")
        self.export_format.addItem("统计 Excel", "summary")
        self.export_button = QPushButton("导出当前范围")
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
        bulk.addWidget(self.bulk_scope, 1)
        bulk.addWidget(self.bulk_normal)
        bulk.addWidget(self.import_button)
        bulk.addWidget(self.export_format)
        bulk.addWidget(self.export_button)
        bulk.addWidget(self.delete_button)
        layout.addLayout(bulk)
        self.load()

    def load(self):
        self.message.setText("正在读取状态记录...")
        self.client.get("/api/states", self._loaded)

    def _loaded(self, data, error):
        self.current = None
        self.bulk_scope.setText("批量操作以当前选中记录的大修/机组为范围")
        if error or not data:
            self.message.setText(error or "状态读取失败")
            self.model.replace([])
            return
        rows = data.get("items") or []
        self.all_rows = rows
        self._show_filtered()
        self.message.setText(f"已加载 {len(rows):,} 条状态记录；保存操作会写入审计历史")

    def set_workspace_scope(self, scope):
        normalized = {key: str(scope.get(key) or "") for key in ("site", "unit", "outage")}
        self.scope_bar.set_scope(normalized)
        if normalized != self._state_scope:
            self._filter_scope(normalized)
        if scope.get("thimble"):
            self.plate.selected = {int(scope["thimble"])}
            self.plate.update()

    def _filter_scope(self, scope):
        self._state_scope = scope
        self._scope_request += 1
        number = self._scope_request
        self._show_filtered()
        if scope.get("outage") and scope.get("unit"):
            from urllib.parse import urlencode
            self.client.get("/api/states/scope?" + urlencode({
                "outage": scope["outage"], "unit_id": scope["unit"], "details": "maintenance"}),
                lambda data, error: self.plate.set_data((data or {}).get("items", []),
                                                        int(scope["unit"]), mode="state")
                if number == self._scope_request and not error else None)

    def _show_filtered(self):
        scope = getattr(self, "_state_scope", {})
        text = self.filter_text.text().strip()
        rows = [row for row in getattr(self, "all_rows", [])
                if (not scope.get("site") or str(row.get("outage") or "").startswith(scope["site"]))
                and (not scope.get("unit") or str(row.get("unit_id")) == str(scope["unit"]))
                and (not scope.get("outage") or row.get("outage") == scope["outage"])
                and (not text or text in str(row.get("thimble_id")) or text in str(row.get("note") or ""))]
        self.model.replace(rows)
        self.plate.set_data(rows, int(scope.get("unit") or 1), mode="state")

    def _select_grid_tube(self, tube):
        for index, row in enumerate(self.model.rows):
            if row["thimble_id"] == tube:
                self.table.selectRow(index)
                self._select(self.model.index(index, 0))
                return
        scope = self._state_scope
        if not scope.get("unit") or not scope.get("outage"):
            self.message.setText("请选择具体机组和大修")
            return
        self.current = {"outage": scope["outage"], "unit_id": int(scope["unit"]),
                        "thimble_id": tube, "state": "normal", "events": [], "note": ""}
        self.message.setText(f"{tube}号管 · 本次尚未维护")
        self._edit_advanced()

    def _select(self, index):
        self.current = self.model.rows[index.row()]
        self.bulk_scope.setText(
            f"当前范围：{self.current.get('outage', '')} · {self.current.get('unit_id', '')}号机组"
        )
        state = str(self.current.get("state") or "normal")
        idx = self.state.findData(state)
        self.state.setCurrentIndex(max(0, idx))
        self.offset.setText("" if self.current.get("offset_mm") is None else str(self.current.get("offset_mm")))
        self.note.setText(str(self.current.get("note") or ""))
        from urllib.parse import urlencode
        self.client.get("/api/state-history?" + urlencode({
            "site": canonical_site(str(self.current["outage"]).rstrip("0123456789")),
            "unit_id": self.current["unit_id"], "thimble_id": self.current["thimble_id"]}),
            lambda data, error, selected=self.current: self._history_loaded(data, error)
            if self.current is selected else None)

    def _history_loaded(self, data, error):
        self.history.setPlainText(error or "\n".join(
            f"{row.get('created_at', '')} · {row.get('operator', '')} · {row.get('action', '')}\n"
            f"{row.get('after_json', '')}" for row in (data or {}).get("items", [])))

    def _save(self):
        if not self.current:
            QMessageBox.information(self, PRODUCT_NAME, "请先选择状态记录")
            return
        events = self.current.get("events") or []
        if len(events) > 1 or self.current.get("unsigned_offset_mm") is not None or self.current.get("offset_confirmed") == 0:
            QMessageBox.warning(
                self, PRODUCT_NAME,
                "该记录包含复合维护事件或尚未确认的位移方向，简化表单不能安全修改。"
                "请保留原记录，待完整维护界面核对后处理。",
            )
            return
        raw_offset = self.offset.text().strip()
        try:
            offset = float(raw_offset) if raw_offset else None
        except ValueError:
            QMessageBox.warning(self, PRODUCT_NAME, "位移量必须是数字")
            return
        payload = {
            "outage": self.current.get("outage"),
            "unit_id": self.current.get("unit_id"),
            "thimble_id": self.current.get("thimble_id"),
            "state": self.state.currentData(),
            "offset_mm": offset,
            "note": self.note.text(),
            "expected_updated_at": self.current.get("updated_at"),
        }
        self.save.setEnabled(False)
        self.client.post("/api/state", payload, self._saved)

    def _saved(self, data, error):
        self.save.setEnabled(self.permissions is None or "state.write" in self.permissions)
        self.advanced.setEnabled(self.permissions is None or "state.write" in self.permissions)
        self.new_state.setEnabled(self.permissions is None or "state.write" in self.permissions)
        if error:
            QMessageBox.warning(self, PRODUCT_NAME, error)
            return
        QMessageBox.information(self, PRODUCT_NAME, "状态已保存，审计记录已生成")
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
        if not indexes:
            QMessageBox.information(self, PRODUCT_NAME, "请先选择要删除的状态记录")
            return
        rows = [self.model.rows[index.row()] for index in indexes if 0 <= index.row() < len(self.model.rows)]
        if QMessageBox.warning(
            self, PRODUCT_NAME,
            f"将撤销 {len(rows)} 条维护记录（检测数据不会删除），是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self.delete_button.setEnabled(False)
        self.client.post(
            "/api/states/delete-batch",
            {"rows": rows, "confirmed": True},
            self._delete_done,
        )

    def _delete_done(self, data: dict[str, Any] | None, error: str | None) -> None:
        self.delete_button.setEnabled(self.permissions is None or "state.write" in self.permissions)
        if error or not data:
            QMessageBox.warning(self, PRODUCT_NAME, error or "状态撤销失败")
            return
        QMessageBox.information(self, PRODUCT_NAME, f"已撤销 {data.get('deleted', 0)} 条维护记录")
        self.load()


class NativeAnalyticsPage(QWidget):
    def __init__(self, client: NativeClient, user: dict[str, Any] | None = None, parent=None):
        super().__init__(parent)
        self.client = client
        self.permissions = None if user is None else set(user.get("permissions", []))
        self._analysis_request = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        title = QLabel("数据可视化")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        self.scope_bar = ScopeBar(client)
        layout.addWidget(self.scope_bar)
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
        scope.addWidget(QLabel("历史大修"))
        scope.addWidget(self.analysis_old)
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
        layout.addLayout(analysis_actions)
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
        self.analysis_details = QCheckBox("显示明细与质量诊断")
        self.analysis_details.toggled.connect(self.complex_tabs.setVisible)
        layout.addWidget(self.analysis_details)
        layout.addWidget(self.complex_tabs, 1)
        refresh = QPushButton("刷新统计")
        refresh.clicked.connect(self.load)
        layout.addWidget(refresh, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        self.load()

    def _scope_selected(self, scope):
        self.analysis_site.setText(scope.get("site") or "")
        self.analysis_unit.setValue(int(scope.get("unit") or 1))
        self.analysis_outage.setText(scope.get("outage") or "")
        self.load_complex_analysis()

    def set_workspace_scope(self, scope):
        previous = (self.analysis_site.text(), self.analysis_unit.value(), self.analysis_outage.text())
        self.scope_bar.set_scope(scope)
        current = (scope.get("site") or "", int(scope.get("unit") or 1), scope.get("outage") or "")
        if previous != current or not self.visualization.data:
            self._scope_selected(scope)
        if scope.get("thimble"):
            self.visualization.select_tube(int(scope["thimble"]))

    def load(self):
        self.client.get("/api/analytics/summary", self._loaded)

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
        sites = self.analysis_site.text().strip().upper()
        unit = self.analysis_unit.value()
        outage = self.analysis_outage.text().strip().upper()
        params = {
            "sites": sites,
            "unit": f"{sites}{unit}" if sites and self.scope_bar.values().get("unit") else "",
            "outage": outage,
        }
        self.complex_button.setEnabled(False)
        self.analysis_status.setText("正在计算趋势、相邻增量和覆盖质量...")
        self._analysis_request += 1
        number = self._analysis_request
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
        self._preview_number = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        title = QLabel("报告中心")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        self.report_tabs = QTabBar()
        self.report_tabs.addTab("检验报告单")
        self.report_tabs.addTab("检验结果比对表")
        layout.addWidget(self.report_tabs)
        self.scope_bar = ScopeBar(client)
        layout.addWidget(self.scope_bar)
        self.scope_bar.changed.connect(self._scope_selected)
        scope = QHBoxLayout()
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
        self.history_combo.setMinimumWidth(180)
        self.history_combo.setEditable(False)
        self.history_combo.currentTextChanged.connect(self.old_outage.setText)
        self.old_outage.hide()
        for label, control in (("历史大修", self.history_combo),):
            scope.addWidget(QLabel(label))
            scope.addWidget(control)
        for control in (self.site, self.unit, self.outage):
            control.hide()
        scope.addStretch()
        layout.addLayout(scope)
        actions = ToolFlowLayout()
        self.preview = QPushButton("生成预览")
        self.export = QPushButton("导出报告")
        self.export_format = QComboBox()
        self.export_format.addItem("DOCX", "docx")
        self.export_format.addItem("XLSX", "xlsx")
        header = QPushButton("表头信息")
        self.header_button = header
        self.edit_draft = QPushButton("编辑报告内容")
        self.edit_draft.setEnabled(False)
        self.edit_draft.clicked.connect(self.edit_report)
        clear_draft = QPushButton("清除报告修改")
        clear_draft.clicked.connect(self.clear_report_draft)
        self.use_selected = QCheckBox("仅使用工作台勾选记录")
        actions.addWidget(self.use_selected)
        header.clicked.connect(self.edit_header)
        self.preview.clicked.connect(self.preview_report)
        self.export.clicked.connect(self.export_report)
        self.export_copy = button("另存副本", "file-down", self.save_export_copy)
        self.export_copy.setEnabled(False)
        self._last_export_path = None
        if self.permissions is not None and "export.create" not in self.permissions:
            self.export.setEnabled(False)
            self.export.setToolTip("当前账户没有报告导出权限")
        actions.addWidget(self.preview)
        actions.addWidget(self.export)
        actions.addWidget(self.export_format)
        actions.addWidget(self.export_copy)
        actions.addWidget(header)
        actions.addWidget(self.edit_draft)
        actions.addWidget(clear_draft)
        layout.addLayout(actions)
        self.templates = QListWidget()
        self.templates.currentItemChanged.connect(self._template_changed)
        self.templates.hide()
        tools = QHBoxLayout()
        from .native_report_view import ReportPreview
        self.preview_text = ReportPreview()
        self.preview_text.cellEdited.connect(self._inline_report_edit)
        tools.addWidget(button("", "chevron-left", lambda: self.preview_text.horizontalScrollBar().triggerAction(
            self.preview_text.horizontalScrollBar().SliderAction.SliderPageStepSub)))
        tools.addWidget(button("-", None, lambda: self.preview_text.set_zoom(self.preview_text.zoom - .1)))
        tools.addWidget(button("+", None, lambda: self.preview_text.set_zoom(self.preview_text.zoom + .1)))
        tools.addWidget(button("适宽", None, self.preview_text.fit_width))
        tools.addWidget(button("保存修改并更新预览", "save", self.preview_report))
        tools.addStretch()
        layout.addLayout(tools)
        document = QSplitter(Qt.Orientation.Horizontal)
        document.addWidget(self.preview_text)
        self.draft_table = QTableWidget(0, 3)
        self.draft_table.setHorizontalHeaderLabels(["单元格", "原始值", "修改值"])
        self.draft_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.draft_table.hide()
        document.addWidget(self.draft_table)
        document.setSizes([900, 300])
        layout.addWidget(document, 1)
        self.sources_text = QPlainTextEdit()
        self.sources_text.setReadOnly(True)
        self.sources_text.setMaximumHeight(90)
        self.sources_text.hide()
        layout.addWidget(button("来源追溯", "files", lambda: self.sources_text.setVisible(self.sources_text.isHidden())))
        layout.addWidget(self.sources_text)
        self.status = QLabel("正在读取报告模板...")
        layout.addWidget(self.status)
        self.warnings = QPlainTextEdit()
        self.warnings.setReadOnly(True)
        self.warnings.setMaximumHeight(100)
        self.warnings.hide()
        layout.addWidget(self.warnings)
        refresh = QPushButton("刷新模板")
        refresh.clicked.connect(self.load)
        layout.addWidget(refresh, 0, Qt.AlignmentFlag.AlignLeft)
        self.load()
        self.kind.currentIndexChanged.connect(self._report_mode_changed)
        self.scope_bar.loaded.connect(lambda _scope: self._populate_history())
        self._report_mode_changed()

    def _invalidate_report(self):
        self._preview_number += 1
        self.snapshot_id = None
        self.preview.setEnabled(True)
        self.edit_draft.setEnabled(False)
        self.draft_edits = []
        self.draft_table.setRowCount(0)
        self.preview_text.setPlainText("选择范围后生成报告预览")

    def _report_mode_changed(self, *_):
        comparison = self.kind.currentData() == "comparison"
        self.use_selected.setEnabled(not comparison)
        self.use_selected.setVisible(not comparison)
        if comparison:
            self.use_selected.setChecked(False)
        self.header_button.setVisible(not comparison)
        self.history_combo.setEnabled(comparison and self.history_combo.count() > 1)
        self._invalidate_report()

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

    def set_workspace_scope(self, scope):
        self.scope_bar.set_scope(scope)
        self._scope_selected(scope)

    def _inline_report_edit(self, key, value):
        original = next((cell for cell in self.editable_cells if cell["key"] == key), {})
        changes = {edit["key"]: edit["value"] for edit in self.draft_edits}
        if value == str(original.get("source_value") or ""):
            changes.pop(key, None)
        else:
            changes[key] = value
        self.draft_edits = [{"key": k, "value": v} for k, v in changes.items()]
        self.snapshot_id = None
        self.draft_table.setRowCount(len(changes))
        cells = {cell["key"]: cell for cell in self.editable_cells}
        for row, (cell_key, cell_value) in enumerate(changes.items()):
            cell = cells.get(cell_key) or {}
            for col, text in enumerate((cell.get("label") or cell_key, cell.get("source_value") or "", cell_value)):
                self.draft_table.setItem(row, col, QTableWidgetItem(str(text)))
        self.status.setText(f"已修改 {len(changes)} 个单元格，请保存修改并更新预览")

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
            self.export_format.addItem(str(fmt).upper(), str(fmt))
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
                    self.export_format.addItem(str(fmt).upper(), str(fmt))
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
        if self.use_selected.isChecked():
            context = getattr(self.window(), "context", None)
            if not context or not context.selected:
                QMessageBox.warning(self, PRODUCT_NAME, "请先在工作台勾选当前范围的检测记录")
                return
        self.preview.setEnabled(False)
        self.snapshot_id = None
        self.edit_draft.setEnabled(False)
        self.preview_payload = self._payload()
        self._preview_number += 1
        number = self._preview_number
        self.status.setText("正在生成预览...")
        self.client.post("/api/reports/preview", self.preview_payload,
                         lambda data, error: self._on_preview(data, error) if number == self._preview_number else None)

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
        self.preview_text.setHtml(str(data.get("html") or ""))
        self.sources_text.setPlainText("\n".join(" | ".join("" if value is None else str(value) for value in row)
                                                for row in data.get("sources", [])))
        warnings = data.get("warnings") or []
        self.warnings.setPlainText("\n".join(
            f"{item.get('thimble_id') or '范围'}：{item.get('reason') or '请核查原始资料'}"
            for item in warnings if isinstance(item, dict)
        ))
        self.warnings.setVisible(bool(warnings))
        self.status.setText(
            f"报告预览已生成，{data.get('rows', 0)} 行，{len(warnings)} 条核查提示"
            + ("；50根管完整性未通过，不能导出" if data.get("coverage_complete") is False else "")
        )

    def edit_report(self) -> None:
        self.draft_table.setVisible(self.draft_table.isHidden())

    def clear_report_draft(self) -> None:
        if self.draft_edits:
            self.draft_edits = []
            self.snapshot_id = None
            self.edit_draft.setEnabled(False)
            self.status.setText("报告修改已清除，请重新生成预览")

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
        self.users_table = QTableWidget(0, 4)
        self.users_table.setHorizontalHeaderLabels(["用户名", "显示名称", "角色", "状态"])
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
        self.source = QWidget()
        source_layout = QVBoxLayout(self.source)
        source_form = QFormLayout()
        self.source_fields = {}
        for key, caption in (("engine", "数据库类型"), ("path", "业务库位置"),
                             ("exists", "文件状态"), ("size", "文件大小"),
                             ("integrity", "校验结果")):
            value = QLabel("正在读取…")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setWordWrap(True)
            self.source_fields[key] = value
            source_form.addRow(caption, value)
        source_layout.addLayout(source_form)
        self.source_text = QPlainTextEdit()
        self.source_text.setReadOnly(True)
        self.source_text.hide()
        source_layout.addWidget(button("诊断详情", "files",
                                       lambda: self.source_text.setVisible(self.source_text.isHidden())))
        source_layout.addWidget(self.source_text)
        source_actions = QHBoxLayout()
        source_refresh = QPushButton("读取数据源")
        source_validate = QPushButton("校验数据库")
        source_refresh.clicked.connect(self.load_source)
        source_validate.clicked.connect(self.validate_source)
        source_validate.setEnabled("settings.manage" in permissions)
        source_actions.addWidget(source_refresh)
        source_actions.addWidget(source_validate)
        source_actions.addStretch(1)
        source_layout.addLayout(source_actions)
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
        self.client.get("/api/settings/data-source", lambda data, error: self._source_loaded(data, error))

    def _source_loaded(self, data: dict[str, Any] | None, error: str | None) -> None:
        if error:
            self.source_text.setPlainText(error)
            return
        import json
        self.source_text.setPlainText(json.dumps(data or {}, ensure_ascii=False, indent=2))
        active = (data or {}).get("active") or {}
        values = {"engine": str(active.get("engine") or "").upper(),
                  "path": active.get("path") or "未提供",
                  "exists": "已存在" if active.get("exists") else "未找到",
                  "size": f"{active.get('size_bytes', 0) / 1024 / 1024:.2f} MB",
                  "integrity": (data or {}).get("message") or "尚未校验"}
        for key, value in values.items():
            self.source_fields[key].setText(value)

    def validate_source(self) -> None:
        self.client.post("/api/settings/data-source/validate", {"target": "local"},
                         self._source_loaded)

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

class _HeadlessThreeDRoot(QObject):
    """Small property/signal adapter used when no scene graph is available."""

    tubeSelected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._values = {
            "tubes": [], "yaw": 0, "pitch": -34, "zoomFactor": 1,
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
        self.request_number = 0
        self.rows: dict[int, dict[str, Any]] = {}
        self.record_details = {}
        self._scope_data = None
        self._pending_scope = {}
        self._syncing_scope = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        heading = QLabel("三维检测分布")
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        controls = QHBoxLayout()
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
        controls.addStretch(1)
        layout.addLayout(controls)
        views = QHBoxLayout()
        self.display_mode = QComboBox()
        for label, mode in (("整体布置", "assembly"), ("管板俯视", "plate"),
                            ("单管全长", "full"), ("管座装配", "socket")):
            self.display_mode.addItem(label, mode)
        self.display_mode.currentIndexChanged.connect(self._display_changed)
        views.addWidget(self.display_mode)
        self.tube_selector = QSpinBox()
        self.tube_selector.setRange(1, 50)
        self.tube_selector.setPrefix("管号 ")
        self.tube_selector.valueChanged.connect(self.show_tube)
        views.addWidget(self.tube_selector)
        self.visibility_checks = {}
        for label, prop, checked in (("容器包络", "showVessel", True), ("下封头", "showDome", True),
                                     ("支承板", "showPlates", True), ("支承柱", "showSupports", True),
                                     ("管座", "showSockets", True), ("管径放大", "enlargeTubes", True)):
            check = QCheckBox(label)
            check.setChecked(checked)
            check.toggled.connect(lambda value, name=prop: self._set_scene_property(name, value))
            self.visibility_checks[prop] = check
            views.addWidget(check)
        self.maintenance_preview = QCheckBox("维护后位置预览")
        self.maintenance_preview.toggled.connect(self._rebuild_scene)
        views.addWidget(self.maintenance_preview)
        views.addStretch()
        layout.addLayout(views)
        tools = QGridLayout()
        self.camera_preset = QComboBox()
        for label, angles in (("等轴视角", (0, -34)), ("正视", (0, 0)),
                               ("侧视", (90, 0)), ("俯视", (0, -89))):
            self.camera_preset.addItem(label, angles)
        self.camera_preset.currentIndexChanged.connect(self._camera_changed)
        tools.addWidget(self.camera_preset, 0, 0)
        self.type_filter = QComboBox()
        self.type_filter.addItem("全部管型", "")
        from .native_model_data import reference_layout
        for kind in sorted({str(c["type"]) for c in reference_layout()["channels"]}):
            self.type_filter.addItem(kind, kind)
        self.type_filter.currentIndexChanged.connect(
            lambda: self._set_scene_property("tubeType", self.type_filter.currentData()))
        tools.addWidget(self.type_filter, 0, 1)
        self.axes = QCheckBox("坐标轴")
        self.axes.setToolTip("X红 / Y绿 / Z蓝")
        self.axes.toggled.connect(lambda v: self._set_scene_property("showAxes", v))
        tools.addWidget(self.axes, 0, 2)
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(10, 100)
        self.opacity.setValue(65)
        self.opacity.setMaximumWidth(110)
        self.opacity.valueChanged.connect(lambda v: self._set_scene_property("modelOpacity", v / 100))
        tools.addWidget(QLabel("透明度"), 0, 3)
        tools.addWidget(self.opacity, 0, 4)
        self.explode = QSlider(Qt.Orientation.Horizontal)
        self.explode.setRange(0, 100)
        self.explode.setMaximumWidth(110)
        self.explode.valueChanged.connect(lambda v: self._set_scene_property("explode", v / 100))
        tools.addWidget(QLabel("装配展开"), 0, 5)
        tools.addWidget(self.explode, 0, 6)
        self.section = QCheckBox("剖切")
        self.section.toggled.connect(lambda v: self._set_scene_property("clipEnabled", v))
        tools.addWidget(self.section, 1, 0)
        self.section_axis = QComboBox()
        for axis in ("x", "y", "z"):
            self.section_axis.addItem(axis.upper(), axis)
        self.section_axis.currentIndexChanged.connect(
            lambda: self._set_scene_property("clipAxis", self.section_axis.currentData()))
        tools.addWidget(self.section_axis, 1, 1)
        self.section_offset = QSpinBox()
        self.section_offset.setRange(-10000, 10000)
        self.section_offset.setSingleStep(100)
        self.section_offset.setSuffix(" mm")
        self.section_offset.valueChanged.connect(lambda v: self._set_scene_property("clipOffset", v))
        tools.addWidget(self.section_offset, 1, 2)
        self.measurement = QCheckBox("两点测距")
        self.measurement.toggled.connect(lambda v: self._set_scene_property("measurementEnabled", v))
        tools.addWidget(self.measurement, 1, 3)
        self.measurement_value = QLabel()
        self.measurement_value.setWordWrap(True)
        tools.addWidget(self.measurement_value, 1, 4, 1, 3)
        self.image_export = button("导出 PNG", "download",
                                   lambda: export_widget_image(self, self.client, self.view, "导出三维视图"))
        tools.addWidget(self.image_export, 0, 7)
        tools.setColumnStretch(8, 1)
        layout.addLayout(tools)
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
            if hasattr(root, "measurementChanged"):
                root.measurementChanged.connect(self.measurement_value.setText)
            from .native_model_data import reference_layout
            root.setProperty("columns", [{**row, "meshId": f"column-{index}"}
                                         for index, row in enumerate(reference_layout()["structure"]["columns"])])
        self.view_container.setMinimumSize(320, 280)
        split = QSplitter()
        split.addWidget(self.view_container)
        detail_host = QWidget()
        detail_host.setMinimumWidth(240)
        detail_host.setMaximumWidth(390)
        detail_layout = QVBoxLayout(detail_host)
        self.detail = QLabel("选择管子查看检测记录与维护状态")
        self.detail.setWordWrap(True)
        detail_layout.addWidget(self.detail)
        self.records = QListWidget()
        self.records.currentRowChanged.connect(self._record_selected)
        detail_layout.addWidget(self.records, 1)
        self.record_detail = QPlainTextEdit()
        self.record_detail.setReadOnly(True)
        detail_layout.addWidget(self.record_detail, 1)
        split.addWidget(detail_host)
        split.setSizes([1000, 300])
        layout.addWidget(split, 1)
        self.load_overview()

    def _set_scene_property(self, name, value):
        root = self.view.rootObject()
        if root is not None:
            root.setProperty(name, value)

    def _display_changed(self):
        self._set_scene_property("displayMode", self.display_mode.currentData())
        self._set_scene_property("selectedTube", self.tube_selector.value())
        self._set_scene_property("measurementCount", 0)
        self.measurement_value.clear()
        self._reset_three_d_view()

    def _camera_changed(self):
        yaw, pitch = self.camera_preset.currentData()
        self._set_scene_property("yaw", yaw)
        self._set_scene_property("pitch", pitch)

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
        self.record_details = {}
        self.records.clear()
        self.record_detail.clear()
        root = self.view.rootObject()
        if root is not None:
            root.setProperty("tubes", [])
            root.setProperty("defects", [])
        self.detail.setText("选择管子查看检测记录与维护状态")
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
            self._set_scene_property("tubes", [])
            self._set_scene_property("defects", [])
            self.status.setText(str(exc))
            return
        root = self.view.rootObject()
        if root is None:
            self.status.setText("三维场景无法初始化")
            return
        self.rows = rows
        self.record_details = details
        root.setProperty("tubes", tubes)
        root.setProperty("defects", defects)
        self.status.setText(f"缺陷 {len(defects)} 处已定位，{len(unresolved)} 处位置待确认。"
                            "红：缺陷 | 黄：待复核 | 绿：NDD | 灰：无记录。原工程参考管长与布置；"
                            "P 位包含推导/推定基面，非电厂实测标定。")
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
        root = self.view.rootObject()
        if root is not None:
            root.setProperty("yaw", 0)
            mode = self.display_mode.currentData()
            root.setProperty("pitch", -89 if mode == "plate" else -34)
            root.setProperty("zoomFactor", 1.8 if mode in {"plate", "full"} else 1)
            root.setProperty("panX", 0)
            root.setProperty("panY", 0)

    def show_tube(self, number: int) -> None:
        row = self.rows.get(number)
        if not row:
            return
        self.tube_selector.blockSignals(True)
        self.tube_selector.setValue(number)
        self.tube_selector.blockSignals(False)
        self._set_scene_property("selectedTube", number)
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
        layout.setContentsMargins(22, 20, 22, 20)
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
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        top = QWidget()
        top.setObjectName("topNavigation")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(14, 8, 14, 8)
        self.nav = QTabBar()
        self.nav.setExpanding(False)
        for label, name in (("数据工作台", "database"), ("三维缺陷模型", "box"),
                            ("数据可视化", "chart-no-axes-combined"), ("报告中心", "files"),
                            ("状态处理", "wrench")):
            self.nav.addTab(icon(name), label)
        top_layout.addWidget(self.nav)
        top_layout.addStretch()
        self.account_button = button(str(user.get("display_name") or user.get("username") or "账户"),
                                      None, lambda: self.open_settings(4))
        self.notifications_button = button("", "bell", self.show_notifications)
        self.notifications_button.setToolTip("通知中心")
        self.settings_button = button("", "settings", lambda: self.open_settings(0))
        self.settings_button.setToolTip("软件设置")
        for control in (self.account_button, self.notifications_button, self.settings_button):
            top_layout.addWidget(control)
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
        self.stack.widget(2).scopeChanged.connect(self.context.set_scope)
        self.stack.widget(3).visualization.scopeChanged.connect(self.context.set_scope)
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
        self.statusBar().showMessage("本机服务已连接 · SQLite")

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
        self.settings_dialog.nav.setCurrentRow(index)
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def _open_record_context(self, scope):
        self.settings_dialog.hide()
        self.context.set_scope(scope)
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
        self.stack.widget(1).load()
        analytics = self.stack.widget(3)
        analytics.load()
        analytics.load_complex_analysis()
        for page in (self.maintenance.audit, self.maintenance.quality, self.maintenance.batches,
                     self.maintenance.validation, self.maintenance.recycle):
            page.load()
        reports = self.stack.widget(4)
        reports._invalidate_report()
        reports.status.setText("业务数据已更新，请重新生成报告预览")

    def apply_preferences(self):
        prefs = self.context.preferences.values
        theme = prefs["theme"]
        if theme == "system":
            from PySide6.QtGui import QGuiApplication
            theme = "dark" if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"
        self.setStyleSheet(workspace_styles(theme, prefs["density"]))
        for control in self.findChildren(QPushButton):
            if control.property("iconName"):
                control.setIcon(icon(control.property("iconName"), theme))
        for index, name in enumerate(("database", "box", "chart-no-axes-combined", "files", "wrench")):
            self.nav.setTabIcon(index, icon(name, theme))
        for plate in (self.workbench.plate, self.stack.widget(1).plate, self.stack.widget(3).visualization.plate):
            plate.levels = list(prefs["depth_levels"])
            plate.colors = list(prefs["depth_colors"])
            plate.update()
        visualization = self.stack.widget(3).visualization
        visualization.set_theme(theme, prefs["animations"])
        self.workbench.table.verticalHeader().setDefaultSectionSize(27 if prefs["density"] == "compact" else 34)

    def _notify_error(self, path, error):
        self.statusBar().showMessage(error)

    def _request_finished(self, path, data, error):
        if (data or {}).get("dry_run") or (data or {}).get("check_only"):
            return
        if not error and path in {"/api/state", "/api/states/batch", "/api/states/delete-batch",
                                  "/api/states/import", "/api/recycle-bin/restore", "/api/import",
                                  "/api/import-excel", "/api/deduplicate", "/api/import-batches/action",
                                  "/api/cross-group-reviews", "/api/state-delete"}:
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
        three_d = self.stack.widget(2)
        if isinstance(three_d, NativeThreeDPage):
            three_d.shutdown()
        abort_all = getattr(self.client, "abort_all", None)
        if callable(abort_all):
            abort_all()
        self.closed.emit()
        super().closeEvent(event)
