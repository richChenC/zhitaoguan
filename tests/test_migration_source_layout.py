"""Source audits must work before and after workspace classification."""
import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "migration_source_layout", ROOT / "scripts" / "verify_migration.py")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class MigrationSourceLayoutTests(unittest.TestCase):
    def test_every_audited_source_has_an_explicit_classification(self):
        self.assertEqual(set(AUDIT.SOURCE_LOCATIONS),
                         set(AUDIT.DIRECTORIES) | set(AUDIT.FILES))
        for relative in AUDIT.SOURCE_LOCATIONS.values():
            self.assertFalse(Path(relative).is_absolute())
            self.assertNotIn("..", Path(relative).parts)

    def test_classified_source_takes_precedence_without_legacy_alias(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            expected = source / AUDIT.SOURCE_LOCATIONS["记忆"]
            expected.mkdir(parents=True)
            self.assertEqual(AUDIT.source_path(source, "记忆"), expected)

    def test_flat_source_is_supported_for_occupied_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            name = "导入台账_全量72次大修.xlsx"
            expected = source / name
            expected.touch()
            self.assertEqual(AUDIT.source_path(source, name), expected)
