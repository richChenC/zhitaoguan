"""Exercise native chart focus and comparison windows against a disposable snapshot."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import csv
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from unittest.mock import patch

from native_desktop_workflow import request, until, wait


def main():
    native = Path(__file__).resolve().parents[2]
    work = native.parent / "05_测试与验证/03_自动化临时产物" / (
        "native-chart-windows-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    work.mkdir(parents=True)
    database = work / "data.db"
    with sqlite3.connect((native / "user-data/data/thimble.db").resolve().as_uri() + "?mode=ro",
                        uri=True) as source, sqlite3.connect(database) as target:
        source.backup(target)
        target.executescript("DELETE FROM login_sessions; DELETE FROM user_roles; DELETE FROM users;")
    for key, value in {
        "THIMBLE_QT_TEST_DATA_ROOT": work, "THIMBLE_DB_PATH": database,
        "THIMBLE_ALLOW_MULTI_INSTANCE": "1", "THIMBLE_PORT": "0",
        "THIMBLE_DATA_DIR": work / "data", "THIMBLE_REPORT_DIR": work / "reports",
        "THIMBLE_OUTPUT_DIR": work / "exports",
    }.items():
        os.environ[key] = str(value)
    sys.path.insert(0, str(native))
    from PySide6.QtCore import QRect, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QTableWidget, QWidget
    from qt_shell.backend_service import BackendService
    from qt_shell.log_utils import ServiceLog
    from qt_shell.native_client import NativeClient
    from qt_shell.native_windows import NativeMainWindow

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    backend = BackendService(ServiceLog(work / "service.log"))
    result = {"passed": False, "errors": [], "panels": [], "screens": []}
    window = client = None

    def capture(widget, name):
        filename = name + ".png"
        assert widget.grab().save(str(work / filename))
        result["screens"].append(filename)

    try:
        client = NativeClient(backend.start(), app)
        request(client, "POST", "/api/auth/setup", {
            "username": "chartprobe", "display_name": "Chart Probe", "password": "ChartProbe@2026"})
        user = request(client, "POST", "/api/auth/login", {
            "username": "chartprobe", "password": "ChartProbe@2026"})["user"]
        window = NativeMainWindow(client, user)
        window.resize(1480, 940)
        window.show()
        until(app, lambda: window.workbench.model.rowCount() > 0, "source records")
        window.context.set_scope({"site": "F", "unit": "1", "outage": ""})
        window.nav.setCurrentIndex(2)
        page = window.stack.widget(3)
        vis = page.visualization
        until(app, lambda: set(vis.latest_snapshots()) == {"F1"}, "main F1 scope")
        vis.comparison_mode.setCurrentIndex(vis.comparison_mode.findData("single"))
        original = deepcopy(vis.total.contract)
        started = time.perf_counter()
        detached = page.open_chart_window("total")
        until(app, lambda: not detached.client._replies, "independent initial requests", 30)
        result["open_total_ms"] = round((time.perf_counter() - started) * 1000, 2)
        assert detached.panel.isVisible() and not detached.isModal()
        assert detached.panel.contract == original
        vis.setCurrentIndex(1)
        vis.trends.setCurrentWidget(vis.total)
        wait(app, 50)
        assert vis.total.isVisible()
        child = detached.page
        child.scope_bar.set_scope({"site": "N", "unit": "1", "outage": "N101"})
        child.scope_bar._emit()
        until(app, lambda: set(child.visualization.latest_snapshots()) == {"N1"}
              and child.visualization.current_snapshot()["outage"] == "N101", "independent N101 scope")
        assert page.scope_bar.values() == {"site": "F", "unit": "1", "outage": ""}
        assert vis.total.contract == original
        result["independent_scope"] = {"main": page.scope_bar.values(), "child": child.scope_bar.values()}
        child.visualization.comparison_mode.setCurrentIndex(0)
        assert vis.comparison_mode.currentData() == "single"
        for width, height, theme in ((1200, 800, "light"), (900, 700, "dark")):
            window.context.preferences.save(theme=theme)
            window.apply_preferences()
            detached.resize(width, height)
            wait(app, 150)
            assert detached.panel.theme == theme
            assert detached.panel.view.width() > 300 and detached.panel.view.height() > 100
            capture(detached, f"total-{width}-{theme}")
        states = request(client, "GET", "/api/states")["items"]
        previous = next((row for row in states if row["outage"] == "N101"
                         and row["unit_id"] == 1 and row["thimble_id"] == 2), {})
        note = "INDEPENDENT CHART LIVE REFRESH"
        request(client, "POST", "/api/state", {
            "outage": "N101", "unit_id": 1, "thimble_id": 2, "state": "plugged",
            "events": ["plugged"], "offset_mm": 0, "note": note,
            "source": "isolated chart regression", "expected_updated_at": previous.get("updated_at")})
        until(app, lambda: any(tube.get("remarks") == note
                              for snap in child.visualization.data.get("snapshots") or []
                              for tube in snap.get("tubes") or []), "detached live database refresh", 30)
        assert child.scope_bar.values() == {"site": "N", "unit": "1", "outage": "N101"}
        assert page.scope_bar.values() == {"site": "F", "unit": "1", "outage": ""}
        result["live_mutation"] = {"scope_retained": True, "note": note}

        focused = []
        original_layout = detached.panel.layout()

        def inspect_focus():
            dialog = app.activeModalWidget()
            try:
                assert dialog and dialog.isAncestorOf(child.visualization.comparison_mode)
                assert dialog.isAncestorOf(detached.panel.view)
                capture(dialog, "total-focus")
                focused.append(True)
            except Exception:
                import traceback
                result["errors"].append(traceback.format_exc())
            finally:
                if dialog:
                    QTest.keyClick(dialog, Qt.Key.Key_Escape)

        QTimer.singleShot(150, inspect_focus)
        QTest.mouseClick(detached.panel.expand_button, Qt.MouseButton.LeftButton)
        assert focused == [True] and detached.panel.layout() is original_layout
        result["focus_controls_restored"] = True
        child_client = detached.client
        QTest.keyClick(detached, Qt.Key.Key_Escape)
        assert not child_client._replies and not page._chart_windows
        wait(app, 50)
        vis.setCurrentIndex(3)
        vis.history_site.setCurrentIndex(vis.history_site.findData("N"))
        vis.history_unit.setCurrentIndex(vis.history_unit.findData("N1"))
        vis.tube_number.setValue(2)
        history = vis.tube_history
        until(app, lambda: history._scope == ("N1", 2) and history.isVisible()
              and bool(history.rounds), "complete N1/2 history")
        assert page.scope_bar.values() == {"site": "F", "unit": "1", "outage": ""}
        expected = request(client, "GET", "/api/analysis/tube-longitudinal?site=N&unit=1")
        expected_tube = next(row for row in expected["tubes"] if row["tube"] == 2)
        history.rounds["N101"].header.setChecked(True)
        original_table = history.rounds["N101"].body.findChild(QTableWidget)
        findings = next(point for point in expected_tube["series"] if point["outage"] == "N101")["findings"]
        assert original_table.rowCount() == len(findings)
        for index, finding in enumerate(findings):
            assert original_table.item(index, 0).text() == (finding["location"] or "/")
            assert original_table.item(index, 4).toolTip() == (finding["source"] or "")
        if history.toggle_layout.count():
            history.toggle_layout.itemAt(0).widget().setChecked(False)
        for width, theme in ((1480, "light"), (1024, "dark")):
            window.context.preferences.save(theme=theme)
            window.apply_preferences()
            window.resize(width, 900)
            page.scroll.ensureWidgetVisible(history.subject)
            wait(app, 150)
            capture(window, f"complete-history-{width}-{theme}")
            page.scroll.ensureWidgetVisible(history.rounds["N101"].body)
            wait(app, 100)
            capture(window, f"history-original-{width}-{theme}")
        saved_csv = work / "complete-history.csv"
        page.scroll.ensureWidgetVisible(history.export)
        with patch("qt_shell.native_tube_history.QFileDialog.getSaveFileName",
                   return_value=(str(saved_csv), "CSV")):
            QTest.mouseClick(history.export, Qt.MouseButton.LeftButton)
        until(app, saved_csv.exists, "complete-history CSV", 30)
        with saved_csv.open(encoding="utf-8-sig", newline="") as stream:
            csv_rows = list(csv.DictReader(stream))
        assert len(csv_rows) == sum(max(1, len(point.get("findings") or [])) for point in expected_tube["series"])
        assert all(row["基地机组"] == "N1" and row["管号"] == "2" for row in csv_rows)
        result["complete_history"] = {"scope": list(history._scope), "rounds": len(history.rounds),
                                      "original_rows_checked": len(findings), "csv_rows": len(csv_rows),
                                      "main_scope_retained": page.scope_bar.values()}
        clone = page.open_chart_window("longitudinal")
        until(app, lambda: clone.page.visualization.tube_history._scope == ("N1", 2)
              and not clone.client._replies, "independent complete history", 30)
        clone_history = clone.page.visualization.tube_history
        assert clone_history.rounds["N101"].header.isChecked()
        if clone_history.toggle_layout.count():
            assert not clone_history.toggle_layout.itemAt(0).widget().isChecked()
        clone.resize(900, 700)
        clone.findChild(QScrollArea).ensureWidgetVisible(clone_history.rounds["N101"].body)
        wait(app, 150)
        dark_body = clone.findChild(QWidget, "workspaceBody")
        background = dark_body.grab(QRect(1, dark_body.height() - 3, 1, 1)).toImage().pixelColor(0, 0)
        assert max(background.red(), background.green(), background.blue()) < 100, background.name()
        result["complete_history"]["detached_dark_background"] = background.name()
        capture(clone, "independent-complete-history")
        result["complete_history"]["detached_disclosure_and_positions_preserved"] = True
        states = request(client, "GET", "/api/states")["items"]
        current = next(row for row in states if row["outage"] == "N101" and row["unit_id"] == 1 and row["thimble_id"] == 2)
        updated_note = "COMPLETE HISTORY LIVE SOURCE\n<literal note>"
        request(client, "POST", "/api/state", {
            "outage": "N101", "unit_id": 1, "thimble_id": 2, "state": "plugged",
            "events": ["plugged"], "offset_mm": 0, "note": updated_note,
            "source": "isolated complete history regression", "expected_updated_at": current["updated_at"]})
        for candidate in (history, clone_history):
            until(app, lambda item=candidate: item.rounds["N101"].body is not None and any(
                updated_note in label.text() for label in item.rounds["N101"].body.findChildren(QLabel)),
                "opened complete history refresh", 30)
            assert candidate.rounds["N101"].header.isChecked()
        result["complete_history"]["opened_round_refresh"] = True
        clone.close()
        wait(app, 50)
        for key in vis.chart_panels:
            dialog = page.open_chart_window(key)
            until(app, lambda: not dialog.client._replies, key + " initial requests", 30)
            assert dialog.panel.isVisible()
            assert dialog.panel.view.chart().series() or key in {"position", "increment", "scatter_panel", "frequency"}
            if key in {"longitudinal", "depths", "frequency", "position"}:
                capture(dialog, key)
            if key == "longitudinal":
                assert dialog.page.visualization.tube_number.isVisible()
                assert dialog.page.visualization.longitudinal_table.rowCount() > 0
            result["panels"].append(key)
            dialog.close()
            wait(app, 50)
        assert not page._chart_windows
        final = page.open_chart_window("total")
        last_client = final.client
        final.refresh()
        window.close()
        assert not last_client._replies and final._closed
        result["owner_close_cancels_pending"] = True
        result["passed"] = not result["errors"]
    except Exception:
        import traceback
        result["errors"].append(traceback.format_exc())
    finally:
        if window:
            window.close()
            window.deleteLater()
        if client:
            client.abort_all()
        wait(app, 50)
        backend.stop()
        if result["passed"] and "Traceback" in (work / "service.log").read_text(encoding="utf-8", errors="replace"):
            result["passed"] = False
            result["errors"].append("Backend produced a traceback during chart-window regression.")
        (work / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        app.quit()
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
