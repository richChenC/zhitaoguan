"""Native settings categories, sharing the live account and maintenance pages."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QListWidget, QMessageBox, QPushButton, QSpinBox,
    QStackedWidget, QVBoxLayout, QWidget, QLineEdit, QGroupBox, QScrollArea, QTableWidget, QTableWidgetItem,
)

from .native_components import button


class SettingsDialog(QDialog):
    preferencesChanged = Signal()

    def __init__(self, client, preferences, account_page, maintenance_page, rules_action, parent=None):
        super().__init__(parent)
        self.setWindowTitle("软件设置")
        self.resize(1180, 820)
        self.setMinimumSize(820, 600)
        self.client, self.preferences = client, preferences
        self.permissions = set(account_page.user.get("permissions") or [])
        self._preference_timer = QTimer(self)
        self._preference_timer.setSingleShot(True)
        self._preference_timer.setInterval(200)
        self._preference_timer.timeout.connect(self.save_preferences)
        self._display_timer = QTimer(self)
        self._display_timer.setSingleShot(True)
        self._display_timer.setInterval(250)
        self._display_timer.timeout.connect(self.save_display)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 18)
        root.setSpacing(12)
        heading = QHBoxLayout()
        title = QLabel("软件设置")
        title.setObjectName("pageTitle")
        heading.addWidget(title)
        heading.addStretch()
        source = QLabel("本地 SQLite")
        source.setObjectName("muted")
        heading.addWidget(source)
        root.addLayout(heading)
        body = QHBoxLayout()
        body.setSpacing(14)
        self.nav = QListWidget()
        self.nav.setObjectName("settingsNav")
        self.nav.setFixedWidth(210)
        self.stack = QStackedWidget()
        self.stack.setObjectName("settingsStack")
        body.addWidget(self.nav)
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)

        # Move the existing pages into categories without changing their clients.
        account_page.tabs.removeTab(account_page.tabs.indexOf(account_page.source))
        self.add_page("数据存储", account_page.source)
        flow = QWidget()
        flow_layout = QVBoxLayout(flow)
        self.save_status = QLabel("偏好已保存")
        self.save_status.setObjectName("muted")
        flow_layout.addWidget(self.save_status)

        def group(title):
            box = QGroupBox(title)
            form = QFormLayout(box)
            form.setVerticalSpacing(12)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            flow_layout.addWidget(box)
            return form

        self.theme = QComboBox()
        self.theme.addItem("日间", "light")
        self.theme.addItem("夜间", "dark")
        self.theme.addItem("跟随系统", "system")
        self.theme.setCurrentIndex(max(0, self.theme.findData(preferences.values["theme"])))
        self.density = QComboBox()
        self.density.addItem("标准", "comfortable")
        self.density.addItem("紧凑", "compact")
        self.density.setCurrentIndex(max(0, self.density.findData(preferences.values["density"])))
        self.animations = QCheckBox()
        self.animations.setChecked(preferences.values["animations"])
        self.start = QComboBox()
        self.start.addItems(["数据工作台", "三维缺陷模型", "数据可视化", "报告中心", "状态处理"])
        self.start.setCurrentIndex(int(preferences.values["start_page"]))
        self.remember = QCheckBox()
        self.remember.setChecked(preferences.values["remember_page"])
        self.direction = QComboBox()
        for text, value in (("正向（+）", "1"), ("负向（-）", "-1"), ("留待核对", "pending")):
            self.direction.addItem(text, value)
        form = group("界面显示")
        for label, widget in (("外观", self.theme), ("工作区密度", self.density), ("交互动画", self.animations)):
            form.addRow(label, widget)
        form = group("操作通知")
        self.notification_duration = QComboBox()
        for text, value in (("3 秒", 3000), ("5 秒", 5000), ("手动关闭", 0)):
            self.notification_duration.addItem(text, value)
        self.notification_duration.setCurrentIndex(max(0, self.notification_duration.findData(
            preferences.values["notification_duration"])))
        self.notification_sound = QCheckBox("播放提示音")
        self.notification_sound.setChecked(preferences.values["notification_sound"])
        form.addRow("提示停留时间", self.notification_duration)
        form.addRow("提示音", self.notification_sound)
        form = group("启动与导航")
        for label, widget in (("启动工作区", self.start), ("记住上次工作区", self.remember)):
            form.addRow(label, widget)
        form = group("状态与导入默认值")
        self.auto_ndd = QCheckBox("自动识别无磨损信息的空白结论为 NDD")
        self.auto_ndd.setChecked(preferences.values["auto_ndd"])
        for label, widget in (("无符号移位默认方向", self.direction), ("检测结论", self.auto_ndd)):
            form.addRow(label, widget)
        flow_layout.addWidget(button("恢复默认偏好", "rotate-ccw", self.reset_preferences))
        flow_layout.addStretch()
        for control in (self.theme, self.density, self.start, self.notification_duration):
            control.currentIndexChanged.connect(self._queue_preferences)
        for control in (self.animations, self.remember, self.notification_sound, self.auto_ndd):
            control.toggled.connect(self._queue_preferences)
        self.direction.activated.connect(self.save_direction)
        self.add_page("界面与工作流", flow, scroll=True)
        client.get("/api/settings/state-direction", self._direction_loaded)
        display = QWidget()
        display_layout = QVBoxLayout(display)
        source_group = QGroupBox("导入来源")
        form = QFormLayout(source_group)
        display_layout.addWidget(source_group)
        self.source_path = QLineEdit(str(preferences.values["source_path"]))
        select = button("选择目录", "funnel", self.choose_source)
        row = QHBoxLayout()
        row.addWidget(self.source_path, 1)
        row.addWidget(select)
        form.addRow("默认导入目录", row)
        self.policy = QComboBox()
        for name, value in (("手动确认 Report", "manual"), ("每组最新 Report", "latest")):
            self.policy.addItem(name, value)
        self.policy.setCurrentIndex(max(0, self.policy.findData(preferences.values["report_policy"])))
        form.addRow("Report 使用策略", self.policy)
        self.scan_source = button("扫描来源目录", "search", self.scan_sources)
        form.addRow(self.scan_source)
        self.source_results = QTableWidget(0, 3)
        self.source_results.setHorizontalHeaderLabels(["目录", "基地/机组", "大修"])
        self.source_results.horizontalHeader().setStretchLastSection(True)
        self.source_results.setMaximumHeight(180)
        self.source_results.hide()
        form.addRow(self.source_results)
        self.scan_status = QLabel()
        self.scan_status.setWordWrap(True)
        form.addRow(self.scan_status)
        depth_group = QGroupBox("磨损显示分级")
        form = QFormLayout(depth_group)
        display_layout.addWidget(depth_group)
        self.levels = []
        for i, value in enumerate(preferences.values["depth_levels"]):
            level = QSpinBox()
            level.setRange(1, 100)
            level.setValue(value)
            self.levels.append(level)
            form.addRow(f"磨损深度分界 {i + 1}（%）", level)
        self.color_values = list(preferences.values["depth_colors"])
        self.swatches = []
        colors = QHBoxLayout()
        for i, value in enumerate(self.color_values):
            swatch = QPushButton()
            swatch.setFixedSize(46, 30)
            swatch.setToolTip(f"第 {i + 1} 档磨损颜色")
            swatch.setStyleSheet(f"background:{value}")
            swatch.clicked.connect(lambda _, index=i: self.choose_color(index))
            self.swatches.append(swatch)
            colors.addWidget(swatch)
        colors.addStretch()
        form.addRow("深度色阶", colors)
        self.display_status = QLabel("导入与显示设置已保存")
        self.display_status.setObjectName("muted")
        display_layout.addWidget(self.display_status)
        display_layout.addStretch()
        self.source_path.editingFinished.connect(self.save_display)
        self.policy.currentIndexChanged.connect(self._queue_display)
        for control in self.levels:
            control.valueChanged.connect(self._queue_display)
        self.add_page("导入与显示", display, scroll=True)
        rules = QWidget()
        rules_layout = QVBoxLayout(rules)
        self.rules_text = QLabel()
        self.rules_text.setWordWrap(True)
        rules_layout.addWidget(self.rules_text)
        self.create_rule = button("建立并激活规则版本", "settings", rules_action)
        self.create_rule.setEnabled("settings.manage" in self.permissions)
        rules_layout.addWidget(self.create_rule)
        rules_layout.addStretch()
        self.add_page("对比规则", rules)
        client.get("/api/analysis-rules", self._rules_loaded)
        self.add_page("账户与权限", account_page)
        maintenance = QWidget()
        maintenance_layout = QVBoxLayout(maintenance)
        # Account and runtime logs remain in their existing native tabs.
        backup_index = account_page.tabs.indexOf(account_page.backups.parentWidget())
        backup_host = account_page.backups.parentWidget()
        if backup_index >= 0:
            account_page.tabs.removeTab(backup_index)
        maintenance_layout.addWidget(backup_host)
        backup_host.show()
        policy_row = QHBoxLayout()
        policy_row.addWidget(QLabel("自动备份保留数量"))
        self.keep = QSpinBox()
        self.keep.setRange(5, 200)
        self.keep.setValue(20)
        policy_row.addWidget(self.keep)
        self.save_policy = button("保存备份策略", "save", self.save_backup_policy)
        self.restore_external = button("选择外部备份恢复", "archive-restore", lambda: self.select_backup(account_page))
        self.deduplicate_button = button("数据库去重", "check-check", self.deduplicate)
        self.keep.setEnabled("backup.manage" in self.permissions)
        self.save_policy.setEnabled("backup.manage" in self.permissions)
        self.restore_external.setEnabled({"backup.manage", "database.restore"} <= self.permissions)
        self.deduplicate_button.setEnabled("data.purge" in self.permissions)
        policy_row.addWidget(self.save_policy)
        policy_row.addWidget(self.restore_external)
        policy_row.addWidget(self.deduplicate_button)
        policy_row.addStretch()
        maintenance_layout.addLayout(policy_row)
        self.add_page("备份与维护", maintenance)
        self.add_page("质量与操作审计", maintenance_page)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        if "backup.manage" in self.permissions:
            client.get("/api/backup-policy", self._policy_loaded)

    def add_page(self, text, widget, *, scroll=False):
        widget.setObjectName(widget.objectName() or "settingsPage")
        self.nav.addItem(text)
        if scroll:
            host = QScrollArea()
            host.setWidgetResizable(True)
            host.setFrameShape(QScrollArea.Shape.NoFrame)
            host.setWidget(widget)
            widget = host
        self.stack.addWidget(widget)

    def choose_source(self):
        path = QFileDialog.getExistingDirectory(self, "选择默认导入目录", self.source_path.text())
        if path:
            self.source_path.setText(path)
            self.save_display()

    def choose_color(self, index):
        from PySide6.QtGui import QColor
        color = QColorDialog.getColor(QColor(self.color_values[index]), self)
        if color.isValid():
            self.color_values[index] = color.name()
            self.swatches[index].setStyleSheet(f"background:{color.name()}")
            self.save_display()

    def _queue_preferences(self, *_):
        self.save_status.setText("正在保存...")
        self._preference_timer.start()

    def _queue_display(self, *_):
        self.display_status.setText("正在保存...")
        self._display_timer.start()

    def reset_preferences(self):
        defaults = self.preferences.defaults
        for control, key in ((self.theme, "theme"), (self.density, "density"),
                             (self.notification_duration, "notification_duration")):
            control.setCurrentIndex(control.findData(defaults[key]))
        self.start.setCurrentIndex(defaults["start_page"])
        for control, key in ((self.animations, "animations"), (self.remember, "remember_page"),
                             (self.notification_sound, "notification_sound"), (self.auto_ndd, "auto_ndd")):
            control.setChecked(defaults[key])
        self.save_preferences()

    def scan_sources(self):
        path = self.source_path.text().strip()
        if not path:
            self.scan_status.setText("请选择来源目录")
            return
        self.scan_source.setEnabled(False)
        self.scan_status.setText("正在扫描...")
        self.client.post("/api/discover-server", {"path": path}, self._sources_loaded)

    def _sources_loaded(self, data, error):
        self.scan_source.setEnabled(True)
        items = (data or {}).get("items") or []
        self.source_results.setRowCount(len(items))
        for row, item in enumerate(items):
            for col, value in enumerate((item.get("path", ""),
                                         f"{item.get('station') or item.get('site', '')} / {item.get('unit_id', '')}号机组",
                                         item.get("outage", ""))):
                self.source_results.setItem(row, col, QTableWidgetItem(str(value)))
        self.source_results.setVisible(bool(items))
        self.scan_status.setText(error or f"发现 {len(items)} 个来源；扫描 {(data or {}).get('scanned_directories', 0)} 个目录"
                                 + ("，目录较多，请缩小范围继续扫描" if (data or {}).get("truncated") else ""))

    def save_preferences(self):
        try:
            self.preferences.save(theme=self.theme.currentData(), density=self.density.currentData(),
                                  animations=self.animations.isChecked(), start_page=self.start.currentIndex(),
                                  remember_page=self.remember.isChecked(), auto_ndd=self.auto_ndd.isChecked(),
                                  notification_duration=self.notification_duration.currentData(),
                                  notification_sound=self.notification_sound.isChecked())
            self.preferencesChanged.emit()
            self.save_status.setText("偏好已保存")
        except OSError as exc:
            QMessageBox.warning(self, "保存失败", str(exc))

    def save_display(self):
        levels = [control.value() for control in self.levels]
        if levels != sorted(set(levels)):
            self.display_status.setText("分界值必须严格递增，尚未保存")
            return
        try:
            self.preferences.save(source_path=self.source_path.text(), report_policy=self.policy.currentData(),
                                  depth_levels=levels, depth_colors=self.color_values)
            self.preferencesChanged.emit()
            self.display_status.setText("导入与显示设置已保存")
        except OSError as exc:
            QMessageBox.warning(self, "保存失败", str(exc))

    def _direction_loaded(self, data, error):
        self.direction.setEnabled(bool(data and data.get("writable")))
        if data:
            self.direction.setCurrentIndex(max(0, self.direction.findData(data.get("shift_direction"))))

    def save_direction(self):
        self.client.post("/api/settings/state-direction", {"shift_direction": self.direction.currentData()},
                         self._direction_loaded)

    def _policy_loaded(self, data, error):
        if data:
            self.keep.setValue(int(data.get("automatic_keep") or 20))
        self.keep.setToolTip(error or "")

    def save_backup_policy(self):
        self.client.post("/api/backup-policy", {"automatic_keep": self.keep.value()}, self._policy_loaded)

    def _rules_loaded(self, data, error):
        active = (data or {}).get("active") or {}
        self.rules_text.setText(error or f"当前规则：{active.get('name', '')}\n"
                                f"版本：{active.get('version', 0)}\n"
                                f"轴向匹配容差：±{active.get('match_tolerance_mm', 0.01)} mm\n"
                                f"{active.get('note', '')}")

    def select_backup(self, page):
        path, _ = QFileDialog.getOpenFileName(self, "选择数据库备份", "", "数据库备份 (*.db)")
        if path:
            self.client.post("/api/backup-validate", {"path": path},
                             lambda data, error: page._backup_validated(path, data, error))

    def deduplicate(self):
        if QMessageBox.question(self, "数据库去重", "去重前自动备份。确认合并业务字段完全相同的记录？") == QMessageBox.StandardButton.Yes:
            self.client.post("/api/deduplicate", {}, lambda data, error: QMessageBox.information(
                self, "数据库去重", error or f"移除 {data.get('removed', 0)} 条重复记录"))

    def closeEvent(self, event):
        if self._preference_timer.isActive():
            self._preference_timer.stop()
            self.save_preferences()
        if self._display_timer.isActive():
            self._display_timer.stop()
            self.save_display()
        super().closeEvent(event)
