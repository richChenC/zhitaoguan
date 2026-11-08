"""Exercise filtered backup selection and the native recovery confirmation."""
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialogButtonBox, QLineEdit, QMessageBox


def run(app, window, client, work, request, wait, until):
    settings = window.settings_page
    window.open_settings(5)
    responses = []
    client.mutationFinished.connect(lambda path, data, error: responses.append((path, data, error)))
    errors, confirmed = [], []
    wait(app, 100)
    assert settings.backup_now.isVisible() and settings.backup_now.isEnabled()
    assert settings.restore_backup.isVisible() and settings.restore_backup.isEnabled()
    assert settings.backups.table.isVisible()
    with patch.object(QMessageBox, "information", return_value=QMessageBox.StandardButton.Ok), \
            patch.object(QMessageBox, "warning", side_effect=lambda *args: errors.append(str(args[-1]))):
        QTest.mouseClick(settings.backup_now, Qt.MouseButton.LeftButton)
        until(app, lambda: any(path == "/api/backup" for path, _, _ in responses), "backup button", 40)
        created, error = next((data, error) for path, data, error in responses if path == "/api/backup")
        assert not error, error
        path = created["path"]
        until(app, lambda: any(row.get("path") == path for row in settings.backups.model.rows),
              "new backup visible")
        finding = request(client, "GET", "/api/findings?raw=1&size=1")["items"][0]
        request(client, "POST", "/api/findings/edit", {"id": finding["id"], "field": "analysis",
                "value": "BEFORE NATIVE RESTORE", "expected_value": finding.get("analysis")})
        settings.backups.search.setText(Path(path).name)
        assert len(settings.backups.model.rows) == 1
        settings.backups.table.selectRow(0)
        window.settings_dialog.grab().save(str(work / "screens" / "backup-visible-selection.png"))
        def confirm_restore():
            dialog = app.activeModalWidget()
            if dialog is None:
                QTimer.singleShot(50, confirm_restore)
                return
            dialog.findChild(QLineEdit).setText("恢复数据库")
            confirmed.append(True)
            QTest.mouseClick(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok),
                             Qt.MouseButton.LeftButton)
        QTimer.singleShot(70, confirm_restore)
        QTest.mouseClick(settings.restore_backup, Qt.MouseButton.LeftButton)
        until(app, lambda: any(p == "/api/restore" for p, _, _ in responses), "native restore", 45)
        restored, error = next((data, error) for p, data, error in responses if p == "/api/restore")
        assert not error and restored.get("safety_backup"), (restored, error)
        assert confirmed and not errors, errors
        window.settings_dialog.hide()
    return {"backup_path": path, "filtered_selected": True, "typed_confirmation": True,
            "safety_backup": restored["safety_backup"], "finding_id": finding["id"],
            "original_analysis": finding.get("analysis")}
