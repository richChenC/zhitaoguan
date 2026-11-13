"""Exercise native pagination and compare table controls with the live reference."""
from __future__ import annotations

import json
import math
import time

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtTest import QTest


def verify_workbench_table(app, window, client, work, reference_path, wait, until, request):
    page = window.workbench
    reference = {sample["name"]: sample for sample in json.loads(reference_path.read_text(encoding="utf-8-sig"))}
    requested, samples, paging = [], [], []
    gaps, previous = [], [time.perf_counter()]
    heartbeat = QTimer()
    heartbeat.setInterval(16)
    def beat():
        now = time.perf_counter()
        gaps.append((now - previous[0]) * 1000)
        previous[0] = now
    heartbeat.timeout.connect(beat)
    def started(_identifier, _method, path):
        if path.startswith("/api/findings?"):
            requested.append(path)
    client.requestStarted.connect(started)
    def settled(label):
        until(app, lambda: not page._filter_busy, label, 30)
        wait(60)
    def bounds(widget, parent):
        position = widget.mapTo(parent, QPoint(0, 0))
        return {"x": position.x(), "y": position.y(), "w": widget.width(), "h": widget.height()}
    try:
        page.reset_query()
        settled("table reset")
        for width, theme in ((1480, "light"), (1480, "dark"), (1120, "light"), (1024, "dark"), (980, "light")):
            window.context.preferences.save(theme=theme)
            window.apply_preferences()
            window.resize(width, 940)
            wait(150)
            page.scroll.verticalScrollBar().setValue(0)
            for mode, index in (("focus", 0), ("all", 1)):
                QTest.mouseClick(page.field_mode, Qt.MouseButton.LeftButton,
                                 pos=page.field_mode.tabRect(index).center())
                wait(50)
                assert page.field_mode.currentIndex() == index
                sample = reference[f"{width}-{theme}-{mode}"]
                actual = {"heading": bounds(page.table_heading, page.table_host),
                          "fields": bounds(page.field_modes, page.table_heading),
                          "page_size": bounds(page.page_size, page.pager),
                          "previous": bounds(page.prev, page.pager),
                          "page_info": bounds(page.page_info, page.pager),
                          "jump": bounds(page.page_jump, page.pager),
                          "table_width": page.table_host.width(), "pager_height": page.pager.height()}
                # Both engines use integer/native versus subpixel/browser layouts.
                expected_heading = sample["controls"]["#workspace .table-panel .panel-title"][0]["rect"]
                assert abs(page.table_heading.height() - expected_heading["h"]) <= 1
                assert page.field_modes.size().toTuple() == (134, 34)
                assert page.field_mode.tabRect(0).size().toTuple() == (64, 28)
                assert abs(page.table.horizontalHeader().height() - sample["controls"]["#workspace thead th"][0]["rect"]["h"]) <= 1
                for control, selector in ((page.page_size, "#pageSize"), (page.prev, "#prevBtn"),
                                           (page.page_info, "#pageInfo"), (page.page_jump, "#workspacePageJump")):
                    target = sample["controls"][selector][0]["rect"]
                    assert abs(control.width() - target["w"]) <= 1, (selector, actual, target)
                    if control is not page.page_info:
                        assert abs(control.height() - target["h"]) <= 1, (selector, actual, target)
                expected_fields = sample["controls"][".workspace-column-modes"][0]["rect"]
                assert abs(actual["fields"]["x"] - (expected_fields["x"] - expected_heading["x"])) <= 3, actual
                assert abs(actual["fields"]["y"] - (expected_fields["y"] - expected_heading["y"])) <= 1, actual
                expected_pager = sample["controls"]["#workspace .pager"][0]["rect"]
                pager_differences = {}
                for key, selector in (("page_size", "#pageSize"), ("previous", "#prevBtn"),
                                      ("page_info", "#pageInfo"), ("jump", "#workspacePageJump")):
                    target = sample["controls"][selector][0]["rect"]
                    pager_differences[key] = {
                        "x": round(actual[key]["x"] - (target["x"] - expected_pager["x"]), 3),
                        "center_y": round(actual[key]["y"] + actual[key]["h"] / 2
                                          - (target["y"] + target["h"] / 2 - expected_pager["y"]), 3),
                    }
                assert all(abs(value) <= 3 for difference in pager_differences.values() for value in difference.values()), (
                    width, theme, pager_differences)
                widths = []
                for column, expected in enumerate(sample["controls"]["#workspace thead th"]):
                    if expected["display"] == "none":
                        assert page.table.isColumnHidden(column), (mode, column)
                    else:
                        assert not page.table.isColumnHidden(column), (mode, column)
                        value = page.table.columnWidth(column)
                        assert abs(value - expected["rect"]["w"]) <= 1, (mode, column, value, expected["rect"])
                        widths.append(value)
                assert not page.table.isColumnHidden(18)
                assert page.scroll.horizontalScrollBar().maximum() == 0
                assert page.field_modes.geometry().right() <= page.table_heading.width() - 14
                samples.append({"width":width,"theme":theme,"mode":mode,"actual":actual,
                                "pager_differences":pager_differences,
                                "visible_reference_column_widths":widths})
            window.grab().save(str(work / f"table-{width}-{theme}.png"))
        window.resize(1480, 940)
        window.context.preferences.save(theme="light")
        window.apply_preferences()
        page.field_mode.setCurrentIndex(0)
        wait(100)
        page.model.selected[page.model.rows[0]["id"]] = dict(page.model.rows[0])
        page._selection_changed()
        selected = dict(page.model.selected)
        count = len(requested)
        previous[0] = time.perf_counter()
        heartbeat.start()
        page.scroll.ensureWidgetVisible(page.pager)
        QTest.mouseClick(page.next, Qt.MouseButton.LeftButton)
        assert not page.next.isEnabled() and not page.page_jump.isEnabled()
        settled("next real page")
        assert len(requested) == count + 1 and "core=0" in requested[-1]
        assert page.model.selected == selected
        assert page.page_info.text() == reference["next-page"]["controls"]["#pageInfo"][0]["text"]
        assert page.status.text() == reference["next-page"]["controls"]["#workspacePageRange"][0]["text"]
        page.page_jump.setFocus()
        QTest.keyClicks(page.page_jump, "46")
        QTest.keyClick(page.page_jump, Qt.Key.Key_Return)
        settled("last real page")
        assert page.status.text() == reference["last-page"]["controls"]["#workspacePageRange"][0]["text"]
        assert page.model.rowCount() == 17 and not page.next.isEnabled()
        count = len(requested)
        page.page_jump.setText("999")
        QTest.keyClick(page.page_jump, Qt.Key.Key_Return)
        wait(80)
        assert len(requested) == count and page.page_jump.text() == "999"
        QTest.keyClick(page.page_jump, Qt.Key.Key_Escape)
        assert page.page_jump.text() == ""
        for size in (20, 50, 200, 500, 100):
            page.page_size.setCurrentIndex(page.page_size.findData(size))
            settled(f"real page size {size}")
            assert page.page == 1 and page.pages == math.ceil(4517 / size)
            assert page.model.rowCount() == size
            assert page.status.text() == f"第 1\u2013{size} 条，共 4517 条"
            assert "core=0" not in requested[-1]
            paging.append({"size":size,"pages":page.pages,"count":page.model.rowCount(),"range":page.status.text()})
        page.table.setFocus()
        window.activateWindow()
        wait(80)
        QTest.keyClick(page.table, Qt.Key.Key_Right, Qt.KeyboardModifier.AltModifier)
        settled("native Alt Right")
        assert page.page == 2
        QTest.keyClick(page.table, Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
        settled("native Alt Left")
        assert page.page == 1
        heartbeat.stop()
        page.clear_selection()
        page.scroll.verticalScrollBar().setValue(0)
        window.grab().save(str(work / "table-final-1480.png"))
        return {"samples":samples,"paging":paging,"cross_page_selection":True,"boundary_no_query":True,
                "keyboard_navigation":True,"query_count":len(requested),
                "heartbeat_max_ms":round(max(gaps, default=0),2),
                "heartbeat_median_ms":round(sorted(gaps)[len(gaps)//2],2) if gaps else None}
    finally:
        heartbeat.stop()
        client.requestStarted.disconnect(started)
