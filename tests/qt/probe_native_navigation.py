"""Compare native navigation with actual TRAE computed bounds on real data."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

from native_desktop_workflow import request, until, wait as process_events


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("reference", type=Path)
    parser.add_argument("--workbench-reference", type=Path)
    parser.add_argument("--workbench-only", action="store_true")
    parser.add_argument("--table-reference", type=Path)
    parser.add_argument("--plate-reference", type=Path)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[2]
    work = project.parent / "05_测试与验证" / "03_自动化临时产物" / (
        "native-navigation-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    work.mkdir(parents=True)
    database = work / "data.db"
    with sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True) as source:
        with sqlite3.connect(database) as target:
            source.backup(target)
            target.executescript("DELETE FROM login_sessions; DELETE FROM user_roles; DELETE FROM users;")
    for key, value in {"THIMBLE_QT_TEST_DATA_ROOT": work, "THIMBLE_DB_PATH": database,
                       "THIMBLE_DATA_DIR": work / "data", "THIMBLE_OUTPUT_DIR": work / "exports",
                       "THIMBLE_REPORT_DIR": work / "reports", "THIMBLE_ALLOW_MULTI_INSTANCE": "1",
                       "THIMBLE_PORT": "0"}.items():
        os.environ[key] = str(value)
    os.environ.setdefault("QSG_RENDER_LOOP", "basic")
    from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QWidget
    from qt_shell.backend_service import BackendService
    from qt_shell.log_utils import ServiceLog
    from qt_shell.native_client import NativeClient
    from qt_shell.native_windows import NativeMainWindow
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    def wait(milliseconds):
        process_events(app, milliseconds)
    backend = BackendService(ServiceLog(work / "service.log"))
    result = {"errors": [], "samples": [], "source": str(args.database.resolve())}
    window = client = None
    gaps, previous = [], [time.perf_counter()]
    def beat():
        now = time.perf_counter()
        gaps.append((now - previous[0]) * 1000)
        previous[0] = now
    heartbeat = QTimer()
    heartbeat.setInterval(16)
    heartbeat.timeout.connect(beat)
    try:
        client = NativeClient(backend.start(), app)
        request(client, "POST", "/api/auth/setup",
                {"username": "visualprobe", "display_name": "Visual Probe", "password": "VisualProbe@2026"})
        user = request(client, "POST", "/api/auth/login",
                       {"username": "visualprobe", "password": "VisualProbe@2026"})["user"]
        window = NativeMainWindow(client, user)
        window.show()
        until(app, lambda: window.workbench.model.rowCount() > 0, "real records")
        with sqlite3.connect(database) as db:
            result["findings_before"] = db.execute("SELECT COUNT(*) FROM findings").fetchone()[0]
        def bounds(control):
            origin = control.mapTo(window, QPoint(0, 0))
            return {"x": origin.x(), "y": origin.y(), "w": control.width(), "h": control.height()}
        navigation_samples = [] if args.workbench_only else json.loads(args.reference.read_text(encoding="utf-8-sig"))
        for sample in navigation_samples:
            width, theme = sample["width"], sample["theme"]
            window.context.preferences.save(theme=theme)
            window.apply_preferences()
            window.resize(width, 940)
            window.nav.setCurrentIndex(0)
            wait(180)
            actual = {".app-nav": bounds(window.findChild(QWidget, "topNavigation")),
                      ".app-nav footer": bounds(window.utilities),
                      "#localAccountButton": bounds(window.account_button),
                      "#feedbackToggle": bounds(window.notifications_button),
                      ".nav-settings": bounds(window.settings_button)}
            differences = {}
            for selector, rect in actual.items():
                expected = sample["controls"][selector]["rect"]
                differences[selector] = {key: round(rect[key] - expected[key], 3) for key in rect}
                assert all(abs(value) <= 1 for value in differences[selector].values()), (
                    width, theme, selector, rect, expected)
            tabs = []
            for index, reference_tab in enumerate(sample["tabs"]):
                rect = window.nav.visual_tab_rect(index)
                origin = window.nav.mapTo(window, rect.topLeft())
                actual_tab = {"x": origin.x(), "y": origin.y(), "w": rect.width(), "h": rect.height()}
                assert all(abs(actual_tab[key] - reference_tab["rect"][key]) <= 1 for key in actual_tab), (
                    width, theme, index, actual_tab, reference_tab["rect"])
                tabs.append(actual_tab)
            window.grab().save(str(work / f"native-navigation-{width}-{theme}.png"))
            heartbeat.start()
            previous[0] = time.perf_counter()
            gaps.clear()
            selected = []
            for index in (4, 3, 2, 1, 0):
                QTest.mouseClick(window.nav, Qt.MouseButton.LeftButton,
                                 pos=window.nav.visual_tab_rect(index).center())
                wait(100)
                assert window.stack.currentIndex() == window._navigation_indices[index]
                selected.append(window.stack.currentIndex())
                assert window.nav.visual_tab_rect(4).right() < window.utilities.x()
            heartbeat.stop()
            result["samples"].append({"width": width, "theme": theme, "controls": actual,
                                      "differences": differences, "tabs": tabs, "pages": selected,
                                      "heartbeat_max_ms": round(max(gaps, default=0), 2)})
        QTest.mouseClick(window.account_button, Qt.MouseButton.LeftButton)
        wait(80)
        assert window.settings_dialog.isVisible() and window.settings_dialog.nav.currentRow() == 4
        window.settings_dialog.hide()
        QTest.mouseClick(window.settings_button, Qt.MouseButton.LeftButton)
        wait(80)
        assert window.settings_dialog.isVisible() and window.settings_dialog.nav.currentRow() == 0
        window.settings_dialog.hide()
        QTest.mouseClick(window.notifications_button, Qt.MouseButton.LeftButton)
        wait(80)
        assert window.task_center.dialog.isVisible()
        window.task_center.dialog.hide()
        result["utilities_clicked"] = ["账户与权限", "软件设置", "操作通知"]
        if args.workbench_reference:
            from probe_native_workbench_filters import verify_workbench_filters
            result["workbench_filters"] = verify_workbench_filters(
                app, window, client, work, args.workbench_reference, wait, until, request)
        if args.table_reference:
            from probe_native_workbench_table import verify_workbench_table
            result["workbench_table"] = verify_workbench_table(
                app, window, client, work, args.table_reference, wait, until, request)
        if args.plate_reference:
            from probe_native_workbench_plate import verify_workbench_plate
            result["workbench_plate"] = verify_workbench_plate(
                app, window, client, work, args.plate_reference, wait, until, request)
        with sqlite3.connect(database) as db:
            result["findings_after"] = db.execute("SELECT COUNT(*) FROM findings").fetchone()[0]
        assert result["findings_before"] == result["findings_after"]
    except Exception as exc:
        import traceback
        result["errors"].append(str(exc))
        result["traceback"] = traceback.format_exc()
    finally:
        heartbeat.stop()
        if window:
            window.close()
            window.deleteLater()
        if client:
            client.abort_all()
        wait(100)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        backend.stop()
        app.quit()
        (work / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"artifacts": str(work), **result}, ensure_ascii=False), flush=True)
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
