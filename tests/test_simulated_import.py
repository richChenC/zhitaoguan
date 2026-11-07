"""Exercise the user's complete lifecycle samples against an isolated database."""
import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.backend import server, state_transfer


class SimulatedImportTests(unittest.TestCase):
    def setUp(self):
        project = Path(__file__).resolve().parents[2]
        self.samples = project / "05_测试与验证" / "01_模拟数据" / "管子生命周期模拟数据_v2_非真实"
        if not self.samples.exists():
            self.samples = project / "03_模拟测试数据" / "管子生命周期模拟数据_v2_非真实"
        if not self.samples.exists():
            self.skipTest("User lifecycle samples are not available in this workspace")
        self.expected = json.loads((self.samples / "模拟数据清单.json").read_text(encoding="utf-8"))
        test_root = project / "05_测试与验证" / "03_自动化临时产物"
        test_root.mkdir(parents=True, exist_ok=True)
        folder = tempfile.TemporaryDirectory(prefix="lifecycle-import-", dir=test_root)
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        for name, target in (("DB_PATH", self.root / "test.db"),
                             ("EXCEL_DIR", self.root / "exports"),
                             ("REPORT_DIR", self.root / "reports")):
            change = patch.object(server, name, target)
            change.start()
            self.addCleanup(change.stop)
        server.init_db()

    def test_full_12600_record_state_file_previews_and_commits_without_splitting(self):
        source = self.samples / "模拟状态维护导入_全量.csv"
        content = source.read_bytes()
        result = state_transfer.preview(server, {
            "filename": source.name, "content": base64.b64encode(content).decode("ascii"),
        })
        self.assertEqual(len(result["rows"]), self.expected["维护记录数"])
        applied = state_transfer.apply_batch(server, {"rows": result["rows"], "confirmed": True})
        self.assertEqual(applied["changed"], self.expected["维护记录数"])
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tube_states WHERE is_deleted=0").fetchone()[0],
                             self.expected["维护记录数"])
        self.assertEqual(source.read_bytes(), content)

    def test_complete_excel_import_keeps_all_detection_rows_and_maintenance_states(self):
        source = self.samples / "软件导入专用_检测记录及管状态_模拟非真实.xlsx"
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        result = server.import_excel_file(str(source), operator="isolated-simulation-test")
        self.assertEqual(result["parsed"], self.expected["检测记录数"])
        self.assertEqual(result["inserted"], self.expected["检测记录数"])
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM findings WHERE is_deleted=0").fetchone()[0],
                             self.expected["检测记录数"])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tube_states WHERE is_deleted=0").fetchone()[0],
                             self.expected["维护记录数"])
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
        repeated = server.import_excel_file(str(source), operator="isolated-simulation-test")
        self.assertEqual(repeated["inserted"], 0)

    def test_oversize_batches_are_rejected_before_any_write(self):
        with self.assertRaisesRegex(ValueError, str(state_transfer.MAX_STATE_ROWS)):
            state_transfer.validate_rows(server, [{}] * (state_transfer.MAX_STATE_ROWS + 1))
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tube_states").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
