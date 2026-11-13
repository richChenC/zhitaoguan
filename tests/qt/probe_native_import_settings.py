"""Real source scan, rule lineage, persistence and responsive native window probe."""
from datetime import datetime
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import shutil
import traceback

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
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    work = root.parent / "05_测试与验证/03_自动化临时产物" / (
        "native-import-settings-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    work.mkdir(parents=True)
    formal = root / "user-data/data/thimble.db"
    preferences = root / "user-data/native-preferences.json"
    formal_before = hashes(formal)
    pref_before = hashlib.sha256(preferences.read_bytes()).hexdigest()
    database = work / "data/thimble.db"
    database.parent.mkdir()
    with closing(sqlite3.connect(formal.as_uri() + "?mode=ro", uri=True)) as source, closing(sqlite3.connect(database)) as target:
        source.backup(target)
        target.executescript("DELETE FROM login_sessions; DELETE FROM user_roles; DELETE FROM users;")
    for key, value in {"THIMBLE_QT_TEST_DATA_ROOT": work, "THIMBLE_ALLOW_MULTI_INSTANCE": "1",
                       "THIMBLE_DB_PATH": database, "THIMBLE_DATA_DIR": database.parent,
                       "THIMBLE_OUTPUT_DIR": work / "exports", "THIMBLE_REPORT_DIR": work / "reports",
                       "THIMBLE_PORT": "0", "QSG_RENDER_LOOP": "basic"}.items():
        os.environ[key] = str(value)
    from PySide6.QtCore import QPoint, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from qt_shell.backend_service import BackendService
    from qt_shell.log_utils import ServiceLog
    from qt_shell.native_client import NativeClient
    from qt_shell.native_windows import NativeMainWindow
    from qt_shell.native_import import ImportWizard
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    backend = BackendService(ServiceLog(work / "service.log"))
    result = {"passed": False, "samples": [], "errors": []}
    window = client = None
    try:
        client = NativeClient(backend.start(), app)
        credentials = {"username": "settingsprobe", "display_name": "Settings Probe",
                       "password": "SettingsProbe@2026"}
        request(client, "POST", "/api/auth/setup", credentials)
        user = request(client, "POST", "/api/auth/login", credentials)["user"]
        window = NativeMainWindow(client, user)
        window.show()
        dialog = window.settings_dialog
        window.open_settings(2)
        until(app, lambda: dialog._source_baseline is not None and dialog.rules_panel.loaded,
              "source and rule settings loaded")
        for sample in json.loads(args.reference.read_text(encoding="utf-8-sig"))["samples"]:
            dialog.resize(sample["width"], 820)
            pane = sample["pane"]
            dialog.nav.setCurrentRow(2 if pane == "Import" else 3)
            host = dialog.stack.currentWidget()
            host.verticalScrollBar().setValue(0)
            wait(app, 100)
            controls = {
                ".software-settings-panel": [dialog.source_panel, dialog.parsing_panel, dialog.severity_panel],
                "#serverRoot": [dialog.source_path], "#selectServerRoot": [dialog.source_browse],
                "#saveSourceDirectory": [dialog.save_source], "#scanServerBtn": [dialog.scan_source],
                "#serverStatus": [dialog.scan_status], "#sourceDirectorySaveStatus": [dialog.source_save_status],
                "#serverSources": [dialog.source_empty], "#reportPolicyNote": [dialog.policy_note],
            } if pane == "Import" else {
                "#analysisRulesPanel": [dialog.rules_panel], ".ar-active": [dialog.rules_panel.active],
                "#arName": [dialog.rules_panel.name], "#arTolerance": [dialog.rules_panel.tolerance],
                "#arNote": [dialog.rules_panel.note], "#arCreate": [dialog.rules_panel.create]}
            actual = {}
            for key, widgets in controls.items():
                entries = []
                for index, widget in enumerate(widgets):
                    point = widget.mapTo(dialog, QPoint())
                    bounds = dict(x=point.x(), y=point.y(), width=widget.width(), height=widget.height())
                    expected = sample["controls"][key][index]["rect"]
                    entries.append({"rect": bounds, "difference": {
                        field: round(value - expected[field], 3) for field, value in bounds.items()}})
                actual[key] = entries
            result["samples"].append({"width": sample["width"], "pane": pane, "controls": actual})
            dialog.grab().save(str(work / f"native-{pane}-{sample['width']}.png"))
        original_rpt = root.parent / "02_项目原始资料/06_当前软件引用资料/03_原始验证数据/测试数据/指套管数据2/2.3 指套管"
        assert original_rpt.is_dir(), original_rpt
        rpt = work / "source"
        shutil.copytree(original_rpt, rpt / "红沿河项目/2号机组/H209/2.3 指套管")
        dialog.nav.setCurrentRow(2)
        dialog.source_path.setText(str(rpt))
        dialog.persist_source()
        until(app, lambda: not dialog._source_saving, "source profile save")
        profile = request(client, "GET", "/api/settings/data-source")["profile"]
        assert profile["source_directory"] == str(rpt), profile
        assert dialog.preferences.values["source_path"] == str(rpt)
        dialog.scan_sources()
        until(app, lambda: not dialog._source_scanning, "real source scan", timeout=60)
        assert dialog.source_results.buttons, dialog.scan_status.text()
        result["source_scan"] = {"status": dialog.scan_status.text(),
                                 "items": [button.item for button in dialog.source_results.buttons]}
        wizard_result = {}
        def inspect_wizard():
            try:
                wizard = next(widget for widget in app.topLevelWidgets()
                              if isinstance(widget, ImportWizard) and widget.isVisible())
                until(app, lambda: not wizard.busy, "RPT candidates loaded", timeout=60)
                assert wizard.mode.currentData() == "directory"
                assert wizard.report_choice and wizard.report_choice.groups, wizard.source_status.text()
                wizard_result.update(path=wizard.path.text(), groups=len(wizard.report_choice.groups))
                wizard.reject()
            except Exception:
                wizard_result["error"] = traceback.format_exc()
                for widget in app.topLevelWidgets():
                    if isinstance(widget, ImportWizard):
                        widget.reject()
        QTimer.singleShot(400, inspect_wizard)
        QTest.mouseClick(dialog.source_results.buttons[0], Qt.MouseButton.LeftButton)
        assert not wizard_result.get("error"), wizard_result
        assert wizard_result.get("groups"), wizard_result
        result["source_to_import"] = wizard_result
        rules = dialog.rules_panel
        dialog.nav.setCurrentRow(3)
        parent = rules.base_version
        for name, tolerance in (("原生规则来源验证", ".025"), ("原生规则第二版", ".05")):
            rules.name.setText(name)
            rules.tolerance.setText(tolerance)
            rules.note.setText("隔离真实数据联调")
            QTest.mouseClick(rules.create, Qt.MouseButton.LeftButton)
            until(app, lambda: not rules.busy and not rules.name.text() and
                  any(row["name"] == name for row in rules.rules), "rule version activated")
        active = request(client, "GET", "/api/analysis-rules")
        assert active["active"]["parent_version"] > parent
        rules.group.button(parent).click()
        assert rules.base_version == parent
        assert rules.name.text() == ""
        rules.name.setText("未保存的表单")
        rules.note.setText("刷新应保留")
        rules.load()
        wait(app, 300)
        assert rules.name.text() == "未保存的表单" and rules.note.text() == "刷新应保留"
        with closing(sqlite3.connect(database)) as db:
            stored = db.execute("SELECT version,parent_version,is_active FROM analysis_rules ORDER BY version").fetchall()
            assert sum(row[2] for row in stored) == 1
            assert stored[-1][1] == stored[-2][0]
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert db.execute("PRAGMA user_version").fetchone()[0] == 6
        result["rules"] = {"stored": stored, "draft_preserved": True}
        wait(app, 300)
        rules_host = dialog.stack.currentWidget()
        rules_host.verticalScrollBar().setValue(0)
        wait(app, 150)
        result["rule_history_geometry"] = {
            "history_height": rules.history.height(),
            "host_height": rules.history_host.height(),
            "rows": [{"version": rules.group.id(control), "height": control.height(),
                      "visible": not control.visibleRegion().isEmpty()}
                     for control in rules.group.buttons()],
        }
        dialog.grab().save(str(work / "native-rules-history-after-create.png"))
        assert rules.history.height() > 0, result["rule_history_geometry"]
        assert any(not control.visibleRegion().isEmpty() for control in rules.group.buttons()), result["rule_history_geometry"]
        for width, theme in ((1180, "light"), (820, "dark")):
            dialog.resize(width, 600)
            dialog.preferences.save(theme=theme)
            window.apply_preferences()
            for page in (2, 3):
                dialog.nav.setCurrentRow(page)
                wait(app, 180)
                host = dialog.stack.currentWidget()
                control = dialog.display_status if page == 2 else rules.create
                for _attempt in range(3):
                    host.verticalScrollBar().setValue(host.verticalScrollBar().maximum())
                    host.ensureWidgetVisible(control)
                    wait(app, 100)
                dialog.grab().save(str(work / f"native-end-{page}-{width}-{theme}.png"))
                assert not control.visibleRegion().isEmpty(), (page, width)
        result["passed"] = True
    except Exception:
        result["errors"].append(traceback.format_exc())
        if window:
            window.settings_dialog.grab().save(str(work / "failure.png"))
    finally:
        if window:
            window.close()
        if client:
            client.abort_all()
        backend.stop()
        app.processEvents()
        result["formal_business_unchanged"] = hashes(formal) == formal_before
        result["formal_preferences_unchanged"] = hashlib.sha256(preferences.read_bytes()).hexdigest() == pref_before
        result["passed"] &= result["formal_business_unchanged"] and result["formal_preferences_unchanged"]
        (work / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"passed": result["passed"], "artifacts": str(work), "errors": result["errors"]},
                         ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
