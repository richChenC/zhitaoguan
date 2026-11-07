import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.name == "nt", "Windows batch entry point")
class WindowsLauncherTests(unittest.TestCase):
    def test_qt_runtime_batch_launchers_use_windows_line_endings(self):
        app = Path(__file__).resolve().parents[1]
        for name in ("启动Qt版.cmd", "启动Qt版-调试.cmd"):
            with self.subTest(launcher=name):
                data = (app / name).read_bytes()
                self.assertNotIn(b"\n", data.replace(b"\r\n", b""))

    def test_workspace_entry_points_to_qt_primary_version(self):
        version = Path(__file__).resolve().parents[1]
        launcher = version / "scripts" / "start-current-version.cmd"
        self.assertNotIn(b"\n", launcher.read_bytes().replace(b"\r\n", b""))
        artifacts = Path(os.environ.get(
            "THIMBLE_TEST_OUTPUT_ROOT",
            version.parent / "05_测试与验证" / "03_自动化临时产物",
        ))
        artifacts.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="thimble-workspace-launcher-", dir=artifacts) as temporary:
            root = Path(temporary) / "中文工作区 with spaces"
            app = root / "08_Qt移植版"
            app.mkdir(parents=True)
            shutil.copyfile(launcher, root / "启动Qt主版本.cmd")
            (app / "expected-directory.txt").touch()
            inner = app / "启动正式版.cmd"
            driver = root / "verify.cmd"
            for codepage in (936, 65001):
                for exit_code in (0, 7):
                    with self.subTest(codepage=codepage, exit_code=exit_code):
                        inner.write_bytes((
                            '@echo off\r\n'
                            'cd /d "%~dp0"\r\n'
                            'if not exist "expected-directory.txt" exit /b 9\r\n'
                            'echo QT_PRIMARY_DESKTOP_OK\r\n'
                            f'exit /b {exit_code}\r\n'
                        ).encode("ascii"))
                        driver.write_bytes((
                            f'@echo off\r\nchcp {codepage} >nul\r\n'
                            'call "%~dp0启动Qt主版本.cmd"\r\n'
                            'exit /b %ERRORLEVEL%\r\n'
                        ).encode("utf-8" if codepage == 65001 else "gbk"))
                        result = subprocess.run(
                            [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(driver)],
                            cwd=temporary, capture_output=True, timeout=30,
                        )
                        self.assertEqual(result.returncode, exit_code, result.stdout + result.stderr)
                        self.assertIn(b"QT_PRIMARY_DESKTOP_OK", result.stdout)
                        self.assertEqual(result.stderr, b"")

    def test_qt_official_launcher_calls_qt_runtime_launcher(self):
        launcher = Path(__file__).resolve().parents[1] / "启动正式版.cmd"
        self.assertNotIn(b"\n", launcher.read_bytes().replace(b"\r\n", b""))
        artifacts = Path(os.environ.get(
            "THIMBLE_TEST_OUTPUT_ROOT",
            launcher.parents[1] / "05_测试与验证" / "03_自动化临时产物",
        ))
        artifacts.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="thimble-launcher-", dir=artifacts) as temporary:
            root = Path(temporary) / "中文路径 with spaces"
            app = root
            app.mkdir(parents=True)
            shutil.copyfile(launcher, root / launcher.name)
            inner = app / "启动Qt版.cmd"
            driver = root / "verify.cmd"
            for codepage in (936, 65001):
                for exit_code in (0, 7):
                    with self.subTest(codepage=codepage, exit_code=exit_code):
                        inner.write_bytes(
                            f'@echo off\r\nif not exist "expected-directory.txt" exit /b 9\r\n'
                            f'echo DESKTOP_LAUNCH_OK\r\nexit /b {exit_code}\r\n'.encode("ascii")
                        )
                        (app / "expected-directory.txt").touch()
                        driver_text = (
                            f'@echo off\r\nchcp {codepage} >nul\r\n'
                            'call "%~dp0启动正式版.cmd"\r\n'
                            'exit /b %ERRORLEVEL%\r\n'
                        )
                        driver.write_bytes(driver_text.encode("utf-8" if codepage == 65001 else "gbk"))
                        result = subprocess.run(
                            [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(driver)],
                            cwd=temporary, capture_output=True, timeout=30,
                        )
                        self.assertEqual(result.returncode, exit_code, result.stdout + result.stderr)
                        self.assertIn(b"DESKTOP_LAUNCH_OK", result.stdout)
                        self.assertEqual(result.stderr, b"")

    def test_legacy_named_launcher_forwards_to_qt_official_launcher(self):
        launcher = Path(__file__).resolve().parents[1] / "启动指套管软件.cmd"
        self.assertNotIn(b"\n", launcher.read_bytes().replace(b"\r\n", b""))
        artifacts = Path(os.environ.get(
            "THIMBLE_TEST_OUTPUT_ROOT",
            launcher.parents[1] / "05_测试与验证" / "03_自动化临时产物",
        ))
        artifacts.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="thimble-legacy-launcher-", dir=artifacts) as temporary:
            root = Path(temporary) / "中文路径 with spaces"
            root.mkdir(parents=True)
            shutil.copyfile(launcher, root / launcher.name)
            inner = root / "启动正式版.cmd"
            driver = root / "verify.cmd"
            for codepage in (936, 65001):
                for exit_code in (0, 7):
                    with self.subTest(codepage=codepage, exit_code=exit_code):
                        inner.write_bytes(
                            f'@echo off\r\n'
                            f'echo QT_OFFICIAL_ENTRY_OK\r\n'
                            f'exit /b {exit_code}\r\n'.encode("ascii")
                        )
                        driver.write_bytes((
                            f'@echo off\r\nchcp {codepage} >nul\r\n'
                            'call "%~dp0启动指套管软件.cmd"\r\n'
                            'exit /b %ERRORLEVEL%\r\n'
                        ).encode("utf-8" if codepage == 65001 else "gbk"))
                        result = subprocess.run(
                            [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(driver)],
                            cwd=temporary, capture_output=True, timeout=30,
                        )
                        self.assertEqual(result.returncode, exit_code, result.stdout + result.stderr)
                        self.assertIn(b"QT_OFFICIAL_ENTRY_OK", result.stdout)
                        self.assertEqual(result.stderr, b"")
