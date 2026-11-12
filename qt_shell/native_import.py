"""Single native wizard for inspection, source review, confirmation and commit."""
from __future__ import annotations

import uuid
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QTabBar, QVBoxLayout, QWizard, QWizardPage,
)
from .constants import EXCEL_EXTENSIONS, EXCEL_SCAN_LIMIT, OFFICE_MAX_BYTES


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


class ImportWizard(QWizard):
    imported = Signal(dict)

    def __init__(self, client, mapping_fields, preferences, parent=None, *, mode="excel"):
        super().__init__(parent)
        self.client, self.preferences = client, preferences
        permissions = getattr(parent, "permissions", None)
        self.can_export = permissions is None or "export.create" in permissions
        self.setWindowTitle("导入检测数据")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.resize(1050, 790)
        self.setMinimumSize(820, 620)
        self.setButtonText(QWizard.WizardButton.NextButton, "下一步")
        self.setButtonText(QWizard.WizardButton.BackButton, "上一步")
        self.setButtonText(QWizard.WizardButton.CancelButton, "取消")
        self.setButtonText(QWizard.WizardButton.FinishButton, "完成")
        self.ready_source = self.ready_preview = self.finished = self.busy = self.executing = False
        self.closed = False
        self.sheets, self.options, self.group_controls = [], [], []
        self.payload, self.result = {}, {}
        self.token = None
        self.generation = 0
        self.source_paths = []
        self.file_mappings = {}
        self._mapping_path = ""
        source = self._page("选择来源")
        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.addItem("Excel 工作簿", "excel")
        self.mode.addItem("RPT 数据目录", "directory")
        self.mode.setCurrentIndex(max(0, self.mode.findData(mode)))
        self.source_tabs = QTabBar()
        self.source_tabs.addTab("Excel 检测数据")
        self.source_tabs.addTab("原始 RPT 数据")
        self.source_tabs.setCurrentIndex(self.mode.currentIndex())
        self.source_tabs.currentChanged.connect(self.mode.setCurrentIndex)
        self.mode.currentIndexChanged.connect(self.source_tabs.setCurrentIndex)
        source.layout().addWidget(self.source_tabs)
        self.mode.hide()
        path_row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setObjectName("importSourcePath")
        path_row.addWidget(self.path, 1)
        browse = QPushButton("选择")
        browse.clicked.connect(self.browse)
        path_row.addWidget(browse)
        form.addRow("来源路径", path_row)
        source.layout().addLayout(form)
        choices = QHBoxLayout()
        self.add_files = QPushButton("选择多个 Excel 文件")
        self.add_files.clicked.connect(self.browse_files)
        self.add_folder = QPushButton("选择 Excel 文件夹")
        self.add_folder.clicked.connect(self.browse_excel_folder)
        self.remove_file = QPushButton("移除所选文件")
        self.remove_file.clicked.connect(self.remove_source)
        for control in (self.add_files, self.add_folder, self.remove_file):
            choices.addWidget(control)
        source.layout().addLayout(choices)
        self.queue_table = QTableWidget(0, 2)
        self.queue_table.setHorizontalHeaderLabels(["来源文件", "处理状态"])
        self.queue_table.horizontalHeader().setStretchLastSection(True)
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.queue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        source.layout().addWidget(self.queue_table, 1)
        self.source_status = QLabel()
        self.source_status.setWordWrap(True)
        source.layout().addWidget(self.source_status)
        source.layout().addStretch()
        mapping = self._page("识别与字段映射")
        self.file_choice = QComboBox()
        self.file_choice.currentIndexChanged.connect(self.select_mapping_file)
        mapping.layout().addWidget(self.file_choice)
        settings = QHBoxLayout()
        self.sheet = QComboBox()
        self.sheet.setObjectName("importWorksheet")
        settings.addWidget(self.sheet, 1)
        self.manual = QCheckBox("手动映射当前工作表")
        settings.addWidget(self.manual)
        self.header = QSpinBox()
        self.header.setRange(1, 9999)
        settings.addWidget(QLabel("表头行"))
        settings.addWidget(self.header)
        mapping.layout().addLayout(settings)
        self.mapping_form = QFormLayout()
        self.columns = {}
        for key, label, required in mapping_fields:
            combo = QComboBox()
            combo.setObjectName("importMapping_" + key)
            self.columns[key] = combo
            self.mapping_form.addRow(label + (" *" if required else ""), combo)
        # Two columns keep the mapping form and raw source rows visible together.
        from PySide6.QtWidgets import QWidget, QSplitter
        mapping_host = QWidget()
        mapping_host.setLayout(self.mapping_form)
        self.mapping_host = mapping_host
        split = QSplitter()
        split.addWidget(mapping_host)
        self.source_table = QTableWidget()
        self.source_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        split.addWidget(self.source_table)
        split.setSizes([360, 650])
        mapping.layout().addWidget(split, 1)
        self.report_table = QTableWidget(0, 5)
        self.report_table.setHorizontalHeaderLabels(["基地/机组", "大修", "数据组", "候选报告", "记录数"])
        self.report_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.report_table.horizontalHeader().setStretchLastSection(True)
        mapping.layout().addWidget(self.report_table, 1)
        self.directory_export = QPushButton("仅生成并保存标准 Excel")
        self.directory_export.clicked.connect(self.export_directory)
        self.directory_export.setEnabled(self.can_export)
        mapping.layout().addWidget(self.directory_export)
        self.mapping_note = QLabel()
        self.mapping_note.setWordWrap(True)
        mapping.layout().addWidget(self.mapping_note)
        self.policy = QComboBox()
        self.policy.addItem("空三字符进入待复核", "review")
        self.policy.addItem("空三字符按 WAR 填充", "fill_war")
        self.policy.addItem("仅预检，不写入记录", "check")
        mapping.layout().addWidget(self.policy)
        preview = self._page("预检与确认")
        self.preview_summary = QLabel()
        self.preview_summary.setWordWrap(True)
        preview.layout().addWidget(self.preview_summary)
        self.preview_table = QTableWidget()
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
        result.layout().addWidget(self.result_summary)
        self.result_details = QPlainTextEdit()
        self.result_details.setReadOnly(True)
        result.layout().addWidget(self.result_details, 1)
        self.retry = QPushButton("修正后重试")
        self.retry.clicked.connect(self.retry_import)
        self.retry.hide()
        result.layout().addWidget(self.retry)
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

    def _page(self, title):
        page = QWizardPage()
        page.setTitle(title)
        page.setLayout(QVBoxLayout())
        self.addPage(page)
        return page

    def invalidate(self, *_):
        self.ready_source = self.ready_preview = False
        self.generation += 1

    def _source_mode_changed(self, *_):
        excel = self.mode.currentData() == "excel"
        for control in (self.add_files, self.add_folder, self.remove_file, self.queue_table, self.file_choice):
            control.setVisible(excel)

    def set_sources(self, paths):
        self.source_paths = list(dict.fromkeys(str(Path(path).resolve()) for path in paths))
        self.file_mappings = {key: value for key, value in self.file_mappings.items() if key in self.source_paths}
        self.queue_table.setRowCount(len(self.source_paths))
        for row, path in enumerate(self.source_paths):
            self.queue_table.setItem(row, 0, QTableWidgetItem(path))
            self.queue_table.setItem(row, 1, QTableWidgetItem("待预检"))
        self.queue_table.setColumnWidth(0, 680)
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
        for role in (QWizard.WizardButton.NextButton, QWizard.WizardButton.BackButton):
            self.button(role).setEnabled(not busy)
        self.button(QWizard.WizardButton.CancelButton).setEnabled(not self.executing)
        for widget in (self.path, self.mode, self.source_tabs, self.file_choice, self.add_files, self.add_folder,
                       self.remove_file, self.sheet, self.manual, self.header, self.policy, self.report_table,
                       self.directory_export):
            widget.setEnabled(not busy)
        self.mapping_host.setEnabled(not busy and self.manual.isChecked())
        self.directory_export.setEnabled(not busy and self.can_export)

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
        if self.closed:
            return
        self.set_busy(False)
        if generation != self.generation:
            self.source_status.setText("来源已改变，请重新识别")
            return
        if error or not data:
            self.source_status.setText(error or "来源识别失败")
            return
        excel = self.mode.currentData() == "excel"
        for widget in (self.sheet, self.manual, self.header, self.mapping_host, self.source_table):
            widget.setVisible(excel)
        self.report_table.setVisible(not excel)
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
            groups = {}
            for row in self.options:
                if row.get("path") and not row.get("error"):
                    key = (row.get("site_code") or "", int(row.get("unit_id") or 0),
                           row.get("outage") or "", row.get("group") or "")
                    groups.setdefault(key, []).append(row)
            if not groups:
                self.source_status.setText("未找到可解析的 RPT 数据组")
                return
            self.report_table.setRowCount(len(groups))
            self.group_controls = []
            for index, (key, candidates) in enumerate(sorted(groups.items())):
                candidates.sort(key=lambda row: int(row.get("modified_ns") or 0), reverse=True)
                for column, text in enumerate((f"{key[0]}/{key[1]}", key[2], key[3])):
                    self.report_table.setItem(index, column, QTableWidgetItem(str(text)))
                combo = QComboBox()
                if len(candidates) > 1 and self.preferences.get("report_policy") != "latest":
                    combo.addItem("请选择报告版本", None)
                for row in candidates:
                    combo.addItem(f"{row.get('name') or Path(row['path']).name} · {row.get('records', 0)} 条", row)
                self.report_table.setCellWidget(index, 3, combo)
                self.report_table.setItem(index, 4, QTableWidgetItem(str(candidates[0].get("records", 0))))
                self.group_controls.append(combo)
            self.report_table.setColumnWidth(3, 430)
            failed = sum(bool(row.get("error")) for row in self.options)
            self.mapping_note.setText(f"{len(groups)} 个数据组；每组选择唯一报告。"
                                      f"{failed} 份失败候选未入选。" +
                                      "\n".join(f"{row.get('path', '')}：{row.get('error')}"
                                                for row in self.options if row.get("error")))
        self.ready_source = True
        if advance:
            self.next()

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
            if any(combo.currentData() is None for combo in self.group_controls):
                QMessageBox.warning(self, "报告版本", "请逐组确认要入库的 RPT 报告")
                return False
            self.payload["reports"] = [combo.currentData()["path"] for combo in self.group_controls]
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
        import json
        errors = data.get("errors") or data.get("invalid_rows") or []
        self.preview_errors.setPlainText("\n".join(
            row if isinstance(row, str) else json.dumps(row, ensure_ascii=False) for row in errors) or "预检未报告错误")
        # Advance directly because validateCurrentPage would otherwise rerun preflight.
        self.ready_preview = True
        self._advance_after_preflight()

    def _advance_after_preflight(self):
        self._accept_preflight_once = True
        self.next()

    def page_changed(self, page):
        if page == 4:
            self.button(QWizard.WizardButton.BackButton).setEnabled(False)
        self.setButtonText(QWizard.WizardButton.NextButton, "开始导入" if page == 2 else "下一步")
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
        import json
        if error or not data:
            self.retry.show()
            self.result_summary.setText("导入失败：" + (error or "没有返回结果"))
            self.result_details.setPlainText("请在质量与操作审计中查看失败批次，修正来源后重新导入。\n"
                                             + json.dumps(self.result, ensure_ascii=False, indent=2))
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
            self.result_details.setPlainText(json.dumps(data, ensure_ascii=False, indent=2))
        self.next()

    def retry_import(self):
        self.ready_source = self.ready_preview = self.finished = self.busy = self.executing = False
        self.generation += 1
        self.result = {}
        self.retry.hide()
        self.source_status.setText("")
        self.restart()

    def reject(self):
        if self.executing:
            return
        self.closed = True
        if getattr(self, "_scan_job", None):
            self._scan_job.cancelled.set()
        self.timer.stop()
        super().reject()

    def closeEvent(self, event):
        if self.executing:
            event.ignore()
            return
        self.closed = True
        if getattr(self, "_scan_job", None):
            self._scan_job.cancelled.set()
        self.timer.stop()
        super().closeEvent(event)
