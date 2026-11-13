"""Exercise multiline, raw-position and concurrent edits against real SQLite rows."""
from __future__ import annotations

import json
import sqlite3
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox, QPlainTextEdit


def verify_workbench_editor(app, window, client, work, reference_path, wait, until, request):
    ref = json.loads(reference_path.read_text(encoding="utf-8-sig"))
    page = window.workbench
    window.resize(1480, 940)
    window.raise_()
    window.activateWindow()
    page.reset_query()
    until(app, lambda: not page._filter_busy and page.model.rows, "editor initial real rows")
    assert page.model.rows[0]["id"] == ref["record"]["id"]
    page.clear_selection()
    page.field_mode.setCurrentIndex(0)
    samples = []
    original_height = page.table.rowHeight(0)
    database = work / "data.db"

    def begin(field, row=0):
        page.scroll.ensureWidgetVisible(page.table)
        index = page.model.index(row, page.model.fields.index(field))
        page.table.scrollTo(index)
        wait(40)
        point = page.table.visualRect(index).center()
        QTest.mouseClick(page.table.viewport(), Qt.MouseButton.LeftButton, pos=point)
        QTest.mouseDClick(page.table.viewport(), Qt.MouseButton.LeftButton, pos=point)
        kind = QPlainTextEdit if field in {"analysis", "maintenance_text"} else QLineEdit
        until(app, lambda: any(e.isVisible() for e in page.table.findChildren(kind)), "actual finding editor")
        return next(e for e in page.table.findChildren(kind) if e.isVisible())

    def history():
        with sqlite3.connect(database) as db:
            return db.execute("SELECT COUNT(*) FROM finding_edit_history").fetchone()[0]

    def saved(field, value, row=0):
        until(app, lambda: not page._filter_busy and page.model.rows
              and page.model.rows[row].get("location_raw" if field == "location" else field) == value,
              "persisted field and completed refresh")
        with sqlite3.connect(database) as db:
            record = page.model.rows[row]
            assert db.execute(f"SELECT {field} FROM findings WHERE id=?", (record["id"],)).fetchone()[0] == value

    before = history()
    editor = begin("analysis")
    assert not page.model.selected
    assert page.parity_tabs.currentIndex() == 0
    expected = ref["samples"][0]
    actual = {"width": editor.width(), "height": editor.height(), "row": page.table.rowHeight(0)}
    assert abs(actual["width"] - expected["rect"]["width"]) <= 1, actual
    assert abs(actual["height"] - expected["rect"]["height"]) <= 1, actual
    assert abs(actual["row"] - expected["cell"]["height"]) <= 1, actual
    window.grab().save(str(work / "native-multiline-editor.png"))
    QTest.keyClicks(editor, "NATIVE MULTILINE CHECK")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    composition = QInputMethodEvent()
    composition.setCommitString("中文第二行")
    QApplication.sendEvent(editor, composition)
    QTest.keyClick(editor, Qt.Key.Key_Return)
    value = editor.toPlainText()
    assert value == ref["samples"][1]["value"]
    assert history() == before and editor.isVisible()
    samples.append({"name": "enter-newline", "value": value, "history_added": 0})
    QTest.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    saved("analysis", value)
    assert history() == before + 1
    assert page.table.rowHeight(0) == original_height and not page.model.selected
    editor = begin("analysis")
    editor.setPlainText("CANCELED VALUE")
    QTest.keyClick(editor, Qt.Key.Key_Escape)
    wait(40)
    assert page.model.rows[0]["analysis"] == value and history() == before + 1
    editor = begin("analysis")
    editor.setPlainText(ref["record"]["analysis"])
    # A real click outside the editor triggers the same blur save as the reference.
    QTest.mouseClick(page.records_title, Qt.MouseButton.LeftButton)
    saved("analysis", ref["record"]["analysis"])
    assert history() == before + 2
    location_row = next(i for i, row in enumerate(page.model.rows) if row["id"] == ref["locationRecord"]["id"])
    original_location = page.model.rows[location_row]["location_raw"]
    editor = begin("location", location_row)
    assert editor.text() == ref["locationRecord"]["location_raw"] == original_location
    QTest.keyClick(editor, Qt.Key.Key_Return)
    wait(50)
    assert history() == before + 2, "opening and closing raw location wrote formatted display"
    editor = begin("location", location_row)
    editor.setText("P4+2")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    saved("location", "P4+2", location_row)
    editor = begin("location", location_row)
    editor.setText(original_location)
    QTest.keyClick(editor, Qt.Key.Key_Return)
    saved("location", original_location, location_row)
    assert history() == before + 4
    # A stale editor must be refused by the real backend optimistic check.
    original_note = page.model.rows[0]["analysis"]
    editor = begin("analysis")
    request(client, "POST", "/api/findings/edit", {"id": ref["record"]["id"], "field": "analysis",
                                                "value": "EXTERNAL CHANGE", "expected_value": original_note})
    editor.setPlainText("STALE EDIT")
    warnings = []
    with patch.object(QMessageBox, "warning", side_effect=lambda *args: warnings.append(str(args[-1]))):
        QTest.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        until(app, lambda: bool(warnings), "stale edit refusal")
        saved("analysis", "EXTERNAL CHANGE")
    assert "其他操作" in warnings[0], warnings
    assert history() == before + 5
    editor = begin("analysis")
    editor.setPlainText(original_note)
    QTest.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    saved("analysis", original_note)
    assert history() == before + 6
    # The retained maintenance source column also uses a multiline editor,
    # with Escape preserving the original and no recognition write.
    editor = begin("maintenance_text")
    editor.setPlainText("管状态原文\n待人工核对")
    QTest.keyClick(editor, Qt.Key.Key_Escape)
    wait(40)
    assert history() == before + 6
    assert page.table.rowHeight(0) == original_height
    page.table.horizontalScrollBar().setValue(0)
    window.grab().save(str(work / "native-editor-restored.png"))
    return {"reference_editor": expected, "native_editor": actual, "enter_and_ime_value": value,
            "samples": samples, "history_added": history() - before, "raw_location": original_location,
            "raw_location_roundtrip": True, "unchanged_did_not_write": True, "blur_restore": True,
            "escape_preserved": True, "conflict_rejected": warnings[0], "maintenance_escape": True}
