"""Native, merged-cell source-form preview with inline draft edits."""
from __future__ import annotations

from html.parser import HTMLParser
from collections import OrderedDict
import re

from PySide6.QtCore import QEvent, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QTextDocument
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit, QScrollArea,
                               QStyledItemDelegate, QStyle, QStyleOptionViewItem, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .native_components import button


class ReportWarnings(QWidget):
    """Tube-grouped review evidence, with details built only when opened."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("reportWarnings")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.toggle = button("", "chevron-right")
        self.toggle.setObjectName("reportWarningToggle")
        self.toggle.setCheckable(True)
        self.toggle.toggled.connect(self._toggle)
        layout.addWidget(self.toggle)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setMinimumHeight(120)
        self.scroll.setMaximumHeight(260)
        self.scroll.setObjectName("reportWarningScroll")
        self.contents = QWidget()
        self.contents.setObjectName("reportWarningContents")
        self.contents.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.grid = QGridLayout(self.contents)
        self.grid.setContentsMargins(10, 0, 10, 10)
        self.grid.setSpacing(7)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.contents)
        layout.addWidget(self.scroll)
        self.groups = {}
        self._scope = None
        self._columns = 0
        self.scroll.hide()
        self.hide()

    def _toggle(self, opened):
        self.scroll.setVisible(opened)
        self.toggle.setProperty("iconName", "chevron-down" if opened else "chevron-right")
        from .native_components import icon
        theme = "dark" if self.palette().windowText().color().lightness() > 160 else "light"
        self.toggle.setIcon(icon(self.toggle.property("iconName"), theme))

    @staticmethod
    def _value(value):
        return "/" if value is None or not str(value).strip() else str(value)

    @staticmethod
    def _label(text, name=""):
        label = QLabel(str(text))
        label.setObjectName(name)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        return label

    def set_warnings(self, warnings, *, scope=None):
        same_scope = scope == self._scope
        expanded = {tube for tube, group in self.groups.items() if group["toggle"].isChecked()} if same_scope else set()
        vertical = self.scroll.verticalScrollBar().value() if same_scope else 0
        self._scope = scope
        if not same_scope:
            self.toggle.setChecked(False)
        while self.grid.count():
            item = self.grid.takeAt(0)
            item.widget().hide()
            item.widget().deleteLater()
        self.groups.clear()
        grouped = {}
        valid = [item for item in warnings if isinstance(item, dict)]
        for warning in valid:
            tube = warning.get("thimble_id")
            key = "范围" if tube is None else f"{tube}号管"
            rows = grouped.setdefault(key, [])
            if not any(all(row.get(field) == warning.get(field) for field in ("reason", "code", "old_id"))
                       for row in rows):
                rows.append(warning)
        for tube in sorted(grouped, key=lambda key: (-1, "") if key == "范围" else
                           (int(re.match(r"\d+", key)[0]), key) if re.match(r"\d+", key) else (10**9, key)):
            rows = grouped[tube]
            group = QWidget()
            group.setObjectName("reportWarningGroup")
            group.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            box = QVBoxLayout(group)
            box.setContentsMargins(10, 8, 10, 8)
            box.setSpacing(6)
            code = {"unmatched_history": "历史未匹配", "missing_tube": "缺少检测记录",
                    "incomplete_tube_result": "结论不完整"}.get(rows[0].get("code"), "待核查")
            control = button(f"{tube}   {code}   {len(rows)} 条", "chevron-right")
            control.setObjectName("reportWarningGroupToggle")
            control.setCheckable(True)
            control.setAccessibleName(f"{tube} {code} {len(rows)}条")
            box.addWidget(control)
            reason = rows[0].get("reason") or "请核对原始资料和导入记录"
            headline = self._label(reason.split("；")[0], "reportWarningHeadline")
            box.addWidget(headline)
            body = QWidget()
            body.setObjectName("reportWarningBody")
            body.setLayout(QVBoxLayout())
            body.layout().setContentsMargins(0, 6, 0, 0)
            body.layout().setSpacing(8)
            box.addWidget(body)
            body.hide()
            entry = {"widget": group, "toggle": control, "body": body, "warnings": rows, "built": False}
            self.groups[tube] = entry
            control.toggled.connect(lambda opened, entry=entry: self._group_toggled(entry, opened))
            control.setChecked(tube in expanded)
        self.toggle.setText(f"需人工核查   {len(grouped)} 个管号   {len(valid)} 条提示")
        self._columns = 0
        self._reflow()
        self.setVisible(bool(valid))
        self.scroll.setVisible(bool(valid) and self.toggle.isChecked())
        self.scroll.verticalScrollBar().setValue(vertical)

    def _group_toggled(self, entry, opened):
        if opened and not entry["built"]:
            for warning in entry["warnings"]:
                self._add_detail(entry["body"].layout(), warning)
            entry["built"] = True
        entry["body"].setVisible(opened)
        from .native_components import icon
        name = "chevron-down" if opened else "chevron-right"
        entry["toggle"].setProperty("iconName", name)
        theme = "dark" if self.palette().windowText().color().lightness() > 160 else "light"
        entry["toggle"].setIcon(icon(name, theme))

    def _add_detail(self, layout, warning):
        reason = warning.get("reason") or "请核对原始资料和导入记录"
        history = warning.get("historical")
        if warning.get("code") != "unmatched_history" or not isinstance(history, dict):
            context = ""
            if warning.get("current_location"):
                context = f"本次位置 {warning['current_location']}"
                locations = [str(value) for value in warning.get("historical_locations", []) if value]
                if locations:
                    context += "；历史同 P 位 " + "、".join(locations)
                if warning.get("shift_mm"):
                    shift = warning["shift_mm"]
                    context += f"；移位 {'+' if float(shift) > 0 else ''}{shift} mm"
            layout.addWidget(self._label((context + "。" if context else "") + reason, "reportWarningReason"))
            return
        layout.addWidget(self._label("未匹配原因  " + reason, "reportWarningReason"))
        compare = QWidget()
        columns = QHBoxLayout(compare)
        columns.setContentsMargins(0, 0, 0, 0)
        old = (f"历史记录\n{self._value(history.get('outage'))} · {self._value(history.get('location'))}\n"
               f"幅值 {self._value(history.get('volts'))} · 深度 "
               f"{self._value(history.get('percent'))}{'%' if history.get('percent') not in (None, '') else ''}"
               f" · 数据点 {self._value(history.get('datapoint'))}")
        current = warning.get("current") or {}
        state = current.get("state")
        state_text = ("本次该管无检测记录" if state == "missing" else
                      "本次该管全部为 NDD / 无显示" if state == "NDD" else
                      f"本次该管有 {current['defects']} 条缺陷显示；这条历史记录没有匹配" if current.get("defects") else
                      "本次该管没有缺陷显示")
        now = "本次情况\n" + state_text
        nearest = current.get("nearest")
        if nearest:
            now += (f"\n最近显示 {self._value(nearest.get('location'))} · 相距 "
                    f"{self._value(nearest.get('distance_mm'))} mm · 当前容差 "
                    f"±{self._value(warning.get('tolerance_mm'))} mm")
        columns.addWidget(self._label(old, "reportWarningEvidence"), 1)
        columns.addWidget(self._label(now, "reportWarningEvidence"), 1)
        layout.addWidget(compare)
        layout.addWidget(self._label("不得自动判定为消失或 NDD，须人工核对原始报告。", "reportWarningRequirement"))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self):
        columns = 2 if self.width() >= 760 else 1
        if columns == self._columns:
            return
        self._columns = columns
        while self.grid.count():
            self.grid.takeAt(0)
        self.grid.setColumnStretch(1, 1 if columns == 2 else 0)
        self.grid.setColumnStretch(0, 1)
        for index, entry in enumerate(self.groups.values()):
            self.grid.addWidget(entry["widget"], index // columns, index % columns,
                                Qt.AlignmentFlag.AlignTop)


class FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables, self.rows, self.row, self.cell = [], None, None, None
        self.specs, self.spec = [], None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table":
            self.rows = []
            self.spec = {"widths": [], "heights": []}
        elif tag == "col" and self.spec is not None:
            match = re.search(r"width:\s*([\d.]+)%", attrs.get("style", ""))
            self.spec["widths"].append(float(match[1]) if match else 1)
        elif tag == "tr" and self.rows is not None:
            self.row = []
            match = re.search(r"height:\s*([\d.]+)pt", attrs.get("style", ""))
            self.spec["heights"].append(float(match[1]) * 96 / 72 if match else 26)
        elif tag in ("td", "th") and self.row is not None:
            self.cell = {"text": "", "rows": int(attrs.get("rowspan", 1)),
                         "cols": int(attrs.get("colspan", 1)), "key": attrs.get("data-edit-key", ""),
                         "html": ""}
        elif tag == "br" and self.cell is not None:
            self.cell["text"] += "\n"
        elif tag == "p" and self.cell and self.cell["text"]:
            self.cell["text"] += "\n"
        if self.cell is not None and tag not in ("td", "th"):
            from html import escape
            self.cell["html"] += "<" + tag + "".join(f' {key}="{escape(value or "", quote=True)}"'
                                                       for key, value in attrs.items()) + ">"

    def handle_data(self, data):
        if self.cell is not None:
            self.cell["text"] += data
            from html import escape
            self.cell["html"] += escape(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(self.cell)
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        elif tag == "table" and self.rows is not None:
            self.tables.append(self.rows)
            self.specs.append(self.spec)
            self.rows = None
            self.spec = None
        elif self.cell is not None:
            self.cell["html"] += "</" + tag + ">"


class FormCellDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._documents = OrderedDict()

    def createEditor(self, parent, option, index):
        editor = QPlainTextEdit(parent)
        editor.setAccessibleName("报告单元格")
        editor.setTabChangesFocus(True)
        return editor

    def setEditorData(self, editor, index):
        editor.setPlainText(index.data(Qt.ItemDataRole.EditRole) or "")
        editor.selectAll()

    def setModelData(self, editor, model, index):
        model.setData(index, editor.toPlainText(), Qt.ItemDataRole.EditRole)

    def eventFilter(self, editor, event):
        if isinstance(editor, QPlainTextEdit) and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.commitData.emit(editor)
                self.closeEditor.emit(editor)
                return True
        return super().eventFilter(editor, event)

    def paint(self, painter, option, index):
        html = index.data(Qt.ItemDataRole.UserRole + 1)
        if not html:
            return super().paint(painter, option, index)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else __import__(
            "PySide6.QtWidgets", fromlist=["QApplication"]).QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        zoom = self.parent().property("reportZoom") or 1
        key = (html, option.rect.width(), zoom)
        document = self._documents.get(key)
        if document is None:
            document = QTextDocument()
            document.setDocumentMargin(3)
            document.setHtml(html)
            document.setTextWidth(max(1, option.rect.width() / zoom))
            self._documents[key] = document
            if len(self._documents) > 256:
                self._documents.popitem(last=False)
        else:
            self._documents.move_to_end(key)
        painter.save()
        painter.setClipRect(option.rect)
        painter.translate(option.rect.left(), option.rect.top() + max(0, (option.rect.height() - document.size().height() * zoom) / 2))
        painter.scale(zoom, zoom)
        document.drawContents(painter)
        painter.restore()


class ReportPreview(QScrollArea):
    cellEdited = Signal(str, str)
    zoomChanged = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.viewport().setStyleSheet("background:#dce3e7")
        self.host = QWidget()
        self.host.setStyleSheet("background:#dce3e7; QLabel{color:#30434f;background:transparent}")
        self.pages = QVBoxLayout(self.host)
        self.pages.setContentsMargins(24, 24, 24, 24)
        self.pages.setSpacing(22)
        self.setWidget(self.host)
        self.tables = []
        self.paper_widgets = []
        self.zoom = 1.
        self.editable_keys = set()
        self._source_cells = {}
        self._items = {}
        self.setPlainText("选择范围后生成报告预览")

    def _clear(self):
        while self.pages.count():
            item = self.pages.takeAt(0)
            item.widget().hide()
            item.widget().deleteLater()
        self.tables.clear()
        self.paper_widgets.clear()
        self._items.clear()

    def setPlainText(self, text):
        from PySide6.QtWidgets import QLabel
        self._clear()
        label = QLabel(text)
        label.setContentsMargins(24, 24, 24, 24)
        self.pages.addWidget(label)
        self._resize_host()

    def _resize_host(self):
        self.pages.invalidate()
        self.pages.activate()
        if self.tables:
            margins = self.pages.contentsMargins()
            width = max(paper.width() for paper in self.paper_widgets) + margins.left() + margins.right()
            height = (sum(paper.height() for paper in self.paper_widgets) + margins.top() + margins.bottom()
                      + self.pages.spacing() * max(0, len(self.tables) - 1))
            self.host.setFixedSize(width, height)
        else:
            self.host.setFixedSize(self.pages.sizeHint())

    def setHtml(self, html, *, source_values=None, changed_keys=()):
        horizontal = self.horizontalScrollBar().value()
        vertical = self.verticalScrollBar().value()
        selected = next((table.currentItem().data(Qt.ItemDataRole.UserRole) for table in self.tables
                         if table.currentItem() is not None), None)
        self._clear()
        source_values = source_values or {}
        changed_keys = set(changed_keys)
        parser = FormParser()
        parser.feed(html)
        if not parser.tables:
            self.setPlainText("报告没有可显示的表格")
            return
        for page_number, rows in enumerate(parser.tables):
            occupied = set()
            positioned = []
            columns = 0
            for ri, row in enumerate(rows):
                ci = 0
                for cell in row:
                    while (ri, ci) in occupied:
                        ci += 1
                    positioned.append((ri, ci, cell))
                    for r in range(ri, ri + cell["rows"]):
                        for c in range(ci, ci + cell["cols"]):
                            occupied.add((r, c))
                    ci += cell["cols"]
                    columns = max(columns, ci)
            table = QTableWidget(len(rows), columns)
            table.setObjectName(f"reportPage{page_number + 1}")
            table.setStyleSheet("QTableWidget{background:white;color:#18232b;border:1px solid #b7bfc4;"
                               "border-radius:0;gridline-color:#58656e;} QTableWidget::item{padding:3px;color:#18232b;}")
            table.horizontalHeader().hide()
            table.horizontalHeader().setMinimumSectionSize(1)
            table.verticalHeader().hide()
            table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            table.setFont(QFont("SimSun", 10))
            table.setItemDelegate(FormCellDelegate(table))
            table.source_spec = parser.specs[page_number]
            for ri, ci, cell in positioned:
                if cell["rows"] > 1 or cell["cols"] > 1:
                    table.setSpan(ri, ci, cell["rows"], cell["cols"])
                item = QTableWidgetItem(cell["text"].strip())
                item.setData(Qt.ItemDataRole.UserRole, cell["key"])
                item.setData(Qt.ItemDataRole.UserRole + 1, cell["html"])
                if cell["key"]:
                    key = cell["key"]
                    source = source_values.get(key, item.text())
                    previous = self._source_cells.get(key)
                    if previous is None or previous[0] != source:
                        from html import escape
                        markup = cell["html"] if key not in changed_keys else escape(
                            str(source if source is not None and source != "" else "/"))
                        text = item.text() if key not in changed_keys else str(source if source is not None else "/")
                        self._source_cells[key] = (source, text, markup)
                    self._items[key] = item
                    if key in changed_keys:
                        item.setBackground(QColor("#fff3cd"))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if not cell["key"] or cell["key"] not in self.editable_keys:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(ri, ci, item)
            table.itemChanged.connect(self._edited)
            self.tables.append(table)
            paper = QWidget()
            paper.setStyleSheet("background:white")
            paper_layout = QVBoxLayout(paper)
            paper_layout.setSpacing(0)
            paper_layout.addWidget(table)
            self.paper_widgets.append(paper)
            self.pages.addWidget(paper)
            table.show()
        self.set_zoom(self.zoom)
        if selected in self._items:
            item = self._items[selected]
            item.tableWidget().setCurrentItem(item)
        self.horizontalScrollBar().setValue(horizontal)
        self.verticalScrollBar().setValue(vertical)

    def clear_sources(self):
        self._source_cells.clear()

    def set_cell_value(self, key, value, *, changed):
        item = self._items.get(key)
        if item is None:
            return False
        with QSignalBlocker(item.tableWidget()):
            source = self._source_cells.get(key)
            if not changed and source is not None:
                item.setText(source[1])
                item.setData(Qt.ItemDataRole.UserRole + 1, source[2])
                item.setBackground(QBrush())
            else:
                item.setText("/" if value is None or value == "" else str(value))
                item.setData(Qt.ItemDataRole.UserRole + 1, None)
                item.setBackground(QColor("#fff3cd") if changed else QBrush())
        return True

    def locate_cell(self, key):
        item = self._items.get(key)
        if item is None:
            return False
        table = item.tableWidget()
        table.setCurrentItem(item)
        table.setFocus(Qt.FocusReason.OtherFocusReason)
        point = table.viewport().mapTo(self.host, table.visualItemRect(item).center())
        self.ensureVisible(point.x(), point.y(), 40, 60)
        return True

    def _edited(self, item):
        key = item.data(Qt.ItemDataRole.UserRole)
        if key:
            item.tableWidget().blockSignals(True)
            item.setData(Qt.ItemDataRole.UserRole + 1, None)
            item.setBackground(QColor("#fff3cd"))
            item.tableWidget().blockSignals(False)
            self.cellEdited.emit(key, item.text())

    def set_zoom(self, value):
        self.zoom = max(.5, min(1.5, value))
        self.zoomChanged.emit(self.zoom)
        width = int(718 * self.zoom)
        for table, paper in zip(self.tables, self.paper_widgets):
            table.setProperty("reportZoom", self.zoom)
            font = QFont("SimSun")
            font.setPointSizeF(10 * self.zoom)
            table.setFont(font)
            weights = table.source_spec["widths"]
            if len(weights) != table.columnCount() or not sum(weights):
                weights = [1] * table.columnCount()
            for column, weight in enumerate(weights):
                table.setColumnWidth(column, max(2, int((width - 2) * weight / sum(weights))))
            for row in range(table.rowCount()):
                height = max(22, table.source_spec["heights"][row])
                for column in range(table.columnCount()):
                    item = table.item(row, column)
                    if item:
                        cell_width = sum(table.columnWidth(c) for c in range(column, column + table.columnSpan(row, column))) / self.zoom
                        document = QTextDocument()
                        document.setDefaultFont(QFont("SimSun", 10))
                        html = item.data(Qt.ItemDataRole.UserRole + 1)
                        document.setHtml(html) if html else document.setPlainText(item.text())
                        document.setTextWidth(max(1, cell_width - 6))
                        height = max(height, (document.size().height() + 6) / table.rowSpan(row, column))
                table.setRowHeight(row, int(height * self.zoom))
            table.setFixedSize(width, sum(table.rowHeight(r) for r in range(table.rowCount())) + 2)
            paper.layout().setContentsMargins(round(38 * self.zoom), round(28 * self.zoom),
                                              round(38 * self.zoom), round(28 * self.zoom))
            paper.setFixedSize(round(794 * self.zoom), table.height() + round(56 * self.zoom))
        self._resize_host()

    def fit_width(self):
        self.set_zoom((self.viewport().width() - 54) / 794)
