"""Native settings categories, sharing the live account and maintenance pages."""
from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QFileDialog,
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QSpinBox,
    QStackedWidget, QVBoxLayout, QWidget, QLineEdit, QScrollArea,
    QListWidgetItem, QTabWidget, QLayout, QGridLayout,
)

from .native_components import button
from .native_settings_layout import (
    SettingsNavigation, SettingsNavigationDelegate, SettingsPreferencePanel,
    SettingsQuickActions, SettingsToggle, SettingsPreferenceRow, settings_styles,
)
from .native_settings_business import (
    ColorSwatch, RulesSettingsPanel, SettingsBusinessPanel, SourceResults, business_styles, label,
)


class SettingsDialog(QDialog):
    preferencesChanged = Signal()
    sourceImportRequested = Signal(str)

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
        display_layout.setContentsMargins(0, 0, 0, 0)
        display_layout.setSpacing(16)
        source_group = self.source_panel = SettingsBusinessPanel("检测文件来源", badge=label("导入目录"))
        form = source_group.content
        form.setContentsMargins(20, 4, 20, 20)
        display_layout.addWidget(source_group)
        self._source_baseline = None
        self._source_saving, self._source_scanning, self._source_revision = False, False, 0
        self._scan_serial = 0
        self.source_path = QLineEdit()
        self.source_path.setObjectName("settingsSourcePath")
        self.source_path.setPlaceholderText("选择检测数据所在文件夹，可使用共享目录")
        self.source_path.setAccessibleName("本地或共享文件夹")
        self.source_path.setFixedHeight(38)
        self.source_browse = button("浏览…", None, self.choose_source)
        self.source_browse.setObjectName("settingsSourceBrowse")
        self.source_browse.setFixedSize(62, 38)
        source_caption = label("本地或共享文件夹")
        source_caption.setFixedHeight(19)
        form.addWidget(source_caption)
        form.addSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.source_path, 1)
        row.addWidget(self.source_browse)
        form.addLayout(row)
        form.addSpacing(19)
        actions = QHBoxLayout()
        actions.setSpacing(9)
        self.source_save_status = label("正在读取文件来源…", "settingsBusinessHint")
        self.source_save_status.setFixedHeight(18)
        actions.addWidget(self.source_save_status, 1, Qt.AlignmentFlag.AlignVCenter)
        self.save_source = QPushButton("保存来源")
        self.save_source.setObjectName("settingsSourceSave")
        self.save_source.clicked.connect(self.persist_source)
        self.save_source.setFixedSize(75, 36)
        actions.addWidget(self.save_source)
        self.scan_source = button("扫描指套管目录", None, self.scan_sources)
        self.scan_source.setObjectName("settingsSourceScan")
        self.scan_source.setProperty("primary", True)
        self.scan_source.setFixedSize(118, 36)
        actions.addWidget(self.scan_source)
        form.addLayout(actions)
        form.addSpacing(10)
        self.scan_status = label("尚未扫描", "settingsBusinessHint")
        self.scan_status.setMinimumHeight(18)
        form.addWidget(self.scan_status)
        form.addSpacing(10)
        self.source_empty = label("选择文件夹后扫描可用大修目录", "settingsSourceEmpty")
        self.source_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.source_empty.setMinimumHeight(55)
        form.addWidget(self.source_empty)
        self.source_results = SourceResults(self._open_source)
        self.source_results.hide()
        form.addWidget(self.source_results)
        parsing_group = self.parsing_panel = SettingsBusinessPanel("文件解析", badge=label("自动保存"))
        parsing_group.resized.connect(self._layout_sidebar)
        self.display_policy = QComboBox()
        for index in range(self.policy.count()):
            self.display_policy.addItem(self.policy.itemText(index), self.policy.itemData(index))
        self.display_policy.setCurrentIndex(self.policy.currentIndex())
        self.parsing_row = SettingsPreferenceRow("RPT 选择策略",
                                                "手动逐组选择，或预选修改时间最新版本后逐组确认",
                                                self.display_policy, parsing_group.body)
        self.parsing_row.setObjectName("settingsParsingRow")
        parsing_group.content.addWidget(self.parsing_row)
        self.policy_note = label("", "settingsPolicyNote")
        self.policy_note.setMinimumHeight(40)
        parsing_group.content.addSpacing(12)
        parsing_group.content.addWidget(self.policy_note)
        self._report_policy_note()
        display_layout.addWidget(parsing_group)
        depth_group = self.severity_panel = SettingsBusinessPanel(
            "二维管板严重度", "按同一管的最大磨损比例显示单一颜色，不改变原始数据")
        form = depth_group.content
        display_layout.addWidget(depth_group)
        self.color_values = list(preferences.values["depth_colors"])
        self.none_color = preferences.values["ndd_color"]
        self.swatches, self.severity_labels = [], []
        form.addSpacing(8)
        legend = label("颜色分级", "settingsSeverityLegend")
        legend.setMinimumHeight(27)
        form.addWidget(legend)
        form.addSpacing(2)
        self.none_swatch = ColorSwatch(self.none_color)
        self.none_swatch.setAccessibleName("NDD 颜色")
        self.none_swatch.setToolTip("NDD 颜色")
        self.none_swatch.clicked.connect(lambda: self.choose_color(-1))
        color_rows = [("NDD", self.none_swatch)]
        for i, value in enumerate(self.color_values):
            swatch = ColorSwatch(value)
            swatch.setAccessibleName(f"第 {i + 1} 档磨损颜色")
            swatch.setToolTip(f"第 {i + 1} 档磨损颜色")
            swatch.clicked.connect(lambda _, index=i: self.choose_color(index))
            self.swatches.append(swatch)
            color_rows.append(("", swatch))
        for title, control in color_rows:
            text = label(title)
            self.severity_labels.append(text)
            self._severity_row(form, text, control)
        form.addSpacing(8)
        legend = label("关注与极限阈值", "settingsSeverityLegend")
        legend.setMinimumHeight(27)
        form.addWidget(legend)
        form.addSpacing(2)
        self.levels = []
        for i, value in enumerate(preferences.values["depth_levels"]):
            level = QSpinBox()
            level.setRange(0, 100)
            level.setFixedSize(120, 34)
            level.setValue(value)
            self.levels.append(level)
            title = ("关注起始比例 (%)", "极限起始比例 (%)")[i] if len(
                preferences.values["depth_levels"]) == 2 else f"磨损深度分界 {i + 1} (%)"
            level.setAccessibleName(title)
            self._severity_row(form, label(title), level)
        self.point_labels = QCheckBox()
        self.point_labels.setChecked(preferences.values["point_labels"])
        self.ndd_zero = QCheckBox()
        self.ndd_zero.setChecked(preferences.values["ndd_zero"])
        self.auto_ndd.setText("")
        for title, control, hint in (
            ("图表数值标注", self.point_labels, "在趋势与分布图数据点旁显示数值"),
            ("自动识别 NDD", self.auto_ndd,
             "开启：空白结论且无磨损信息时按 NDD 统计（会在检测结论徽章标注“自动”）；关闭：仅原始 NDD 类代码才算 NDD，空白保持“无结论”"),
            ("NDD 记 0 深度", self.ndd_zero,
             "开启：前次结论为明确 NDD 时按 0 深度起算匹配增量，趋势图与明细会标注“NDD 0 基线”（判定值，非实测）；关闭：NDD 不参与零基线，相关增量保持留空"),
        ):
            control.setAccessibleName(title)
            control.setToolTip(hint)
            row = QWidget()
            row.setObjectName("settingsSeverityRow")
            grid = QGridLayout(row)
            grid.setContentsMargins(0, 10, 0, 10)
            grid.setHorizontalSpacing(12)
            grid.setVerticalSpacing(12)
            control.setFixedSize(25, 25)
            grid.addWidget(label(title), 0, 0)
            grid.addWidget(control, 0, 1)
            hint_label = label(hint, "settingsBusinessHint")
            hint_label.setMinimumHeight(18)
            grid.addWidget(hint_label, 1, 0, 1, 2)
            grid.setColumnStretch(0, 1)
            row.setMinimumHeight(77)
            form.addWidget(row)
        form.addSpacing(12)
        self.severity_note = label("", "settingsRulesNote")
        form.addWidget(self.severity_note)
        self.display_status = label("导入与显示设置已保存", "settingsBusinessHint")
        form.addWidget(self.display_status)
        display_layout.addStretch()
        self.source_path.textChanged.connect(self._source_edited)
        self.policy.currentIndexChanged.connect(self._preference_policy_selected)
        self.display_policy.currentIndexChanged.connect(self._display_policy_selected)
        self.point_labels.toggled.connect(self._queue_display)
        self.ndd_zero.toggled.connect(self._queue_display)
        for control in self.levels:
            control.valueChanged.connect(self._queue_display)
        self._severity_labels()
        self.add_page("导入与显示", display, subtitle="来源与可视化", scroll=True, framed=False)
        rules = self.rules_panel = RulesSettingsPanel(client, self.permissions)
        self.rules_text, self.create_rule = rules.active, rules.create
        rules_page = QWidget()
        rules_layout = QVBoxLayout(rules_page)
        rules_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        rules_layout.setContentsMargins(0, 0, 0, 0)
        rules_layout.addWidget(rules)
        rules_layout.addStretch()
        self.add_page("对比规则", rules_page, subtitle="历次结果匹配", scroll=True, framed=False)
        self._source_actions()
        client.get("/api/settings/data-source", self._source_profile_loaded)
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
        if hasattr(self, "parsing_row"):
            width = max(1, self.parsing_panel.width() - 42)
            height = self.parsing_row.layout_for_width(width, narrow,
                                                      9 if self.width() <= 1000 else 14, True)
            for child in (self.parsing_row.title, self.parsing_row.hint, self.display_policy):
                child.move(child.x() - 12, child.y())
            self.parsing_row.setFixedHeight(round(height))
        if hasattr(self, "rules_panel"):
            self.rules_panel.relayout()

    def set_theme(self, theme):
        dark = theme == "dark"
        self.setStyleSheet(settings_styles(theme) + business_styles(dark))
        self.rules_panel.setProperty("dark", dark)
        for control in self.rules_panel.group.buttons():
            control.setProperty("dark", dark)
            control.update()
        self.nav.setProperty("dark", dark)
        self.nav.viewport().update()
        for control in self.quick_actions.values():
            control.set_theme(dark)
        self.preference_panel.set_theme(dark)
        for row in (self.parsing_row, *self.rules_panel.rows):
            row.dark = dark
            row.update()
        self.preference_panel.relayout()

    def _sync_report_policy(self):
        value = self.preferences.values["report_policy"]
        if value == self._report_policy_value:
            return
        self._report_policy_value = value
        for control in (self.policy, self.display_policy):
            with QSignalBlocker(control):
                control.setCurrentIndex(control.findData(value))
        self._report_policy_note()

    def _preference_policy_selected(self, *_):
        with QSignalBlocker(self.display_policy):
            self.display_policy.setCurrentIndex(self.display_policy.findData(self.policy.currentData()))
        self._queue_preferences()
        self._report_policy_note()

    def _display_policy_selected(self, *_):
        with QSignalBlocker(self.policy):
            self.policy.setCurrentIndex(self.policy.findData(self.display_policy.currentData()))
        self._queue_display()
        self._report_policy_note()

    def _report_policy_note(self):
        if hasattr(self, "policy_note"):
            self.policy_note.setText("扫描后按修改时间预选最新 RPT，仍需逐组确认。"
                                     if self.display_policy.currentData() == "latest" else
                                     "扫描后由你为每个数据组手动选择一份 RPT，并逐组确认。")

    @staticmethod
    def _severity_row(layout, title, control):
        row = QWidget()
        row.setObjectName("settingsSeverityRow")
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 10, 0, 10)
        line.setSpacing(12)
        line.addWidget(title, 1)
        line.addWidget(control)
        row.setMinimumHeight(59 if isinstance(control, QSpinBox) else 56)
        layout.addWidget(row)

    def _severity_labels(self):
        levels = [control.value() for control in self.levels]
        for index, control in enumerate(self.severity_labels[1:]):
            lower = 0 if index == 0 else levels[index - 1]
            grade = ("一", "二", "三", "四")[index] + "级"
            text = f"{grade} · {lower} 至 {levels[index]}%" if index < len(levels) else f"{grade} · {lower}% 以上"
            if len(levels) == 2:
                text = text.replace("1级", "一级").replace("2级", "二级").replace("3级", "三级")
            control.setText(text)
        self.severity_note.setText(
            f"当前关注阈值 {levels[0]}% / 极限阈值 {levels[-1]}%；管板颜色、严重度统计和分析参考线会立即更新。"
            "它们仅用于显示和分析，不是维修或验收判据。图表悬浮提示保留通道、位置、轮次、深度和状态。")

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
        if self._source_scanning:
            return
        path = QFileDialog.getExistingDirectory(self, "选择默认导入目录", self.source_path.text())
        if path:
            self.source_path.setText(path)
            self.scan_status.setText("已选择来源文件夹，可保存配置或扫描目录")

    def _source_edited(self, *_):
        self._source_revision += 1
        if not self._source_saving and self._source_baseline is not None:
            self.source_save_status.setText("来源路径尚未保存" if self._source_dirty() else "文件来源已保存。")
        self._source_actions()

    def _source_dirty(self):
        return self._source_baseline is not None and self.source_path.text().strip() != self._source_baseline.get("source_directory", "")

    def _source_actions(self):
        self.save_source.setEnabled("settings.manage" in self.permissions and
                                    not self._source_saving and self._source_dirty())
        self.scan_source.setEnabled("data.import" in self.permissions and not self._source_scanning)
        self.source_browse.setEnabled(not self._source_scanning)

    def _source_profile_loaded(self, data, error):
        if error or not data or not isinstance(data.get("profile"), dict):
            self.source_save_status.setText("配置未读取，仍可临时选择文件夹扫描。")
        else:
            self._source_baseline = dict(data["profile"])
            if self._source_revision == 0:
                with QSignalBlocker(self.source_path):
                    self.source_path.setText(str(self._source_baseline.get("source_directory") or ""))
            self.source_save_status.setText("来源路径尚未保存" if self._source_dirty() else
                                            ("已保存文件来源。" if self.source_path.text() else "文件来源与数据库存储相互独立"))
            if data.get("warnings"):
                self.source_save_status.setText(" ".join(data["warnings"]))
        self._source_actions()

    def persist_source(self):
        if self._source_saving or not self._source_dirty() or "settings.manage" not in self.permissions:
            return
        self._source_saving = True
        revision, path = self._source_revision, self.source_path.text().strip()
        self.source_save_status.setText("正在保存到本地配置…")
        self.save_source.setText("保存中…")
        self._source_actions()

        def refreshed(data, error):
            if error or not data or not isinstance(data.get("profile"), dict):
                saved(None, error or "服务未返回有效来源配置")
                return
            payload = {**data["profile"], "source_directory": path}
            self.client.post("/api/settings/data-source", {"profile": payload}, saved)

        def saved(data, error):
            self._source_saving = False
            self.save_source.setText("保存来源")
            if error or not data or not isinstance(data.get("profile"), dict):
                self.source_save_status.setText(f"保存失败：{error or '服务未返回有效来源配置'}")
            else:
                self._source_baseline = dict(data["profile"])
                if revision == self._source_revision:
                    with QSignalBlocker(self.source_path):
                        self.source_path.setText(str(self._source_baseline.get("source_directory") or ""))
                self.source_save_status.setText("来源路径尚未保存" if self._source_dirty() else "文件来源已保存。")
                try:
                    self.preferences.save(source_path=str(self._source_baseline.get("source_directory") or ""))
                except OSError as exc:
                    self.source_save_status.setText(f"来源已保存，本机目录偏好未更新：{exc}")
            self._source_actions()
        self.client.get("/api/settings/data-source", refreshed)

    def _open_source(self, item):
        path = str(item.get("path") or "")
        if path and "data.import" in self.permissions:
            self.sourceImportRequested.emit(path)
        elif path:
            self.scan_status.setText("当前账户没有导入权限")

    def choose_color(self, index):
        from PySide6.QtGui import QColor
        color = QColorDialog.getColor(QColor(self.none_color if index == -1 else self.color_values[index]), self)
        if color.isValid():
            if index == -1:
                self.none_color = color.name()
                self.none_swatch.color = color.name()
                self.none_swatch.update()
            else:
                self.color_values[index] = color.name()
                self.swatches[index].color = color.name()
                self.swatches[index].update()
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
        if self._source_scanning or "data.import" not in self.permissions:
            return
        path = self.source_path.text().strip()
        if not path:
            self.scan_status.setText("请选择来源目录")
            return
        self._source_scanning = True
        self._scan_serial += 1
        serial = self._scan_serial
        self._source_actions()
        self.scan_source.setText("正在扫描...")
        self.scan_status.setText("正在识别检测来源目录...")
        self.source_results.hide()
        self.source_empty.setText("正在扫描本地或共享文件夹...")
        self.source_empty.show()
        self.client.post("/api/discover-server", {"path": path},
                         lambda data, error: self._sources_loaded(data, error, serial))

    def _sources_loaded(self, data, error, serial=None):
        if serial is not None and serial != self._scan_serial:
            return
        self._source_scanning = False
        self.scan_source.setText("扫描指套管目录")
        self._source_actions()
        items = (data or {}).get("items") or []
        self.source_results.set_items(items if not error else [])
        self.source_results.setVisible(bool(items) and not error)
        self.source_empty.setVisible(not items or bool(error))
        self.source_empty.setText(error or "未发现包含 TH 数据组的指套管目录")
        self.scan_status.setText("扫描失败，可修改路径后重试" if error else
                                 f"已扫描 {(data or {}).get('scanned_directories', 0)} 个目录，发现 {len(items)} 个指套管大修"
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
        if levels != sorted(levels):
            self.display_status.setText("关注阈值不能大于极限阈值，尚未保存")
            return
        try:
            self.preferences.save(report_policy=self.policy.currentData(),
                                  depth_levels=levels, depth_colors=self.color_values,
                                  ndd_color=self.none_color,
                                  point_labels=self.point_labels.isChecked(), ndd_zero=self.ndd_zero.isChecked())
            self._severity_labels()
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
        self.rules_panel._loaded(self.rules_panel.serial, data, error)

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
