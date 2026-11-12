"""Native charts/layout/performance inspection using an isolated source snapshot."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

from native_desktop_workflow import request, wait, until


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("--profile", action="store_true")
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[2]
    work = project.parent / "05_测试与验证" / "03_自动化临时产物" / (
        "native-visual-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    work.mkdir(parents=True)
    database = work / "data.db"
    with sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True) as source, sqlite3.connect(database) as target:
        source.backup(target)
        target.executescript("DELETE FROM login_sessions; DELETE FROM user_roles; DELETE FROM users;")
    for key, value in {"THIMBLE_QT_TEST_DATA_ROOT": work, "THIMBLE_DB_PATH": database,
                       "THIMBLE_DATA_DIR": work / "data", "THIMBLE_OUTPUT_DIR": work / "exports",
                       "THIMBLE_REPORT_DIR": work / "reports", "THIMBLE_ALLOW_MULTI_INSTANCE": "1",
                       "THIMBLE_PORT": "0"}.items():
        os.environ[key] = str(value)
    os.environ.setdefault("QSG_RENDER_LOOP", "basic")
    sys.path.insert(0, str(project))
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QTableWidget, QScrollArea
    from qt_shell.backend_service import BackendService
    from qt_shell.log_utils import ServiceLog
    from qt_shell.native_client import NativeClient
    from qt_shell.native_windows import NativeMainWindow
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    backend = BackendService(ServiceLog(work / "service.log"))
    result = {"errors": [], "timings": {}, "screens": [], "source": str(args.database.resolve())}
    window = client = None
    try:
        started = time.perf_counter()
        url = backend.start()
        result["timings"]["backend_start_s"] = round(time.perf_counter() - started, 3)
        client = NativeClient(url, app)
        request(client, "POST", "/api/auth/setup",
                {"username": "visualprobe", "display_name": "Visual Probe", "password": "VisualProbe@2026"})
        user = request(client, "POST", "/api/auth/login", {"username": "visualprobe", "password": "VisualProbe@2026"})["user"]
        gaps, beats, previous = [], [], [time.perf_counter()]
        def beat():
            now = time.perf_counter()
            gap = (now - previous[0]) * 1000
            gaps.append(gap)
            beats.append({"page": window.nav.currentIndex() if window else -1, "ms": round(gap, 2)})
            previous[0] = now
        heartbeat = QTimer()
        heartbeat.setInterval(16)
        heartbeat.timeout.connect(beat)
        heartbeat.start()
        started = time.perf_counter()
        window = NativeMainWindow(client, user)
        window.resize(1480, 940)
        window.show()
        until(app, lambda: window.workbench.model.rowCount() > 0, "first records")
        result["timings"]["window_to_records_s"] = round(time.perf_counter() - started, 3)
        window.grab().save(str(work / "workbench-1480-light.png"))
        with sqlite3.connect(database) as db:
            result["rows"] = db.execute("SELECT COUNT(*) FROM findings WHERE is_deleted=0").fetchone()[0]
            result["states"] = db.execute("SELECT COUNT(*) FROM tube_states WHERE is_deleted=0").fetchone()[0]
        query_metrics = {}
        for path in ("/api/findings?raw=1&page=1&size=100", "/api/analysis/visualization", "/api/data-quality?page=1&size=100"):
            values = []
            for _ in range(3):
                started = time.perf_counter()
                request(client, "GET", path, timeout=30)
                values.append(round((time.perf_counter() - started) * 1000, 2))
            query_metrics[path] = values
        result["timings"]["queries_ms"] = query_metrics
        window.context.set_scope({})
        analytics = window.stack.widget(3)
        window.nav.setCurrentIndex(2)
        until(app, lambda: bool(analytics.visualization.data.get("snapshots")), "chart dataset")
        vis = analytics.visualization
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QPushButton
        QTest.mouseClick(analytics.site_coverage_buttons["N"], Qt.MouseButton.LeftButton)
        QTest.mouseClick(analytics.site_coverage_buttons["H"], Qt.MouseButton.LeftButton)
        until(app, lambda: {snapshot["site"] for snapshot in vis.data.get("snapshots") or []} == {"N", "H"},
              "multisite chart dataset")
        result["multisite"] = {"selected": sorted(analytics.scope_bar.selected_sites),
                                "units": sorted(vis.latest_snapshots())}
        assert analytics.scope_bar.selected_sites == {"N", "H"}
        analytics.scope_bar.unit.setCurrentIndex(analytics.scope_bar.unit.findData("H1"))
        until(app, lambda: set(vis.latest_snapshots()) == {"H1"}, "coded H1 unit filter")
        assert analytics.scope_bar.selected_sites == {"N", "H"}
        window.nav.setCurrentIndex(0)
        window.nav.setCurrentIndex(2)
        assert analytics.scope_bar.selected_sites == {"N", "H"}
        QTest.mouseClick(analytics.scope_bar.reset, Qt.MouseButton.LeftButton)
        until(app, lambda: len(vis.latest_snapshots()) == 20, "reset all sites")
        disclosure = vis.unit_overview.disclosures[("unit", "N1")]
        analytics.scroll.ensureWidgetVisible(disclosure.header)
        QTest.mouseClick(disclosure.header, Qt.MouseButton.LeftButton)
        outage = vis.unit_overview.disclosures[("outage", "N1", "N101")]
        analytics.scroll.ensureWidgetVisible(outage.header)
        QTest.mouseClick(outage.header, Qt.MouseButton.LeftButton)
        record_button = next(control for control in outage.body.findChildren(QPushButton)
                             if control.text() == "原始检测表")
        analytics.scroll.ensureWidgetVisible(record_button)
        QTest.mouseClick(record_button, Qt.MouseButton.LeftButton)
        until(app, lambda: vis.unit_records_dialog.findChild(QTableWidget).rowCount() > 0, "raw historical records")
        raw = request(client, "GET", "/api/findings?site=N&unit=1&outage=N101&raw=1&core=0&auto_ndd=0&size=100")
        raw_table = vis.unit_records_dialog.findChild(QTableWidget)
        assert raw_table.rowCount() == len(raw["items"])
        for row, item in enumerate(raw["items"]):
            assert raw_table.item(row, 2).text() == str(item.get("indication") or "")
            assert raw_table.item(row, 6).text() == str(item.get("analysis") or "")
        result["raw_history"] = {"rows": raw_table.rowCount(), "total": raw["total"], "original_values_match": True}
        vis.unit_records_dialog.grab().save(str(work / "raw-history.png"))
        vis.unit_records_dialog.reject()
        vis.open_unit_history("N1", "N101")
        vis.open_unit_tubes("N1", "N101", [2], "state")
        history_table = vis.unit_history_dialog.findChild(QTableWidget)
        tube_table = vis.unit_tubes_dialog.findChild(QTableWidget)
        note = "LIVE DIALOG REFRESH\n<original text>"
        states = request(client, "GET", "/api/states")["items"]
        current = next((row for row in states if row["outage"] == "N101"
                        and row["unit_id"] == 1 and row["thimble_id"] == 2), {})
        request(client, "POST", "/api/state", {
            "outage": "N101", "unit_id": 1, "thimble_id": 2, "state": "plugged",
            "events": ["plugged"], "offset_mm": 0, "note": note, "source": "isolated visual regression",
            "expected_updated_at": current.get("updated_at")})
        until(app, lambda: any(history_table.item(row, 3).text() == note
                              for row in range(history_table.rowCount())), "open history refresh after write")
        until(app, lambda: tube_table.rowCount() == 1 and tube_table.item(0, 4).text() == note,
              "open tube details refresh after write")
        assert "堵管" in tube_table.item(0, 3).text()
        result["live_dialog_sync"] = {"passed": True, "scope": "N1/N101/2", "original_note_preserved": True}
        vis.unit_history_dialog.reject()
        vis.unit_tubes_dialog.reject()
        window.grab().save(str(work / "expanded-unit-history.png"))
        QTest.mouseClick(vis.unit_overview.disclosures[("unit", "N1")].header, Qt.MouseButton.LeftButton)
        analytics.scroll.verticalScrollBar().setValue(0)
        for main_tab, sub_tabs in ((0, None), (1, vis.trends), (2, None), (3, None), (4, vis.risk)):
            vis.setCurrentIndex(main_tab)
            for sub_tab in range(sub_tabs.count() if sub_tabs else 1):
                if sub_tabs:
                    sub_tabs.setCurrentIndex(sub_tab)
                wait(app, 300)
                name = f"chart-{main_tab}-{sub_tab}.png"
                window.grab().save(str(work / name))
                result["screens"].append(name)
                if main_tab == 0:
                    target = next(iter(vis.unit_overview.groups.values()), vis.unit_overview)
                    analytics.scroll.ensureWidgetVisible(target)
                    wait(app, 100)
                    unit_name = "overview-unit-history.png"
                    window.grab().save(str(work / unit_name))
                    result["screens"].append(unit_name)
                    analytics.scroll.verticalScrollBar().setValue(0)
        result["analytics"] = {"snapshots": len(vis.data["snapshots"]),
                               "change_rows": len(vis.change_result.get("rows") or []),
                               "longitudinal_points": vis.longitudinal_table.rowCount(),
                               "histogram": vis.depths.contract.get("distribution")}
        scope = request(client, "GET", "/api/overview")["combinations"][0]
        window.context.set_scope({"site": scope["site"], "unit": scope["unit_id"],
                                  "outage": scope["outage"], "thimble": "1"})
        until(app, lambda: bool(window.stack.widget(2).rows), "3D dataset")
        window.nav.setCurrentIndex(3)
        reports = window.stack.widget(4)
        QTest.mouseClick(reports.preview, Qt.MouseButton.LeftButton)
        until(app, lambda: bool(reports.snapshot_id), "rendered report preview")
        result["layouts"] = []
        for width, height, theme in ((1024, 768, "light"), (1480, 940, "dark"), (1920, 1080, "light")):
            window.context.preferences.save(theme=theme, animations=False)
            window.apply_preferences()
            window.resize(width, height)
            for page in range(5):
                window.nav.setCurrentIndex(page)
                wait(app, 150)
                name = f"layout-{width}-{theme}-{page}.png"
                window.grab().save(str(work / name))
                if page == 1:
                    image = window.stack.widget(2).view.grabWindow()
                    scene_name = name.replace(".png", "-scene.png")
                    image.save(str(work / scene_name))
                    colors = len({image.pixel(x, y) for x in range(0, image.width(), 4)
                                  for y in range(0, image.height(), 4)})
                    assert colors > 30, (scene_name, colors)
                result["layouts"].append({"requested": [width, height], "actual": [window.width(), window.height()],
                                          "page": page, "screen": name})
            window.nav.setCurrentIndex(3)
            reports.edit_header()
            wait(app, 100)
            name = f"header-{width}-{theme}.png"
            window.grab().save(str(work / name))
            result["screens"].append(name)
            reports.edit_header()
            from qt_shell.native_import import ImportWizard
            from qt_shell.native_windows import DataWorkbench
            wizard = ImportWizard(client, DataWorkbench.MAPPING_FIELDS,
                                  window.context.preferences.values, window)
            wizard.resize(900, min(820, height - 70))
            wizard.set_sources([str(args.database.parent / "reference-a.xlsx"),
                                str(args.database.parent / "reference-b.xlsx")])
            wizard.show()
            wait(app, 100)
            name = f"import-excel-{width}-{theme}.png"
            capture = wizard.grab().toImage()
            capture.save(str(work / name))
            if theme == "dark":
                assert capture.pixelColor(5, 5).lightness() < 128, "import header did not follow dark theme"
            result["screens"].append(name)
            wizard.source_tabs.setCurrentIndex(1)
            wait(app, 100)
            name = f"import-rpt-{width}-{theme}.png"
            wizard.grab().save(str(work / name))
            result["screens"].append(name)
            wizard.reject()
            window.nav.setCurrentIndex(4)
            states = window.stack.widget(1)
            states._show_state_summary("maintained")
            until(app, lambda: states.summary_dialog.findChild(QTableWidget).rowCount() > 0,
                "maintenance summary")
            name = f"state-summary-{width}-{theme}.png"
            states.summary_dialog.grab().save(str(work / name))
            result["screens"].append(name)
            states.summary_dialog.close()
            states.batch_mode.setChecked(True)
            states._select_batch(True)
            states.batch_state.setCurrentIndex(states.batch_state.findData("shifted"))
            states.findChild(QScrollArea).ensureWidgetVisible(states.batch_editor)
            wait(app, 100)
            name = f"state-batch-{width}-{theme}.png"
            window.grab().save(str(work / name))
            result["screens"].append(name)
            states.batch_mode.setChecked(False)
            QTest.mouseClick(window.notifications_button, Qt.MouseButton.LeftButton)
            wait(app, 100)
            name = f"notifications-{width}-{theme}.png"
            window.grab().save(str(work / name))
            result["screens"].append(name)
            QTest.mouseClick(window.notifications_button, Qt.MouseButton.LeftButton)
        window.settings_dialog.resize(1024, 768)
        result["settings_layouts"] = []
        for category in range(window.settings_dialog.nav.count()):
            window.open_settings(category)
            wait(app, 100)
            name = f"settings-1024-{category}.png"
            window.settings_dialog.grab().save(str(work / name))
            result["settings_layouts"].append({"category": category, "screen": name,
                                              "actual": [window.settings_dialog.width(), window.settings_dialog.height()]})
        window.settings_dialog.hide()
        # Measure navigation after the first-load work has settled.
        window.raise_()
        window.activateWindow()
        wait(app, 500)
        import cProfile
        profiler = cProfile.Profile()
        gaps.clear()
        beats.clear()
        previous[0] = time.perf_counter()
        if args.profile:
            profiler.enable()
        switches = []
        for cycle in range(5):
            for page in range(5):
                started = time.perf_counter()
                window.nav.setCurrentIndex(page)
                switches.append({"page": page, "ms": round((time.perf_counter() - started) * 1000, 2)})
                wait(app, 65)
        if args.profile:
            profiler.disable()
            import pstats
            with (work / "navigation-profile.txt").open("w", encoding="utf-8") as stream:
                pstats.Stats(profiler, stream=stream).sort_stats("cumulative").print_stats(45)
        heartbeat.stop()
        ordered = sorted(gaps)
        result["timings"]["navigation_heartbeat_p95_ms"] = round(ordered[int(len(ordered) * .95)], 2)
        result["timings"]["navigation_heartbeat_max_ms"] = round(max(gaps), 2)
        result["timings"]["navigation_samples"] = len(gaps)
        result["timings"]["longest_beats"] = sorted(beats, key=lambda item: item["ms"], reverse=True)[:10]
        result["timings"]["switches"] = switches
        result["passed"] = not result["errors"] and result["analytics"]["change_rows"] == 50
    except Exception:
        import traceback
        result["errors"].append(traceback.format_exc())
        result["passed"] = False
    finally:
        if window:
            window.close()
            window.deleteLater()
        if client:
            client.abort_all()
        wait(app, 50)
        backend.stop()
        (work / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False), flush=True)
        app.quit()
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
