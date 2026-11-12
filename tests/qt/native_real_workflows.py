"""Actual native controls against an isolated backend and the supplied files."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch
import zipfile
import xml.etree.ElementTree as ET

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QDialogButtonBox, QFileDialog, QLineEdit, QMessageBox, QPushButton, QWizard,
)


def run(app, window, client, work, scope, request, wait, until):
    from qt_shell.native_import import ImportWizard
    from qt_shell.native_windows import DataWorkbench

    project = Path(__file__).resolve().parents[3]
    result = {}
    def click(widget):
        assert widget.isVisible() and widget.isEnabled(), widget
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
        app.processEvents()

    def choose_excel(policy):
        wizard = ImportWizard(client, DataWorkbench.MAPPING_FIELDS, {}, window)
        wizard.imported.connect(window.workbench._wizard_imported)
        wizard.show()
        wizard.path.setText(str(project / "指套管检测数据_按原工作表整理.xlsx"))
        wait(app, 100)
        click(wizard.button(QWizard.WizardButton.NextButton))
        until(app, lambda: wizard.currentId() == 1, "real Excel recognition", 60)
        assert wizard.source_table.rowCount() > 0
        wizard.policy.setCurrentIndex(wizard.policy.findData(policy))
        click(wizard.button(QWizard.WizardButton.NextButton))
        until(app, lambda: wizard.currentId() == 2, "real Excel preflight", 60)
        assert wizard.preview_table.rowCount() > 0, wizard.preview_summary.text()
        parsed = wizard.result["parsed"]
        click(wizard.button(QWizard.WizardButton.NextButton))
        until(app, lambda: wizard.currentId() == 4, "real Excel commit", 60)
        assert not wizard.retry.isVisible(), wizard.result_summary.text()
        data = dict(wizard.result)
        data["preflight_parsed"] = parsed
        wizard.grab().save(str(work / "screens" / f"excel-{policy}.png"))
        click(wizard.button(QWizard.WizardButton.FinishButton))
        wizard.deleteLater()
        return data

    before = request(client, "GET", "/api/findings?size=1")["total"]
    checked = choose_excel("check")
    assert checked["check_only"] is True
    assert request(client, "GET", "/api/findings?size=1")["total"] == before
    first = choose_excel("review")
    second = choose_excel("review")
    assert second["inserted"] == 0, second
    assert second["skipped"] > 0, second
    result["excel"] = {"check_parsed": checked["preflight_parsed"], "check_wrote": 0,
                       "first_inserted": first["inserted"], "repeat_inserted": second["inserted"],
                       "repeat_skipped": second["skipped"]}
    queue = ImportWizard(client, DataWorkbench.MAPPING_FIELDS, {}, window)
    queue.show()
    queue.set_sources([project / "指套管检测数据_按原工作表整理.xlsx",
                       project / "指套管检测数据_按原工作表整理_已核对.xlsx"])
    click(queue.button(QWizard.WizardButton.NextButton))
    until(app, lambda: queue.currentId() == 1, "two real workbook recognition", 60)
    click(queue.button(QWizard.WizardButton.NextButton))
    until(app, lambda: queue.currentId() == 2, "two real workbook preflight", 90)
    assert len(queue.result["files"]) == 2
    assert all(payload.get("expected_sha256") for payload in queue._batch_payloads)
    expected_parsed = queue.result["parsed"]
    click(queue.button(QWizard.WizardButton.NextButton))
    until(app, lambda: queue.currentId() == 4, "two real workbook commit", 90)
    assert not queue.retry.isVisible(), queue.result_summary.text()
    assert len(queue.result["files"]) == 2
    assert all(row.get("batch_id") for row in queue.result["files"])
    assert queue.result["parsed"] == expected_parsed
    result["excel_queue"] = {"files": 2, "parsed": expected_parsed,
                             "inserted": queue.result["inserted"], "skipped": queue.result["skipped"],
                             "per_file_hash_checked": True,
                             "batch_ids": [row["batch_id"] for row in queue.result["files"]]}
    click(queue.button(QWizard.WizardButton.FinishButton))
    queue.deleteLater()
    rpt_dir = (project / "02_项目原始资料" / "03_原始检测数据" / "测试数据" /
               "指套管数据1" / "H209" / "数据" / "2.3 指套管")
    directory_runs = []
    for attempt in range(2):
        wizard = ImportWizard(client, DataWorkbench.MAPPING_FIELDS, {"report_policy": "latest"}, window,
                              mode="directory")
        wizard.show()
        wizard.path.setText(str(rpt_dir))
        wait(app, 100)
        click(wizard.button(QWizard.WizardButton.NextButton))
        until(app, lambda: wizard.currentId() == 1, "real RPT candidates", 60)
        assert len(wizard.group_controls) >= 1, wizard.mapping_note.text()
        if attempt == 0:
            count_before = request(client, "GET", "/api/findings?size=1")["total"]
            output = work / "rpt-standard-only.xlsx"
            with patch.object(QFileDialog, "getSaveFileName", return_value=(str(output), "Excel (*.xlsx)")):
                click(wizard.directory_export)
                until(app, lambda: output.is_file(), "RPT standard Excel only", 60)
            with zipfile.ZipFile(output) as archive:
                namespace = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                workbook = ET.fromstring(archive.read("xl/workbook.xml"))
                sheets = [sheet.get("name") for sheet in workbook.findall("s:sheets/s:sheet", namespace)]
                data_rows = sum(max(0, len(ET.fromstring(archive.read(name)).findall(
                    "s:sheetData/s:row", namespace)) - 1) for name in archive.namelist()
                    if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"))
                assert data_rows >= 123, (sheets, data_rows)
                import base64
                import zlib
                properties = ET.fromstring(archive.read("docProps/custom.xml"))
                encoded = next("".join(prop.itertext()) for prop in properties
                               if prop.get("name") == "ThimbleRPTMetadataV2")
                metadata = json.loads(zlib.decompress(base64.b64decode(encoded)))
                assert metadata["version"] == 2
                assert any(row.get("RPT SHA-256") and row.get("SUM SHA-256")
                           for row in metadata["confirmation"])
            assert request(client, "GET", "/api/findings?size=1")["total"] == count_before
            result["rpt_standard_only"] = {"saved": True, "sheets": sheets,
                                           "data_rows": data_rows, "metadata_hashes_retained": True,
                                           "findings_unchanged": True}
        click(wizard.button(QWizard.WizardButton.NextButton))
        until(app, lambda: wizard.currentId() == 2, "real RPT preflight", 60)
        assert wizard.preview_table.rowCount() > 0
        click(wizard.button(QWizard.WizardButton.NextButton))
        until(app, lambda: wizard.currentId() == 4, "real RPT commit", 60)
        assert not wizard.retry.isVisible(), wizard.result_summary.text()
        directory_runs.append(dict(wizard.result))
        click(wizard.button(QWizard.WizardButton.FinishButton))
        wizard.deleteLater()
    assert directory_runs[1]["inserted"] == 0
    assert directory_runs[1]["skipped"] > 0
    result["rpt"] = {"groups": len(wizard.group_controls), "first_inserted": directory_runs[0]["inserted"],
                     "repeat_inserted": directory_runs[1]["inserted"],
                     "repeat_skipped": directory_runs[1]["skipped"]}

    reports = window.stack.widget(4)
    window.nav.setCurrentIndex(window._navigation_indices.index(4))
    window.context.set_scope(scope)
    wait(app, 200)
    header_path = project / "宁德核电厂_报告表头设置.json"
    expected_header = json.loads(header_path.read_text(encoding="utf-8-sig"))["fields"]
    reports.edit_header()
    with patch.object(QFileDialog, "getOpenFileName", return_value=(str(header_path), "JSON (*.json)")):
        click(reports.import_header_button)
    reports.edit_header()
    assert reports.header_values == expected_header
    assert reports._load_saved_header() == expected_header
    click(reports.preview)
    until(app, lambda: bool(reports.snapshot_id), "report with supplied header")
    preview = reports.preview_text
    chosen = None
    for table in preview.tables:
        assert sum(table.columnWidth(c) for c in range(table.columnCount())) <= table.width()
        for row in range(table.rowCount()):
            for column in range(table.columnCount()):
                item = table.item(row, column)
                if item and item.flags() & Qt.ItemFlag.ItemIsEditable and item.text().strip() == "/":
                    chosen = (table, item)
                    break
            if chosen:
                break
        if chosen:
            break
    assert chosen, "No editable report cell"
    table, item = chosen
    rect = table.visualItemRect(item)
    point = table.viewport().mapTo(preview.host, rect.center())
    preview.ensureVisible(point.x(), point.y(), 30, 30)
    wait(app, 100)
    QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    QTest.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    until(app, lambda: any(e.isVisible() for e in table.findChildren(QLineEdit)), "native inline cell editor")
    editor = next(e for e in table.findChildren(QLineEdit) if e.isVisible())
    editor.setText("NATIVE_UI_VERIFIED")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    until(app, lambda: bool(reports.draft_edits), "inline draft")
    assert reports.snapshot_id is None
    save = next(b for b in reports.findChildren(QPushButton) if b.text() == "保存修改并更新预览")
    click(save)
    until(app, lambda: bool(reports.snapshot_id), "edited report snapshot")
    assert any(e["value"] == "NATIVE_UI_VERIFIED" for e in reports.preview_payload["draft_edits"])
    exports = []
    def exported(path, data, error):
        if path == "/api/reports/export":
            assert not error, error
            exports.append(data)
    client.requestFinished.connect(exported)
    try:
        for fmt in ("docx", "xlsx"):
            reports.export_format.setCurrentIndex(reports.export_format.findData(fmt))
            with patch.object(QMessageBox, "information", return_value=QMessageBox.StandardButton.Ok):
                count = len(exports)
                click(reports.export)
                until(app, lambda: len(exports) > count, f"edited {fmt} export", 30)
            output = Path(exports[-1]["file_path"])
            assert output.is_file()
            with zipfile.ZipFile(output) as archive:
                names = ["word/document.xml"] if fmt == "docx" else [
                    name for name in archive.namelist()
                    if name == "xl/sharedStrings.xml" or name.startswith("xl/worksheets/sheet")]
                text = "\n".join("".join(ET.fromstring(archive.read(name)).itertext()) for name in names)
            assert "NATIVE_UI_VERIFIED" in text, f"{fmt} lost inline draft"
            missing = [value for value in expected_header.values() if value and value not in text]
            assert not missing, (fmt, missing)
            copy = work / f"report-copy.{fmt}"
            with patch.object(QFileDialog, "getSaveFileName", return_value=(str(copy), "")):
                click(reports.export_copy)
                until(app, lambda: copy.is_file(), f"{fmt} save copy")
            assert copy.read_bytes() == output.read_bytes(), f"{fmt} copy differs"
        result["report"] = {"header_fields": len(expected_header), "persisted": True,
                            "inline_edit": True, "docx_and_xlsx_match": True,
                            "save_copy_matches": True}
    finally:
        client.requestFinished.disconnect(exported)
    return result
