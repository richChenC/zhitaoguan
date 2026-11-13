"""Compare actual plate geometry and colors with the captured TRAE page."""
from __future__ import annotations

import json
import time

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtTest import QTest


def verify_workbench_plate(app, window, client, work, reference_path, wait, until, request):
    page = window.workbench
    references = json.loads(reference_path.read_text(encoding="utf-8-sig"))
    samples = []
    page.reset_query()
    until(app, lambda: not page._filter_busy, "plate data")
    page.clear_selection()

    def bounds(widget, parent):
        point = widget.mapTo(parent, QPoint())
        return {"x": point.x(), "y": point.y(), "w": widget.width(), "h": widget.height()}

    for sample in references:
        if not sample["name"].endswith("-empty"):
            continue
        width, theme = sample["width"], sample["theme"]
        window.context.preferences.save(theme=theme)
        window.apply_preferences()
        window.resize(width, 940)
        wait(200)
        page.scroll.verticalScrollBar().setValue(0)
        panel = page.map_panel
        actual = {".core-panel-title": bounds(panel.heading, panel),
                  "#exportCorePng": bounds(panel.export_button, panel),
                  ".core-switch": bounds(panel.modes, panel),
                  "#coreMap": bounds(page.plate, panel),
                  "#coreStats": bounds(panel.stats, panel),
                  "#detail": bounds(panel.details, panel)}
        expected_panel = sample["controls"]["#workspace .core-panel"][0]["rect"]
        differences = {}
        for selector, rect in actual.items():
            expected = sample["controls"][selector][0]["rect"]
            delta = {key: round(rect[key] - (expected[key] - expected_panel[key]
                     if key in ("x", "y") else expected[key]), 3) for key in rect}
            differences[selector] = delta
            assert all(abs(value) <= 2 for value in delta.values()), (width, theme, selector, delta)
        assert abs(panel.width() - expected_panel["w"]) <= 2
        assert page.splitter.widget(0) is (panel if width <= 1100 else page.table_host)
        grid = page.plate.grid_rect()
        expected_grid = sample["controls"][".reference-grid"][0]["rect"]
        expected_map = sample["controls"]["#coreMap"][0]["rect"]
        grid_delta = {"x": round(grid.x() - (expected_grid["x"] - expected_map["x"]), 3),
                      "y": round(grid.y() - (expected_grid["y"] - expected_map["y"]), 3),
                      "w": round(grid.width() - expected_grid["w"], 3)}
        assert all(abs(value) <= 2 for value in grid_delta.values()), grid_delta
        image = page.plate.grab().toImage()
        assert image.pixelColor(10, 10).name() == ("#182123" if theme == "dark" else "#ffffff")
        for index in range(3):
            QTest.mouseClick(page.parity_tabs, Qt.MouseButton.LeftButton,
                             pos=page.parity_tabs.tabRect(index).center())
            assert page.parity_tabs.tabRect(index).size().toTuple() == (74, 34)
            assert page.plate.parity == ("both", "odd", "even")[index]
        page.parity_tabs.setCurrentIndex(0)
        assert len(page.plate.hit_regions) == 50
        page.scroll.ensureWidgetVisible(panel)
        wait(80)
        window.grab().save(str(work / f"plate-{width}-{theme}.png"))
        samples.append({"width": width, "theme": theme, "panel_width": panel.width(),
                        "expected_width": expected_panel["w"], "controls": actual,
                        "differences": differences, "grid_difference": grid_delta})
    # Select only the first actual scope, matching the reference's selection anchor.
    window.resize(1480, 940)
    wait(100)
    anchor = page.model.rows[0]
    rows = [row for row in page.model.rows if (row["outage"], row["unit_id"]) ==
            (anchor["outage"], anchor["unit_id"])]
    page.model.selected = {row["id"]: dict(row) for row in rows}
    page._selection_changed()
    wait(100)
    expected = next(item for item in references if item["name"] == "1480-dark-selected")
    fields = [value.text() for _host, value in page.plate_stats.fields]
    targets = [item["text"] for item in expected["controls"]["#coreStats b"]]
    assert fields == targets, (fields, targets)
    assert page.plate_detail.model.rowCount() == len(rows)
    assert page.plate_detail.records.verticalScrollBar().maximum() > 0
    page.scroll.ensureWidgetVisible(page.plate_detail)
    wait(80)
    window.grab().save(str(work / "plate-selected-details.png"))
    # Actual painted even-half click must keep unit 6, load current-scope rows,
    # and offer a native three-dimensional navigation action.
    assert page.map_unit.value() == 6 and page.parity_tabs.currentIndex() == 2
    page.scroll.ensureWidgetVisible(page.plate)
    wait(80)
    key = next(key for key in page.plate.hit_regions if key[1] == 2)
    QTest.mouseClick(page.plate, Qt.MouseButton.LeftButton,
                     pos=page.plate.hit_regions[key].center().toPoint())
    until(app, lambda: "6号机 · 2号指套管" in page.plate_detail.text(), "actual tube details")
    expected_rows = request(client, "GET", "/api/findings?unit=6&outage=Y601&thimble=2&size=200")["items"]
    assert page.plate_detail.model.rowCount() == len(expected_rows) == 2
    page.scroll.ensureWidgetVisible(page.plate_detail.focus_button)
    QTest.mouseClick(page.plate_detail.focus_button, Qt.MouseButton.LeftButton)
    until(app, lambda: window.nav.currentIndex() == 1, "native tube focus navigation")
    until(app, lambda: window.stack.widget(2).tube_selector.value() == 2, "native tube number")
    assert str(window.stack.widget(2).scope.currentData()["unit"]) == "6"
    assert window.stack.widget(2).scope.currentData()["outage"] == "Y601"
    window.nav.setCurrentIndex(0)
    # Virtual record rendering stays bounded for a large selection.
    gaps, previous = [], [time.perf_counter()]
    timer = QTimer()
    timer.setInterval(16)
    def beat():
        now = time.perf_counter()
        gaps.append((now - previous[0]) * 1000)
        previous[0] = now
    timer.timeout.connect(beat)
    timer.start()
    for _ in range(10):
        page.map_panel.show_records(rows * 100)
        wait(20)
        page.map_panel.show_records(rows)
        wait(20)
    timer.stop()
    page.clear_selection()
    return {"samples": samples, "selection_stats": fields, "detail_rows": len(rows),
            "clicked_tube_rows": len(expected_rows), "native_three_d_focus": True,
            "large_selection_heartbeat_max_ms": round(max(gaps, default=0), 2)}
