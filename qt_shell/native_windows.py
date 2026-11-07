"""Native Qt Widgets workspace.

This is the first native slice: overview/data workbench, state maintenance,
analytics summary, import flow and settings/logout. The existing WebEngine
shell remains available as a fallback until the remaining specialist views are
migrated.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QUrl, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QGridLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtQuickWidgets import QQuickWidget

from .constants import APP_ICON, PRODUCT_NAME
from .native_client import NativeClient


class FindingsModel(QAbstractTableModel):
    headers = ["基地", "大修号", "机组", "通道", "堆芯位置", "三字符", "磨损深度", "状态", "分析人员"]
    fields = ["site_code", "outage", "unit_id", "thimble_id", "position", "display_conclusion", "percent", "state", "analyst"]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.rows: list[dict[str, Any]] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.rows):
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            value = self.rows[index.row()].get(self.fields[index.column()], "")
            if value is None:
                return ""
            if self.fields[index.column()] == "percent":
                return f"{value:g}%" if isinstance(value, (int, float)) else str(value)
            return str(value)
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() in {2, 3, 6}:
            return int(Qt.AlignmentFlag.AlignCenter)
        return None

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


class DataWorkbench(QWidget):
    def __init__(self, client: NativeClient, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.model = FindingsModel(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        title = QLabel("数据工作台")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        self.summary = QLabel("正在读取数据概况...")
        self.summary.setObjectName("muted")
        layout.addWidget(self.summary)

        filters = QHBoxLayout()
        self.site = QComboBox()
        self.site.setEditable(True)
        self.site.setPlaceholderText("基地")
        self.unit = QLineEdit()
        self.unit.setPlaceholderText("机组号")
        self.outage = QLineEdit()
        self.outage.setPlaceholderText("大修号")
        self.analyst = QLineEdit()
        self.analyst.setPlaceholderText("分析人员")
        self.channel = QLineEdit()
        self.channel.setPlaceholderText("通道号")
        self.page_size = QSpinBox()
        self.page_size.setRange(20, 500)
        self.page_size.setValue(100)
        self.search = QPushButton("查询")
        self.search.clicked.connect(self.load_findings)
        self.import_button = QPushButton("导入 Excel")
        self.import_button.clicked.connect(self.import_excel)
        for widget in (self.site, self.unit, self.outage, self.analyst, self.channel, self.page_size, self.search, self.import_button):
            filters.addWidget(widget)
        layout.addLayout(filters)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setDefaultSectionSize(32)
        layout.addWidget(self.table, 1)
        bottom = QHBoxLayout()
        self.status = QLabel("准备就绪")
        self.prev = QPushButton("上一页")
        self.next = QPushButton("下一页")
        self.prev.clicked.connect(lambda: self._change_page(-1))
        self.next.clicked.connect(lambda: self._change_page(1))
        bottom.addWidget(self.status)
        bottom.addStretch(1)
        bottom.addWidget(self.prev)
        bottom.addWidget(self.next)
        layout.addLayout(bottom)
        self.page = 1
        self.pages = 1
        self.load_overview()
        self.load_findings()

    def _params(self) -> str:
        from urllib.parse import urlencode
        values = {
            "page": self.page, "size": self.page_size.value(),
            "site": self.site.currentText().strip(), "unit": self.unit.text().strip(),
            "outage": self.outage.text().strip(), "analyst": self.analyst.text().strip(),
            "channel": self.channel.text().strip(),
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
        self.site.clear()
        self.site.addItems([""] + [str(item) for item in data.get("sites", [])])

    def load_findings(self) -> None:
        self.status.setText("正在加载...")
        self.client.get(f"/api/findings{self._params()}", self._on_findings)

    def _on_findings(self, data: dict[str, Any] | None, error: str | None) -> None:
        if error or not data:
            self.status.setText(error or "数据读取失败")
            self.model.replace([])
            return
        self.model.replace(data.get("items") or [])
        self.pages = max(1, int(data.get("pages") or 1))
        self.status.setText(f"第 {data.get('page', 1)} / {self.pages} 页，共 {data.get('total', 0):,} 条")
        self.prev.setEnabled(self.page > 1)
        self.next.setEnabled(self.page < self.pages)

    def _change_page(self, delta: int) -> None:
        self.page = max(1, min(self.pages, self.page + delta))
        self.load_findings()

    def import_excel(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 Excel 检测数据", "", "Excel (*.xlsx *.xlsm *.xls)")
        if not path:
            return
        self.import_button.setEnabled(False)
        self.status.setText("正在导入，完成前请勿关闭软件...")
        self.client.post("/api/import-excel", {"path": path, "blank_indication_policy": "review"}, self._on_import)

    def _on_import(self, data: dict[str, Any] | None, error: str | None) -> None:
        self.import_button.setEnabled(True)
        if error or not data:
            QMessageBox.warning(self, PRODUCT_NAME, error or "导入失败")
            self.status.setText("导入失败")
            return
        QMessageBox.information(self, PRODUCT_NAME, f"导入完成：{data.get('inserted', data.get('rows', 0))} 条记录")
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


class NativeStatePage(QWidget):
    def __init__(self, client: NativeClient, parent=None):
        super().__init__(parent)
        self.client = client
        self.model = StateModel(self)
        self.current: dict[str, Any] | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        title = QLabel("状态处理")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
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
        layout.addWidget(self.table, 1)
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
        self.refresh = QPushButton("刷新")
        self.refresh.clicked.connect(self.load)
        form.addWidget(self.state)
        form.addWidget(self.offset)
        form.addWidget(self.note, 1)
        form.addWidget(self.save)
        form.addWidget(self.refresh)
        layout.addLayout(form)
        self.load()

    def load(self):
        self.message.setText("正在读取状态记录...")
        self.client.get("/api/states", self._loaded)

    def _loaded(self, data, error):
        if error or not data:
            self.message.setText(error or "状态读取失败")
            self.model.replace([])
            return
        rows = data.get("items") or []
        self.model.replace(rows)
        self.message.setText(f"已加载 {len(rows):,} 条状态记录；保存操作会写入审计历史")

    def _select(self, index):
        self.current = self.model.rows[index.row()]
        state = str(self.current.get("state") or "normal")
        idx = self.state.findData(state)
        self.state.setCurrentIndex(max(0, idx))
        self.offset.setText("" if self.current.get("offset_mm") is None else str(self.current.get("offset_mm")))
        self.note.setText(str(self.current.get("note") or ""))

    def _save(self):
        if not self.current:
            QMessageBox.information(self, PRODUCT_NAME, "请先选择状态记录")
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
            "source": "native-qt",
        }
        self.save.setEnabled(False)
        self.client.post("/api/state", payload, self._saved)

    def _saved(self, data, error):
        self.save.setEnabled(True)
        if error:
            QMessageBox.warning(self, PRODUCT_NAME, error)
            return
        QMessageBox.information(self, PRODUCT_NAME, "状态已保存，审计记录已生成")
        self.load()


class NativeAnalyticsPage(QWidget):
    def __init__(self, client: NativeClient, parent=None):
        super().__init__(parent)
        self.client = client
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        title = QLabel("数据可视化")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        self.cards = QGridLayout()
        self.labels: dict[str, QLabel] = {}
        for index, (key, caption) in enumerate((
            ("totalTubes", "涉及套管"), ("activeDefects", "检测记录"),
            ("runningUnits", "机组数量"), ("activeOutages", "近 30 天大修"),
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
        self.detail = QLabel("正在加载统计摘要...")
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)
        refresh = QPushButton("刷新统计")
        refresh.clicked.connect(self.load)
        layout.addWidget(refresh, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        self.load()

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


class NativeReportsPage(QWidget):
    def __init__(self, client: NativeClient, parent=None):
        super().__init__(parent)
        self.client = client
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        title = QLabel("报告中心")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel("报告模板和导出操作通过本地数据服务执行。"))
        self.templates = QListWidget()
        layout.addWidget(self.templates, 1)
        self.status = QLabel("正在读取报告模板...")
        layout.addWidget(self.status)
        refresh = QPushButton("刷新模板")
        refresh.clicked.connect(self.load)
        layout.addWidget(refresh, 0, Qt.AlignmentFlag.AlignLeft)
        self.load()

    def load(self):
        self.client.get("/api/reports/templates", self._loaded)

    def _loaded(self, data, error):
        self.templates.clear()
        if error or not data:
            self.status.setText(error or "模板读取失败")
            return
        rows = data.get("items") or data.get("reports") or []
        if isinstance(rows, dict):
            rows = list(rows.values())
        for item in rows:
            if isinstance(item, dict):
                text = str(item.get("name") or item.get("title") or item.get("id") or item)
            else:
                text = str(item)
            self.templates.addItem(text)
        self.status.setText(f"已加载 {len(rows)} 个报告模板")


class NativeThreeDPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.view = QQuickWidget(self)
        self.view.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        qml = Path(__file__).with_name("native_threed.qml")
        self.view.setSource(QUrl.fromLocalFile(str(qml)))
        layout.addWidget(self.view)


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
        self.setWindowTitle(PRODUCT_NAME)
        self.resize(1480, 940)
        self.setMinimumSize(980, 680)
        if APP_ICON.is_file():
            from PySide6.QtGui import QIcon
            self.setWindowIcon(QIcon(str(APP_ICON)))

        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        self.nav = QListWidget()
        self.nav.setFixedWidth(210)
        for label in ("数据工作台", "状态处理", "三维模型", "数据可视化", "报告中心", "设置"):
            self.nav.addItem(QListWidgetItem(label))
        self.stack = QStackedWidget()
        self.workbench = DataWorkbench(client)
        self.stack.addWidget(self.workbench)
        self.stack.addWidget(NativeStatePage(client))
        self.stack.addWidget(NativeThreeDPage())
        self.stack.addWidget(NativeAnalyticsPage(client))
        self.stack.addWidget(NativeReportsPage(client))
        settings = SettingsPage(user)
        settings.logoutRequested.connect(self._logout)
        self.stack.addWidget(settings)
        layout.addWidget(self.nav)
        layout.addWidget(self.stack, 1)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        self.setStyleSheet(
            """
            QMainWindow { background: #f4f7f8; }
            QListWidget { background: #17324d; color: #e7eef5; border: 0; padding: 14px 10px; font-size: 14px; }
            QListWidget::item { padding: 13px 14px; margin: 2px 0; border-radius: 4px; }
            QListWidget::item:selected { background: #28658f; color: white; }
            QWidget { color: #253746; font-size: 13px; }
            #pageTitle { font-size: 22px; font-weight: 700; color: #16324f; }
            #muted { color: #607283; }
            QLineEdit, QComboBox, QSpinBox { min-height: 30px; border: 1px solid #c7d1da; border-radius: 4px; padding: 0 7px; background: white; }
            QPushButton { min-height: 30px; padding: 0 14px; border: 1px solid #b6c4cf; border-radius: 4px; background: white; }
            QPushButton:hover { background: #eaf2f7; }
            QTableView { background: white; border: 1px solid #d3dce3; gridline-color: #e6ebef; }
            QHeaderView::section { background: #e8eef2; padding: 7px; border: 0; font-weight: 600; }
            #metricCard { background: white; border: 1px solid #d3dce3; border-radius: 5px; }
            #metricValue { color: #1769aa; font-size: 22px; font-weight: 700; }
            """
        )

    def _logout(self) -> None:
        self.client.post("/api/auth/logout", {}, lambda _data, _error: self.logoutRequested.emit())

    def closeEvent(self, event: QCloseEvent) -> None:
        self.closed.emit()
        event.accept()
