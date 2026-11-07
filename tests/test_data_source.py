from enterprise_fixtures import admin_cookie
"""Settings, non-connecting server profiles, and SQLite compatibility checks."""
import hashlib
from http.client import HTTPConnection
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from src.backend import data_source, server


class DataSourceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db_path = Path(self.directory.name) / "nested" / "test.db"

    def make_db(self):
        with data_source.SQLiteProvider(self.db_path).connect() as db:
            db.executescript("CREATE TABLE findings(id INTEGER); CREATE TABLE tube_states(id INTEGER);")
            db.execute("INSERT INTO findings VALUES(7)")

    def test_default_settings_do_not_create_database_or_config(self):
        result = data_source.settings(self.db_path)
        self.assertEqual(result["active"]["mode"], "local")
        self.assertEqual(result["active"]["engine"], "sqlite")
        self.assertFalse(result["active"]["exists"])
        self.assertEqual(result["active"]["size_bytes"], 0)
        self.assertEqual(result["capabilities"], {"local": True, "server": False})
        self.assertEqual(result["warnings"], [])
        self.assertFalse(self.db_path.parent.exists())

    def test_profile_is_persisted_atomically_next_to_selected_database(self):
        profile = {"server_url": "https://api.example.com/v1", "timeout_seconds": 23,
                   "source_directory": r"D:\资料\历史数据"}
        saved = data_source.save_settings(self.db_path, {"profile": profile})
        self.assertEqual(saved["profile"], profile)
        self.assertEqual(data_source.settings(self.db_path)["profile"], profile)
        self.assertEqual(list(self.db_path.parent.glob(".data-source-*")), [])
        self.assertFalse(self.db_path.exists())
        other = Path(self.directory.name) / "other" / "db.sqlite"
        self.assertEqual(data_source.settings(other)["profile"], data_source.DEFAULT_PROFILE)

    def test_partial_profile_updates_preserve_other_fields(self):
        data_source.save_settings(self.db_path, {"server_url": "http://localhost:8080/api"})
        result = data_source.save_settings(self.db_path, {"profile": {"timeout_seconds": 15}})
        self.assertEqual(result["profile"]["server_url"], "http://localhost:8080/api")
        self.assertEqual(result["profile"]["timeout_seconds"], 15)

    def test_active_database_cannot_be_switched_by_saved_settings(self):
        for payload in ({"active": {"mode": "online"}}, {"mode": "online"},
                        {"profile": {}, "active": {"path": "other.db"}},
                        {"profile": {"password": "sensitive"}}):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    data_source.save_settings(self.db_path, payload)
        self.assertFalse(self.db_path.parent.exists())

    def test_invalid_profiles_are_rejected_without_password_echo(self):
        for url in (
            "file:///D:/db.sqlite", "javascript:alert(1)", "postgres://host/db",
            "https://user:secret@host/api", "https://host/api?password=secret",
            "https://host/#secret", "https://host:99999", "https://bad host/api",
            "https://host\\@evil/api", "https://host?", "https://host#",
            "https://", "https://bad%40host/api",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError) as raised:
                    data_source.save_settings(self.db_path, {"server_url": url})
                self.assertNotIn("secret", str(raised.exception))
        for timeout in (0, 121, True, "10", 1.5):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError):
                    data_source.save_settings(self.db_path, {"timeout_seconds": timeout})

    def test_valid_server_urls_cover_lan_ipv6_and_unicode_hosts(self):
        for url in ("http://127.0.0.1:8080/api", "https://[::1]:443/v1",
                    "https://server.local/api", "https://业务.example/api"):
            with self.subTest(url=url):
                self.assertEqual(data_source.normalize_profile({"server_url": url})["server_url"], url)

    def test_damaged_configuration_is_reported_and_never_overwritten(self):
        path = data_source.config_path(self.db_path)
        path.parent.mkdir(parents=True)
        for content in (b"{bad", b"[]", b'{"schema_version":99,"profile":{}}',
                        b'{"schema_version":1,"profile":{"server_url":"file:///db"}}'):
            with self.subTest(content=content):
                path.write_bytes(content)
                result = data_source.settings(self.db_path)
                self.assertEqual(len(result["warnings"]), 1)
                self.assertEqual(result["profile"], data_source.DEFAULT_PROFILE)
                with self.assertRaises(ValueError):
                    data_source.save_settings(self.db_path, {"profile": {}})
                self.assertEqual(path.read_bytes(), content)

    def test_atomic_replace_failure_keeps_previous_config_and_cleans_temp(self):
        data_source.save_settings(self.db_path, {"timeout_seconds": 11})
        original = data_source.config_path(self.db_path).read_bytes()
        with patch.object(data_source.os, "replace", side_effect=OSError("locked")):
            with self.assertRaises(OSError):
                data_source.save_settings(self.db_path, {"timeout_seconds": 12})
        self.assertEqual(data_source.config_path(self.db_path).read_bytes(), original)
        self.assertEqual(list(self.db_path.parent.glob(".data-source-*")), [])

    def test_provider_preserves_row_factory_pragmas_and_closing_context(self):
        provider = data_source.SQLiteProvider(self.db_path)
        with provider.connect() as db:
            self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(db.execute("PRAGMA busy_timeout").fetchone()[0], 10000)
            self.assertEqual(db.execute("PRAGMA synchronous").fetchone()[0], 1)
            self.assertEqual(db.execute("PRAGMA temp_store").fetchone()[0], 2)
            self.assertEqual(db.execute("PRAGMA cache_size").fetchone()[0], -16000)
            db.execute("CREATE TABLE sample(value INTEGER)")
            db.execute("INSERT INTO sample VALUES(3)")
            self.assertEqual(db.execute("SELECT value FROM sample").fetchone()["value"], 3)
        with self.assertRaises(sqlite3.ProgrammingError):
            db.execute("SELECT 1")

    def test_provider_rolls_back_and_closes_failed_transactions(self):
        self.make_db()
        with self.assertRaises(RuntimeError):
            with data_source.SQLiteProvider(self.db_path).connect() as db:
                db.execute("INSERT INTO findings VALUES(99)")
                raise RuntimeError("rollback")
        with data_source.SQLiteProvider(self.db_path).connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM findings").fetchone()[0], 1)

    def test_local_validation_does_not_create_missing_database(self):
        result = data_source.validate_settings(self.db_path, {"target": "local"})
        self.assertFalse(result["ok"])
        self.assertFalse(result["connected"])
        self.assertFalse(self.db_path.parent.exists())

    def test_local_validation_is_read_only_and_checks_business_schema(self):
        self.make_db()
        before = hashlib.sha256(self.db_path.read_bytes()).hexdigest()
        result = data_source.validate_settings(self.db_path, {"target": "local"})
        self.assertTrue(result["ok"])
        self.assertTrue(result["connected"])
        self.assertEqual(result["checks"], {"exists": True, "read_only": True,
                                          "integrity": True, "missing_tables": []})
        self.assertEqual(hashlib.sha256(self.db_path.read_bytes()).hexdigest(), before)
        self.assertFalse(data_source.config_path(self.db_path).exists())

    def test_non_application_sqlite_and_invalid_files_do_not_pass(self):
        self.db_path.parent.mkdir(parents=True)
        with sqlite3.connect(self.db_path, factory=data_source.ClosingConnection) as db:
            db.execute("CREATE TABLE unrelated(id INTEGER)")
        result = data_source.validate_settings(self.db_path, {})
        self.assertFalse(result["ok"])
        self.assertEqual(result["checks"]["missing_tables"], ["findings", "tube_states"])
        self.db_path.write_bytes(b"not a database")
        self.assertFalse(data_source.validate_settings(self.db_path, {})["ok"])

    def test_server_validation_is_format_only_and_never_changes_current_database(self):
        self.make_db()
        before = self.db_path.read_bytes()
        with patch("socket.create_connection", side_effect=AssertionError("network forbidden")):
            result = data_source.validate_settings(self.db_path, {
                "target": "server", "profile": {"server_url": "https://api.example.com/v1"},
            })
        self.assertTrue(result["ok"])
        self.assertFalse(result["connected"])
        self.assertFalse(result["checks"]["network_requested"])
        self.assertEqual(result["active"]["mode"], "local")
        self.assertEqual(result["profile"]["server_url"], "")
        self.assertFalse(data_source.config_path(self.db_path).exists())
        self.assertEqual(self.db_path.read_bytes(), before)
        for profile in ({}, {"server_url": "https://user:secret@host/api"}):
            invalid = data_source.validate_settings(self.db_path, {"target": "server", "profile": profile})
            self.assertFalse(invalid["ok"])
            self.assertNotIn("secret", invalid["message"])

    def test_server_connect_remains_injected_by_db_path_and_attaches_existing_view(self):
        with patch.object(server, "DB_PATH", self.db_path):
            server.init_db()
            with server.connect() as db:
                self.assertIsInstance(db, data_source.ClosingConnection)
                self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                self.assertIsNotNone(db.execute("SELECT * FROM findings").description)


class DataSourceHttpTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "http.db"
        patcher = patch.object(server, "DB_PATH", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        server.init_db()
        self.auth_cookie = admin_cookie(server)
        self.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.addCleanup(self.httpd.server_close)
        worker = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(lambda: (self.httpd.shutdown(), worker.join(2)))

    def request(self, method, payload=None, path="/api/settings/data-source"):
        connection = HTTPConnection("127.0.0.1", self.httpd.server_port, timeout=5)
        headers = {"Content-Type": "application/json","X-Thimble-Request":"1","Cookie":self.auth_cookie}
        connection.request(method, path, body=json.dumps(payload) if payload is not None else None,
                           headers=headers)
        response = connection.getresponse()
        data = json.loads(response.read())
        connection.close()
        return response.status, data

    def test_get_save_and_local_validation_are_wired_to_http(self):
        status, result = self.request("GET")
        self.assertEqual(status, 200)
        self.assertEqual(result["active"]["path"], str(self.path.resolve()))
        status, result = self.request("POST", {"profile": {"server_url": "https://example.com/api"}})
        self.assertEqual(status, 200)
        self.assertEqual(result["profile"]["server_url"], "https://example.com/api")
        status, result = self.request("POST", {"target": "local"},
                                      "/api/settings/data-source/validate")
        self.assertEqual(status, 200)
        self.assertTrue(result["ok"])

    def test_invalid_save_returns_400_and_server_check_stays_explicitly_offline(self):
        status, result = self.request("POST", {"profile": {"server_url": "https://a:secret@host"}})
        self.assertEqual(status, 400)
        self.assertNotIn("secret", result["error"])
        status, result = self.request("POST", {"target": "server", "profile": {
            "server_url": "https://example.com/api"}}, "/api/settings/data-source/validate")
        self.assertEqual(status, 200)
        self.assertTrue(result["ok"])
        self.assertFalse(result["connected"])

    def test_array_request_has_clear_validation_error(self):
        status, result = self.request("POST", [])
        self.assertEqual(status, 400)
        self.assertIn("对象", result["error"])


if __name__ == "__main__":
    unittest.main()
