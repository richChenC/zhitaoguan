"""Native settings categories, sharing the live account and maintenance pages."""
from __future__ import annotations

from PySide6.QtCore import QSize, QSignalBlocker, QTimer, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QListWidget, QMessageBox, QPushButton, QSpinBox,
    QStackedWidget, QVBoxLayout, QWidget, QLineEdit, QGroupBox, QScrollArea, QTableWidget, QTableWidgetItem,
    QListWidgetItem, QStyledItemDelegate, QStyle, QStyleOptionViewItem, QTabWidget,
)

from .native_components import button


class SettingsNavigationDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(204, 66)

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        opt.widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        painter.save()
        painter.setPen(opt.palette.text().color())
        title = QFont(opt.font)
        title.setBold(True)
        painter.setFont(title)
        rect = opt.rect.adjusted(16, 8, -8, -8)
        painter.drawText(rect.adjusted(0, 0, 0, -22), Qt.AlignmentFlag.AlignVCenter,
                         index.data(Qt.ItemDataRole.DisplayRole))
        subtitle = QFont(opt.font)
        subtitle.setPointSize(max(8, subtitle.pointSize() - 1))
        painter.setFont(subtitle)
        color = opt.palette.text().color()
        color.setAlpha(180)
        painter.setPen(color)
        painter.drawText(rect.adjusted(0, 24, 0, 0), Qt.AlignmentFlag.AlignVCenter,
                         index.data(Qt.ItemDataRole.UserRole) or "")
        painter.restore()


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
        body.setSpacing(22)
        sidebar = QWidget()
        sidebar.setObjectName("settingsSidebar")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(10, 12, 10, 14)
        caption = QLabel("偏好与维护")
        caption.setObjectName("muted")
        sidebar_layout.addWidget(caption)
        self.nav = QListWidget()
        self.nav.setObjectName("settingsNav")
        self.nav.setItemDelegate(SettingsNavigationDelegate(self.nav))
        sidebar.setFixedWidth(236)
        sidebar_layout.addWidget(self.nav)
        local = QLabel("本地 SQLite")
        local.setObjectName("muted")
        sidebar_layout.addWidget(local)
        sidebar_layout.addStretch()
        self.stack = QStackedWidget()
        self.stack.setObjectName("settingsStack")
        body.addWidget(sidebar)
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)

        # Move the existing pages into categories without changing their clients.
        account_page.tabs.removeTab(account_page.tabs.indexOf(account_page.source))
        storage = QWidget()
        storage_layout = QVBoxLayout(storage)
        storage_layout.addWidget(account_page.source)
        account_page.source.show()
        quick_heading = QLabel("常用操作")
        quick_heading.setObjectName("settingsSectionTitle")
        storage_layout.addWidget(quick_heading)
        self.quick_actions = {}
        quick_actions = QHBoxLayout()
        for text, index, name in (("导入与显示", 2, "upload"), ("对比规则", 3, "arrow-right-left"),
                                  ("备份与维护", 5, "archive-restore")):
            jump = button(text, name, lambda _checked=False, target=index: self.nav.setCurrentRow(target))
            self.quick_actions[index] = jump
            quick_actions.addWidget(jump, 1)
        storage_layout.addLayout(quick_actions)
        storage_layout.addStretch()
        self.add_page("数据存储", storage, subtitle="本地数据库", title="当前数据库", scroll=True)
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
        self.theme.hide()
        theme_host = QWidget()
        theme_layout = QHBoxLayout(theme_host)
        theme_layout.setContentsMargins(0, 0, 0, 0)
        theme_layout.setSpacing(0)
        self.theme_choices = {}
        for text, value, name in (("跟随系统", "system", None), ("日间", "light", "sun"), ("夜间", "dark", "moon")):
            choice = button(text, name, lambda _checked=False, key=value: self.theme.setCurrentIndex(self.theme.findData(key)))
            choice.setCheckable(True)
            choice.setChecked(value == self.theme.currentData())
            self.theme_choices[value] = choice
            theme_layout.addWidget(choice)
        self.theme.currentIndexChanged.connect(self._theme_selected)
        self.theme.setParent(theme_host)
        self.theme.hide()
        self.density = QComboBox()
        self.density.addItem("标准", "comfortable")
        self.density.addItem("紧凑", "compact")
        self.density.setCurrentIndex(max(0, self.density.findData(preferences.values["density"])))
        self.animations = QCheckBox()
        self.animations.setChecked(preferences.values["animations"])
        self.start = QComboBox()
        self.start.addItem("恢复上次工作区", -1)
        for index, text in enumerate(("数据工作台", "三维缺陷模型", "数据可视化", "报告中心", "状态处理")):
            self.start.addItem(text, index)
        self.start.setCurrentIndex(self.start.findData(-1 if preferences.values["remember_page"]
                                                       else int(preferences.values["start_page"])))
        self.remember = QCheckBox()
        self.remember.setChecked(preferences.values["remember_page"])
        self.direction = QComboBox()
        for text, value in (("正向（+）", "1"), ("负向（-）", "-1"), ("留待核对", "pending")):
            self.direction.addItem(text, value)
        self.policy = QComboBox()
        for name, value in (("手动选择 RPT", "manual"), ("预选最新并逐组确认", "latest")):
            self.policy.addItem(name, value)
        self.policy.setCurrentIndex(max(0, self.policy.findData(preferences.values["report_policy"])))
        form = group("界面显示")
        for label, widget in (("外观模式", theme_host), ("工作区密度", self.density), ("交互动画", self.animations)):
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
        for label, widget in (("无符号移位默认方向", self.direction),):
            form.addRow(label, widget)
        flow_layout.addWidget(button("恢复默认偏好", "rotate-ccw", self.reset_preferences))
        flow_layout.addStretch()
        for control in (self.theme, self.density, self.notification_duration):
            control.currentIndexChanged.connect(self._queue_preferences)
        for control in (self.animations, self.notification_sound, self.auto_ndd):
            control.toggled.connect(self._queue_preferences)
        self.start.currentIndexChanged.connect(self._startup_selected)
        self.remember.toggled.connect(self._remember_selected)
        self.direction.activated.connect(self.save_direction)
        self.add_page("界面与工作流", flow, subtitle="偏好设置", scroll=True)
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
        parsing_group = QGroupBox("文件解析")
        parsing_form = QFormLayout(parsing_group)
        parsing_form.addRow("RPT 选择策略", self.policy)
        display_layout.addWidget(parsing_group)
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
        self.point_labels = QCheckBox("在趋势与分布图数据点旁显示数值")
        self.point_labels.setChecked(preferences.values["point_labels"])
        self.ndd_zero = QCheckBox("NDD 记 0 深度")
        self.ndd_zero.setToolTip("前次明确 NDD 按 0 基线计算匹配增量；关闭后留空。判定值，非实测。")
        self.ndd_zero.setChecked(preferences.values["ndd_zero"])
        form.addRow("图表数值标注", self.point_labels)
        form.addRow("检测结论", self.auto_ndd)
        form.addRow("NDD 深度基线", self.ndd_zero)
        self.display_status = QLabel("导入与显示设置已保存")
        self.display_status.setObjectName("muted")
        display_layout.addWidget(self.display_status)
        display_layout.addStretch()
        self.source_path.editingFinished.connect(self.save_display)
        self.policy.currentIndexChanged.connect(self._queue_display)
        self.point_labels.toggled.connect(self._queue_display)
        self.ndd_zero.toggled.connect(self._queue_display)
        for control in self.levels:
            control.valueChanged.connect(self._queue_display)
        self.add_page("导入与显示", display, subtitle="来源与可视化", scroll=True)
        rules = QWidget()
        rules_layout = QVBoxLayout(rules)
        self.rules_text = QLabel()
        self.rules_text.setWordWrap(True)
        rules_layout.addWidget(self.rules_text)
        self.create_rule = button("建立并激活规则版本", "settings", rules_action)
        self.create_rule.setEnabled("settings.manage" in self.permissions)
        rules_layout.addWidget(self.create_rule)
        rules_layout.addStretch()
        self.add_page("对比规则", rules, subtitle="历次结果匹配")
        client.get("/api/analysis-rules", self._rules_loaded)
        self.add_page("账户与权限", account_page, subtitle="个人账户、角色与密码")
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
        self.maintenance_tabs = QTabWidget()
        self.maintenance_tabs.addTab(maintenance, "备份与恢复")
        self.maintenance_tabs.addTab(maintenance_page, "质量与操作审计")
        self.add_page("备份与维护", self.maintenance_tabs, subtitle="安全与审计")
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setMinimumHeight(self.nav.count() * 66 + 8)
        self.nav.setCurrentRow(0)
        self.preferences.changed.connect(self._sync_report_policy)
        if "backup.manage" in self.permissions:
            client.get("/api/backup-policy", self._policy_loaded)

    def _sync_report_policy(self):
        with QSignalBlocker(self.policy):
            self.policy.setCurrentIndex(self.policy.findData(self.preferences.values["report_policy"]))

    def add_page(self, text, widget, *, subtitle="", title=None, scroll=False):
        widget.setObjectName(widget.objectName() or "settingsPage")
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, subtitle)
        item.setToolTip(f"{text} · {subtitle}")
        self.nav.addItem(item)
        panel = QWidget()
        panel.setObjectName("settingsSection")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 12, 16, 16)
        heading = QLabel(title or text)
        heading.setObjectName("settingsSectionTitle")
        layout.addWidget(heading)
        layout.addWidget(widget, 1)
        widget = panel
        if scroll:
            host = QScrollArea()
            host.setWidgetResizable(True)
            host.setFrameShape(QScrollArea.Shape.NoFrame)
            host.setWidget(widget)
            widget = host
        self.stack.addWidget(widget)

    def _theme_selected(self, *_):
        for key, choice in self.theme_choices.items():
            choice.setChecked(key == self.theme.currentData())

    def _startup_selected(self, *_):
        with QSignalBlocker(self.remember):
            self.remember.setChecked(self.start.currentData() == -1)
        self._queue_preferences()

    def _remember_selected(self, checked):
        with QSignalBlocker(self.start):
            value = -1 if checked else self.preferences.values["start_page"]
            self.start.setCurrentIndex(self.start.findData(value))
        self._queue_preferences()

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
        self.start.setCurrentIndex(self.start.findData(-1 if defaults["remember_page"] else defaults["start_page"]))
        self.policy.setCurrentIndex(self.policy.findData(defaults["report_policy"]))
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
                                  animations=self.animations.isChecked(),
                                  start_page=(self.start.currentData() if self.start.currentData() != -1
                                              else self.preferences.values["start_page"]),
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
                                  depth_levels=levels, depth_colors=self.color_values,
                                  point_labels=self.point_labels.isChecked(), ndd_zero=self.ndd_zero.isChecked())
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
