"""Analyst-first RPT selection with explicit, resumable group confirmation."""
from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QGridLayout, QHBoxLayout, QLineEdit, QProgressBar, QRadioButton, QScrollArea,
    QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from .native_components import ToolFlowLayout, button, icon
from .native_unit_overview import plain_label


def report_groups(options):
    groups = {}
    for report in options:
        if not report.get("path") or report.get("error"):
            continue
        key = (report.get("site_code") or "", int(report.get("unit_id") or 0),
               report.get("outage") or "未识别大修", report.get("group") or "未知数据组")
        groups.setdefault(key, []).append(report)
    return list(groups.items())


def latest_report(reports):
    def natural(value):
        return tuple((0, int(part)) if part.isdigit() else (1, part.casefold())
                     for part in re.split(r"(\d+)", str(value or "")))
    return max(reports, key=lambda row: (int(row.get("modified_ns") or 0),
                                        natural(row.get("name")), str(row["path"])))

class ReportSelectionSummary(QWidget):
    groupActivated = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(7)
        self.search = QLineEdit()
        self.search.setPlaceholderText("筛选已选分析人员或报告")
        self.search.setAccessibleName("筛选已选分析人员或报告")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        box.addWidget(self.search)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("reportSelectionSummary")
        self.scroll.setAccessibleName("已选 Report 摘要")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setMinimumHeight(58)
        self.scroll.setMaximumHeight(210)
        self.host = QWidget()
        self.host.setObjectName("reportSummaryBody")
        self.rows_layout = QVBoxLayout(self.host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(0)
        self.empty = plain_label("选择文件夹后扫描并确认 Report", "muted")
        self.empty.setContentsMargins(10, 12, 10, 12)
        self.rows_layout.addWidget(self.empty)
        self.rows_layout.addStretch()
        self.scroll.setWidget(self.host)
        box.addWidget(self.scroll)
        self.rows = []
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.timeout.connect(self._reflow)
        self.scroll.viewport().installEventFilter(self)
        self.set_choice(None)

    def set_choice(self, choice):
        self._layout_timer.stop()
        for row in self.rows:
            self.rows_layout.removeWidget(row["widget"])
            row["widget"].hide()
            row["widget"].deleteLater()
        self.rows = []
        for index, (key, _reports) in enumerate(choice.groups if choice else []):
            selected = choice.selected[index] or {}
            row = QWidget()
            row.setObjectName("reportSummaryRow")
            row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            row.setMinimumHeight(48)
            row.setProperty("groupIndex", index)
            row.setAccessibleName(f"{key[2]} · {key[3]}")
            row.setAccessibleDescription(f"{key[0]}/{key[1]} · " +
                                         ("已确认" if index in choice.confirmed else "未确认"))
            grid = QGridLayout(row)
            grid.setContentsMargins(10, 8, 10, 8)
            grid.setHorizontalSpacing(8)
            grid.setVerticalSpacing(4)
            group = plain_label(f"{key[2]} · {key[3]}", "reportSummaryGroup")
            analysts = QWidget()
            analyst_layout = ToolFlowLayout(analysts)
            analyst_layout.setContentsMargins(0, 0, 0, 0)
            names = list(dict.fromkeys(str(value or "").strip() for value in selected.get("analysts") or []
                                       if str(value or "").strip()))
            listed = bool(names)
            names = names or ["未标明分析人员" if selected else "未确认"]
            for name in names:
                label = plain_label(name, "reportSummaryAnalyst")
                code = 0
                for char in name:
                    unit = int.from_bytes(char.encode("utf-16-le")[:2], "little")
                    code = (code*31 + unit) & 0xffffffff
                label.setProperty("tone", str(code % 6) if listed else "unlisted")
                analyst_layout.addWidget(label)
            text = f"{selected.get('name') or '尚未确认'} · {selected.get('records') or 0} 条结果"
            if selected.get("modified_at"):
                text += " · 修改于 " + str(selected["modified_at"]).replace("T", " ")
            source = plain_label(text, "reportSummarySource")
            source.setToolTip(str(selected.get("path") or ""))
            for control in (group, analysts, source):
                control.setMinimumWidth(0)
                control.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            for control in (row, group, source, analysts, *analysts.findChildren(QWidget)):
                control.setProperty("groupIndex", index)
                control.installEventFilter(self)
            self.rows_layout.insertWidget(index, row)
            self.rows.append({"widget": row, "group": group, "analysts": analysts, "source": source,
                              "search": " ".join((group.text(), *names, text)).casefold()})
        self.search.setVisible(bool(self.rows))
        self.empty.setVisible(not self.rows)
        self._filter()
        self._reflow()

    def _filter(self):
        term = self.search.text().strip().casefold()
        for row in self.rows:
            row["widget"].setVisible(not term or term in row["search"])
        self._layout_timer.start()

    def _reflow(self):
        width = self.scroll.viewport().width()
        narrow = width < 620
        height = 0
        for row in self.rows:
            grid = row["widget"].layout()
            for control in (row["group"], row["analysts"], row["source"]):
                grid.removeWidget(control)
            grid.addWidget(row["group"], 0, 0)
            grid.addWidget(row["analysts"], 0, 1)
            grid.addWidget(row["source"], 1 if narrow else 0, 0 if narrow else 2, 1, 2 if narrow else 1)
            for column, stretch in enumerate((8, 10, 0 if narrow else 12)):
                grid.setColumnStretch(column, stretch)
            if not row["widget"].isHidden():
                height += max(48, grid.totalHeightForWidth(width) if grid.hasHeightForWidth()
                              else grid.totalSizeHint().height())
        self.scroll.setFixedHeight(min(210, max(58, height + self.scroll.frameWidth()*2)))
        self.host.updateGeometry()

    def eventFilter(self, watched, event):
        if watched is self.scroll.viewport() and event.type() == QEvent.Type.Resize:
            self._layout_timer.start()
        elif event.type() == QEvent.Type.MouseButtonDblClick and event.button() == Qt.MouseButton.LeftButton:
            index = watched.property("groupIndex")
            if index is not None:
                self.groupActivated.emit(index)
                return True
        return super().eventFilter(watched, event)


class ReportChoiceDialog(QDialog):
    selectionChanged = Signal()

    def __init__(self, options, parent=None, *, latest=False):
        super().__init__(parent)
        self.setWindowTitle("选择分析报告")
        self.setObjectName("reportChoiceDialog")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumSize(420, 400)
        self.groups = report_groups(options)
        self.resize(700, min(640, max(400, 260 + max((len(rows) for _, rows in self.groups), default=0) * 130)))
        self.selected = [latest_report(rows) if latest else None for _, rows in self.groups]
        self.confirmed = set()
        self.index = 0
        box = QVBoxLayout(self)
        box.setContentsMargins(18, 15, 18, 15)
        box.setSpacing(10)
        head = QHBoxLayout()
        heading = QVBoxLayout()
        self.step = plain_label("", "muted")
        self.title = plain_label("", "reportChoiceTitle")
        heading.addWidget(self.step)
        heading.addWidget(self.title)
        head.addLayout(heading, 1)
        head.addWidget(button("取消", callback=self.reject), 0, Qt.AlignmentFlag.AlignTop)
        box.addLayout(head)
        self.progress = QProgressBar()
        self.progress.setObjectName("reportChoiceProgress")
        self.progress.setFixedHeight(4)
        self.progress.setStyleSheet("QProgressBar { min-height:0; max-height:4px; border:0; }")
        self.progress.setTextVisible(False)
        box.addWidget(self.progress)
        overview_head = QHBoxLayout()
        overview_head.addWidget(plain_label("选择总览"))
        overview_head.addStretch()
        overview_head.addWidget(plain_label("已确认 · 当前 · 未确认", "muted"))
        box.addLayout(overview_head)
        overview_scroll = QScrollArea()
        overview_scroll.setWidgetResizable(True)
        overview_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        overview_scroll.setFixedHeight(58)
        overview = QWidget()
        overview.setObjectName("reportChoiceOverview")
        overview_layout = ToolFlowLayout(overview)
        overview_scroll.setWidget(overview)
        self.overview_buttons = []
        for index, (key, _) in enumerate(self.groups):
            control = QToolButton()
            control.setObjectName("reportGroupChoice")
            control.setFixedSize(28, 28)
            control.setAccessibleName(f"第{index + 1}组：{key[2]} · {key[3]}")
            control.clicked.connect(lambda _, number=index: self.show_group(number))
            overview_layout.addWidget(control)
            self.overview_buttons.append(control)
        box.addWidget(overview_scroll)
        self.context = plain_label("")
        box.addWidget(self.context)
        self.options_scroll = QScrollArea()
        self.options_scroll.setWidgetResizable(True)
        self.options_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        box.addWidget(self.options_scroll, 1)
        dock = QHBoxLayout()
        self.status = plain_label("", "muted")
        dock.addWidget(self.status, 1)
        self.previous = button("上一个", "chevron-left", lambda: self.show_group(self.index - 1))
        self.previous.setAccessibleName("上一个数据组")
        dock.addWidget(self.previous)
        self.confirm = button("下一个", "chevron-right", self.confirm_current)
        self.confirm.setProperty("primary", True)
        self.confirm.setDefault(True)
        dock.addWidget(self.confirm)
        box.addLayout(dock)
        self.radios = []
        self.show_group(0)

    @property
    def complete(self):
        return bool(self.groups) and len(self.confirmed) == len(self.groups) and all(self.selected)

    def showEvent(self, event):
        super().showEvent(event)
        area = self.screen().availableGeometry()
        self.resize(min(self.width(), max(self.minimumWidth(), area.width() - 28)),
                    min(self.height(), max(self.minimumHeight(), int(area.height() * .84))))
        theme = "dark" if self.palette().windowText().color().lightness() > 160 else "light"
        self.previous.setIcon(icon("chevron-left", theme))
        self.confirm.setIcon(icon("check" if self.index == len(self.groups) - 1 else "chevron-right", theme))

    def coverage(self, key):
        return {tube for index in self.confirmed if self.groups[index][0][:3] == key[:3]
                for tube in (self.selected[index] or {}).get("tubes") or []}

    def _refresh_status(self):
        count = len(self.groups)
        self.status.setText(f"已确认 {len(self.confirmed)} / {count} 组")
        for index, control in enumerate(self.overview_buttons):
            confirmed = index in self.confirmed
            control.setText(str(index + 1))
            control.setProperty("confirmed", confirmed)
            control.setProperty("current", index == self.index)
            control.setAccessibleDescription("已确认" if confirmed else "未确认")
            key = self.groups[index][0]
            control.setToolTip(f"{index + 1}. {key[2]} · {key[3]} · " + ("已确认" if confirmed else "未确认"))
            control.style().unpolish(control)
            control.style().polish(control)
        if count:
            key, reports = self.groups[self.index]
            coverage = self.coverage(key)
            missing = sorted(set(range(1, 51)) - coverage)
            self.context.setText(f"该数据组发现 {len(reports)} 份可用 Report。"
                                 f"{key[2]} 已确认覆盖 {len(coverage)}/50 根管"
                                 + (f" · 尚缺 {len(missing)} 根" if coverage and missing else ""))
            self.context.setToolTip("尚缺管号：" + "、".join(map(str, missing)) if missing else "")

    def show_group(self, index):
        if not 0 <= index < len(self.groups):
            return
        self.index = index
        key, reports = self.groups[index]
        self.step.setText(f"Report 确认 {index + 1} / {len(self.groups)}")
        self.title.setText(f"{key[2]} · {key[3]}")
        self.progress.setRange(0, len(self.groups))
        self.progress.setValue(index + 1)
        self.previous.setEnabled(index > 0)
        self.confirm.setText("完成确认" if index == len(self.groups) - 1 else "下一个")
        theme = "dark" if self.palette().windowText().color().lightness() > 160 else "light"
        self.confirm.setIcon(icon("check" if index == len(self.groups) - 1 else "chevron-right", theme))
        old = self.options_scroll.takeWidget()
        if old:
            old.hide()
            old.deleteLater()
        self.option_host = QWidget()
        self.option_host.setObjectName("reportChoiceOptions")
        layout = QVBoxLayout(self.option_host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.radio_group = QButtonGroup(self.option_host)
        self.radios = []
        for number, report in enumerate(reports):
            option = QWidget()
            option.setObjectName("reportCandidate")
            option.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            option.setProperty("selected", self.selected[index] is report)
            row = QHBoxLayout(option)
            row.setContentsMargins(14, 13, 14, 13)
            row.setSpacing(11)
            radio = QRadioButton()
            radio.setAccessibleName("选择报告：" + str(report.get("name") or report["path"]))
            self.radio_group.addButton(radio, number)
            radio.setChecked(self.selected[index] is report)
            self.radios.append(radio)
            row.addWidget(radio, 0, Qt.AlignmentFlag.AlignTop)
            body = QVBoxLayout()
            body.setSpacing(6)
            analysts = report.get("analysts") or ["未列出"]
            analyst = plain_label("分析人员  " + " · ".join(map(str, analysts)), "reportAnalystHeading")
            body.addWidget(analyst)
            name = plain_label(report.get("name") or report["path"], "reportCandidateName")
            name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            body.addWidget(name)
            statistics = (f"{report.get('tube_count', 0)} 根管 · {report.get('records', 0)} 条结果"
                          f" · {report.get('indication_count', 0)} 条缺陷指示")
            if report.get("duplicate_paths"):
                statistics += f" · 已合并 {len(report['duplicate_paths'])} 个相同副本"
            body.addWidget(plain_label(statistics, "muted"))
            blank = report.get("blank_indication") or {}
            if blank.get("count"):
                body.addWidget(plain_label(f"三字符缺失 {blank['count']} 条，涉及 {blank.get('tubes', 0)} 根管；"
                                           "入库前必须处理", "reportChoiceWarning"))
            source = plain_label(report["path"], "reportCandidateSource")
            source.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            source.setToolTip("\n".join([report["path"]] + (report.get("duplicate_paths") or [])))
            body.addWidget(source)
            row.addLayout(body, 1)
            for label in option.findChildren(type(name)):
                label.setBuddy(radio)
                label.mousePressEvent = lambda event, control=radio: control.click()
            radio.toggled.connect(lambda checked, group=index, candidate=report:
                                  self.choose(group, candidate) if checked else None)
            layout.addWidget(option)
        self.options_scroll.setWidget(self.option_host)
        self._refresh_status()

    def choose(self, index, report):
        if self.selected[index] is not report:
            self.selected[index] = report
            self.confirmed.discard(index)
            for radio in self.radios:
                option = radio.parentWidget()
                option.setProperty("selected", radio.isChecked())
                option.style().unpolish(option)
                option.style().polish(option)
            self._refresh_status()
            self.selectionChanged.emit()

    def confirm_current(self):
        if not self.groups or not self.selected[self.index]:
            self.context.setText("请选择一份 Report 后继续")
            return
        self.confirmed.add(self.index)
        self._refresh_status()
        self.selectionChanged.emit()
        if self.index < len(self.groups) - 1:
            self.show_group(self.index + 1)
        elif not self.complete:
            missing = [index for index in range(len(self.groups)) if index not in self.confirmed]
            self.show_group(missing[0])
            self.context.setText(f"还有 {len(missing)} 个数据组未确认，已定位到第一处遗漏。")
        else:
            self.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Left:
            self.show_group(self.index - 1)
        elif event.key() == Qt.Key.Key_Right:
            self.confirm_current()
        else:
            super().keyPressEvent(event)
