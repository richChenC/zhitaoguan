"""Real-data settings navigation, storage, clipboard and integrity verification."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time

from native_desktop_workflow import request, until, wait


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("reference", type=Path)
    parser.add_argument("--preferences-reference", type=Path)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[2]
    work = project.parent / "05_测试与验证/03_自动化临时产物" / (
        "native-settings-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    work.mkdir(parents=True)
    database = work / "data/thimble.db"
    database.parent.mkdir()
    formal = project / "user-data/data/thimble.db"
    def business_hashes(path):
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
            return {table: hashlib.sha256(json.dumps(connection.execute(
                f"SELECT * FROM {table} ORDER BY rowid").fetchall(), ensure_ascii=False,
                separators=(",", ":")).encode()).hexdigest()
                    for table in ("findings", "tube_states", "import_batches", "analysis_rules")}
    formal_before = business_hashes(formal)
    with sqlite3.connect(formal.as_uri() + "?mode=ro", uri=True) as source, \
            sqlite3.connect(database) as target:
        source.backup(target)
        target.executescript("DELETE FROM login_sessions; DELETE FROM user_roles; DELETE FROM users;")
    for key, value in {
        "THIMBLE_QT_TEST_DATA_ROOT": work, "THIMBLE_DB_PATH": database,
        "THIMBLE_DATA_DIR": database.parent, "THIMBLE_OUTPUT_DIR": work / "exports",
        "THIMBLE_REPORT_DIR": work / "reports", "THIMBLE_PORT": "0",
        "THIMBLE_ALLOW_MULTI_INSTANCE": "1", "QSG_RENDER_LOOP": "basic",
    }.items():
        os.environ[key] = str(value)
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from qt_shell.backend_service import BackendService
    from qt_shell.log_utils import ServiceLog
    from qt_shell.native_client import NativeClient
    from qt_shell.native_windows import NativeMainWindow
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    backend = BackendService(ServiceLog(work / "service.log"))
    window = client = None
    result = {"passed": False, "errors": [], "samples": []}
    reference = json.loads(args.reference.read_text(encoding="utf-8-sig"))
    try:
        client = NativeClient(backend.start(), app)
        request(client, "POST", "/api/auth/setup",
                {"username": "settingsprobe", "display_name": "Settings Probe", "password": "SettingsProbe@2026"})
        user = request(client, "POST", "/api/auth/login",
                       {"username": "settingsprobe", "password": "SettingsProbe@2026"})["user"]
        window = NativeMainWindow(client, user)
        window.show()
        until(app, lambda: window.workbench.model.rowCount() > 0 and not window.settings_page._source_busy,
              "settings source and real findings")
        window.open_settings()
        dialog, page = window.settings_dialog, window.settings_page
        until(app, lambda: bool(page.source_fields["path"].text()), "actual SQLite path")
        assert Path(page.source_fields["path"].text()) == database
        actual_path = page.source_fields["path"].text()
        for sample in reference["samples"]:
            if sample["pane"] != "Data":
                continue
            window.context.preferences.save(theme=sample["theme"])
            window.apply_preferences()
            dialog.resize(sample["width"], 820)
            dialog.nav.setCurrentRow(0)
            wait(app, 150)
            # Reuse the same displayed path to compare line wrapping independently of sandbox names.
            page.source_fields["path"].setText(sample["controls"]["#dataSourcePath"]["text"])
            wait(app, 80)
            controls = {
                ".settings-sidebar": dialog.sidebar, ".settings-nav": dialog.nav,
                ".settings-sidebar-label": dialog.sidebar_caption, ".settings-local-indicator": dialog.local,
                "#settingsDataPane .panel-title": page.source.header,
                "#dataSourceMode": page.source_badge, "#dataSourcePath": page.source_fields["path"],
                "#copyDataSourcePath": page.source_copy, "#dataSourceStatus": page.source_status,
                "#refreshDataSource": page.source_refresh, "#validateDataSource": page.source_validate,
                ".settings-quick-actions": dialog.quick_host, ".settings-quick-heading": dialog.quick_host.heading_row,
            }
            actual, differences = {}, {}
            for selector, control in controls.items():
                origin = control.mapTo(dialog, QPoint())
                bounds = dict(x=origin.x(), y=origin.y(), width=control.width(), height=control.height())
                expected = sample["controls"][selector]["rect"]
                actual[selector] = bounds
                differences[selector] = {key: round(value - expected[key], 3) for key, value in bounds.items()}
            tabs = []
            for index, expected in enumerate(sample["tabs"]):
                rect = dialog.nav.visualItemRect(dialog.nav.item(index))
                origin = dialog.nav.viewport().mapTo(dialog, rect.topLeft())
                bounds = dict(x=origin.x(), y=origin.y(), width=rect.width(),
                              height=rect.height() - (4 if index < 5 else 0))
                tabs.append({"bounds": bounds, "differences": {
                    key: round(value - expected["rect"][key], 3) for key, value in bounds.items()}})
            result["samples"].append({"width": sample["width"], "theme": sample["theme"],
                                      "controls": actual, "differences": differences, "tabs": tabs})
            dialog.grab().save(str(work / f"native-settings-Data-{sample['width']}-{sample['theme']}.png"))
        if args.preferences_reference:
            preferences_reference = json.loads(args.preferences_reference.read_text(encoding="utf-8-sig"))
            result["preferences"] = []
            for sample in preferences_reference["samples"]:
                window.context.preferences.save(theme=sample["theme"])
                window.apply_preferences()
                dialog.resize(sample["width"], 820)
                dialog.nav.setCurrentRow(1)
                host = dialog.stack.widget(1)
                host.verticalScrollBar().setValue(0)
                wait(app, 100)
                panel = dialog.preference_panel
                controls = {
                    ".preferences-panel": panel, ".panel-title": panel.header,
                    "#preferencesSaved": panel.saved,
                    "#preferencesStatus": panel.status, "#resetPreferences": panel.reset,
                    ".settings-action-row": panel.actions, "#settingsDensity": dialog.density,
                    "#settingsMotion": dialog.animations, "#settingsNotificationDuration": dialog.notification_duration,
                    "#settingsStartupView": dialog.start, "#settingsShiftDirection": dialog.direction,
                    "#settingsImportPolicy": dialog.policy, ".theme-switch": dialog.theme_host,
                }
                actual, differences = {}, {}
                for selector, control in controls.items():
                    origin = control.mapTo(dialog, QPoint())
                    bounds = dict(x=origin.x(), y=origin.y(), width=control.width(), height=control.height())
                    expected = sample["controls"][selector]["rect"]
                    actual[selector] = bounds
                    differences[selector] = {key: round(value - expected[key], 3) for key, value in bounds.items()}
                rows = []
                for row, expected in zip(panel.rows, sample["rows"]):
                    origin = row.mapTo(dialog, QPoint())
                    bounds = dict(x=origin.x(), y=origin.y(), width=row.width(), height=row.height())
                    rows.append({"bounds": bounds, "differences": {
                        key: round(value - expected["rect"][key], 3) for key, value in bounds.items()}})
                result["preferences"].append({"width": sample["width"], "theme": sample["theme"],
                    "controls": actual, "differences": differences, "rows": rows,
                    "hints": [{"text": row.hint.text(), "width": row.hint.width(),
                               "layout_height": row.hint.text_layout(row.hint.width())[1],
                               "family": row.hint.font().family()} for row in panel.rows]})
                if sample["width"] in (1180, 901, 900, 820):
                    dialog.grab().save(str(work / f"native-preferences-{sample['width']}-{sample['theme']}.png"))
                host.verticalScrollBar().setValue(host.verticalScrollBar().maximum())
                wait(app, 40)
                assert dialog.reset_button.visibleRegion().boundingRect().height() >= 35
            dialog.nav.setCurrentRow(0)
            wait(app, 50)
        page.source_fields["path"].setText(actual_path)
        QTest.mouseClick(page.source_copy, Qt.MouseButton.LeftButton)
        assert QApplication.clipboard().text() == actual_path
        assert page.source_copy.text() == "已复制"
        QTest.mouseClick(page.source_validate, Qt.MouseButton.LeftButton)
        assert not page.source_validate.isEnabled() and not page.source_refresh.isEnabled()
        until(app, lambda: not page._source_busy, "integrity validation")
        assert "通过" in page.source_status.text(), page.source_status.text()
        assert "校验通过" in page.source_badge.text(), page.source_badge.text()
        result["integrity"] = page.source_status.text()
        result["clipboard_verified"] = True
        QTest.mouseClick(dialog.quick_actions[2], Qt.MouseButton.LeftButton)
        assert dialog.nav.currentRow() == 2 and dialog.nav.hasFocus()
        for key, expected in ((Qt.Key.Key_Down, 3), (Qt.Key.Key_End, 5), (Qt.Key.Key_Right, 0),
                              (Qt.Key.Key_Left, 5), (Qt.Key.Key_Home, 0)):
            QTest.keyClick(dialog.nav, key)
            assert dialog.nav.currentRow() == expected
        result["keyboard"] = True
        for index in range(6):
            QTest.mouseClick(dialog.nav.viewport(), Qt.MouseButton.LeftButton,
                             pos=dialog.nav.visualItemRect(dialog.nav.item(index)).center())
            assert dialog.stack.currentIndex() == index
        result["categories"] = 6
        if args.preferences_reference:
            dialog.nav.setCurrentRow(1)
            wait(app, 50)
            duration = dialog.notification_duration
            duration.setCurrentIndex(duration.findData(5000))
            until(app, lambda: window.context.preferences.values["notification_duration"] == 5000,
                  "saved notification duration")
            dialog.animations.setCurrentIndex(dialog.animations.findData(False))
            dialog.policy.setCurrentIndex(dialog.policy.findData("latest"))
            until(app, lambda: window.context.preferences.values["report_policy"] == "latest"
                  and window.context.preferences.values["animations"] is False, "saved preference controls")
            assert dialog.display_policy.currentData() == "latest"
            dialog.display_policy.setCurrentIndex(dialog.display_policy.findData("manual"))
            until(app, lambda: window.context.preferences.values["report_policy"] == "manual",
                  "import policy synchronized from import display category")
            assert dialog.policy.currentData() == "manual"
            dialog.start.setCurrentIndex(dialog.start.findData(3))
            assert not dialog.remember.isChecked()
            until(app, lambda: window.context.preferences.values["start_page"] == 3
                  and not window.context.preferences.values["remember_page"], "startup choice saved")
            dialog.remember.setChecked(True)
            assert dialog.start.currentData() == -1
            until(app, lambda: window.context.preferences.values["remember_page"], "remember workspace saved")
            before = request(client, "GET", "/api/settings/state-direction")
            for value in ("pending", before["shift_direction"]):
                dialog.direction.setCurrentIndex(dialog.direction.findData(value))
                dialog.save_direction()
                until(app, lambda: not dialog._direction_busy, "database direction saved")
                assert request(client, "GET", "/api/settings/state-direction")["shift_direction"] == value
                with sqlite3.connect(database) as connection:
                    stored = connection.execute("SELECT shift_direction FROM state_preferences WHERE id=1").fetchone()
                assert stored == (value,), stored
                result.setdefault("database_direction", []).append({"requested": value, "stored": stored})
            result["preference_interactions"] = True
            apply_times = []
            for index in range(10):
                window.context.preferences.save(notification_duration=3000 if index % 2 else 5000)
                started = time.perf_counter()
                window.apply_preferences()
                apply_times.append(round((time.perf_counter() - started) * 1000, 3))
                wait(app, 20)
            result["notification_apply_ms"] = apply_times
        formal_after = business_hashes(formal)
        result["formal_business"] = {"before": formal_before, "after": formal_after,
                                     "unchanged": formal_before == formal_after}
        assert result["formal_business"]["unchanged"]
        bad = [(s["width"], s["theme"], selector, diff) for s in result["samples"]
               for selector, diff in s["differences"].items() if any(abs(v) > 2 for v in diff.values())]
        bad.extend((s["width"], s["theme"], "tab", tab["differences"]) for s in result["samples"]
                   for tab in s["tabs"] if any(abs(v) > 2 for v in tab["differences"].values()))
        bad.extend((s["width"], s["theme"], selector, diff) for s in result.get("preferences", [])
                   for selector, diff in s["differences"].items() if any(abs(v) > 2 for v in diff.values()))
        bad.extend((s["width"], s["theme"], "row", row["differences"]) for s in result.get("preferences", [])
                   for row in s["rows"] if any(abs(v) > 2 for v in row["differences"].values()))
        assert not bad, bad
        result["passed"] = True
    except Exception as exc:
        result["errors"].append(str(exc))
    finally:
        if window:
            window.close()
        if client:
            client.abort_all()
        backend.stop()
        (work / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"artifacts": str(work), **result}, ensure_ascii=False, indent=2), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
