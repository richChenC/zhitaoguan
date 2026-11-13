"""Native settings categories, sharing the live account and maintenance pages."""
from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QSpinBox,
    QStackedWidget, QVBoxLayout, QWidget, QLineEdit, QGroupBox, QScrollArea, QTableWidget, QTableWidgetItem,
    QListWidgetItem, QTabWidget,
)

from .native_components import button
from .native_settings_layout import (
    SettingsNavigation, SettingsNavigationDelegate, SettingsPreferencePanel,
    SettingsQuickActions, SettingsToggle, settings_styles,
)


class SettingsDialog(QDialog):
    preferencesChanged = Signal()

    def __init__(self, client, preferences, account_page, maintenance_page, rules_action, parent=None):
        super().__init__(parent)
        self.setObjectName("nativeSettings")
        self.setWindowTitle("软件设置")
        self.resize(1180, 820)
        self.setMinimumSize(820, 600)
        self.client, self.preferences = client, preferences
        self._report_policy_value = preferences.values["report_policy"]
        self.permissions = set(account_page.user.get("permissions") or [])
        self._preference_timer = QTimer(self)
        self._preference_timer.setSingleShot(True)
        self._preference_timer.setInterval(200)
        self._preference_timer.timeout.connect(self.save_preferences)
        self._display_timer = QTimer(self)
        self._display_timer.setSingleShot(True)
        self._display_timer.setInterval(250)
        self._display_timer.timeout.connect(self.save_display)
        root = self.root_layout = QVBoxLayout(self)
        root.setContentsMargins(26, 26, 26, 28)
        root.setSpacing(0)
        body = self.body_layout = QHBoxLayout()
        body.setSpacing(22)
        sidebar = self.sidebar = QWidget()
        sidebar.setObjectName("settingsSidebar")
        caption = self.sidebar_caption = QLabel("偏好与维护", sidebar)
        caption.setObjectName("settingsSidebarCaption")
        self.nav = SettingsNavigation(sidebar)
        self.nav.setObjectName("settingsNav")
        self.nav.setItemDelegate(SettingsNavigationDelegate(self.nav))
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav.setMouseTracking(True)
        self.local = QWidget(sidebar)
        self.local.setObjectName("settingsLocal")
        dot = QWidget(self.local)
        dot.setObjectName("settingsLocalDot")
        dot.setGeometry(0, 20, 8, 8)
        local = QLabel("本地 SQLite", self.local)
        local.setGeometry(15, 15, 150, 17)
        self.stack = QStackedWidget()
        self.stack.setObjectName("settingsStack")
        body.addWidget(sidebar, 0, Qt.AlignmentFlag.AlignTop)
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)

        # Move the existing pages into categories without changing their clients.
        account_page.tabs.removeTab(account_page.tabs.indexOf(account_page.source))
        storage = QWidget()
        storage_layout = QVBoxLayout(storage)
        storage_layout.setContentsMargins(0, 0, 0, 0)
        storage_layout.setSpacing(28)
        storage_layout.addWidget(account_page.source)
        account_page.source.show()
        self.quick_host = SettingsQuickActions()
        self.quick_actions = self.quick_host.buttons
        self.quick_host.jumpRequested.connect(self._jump)
        storage_layout.addWidget(self.quick_host)
        storage_layout.addStretch()
        self.add_page("数据存储", storage, subtitle="本地数据库", title="当前数据库", scroll=True, framed=False)
        self.save_status = QLabel("修改后自动保存")
        self.preference_badge = QLabel("自动保存")
        self._saved_timer = QTimer(self)
        self._saved_timer.setSingleShot(True)
        self._saved_timer.setInterval(1800)
        self._saved_timer.timeout.connect(lambda: self.preference_badge.setText("自动保存"))

        self.theme = QComboBox()
        self.theme.addItem("日间", "light")
        self.theme.addItem("夜间", "dark")
        self.theme.addItem("跟随系统", "system")
        self.theme.setCurrentIndex(max(0, self.theme.findData(preferences.values["theme"])))
        self.theme.hide()
        theme_host = self.theme_host = QWidget()
        theme_host.setObjectName("settingsThemeSwitch")
        theme_host.setFixedSize(274, 40)
        theme_layout = QHBoxLayout(theme_host)
        theme_layout.setContentsMargins(4, 4, 4, 4)
        theme_layout.setSpacing(4)
        self.theme_choices = {}
        for text, value, name in (("跟随系统", "system", None), ("日间", "light", "sun"), ("夜间", "dark", "moon")):
            choice = button(text, name, lambda _checked=False, key=value: self.theme.setCurrentIndex(self.theme.findData(key)))
            choice.setCheckable(True)
            choice.setAutoExclusive(True)
            choice.setFixedSize(86, 32)
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
        self.animations = QComboBox()
        self.animations.addItem("完整反馈", True)
        self.animations.addItem("减少动画", False)
        self.animations.setCurrentIndex(self.animations.findData(preferences.values["animations"]))
        self.start = QComboBox()
        self.start.addItem("恢复上次工作区", -1)
        for index, text in enumerate(("数据工作台", "三维缺陷模型", "数据可视化", "报告中心", "状态处理")):
            self.start.addItem(text, index)
        self.start.setCurrentIndex(self.start.findData(-1 if preferences.values["remember_page"]
                                                       else int(preferences.values["start_page"])))
        self.remember = SettingsToggle("记住上次工作区")
        self.remember.setChecked(preferences.values["remember_page"])
        self.direction = QComboBox()
        self.direction.setEnabled(False)
        self._direction_value = None
        self._direction_busy = False
        self._direction_serial = 0
        self._direction_writable = False
        for text, value in (("正向（+）", "1"), ("负向（-）", "-1"), ("留待核对", "pending")):
            self.direction.addItem(text, value)
        self.policy = QComboBox()
        for name, value in (("手动选择 RPT", "manual"), ("预选最新并逐组确认", "latest")):
            self.policy.addItem(name, value)
        self.policy.setCurrentIndex(max(0, self.policy.findData(preferences.values["report_policy"])))
        self.notification_duration = QComboBox()
        for text, value in (("3 秒", 3000), ("5 秒", 5000), ("不自动隐藏", 0)):
            self.notification_duration.addItem(text, value)
        self.notification_duration.setCurrentIndex(max(0, self.notification_duration.findData(
            preferences.values["notification_duration"])))
        self.notification_sound = SettingsToggle("通知提示音")
        self.notification_sound.setChecked(preferences.values["notification_sound"])
        self.auto_ndd = QCheckBox("自动识别无磨损信息的空白结论为 NDD")
        self.auto_ndd.setChecked(preferences.values["auto_ndd"])
        self.reset_button = QPushButton("恢复本页默认")
        self.reset_button.clicked.connect(self.reset_preferences)
        self.preference_panel = SettingsPreferencePanel([
            ("界面显示", [
                ("外观模式", "跟随系统、日间或夜间；报告和管板的原始颜色不变", theme_host),
                ("工作区密度", "紧凑模式减少行距", self.density),
                ("交互动画", "减少界面过渡和弹出动画", self.animations)]),
            ("操作通知", [
                ("通知自动隐藏", "通知默认显示 3 秒；鼠标悬停或键盘聚焦时会暂停隐藏", self.notification_duration),
                ("通知提示音", "操作完成、提醒或失败时播放", self.notification_sound)]),
            ("启动与导航", [
                ("启动工作区", "下次启动恢复最后使用的主工作区" if self.remember.isChecked()
                 else "下次启动打开所选工作区", self.start),
                ("记住上次工作区", "启用后，启动页面同步为“恢复上次工作区”", self.remember)]),
            ("状态与导入默认值", [
                ("无符号移位默认方向", "识别到“移位 42 mm”但原文没有正负号时使用；“留待核对”不会自动确认方向", self.direction),
                ("RPT 选择策略", "手动逐组选择，或预选修改时间最新版本后逐组确认", self.policy)]),
        ], self.preference_badge, self.save_status, self.reset_button)
        self.start_hint = self.preference_panel.rows[5].hint
        flow = QWidget()
        flow_layout = QVBoxLayout(flow)
        flow_layout.setContentsMargins(0, 0, 0, 0)
        flow_layout.setSpacing(0)
        flow_layout.addWidget(self.preference_panel)
        flow_layout.addStretch()
        for control in (self.theme, self.density, self.animations, self.notification_duration):
            control.currentIndexChanged.connect(self._queue_preferences)
        for control in (self.notification_sound, self.auto_ndd):
            control.toggled.connect(self._queue_preferences)
        self.start.currentIndexChanged.connect(self._startup_selected)
        self.remember.toggled.connect(self._remember_selected)
        self.direction.activated.connect(self.save_direction)
        self.add_page("界面与工作流", flow, subtitle="偏好设置", scroll=True, framed=False)
        client.get("/api/settings/state-direction", lambda data, error: self._direction_loaded(data, error, 0))
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
        self.display_policy = QComboBox()
        for index in range(self.policy.count()):
            self.display_policy.addItem(self.policy.itemText(index), self.policy.itemData(index))
        self.display_policy.setCurrentIndex(self.policy.currentIndex())
        parsing_form.addRow("RPT 选择策略", self.display_policy)
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
        self.policy.currentIndexChanged.connect(self._preference_policy_selected)
        self.display_policy.currentIndexChanged.connect(self._display_policy_selected)
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
        self.nav.setCurrentRow(0)
        self.preferences.changed.connect(self._sync_report_policy)
        if "backup.manage" in self.permissions:
            client.get("/api/backup-policy", self._policy_loaded)
        self._layout_sidebar()

    def _jump(self, index):
        self.nav.setCurrentRow(index)
        self.nav.setFocus(Qt.FocusReason.OtherFocusReason)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "sidebar"):
            self._layout_sidebar()

    def _layout_sidebar(self):
        narrow = self.width() <= 900
        margin, top, gap, width = (16, 20, 14, 190) if narrow else (26, 26, 22, 236)
        self.root_layout.setContentsMargins(margin, top, margin, 28)
        self.body_layout.setSpacing(gap)
        self.sidebar.setFixedSize(width, 522)
        self.sidebar_caption.setGeometry(13, 19, width - 26, 29)
        self.nav.setGeometry(13, 48, width - 26, 407)
        self.local.setGeometry(23, 473, width - 46, 32)
        if hasattr(self, "preference_panel"):
            self.preference_panel.narrow = narrow
            self.preference_panel.window_width = self.width()
            self.preference_panel.relayout()

    def set_theme(self, theme):
        dark = theme == "dark"
        self.setStyleSheet(settings_styles(theme))
        self.nav.setProperty("dark", dark)
        self.nav.viewport().update()
        for control in self.quick_actions.values():
            control.set_theme(dark)
        self.preference_panel.set_theme(dark)
        self.preference_panel.relayout()

    def _sync_report_policy(self):
        value = self.preferences.values["report_policy"]
        if value == self._report_policy_value:
            return
        self._report_policy_value = value
        for control in (self.policy, self.display_policy):
            with QSignalBlocker(control):
                control.setCurrentIndex(control.findData(value))

    def _preference_policy_selected(self, *_):
        with QSignalBlocker(self.display_policy):
            self.display_policy.setCurrentIndex(self.display_policy.findData(self.policy.currentData()))
        self._queue_preferences()

    def _display_policy_selected(self, *_):
        with QSignalBlocker(self.policy):
            self.policy.setCurrentIndex(self.policy.findData(self.display_policy.currentData()))
        self._queue_display()

    def add_page(self, text, widget, *, subtitle="", title=None, scroll=False, framed=True):
        widget.setObjectName(widget.objectName() or "settingsPage")
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, subtitle)
        item.setToolTip(f"{text} · {subtitle}")
        self.nav.addItem(item)
        panel = QWidget()
        panel.setObjectName("settingsSection")
        layout = QVBoxLayout(panel)
        if framed:
            layout.setContentsMargins(16, 12, 16, 16)
            heading = QLabel(title or text)
            heading.setObjectName("settingsSectionTitle")
            layout.addWidget(heading)
        else:
            panel.setObjectName("settingsUnframedSection")
            widget.setObjectName("settingsUnframedPage")
            layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(widget, 1)
        widget = panel
        if scroll:
            host = QScrollArea()
            host.setObjectName("settingsPageScroll")
            host.setWidgetResizable(True)
            host.setFrameShape(QScrollArea.Shape.NoFrame)
            host.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            host.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
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
        self._startup_hint()

    def _remember_selected(self, checked):
        with QSignalBlocker(self.start):
            value = -1 if checked else self.preferences.values["start_page"]
            self.start.setCurrentIndex(self.start.findData(value))
        self._queue_preferences()
        self._startup_hint()

    def _startup_hint(self):
        self.start_hint.setText("下次启动恢复最后使用的主工作区" if self.remember.isChecked()
                                else "下次启动打开所选工作区")
        self.preference_panel.relayout()

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
        self.preference_badge.setText("正在保存")
        self._preference_timer.start()

    def _queue_display(self, *_):
        self.display_status.setText("正在保存...")
        self._display_timer.start()

    def reset_preferences(self):
        if self._direction_busy:
            return
        if QMessageBox.question(self, "恢复设置默认值", "恢复本页默认设置？数据库、检测数据和报告文件不会改变。"
                                ) != QMessageBox.StandardButton.Yes:
            return
        if self._direction_writable:
            self._set_direction("1", reset=True)
        else:
            self._apply_default_preferences()

    def _apply_default_preferences(self):
        defaults = dict(theme="system", density="comfortable", animations=True, start_page=0,
                        remember_page=True, last_page=0, report_policy="manual",
                        notification_duration=3000, notification_sound=True)
        try:
            self.preferences.save(**defaults)
        except OSError as exc:
            self.save_status.setText(f"恢复本机偏好失败：{exc}")
            self.preference_badge.setText("保存失败")
            return
        self._preference_timer.stop()
        for control, key in ((self.theme, "theme"), (self.density, "density"), (self.animations, "animations"),
                             (self.notification_duration, "notification_duration"), (self.policy, "report_policy"),
                             (self.display_policy, "report_policy")):
            with QSignalBlocker(control):
                control.setCurrentIndex(control.findData(defaults[key]))
        for control, key in ((self.remember, "remember_page"), (self.notification_sound, "notification_sound")):
            with QSignalBlocker(control):
                control.setChecked(defaults[key])
        with QSignalBlocker(self.start):
            self.start.setCurrentIndex(self.start.findData(-1))
        self._theme_selected()
        self._startup_hint()
        self.preferencesChanged.emit()
        self._preference_saved("已恢复本页默认设置")

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
                                  animations=self.animations.currentData(),
                                  start_page=(self.start.currentData() if self.start.currentData() != -1
                                              else self.preferences.values["start_page"]),
                                  remember_page=self.remember.isChecked(), auto_ndd=self.auto_ndd.isChecked(),
                                  notification_duration=self.notification_duration.currentData(),
                                  notification_sound=self.notification_sound.isChecked(),
                                  report_policy=self.policy.currentData())
            self.preferencesChanged.emit()
            self._preference_saved("已保存到本机")
        except OSError as exc:
            self.preference_badge.setText("保存失败")
            self.save_status.setText(str(exc))
            QMessageBox.warning(self, "保存失败", str(exc))

    def _preference_saved(self, message):
        self.save_status.setText(message)
        self.preference_badge.setText("已保存")
        self._saved_timer.start()

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

    def _direction_loaded(self, data, error, serial=None, *, changed=False, reset=False):
        if serial is not None and serial != self._direction_serial:
            return
        self._direction_busy = False
        if not data and not error:
            error = "服务未返回有效的方向设置"
        if data:
            self._direction_value = data.get("shift_direction", self._direction_value)
            self._direction_writable = bool(data.get("writable"))
        self.direction.setEnabled(self._direction_writable)
        self.reset_button.setEnabled(True)
        if self._direction_value is not None:
            with QSignalBlocker(self.direction):
                self.direction.setCurrentIndex(max(0, self.direction.findData(self._direction_value)))
        if error:
            self.save_status.setText(f"移位默认方向未保存：{error}" if changed else f"移位默认方向读取失败：{error}")
            self.preference_badge.setText("保存失败" if changed else "读取失败")
        elif reset:
            self._apply_default_preferences()
        elif changed:
            self._preference_saved("移位方向默认值已更新")

    def save_direction(self):
        if not self._direction_busy and self._direction_writable:
            self._set_direction(self.direction.currentData())

    def _set_direction(self, value, *, reset=False):
        self._direction_busy = True
        self._direction_serial += 1
        serial = self._direction_serial
        self.direction.setEnabled(False)
        self.reset_button.setEnabled(False)
        self.client.post("/api/settings/state-direction", {"shift_direction": value},
                         lambda data, error: self._direction_loaded(data, error, serial, changed=True, reset=reset))

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
