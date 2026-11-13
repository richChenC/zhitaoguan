"""Single native wizard for inspection, source review, confirmation and commit."""
from __future__ import annotations

import uuid
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem, QTabBar, QVBoxLayout,
    QWidget, QWizard, QWizardPage,
)
from .constants import EXCEL_EXTENSIONS, EXCEL_SCAN_LIMIT, OFFICE_MAX_BYTES
from .native_components import button, icon
from .native_report_choice import ReportChoiceDialog, ReportSelectionSummary


def scan_excel_sources(directory, cancelled=None):
    files, visited = [], set()
    pending = [(Path(directory), 0)]
    while pending:
        if cancelled is not None and cancelled.is_set():
            return [], False
        folder, depth = pending.pop()
        try:
            resolved = folder.resolve()
            if resolved in visited:
                continue
            visited.add(resolved)
            entries = sorted(folder.iterdir(), key=lambda path: path.name.casefold())
            for entry in entries:
                if entry.is_file() and entry.suffix.lower() in EXCEL_EXTENSIONS and not entry.name.startswith("~$"):
                    if len(files) == EXCEL_SCAN_LIMIT:
                        return files, True
                    files.append(str(entry.resolve()))
                elif (depth < 4 and entry.is_dir() and not entry.name.startswith(".")
                      and not entry.is_symlink() and not entry.is_junction()):
                    pending.append((entry, depth + 1))
        except OSError:
            continue
    return files, False


class _ScanSignals(QObject):
    finished = Signal(object, bool)


class _ExcelScan(QRunnable):
    def __init__(self, directory):
        super().__init__()
        self.directory = directory
        self.cancelled = Event()
        self.signals = _ScanSignals()

    def run(self):
        files, truncated = scan_excel_sources(self.directory, self.cancelled)
        self.signals.finished.emit(files, truncated)


class ImportWizard(QDialog):
    imported = Signal(dict)
    currentIdChanged = Signal(int)

    def __init__(self, client, mapping_fields, preferences, parent=None, *, mode="excel"):
        super().__init__(parent)
        self.client, self.preferences = client, dict(preferences)
        permissions = getattr(parent, "permissions", None)
        self.can_export = permissions is None or "export.create" in permissions
        self.setWindowTitle("导入检测数据")
        self.setObjectName("importWorkspace")
        self.resize(900, 820)
        self.setMinimumSize(640, 500)
        self._pages = []
        self._current_page = 0
        workspace = QVBoxLayout(self)
        workspace.setContentsMargins(0, 0, 0, 0)
        workspace.setSpacing(0)
        heading = QWidget()
        heading.setObjectName("importHeading")
        heading.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        heading_layout = QVBoxLayout(heading)
        heading_layout.setContentsMargins(20, 12, 20, 12)
        heading_layout.setSpacing(3)
        eyebrow = QLabel("数据导入")
        eyebrow.setObjectName("importEyebrow")
        heading_layout.addWidget(eyebrow)
        title = QLabel("导入检测数据")
        title.setObjectName("importTitle")
        heading_layout.addWidget(title)
        subtitle = QLabel("选择来源，检查数据，完成入库。")
        subtitle.setObjectName("muted")
        heading_layout.addWidget(subtitle)
        workspace.addWidget(heading)
        self.source_tabs = QTabBar()
        self.source_tabs.setObjectName("importSourceTabs")
        self.source_tabs.setAccessibleName("选择导入来源")
        self.source_tabs.setExpanding(True)
        self.source_tabs.setDrawBase(False)
        self.source_tabs.setFixedHeight(58)
        self.source_tabs.addTab("标准 Excel\n导入已有 .xls / .xlsx / .xlsm")
        self.source_tabs.addTab("RPT 文件夹\n逐组确认最终报告")
        workspace.addWidget(self.source_tabs)
        self.pages = QStackedWidget()
        self.pages.setObjectName("importPages")
        workspace.addWidget(self.pages, 1)
        self.dock = QWidget()
        self.dock.setObjectName("importActionDock")
        self.dock.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        dock_layout = QHBoxLayout(self.dock)
        dock_layout.setContentsMargins(20, 11, 20, 14)
        dock_layout.setSpacing(8)
        self.action_hint = QLabel()
        self.action_hint.setObjectName("muted")
        self.action_hint.setWordWrap(True)
        dock_layout.addWidget(self.action_hint, 1)
        self._buttons = {}
        for role, label, callback in (
            (QWizard.WizardButton.BackButton, "上一步", self.back),
            (QWizard.WizardButton.CancelButton, "关闭", self.reject),
            (QWizard.WizardButton.NextButton, "检查数据", self.next),
            (QWizard.WizardButton.FinishButton, "完成", self.accept),
        ):
            control = QPushButton(label)
            control.setAutoDefault(False)
            control.clicked.connect(callback)
            self._buttons[role] = control
            dock_layout.addWidget(control)
        for role in (QWizard.WizardButton.NextButton, QWizard.WizardButton.FinishButton):
            self.button(role).setProperty("primary", True)
            self.button(role).setMinimumWidth(130)
        workspace.addWidget(self.dock)
        self.ready_source = self.ready_preview = self.finished = self.busy = self.executing = False
        self.closed = False
        self.sheets, self.options = [], []
        self.report_choice = None
        self.payload, self.result = {}, {}
        self.token = None
        self.generation = 0
        self.source_paths = []
        self.file_mappings = {}
        self._mapping_path = ""
        source = self._page("导入检测数据")
        self.mode = QComboBox(self)
        self.mode.addItem("Excel 工作簿", "excel")
        self.mode.addItem("RPT 数据目录", "directory")
        self.mode.setCurrentIndex(max(0, self.mode.findData(mode)))
        self.source_tabs.setCurrentIndex(self.mode.currentIndex())
        self.source_tabs.currentChanged.connect(self.mode.setCurrentIndex)
        self.mode.currentIndexChanged.connect(self.source_tabs.setCurrentIndex)
        self.mode.hide()
        self.route_title = QLabel()
        self.route_title.setObjectName("importRouteTitle")
        self.route_title.setWordWrap(True)
        self.route_title.setFixedHeight(54)
        source.layout().addWidget(self.route_title)
        self.source_host = QWidget()
        self.source_host.setObjectName("importSourcePanel")
        source_box = QVBoxLayout(self.source_host)
        source_box.setContentsMargins(14, 14, 14, 14)
        source_box.setSpacing(10)
        self.rpt_note = QLabel("RPT 没有管状态时，状态栏保持空白，不会自动推断或修改管状态。")
        self.rpt_note.setObjectName("muted")
        self.rpt_note.setWordWrap(True)
        source_box.addWidget(self.rpt_note)
        choices = QHBoxLayout()
        self.add_files = button("选择 Excel 文件", "files", self.browse_files)
        self.add_folder = button("选择文件夹", "upload", self.browse_excel_folder)
        for control in (self.add_files, self.add_folder):
            choices.addWidget(control)
        choices.addStretch()
        source_box.addLayout(choices)
        path_row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setObjectName("importSourcePath")
        self.path.setAccessibleName("导入来源路径")
        self.path.setPlaceholderText("尚未选择来源")
        path_row.addWidget(self.path, 1)
        self.browse_source = button("选择来源", "upload", self.browse)
        path_row.addWidget(self.browse_source)
        source_box.addLayout(path_row)
        source.layout().addWidget(self.source_host)
        self.queue_heading = QWidget()
        queue_heading = QHBoxLayout(self.queue_heading)
        queue_heading.setContentsMargins(0, 12, 0, 0)
        queue_title = QLabel("待导入队列")
        queue_title.setObjectName("importRouteTitle")
        queue_heading.addWidget(queue_title)
        self.queue_summary = QLabel("尚未添加文件")
        self.queue_summary.setObjectName("muted")
        queue_heading.addWidget(self.queue_summary, 1)
        self.remove_file = button("移除所选文件", "trash-2", self.remove_source)
        self.remove_file.setEnabled(False)
        queue_heading.addWidget(self.remove_file)
        source.layout().addWidget(self.queue_heading)
        self.queue_table = QTableWidget(0, 2)
        self.queue_table.setObjectName("importQueue")
        self.queue_table.setMinimumHeight(86)
        self.queue_table.setMaximumHeight(160)
        self.queue_table.setHorizontalHeaderLabels(["来源文件", "处理状态"])
        self.queue_table.verticalHeader().hide()
        self.queue_table.horizontalHeader().setStretchLastSection(True)
        self.queue_table.setColumnWidth(0, 610)
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.queue_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.queue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.queue_table.itemSelectionChanged.connect(
            lambda: self.remove_file.setEnabled(not self.busy and self.queue_table.currentRow() >= 0))
        source.layout().addWidget(self.queue_table, 1)
        self.source_status = QLabel()
        self.source_status.setWordWrap(True)
        source.layout().addWidget(self.source_status)
        source.layout().addStretch()
        mapping = self._page("识别与字段映射")
        self.mapping_heading = mapping.layout().itemAt(0).widget()
        self.file_choice = QComboBox()
        self.file_choice.currentIndexChanged.connect(self.select_mapping_file)
        mapping.layout().addWidget(self.file_choice)
        self.excel_settings = QWidget()
        settings = QHBoxLayout(self.excel_settings)
        settings.setContentsMargins(0, 0, 0, 0)
        self.sheet = QComboBox()
        self.sheet.setObjectName("importWorksheet")
        settings.addWidget(self.sheet, 1)
        self.manual = QCheckBox("手动映射当前工作表")
        settings.addWidget(self.manual)
        self.header = QSpinBox()
        self.header.setRange(1, 9999)
        settings.addWidget(QLabel("表头行"))
        settings.addWidget(self.header)
        mapping.layout().addWidget(self.excel_settings)
        self.mapping_form = QFormLayout()
        self.columns = {}
        for key, label, required in mapping_fields:
            combo = QComboBox()
            combo.setObjectName("importMapping_" + key)
            self.columns[key] = combo
            self.mapping_form.addRow(label + (" *" if required else ""), combo)
        # Two columns keep the mapping form and raw source rows visible together.
        from PySide6.QtWidgets import QSplitter
        mapping_host = QWidget()
        mapping_host.setLayout(self.mapping_form)
        self.mapping_host = mapping_host
        split = QSplitter()
        self.mapping_split = split
        split.addWidget(mapping_host)
        self.source_table = QTableWidget()
        self.source_table.setMinimumSize(240, 220)
        self.source_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        split.addWidget(self.source_table)
        split.setSizes([360, 650])
        mapping.layout().addWidget(split, 1)
        self.report_settings = QWidget()
        report_box = QVBoxLayout(self.report_settings)
        report_box.setContentsMargins(0, 0, 0, 0)
        report_box.setSpacing(8)
        source_box.addWidget(self.report_settings)
        self.report_actions = QWidget()
        report_actions = QVBoxLayout(self.report_actions)
        report_actions.setContentsMargins(0, 0, 0, 0)
        policy_row = QHBoxLayout()
        policy_row.addWidget(QLabel("RPT 选择"))
        self.report_policy = QComboBox()
        self.report_policy.setAccessibleName("RPT 选择策略")
        self.report_policy.addItem("手动选择 RPT", "manual")
        self.report_policy.addItem("预选最新并逐组确认", "latest")
        self.report_policy.setCurrentIndex(max(0, self.report_policy.findData(
            self.preferences.get("report_policy") or "manual")))
        self.report_policy.currentIndexChanged.connect(self._report_policy_changed)
        policy_row.addWidget(self.report_policy)
        self.report_policy_hint = QLabel()
        self.report_policy_hint.setObjectName("muted")
        self.report_policy_hint.setWordWrap(True)
        policy_row.addWidget(self.report_policy_hint, 1)
        report_actions.addLayout(policy_row)
        versions = QHBoxLayout()
        versions.addWidget(QLabel("Report 版本"))
        versions.addStretch()
        self.choose_reports = button("继续 Report 选择", "files", self.open_report_choices)
        versions.addWidget(self.choose_reports)
        report_actions.addLayout(versions)
        report_box.addWidget(self.report_actions)
        self.report_summary = ReportSelectionSummary()
        self.report_summary.groupActivated.connect(self.open_report_choices)
        report_box.addWidget(self.report_summary)
        export_row = QHBoxLayout()
        self.directory_export = QPushButton("仅生成并保存标准 Excel")
        self.directory_export.clicked.connect(self.export_directory)
        self.directory_export.setEnabled(self.can_export)
        export_row.addWidget(self.directory_export)
        export_row.addStretch()
        report_box.addLayout(export_row)
        self.mapping_note = QLabel()
        self.mapping_note.setWordWrap(True)
        mapping.layout().addWidget(self.mapping_note)
        self.policy = QComboBox()
        self.policy.addItem("空三字符进入待复核", "review")
        self.policy.addItem("空三字符按 WAR 填充", "fill_war")
        self.policy.addItem("仅预检，不写入记录", "check")
        mapping.layout().addWidget(self.policy)
        mapping.layout().addStretch()
        self._update_report_policy_hint()
        preview = self._page("预检与确认")
        self.preview_summary = QLabel()
        self.preview_summary.setWordWrap(True)
        preview.layout().addWidget(self.preview_summary)
        self.preview_table = QTableWidget()
        self.preview_table.setMinimumHeight(240)
        self.preview_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        preview.layout().addWidget(self.preview_table, 1)
        self.preview_errors = QPlainTextEdit()
        self.preview_errors.setReadOnly(True)
        self.preview_errors.setMaximumHeight(150)
        preview.layout().addWidget(self.preview_errors)
        execute = self._page("执行导入")
        self.stage = QLabel()
        self.stage.setWordWrap(True)
        self.progress = QProgressBar()
        execute.layout().addWidget(self.stage)
        execute.layout().addWidget(self.progress)
        execute.layout().addStretch()
        result = self._page("导入结果")
        self.result_summary = QLabel()
        self.result_summary.setWordWrap(True)
        self.result_summary.setTextFormat(Qt.TextFormat.PlainText)
        result.layout().addWidget(self.result_summary)
        self.result_metrics = QWidget()
        self.result_metrics.setObjectName("importResultMetrics")
        metrics = QGridLayout(self.result_metrics)
        metrics.setContentsMargins(0, 0, 0, 0)
        metrics.setSpacing(1)
        self.metric_values = {}
        for index, (key, label) in enumerate((("parsed", "解析"), ("inserted", "新增"), ("updated", "更新"),
                                               ("skipped", "跳过"), ("error_total", "问题"))):
            metric = QWidget()
            metric.setObjectName("importResultMetric")
            metric.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            metric_layout = QVBoxLayout(metric)
            metric_layout.setContentsMargins(10, 8, 10, 8)
            value = QLabel("0")
            value.setObjectName("importMetricValue")
            metric_layout.addWidget(value)
            caption = QLabel(label)
            caption.setObjectName("muted")
            metric_layout.addWidget(caption)
            self.metric_values[key] = value
            metrics.addWidget(metric, 0, index)
        result.layout().addWidget(self.result_metrics)
        self.result_disclosure = button("查看详细结果", "chevron-right")
        self.result_disclosure.setCheckable(True)
        result.layout().addWidget(self.result_disclosure)
        self.result_details = QPlainTextEdit()
        self.result_details.setReadOnly(True)
        self.result_details.setMinimumHeight(180)
        self.result_details.hide()
        self.result_disclosure.toggled.connect(self.result_details.setVisible)
        result.layout().addWidget(self.result_details)
        self.retry = QPushButton("修正后重试")
        self.retry.clicked.connect(self.retry_import)
        self.retry.hide()
        result.layout().addWidget(self.retry)
        result.layout().addStretch()
        self.timer = QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.poll)
        self.sheet.currentIndexChanged.connect(self.show_sheet)
        self.manual.toggled.connect(self.mapping_host.setEnabled)
        self.path.textChanged.connect(self.invalidate)
        self.mode.currentIndexChanged.connect(self.invalidate)
        self.mode.currentIndexChanged.connect(self._source_mode_changed)
        self.currentIdChanged.connect(self.page_changed)
        self._source_mode_changed()
        self._update_navigation()

    def _page(self, title):
        page = QWizardPage()
        page.setTitle(title)
        page.setLayout(QVBoxLayout())
        page.layout().setContentsMargins(20, 14, 20, 14)
        page.layout().setSpacing(10)
        if self._pages:
            heading = QLabel(f"{len(self._pages) + 1}  {title}")
            heading.setObjectName("importRouteTitle")
            page.layout().addWidget(heading)
        scroll = QScrollArea()
        scroll.setObjectName("importBody")
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        self._pages.append(page)
        self.pages.addWidget(scroll)
        return page

    def button(self, role):
        return self._buttons[role]

    def setButtonText(self, role, text):
        self.button(role).setText(text)

    def currentId(self):
        return self._current_page

    def _update_navigation(self):
        page = self.currentId()
        directory = self.mode.currentData() == "directory"
        self.button(QWizard.WizardButton.BackButton).setVisible(page == 2 or (page == 1 and not directory))
        self.button(QWizard.WizardButton.BackButton).setEnabled(not self.busy and page in (1, 2))
        next_button = self.button(QWizard.WizardButton.NextButton)
        next_button.setVisible(page < 4)
        next_button.setEnabled(not self.busy and page != 3)
        next_button.setText(("检查数据", "预检数据", "开始导入", "正在导入", "")[page])
        next_button.setDefault(page < 3)
        finish = self.button(QWizard.WizardButton.FinishButton)
        finish.setVisible(page == 4)
        finish.setDefault(page == 4)
        self.button(QWizard.WizardButton.CancelButton).setEnabled(not self.executing)
        hints = (
            "添加 Excel 文件后检查数据。" if self.mode.currentData() == "excel" else "选择检测文件夹后逐组确认最终报告。",
            "确认来源和字段后预检数据。",
            "核对预检结果后开始导入。" if self.policy.currentData() != "check" else "本次仅预检，不写入业务记录。",
            "正在处理，请稍候。",
            "导入结果以数据库批次记录为准。",
        )
        self.action_hint.setText(hints[page])

    def _set_page(self, page):
        self._current_page = page
        self.pages.setCurrentIndex(0 if page == 1 and self.mode.currentData() == "directory" else page)
        self._update_navigation()
        self.currentIdChanged.emit(page)

    def next(self):
        if not self.closed and self.currentId() < 4 and self.validateCurrentPage():
            self._set_page(self.currentId() + 1)

    def back(self):
        if not self.closed and not self.busy and self.currentId() in (1, 2):
            self._set_page(self.currentId() - 1)

    def restart(self):
        self._accept_preflight_once = False
        self._set_page(0)

    def accept(self):
        if self.currentId() != 4 or self.executing:
            return
        self.closed = True
        self.timer.stop()
        super().accept()

    def showEvent(self, event):
        super().showEvent(event)
        available = self.screen().availableGeometry()
        self.resize(min(self.width(), max(self.minimumWidth(), available.width() - 28)),
                    min(self.height(), max(self.minimumHeight(), available.height() - 60)))
        theme = "dark" if self.palette().windowText().color().lightness() > 160 else "light"
        for control in self.findChildren(QPushButton):
            name = control.property("iconName")
            if name:
                control.setIcon(icon(name, theme))

    def invalidate(self, *_):
        self.ready_source = self.ready_preview = False
        self.generation += 1
        self._clear_report_choices()
        if self.currentId() == 1 and self.mode.currentData() == "directory":
            self._set_page(0)

    def _clear_report_choices(self):
        if self.report_choice:
            self.report_choice.close()
            self.report_choice.deleteLater()
            self.report_choice = None
        self.options = []
        self.report_summary.set_choice(None)
        self.directory_export.setEnabled(False)
        self.choose_reports.setText("扫描并确认")
        self.mapping_note.clear()

    def _update_report_policy_hint(self):
        self.report_policy_hint.setText("按修改时间预选，仍需逐组确认"
                                        if self.report_policy.currentData() == "latest"
                                        else "为每个数据组手动选择一份")

    def _report_policy_changed(self, *_):
        value = self.report_policy.currentData()
        self._update_report_policy_hint()
        self.preferences["report_policy"] = value
        parent = self.parentWidget()
        context = getattr(parent.window(), "context", None) if parent else None
        if context:
            context.preferences.save(report_policy=value)
        if self.report_choice:
            self.report_choice.close()
            self.report_choice.deleteLater()
            self.report_choice = ReportChoiceDialog(self.options, self, latest=value == "latest")
            self.report_choice.selectionChanged.connect(self._report_selection_changed)
            self._report_selection_changed()

    def open_report_choices(self, index=None):
        if self.closed or self.busy:
            return
        if not self.report_choice:
            if self.currentId() == 0 and self.mode.currentData() == "directory":
                self.next()
            return
        self.report_choice.show_group(index if type(index) is int else 0)
        self.report_choice.open()

    def _report_selection_changed(self):
        self.ready_preview = False
        self._accept_preflight_once = False
        self.payload = {}
        choice = self.report_choice
        if not choice:
            return
        self.report_summary.set_choice(choice)
        failed = [row for row in self.options if row.get("error")]
        self.mapping_note.setText(
            f"已确认 {len(choice.confirmed)} / {len(choice.groups)} 个数据组。"
            + ("可生成标准 Excel 或预检入库。" if choice.complete else "请逐组确认最终报告。")
            + (f"\n另有 {len(failed)} 份 RPT 解析失败，不会被转换：\n"
               + "\n".join(f"{row.get('path', '')}：{row['error']}" for row in failed) if failed else ""))
        self.choose_reports.setText("修改 Report 选择" if choice.complete else "继续 Report 选择")
        self.directory_export.setEnabled(not self.busy and self.can_export and choice.complete)

    def _source_mode_changed(self, *_):
        excel = self.mode.currentData() == "excel"
        previous = getattr(self, "_active_source_mode", None)
        if previous is not None:
            self._route_paths[previous] = self.path.text()
        else:
            self._route_paths = {}
        self._active_source_mode = self.mode.currentData()
        self.path.setReadOnly(excel and len(self.source_paths) > 1)
        self.path.setText(self._route_paths.get(self._active_source_mode, ""))
        self.route_title.setText("1  选择已有 Excel 文件" if excel else "1  原始 RPT → 标准 Excel → 数据库")
        self.rpt_note.setVisible(not excel)
        self.report_settings.setVisible(not excel)
        note_layout = self._pages[1].layout() if excel else self.report_settings.layout()
        for control in (self.mapping_note, self.policy):
            if excel:
                note_layout.insertWidget(note_layout.count()-1, control)
            else:
                note_layout.addWidget(control)
        self.path.setPlaceholderText("尚未选择 Excel 文件" if excel else "请选择原始检测数据根目录")
        self.browse_source.setText("选择文件" if excel else "选择检测文件夹")
        for control in (self.add_files, self.add_folder, self.queue_heading, self.queue_table, self.file_choice):
            control.setVisible(excel)
        if self.currentId() > 0:
            self.ready_source = self.ready_preview = self.finished = False
            self.result = {}
            self.retry.hide()
            self.restart()
        self._update_navigation()

    def set_sources(self, paths):
        self.source_paths = list(dict.fromkeys(str(Path(path).resolve()) for path in paths))
        self.file_mappings = {key: value for key, value in self.file_mappings.items() if key in self.source_paths}
        self.queue_table.setRowCount(len(self.source_paths))
        for row, path in enumerate(self.source_paths):
            item = QTableWidgetItem(Path(path).name)
            item.setToolTip(path)
            self.queue_table.setItem(row, 0, item)
            self.queue_table.setItem(row, 1, QTableWidgetItem("待预检"))
        self.queue_summary.setText(f"{len(self.source_paths)} 个文件" if self.source_paths else "尚未添加文件")
        self.remove_file.setEnabled(bool(self.source_paths) and not self.busy and self.queue_table.currentRow() >= 0)
        self.file_choice.blockSignals(True)
        self.file_choice.clear()
        for path in self.source_paths:
            self.file_choice.addItem(Path(path).name, path)
        self.file_choice.blockSignals(False)
        self.path.setText(self.source_paths[0] if self.source_paths else "")
        self.path.setReadOnly(len(self.source_paths) > 1)
        self.invalidate()

    def browse_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "选择检测工作簿",
                                                self.preferences.get("source_path") or "",
                                                "Excel (*.xlsx *.xlsm *.xls)")
        if paths:
            self.set_sources(self.source_paths + paths)

    def browse_excel_folder(self):
        path = QFileDialog.getExistingDirectory(self, "选择 Excel 文件夹", self.preferences.get("source_path") or "")
        if path:
            generation = self.generation
            self.set_busy(True)
            self.source_status.setText("正在扫描 Excel 文件夹...")
            self._scan_job = _ExcelScan(path)
            self._scan_job.signals.finished.connect(
                lambda paths, truncated: self._folder_scanned(generation, paths, truncated))
            QThreadPool.globalInstance().start(self._scan_job)

    def _folder_scanned(self, generation, paths, truncated):
        if self.closed or generation != self.generation:
            return
        self.set_busy(False)
        if not paths:
            self.source_status.setText("所选文件夹没有可读取的 Excel 工作簿")
            return
        self.set_sources(self.source_paths + paths)
        self.source_status.setText(f"已添加 {len(paths)} 个文件" +
                                   ("；文件较多，请缩小目录范围后分批添加" if truncated else ""))

    def remove_source(self):
        row = self.queue_table.currentRow()
        if 0 <= row < len(self.source_paths):
            self.set_sources([path for index, path in enumerate(self.source_paths) if index != row])

    def _current_mapping(self):
        if not self.manual.isChecked():
            return None
        return {"sheet": (self.sheet.currentData() or {}).get("name"), "header_row": self.header.value(),
                "columns": {key: combo.currentData() for key, combo in self.columns.items()
                            if combo.currentData() is not None}}

    def select_mapping_file(self, *_):
        if self.busy or self.mode.currentData() != "excel":
            return
        path = self.file_choice.currentData()
        if not path or path == self._mapping_path:
            return
        if self._mapping_path:
            self.file_mappings[self._mapping_path] = self._current_mapping()
        self.set_busy(True)
        generation = self.generation
        self.client.post("/api/import-excel-inspect", {"path": path},
                         lambda data, error: self.source_loaded(generation, data, error, advance=False, path=path))

    def browse(self):
        directory = self.preferences.get("source_path") or ""
        if self.mode.currentData() == "excel":
            path, _ = QFileDialog.getOpenFileName(self, "选择检测工作簿", directory, "Excel (*.xlsx *.xlsm *.xls)")
        else:
            path = QFileDialog.getExistingDirectory(self, "选择 RPT 数据目录", directory)
        if path:
            if self.mode.currentData() == "excel":
                self.set_sources([path])
            else:
                self.path.setText(path)

    def set_busy(self, busy):
        self.busy = busy
        self._update_navigation()
        for widget in (self.path, self.mode, self.source_tabs, self.file_choice, self.add_files, self.add_folder,
                       self.browse_source,
                       self.remove_file, self.sheet, self.manual, self.header, self.policy, self.report_summary,
                       self.directory_export, self.report_actions):
            widget.setEnabled(not busy)
        self.remove_file.setEnabled(not busy and self.queue_table.currentRow() >= 0)
        self.mapping_host.setEnabled(not busy and self.manual.isChecked())
        self.directory_export.setEnabled(not busy and self.can_export
                                         and bool(self.report_choice and self.report_choice.complete))

    def validateCurrentPage(self):
        if self.busy:
            return False
        if self.currentId() == 0 and not self.ready_source:
            path = self.path.text().strip()
            if not path:
                self.source_status.setText("请选择来源文件或目录")
                return False
            self.set_busy(True)
            generation = self.generation
            self.source_status.setText("正在识别来源...")
            endpoint = "/api/import-excel-inspect" if self.mode.currentData() == "excel" else "/api/report-options"
            self.client.post(endpoint, {"path": path},
                             lambda data, error: self.source_loaded(generation, data, error))
            return False
        if self.currentId() == 1:
            if getattr(self, "_accept_preflight_once", False):
                self._accept_preflight_once = False
                return True
            self.ready_preview = False
            if not self.prepare_payload():
                return False
            self.set_busy(True)
            self.token = uuid.uuid4().hex
            if self.mode.currentData() == "excel" and len(self.source_paths) > 1:
                self.file_mappings[self._mapping_path] = self._current_mapping()
                self._batch_payloads = [{"path": path, "mapping": self.file_mappings.get(path),
                                         "blank_indication_policy": self.policy.currentData()}
                                        for path in self.source_paths]
                self._batch_results = []
                self._batch_preflight(0)
                return False
            endpoint = "/api/import-excel" if self.mode.currentData() == "excel" else "/api/import-directory-preview"
            payload = {**self.payload, "blank_indication_policy": "check"}
            generation = self.generation
            self.client.post(endpoint, payload,
                             lambda data, error: self.preflight_loaded(data, error)
                             if not self.closed and generation == self.generation else None,
                             task_token=self.token)
            return False
        if self.currentId() == 3:
            return self.finished
        return True

    def source_loaded(self, generation, data, error, *, advance=True, path=None):
        if self.closed or generation != self.generation:
            return
        self.set_busy(False)
        if error or not data:
            self.source_status.setText(error or "来源识别失败")
            return
        excel = self.mode.currentData() == "excel"
        for widget in (self.excel_settings, self.mapping_split):
            widget.setVisible(excel)
        self.mapping_heading.setText("2  识别与字段映射" if excel else "2  扫描并确认 Report")
        self.report_summary.setVisible(not excel)
        self.report_actions.setVisible(not excel)
        self.directory_export.setVisible(not excel)
        if excel:
            self._mapping_path = path or self.path.text().strip()
            self.sheets = data.get("sheets") or []
            if not self.sheets:
                self.source_status.setText("没有可读取的工作表")
                return
            self.sheet.clear()
            for sheet in self.sheets:
                self.sheet.addItem(f"{sheet['name']} · {'已识别' if sheet.get('recognized') else '需映射'}", sheet)
            self.show_sheet()
            saved = self.file_mappings.get(self._mapping_path)
            self.manual.setChecked(saved is not None)
            if saved:
                index = next((i for i in range(self.sheet.count())
                              if (self.sheet.itemData(i) or {}).get("name") == saved.get("sheet")), 0)
                self.sheet.setCurrentIndex(index)
                self.header.setValue(saved["header_row"])
                for key, value in saved["columns"].items():
                    if key in self.columns:
                        self.columns[key].setCurrentIndex(max(0, self.columns[key].findData(value)))
            self.mapping_note.setText("自动识别会检查全部工作表；手动映射只处理当前工作表。右侧保留原始行号。")
        else:
            self.options = [row for row in data.get("reports", []) if isinstance(row, dict)]
            if self.report_choice:
                self.report_choice.close()
                self.report_choice.deleteLater()
            self.report_choice = ReportChoiceDialog(
                self.options, self, latest=self.report_policy.currentData() == "latest")
            if not self.report_choice.groups:
                failed = [row for row in self.options if row.get("error")]
                self.source_status.setText("未找到可解析的 RPT 数据组"
                                           + ("\n" + "\n".join(f"{row.get('path', '')}：{row['error']}"
                                                              for row in failed) if failed else ""))
                return
            self.report_choice.selectionChanged.connect(self._report_selection_changed)
            self._report_selection_changed()
        self.source_status.clear()
        self.ready_source = True
        if advance:
            self.next()
            if not excel:
                QTimer.singleShot(0, self.open_report_choices)

    def export_directory(self):
        if self.busy or not self.can_export or not self.prepare_payload():
            return
        self.set_busy(True)
        self.client.post("/api/export-folder-excel", self.payload, self._directory_exported)

    def _directory_exported(self, data, error):
        if self.closed:
            return
        self.set_busy(False)
        if error or not data:
            QMessageBox.warning(self, "生成标准 Excel", error or "生成失败")
            return
        from .artifact_save import save_artifact
        source = Path(data.get("file_path") or data.get("path") or "")
        if not source.is_file():
            QMessageBox.warning(self, "生成标准 Excel", "未找到生成的工作簿，请重新生成")
            return
        self.mapping_note.setText(f"已生成 {data.get('rows', 0)} 条标准 Excel：{source.name}")
        target, _ = QFileDialog.getSaveFileName(self, "保存标准 Excel", source.name, "Excel (*.xlsx)")
        if not target:
            return
        def authorized(data, error):
            if self.closed:
                return
            if error or "export.create" not in ((data or {}).get("user") or {}).get("permissions", []):
                QMessageBox.warning(self, "保存标准 Excel", error or "当前账户没有导出权限")
                return
            try:
                if source.stat().st_size > OFFICE_MAX_BYTES:
                    raise ValueError("文件超过 50 MB，请缩小范围后重新生成")
                save_artifact(target, source.read_bytes())
                self.mapping_note.setText(f"已保存标准 Excel：{target}")
            except (OSError, ValueError, RuntimeError) as exc:
                QMessageBox.warning(self, "保存标准 Excel", str(exc))
        self.client.get("/api/auth/me", authorized)

    def _batch_preflight(self, index):
        if index == len(self._batch_payloads):
            self.preflight_loaded(self._aggregate_batch(self._batch_results), None)
            return
        payload = self._batch_payloads[index]
        generation = self.generation
        self.queue_table.item(index, 1).setText("正在预检")

        def done(data, error):
            if self.closed or generation != self.generation:
                return
            if error or not data:
                self.queue_table.item(index, 1).setText("预检失败")
                self.preflight_loaded(None, f"{Path(payload['path']).name}：{error or '预检失败'}")
                return
            self._batch_results.append({**data, "source_path": payload["path"]})
            if data.get("source_sha256"):
                payload["expected_sha256"] = data["source_sha256"]
            self.queue_table.item(index, 1).setText(f"预检完成：{data.get('parsed', 0)} 条")
            self._batch_preflight(index + 1)
        self.client.post("/api/import-excel", {**payload, "blank_indication_policy": "check"}, done)

    @staticmethod
    def _aggregate_batch(results):
        result = {"files": results, "preview_rows": [], "invalid_rows": [], "blank_indication": {"count": 0}}
        for source in results:
            for key in ("parsed", "inserted", "updated", "skipped", "invalid_count", "error_total"):
                result[key] = result.get(key, 0) + int(source.get(key) or 0)
            result["preview_rows"].extend((source.get("preview_rows") or [])[:max(0, 500 - len(result["preview_rows"]))])
            result["invalid_rows"].extend(source.get("invalid_rows") or source.get("errors") or [])
            result["blank_indication"]["count"] += int((source.get("blank_indication") or {}).get("count") or 0)
        return result

    def _batch_commit(self, index):
        if index == len(self._batch_payloads):
            self.commit_loaded(self._aggregate_batch(self._batch_results), None)
            return
        payload = self._batch_payloads[index]
        self.token = uuid.uuid4().hex
        self.stage.setText(f"正在导入 {index + 1}/{len(self._batch_payloads)}：{Path(payload['path']).name}")
        self.queue_table.item(index, 1).setText("正在导入")

        def done(data, error):
            if self.closed:
                return
            if error or not data:
                self.queue_table.item(index, 1).setText("失败；后续文件未执行")
                self.result = self._aggregate_batch(self._batch_results)
                if self._batch_results:
                    self.imported.emit({**self.result, "partial": True})
                self.commit_loaded(None, f"{Path(payload['path']).name}：{error or '导入失败'}；"
                                   f"此前已完成 {len(self._batch_results)} 个文件，请核对批次")
                return
            self._batch_results.append({**data, "source_path": payload["path"]})
            self.queue_table.item(index, 1).setText(f"已完成：新增 {data.get('inserted', 0)} 条")
            self._batch_commit(index + 1)
        self.client.post("/api/import-excel", payload, done, task_token=self.token)

    def show_sheet(self, *_):
        sheet = self.sheet.currentData() or {}
        self.header.setValue(int(sheet.get("header_row") or 1))
        for key, combo in self.columns.items():
            combo.clear()
            combo.addItem("未指定", None)
            for column in sheet.get("columns") or []:
                combo.addItem(f"{column['column']}：{column.get('header') or '空列'}", column["column"])
            detected = (sheet.get("mapping") or {}).get(key)
            if detected is not None:
                combo.setCurrentIndex(max(0, combo.findData(int(detected) + 1)))
        self.mapping_host.setEnabled(self.manual.isChecked())
        columns = [(str(column["column"]), column.get("header") or "空列") for column in sheet.get("columns") or []]
        rows = [dict(zip((key for key, _ in columns), row["values"])) | {"_row": row["row_number"]}
                for row in sheet.get("sample_rows") or []]
        self.fill_table(self.source_table, [("_row", "原始行")] + columns, rows)

    def prepare_payload(self):
        self.payload = {"path": self.path.text().strip(), "blank_indication_policy": self.policy.currentData()}
        if self.mode.currentData() == "excel":
            mapping = None
            if self.manual.isChecked():
                mapping = {"sheet": (self.sheet.currentData() or {}).get("name"),
                           "header_row": self.header.value(),
                           "columns": {key: combo.currentData() for key, combo in self.columns.items()
                                       if combo.currentData() is not None}}
            self.payload["mapping"] = mapping
        else:
            if not self.report_choice or not self.report_choice.complete:
                self.mapping_note.setText("请逐组确认要入库的 RPT 报告")
                self.open_report_choices()
                return False
            self.payload["reports"] = [report["path"] for report in self.report_choice.selected]
            self.payload["report_confirmation"] = {"confirmed": True, "candidates": [
                {key: row.get(key) or "" for key in ("path", "sha256", "sum_sha256")}
                for row in self.options if row.get("path") and not row.get("error")]}
        return True

    @staticmethod
    def fill_table(table, columns, rows):
        table.clear()
        table.setColumnCount(len(columns))
        table.setRowCount(len(rows))
        table.setHorizontalHeaderLabels([label for _, label in columns])
        for index, row in enumerate(rows):
            for column, (key, _) in enumerate(columns):
                table.setItem(index, column, QTableWidgetItem(str(row.get(key) if row.get(key) is not None else "")))
        table.resizeColumnsToContents()

    @staticmethod
    def issue_lines(data):
        lines = []
        for source in data.get("files") or [data]:
            path = source.get("source_path") or source.get("file") or ""
            prefix = (Path(path).name + " · ") if path else ""
            sheets = source.get("sheets") or []
            if sheets:
                for sheet in sheets:
                    invalid = sheet.get("invalid_rows") or []
                    if invalid:
                        lines.append(f"{prefix}{sheet.get('sheet', '')} · 待核对原始行："
                                     + "、".join(map(str, invalid)))
            for issue in source.get("errors") or ([] if sheets else source.get("invalid_rows") or []):
                if isinstance(issue, dict):
                    where = " · ".join(str(issue[key]) for key in ("file", "source_path", "sheet_name", "row_number",
                                                                  "field_name", "type") if issue.get(key) is not None
                                       and issue.get(key) != "")
                    message = issue.get("message") or issue.get("error") or issue.get("reason") or "请核对原始资料"
                    lines.append(prefix + (where + "：" if where else "") + str(message))
                elif isinstance(issue, int):
                    lines.append(f"{prefix}待核对原始行：{issue}")
                else:
                    lines.append(prefix + str(issue))
        return lines

    @classmethod
    def result_description(cls, data):
        lines = []
        for source in data.get("files") or [data]:
            path = source.get("source_path") or source.get("file")
            if path:
                lines.append(str(path))
            if source.get("batch_id"):
                lines.append(f"导入批次：{source['batch_id']}")
            lines.append(f"解析 {source.get('parsed', source.get('parsed_total', 0))} 条；"
                         f"新增 {source.get('inserted', 0)} 条；更新 {source.get('updated', 0)} 条；"
                         f"跳过 {source.get('skipped', 0)} 条")
        issues = cls.issue_lines(data)
        lines.extend(["", "待核对问题"] + issues if issues else ["", "本次结果没有返回待核对问题。"])
        return "\n".join(lines)

    def preflight_loaded(self, data, error):
        if self.closed:
            return
        self.set_busy(False)
        if error or not data:
            QMessageBox.warning(self, "预检失败", error or "没有返回预检结果")
            return
        self.result = data
        if self.mode.currentData() == "excel" and data.get("source_sha256"):
            self.payload["expected_sha256"] = data["source_sha256"]
        parsed = data.get("parsed", data.get("parsed_total", 0))
        self.preview_summary.setText(f"预计解析 {parsed:,} 条；空三字符 "
                                     f"{(data.get('blank_indication') or {}).get('count', 0)} 条；"
                                     f"质量问题 {data.get('error_total', data.get('invalid_count', 0))} 条。\n"
                                     f"处理策略：{self.policy.currentText()}")
        rows = data.get("preview_rows") or []
        self.fill_table(self.preview_table, [("outage", "大修"), ("unit_id", "机组"), ("thimble_id", "通道"),
                                            ("indication", "三字符"), ("percent", "磨损深度"),
                                            ("location", "位置"), ("filename", "文件")], rows)
        self.preview_errors.setPlainText("\n".join(self.issue_lines(data)) or "预检未报告错误")
        # Advance directly because validateCurrentPage would otherwise rerun preflight.
        self.ready_preview = True
        self._advance_after_preflight()

    def _advance_after_preflight(self):
        self._accept_preflight_once = True
        self.next()

    def page_changed(self, page):
        if page == 3 and not self.executing and not self.finished:
            if self.policy.currentData() == "check":
                self.commit_loaded({**self.result, "check_only": True}, None)
                return
            self.executing = True
            self.set_busy(True)
            self.token = uuid.uuid4().hex
            self.progress.setRange(0, 100)
            self.stage.setText("正在写入记录...")
            self.timer.start()
            if self.mode.currentData() == "excel" and len(self.source_paths) > 1:
                self._batch_results = []
                self._batch_commit(0)
                return
            endpoint = "/api/import-excel" if self.mode.currentData() == "excel" else "/api/import"
            self.client.post(endpoint, self.payload, self.commit_loaded, task_token=self.token)

    def poll(self):
        self.client.get("/api/import-progress?id=" + self.token, self.progress_loaded)

    def progress_loaded(self, data, error):
        if self.closed or not data:
            return
        self.stage.setText(str(data.get("stage") or "正在处理"))
        if isinstance(data.get("percent"), (int, float)):
            self.progress.setValue(round(data["percent"]))

    def commit_loaded(self, data, error):
        self.timer.stop()
        self.executing = False
        self.finished = True
        self.set_busy(False)
        self.button(QWizard.WizardButton.BackButton).setEnabled(False)
        if error or not data:
            self.retry.show()
            self.result_summary.setText("导入失败：" + (error or "没有返回结果"))
            self.result_details.setPlainText("请在质量与操作审计中查看失败批次，修正来源后重新导入。\n"
                                             + self.result_description(self.result))
        else:
            self.result = data
            if data.get("check_only"):
                self.result_summary.setText("预检完成，未写入业务记录")
            else:
                batches = [str(row["batch_id"]) for row in data.get("files") or [] if row.get("batch_id")]
                batch_label = "、".join(batches) or str(data.get("batch_id") or "/")
                self.result_summary.setText(f"新增 {data.get('inserted', 0)} 条，更新 {data.get('updated', 0)} 条，"
                                            f"跳过 {data.get('skipped', 0)} 条；批次 {batch_label}")
                self.imported.emit(data)
            self.result_details.setPlainText(self.result_description(data))
        for key, label in self.metric_values.items():
            value = self.result.get(key, self.result.get("invalid_count", 0) if key == "error_total" else 0)
            if key == "parsed":
                value = self.result.get("parsed", self.result.get("parsed_total", 0))
            label.setText(f"{int(value or 0):,}")
        self.result_metrics.setVisible(bool(self.result))
        self.result_disclosure.setChecked(bool(error))
        self.next()

    def retry_import(self):
        self.ready_source = self.ready_preview = self.finished = self.busy = self.executing = False
        self.generation += 1
        self.result = {}
        self.result_disclosure.setChecked(False)
        self.retry.hide()
        self.source_status.setText("")
        self.restart()

    def reject(self):
        if self.executing:
            return
        self.closed = True
        self._clear_report_choices()
        if getattr(self, "_scan_job", None):
            self._scan_job.cancelled.set()
        self.timer.stop()
        super().reject()

    def closeEvent(self, event):
        if self.executing:
            event.ignore()
            return
        self.closed = True
        self._clear_report_choices()
        if getattr(self, "_scan_job", None):
            self._scan_job.cancelled.set()
        self.timer.stop()
        super().closeEvent(event)
