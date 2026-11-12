"""Real native report controls and TRAE analytics parity on disposable copies."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import sys
from collections import Counter

from native_desktop_workflow import request, wait, until


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", default="http://127.0.0.1:18789")
    parser.add_argument("--ui-only", action="store_true",
                        help="Validate native controls separately from unresolved business parity.")
    args = parser.parse_args()
    native = Path(__file__).resolve().parents[2]
    work = native.parent / "05_测试与验证/03_自动化临时产物" / (
        "native-report-details-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    work.mkdir(parents=True)
    database = work / "data.db"
    original = native / "user-data/data/thimble.db"
    with sqlite3.connect(original.resolve().as_uri() + "?mode=ro", uri=True) as source, \
            sqlite3.connect(database) as target:
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
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QCheckBox, QPlainTextEdit, QPushButton
    from qt_shell.backend_service import BackendService
    from qt_shell.native_client import NativeClient
    from qt_shell.native_windows import NativeMainWindow
    from qt_shell.log_utils import ServiceLog
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    backend = BackendService(ServiceLog(work / "service.log"))
    window = client = reference = None
    result = {"passed": False, "errors": [], "comparisons": [], "reports": [], "screens": []}

    def click(control):
        assert control.isVisible() and control.isEnabled(), control
        position = QPoint(8, control.height() // 2) if isinstance(control, QCheckBox) else control.rect().center()
        QTest.mouseClick(control, Qt.MouseButton.LeftButton, pos=position)
        app.processEvents()

    try:
        client = NativeClient(backend.start(), app)
        request(client, "POST", "/api/auth/setup", {
            "username": "native_details", "display_name": "界面对照回归", "password": "NativeDetails@2026"})
        user = request(client, "POST", "/api/auth/login", {
            "username": "native_details", "password": "NativeDetails@2026"})["user"]
        if not args.ui_only:
            reference = NativeClient(args.reference, app)
            request(reference, "POST", "/api/auth/login", {
                "username": "detailprobe", "password": "DetailProbe@2026"})
        result["comparison_skipped"] = args.ui_only
        for enabled in (() if args.ui_only else (0, 1)):
            path = f"/api/analysis/visualization?ndd_zero={enabled}"
            actual = request(client, "GET", path)
            expected = request(reference, "GET", path)
            review_differences = []
            if actual["increments"] != expected["increments"]:
                differences = []

                def compare(left, right, path="increments"):
                    if len(differences) >= 15:
                        return
                    if isinstance(left, dict) and isinstance(right, dict):
                        for key in sorted(set(left) | set(right)):
                            compare(left.get(key), right.get(key), f"{path}.{key}")
                    elif isinstance(left, list) and isinstance(right, list):
                        if len(left) != len(right):
                            differences.append({"path": path + ".length", "actual": len(left), "expected": len(right)})
                        for index, (a, b) in enumerate(zip(left, right)):
                            compare(a, b, f"{path}[{index}]")
                    elif left != right:
                        differences.append({"path": path, "actual": left, "expected": right})
                assert len(actual["increments"]) == len(expected["increments"])
                aggregate_fields = {"items", "matched", "excluded", "unmatched_history",
                                    "positions", "total", "partial"}
                for left, right in zip(actual["increments"], expected["increments"]):
                    assert len(left["items"]) == len(right["items"])
                    accepted = False
                    for a, b in zip(left["items"], right["items"]):
                        if a == b:
                            continue
                        if a["reason"].startswith("维护状态需人工核查："):
                            assert a["delta"] is None
                            assert a["current"] == b["current"]
                            assert a["previous"] is None
                            assert a["tube"] == b["tube"] and a["ndd_baseline"] == b["ndd_baseline"]
                            review_differences.append({"outage": left["outage"], "tube": a["tube"],
                                                       "native_reason": a["reason"], "trae_delta": b["delta"],
                                                       "trae_previous": b["previous"]})
                            accepted = True
                        else:
                            compare(a, b, f"{left['outage']}/{a['tube']}")
                    if accepted:
                        compare({k: v for k, v in left.items() if k not in aggregate_fields},
                                {k: v for k, v in right.items() if k not in aggregate_fields}, left["outage"])
                        matched = [row for row in left["items"] if row["delta"] is not None]
                        assert left["matched"] == len(matched)
                        assert left["excluded"] == len(left["items"]) - len(matched)
                        assert left["total"] == (sum(row["delta"] for row in matched) if matched else None)
                        positions = Counter()
                        for row in matched:
                            positions[row["position_bucket"]] += row["delta"]
                        assert left["positions"] == dict(positions)
                        assert left["partial"] and left["unmatched_history"] >= right["unmatched_history"]
                    else:
                        compare(left, right, left["outage"])
                result["differences"] = differences
                if differences:
                    raise AssertionError(f"Increment parity: {enabled}")
            result["comparisons"].append({
                "ndd_zero": bool(enabled), "rounds": len(actual["increments"]),
                "matched": sum(row["matched"] for row in actual["increments"]),
                "ndd_baseline": sum(row.get("ndd_baseline", 0) for row in actual["increments"]),
                "trae_equal": actual["increments"] == expected["increments"],
                "equal_except_unconfirmed_maintenance": not result.get("differences"),
                "review_policy_differences": review_differences})
            for site, unit in (("N", 1), ("F", 1), ("H", 2)):
                path = f"/api/analysis/tube-longitudinal?site={site}&unit={unit}&ndd_zero={enabled}"
                assert request(client, "GET", path) == request(reference, "GET", path), path
        for old, new, site, unit in (() if args.ui_only else (
                ("H101", "H102", "H", 1), ("F201", "F202", "F", 2),
                ("F102", "F103", "F", 1), ("H203", "H204", "H", 2))):
            path = f"/api/compare?old={old}&new={new}&unit={unit}"
            actual = request(client, "GET", path)
            expected = request(reference, "GET", path)
            protected = [row for row in actual["items"] if row.get("row_kind") == "indication"
                         and row["comparison"] == "待确认"
                         and row["comparison_note"].startswith(("维护状态需人工核查：", "该管自 "))]
            protected_tubes = {row["thimble_id"] for row in protected}
            if protected:
                assert all(row.get("old_id") is None and row.get("delta_percent") is None for row in protected)
            else:
                assert actual["summary"] == expected["summary"], (new, actual["summary"], expected["summary"])
            actual_items = [row for row in actual["items"] if row["thimble_id"] not in protected_tubes]
            expected_items = [row for row in expected["items"] if row["thimble_id"] not in protected_tubes]
            assert len(actual_items) == len(expected_items), new
            for a, b in zip(actual_items, expected_items):
                for key in ("id", "old_id", "comparison", "comparison_display", "old_source_location",
                            "old_location", "official_evidence", "official_covered_old_id", "row_kind"):
                    assert a.get(key) == b.get(key), (new, a["thimble_id"], key, a.get(key), b.get(key))
            for kind in ("inspection", "comparison"):
                payload = {"kind": kind, "template_id": kind, "site": site,
                           "unit": unit, "outage": new, "old": old if kind == "comparison" else ""}
                actual = request(client, "POST", "/api/reports/preview", payload, timeout=30)
                expected = request(reference, "POST", "/api/reports/preview", payload, timeout=30)
                for key in (("detection_counts", "coverage_complete") if protected and kind == "comparison" else
                            ("values", "rows", "detection_counts", "summary", "coverage_complete",
                             "reference_rows", "reference_page_rows")):
                    assert actual.get(key) == expected.get(key), (new, kind, key)
                if protected and kind == "comparison":
                    actual_values = [row for row in actual["values"] if row[1] not in protected_tubes]
                    expected_values = [row for row in expected["values"] if row[1] not in protected_tubes]
                    assert actual_values == expected_values, (new, "unprotected report values")
                result["reports"].append({"outage": new, "kind": kind, "rows": actual["rows"],
                                          "values_and_reference_cells_equal": not (protected and kind == "comparison"),
                                          "equal_except_protected_tubes": True,
                                          "protected_tubes": sorted(protected_tubes) if kind == "comparison" else []})
        window = NativeMainWindow(client, user)
        window.resize(1480, 940)
        window.show()
        until(app, lambda: window.workbench.model.rowCount() > 0, "source records")
        dialog = window.settings_dialog
        vis = window.stack.widget(3).visualization
        window.nav.setCurrentIndex(2)
        until(app, lambda: bool(vis.data.get("increments")), "initial analytics")
        window.open_settings(2)
        for enabled in (False, True):
            scroll = dialog.stack.currentWidget()
            scroll.ensureWidgetVisible(dialog.ndd_zero)
            wait(app, 100)
            if dialog.ndd_zero.isChecked() != enabled:
                click(dialog.ndd_zero)
            try:
                until(app, lambda: vis.ndd_zero == enabled and bool(vis.data.get("increments"))
                      and all(row["ndd_zero"] == enabled for row in vis.data["increments"]),
                      f"live NDD option {enabled}", 30)
            except AssertionError:
                result["option_diagnostics"] = {
                    "checked": dialog.ndd_zero.isChecked(), "active": vis.ndd_zero,
                    "saved": window.context.preferences.values["ndd_zero"],
                    "rounds": len(vis.data.get("increments") or []),
                    "result_options": [row.get("ndd_zero") for row in vis.data.get("increments") or []],
                    "status": window.stack.widget(3).analysis_status.text(),
                }
                raise
        scroll.ensureWidgetVisible(dialog.point_labels)
        if not dialog.point_labels.isChecked():
            click(dialog.point_labels)
        until(app, lambda: window.context.preferences.values["point_labels"], "point label persistence")
        window.open_settings(0)
        until(app, lambda: dialog.isVisible() and window.settings_page.source_fields["path"].isVisible(),
              "visible database metadata")
        click(window.settings_page.source_copy)
        assert QApplication.clipboard().text() == str(database)
        click(window.settings_page.source_validate)
        until(app, lambda: window.settings_page.source_validate.isEnabled(), "SQLite integrity")
        assert "尚未校验" not in window.settings_page.source_fields["integrity"].text()
        result["settings"] = {"categories": dialog.nav.count(), "database_fields_visible": True,
                              "path_copy": True, "integrity_checked": True, "options_live": True}
        for theme in ("light", "dark"):
            window.context.preferences.save(theme=theme)
            window.apply_preferences()
            for index in (0, 1, 2, 5):
                window.open_settings(index)
                wait(app, 150)
                name = f"settings-{index}-{theme}.png"
                dialog.grab().save(str(work / name))
                result["screens"].append(name)
        dialog.hide()
        window.context.set_scope({"site": "D", "unit": "1", "outage": "D120"})
        window.nav.setCurrentIndex(3)
        reports = window.stack.widget(4)
        until(app, lambda: bool(reports.snapshot_id), "automatic report preview", 30)
        click(reports.count_toggle)
        assert reports.count_panel.isVisible() and reports.count_table.rowCount() == 1
        result["database_statistics"] = reports.count_table.item(0, 1).text()
        click(reports.count_toggle)
        chosen = next(cell["key"] for cell in reports.editable_cells
                      if reports._report_source_text(cell).strip() in ("", "/"))

        def edit(value):
            assert reports.preview_text.locate_cell(chosen)
            table = next(table for table in reports.preview_text.tables
                         if table.currentItem() and table.currentItem().data(Qt.ItemDataRole.UserRole) == chosen)
            item = table.currentItem()
            table.editItem(item)
            until(app, lambda: any(e.isVisible() for e in table.findChildren(QPlainTextEdit)), "native editor")
            editor = next(e for e in table.findChildren(QPlainTextEdit) if e.isVisible())
            editor.setPlainText(value)
            QTest.keyClick(editor, Qt.Key.Key_Return)
            until(app, lambda: bool(reports.snapshot_id), "automatic draft snapshot", 30)

        edit("真实界面草稿\n第二行")
        assert reports._payload()["draft_edits"] == [{"key": chosen, "value": "真实界面草稿\n第二行"}]
        click(reports.edit_draft)
        assert reports.draft_panel.isVisible()
        for width, height, theme in ((1024, 768, "light"), (1480, 940, "dark")):
            window.context.preferences.save(theme=theme)
            window.apply_preferences()
            window.resize(width, height)
            wait(app, 100)
            name = f"report-draft-{width}-{theme}.png"
            window.grab().save(str(work / name))
            result["screens"].append(name)
        restore = next(control for control in reports.draft_entries.findChildren(QPushButton)
                       if control.toolTip() == "恢复该单元格原值")
        click(restore)
        assert reports.draft_edits == []
        until(app, lambda: bool(reports.snapshot_id), "restored report")
        click(reports.draft_undo)
        assert reports.draft_edits == [{"key": chosen, "value": "真实界面草稿\n第二行"}]
        until(app, lambda: bool(reports.snapshot_id), "undo restore report")
        click(reports.draft_reset)
        assert reports.draft_edits == []
        until(app, lambda: bool(reports.snapshot_id), "restore all report")
        result["report"] = {"multiline": True, "automatic_sync": True, "single_restore": True,
                            "undo": True, "all_restore": True, "scope": reports.scope_bar.values()}
        window.context.set_scope({"site": "H", "unit": "2", "outage": "H204"})
        reports.kind.setCurrentIndex(reports.kind.findData("comparison"))
        until(app, lambda: reports.history_combo.findText("H203") >= 0, "H203 history option")
        reports.history_combo.setCurrentIndex(reports.history_combo.findText("H203"))
        until(app, lambda: bool(reports.snapshot_id) and reports.preview_payload.get("old") == "H203"
              and reports.preview_payload.get("outage") == "H204", "comparison warning evidence", 30)
        warning_data = request(client, "POST", "/api/reports/preview", reports._payload(), timeout=30)
        warnings = warning_data.get("warnings") or []
        assert warnings and reports.warnings.groups
        unique_tubes = {"范围" if row.get("thimble_id") is None else f"{row['thimble_id']}号管"
                        for row in warnings}
        assert set(reports.warnings.groups) == unique_tubes
        click(reports.warnings.toggle)
        group = next((entry for entry in reports.warnings.groups.values()
                      if any(row.get("code") == "unmatched_history" for row in entry["warnings"])),
                     next(iter(reports.warnings.groups.values())))
        reports.warnings.scroll.ensureWidgetVisible(group["toggle"])
        click(group["toggle"])
        for width, height, theme in ((1024, 768, "light"), (1480, 940, "dark")):
            window.context.preferences.save(theme=theme)
            window.apply_preferences()
            window.resize(width, height)
            wait(app, 150)
            reports.warnings.scroll.ensureWidgetVisible(group["toggle"])
            name = f"report-warnings-{width}-{theme}.png"
            window.grab().save(str(work / name))
            result["screens"].append(name)
            assert reports.warnings.scroll.height() <= 260
            assert reports.warnings.width() <= reports.width()
        result["warnings"] = {"raw_count": len(warnings), "groups": len(unique_tubes),
                              "expanded": group["toggle"].text(), "native_disclosure": True}

        from qt_shell.native_import import ImportWizard
        from qt_shell.native_windows import DataWorkbench
        from PySide6.QtWidgets import QWizard
        result["import_workspace"] = []
        for width, height, theme in ((900, 700, "light"), (700, 560, "dark")):
            window.context.preferences.save(theme=theme)
            window.apply_preferences()
            wizard = ImportWizard(client, DataWorkbench.MAPPING_FIELDS, {}, window)
            wizard.resize(width, height)
            wizard.show()
            wizard.set_sources([native.parent / "指套管检测数据_按原工作表整理.xlsx"])

            def capture_import(stage):
                wait(app, 120)
                assert wizard.source_tabs.isVisible() and wizard.dock.isVisible()
                assert wizard.dock.geometry().bottom() < wizard.height()
                assert wizard.pages.geometry().bottom() < wizard.dock.geometry().top()
                assert wizard.width() <= width and wizard.height() <= height
                image = wizard.grab().toImage()
                if theme == "dark":
                    assert image.pixelColor(5, 5).lightness() < 128
                name = f"import-{stage}-{width}-{theme}.png"
                image.save(str(work / name))
                result["screens"].append(name)

            capture_import("source")
            click(wizard.button(QWizard.WizardButton.NextButton))
            until(app, lambda: wizard.currentId() == 1, "Excel mapping in native workspace", 60)
            capture_import("mapping")
            wizard.policy.setCurrentIndex(wizard.policy.findData("check"))
            click(wizard.button(QWizard.WizardButton.NextButton))
            until(app, lambda: wizard.currentId() == 2, "Excel workspace preflight", 60)
            capture_import("preflight")
            before = request(client, "GET", "/api/findings?size=1")["total"]
            click(wizard.button(QWizard.WizardButton.NextButton))
            until(app, lambda: wizard.currentId() == 4, "Excel workspace check result", 30)
            assert request(client, "GET", "/api/findings?size=1")["total"] == before
            capture_import("result")
            parsed = wizard.metric_values["parsed"].text()
            assert parsed != "0"
            click(wizard.button(QWizard.WizardButton.FinishButton))
            wizard.deleteLater()
            result["import_workspace"].append({"size": [width, height], "theme": theme,
                                                "parsed": parsed, "check_wrote": 0, "fixed_dock": True})
        result["passed"] = True
    except Exception:
        import traceback
        result["errors"].append(traceback.format_exc())
    finally:
        if window:
            window.close()
            window.deleteLater()
        for candidate in (client, reference):
            if candidate:
                candidate.abort_all()
        wait(app, 50)
        backend.stop()
        (work / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        app.quit()
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
