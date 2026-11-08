"""Native settings categories, sharing the live account and maintenance pages."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QListWidget, QMessageBox, QPushButton, QSpinBox,
    QStackedWidget, QVBoxLayout, QWidget, QLineEdit,
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
        form = QFormLayout(flow)
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
        for label, widget in (("外观", self.theme), ("工作区密度", self.density),
                              ("交互动画", self.animations), ("启动工作区", self.start),
                              ("记住上次工作区", self.remember), ("无符号移位默认方向", self.direction)):
            form.addRow(label, widget)
        form.addRow(button("保存界面偏好", "save", self.save_preferences))
        self.direction.activated.connect(self.save_direction)
        self.add_page("界面与工作流", flow)
        client.get("/api/settings/state-direction", self._direction_loaded)
        display = QWidget()
        form = QFormLayout(display)
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
        form.addRow(button("保存导入与显示", "save", self.save_display))
        self.add_page("导入与显示", display)
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

    def add_page(self, text, widget):
        widget.setObjectName(widget.objectName() or "settingsPage")
        self.nav.addItem(text)
        self.stack.addWidget(widget)

    def choose_source(self):
        path = QFileDialog.getExistingDirectory(self, "选择默认导入目录", self.source_path.text())
        if path:
            self.source_path.setText(path)

    def choose_color(self, index):
        from PySide6.QtGui import QColor
        color = QColorDialog.getColor(QColor(self.color_values[index]), self)
        if color.isValid():
            self.color_values[index] = color.name()
            self.swatches[index].setStyleSheet(f"background:{color.name()}")

    def save_preferences(self):
        try:
            self.preferences.save(theme=self.theme.currentData(), density=self.density.currentData(),
                                  animations=self.animations.isChecked(), start_page=self.start.currentIndex(),
                                  remember_page=self.remember.isChecked())
            self.preferencesChanged.emit()
        except OSError as exc:
            QMessageBox.warning(self, "保存失败", str(exc))

    def save_display(self):
        levels = [control.value() for control in self.levels]
        if levels != sorted(set(levels)):
            QMessageBox.warning(self, "深度色阶", "分界值必须严格递增")
            return
        try:
            self.preferences.save(source_path=self.source_path.text(), report_policy=self.policy.currentData(),
                                  depth_levels=levels, depth_colors=self.color_values)
            self.preferencesChanged.emit()
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
