"""Single native wizard for inspection, source review, confirmation and commit."""
from __future__ import annotations

import uuid
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWizard, QWizardPage,
)


class ImportWizard(QWizard):
    imported = Signal(dict)

    def __init__(self, client, mapping_fields, preferences, parent=None, *, mode="excel"):
        super().__init__(parent)
        self.client, self.preferences = client, preferences
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
        source = self._page("选择来源")
        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.addItem("Excel 工作簿", "excel")
        self.mode.addItem("RPT 数据目录", "directory")
        self.mode.setCurrentIndex(max(0, self.mode.findData(mode)))
        form.addRow("来源类型", self.mode)
        path_row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setObjectName("importSourcePath")
        path_row.addWidget(self.path, 1)
        browse = QPushButton("选择")
        browse.clicked.connect(self.browse)
        path_row.addWidget(browse)
        form.addRow("来源路径", path_row)
        source.layout().addLayout(form)
        self.source_status = QLabel()
        self.source_status.setWordWrap(True)
        source.layout().addWidget(self.source_status)
        source.layout().addStretch()
        mapping = self._page("识别与字段映射")
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
        self.currentIdChanged.connect(self.page_changed)

    def _page(self, title):
        page = QWizardPage()
        page.setTitle(title)
        page.setLayout(QVBoxLayout())
        self.addPage(page)
        return page

    def invalidate(self, *_):
        self.ready_source = self.ready_preview = False
        self.generation += 1

    def browse(self):
        directory = self.preferences.get("source_path") or ""
        if self.mode.currentData() == "excel":
            path, _ = QFileDialog.getOpenFileName(self, "选择检测工作簿", directory, "Excel (*.xlsx *.xlsm *.xls)")
        else:
            path = QFileDialog.getExistingDirectory(self, "选择 RPT 数据目录", directory)
        if path:
            self.path.setText(path)

    def set_busy(self, busy):
        self.busy = busy
        for role in (QWizard.WizardButton.NextButton, QWizard.WizardButton.BackButton):
            self.button(role).setEnabled(not busy)
        self.button(QWizard.WizardButton.CancelButton).setEnabled(not self.executing)
        for widget in (self.path, self.mode, self.sheet, self.manual, self.header, self.policy, self.report_table):
            widget.setEnabled(not busy)
        self.mapping_host.setEnabled(not busy and self.manual.isChecked())

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
            endpoint = "/api/import-excel" if self.mode.currentData() == "excel" else "/api/import-directory-preview"
            payload = {**self.payload, "blank_indication_policy": "check"}
            self.client.post(endpoint, payload, self.preflight_loaded, task_token=self.token)
            return False
        if self.currentId() == 3:
            return self.finished
        return True

    def source_loaded(self, generation, data, error):
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
        if excel:
            self.sheets = data.get("sheets") or []
            if not self.sheets:
                self.source_status.setText("没有可读取的工作表")
                return
            self.sheet.clear()
            for sheet in self.sheets:
                self.sheet.addItem(f"{sheet['name']} · {'已识别' if sheet.get('recognized') else '需映射'}", sheet)
            self.show_sheet()
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
        self.next()

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
            self.result_details.setPlainText("请在质量与操作审计中查看失败批次，修正来源后重新导入。")
        else:
            self.result = data
            if data.get("check_only"):
                self.result_summary.setText("预检完成，未写入业务记录")
            else:
                self.result_summary.setText(f"新增 {data.get('inserted', 0)} 条，更新 {data.get('updated', 0)} 条，"
                                            f"跳过 {data.get('skipped', 0)} 条；批次 {data.get('batch_id', '/')}")
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
        self.timer.stop()
        super().reject()

    def closeEvent(self, event):
        if self.executing:
            event.ignore()
            return
        self.closed = True
        self.timer.stop()
        super().closeEvent(event)
