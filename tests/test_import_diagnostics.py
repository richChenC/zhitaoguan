import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from openpyxl import Workbook
from src.backend import server, import_audit


class ImportDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, value in (("DB_PATH", self.root / "test.db"),
                            ("LOG_PATH", self.root / "service.log")):
            patcher = patch.object(server, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        server.init_db()
        self.source = self.root / "import.xlsx"
        book = Workbook()
        book.active.append(["大修号", "机组号", "通道编号", "幅值", "三字码"])
        book.active.append(["H209", 2, 1, 3.5, "WAR"])
        book.save(self.source)
        book.close()

    def test_low_space_stops_before_backup_batch_or_record_writes(self):
        usage = type("Usage", (), {"free": 0})()
        with patch.object(server.shutil, "disk_usage", return_value=usage), \
                patch.object(server, "_auto_backup") as backup:
            with self.assertRaisesRegex(ValueError, "磁盘空间不足"):
                server.import_excel_file(str(self.source))
        backup.assert_not_called()
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM findings").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM import_batches").fetchone()[0], 0)

    def test_failed_transaction_is_rolled_back_and_response_points_to_exact_batch(self):
        with patch.object(import_audit, "finding_source",
                          side_effect=sqlite3.OperationalError("database or disk is full")):
            with self.assertRaises(sqlite3.OperationalError) as caught:
                server.import_excel_file(str(self.source))
        payload = server.import_error_response(str(self.source), caught.exception)
        self.assertIn("磁盘空间不足", payload["error"])
        self.assertIn(str(payload["batch_id"]), payload["details_url"])
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM findings").fetchone()[0], 0)
            batch = db.execute("SELECT status,note FROM import_batches WHERE id=?",
                               (payload["batch_id"],)).fetchone()
            self.assertEqual(batch["status"], "failed")
            self.assertIn("disk is full", batch["note"])
        result = server.import_excel_file(str(self.source))
        self.assertEqual(result["inserted"], 1)
        self.assertNotEqual(result["batch_id"], payload["batch_id"])
        self.assertNotIn("batch_id", server.import_error_response(
            str(self.source), ValueError("文件无法读取")))

    def test_failed_read_only_check_never_falls_back_to_writing(self):
        with patch.object(server, "open_excel_workbook",
                          side_effect=ValueError("文件损坏")) as opener, \
                patch.object(server, "_auto_backup") as backup:
            with self.assertRaisesRegex(ValueError, "文件损坏"):
                server.import_excel_file(str(self.source))
        self.assertEqual(opener.call_count, 1)
        backup.assert_not_called()

    def test_failure_audit_error_does_not_replace_original_import_error(self):
        failure = sqlite3.OperationalError("database or disk is full")
        with patch.object(import_audit, "finding_source", side_effect=failure), \
                patch.object(import_audit, "issue",
                             side_effect=sqlite3.OperationalError("audit unavailable")), \
                patch.object(server.LOGGER, "exception"):
            with self.assertRaises(sqlite3.OperationalError) as caught:
                server.import_excel_file(str(self.source))
        self.assertIs(caught.exception, failure)
        self.assertNotIn("batch_id", server.import_error_response(str(self.source), failure))

    def test_service_log_returns_bounded_recent_lines(self):
        server.LOG_PATH.write_text("old\n" * 50000 + "import error\nlast line\n", encoding="utf-8")
        result = server.recent_service_log(2)
        self.assertEqual(result["lines"], ["import error", "last line"])
        self.assertEqual(result["path"], str(server.LOG_PATH))
        self.assertLessEqual(len(server.recent_service_log(10000)["lines"]), 500)

    def test_full_disk_during_response_audit_preserves_actionable_import_failure(self):
        handler = Mock(wfile=io.BytesIO(), auth_cookie=None)
        payload = server.import_error_response(
            str(self.source), sqlite3.OperationalError("database or disk is full"))
        with patch.object(server.local_security, "audit_response",
                          side_effect=sqlite3.OperationalError("database or disk is full")), \
                patch.object(server.LOGGER, "exception"):
            server.Handler.json_response(handler, payload, 500)
        handler.send_response.assert_called_once_with(500)
        self.assertEqual(json.loads(handler.wfile.getvalue()), payload)

    def test_success_response_still_requires_audit_to_succeed(self):
        with patch.object(server.local_security, "audit_response",
                          side_effect=sqlite3.OperationalError("database or disk is full")):
            with self.assertRaises(sqlite3.OperationalError):
                server.Handler.json_response(Mock(), {"ok": True}, 200)


if __name__ == "__main__":
    unittest.main()
