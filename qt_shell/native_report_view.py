"""Native, merged-cell source-form preview with inline draft edits."""
from __future__ import annotations

from html.parser import HTMLParser
from collections import OrderedDict
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QTextDocument
from PySide6.QtWidgets import (QScrollArea, QStyledItemDelegate, QStyle, QStyleOptionViewItem,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)


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
        self.zoom = 1.
        self.editable_keys = set()
        self.setPlainText("选择范围后生成报告预览")

    def _clear(self):
        while self.pages.count():
            item = self.pages.takeAt(0)
            item.widget().hide()
            item.widget().deleteLater()
        self.tables.clear()

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
            width = max(table.width() for table in self.tables) + margins.left() + margins.right()
            height = (sum(table.height() for table in self.tables) + margins.top() + margins.bottom()
                      + self.pages.spacing() * max(0, len(self.tables) - 1))
            self.host.setFixedSize(width, height)
        else:
            self.host.setFixedSize(self.pages.sizeHint())

    def setHtml(self, html):
        self._clear()
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
                               "gridline-color:#58656e;} QTableWidget::item{padding:3px;color:#18232b;}")
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
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if not cell["key"] or cell["key"] not in self.editable_keys:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(ri, ci, item)
            table.itemChanged.connect(self._edited)
            self.tables.append(table)
            self.pages.addWidget(table)
            table.show()
        self.set_zoom(self.zoom)

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
        width = int(850 * self.zoom)
        for table in self.tables:
            table.setProperty("reportZoom", self.zoom)
            font = QFont("SimSun", max(7, round(10 * self.zoom)))
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
        self._resize_host()

    def fit_width(self):
        self.set_zoom((self.viewport().width() - 54) / 850)
