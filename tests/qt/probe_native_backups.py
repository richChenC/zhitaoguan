"""Actual backup UI, real SQLite snapshots and reference geometry."""
from contextlib import closing
from datetime import datetime
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import traceback
from unittest.mock import patch

from native_desktop_workflow import request, until, wait
from probe_native_import_quality import hashes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("reference", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    work = root.parent / "05_测试与验证/03_自动化临时产物" / (
        "native-backups-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    work.mkdir()
    database = work / "data/thimble.db"
    database.parent.mkdir()
    formal = root / "user-data/data/thimble.db"
    pref = root / "user-data/native-preferences.json"
    before, pref_before = hashes(formal), hashlib.sha256(pref.read_bytes()).hexdigest()
    with closing(sqlite3.connect(formal.as_uri() + "?mode=ro", uri=True)) as src, \
            closing(sqlite3.connect(database)) as dst:
        src.backup(dst)
        dst.executescript("DELETE FROM login_sessions; DELETE FROM user_roles; DELETE FROM users; DELETE FROM restore_points;")
        dst.commit()
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
    result = {"passed": False, "errors": [], "samples": [], "dialogs": []}
    client = window = None
    try:
        client = NativeClient(backend.start(), app)
        credentials = {"username": "backupprobe", "display_name": "Backup Probe", "password": "BackupProbe@2026"}
        request(client, "POST", "/api/auth/setup", credentials)
        user = request(client, "POST", "/api/auth/login", credentials)["user"]
        window = NativeMainWindow(client, user)
        window.show()
        window.open_settings(5)
        settings, panel = window.settings_dialog, window.settings_page.backups
        until(app, lambda: panel.loaded and panel.policy_ready, "backup list and policy")
        initial_count = len(panel.rows)
        result["initial_backup_count"] = initial_count
        QTest.mouseClick(panel.now, Qt.MouseButton.LeftButton)
        until(app, lambda: panel.loaded and not panel.busy and len(panel.rows) == initial_count + 1, "default backup", 60)
        first = dict(panel.rows[0])
        exported = work / "exported"
        exported.mkdir()
        with patch("qt_shell.native_backups.QFileDialog.getExistingDirectory", return_value=str(exported)):
            QTest.mouseClick(panel.to_folder, Qt.MouseButton.LeftButton)
        until(app, lambda: panel.loaded and not panel.busy and len(panel.rows) == initial_count + 2, "exported backup", 60)
        exported_item = next(item for item in panel.rows if item["kind"] == "exported")
        assert Path(exported_item["path"]).parent == exported
        result["backup_kinds"] = [item.get("kind") for item in panel.rows]
        for item in panel.rows:
            with closing(sqlite3.connect(Path(item["path"]).as_uri() + "?mode=ro", uri=True)) as db:
                assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert db.execute("SELECT count(*) FROM findings WHERE is_deleted=0").fetchone()[0] == 4517
            if item.get("sha256"):
                assert hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest() == item["sha256"]
        result["default_and_selected_folder_backups"] = True
        reference = json.loads(args.reference.read_text(encoding="utf-8-sig"))
        for sample in reference["samples"]:
            width, theme = sample["width"], sample["theme"]
            window.context.preferences.save(theme=theme)
            window.apply_preferences()
            settings.resize(width, 820)
            settings.stack.widget(5).verticalScrollBar().setValue(0)
            wait(app, 220)
            mapped = {
                "#backupPanel": [panel], "#backupPanel > .panel-title": [panel.header],
                "#backupSummary": [panel.summary], "#backupSummary span": panel.summary_titles,
                "#backupSummary strong": panel.summary_values, ".backup-actions": [panel.actions],
                ".backup-actions button": [panel.now, panel.to_folder, panel.refresh],
                ".backup-list-head": [panel.list_head], ".backup-list": [panel.list_host],
                ".backup-row": panel.row_widgets,
            }
            controls, differences = {}, {}
            origin = sample["controls"]["#backupPanel"][0]["rect"]
            for selector, widgets in mapped.items():
                rects = []
                for control in widgets:
                    point = control.mapTo(panel, QPoint(0, 0))
                    rects.append({"x": point.x(), "y": point.y(), "width": control.width(), "height": control.height()})
                controls[selector] = rects
                expected = sample["controls"][selector]
                differences[selector] = [{key: round(rect[key] - (expected[i]["rect"][key] -
                    (origin[key] if key in ("x", "y") else 0)), 3) for key in rect}
                    for i, rect in enumerate(rects[:len(expected)])]
            result["samples"].append({"width": width, "theme": theme, "controls": controls, "differences": differences})
            settings.grab().save(str(work / f"backup-{theme}-{width}.png"))
            for control in (panel.now, panel.to_folder, panel.refresh):
                assert panel.actions.rect().contains(control.geometry()), (width, control.geometry())
            assert panel.list_hint.width() > 0
        for theme in ("light", "dark"):
            window.context.preferences.save(theme=theme)
            window.apply_preferences()
            settings.resize(1180, 820)
            panel.open_restore(first["path"])
            until(app, lambda: panel.dialog.validated, "restore validation")
            dialog = panel.dialog
            assert not dialog.confirm.isEnabled()
            QTest.mouseClick(dialog.ack, Qt.MouseButton.LeftButton)
            assert dialog.confirm.isEnabled()
            dialog.grab().save(str(work / f"restore-{theme}.png"))
            result["dialogs"].append({"theme": theme, "size": [dialog.width(), dialog.height()],
                "body": [dialog.body.width(), dialog.body.height()],
                "scroll_max": dialog.scroll.verticalScrollBar().maximum()})
            dialog.reject()
        result["validated_acknowledgement_and_cancel"] = True
        panel.open_restore(first["path"])
        until(app, lambda: panel.dialog.validated, "narrow restore")
        panel.dialog.resize(340, 300)
        wait(app, 120)
        assert panel.dialog.scroll.verticalScrollBar().maximum() > 0
        panel.dialog.scroll.ensureWidgetVisible(panel.dialog.ack)
        panel.dialog.grab().save(str(work / "restore-narrow.png"))
        assert panel.dialog.ack.visibleRegion().boundingRect().height() > 0
        assert panel.dialog.confirm.isVisible()
        panel.dialog.reject()
        result["narrow_restore_reachable"] = True
        options = settings.stack.widget(5)
        options.ensureWidgetVisible(panel.keep)
        panel.keep.setValue(35)
        QTest.mouseClick(panel.save_policy, Qt.MouseButton.LeftButton)
        until(app, lambda: not panel.policy_busy, "save backup policy")
        with closing(sqlite3.connect(database)) as db:
            assert db.execute("SELECT automatic_keep FROM backup_policy WHERE id=1").fetchone()[0] == 35
        result["policy_persisted"] = True
        corrupt = work / "invalid.db"
        corrupt.write_bytes(b"invalid backup fixture")
        with patch("qt_shell.native_backups.QFileDialog.getOpenFileName", return_value=(str(corrupt), "")):
            QTest.mouseClick(panel.external, Qt.MouseButton.LeftButton)
        until(app, lambda: panel.dialog and "无法恢复" in panel.dialog.message.text(), "invalid external backup")
        assert not panel.dialog.confirm.isEnabled() and not panel.dialog.ack.isEnabled()
        panel.dialog.reject()
        result["corrupt_backup_rejected"] = True
        finding = request(client, "GET", "/api/findings?raw=1&size=1")["items"][0]
        original = finding.get("analysis")
        request(client, "POST", "/api/findings/edit", {"id": finding["id"], "field": "analysis",
                "value": "BACKUP RESTORE REAL CONTROL", "expected_value": original})
        signals = []
        window.logoutRequested.connect(lambda: signals.append(True))
        with patch("qt_shell.native_backups.QFileDialog.getOpenFileName", return_value=(exported_item["path"], "")):
            QTest.mouseClick(panel.external, Qt.MouseButton.LeftButton)
        until(app, lambda: panel.dialog and panel.dialog.validated, "external backup validated", 60)
        QTest.mouseClick(panel.dialog.ack, Qt.MouseButton.LeftButton)
        QTest.mouseClick(panel.dialog.confirm, Qt.MouseButton.LeftButton)
        until(app, lambda: bool(signals), "restored logout", 60)
        revoked = {}
        client.get("/api/auth/me", lambda data, error: revoked.update(data=data, error=error))
        until(app, lambda: "error" in revoked, "old session rejected")
        assert revoked["error"]
        request(client, "POST", "/api/auth/login", credentials)
        with closing(sqlite3.connect(database)) as db:
            assert db.execute("SELECT analysis FROM findings WHERE id=?", (finding["id"],)).fetchone()[0] == original
            safety = dict(zip(("path", "kind"), db.execute(
                "SELECT path,kind FROM restore_points WHERE kind='safety' ORDER BY id DESC LIMIT 1").fetchone()))
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert db.execute("SELECT automatic_keep FROM backup_policy WHERE id=1").fetchone()[0] == 35
        with closing(sqlite3.connect(Path(safety["path"]).as_uri() + "?mode=ro", uri=True)) as db:
            assert db.execute("SELECT analysis FROM findings WHERE id=?", (finding["id"],)).fetchone()[0] == "BACKUP RESTORE REAL CONTROL"
        result["external_restore_original_value_old_session_and_safety"] = True
        # Recover the pre-restore state from the safety snapshot through the same controls.
        panel.load()
        until(app, lambda: panel.loaded and not panel.reading, "safety backup list")
        panel.open_restore(safety["path"])
        until(app, lambda: panel.dialog and panel.dialog.validated, "safety snapshot validation", 60)
        QTest.mouseClick(panel.dialog.ack, Qt.MouseButton.LeftButton)
        QTest.mouseClick(panel.dialog.confirm, Qt.MouseButton.LeftButton)
        until(app, lambda: len(signals) == 2, "safety snapshot restore", 60)
        request(client, "POST", "/api/auth/login", credentials)
        with closing(sqlite3.connect(database)) as db:
            assert db.execute("SELECT analysis FROM findings WHERE id=?", (finding["id"],)).fetchone()[0] == "BACKUP RESTORE REAL CONTROL"
        result["safety_snapshot_recovery"] = True
        result["formal_business_unchanged"] = before == hashes(formal)
        result["formal_preferences_unchanged"] = pref_before == hashlib.sha256(pref.read_bytes()).hexdigest()
        assert result["formal_business_unchanged"] and result["formal_preferences_unchanged"]
        result["passed"] = True
    except Exception:
        result["errors"].append(traceback.format_exc())
    finally:
        if window:
            if window.settings_page.backups.dialog:
                window.settings_page.backups.dialog.restoring = False
                window.settings_page.backups.dialog.close()
            window.close()
        if client:
            client.abort_all()
        backend.stop()
        (work / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"artifacts": str(work), "passed": result["passed"], "errors": result["errors"]},
                     ensure_ascii=False), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
