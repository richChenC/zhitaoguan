"""Actual native audit UI against a formal snapshot plus explicit isolated fixtures."""
from contextlib import closing
from datetime import datetime
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import traceback
from unittest.mock import patch

from native_desktop_workflow import request, until, wait


def hashes(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        return {table: hashlib.sha256(json.dumps(db.execute(
            f"SELECT * FROM {table} ORDER BY rowid").fetchall(), ensure_ascii=False,
            separators=(",", ":")).encode()).hexdigest()
                for table in ("findings", "tube_states", "import_batches", "analysis_rules")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("reference", type=Path)
    parser.add_argument("--reviews-reference", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    work = root.parent / "05_测试与验证/03_自动化临时产物" / (
        "native-import-quality-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    work.mkdir(parents=True)
    database = work / "data/thimble.db"
    database.parent.mkdir()
    formal = root / "user-data/data/thimble.db"
    pref = root / "user-data/native-preferences.json"
    before, pref_before = hashes(formal), hashlib.sha256(pref.read_bytes()).hexdigest()
    with closing(sqlite3.connect(formal.as_uri() + "?mode=ro", uri=True)) as source, closing(sqlite3.connect(database)) as target:
        source.backup(target)
        target.executescript("DELETE FROM login_sessions; DELETE FROM user_roles; DELETE FROM users;")
        target.commit()
    for key, value in {"THIMBLE_QT_TEST_DATA_ROOT": work, "THIMBLE_ALLOW_MULTI_INSTANCE": "1",
                       "THIMBLE_DB_PATH": database, "THIMBLE_DATA_DIR": database.parent,
                       "THIMBLE_OUTPUT_DIR": work / "exports", "THIMBLE_REPORT_DIR": work / "reports",
                       "THIMBLE_PORT": "0", "QSG_RENDER_LOOP": "basic"}.items():
        os.environ[key] = str(value)
    from PySide6.QtCore import QPoint, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox
    from openpyxl import Workbook, load_workbook
    from qt_shell.backend_service import BackendService
    from qt_shell.log_utils import ServiceLog
    from qt_shell.native_client import NativeClient
    from qt_shell.native_windows import NativeMainWindow
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    backend = BackendService(ServiceLog(work / "service.log"))
    result = {"passed": False, "samples": [], "errors": []}
    window = client = None
    try:
        client = NativeClient(backend.start(), app)
        credentials = {"username": "qualityprobe", "display_name": "Quality Probe", "password": "QualityProbe@2026"}
        request(client, "POST", "/api/auth/setup", credentials)
        user = request(client, "POST", "/api/auth/login", credentials)["user"]
        window = NativeMainWindow(client, user)
        window.show()
        window.open_settings(2)
        dialog, panel = window.settings_dialog, window.settings_dialog.quality_panel
        until(app, lambda: panel.fresh and not panel.reading, "real audit lists")
        initial = request(client, "GET", "/api/data-quality")
        assert initial["totals"]["issues"] == 7 and initial["totals"]["artifacts"] == 1, initial["totals"]
        result["formal_snapshot_audit"] = {"totals": initial["totals"], "batches": initial["batch_total"]}
        for sample in json.loads(args.reference.read_text(encoding="utf-8-sig"))["samples"]:
            theme, width, tab = sample["theme"], sample["width"], sample["tab"]
            dialog.preferences.save(theme=theme)
            window.apply_preferences()
            dialog.resize(width, 820)
            names = ["校验问题", "导入批次", "文件校验", "报告版本", "跨组复核"]
            panel.tabs.button(names.index(tab)).click()
            until(app, lambda: panel.fresh and not panel.reading, "tab audit " + tab)
            host = dialog.stack.currentWidget()
            host.ensureWidgetVisible(panel)
            wait(app, 80)
            controls = {":scope > summary": panel.toggle, ".iq-toolbar": panel.toolbar,
                        "#iqBatch": panel.batch, "#iqCategory": panel.category, "#iqRefresh": panel.refresh_button,
                        "#iqExport": panel.export, "#iqRollback": panel.rollback, "#iqRestore": panel.restore,
                        "#iqStatus": panel.status, ".iq-tabs": panel.tabs_host, ".iq-pager": panel.pager}
            actual = {}
            for key, widget in controls.items():
                point = widget.mapTo(panel, QPoint())
                bounds = dict(x=point.x(), y=point.y(), width=widget.width(), height=widget.height())
                reference = sample["controls"][key][0]["rect"]
                origin = sample["controls"][":scope"][0]["rect"]
                reference = {**reference, "x": reference["x"] - origin["x"], "y": reference["y"] - origin["y"]}
                actual[key] = {"rect": bounds, "difference": {
                    field: round(value - reference[field], 3) for field, value in bounds.items()}}
            assert not panel.category.isEnabled() if tab != "校验问题" else panel.category.isEnabled()
            assert panel.table is None or panel.table.height() <= 340
            result["samples"].append({"theme": theme, "width": width, "tab": tab, "controls": actual})
            if tab == "校验问题":
                dialog.grab().save(str(work / f"native-quality-{theme}-{width}.png"))
        panel.tabs.button(0).click()
        until(app, lambda: panel.fresh and not panel.reading, "issues return")
        panel.category.setCurrentIndex(panel.category.findData("PARSE_FAILED"))
        until(app, lambda: panel.fresh and not panel.reading, "empty issue filter")
        assert panel.data["totals"]["issues"] == 0 and panel.data["totals"]["artifacts"] == 1
        panel.category.setCurrentIndex(0)
        until(app, lambda: panel.fresh and not panel.reading, "all categories")

        # A small, clearly synthetic import exercises real parser and reversible batch writes.
        fixture = work / "audit-fixture.xlsx"
        book = Workbook()
        book.active.append(["大修号", "机组号", "通道编号", "在堆芯内的位置", "三字码", "磨损位置"])
        book.active.append(["F199", 1, 1, "L11", "WAR", "P1"])
        for _ in range(105):
            book.active.append(["F199", 1, 90, "", "", ""])
        book.save(fixture)
        book.close()
        imported = request(client, "POST", "/api/import-excel", {"path": str(fixture)}, timeout=60)
        assert imported.get("inserted") == 1, imported
        batch_id = imported["batch_id"]
        panel.refresh()
        until(app, lambda: panel.fresh and not panel.reading, "fixture batch read")
        panel.batch.setCurrentIndex(panel.batch.findData(str(batch_id)))
        until(app, lambda: panel.fresh and not panel.reading, "fixture batch filter")
        assert panel.data["totals"]["issues"] == 105
        assert panel.pages() == 3 and panel.table.rowCount() == 50
        panel.next.click()
        until(app, lambda: panel.fresh and not panel.reading, "fixture second page")
        assert panel.page == 2 and panel.table.rowCount() == 50
        panel.next.click()
        until(app, lambda: panel.fresh and not panel.reading, "fixture third page")
        assert panel.page == 3 and panel.table.rowCount() == 5
        result["pagination"] = {"issues": 105, "pages": 3, "last_rows": 5}
        def confirm_rollback():
            box = app.activeModalWidget()
            if isinstance(box, QMessageBox):
                next(control for control in box.buttons() if control.text() == "确认回滚").click()
        QTimer.singleShot(50, confirm_rollback)
        panel.rollback.click()
        until(app, lambda: not panel.busy and panel.fresh and panel.selected_batch()["status"] == "rolled_back",
              "batch rollback")
        with closing(sqlite3.connect(database)) as db:
            assert db.execute("SELECT is_deleted FROM findings WHERE import_batch_id=?", (batch_id,)).fetchone()[0] == 1
        panel.restore.click()
        until(app, lambda: not panel.busy and panel.fresh and panel.selected_batch()["status"] == "completed",
              "batch restore")
        with closing(sqlite3.connect(database)) as db:
            assert db.execute("SELECT is_deleted FROM findings WHERE import_batch_id=?", (batch_id,)).fetchone()[0] == 0
        result["batch_actions"] = {"batch_id": batch_id, "rollback_restore": True, "file_preserved": fixture.is_file()}

        # Cross-group members are explicit fixtures; the 4517 snapshot records stay untouched.
        with closing(sqlite3.connect(database)) as db:
            db.row_factory = sqlite3.Row
            first = dict(db.execute("SELECT * FROM findings WHERE import_batch_id=?", (batch_id,)).fetchone())
            fields = [key for key in first if key != "id"]
            db.execute("UPDATE findings SET calgroup='CAL1',analyst='quality fixture' WHERE id=?", (first["id"],))
            first.update(calgroup="CAL2", analyst="quality fixture", business_key="quality-fixture-cal2",
                         source_key="quality-fixture-source-cal2")
            db.execute("INSERT INTO findings(" + ",".join(fields) + ") VALUES(" +
                       ",".join("?" for _ in fields) + ")", [first[key] for key in fields])
            db.commit()
        panel.tabs.button(4).click()
        until(app, lambda: panel.fresh and not panel.reading and bool(panel.review_widgets), "actual review fixtures")
        widget = panel.review_widgets[0]
        assert len(widget.group["members"]) == 2
        widget.radios.buttons()[1].click()
        widget.reason.setText("隔离复核依据")
        widget.actions["representative"].click()
        until(app, lambda: not panel.busy and panel.fresh and
              panel.review_widgets[0].group["status"] == "representative", "representative saved")
        widget = panel.review_widgets[0]
        assert widget.table.rowCount() == 2
        widget.history_toggle.click()
        dialog.resize(820, 600)
        dialog.stack.currentWidget().ensureWidgetVisible(widget.history_toggle)
        wait(app, 100)
        assert not widget.history.visibleRegion().isEmpty()
        dialog.grab().save(str(work / "native-review-history-dark-820.png"))
        widget.actions["keep_all"].click()
        until(app, lambda: not panel.busy and panel.fresh and
              panel.review_widgets[0].group["status"] == "keep_all", "keep all saved")
        panel.review_widgets[0].actions["reset"].click()
        until(app, lambda: not panel.busy and panel.fresh and
              panel.review_widgets[0].group["status"] == "reset", "review reset saved")
        group = panel.review_widgets[0].group
        assert len(group["history"]) == 3 and len(group["members"]) == 2
        result["review"] = {"history": len(group["history"]), "members_preserved": 2,
                            "revision": group["revision"], "status": group["status"]}
        if args.reviews_reference:
            result["review_samples"] = []
            widget = panel.review_widgets[0]
            widget.history_toggle.click()
            for sample in json.loads(args.reviews_reference.read_text(encoding="utf-8-sig"))["samples"]:
                dialog.preferences.save(theme=sample["theme"])
                window.apply_preferences()
                dialog.resize(sample["width"], 820)
                dialog.stack.currentWidget().ensureWidgetVisible(widget)
                wait(app, 100)
                actual = {}
                controls = {"header": widget.header, ".iq-review-reason": widget.reason,
                            ".iq-review-actions": widget.tools, ".iq-review-history summary": widget.history_toggle}
                for key, control in controls.items():
                    point = control.mapTo(widget, QPoint())
                    bounds = dict(x=point.x(), y=point.y(), width=control.width(), height=control.height())
                    expected = sample["controls"][key][0]["rect"]
                    actual[key] = {"rect": bounds, "difference": {
                        field: round(value - expected[field], 3) for field, value in bounds.items()}}
                result["review_samples"].append({"theme": sample["theme"], "width": sample["width"], "controls": actual})
                dialog.grab().save(str(work / f"native-review-{sample['theme']}-{sample['width']}.png"))
        target = work / "saved-audit.xlsx"
        with patch("qt_shell.native_import_quality.QFileDialog.getSaveFileName", return_value=("", "")):
            panel.export.click()
            until(app, lambda: not panel.export_busy and panel.export_file is not None, "cancel export save")
        assert "已取消保存" in panel.status.text()
        with patch("qt_shell.native_import_quality.QFileDialog.getSaveFileName", return_value=(str(target), "")):
            panel.retry.click()
        assert target.is_file() and "已保存" in panel.status.text(), panel.status.text()
        book = load_workbook(target, read_only=True)
        assert book["有效检测记录"].max_row == 3
        assert book["校验问题"].max_row == 106
        assert book["跨组复核历史"].max_row == 4
        assert book["跨组复核来源"].max_row == 7
        result["export"] = {"sheets": book.sheetnames, "finding_rows": 2, "issue_rows": 105, "review_rows": 3,
                            "cancel_then_retry": True}
        book.close()
        timings = []
        for _ in range(8):
            start = time.perf_counter()
            panel.refresh()
            until(app, lambda: panel.fresh and not panel.reading, "repeat quality refresh")
            timings.append(round((time.perf_counter() - start) * 1000, 2))
        result["local_audit_refresh_ms"] = timings
        with closing(sqlite3.connect(database)) as db:
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        result["passed"] = True
    except Exception:
        result["errors"].append(traceback.format_exc())
        if window:
            window.settings_dialog.grab().save(str(work / "native-quality-failure.png"))
    finally:
        if window:
            window.close()
        if client:
            client.abort_all()
        backend.stop()
        result["formal_hashes"] = {"before": before, "after": hashes(formal)}
        result["formal_preferences_unchanged"] = pref_before == hashlib.sha256(pref.read_bytes()).hexdigest()
        result["passed"] = bool(result["passed"] and result["formal_hashes"]["before"] == result["formal_hashes"]["after"]
                                and result["formal_preferences_unchanged"])
        (work / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"passed": result["passed"], "work": str(work), "errors": result["errors"]}, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
