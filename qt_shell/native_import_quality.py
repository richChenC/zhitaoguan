"""Native import audit lists, batch recovery and version-checked source review."""
from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from PySide6.QtCore import QIODevice, QRect, QSaveFile, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QRadioButton, QSizePolicy,
    QStyle, QStyledItemDelegate, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .native_components import ToolFlowLayout, button, icon


CATEGORIES = {
    "PARSE_FAILED": "解析失败", "IMPORT_FAILED": "导入失败", "ECT_REFERENCE": "ECT 关联错误",
    "ECT_HEADER_MISMATCH": "ECT 文件名校验", "MAPPING_ERROR": "管号/坐标映射",
    "SUM_WARNING": "SUM 信息校验", "MISSING_REPORT": "未报告 ECT", "MISSING_REPORT_FILE": "缺失报告",
    "DUPLICATE_ACQUISITION": "重复采集", "HASH_CONFLICT": "哈希冲突", "DUPLICATE_IMPORT": "重复导入",
    "BLANK_INDICATION": "三字符待确认", "INVALID_SCOPE": "必填信息/管号错误",
    "UNIT_OUTAGE_MISMATCH": "机组与大修不一致", "FILE_READ_FAILED": "文件读取失败",
    "RPT_UNIT_MISMATCH": "RPT 与 SUM 机组冲突", "CROSS_GROUP_DUPLICATE": "跨组相同缺陷待复核",
    "SET_UNPARSED": "SET 配置未解析",
}
STATUSES = {"running": "导入中", "completed": "已完成", "failed": "失败",
            "awaiting_confirmation": "待确认", "rolled_back": "已回滚", "cleared": "记录已清空"}
REVIEW_STATUSES = {"pending": "待复核", "representative": "已指定统计代表",
                   "keep_all": "已确认保留全部", "reset": "已撤销，待复核"}
PARSE_STATUSES = {"parsed": "已解析", "parsed_configuration": "配置已解析",
                  "archived_unparsed": "已归档，未解析", "candidate": "保留候选", "failed": "解析失败"}
LISTS = ("issues", "batches", "artifacts", "versions", "reviews")


def text(value):
    return "" if value is None else str(value)


def timestamp(value):
    raw = text(value).strip()
    if not raw:
        return "/"
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone()
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return raw


def plain(text_value="", name="qualityText"):
    control = QLabel(text(text_value))
    control.setObjectName(name)
    control.setTextFormat(Qt.TextFormat.PlainText)
    control.setWordWrap(True)
    control.setMinimumWidth(0)
    control.setToolTip(text(text_value))
    return control


class AuditTable(QTableWidget):
    """Bounded native table with complete, plain-text source values in tooltips."""
    def __init__(self, headers, rows, parent=None, *, row_height=40):
        super().__init__(len(rows), len(headers), parent)
        self._row_height = row_height
        self.setObjectName("qualityTable")
        self.setHorizontalHeaderLabels(headers)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setWordWrap(False)
        self.setShowGrid(False)
        self.setItemDelegate(AuditCellDelegate(self))
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(row_height)
        self.horizontalHeader().setMinimumSectionSize(40)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.horizontalHeader().setStretchLastSection(False)
        self.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.horizontalHeader().setFixedHeight(38)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                item = QTableWidgetItem(text(value))
                item.setToolTip(text(value))
                self.setItem(row, column, item)
        body_font, head_font = QFont("Microsoft YaHei"), QFont("Microsoft YaHei")
        body_font.setPixelSize(12)
        head_font.setPixelSize(11)
        body_metrics, head_metrics = QFontMetrics(body_font), QFontMetrics(head_font)
        self._widths = [min(340, max(
            [head_metrics.horizontalAdvance(header) + 26] +
            [body_metrics.horizontalAdvance(text(row[column])) + 26 for row in rows]))
            for column, header in enumerate(headers)]
        self._row_count = len(rows)
        self.horizontalScrollBar().rangeChanged.connect(lambda *_: self._height())
        self._height()

    def _height(self):
        scrollbar = self.horizontalScrollBar()
        extra = max(15, scrollbar.sizeHint().height()) if scrollbar.maximum() else 0
        self.setFixedHeight(min(340, 38 + max(1, self._row_count) *
                                (self._row_height if self._row_count else 44) + extra))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        surplus = max(0, self.viewport().width() - sum(self._widths))
        for column, width in enumerate(self._widths):
            self.setColumnWidth(column, width + surplus // self.columnCount())
        self._height()


class AuditCellDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        painter.save()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        painter.setFont(option.font)
        painter.setPen(option.palette.color(QPalette.ColorRole.Text))
        area = option.rect.adjusted(13, 0, -13, 0)
        value = QFontMetrics(option.font).elidedText(text(index.data()), Qt.TextElideMode.ElideRight,
                                                   max(0, area.width()))
        painter.drawText(area, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, value)
        color = option.palette.color(QPalette.ColorRole.Text)
        color.setAlpha(30)
        painter.setPen(color)
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
        painter.restore()


class AuditStatus(QLabel):
    def __init__(self):
        super().__init__()
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setMinimumWidth(0)
        self.setObjectName("qualityStatus")

    def setText(self, value):
        super().setText(value)
        self._height()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._height()

    def _height(self):
        metrics = QFontMetrics(self.font())
        bounds = metrics.boundingRect(QRect(0, 0, max(1, self.width() - 32), 100000),
                                      Qt.TextFlag.TextWordWrap, self.text())
        lines = max(1, math.ceil(bounds.height() / max(1, metrics.height())))
        self.setFixedHeight(round(lines * 18.6 + 10))


class RepresentativeRadio(QRadioButton):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    def hitButton(self, point):
        return self.rect().contains(point)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = QColor("#006b78" if self.isEnabled() else "#929ca2")
        painter.setPen(QPen(accent if self.isChecked() else QColor("#808080"), 1))
        painter.setBrush(QColor("#3b3b3b" if self.panel.theme == "dark" else "#ffffff"))
        painter.drawEllipse(self.rect().adjusted(1, 1, -1, -1))
        if self.isChecked():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawEllipse(self.rect().adjusted(9, 9, -9, -9))
        if self.hasFocus():
            painter.setPen(QPen(accent, 1, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.rect().adjusted(0, 0, -1, -1))


class ReviewGroup(QWidget):
    def __init__(self, panel, group):
        super().__init__()
        self.panel, self.group = panel, group
        self.setObjectName("qualityReview")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(0)
        self.header = QWidget()
        self.header.setObjectName("qualityReviewHeader")
        self.header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.header.setFixedHeight(72)
        heading = self.heading = QHBoxLayout(self.header)
        heading.setSpacing(12)
        heading.setContentsMargins(28, 0, 28, 0)
        title = plain(f"{group.get('outage', '')} · TH{group.get('thimble_id', '')} · "
                      f"{group.get('analyst', '')}", "qualityReviewTitle")
        heading.addWidget(title, 1)
        heading.addWidget(plain(REVIEW_STATUSES.get(group.get("status"), "待复核"), "qualityHint"))
        root.addWidget(self.header)
        root.addSpacing(8)
        fields = ("id", "calgroup", "location", "volts", "degrees", "percent", "indication",
                  "measurement_type", "channel", "report_path")
        members = group.get("members") or []
        self.table = AuditTable(["统计代表", "记录", "数据组", "位置", "幅值(V)", "相位(°)",
                                 "壁厚(%)", "显示", "测量类型", "通道", "来源报告"],
                                [["", *(row.get(key) for key in fields)] for row in members], row_height=64)
        self.radios = QButtonGroup(self)
        for index, row in enumerate(members):
            radio = RepresentativeRadio(panel)
            radio.setObjectName("qualityRepresentative")
            radio.setFixedSize(38, 38)
            radio.setAccessibleName(f"选择记录 {row['id']} 为统计代表")
            radio.setChecked(row["id"] == group.get("representative_id"))
            self.radios.addButton(radio, row["id"])
            host = QWidget()
            layout = QHBoxLayout(host)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(radio, 0, Qt.AlignmentFlag.AlignCenter)
            self.table.setCellWidget(index, 0, host)
        root.addWidget(self.table)
        root.addSpacing(10)
        tools = self.tools = QWidget()
        actions = QHBoxLayout(tools)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        self.reason = QLineEdit()
        self.reason.setObjectName("qualityReason")
        self.reason.setAccessibleName("复核依据")
        self.reason.setPlaceholderText("复核依据")
        self.reason.setMaxLength(1000)
        self.reason.setFixedHeight(38)
        self.reason.setMinimumWidth(140)
        actions.addWidget(self.reason, 1)
        self.actions = {}
        for title, action in (("采用所选代表", "representative"), ("保留全部", "keep_all"), ("撤销复核", "reset")):
            control = button(title, None, lambda _checked=False, action=action: panel.save_review(self, action))
            control.setObjectName("qualityReviewAction")
            control.setFixedSize(98 if action == "representative" else 74, 36)
            self.actions[action] = control
            actions.addWidget(control)
        root.addWidget(tools)
        history = group.get("history") or []
        self.history_toggle = None
        if history:
            root.addSpacing(10)
            self.history_toggle = button(f"复核历史（{len(history)}）", "chevron-right")
            self.history_toggle.setObjectName("qualityHistoryToggle")
            self.history_toggle.setCheckable(True)
            self.history_toggle.setFixedHeight(31)
            root.addWidget(self.history_toggle)
            self.history = AuditTable(["时间", "操作人员", "决定", "代表记录", "依据", "状态"], [
                [timestamp(row.get("created_at")), row.get("operator"),
                 REVIEW_STATUSES.get(row.get("action"), row.get("action")), row.get("representative_id"),
                 row.get("reason"), "当前" if row.get("active") else "已失效/被替代"] for row in history])
            self.history.hide()
            self.history_toggle.toggled.connect(self._history_toggled)
            root.addWidget(self.history)
        draft = panel.review_drafts.get((group["group_key"], group["revision"]))
        if draft:
            self.reason.setText(draft["reason"])
            selected = self.radios.button(draft["selected"])
            if selected:
                selected.setChecked(True)
        self.set_writable()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        padding = 14 if self.window().width() <= 900 else 28
        self.heading.setContentsMargins(padding, 0, padding, 0)

    def _history_toggled(self, expanded):
        self.history.setVisible(expanded)
        name = "chevron-down" if expanded else "chevron-right"
        self.history_toggle.setProperty("iconName", name)
        self.history_toggle.setIcon(icon(name, self.panel.theme))

    def set_writable(self):
        allowed = self.panel.fresh and not self.panel.busy and self.panel.allowed("review.write")
        self.reason.setEnabled(allowed)
        for control in self.radios.buttons():
            control.setEnabled(allowed)
        for action, control in self.actions.items():
            control.setEnabled(allowed and (action != "reset" or bool(self.group.get("history"))))


class ImportQualityPanel(QWidget):
    changed = Signal()

    def __init__(self, client, permissions, parent=None):
        super().__init__(parent)
        self.client, self.permissions = client, set(permissions or [])
        self.serial, self.feedback_revision = 0, 0
        self.data, self.review_data = {}, {}
        self.page, self.current_list = 1, "issues"
        self.fresh = self.busy = self.reading = self.export_busy = False
        self.export_file = None
        self.review_widgets, self.review_drafts = [], {}
        self.theme = "light"
        self._confirming = False
        self.setObjectName("importQuality")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.toggle = button("数据质量与导入审计", "chevron-down")
        self.toggle.setObjectName("qualityHeading")
        self.toggle.setCheckable(True)
        self.toggle.setChecked(True)
        self.toggle.toggled.connect(self._expanded)
        root.addWidget(self.toggle)
        self.body = QWidget()
        box = QVBoxLayout(self.body)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        root.addWidget(self.body)
        self.toolbar = QWidget()
        self.toolbar.setObjectName("qualityToolbar")
        self.tools = ToolFlowLayout(self.toolbar)
        self.tools.bottom_aligned = True
        self.tools.setContentsMargins(16, 0, 16, 12)
        self.tools.setSpacing(10)
        self.batch, self.category = QComboBox(), QComboBox()
        self.batch.addItem("全部批次", "")
        self.category.addItem("全部类型", "")
        for code, name in CATEGORIES.items():
            self.category.addItem(name, code)
        self.filter_hosts = []
        for title, control in (("导入批次", self.batch), ("异常类型", self.category)):
            host = QWidget()
            column = QVBoxLayout(host)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(5)
            caption = plain(title, "qualityHint")
            caption.setFixedHeight(19)
            column.addWidget(caption)
            control.setAccessibleName(title)
            control.setMinimumWidth(0)
            control.setFixedHeight(34)
            column.addWidget(control)
            self.filter_hosts.append(host)
            self.tools.addWidget(host)
            control.currentIndexChanged.connect(self._filters_changed)
        self.refresh_button = button("", "refresh-cw", lambda: self.refresh())
        self.refresh_button.setAccessibleName("刷新清单")
        self.refresh_button.setToolTip("刷新清单")
        self.refresh_button.setFixedSize(36, 36)
        self.export = button("导出数据与审计清单", None, self.export_quality)
        self.rollback = button("回滚本批次", None, lambda: self.batch_action("rollback"))
        self.restore = button("恢复本批次", None, lambda: self.batch_action("restore"))
        for control, width in ((self.refresh_button, 36), (self.export, 134), (self.rollback, 86), (self.restore, 86)):
            control.setObjectName("qualityTool")
            control.setFixedSize(width, 36)
            self.tools.addWidget(control)
        box.addWidget(self.toolbar)
        self.status = AuditStatus()
        self.status.setAccessibleName("审计状态")
        box.addWidget(self.status)
        self.retry = button("重新保存", None, self.save_export)
        self.retry.setObjectName("qualityRetry")
        self.retry.hide()
        retry_line = QHBoxLayout()
        retry_line.setContentsMargins(16, 0, 16, 0)
        retry_line.addWidget(self.retry, 0, Qt.AlignmentFlag.AlignLeft)
        retry_line.addStretch()
        box.addLayout(retry_line)
        self.tabs_host = QWidget()
        self.tabs_host.setObjectName("qualityTabs")
        tabs_layout = ToolFlowLayout(self.tabs_host)
        tabs_layout.setContentsMargins(16, 10, 16, 10)
        tabs_layout.setSpacing(4)
        self.tabs = QButtonGroup(self)
        for index, title in enumerate(("校验问题", "导入批次", "文件校验", "报告版本", "跨组复核")):
            control = button(title)
            control.setObjectName("qualityTab")
            control.setCheckable(True)
            control.setChecked(index == 0)
            control.setFixedSize(72, 36)
            self.tabs.addButton(control, index)
            tabs_layout.addWidget(control)
        self.tabs.idClicked.connect(self._tab_changed)
        box.addWidget(self.tabs_host)
        self.rows_host = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(0)
        box.addWidget(self.rows_host)
        self.pager = QWidget()
        self.pager.setObjectName("qualityPager")
        pager = QHBoxLayout(self.pager)
        pager.setContentsMargins(16, 10, 16, 10)
        pager.setSpacing(12)
        pager.addStretch()
        self.previous = button("", "chevron-left", lambda: self.change_page(-1))
        self.next = button("", "chevron-right", lambda: self.change_page(1))
        for control, title in ((self.previous, "上一页"), (self.next, "下一页")):
            control.setFixedSize(36, 36)
            control.setAccessibleName(title)
            control.setToolTip(title)
        self.page_label = plain("", "qualityHint")
        self.page_label.setWordWrap(False)
        pager.addWidget(self.previous)
        pager.addWidget(self.page_label)
        pager.addWidget(self.next)
        box.addWidget(self.pager)
        self.table = None
        self._render()

    def allowed(self, permission):
        return permission in self.permissions

    def _expanded(self, expanded):
        self.body.setVisible(expanded)
        self.toggle.setIcon(icon("chevron-down" if expanded else "chevron-right", self.theme))
        if expanded:
            self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        if self.toggle.isChecked() and not self.reading and not self.fresh:
            self.refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.filter_hosts[0].setFixedWidth(340)
        self.filter_hosts[1].setFixedWidth(220)
        self.tools.invalidate()

    def set_theme(self, theme):
        self.theme = theme
        for control in self.findChildren(QPushButton):
            if control.property("iconName"):
                control.setIcon(icon(control.property("iconName"), theme))
        self.toggle.setIcon(icon("chevron-down" if self.toggle.isChecked() else "chevron-right", theme))

    def _filters_changed(self, *_):
        if self.busy:
            return
        self.page = 1
        self.refresh()

    def _tab_changed(self, index):
        if self.busy:
            return
        self.current_list, self.page = LISTS[index], 1
        self.fresh = False
        self._render()
        self.refresh()

    def change_page(self, delta):
        if self.busy or self.reading:
            return
        target = self.page + delta
        if 1 <= target <= self.pages():
            self.page = target
            self.refresh()

    def payload(self):
        return {"batch_id": self.batch.currentData() or "", "category": self.category.currentData() or ""}

    def refresh_if_visible(self):
        if self.isVisible() and self.toggle.isChecked() and not self.busy:
            self.refresh(quiet=True)

    def refresh(self, *, quiet=False, completion=None):
        if self.busy and completion is None:
            return
        if not self.allowed("data.read"):
            self.fresh = False
            self.status.setText("没有读取审计清单的权限")
            self._controls()
            return
        self.serial += 1
        serial = self.serial
        if not quiet:
            self.feedback_revision += 1
        feedback = self.feedback_revision
        self.fresh, self.reading = False, True
        if not quiet:
            self.status.setText("正在读取本机审计记录...")
        self._controls()
        query = urlencode({**self.payload(), "page": self.page, "size": 50})

        def finish(data, error, reviews=None):
            if serial != self.serial:
                return
            self.reading = False
            if error or not isinstance(data, dict) or "totals" not in data:
                message = error or "本地服务返回的审计数据不完整"
                self.fresh = False
                if feedback == self.feedback_revision:
                    self.status.setText(f"审计列表读取失败：{message}。请点击刷新后继续操作。")
                self._controls()
                if completion:
                    completion(False, message)
                return
            self.data = data
            if reviews is not None:
                self.review_data = reviews
            selected = self.batch.currentData()
            with QSignalBlocker(self.batch):
                self.batch.clear()
                self.batch.addItem("全部批次", "")
                for row in data.get("batches") or []:
                    filename = text(row.get("source_path")).replace("\\", "/").rsplit("/", 1)[-1]
                    title = (f"#{row['id']} · {timestamp(row.get('started_at'))} · "
                             f"{STATUSES.get(row.get('status'), row.get('status', ''))} · {filename}")
                    self.batch.addItem(title, text(row["id"]))
                    self.batch.setItemData(self.batch.count() - 1, title, Qt.ItemDataRole.ToolTipRole)
                index = self.batch.findData(selected or "")
                if index < 0:
                    self.batch.addItem(f"#{selected}", selected)
                    index = self.batch.count() - 1
                self.batch.setCurrentIndex(index)
            self.fresh = True
            if self.page > self.pages():
                self.page = self.pages()
                self.refresh(quiet=quiet, completion=completion)
                return
            if feedback == self.feedback_revision and not quiet:
                legacy = (f" · {data['legacy_rows']} 条历史记录没有批次信息，无法补推原始导入过程"
                          if data.get("legacy_rows") else "")
                self.status.setText(f"校验问题 {data['totals'].get('issues', 0)} 项 · "
                                    f"文件 {data['totals'].get('artifacts', 0)} 个{legacy}。"
                                    "导出包含概览、有效检测记录和各类审计清单；异常类型仅筛选校验问题。")
            self._render()
            if completion:
                completion(True, "")

        def quality_loaded(data, error):
            if serial != self.serial:
                return
            if error or self.current_list != "reviews" or not isinstance(data, dict):
                finish(data, error)
                return
            review_query = urlencode({"batch_id": self.payload()["batch_id"]})
            def reviews_loaded(reviews, review_error):
                if review_error or not isinstance(reviews, dict) or "items" not in reviews:
                    finish(None, review_error or "本地服务返回的复核数据不完整")
                else:
                    finish(data, None, reviews)
            self.client.get("/api/cross-group-reviews?" + review_query, reviews_loaded)
        self.client.get("/api/data-quality?" + query, quality_loaded)

    def pages(self):
        if self.current_list == "batches":
            return 1
        if self.current_list == "reviews":
            return max(1, math.ceil(len(self.review_data.get("items") or []) / 10))
        return max(1, math.ceil(self.data.get("totals", {}).get(self.current_list, 0) / 50))

    def _remember_drafts(self):
        for widget in self.review_widgets:
            key = (widget.group["group_key"], widget.group["revision"])
            self.review_drafts[key] = {"reason": widget.reason.text(), "selected": widget.radios.checkedId()}
        keys = {(row["group_key"], row["revision"]) for row in self.review_data.get("items") or []}
        self.review_drafts = {key: value for key, value in self.review_drafts.items() if key in keys}

    def _render(self):
        self._remember_drafts()
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.table, self.review_widgets = None, []
        if self.current_list == "reviews":
            groups = self.review_data.get("items") or []
            for group in groups[(self.page - 1) * 10:self.page * 10]:
                widget = ReviewGroup(self, group)
                self.review_widgets.append(widget)
                self.rows_layout.addWidget(widget)
                widget.show()
            if not groups:
                self.rows_layout.addWidget(plain("当前范围没有跨数据组相同缺陷", "qualityEmpty"))
            self.page_label.setText(f"{self.page} / {self.pages()} · {len(groups)} 组 · "
                                    f"{self.review_data.get('pending', 0)} 组待复核")
        else:
            fields = {
                "issues": (["批次", "级别", "类型", "问题", "来源文件", "工作表", "行号", "字段"],
                           lambda r: [r.get("batch_id"), "错误" if r.get("severity") == "error" else "提醒",
                                      CATEGORIES.get(r.get("code"), r.get("code")), r.get("message"),
                                      r.get("source_path"), r.get("sheet_name"), r.get("row_number"), r.get("field_name")]),
                "batches": (["批次", "时间", "操作人员", "来源", "解析器", "状态", "解析", "入库", "重复", "错误"],
                            lambda r: [r.get("id"), timestamp(r.get("started_at")), r.get("operator"),
                                       r.get("source_path"), r.get("parser_version"),
                                       STATUSES.get(r.get("status"), r.get("status")),
                                       r.get("rows_parsed"), r.get("rows_inserted"), r.get("rows_skipped"), r.get("error_count")]),
                "artifacts": (["批次", "文件", "类型", "字节数", "SHA-256", "解析状态", "错误"],
                              lambda r: [r.get("batch_id"), r.get("path"), r.get("extension"), r.get("file_size"),
                                         r.get("sha256"), PARSE_STATUSES.get(r.get("parse_status"), r.get("parse_status")),
                                         r.get("error_message")]),
                "versions": (["批次", "大修", "机组", "数据组", "报告文件", "选用", "来源路径"],
                             lambda r: [r.get("batch_id"), r.get("outage"), r.get("unit_id"), r.get("calgroup"),
                                        r.get("filename"), "本批次选用" if r.get("batch_selected") else "保留候选",
                                        r.get("source_path")]),
            }
            headers, values = fields[self.current_list]
            rows = self.data.get(self.current_list) or []
            self.table = AuditTable(headers, [values(row) for row in rows])
            self.rows_layout.addWidget(self.table)
            if not rows:
                self.table.setRowCount(1)
                self.table.setSpan(0, 0, 1, len(headers))
                item = QTableWidgetItem("当前范围没有记录")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(0, 0, item)
            self.table.show()
            total = self.data.get("batch_total", 0) if self.current_list == "batches" else self.data.get("totals", {}).get(self.current_list, 0)
            suffix = "（最近 200 批；完整清单可导出）" if self.current_list == "batches" and total > 200 else ""
            self.page_label.setText(f"{self.page} / {self.pages()} · {total} 条{suffix}")
        self._controls()

    def selected_batch(self):
        selected = text(self.batch.currentData())
        return next((row for row in self.data.get("batches") or [] if text(row["id"]) == selected), None)

    def _controls(self):
        self.batch.setEnabled(not self.busy)
        self.category.setEnabled(not self.busy and self.current_list == "issues")
        self.refresh_button.setEnabled(not self.busy)
        for tab in self.tabs.buttons():
            tab.setEnabled(not self.busy)
        self.export.setEnabled(self.allowed("export.create") and not self.export_busy)
        self.retry.setEnabled(self.allowed("export.create") and not self.export_busy)
        self.previous.setEnabled(not self.busy and not self.reading and self.page > 1)
        self.next.setEnabled(not self.busy and not self.reading and self.page < self.pages())
        batch = self.selected_batch()
        writable = self.fresh and not self.busy and self.current_list != "reviews" and self.allowed("data.delete")
        self.rollback.setEnabled(bool(writable and batch and batch.get("status") == "completed" and batch.get("rows_parsed")))
        self.restore.setEnabled(bool(writable and batch and batch.get("status") == "rolled_back"))
        for widget in self.review_widgets:
            widget.set_writable()

    def batch_action(self, action):
        batch = self.selected_batch()
        if (action not in ("rollback", "restore") or not self.fresh or self.busy or self._confirming or not batch
                or not self.allowed("data.delete") or self.current_list == "reviews"):
            return
        if (action == "rollback" and (batch.get("status") != "completed" or not batch.get("rows_parsed"))
                or action == "restore" and batch.get("status") != "rolled_back"):
            return
        batch_id = batch["id"]
        if action == "rollback":
            message = (f"回滚批次 #{batch_id} 的新增记录、三字符修改及该批次自动写入的管状态；"
                       "原始文件和审计记录保留，可恢复该批次。记录或管状态如有后续修改，"
                       "将取消操作，不会部分回滚。")
            confirm = QMessageBox(QMessageBox.Icon.Warning, "确认批次回滚", message,
                                  QMessageBox.StandardButton.NoButton, self)
            confirm.setTextFormat(Qt.TextFormat.PlainText)
            confirm.addButton("取消", QMessageBox.ButtonRole.RejectRole)
            accept = confirm.addButton("确认回滚", QMessageBox.ButtonRole.AcceptRole)
            self._confirming = True
            try:
                confirm.exec()
            finally:
                self._confirming = False
            if confirm.clickedButton() != accept:
                return
            # A nested dialog event loop can receive a newer list while confirming.
            if not self.fresh or self.busy or self.selected_batch() != batch:
                return
        self._begin_write()
        def saved(data, error):
            if error or not data or data.get("ok") is False:
                self.busy = False
                self.fresh = False
                self.status.setText(error or "批次操作未完成，请刷新后核对")
                self._controls()
                return
            self.changed.emit()
            outcome = f"批次 #{batch_id} 已{'回滚' if action == 'rollback' else '恢复'}，涉及 {data.get('changed', 0)} 条记录"
            self._after_write(outcome)
        self.client.post("/api/import-batches/action", {"batch_id": batch_id, "action": action}, saved)

    def _begin_write(self):
        self.busy, self.fresh = True, False
        self.serial += 1
        self.feedback_revision += 1
        self._controls()

    def _after_write(self, outcome):
        def refreshed(ok, error):
            self.busy = False
            self.status.setText(outcome + ("" if ok else
                                f"；审计列表刷新失败：{error}。无需重复操作，请点击刷新。"))
            self._controls()
        self.refresh(completion=refreshed)

    def save_review(self, widget, action):
        if (action not in ("representative", "keep_all", "reset") or self.busy or not self.fresh
                or not self.allowed("review.write") or widget not in self.review_widgets
                or action == "reset" and not widget.group.get("history")):
            return
        selected = widget.radios.checkedId()
        if action == "representative" and selected < 0:
            self.status.setText("请先选择一条统计代表记录")
            return
        group = widget.group
        payload = {"group_key": group["group_key"], "revision": group["revision"], "action": action,
                   "representative_id": selected if selected >= 0 else None, "reason": widget.reason.text()}
        self._remember_drafts()
        self._begin_write()
        def saved(data, error):
            if error or not data or data.get("ok") is False:
                message = error or "复核未保存"
                def failed_refresh(_ok, _error):
                    self.busy = False
                    self.status.setText(message + ("。请重新核对复核组后操作。" if _ok else
                                        f"；列表刷新失败：{_error}。请点击刷新。"))
                    self._controls()
                self.refresh(completion=failed_refresh)
                return
            self.review_drafts.pop((group["group_key"], group["revision"]), None)
            widget.reason.clear()
            self.changed.emit()
            self._after_write("复核已保存。原始记录完整保留，已通知统计、对比与报告刷新。")
        self.client.post("/api/cross-group-reviews", payload, saved)

    def export_quality(self):
        if not self.allowed("export.create") or self.export_busy:
            return
        self.export_busy = True
        self.feedback_revision += 1
        self.export_file = None
        self.retry.hide()
        self.status.setText("正在生成数据与审计清单...")
        self._controls()
        def generated(data, error):
            self.export_busy = False
            if error or not data or not data.get("file_path"):
                self.status.setText(error or "清单生成失败")
                self._controls()
                return
            self.export_file = dict(data)
            self.save_export()
        self.client.post("/api/data-quality/export", self.payload(), generated)

    def save_export(self):
        if not self.allowed("export.create") or self.export_busy or not self.export_file:
            return
        self.export_busy = True
        self.feedback_revision += 1
        self._controls()
        file = self.export_file
        try:
            target, _ = QFileDialog.getSaveFileName(self, "保存数据与审计清单",
                                                   file.get("filename") or Path(file["file_path"]).name,
                                                   "Excel (*.xlsx)")
            if not target:
                outcome = "已取消保存"
            else:
                content = Path(file["file_path"]).read_bytes()
                output = QSaveFile(target)
                if (not output.open(QIODevice.OpenModeFlag.WriteOnly)
                        or output.write(content) != len(content) or not output.commit()):
                    raise OSError(output.errorString())
                outcome = "已保存"
            self.status.setText(f"{outcome}：{file.get('finding_rows', 0)} 条有效检测记录、"
                                f"{file.get('rows', 0)} 项校验问题。")
        except (KeyError, OSError) as exc:
            self.status.setText(f"保存失败：{exc}。")
        finally:
            self.export_busy = False
            self.retry.show()
            self._controls()


def quality_styles(dark=False):
    border, ink, hint, paper, header, accent = (
        ("#3f5558", "#e1ecee", "#a6bdc1", "#1d2a2b", "#273a3c", "#78cfc1") if dark else
        ("#d9e2e5", "#263c40", "#5d7177", "#ffffff", "#eef4f5", "#006b78"))
    return f"""
        QWidget#importQuality {{border:0;border-radius:4px;background:{"#1b2526" if dark else "transparent"};}}
        QWidget#importQuality QLabel {{font-size:12px;color:{ink};border:0;background:transparent;}}
        QWidget#importQuality QLabel#qualityHint {{color:{hint};}}
        QPushButton#qualityHeading {{text-align:left;padding:0;border:0;background:transparent;color:{hint};
            border-radius:0;font-size:13px;font-weight:400;min-height:20px;max-height:20px;}}
        QWidget#importQuality QComboBox {{height:32px;min-height:32px;max-height:32px;padding:0 8px;
            border:1px solid {border};border-radius:4px;background:{paper};color:{ink};font-size:12px;}}
        QWidget#importQuality QPushButton#qualityTool {{padding:0 12px;min-height:34px;
            max-height:34px;border:1px solid {border};border-radius:8px;font-size:12px;font-weight:600;}}
        QWidget#importQuality QPushButton#qualityReviewAction {{padding:0 12px;min-height:34px;
            max-height:34px;border:1px solid {border};border-radius:8px;font-size:12px;font-weight:600;}}
        QWidget#importQuality QLabel#qualityStatus {{padding:0 16px 10px;color:{hint};}}
        QWidget#qualityTabs {{border-top:1px solid {border};border-bottom:1px solid {border};}}
        QPushButton#qualityTab {{padding:0;border:0;border-radius:8px;background:transparent;
            min-height:34px;max-height:34px;font-size:12px;font-weight:600;}}
        QPushButton#qualityTab:checked {{color:{accent};border-bottom:2px solid {accent};background:{header};}}
        QTableWidget#qualityTable {{font-size:12px;color:{"#d8e5e2" if dark else "#3e535e"};background:transparent;border:0;
            selection-background-color:{header};selection-color:{ink};}}
        QTableWidget#qualityTable::item {{padding:10px 13px;border-bottom:1px solid {border};}}
        QTableWidget#qualityTable QHeaderView::section {{font-size:11px;font-weight:500;
            padding:10px 13px;border:0;border-bottom:1px solid {border};background:{header};color:{hint};}}
        QTableWidget#qualityTable QScrollBar:horizontal {{height:15px;margin:0;background:transparent;}}
        QTableWidget#qualityTable QScrollBar::handle:horizontal {{min-width:30px;
            background:{"#506867" if dark else "#bdcbd2"};border:3px solid transparent;border-radius:6px;}}
        QTableWidget#qualityTable QScrollBar::add-line:horizontal,
        QTableWidget#qualityTable QScrollBar::sub-line:horizontal {{width:12px;background:transparent;}}
        QTableWidget#qualityTable QScrollBar::add-page:horizontal,
        QTableWidget#qualityTable QScrollBar::sub-page:horizontal {{background:transparent;}}
        QWidget#qualityReview {{border-bottom:1px solid {border};}}
        QWidget#qualityReviewHeader {{background:#ffffff;border-bottom:1px solid {border};}}
        QWidget#importQuality QWidget#qualityReviewHeader QLabel {{color:#263c40;}}
        QWidget#importQuality QPushButton#qualityHistoryToggle {{background:{"#3d321c" if dark else "transparent"};}}
        QWidget#importQuality QLabel#qualityReviewTitle {{font-weight:600;}}
        QWidget#importQuality QLabel#qualityEmpty {{padding:24px 16px;color:{hint};}}
        QWidget#importQuality QPushButton:disabled {{color:{"#829794" if dark else "#929ca2"};}}
        QLineEdit#qualityReason {{min-height:36px;max-height:36px;padding:0 10px;
            font-size:12px;border:1px solid {border};border-radius:8px;}}
        QPushButton#qualityHistoryToggle {{border:0;background:transparent;text-align:left;
            min-height:31px;max-height:31px;padding:0;font-size:12px;}}
        QPushButton#qualityRetry {{border:0;background:transparent;color:{accent};padding:0;
            min-height:24px;max-height:24px;font-size:12px;text-align:left;}}
    """
