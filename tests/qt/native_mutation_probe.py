"""Fast focused rerun of actual mutation controls, always on a copied database."""
from __future__ import annotations

from datetime import datetime
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys

from native_desktop_workflow import request, wait


def main():
    project = Path(__file__).resolve().parents[2]
    source = Path(sys.argv[1]).resolve()
    work = project.parent / "05_测试与验证" / "03_自动化临时产物" / (
        "native-mutations-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    (work / "screens").mkdir(parents=True)
    database = work / "data.db"
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src, closing(sqlite3.connect(database)) as dst:
        src.backup(dst)
        dst.executescript("DELETE FROM login_sessions; DELETE FROM user_roles; DELETE FROM users; DELETE FROM restore_points;")
        dst.commit()
    for key, value in {"THIMBLE_QT_TEST_DATA_ROOT": work, "THIMBLE_ALLOW_MULTI_INSTANCE": "1",
                       "THIMBLE_DB_PATH": database, "QSG_RENDER_LOOP": "basic"}.items():
        os.environ[key] = str(value)
    sys.path.insert(0, str(project))
    from PySide6.QtWidgets import QApplication
    from qt_shell.backend_service import BackendService
    from qt_shell.log_utils import ServiceLog
    from qt_shell.native_client import NativeClient
    from qt_shell.native_windows import NativeMainWindow
    from native_desktop_workflow import until
    from native_mutation_workflows import run, run_state_import
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    backend = BackendService(ServiceLog(work / "service.log"))
    window = client = None
    result = {}
    try:
        client = NativeClient(backend.start(), app)
        request(client, "POST", "/api/auth/setup",
                {"username": "mutationprobe", "display_name": "Mutation Probe", "password": "MutationProbe@2026"})
        user = request(client, "POST", "/api/auth/login",
                       {"username": "mutationprobe", "password": "MutationProbe@2026"})["user"]
        window = NativeMainWindow(client, user)
        window.show()
        wait(app, 1800)
        scope = {"site": "H", "unit": "2", "outage": "H209"}
        if "--backup-controls" in sys.argv:
            from native_backup_controls import run as backup_controls
            result["backup_controls"] = backup_controls(app, window, client, work, request, wait, until)
            expired = {}
            client.get("/api/auth/me", lambda data, error: expired.update(error=error))
            until(app, lambda: "error" in expired, "expired session")
            assert expired["error"], expired
            request(client, "POST", "/api/auth/login",
                    {"username": "mutationprobe", "password": "MutationProbe@2026"})
            restored = request(client, "GET", "/api/findings?raw=1&size=1")["items"][0]
            assert restored["id"] == result["backup_controls"]["finding_id"]
            assert restored.get("analysis") == result["backup_controls"]["original_analysis"]
            result["backup_controls"].update(old_session_rejected=True, changed_value_restored=True)
        elif "--state-import" in sys.argv:
            result["states"] = run_state_import(app, window, client, work, request, wait, until)
        else:
            result["controls"] = run(app, window, client, work, scope, request, wait, until)
        result["passed"] = True
    except Exception:
        import traceback
        result.update(passed=False, error=traceback.format_exc())
    finally:
        if window:
            window.close()
            window.deleteLater()
        if client:
            client.abort_all()
        wait(app, 50)
        backend.stop()
        (work / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())
