import json
import tempfile
import unittest
from pathlib import Path

from qt_shell.factory_reset import apply, schedule


class FactoryResetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "data" / "backups").mkdir(parents=True)
        (self.root / "qtwebengine").mkdir()
        (self.root / "output").mkdir()
        (self.root / "data" / "thimble.db").write_bytes(b"database")
        (self.root / "data" / "thimble.db-wal").write_bytes(b"wal")
        (self.root / "data" / "backups" / "old.db").write_bytes(b"backup")
        (self.root / "qtwebengine" / "settings").write_bytes(b"settings")
        (self.root / "output" / "report").write_bytes(b"report")

    def test_reset_preserves_recovery_and_exports(self):
        schedule(self.root)
        self.assertTrue(apply(self.root))
        self.assertFalse(apply(self.root))
        recovery = next((self.root / "data" / "backups").glob("factory-reset-*"))
        self.assertEqual((recovery / "thimble.db").read_bytes(), b"database")
        self.assertEqual((recovery / "thimble.db-wal").read_bytes(), b"wal")
        self.assertEqual((recovery / "qtwebengine" / "settings").read_bytes(), b"settings")
        self.assertFalse((self.root / "data" / "thimble.db").exists())
        self.assertFalse((self.root / "qtwebengine").exists())
        self.assertEqual((self.root / "data" / "backups" / "old.db").read_bytes(), b"backup")
        self.assertEqual((self.root / "output" / "report").read_bytes(), b"report")

    def test_interrupted_reset_resumes(self):
        schedule(self.root)
        marker = self.root / "factory-reset.json"
        recovery = self.root / "data" / "backups" / ("factory-reset-" + json.loads(marker.read_text())["id"])
        recovery.mkdir()
        (self.root / "data" / "thimble.db").rename(recovery / "thimble.db")
        self.assertTrue(apply(self.root))
        self.assertEqual((recovery / "thimble.db").read_bytes(), b"database")
        self.assertEqual((recovery / "thimble.db-wal").read_bytes(), b"wal")

    def test_invalid_marker_does_not_modify_database(self):
        (self.root / "factory-reset.json").write_text('{"id":"../../outside"}')
        with self.assertRaises(RuntimeError):
            apply(self.root)
        self.assertEqual((self.root / "data" / "thimble.db").read_bytes(), b"database")


if __name__ == "__main__":
    unittest.main()
