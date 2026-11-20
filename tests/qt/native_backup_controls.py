"""Exercise a backup row and the validated native recovery confirmation."""

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest


def run(app, window, client, work, request, wait, until):
    settings = window.settings_page
    window.open_settings(5)
    responses = []
    client.mutationFinished.connect(lambda path, data, error: responses.append((path, data, error)))
    wait(app, 100)
    panel = settings.backups
    until(app, lambda: panel.loaded and not panel.reading, "backup list")
    assert settings.backup_now.isVisible() and settings.backup_now.isEnabled()
    assert panel.summary.isVisible()
    QTest.mouseClick(settings.backup_now, Qt.MouseButton.LeftButton)
    until(app, lambda: any(path == "/api/backup" for path, _, _ in responses), "backup button", 40)
    created, error = next((data, error) for path, data, error in responses if path == "/api/backup")
    assert not error, error
    path = created["path"]
    until(app, lambda: panel.loaded and any(row.item.get("path") == path for row in panel.row_widgets),
          "new backup visible")
    finding = request(client, "GET", "/api/findings?raw=1&size=1")["items"][0]
    request(client, "POST", "/api/findings/edit", {"id": finding["id"], "field": "analysis",
            "value": "BEFORE NATIVE RESTORE", "expected_value": finding.get("analysis")})
    selected = next(row for row in panel.row_widgets if row.item.get("path") == path)
    window.settings_dialog.stack.widget(5).ensureWidgetVisible(selected)
    wait(app, 50)
    window.settings_dialog.grab().save(str(work / "screens" / "backup-visible-selection.png"))
    QTest.mouseClick(selected.restore, Qt.MouseButton.LeftButton)
    until(app, lambda: panel.dialog and panel.dialog.validated, "native backup validation", 40)
    dialog = panel.dialog
    assert not dialog.confirm.isEnabled()
    QTest.mouseClick(dialog.ack, Qt.MouseButton.LeftButton)
    assert dialog.confirm.isEnabled()
    QTest.mouseClick(dialog.confirm, Qt.MouseButton.LeftButton)
    until(app, lambda: any(p == "/api/restore" for p, _, _ in responses), "native restore", 45)
    restored, error = next((data, error) for p, data, error in responses if p == "/api/restore")
    assert not error and restored.get("safety_backup"), (restored, error)
    window.settings_dialog.hide()
    return {"backup_path": path, "clicked_row": True, "validated_acknowledgement": True,
            "safety_backup": restored["safety_backup"], "finding_id": finding["id"],
            "original_analysis": finding.get("analysis")}
