"""Single-tube CSV exports retain original measurements and server audit evidence."""
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from src.backend import server, local_security


class TubeHistoryExportTests(unittest.TestCase):
    def setUp(self):
        artifact_root = Path(__file__).resolve().parents[2] / "05_测试与验证/03_自动化临时产物"
        artifact_root.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="history-export-unit-", dir=artifact_root)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        patcher = patch.multiple(server, DB_PATH=self.root / "data.db", EXCEL_DIR=self.root / "excel")
        patcher.start()
        self.addCleanup(patcher.stop)
        server.init_db()

    def test_export_uses_actual_records_preserves_zero_and_audits_scope(self):
        history = {"unit_code": "N1", "tubes": [{"tube": 2, "position": "G14", "series": [
            {"outage": "N101", "generation": 1, "conclusion": "WAR", "state_label": "移位 · 待核对",
             "current_events": ["shifted"], "max_depth": 0, "findings": [
                 {"id": 9, "location": "P3+12", "indication": "WAR", "percent": 0,
                  "channel": "P3", "source": "原始.rpt"},
                 {"id": 10, "location": "P5", "indication": "WAR", "percent": 40,
                  "channel": "P5", "source": "=UNTRUSTED()"}]},
            {"outage": "N102", "generation": 2, "conclusion": "无检测记录", "state_label": "换管",
             "current_events": ["replaced"], "findings": []},
        ]}]}
        with patch.object(server, "tube_longitudinal", return_value=history) as query, \
                local_security.identity({"username": "exporter", "id": "account-id"}):
            result = server.export_tube_history({"site": "N", "unit": 1, "tube": 2, "ndd_zero": False})
        query.assert_called_once_with("N", 1, ndd_zero=False)
        content = Path(result["file_path"]).read_bytes()
        self.assertTrue(content.startswith(b"\xef\xbb\xbf"))
        rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["磨损深度(%)"], "0")
        self.assertEqual(rows[1]["磨损深度(%)"], "40")
        self.assertEqual(rows[1]["数据文件"], "'=UNTRUSTED()")
        self.assertEqual(rows[2]["维护事件"], "换管")
        self.assertEqual(rows[2]["磨损深度(%)"], "")
        evidence = json.loads(Path(result["provenance_file_path"]).read_text(encoding="utf-8"))
        self.assertEqual(evidence["finding_ids"], [9, 10])
        self.assertEqual(evidence["operator"], "exporter")
        self.assertEqual((evidence["site"], evidence["unit"], evidence["tube"]), ("N", 1, 2))
        with server.connect() as db:
            record = db.execute("SELECT * FROM report_exports WHERE id=?", (result["export_audit_id"],)).fetchone()
            self.assertEqual(record["export_kind"], "tube_history")
        self.assertEqual(list(self.root.rglob("*.tmp")), [])

    def test_invalid_scope_and_ndd_options_cannot_create_files(self):
        for payload in ({"site": "..", "unit": 1, "tube": 1}, {"site": "N", "unit": 1, "tube": 51},
                        {"site": "N", "unit": 0, "tube": 1},
                        {"site": "N", "unit": 1.5, "tube": 1},
                        {"site": "N", "unit": True, "tube": 1},
                        {"site": "N", "unit": 1, "tube": 1, "ndd_zero": "false"}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                server.export_tube_history(payload)
        self.assertFalse((self.root / "excel").exists())
        self.assertEqual(local_security.POST_PERMISSIONS["/api/analysis/tube-history/export"], "export.create")

    def test_disconnected_json_reader_is_not_retried_as_a_second_response(self):
        for failure in (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            handler = Mock()
            handler.auth_cookie = None
            handler.wfile.write.side_effect = failure()
            with patch.object(local_security, "audit_response"):
                server.Handler.json_response(handler, {"data": "completed"})
            self.assertIs(handler.close_connection, True)
            handler.send_response.assert_called_once_with(200)
        handler = Mock()
        handler.auth_cookie = None
        handler.wfile.write.side_effect = OSError("unrelated error")
        with patch.object(local_security, "audit_response"), self.assertRaises(OSError):
            server.Handler.json_response(handler, {})


if __name__ == "__main__":
    unittest.main()
