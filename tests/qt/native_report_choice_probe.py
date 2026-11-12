"""Real RPT companion-window controls on a read-only snapshot of business data."""
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import sys
from unittest.mock import patch

from native_desktop_workflow import request, until, wait


def main():
    native = Path(__file__).resolve().parents[2]
    work = native.parent / "05_测试与验证/03_自动化临时产物" / (
        "native-report-choice-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
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
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QWidget, QWizard
    from qt_shell.backend_service import BackendService
    from qt_shell.log_utils import ServiceLog
    from qt_shell.native_client import NativeClient
    from qt_shell.native_components import workspace_styles
    from qt_shell.native_import import ImportWizard
    from qt_shell.native_windows import DataWorkbench

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    backend = BackendService(ServiceLog(work / "service.log"))
    result = {"passed": False, "errors": [], "screens": []}
    host = wizard = client = None
    try:
        client = NativeClient(backend.start(), app)
        request(client, "POST", "/api/auth/setup", {
            "username": "rptprobe", "display_name": "RPT Probe", "password": "RptProbe@2026"})
        request(client, "POST", "/api/auth/login", {"username": "rptprobe", "password": "RptProbe@2026"})
        before = request(client, "GET", "/api/findings?size=1")["total"]
        host = QWidget()
        host.setStyleSheet(workspace_styles("light"))
        wizard = ImportWizard(client, DataWorkbench.MAPPING_FIELDS, {"report_policy": "latest"},
                              host, mode="directory")
        wizard.show()
        wizard.path.setText(str(native.parent / "02_项目原始资料/03_原始检测数据/测试数据"
                                / "指套管数据1/H209/数据/2.3 指套管"))
        QTest.mouseClick(wizard.button(QWizard.WizardButton.NextButton), Qt.MouseButton.LeftButton)
        until(app, lambda: wizard.currentId() == 1 and wizard.report_choice
              and wizard.report_choice.isVisible(), "real report chooser", 90)
        choice = wizard.report_choice
        count = len(choice.groups)
        assert count > 1
        assert all(choice.selected) and not choice.confirmed and not choice.complete
        assert not wizard.directory_export.isEnabled()
        labels = choice.option_host.findChildren(QLabel)
        assert any(label.objectName() == "reportAnalystHeading" and "分析人员" in label.text() for label in labels)
        assert all(label.textFormat() == Qt.TextFormat.PlainText for label in labels)
        for width, height, theme in ((700, 640, "light"), (460, 500, "dark")):
            host.setStyleSheet(workspace_styles(theme))
            choice.resize(width, height)
            wait(app, 200)
            assert choice.confirm.isVisible() and choice.confirm.isEnabled()
            assert choice.confirm.geometry().bottom() < choice.height()
            assert choice.options_scroll.horizontalScrollBar().maximum() == 0
            name = f"report-choice-{width}-{theme}.png"
            assert choice.grab().save(str(work / name))
            result["screens"].append(name)
        QTest.mouseClick(choice.confirm, Qt.MouseButton.LeftButton)
        assert choice.confirmed == {0}
        choice.reject()
        assert not choice.isVisible()
        QTest.mouseClick(wizard.choose_reports, Qt.MouseButton.LeftButton)
        wait(app, 100)
        assert choice.isVisible() and choice.confirmed == {0}
        choice.show_group(0)
        for index in range(count):
            assert choice.index == index
            QTest.mouseClick(choice.confirm, Qt.MouseButton.LeftButton)
        assert choice.complete and not choice.isVisible()
        assert wizard.directory_export.isEnabled()
        paths = [row["path"] for row in choice.selected]
        assert wizard.prepare_payload()
        assert wizard.payload["reports"] == paths
        assert all(row["sha256"] for row in wizard.payload["report_confirmation"]["candidates"])
        result["selection"] = {"groups": count, "confirmed": len(choice.confirmed),
                               "analysts": [row.get("analysts") for row in choice.selected],
                               "records": sum(row.get("records", 0) for row in choice.selected),
                               "cancel_resume_preserved": True, "hashes_retained": True}
        name = "report-choice-summary.png"
        assert wizard.grab().save(str(work / name))
        result["screens"].append(name)
        export = work / "standard-only.xlsx"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(export), "Excel (*.xlsx)")):
            QTest.mouseClick(wizard.directory_export, Qt.MouseButton.LeftButton)
            until(app, export.is_file, "confirmed standard workbook", 60)
        wizard.policy.setCurrentIndex(wizard.policy.findData("check"))
        QTest.mouseClick(wizard.button(QWizard.WizardButton.NextButton), Qt.MouseButton.LeftButton)
        until(app, lambda: wizard.currentId() == 2, "RPT preflight", 60)
        parsed = wizard.result["parsed"]
        QTest.mouseClick(wizard.button(QWizard.WizardButton.NextButton), Qt.MouseButton.LeftButton)
        until(app, lambda: wizard.currentId() == 4, "check-only RPT workflow", 60)
        assert wizard.result["check_only"]
        assert request(client, "GET", "/api/findings?size=1")["total"] == before
        result["standard_export"] = {"bytes": export.stat().st_size, "parsed": parsed,
                                     "check_only": True, "findings_unchanged": True}
        result["passed"] = True
    except Exception as exc:
        result["errors"].append(str(exc))
        import traceback
        traceback.print_exc()
    finally:
        if wizard:
            wizard.close()
            wizard.deleteLater()
        if host:
            host.close()
            host.deleteLater()
        if client:
            client.abort_all()
        wait(app, 100)
        backend.stop()
        logs = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in work.rglob("*.log"))
        if "Traceback" in logs:
            result["passed"] = False
            result["errors"].append("backend traceback")
        (work / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
