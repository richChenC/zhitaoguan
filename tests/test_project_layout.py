"""Guard the relocated desktop project against missing bundled resources."""
import importlib.util
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ProjectLayoutTests(unittest.TestCase):
    def test_documentation_is_classified(self):
        docs = ROOT / "docs"
        self.assertTrue((docs / "开发与验收记录").is_dir())
        self.assertTrue((docs / "使用手册").is_dir())
        self.assertFalse(list(docs.glob("*.docx")))
        self.assertTrue((docs / "开发与验收记录" / "全流程回归验收_2026-11-04-r16.md").is_file())

    def test_verification_evidence_is_classified(self):
        verify = ROOT / "验证"
        expected = (
            "01_启动与环境", "02_基线与对拍", "03_专项报告",
            "04_界面截图", "05_对比结果",
        )
        for name in expected:
            with self.subTest(name=name):
                self.assertTrue((verify / name).is_dir())
        self.assertFalse(list(verify.glob("*.png")))
        self.assertFalse(list(verify.glob("*.json")))

    def test_cleanup_script_uses_project_root(self):
        script = (ROOT / "scripts" / "cleanup-test-artifacts.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertRegex(
            script,
            r"\$workspace\s*=\s*\[IO\.Path\]::GetFullPath"
            r"\(\(Join-Path \$appRoot '\.\.'\)\)",
        )

    def test_bundled_analytics_resources_are_present(self):
        data = ROOT / "src" / "desktop-ui" / "modules" / "analytics" / "data"
        for name in ("china-provinces.json", "ningde-n1-outages.json",
                     "real-domain-data.json", "thimble-ledger/index.json"):
            with self.subTest(resource=name):
                json.loads((data / name).read_text(encoding="utf-8"))
        index = json.loads((data / "thimble-ledger" / "index.json").read_text(encoding="utf-8"))
        for unit_code in index["units"]:
            with self.subTest(unit=unit_code):
                ledger = data / "thimble-ledger" / f"ledger-{unit_code}.json"
                self.assertTrue(ledger.is_file(), ledger)

    def test_offline_tool_paths_stay_inside_version(self):
        specification = importlib.util.spec_from_file_location(
            "relocated_tool_paths", ROOT / "src" / "tools" / "_paths.py")
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        self.assertEqual(Path(module.APP_DIR), ROOT)
        self.assertEqual(Path(module.PROJECT_ROOT), ROOT)
        for name in ("REFERENCE_DIR", "TEST_DATA_DIR", "DATA_DIR", "LEDGER_DIR"):
            with self.subTest(path=name):
                path = Path(getattr(module, name))
                self.assertTrue(path.is_relative_to(ROOT), path)

    def test_new_version_ports_are_consistent_and_not_legacy(self):
        desktop = (ROOT / "src" / "desktop" / "main.cjs").read_text(encoding="utf-8")
        backend = (ROOT / "src" / "backend" / "server.py").read_text(encoding="utf-8")
        launcher = (ROOT / "启动Qt版.cmd").read_text(encoding="utf-8")
        settings = (ROOT / ".env.example").read_text(encoding="utf-8")
        port = re.search(r"const PORT = process.env.THIMBLE_PORT \|\| '(\d+)'", desktop).group(1)
        self.assertNotIn(port, ("8765", "18765"))
        self.assertIn(f'os.environ.get("THIMBLE_PORT", "{port}")', backend)
        self.assertIn(f'set "THIMBLE_PORT={port}"', launcher)
        self.assertIn(f"THIMBLE_PORT={port}", settings)
        qt_constants = (ROOT / "qt_shell" / "constants.py").read_text(encoding="utf-8")
        self.assertIn("ThimbleInspection", qt_constants)
        self.assertIn("PREFERRED_PORT = int(os.environ.get", qt_constants)

    def test_installer_uses_runtime_whitelist_only(self):
        installer = (ROOT / "scripts" / "thimble-installer.iss").read_text(encoding="utf-8-sig")
        for broad_source in (
            r'Source: "..\src\*"',
            r'Source: "..\docs\*"',
            r'Source: "..\assets\*"',
            r'Source: "..\.vendor\*"',
        ):
            self.assertNotIn(broad_source, installer)
        for source in (
            r'Source: "..\docs\使用手册\*"',
            r'Source: "..\assets\report-templates\*"',
            r'Source: "..\assets\app-icon.ico"',
        ):
            self.assertIn(source, installer)
        self.assertTrue((ROOT / "scripts" / "verify-package-payload.ps1").is_file())
