import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import qt_shell.backend_service as backend_module
import qt_shell.main as shell_main
from qt_shell.backend_service import BackendService, ServiceStartError
from qt_shell.constants import DATA_DIR, LOG_DIR, OUTPUT_DIR, REPORT_DIR, RUNTIME, USER_DATA

TEST_ARTIFACT_ROOT = Path(os.environ.get(
    "THIMBLE_TEST_OUTPUT_ROOT",
    Path(__file__).resolve().parents[3] / "05_测试与验证" / "03_自动化临时产物",
))


class BackendEnvironmentTests(unittest.TestCase):
    def test_staged_backend_is_installed_after_normal_startup_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "backend" / "thimble-backend.exe"
            staged = root / "backend-next" / "thimble-backend.exe"
            target.parent.mkdir()
            staged.parent.mkdir()
            target.write_bytes(b"old")
            staged.write_bytes(b"new")
            with patch.object(shell_main, "BACKEND_EXE", target), \
                 patch.object(shell_main.sys, "frozen", False, create=True), \
                 patch.dict(os.environ, {"THIMBLE_QT_TEST_DATA_ROOT": ""}):
                shell_main._install_staged_backend(backend_module.ServiceLog(root / "test.log"))
            self.assertEqual(target.read_bytes(), b"new")
            self.assertFalse(staged.exists())

    def test_source_is_preferred_only_for_nonfrozen_shell(self):
        with patch("pathlib.Path.is_file", return_value=True), \
             patch.object(backend_module.sys, "frozen", False, create=True):
            candidates = BackendService()._candidates()
            self.assertEqual(candidates[0][1], [str(backend_module.BACKEND_SOURCE)])
            self.assertEqual(candidates[1][0], str(backend_module.BACKEND_EXE))
        with patch("pathlib.Path.is_file", return_value=True), \
             patch.object(backend_module.sys, "frozen", True, create=True):
            self.assertEqual(BackendService()._candidates(), [(str(backend_module.BACKEND_EXE), [])])

    def test_inherited_paths_cannot_redirect_qt_data_or_exports(self):
        inherited = {
            "THIMBLE_USER_DATA_DIR": r"C:\production",
            "THIMBLE_DATA_DIR": r"C:\production\data",
            "THIMBLE_DB_PATH": r"C:\production\data\thimble.db",
            "THIMBLE_OUTPUT_DIR": r"C:\production\exports",
            "THIMBLE_REPORT_DIR": r"C:\production\reports",
            "THIMBLE_LOG_PATH": r"C:\production\server.log",
            "THIMBLE_PORT": "19999",
            "THIMBLE_MIGRATE_LEGACY": "1",
            "THIMBLE_LEGACY_DATA_DIRS": r'["C:\\production\\data"]',
        }
        with patch.dict(os.environ, inherited, clear=False):
            env = BackendService()._environment()

        self.assertEqual(env["THIMBLE_USER_DATA_DIR"], str(USER_DATA))
        self.assertEqual(env["THIMBLE_DATA_DIR"], str(DATA_DIR))
        self.assertEqual(env["THIMBLE_DB_PATH"], str(DATA_DIR / "thimble.db"))
        self.assertEqual(env["THIMBLE_OUTPUT_DIR"], str(OUTPUT_DIR))
        self.assertEqual(env["THIMBLE_REPORT_DIR"], str(REPORT_DIR))
        self.assertEqual(env["THIMBLE_LOG_PATH"], str(LOG_DIR / "server.log"))
        self.assertEqual(env["THIMBLE_PORT"], str(RUNTIME.port))
        self.assertNotIn("THIMBLE_MIGRATE_LEGACY", env)
        self.assertNotIn("THIMBLE_LEGACY_DATA_DIRS", env)

    def test_isolated_test_paths_are_allowed_only_inside_test_root(self):
        TEST_ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="qt-backend-test-", dir=TEST_ARTIFACT_ROOT) as directory:
            root = os.path.join(directory, "qt-test")
            env_vars = {
                "THIMBLE_QT_TEST_DATA_ROOT": root,
                "THIMBLE_ALLOW_MULTI_INSTANCE": "1",
                "THIMBLE_DB_PATH": os.path.join(root, "isolated.db"),
                "THIMBLE_DATA_DIR": os.path.join(root, "data"),
                "THIMBLE_OUTPUT_DIR": os.path.join(root, "exports"),
                "THIMBLE_REPORT_DIR": os.path.join(root, "reports"),
                "THIMBLE_LOG_PATH": os.path.join(root, "server.log"),
            }
            with patch.dict(os.environ, env_vars, clear=False):
                env = BackendService()._environment()

            self.assertEqual(env["THIMBLE_USER_DATA_DIR"], os.path.realpath(root))
            self.assertEqual(env["THIMBLE_DB_PATH"], os.path.realpath(env_vars["THIMBLE_DB_PATH"]))

            env_vars["THIMBLE_DB_PATH"] = os.path.join(directory, "outside.db")
            with patch.dict(os.environ, env_vars, clear=False):
                with self.assertRaisesRegex(ServiceStartError, "必须位于测试数据目录内"):
                    BackendService()._environment()


if __name__ == "__main__":
    unittest.main()
