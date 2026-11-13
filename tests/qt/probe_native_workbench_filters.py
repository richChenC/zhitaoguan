"""Real-data filter actions and live reference summary comparison."""
from __future__ import annotations

import json
import time

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtTest import QTest


def verify_workbench_filters(app, window, client, work, reference_path, wait, until, request):
    page = window.workbench
    window.nav.setCurrentIndex(0)
    expected = {row["name"]: row for row in json.loads(reference_path.read_text(encoding="utf-8-sig"))}
    requested = []
    def started(_identifier, _method, path):
        if path.startswith("/api/findings?"):
            requested.append(path)
    client.requestStarted.connect(started)
    samples = []
    gaps, previous = [], [time.perf_counter()]
    heartbeat = QTimer()
    heartbeat.setInterval(16)
    def beat():
        now = time.perf_counter()
        gaps.append((now - previous[0]) * 1000)
        previous[0] = now
    heartbeat.timeout.connect(beat)
    def settled(label):
        until(app, lambda: not page._filter_busy, label, 30)
        wait(60)
    def bounds(control):
        position = control.mapTo(window, QPoint(0, 0))
        return {"x": position.x(), "y": position.y(), "w": control.width(), "h": control.height()}
    try:
        page.reset_query()
        settled("unfiltered workbench")
        for width, theme in ((1480, "light"), (1480, "dark"), (1024, "light"), (980, "dark")):
            window.context.preferences.save(theme=theme)
            window.apply_preferences()
            window.resize(width, 940)
            wait(150)
            page.scroll.verticalScrollBar().setValue(0)
            controls = {"fields": [bounds(field) for field in page.filter_fields],
                        "search": bounds(page.search), "reset": bounds(page.reset_filters),
                        "summary": bounds(page.filter_summary)}
            target = expected[f"{width}-{theme}"]
            window.grab().save(str(work / f"workbench-filters-{width}-{theme}.png"))
            differences = []
            for actual, reference in zip(controls["fields"], target["controls"]["#workspace .workspace-filter"]):
                differences.append({key: round(actual[key] - reference["rect"][key], 3) for key in actual})
            for key, selector in (("search", "#searchBtn"), ("reset", "#resetBtn"),
                                  ("summary", "#workspaceFilterSummary")):
                actual, reference = controls[key], target["controls"][selector][0]["rect"]
                differences.append({part: round(actual[part] - reference[part], 3) for part in actual})
            assert all(abs(value) <= 3 for diff in differences for value in diff.values()), (
                "filter grid differs from reference", width, theme, differences)
            assert page.scroll.horizontalScrollBar().maximum() == 0
            assert not page.reset_filters.isEnabled()
            assert not page.delete.isEnabled() and not page.clear_selection_button.isEnabled()
            assert page.select_page_button.isEnabled()
            assert page.refresh_button.size().width() == page.refresh_button.size().height() == 30, (
                "refresh", bounds(page.refresh_button))
            assert page.import_button.height() == page.clear.height() == 34, (
                "primary commands", bounds(page.import_button), bounds(page.clear))
            assert page.ledger.height() == page.delete.height() == page.recycle_button.height() == 30, (
                "commands", bounds(page.ledger), bounds(page.delete), bounds(page.recycle_button))
            samples.append({"width": width, "theme": theme, "controls": controls,
                            "field_differences": differences, "summary": page.summary.text()})
        page.scope_bar.set_scope({"site": "N", "unit": "1", "outage": "N101"})
        page.detection_status.setCurrentIndex(page.detection_status.findData("war"))
        page.maintenance_status.setCurrentIndex(page.maintenance_status.findData("plugged"))
        page.analyst.setText("张三")
        page.channel.setText("6")
        QTest.mouseClick(page.search, Qt.MouseButton.LeftButton)
        settled("seven active filters")
        assert [text for _, text in page.filter_summary.entries] == [
            chip["text"] for chip in expected["seven-filters"]["chips"]]
        window.grab().save(str(work / "workbench-seven-filters.png"))
        count = len(requested)
        QTest.mouseClick(page.filter_summary.chips["detection_status"].remove_button, Qt.MouseButton.LeftButton)
        settled("clear one filter")
        assert len(requested) == count + 1
        assert [text for _, text in page.filter_summary.entries] == [
            chip["text"] for chip in expected["clear-detection"]["chips"]]
        QTest.mouseClick(page.filter_summary.clear_all, Qt.MouseButton.LeftButton)
        settled("clear all filters")
        assert page.summary.text() == expected["clear-all"]["controls"]["#workspaceFilterSummary"][0]["text"]
        assert page.records_title.text().endswith("4,517 条")
        # User typing must coalesce to one query after 350ms of inactivity.
        window.resize(1480, 940)
        wait(100)
        previous[0] = time.perf_counter()
        gaps.clear()
        count = len(requested)
        heartbeat.start()
        QTest.keyClicks(page.analyst, "continuous-input")
        wait(420)
        settled("debounced analyst")
        heartbeat.stop()
        assert len(requested) == count + 1
        QTest.keyClick(page.analyst, Qt.Key.Key_Escape)
        settled("escape clear analyst")
        # Verify selection controls against loaded records, then clear without writes.
        QTest.mouseClick(page.select_page_button, Qt.MouseButton.LeftButton)
        assert len(page.model.selected) == page.model.rowCount() > 0
        assert page.delete.isEnabled() and page.clear_selection_button.isEnabled()
        QTest.mouseClick(page.clear_selection_button, Qt.MouseButton.LeftButton)
        assert not page.model.selected and not page.delete.isEnabled()
        return {"samples": samples, "reference_seven_filters": [chip["text"] for chip in expected["seven-filters"]["chips"]],
                "one_filter_queries": 1, "debounced_queries": 1, "selection_controls": True,
                "typing_heartbeat_max_ms": round(max(gaps, default=0), 2),
                "typing_heartbeat_median_ms": round(sorted(gaps)[len(gaps)//2], 2) if gaps else None}
    finally:
        heartbeat.stop()
        client.requestStarted.disconnect(started)
