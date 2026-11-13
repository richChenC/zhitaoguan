"""Replay actual reference selection and compare the exported native image."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit

from qt_shell.native_plate_snapshot import create_plate_snapshot


def verify_workbench_selection(app, window, client, work, reference_path, wait, until, request):
    reference = json.loads(reference_path.read_text(encoding="utf-8-sig"))
    targets = {sample["name"]: sample for sample in reference["samples"]}
    page = window.workbench
    window.resize(1480, 940)
    page.reset_query()
    until(app, lambda: not page._filter_busy, "selection initial records")
    page.clear_selection()
    samples = []

    def capture(name):
        actual = list(page.model.selected)
        assert actual == targets[name]["selected"], (name, actual, targets[name]["selected"])
        assert page.model.rows[0]["id"] == targets[name]["first"], name
        samples.append({"name": name, "selected_ids": actual})

    def click(row, modifiers=Qt.KeyboardModifier.NoModifier, column=2):
        page.scroll.ensureWidgetVisible(page.table)
        index = page.model.index(row, column)
        page.table.scrollTo(index)
        wait(30)
        QTest.mouseClick(page.table.viewport(), Qt.MouseButton.LeftButton, modifiers,
                         page.table.visualRect(index).center())
        wait(20)

    click(0)
    capture("row-0-click")
    click(3, Qt.KeyboardModifier.ShiftModifier)
    capture("shift-row-3")
    click(3, Qt.KeyboardModifier.ShiftModifier)
    capture("shift-same-row-3")
    click(56)
    capture("reject-other-scope-row-56")
    for name in ("select-page", "select-page-again"):
        page.scroll.ensureWidgetVisible(page.select_page_button)
        QTest.mouseClick(page.select_page_button, Qt.MouseButton.LeftButton)
        capture(name)
    page.field_mode.setCurrentIndex(1)
    column = page.model.fields.index("analysis")
    index = page.model.index(1, column)
    page.scroll.ensureWidgetVisible(page.table)
    page.table.scrollTo(index)
    wait(50)
    position = page.table.visualRect(index).center()
    QTest.mouseClick(page.table.viewport(), Qt.MouseButton.LeftButton, pos=position)
    QTest.mouseDClick(page.table.viewport(), Qt.MouseButton.LeftButton, pos=position)
    wait(40)
    editors = [control for control in page.table.findChildren(QLineEdit) if control.isVisible()]
    assert len(editors) == 1, "actual double-click editor"
    capture("double-click-editor")
    QTest.keyClick(editors[0], Qt.Key.Key_Escape)
    wait(40)
    capture("cancel-editor")
    exported = reference["exported"]
    rows = list(page.model.selected.values())
    settings = exported["settings"]
    page.plate.levels = [settings["midThreshold"], settings["highThreshold"]]
    page.plate.colors = [settings[key] for key in ("low", "mid", "high")]
    image, stats = create_plate_snapshot(rows, page.plate.channels, page.plate.levels, page.plate.colors)
    assert image.size().toTuple() == (exported["width"], exported["height"])
    assert stats["max_percent"] == exported["maxPercent"]
    assert stats["dense"] == exported["densestZone"] and stats["dense_count"] == exported["densestCount"]
    assert stats["tube_maximums"] == {tuple(map(int, key.split("|"))): value
                                    for key, value in exported["tubeMaximums"]}
    original = QImage(str(reference_path.with_name("reference-plate-export.png")))
    assert not original.isNull() and original.size() == image.size()
    field = "serialOdd" if stats["unit"] % 2 else "serialEven"
    markers = []
    for channel in page.plate.channels:
        match = re.fullmatch(r"([A-Z])(\d+)", channel["pos"])
        x = int(260 + ("RPNMLKJHGFEDCBA".index(match[1]) + .5) * 62)
        y = int(190 + (int(match[2]) - .5) * 62)
        # Interior points avoid font rasterization and antialiased circle boundaries.
        for dx, dy in ((10, -10), (-10, -10), (10, 10), (-10, 10)):
            assert image.pixelColor(x + dx, y + dy) == original.pixelColor(x + dx, y + dy), (
                channel["pos"], image.pixelColor(x + dx, y + dy).name(),
                original.pixelColor(x + dx, y + dy).name())
        markers.append({"tube": int(channel[field]), "position": channel["pos"],
                        "color": image.pixelColor(x + 10, y - 10).name()})
    text_bounds = []
    for area in ((85, 35, 450, 100), (85, 100, 600, 140), (215, 200, 245, 240),
                 (120, 1235, 300, 1280)):
        boxes = []
        for picture in (original, image):
            points = [(x, y) for y in range(area[1], area[3]) for x in range(area[0], area[2])
                      if max(picture.pixelColor(x, y).getRgb()[:3]) < 130]
            assert points, ("missing exported text", area)
            boxes.append((min(x for x, y in points), min(y for x, y in points),
                          max(x for x, y in points), max(y for x, y in points)))
        assert all(abs(a - b) <= 1 for a, b in zip(*boxes)), (area, boxes)
        text_bounds.append({"area": area, "reference": boxes[0], "native": boxes[1]})
    image.save(str(work / "native-plate-export.png"))
    path = work / "native-plate-button-export.png"
    with patch("qt_shell.native_components.QFileDialog.getSaveFileName", return_value=(str(path), "PNG")) as dialog:
        page.scroll.ensureWidgetVisible(page.map_panel.export_button)
        QTest.mouseClick(page.map_panel.export_button, Qt.MouseButton.LeftButton)
        until(app, path.exists, "audited native image file")
        suggested_name = dialog.call_args.args[2]
        assert "管板缺陷分布" in suggested_name and "Y_6号机组_Y601" in suggested_name, suggested_name
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    audits = request(client, "GET", "/api/security/exports?size=100")
    assert digest in json.dumps(audits), "saved export missing from audit API"
    # The business audit endpoint is separately permission checked; verify the exact
    # file digest against the isolated database as well as the visible export.
    database = work / "data.db"
    with sqlite3.connect(database) as db:
        audit = db.execute("SELECT resource,sha256,size_bytes FROM export_audits WHERE sha256=?",
                           (digest,)).fetchall()
    assert audit == [(path.name, digest, path.stat().st_size)], audit
    assert QImage(str(path)).size().toTuple() == (1500, 1390)
    page.clear_selection()
    for number in range(1, 4):
        header = page.table.horizontalHeader()
        page.table.scrollTo(page.model.index(0, page.model.fields.index("percent")))
        section = page.model.fields.index("percent")
        from PySide6.QtCore import QPoint
        QTest.mouseClick(header.viewport(), Qt.MouseButton.LeftButton,
                         pos=QPoint(header.sectionViewportPosition(section) + header.sectionSize(section) // 2,
                                    header.height() // 2))
        until(app, lambda: not page._filter_busy, "sorted real records")
        name = f"sort-percent-{number}"
        capture(name)
        assert page.sort_field == targets[name]["sort"]
        assert page.sort_order == (targets[name]["order"] or "asc")
    page.pager.size_combo.setCurrentText("500")
    until(app, lambda: not page._filter_busy and page.model.rowCount() == 500, "500 record selection")
    started = time.perf_counter()
    page.toggle_page()
    elapsed = round((time.perf_counter() - started) * 1000, 2)
    assert len(page.model.selected) == 56
    page.clear_selection()
    page.scroll.ensureWidgetVisible(page.table)
    page.table.horizontalScrollBar().setValue(0)
    window.grab().save(str(work / "native-selection-workbench.png"))
    return {"samples": samples, "export_size": list(image.size().toTuple()), "markers": markers,
            "text_bounds": text_bounds,
            "max_percent": stats["max_percent"], "dense": stats["dense"], "dense_count": stats["dense_count"],
            "audited_sha256": digest, "suggested_name": suggested_name, "batch_500_ms": elapsed}
