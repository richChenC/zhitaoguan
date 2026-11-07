import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.backend import server


class DeleteWorkflowTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = patch.object(server, "DB_PATH", Path(directory.name) / "test.db")
        patcher.start()
        self.addCleanup(patcher.stop)
        server.init_db()
        with server.connect() as db:
            for outage, unit, tube in [("D101", 1, 1), ("D102", 1, 1), ("D101", 1, 2), ("F101", 1, 1)]:
                db.execute("INSERT INTO findings(outage,unit_id,thimble_id,imported_at) VALUES(?,?,?,'test')",
                           (outage, unit, tube))
                db.execute("INSERT INTO tube_states(outage,unit_id,thimble_id,state) VALUES(?,?,?,'plugged')",
                           (outage, unit, tube))
            db.execute("""INSERT INTO import_batches(started_at,source_path,import_kind,status,outage)
                          VALUES('now','fixture.xlsx','excel','completed','D101')""")
        # Snapshot behavior is covered separately; isolate deletion transactions here.
        backup = patch.object(server, "_auto_backup", return_value="test-backup.db")
        backup.start()
        self.addCleanup(backup.stop)

    def assert_scope(self, scope, data):
        preview = server.api_delete_preview({"scope": scope, "data": data})
        result = server.api_data_delete({"scope": scope, "data": data})
        self.assertFalse(result["hardDelete"])
        self.assertEqual(preview["total_records"], result["deletedCount"])
        with server.connect() as db:
            actual = sum(db.execute(f"SELECT COUNT(*) FROM {table} WHERE delete_batch_id=?",
                                    (result["batchId"],)).fetchone()[0]
                         for table in ("findings", "tube_states", "import_batches"))
        self.assertEqual(actual, result["deletedCount"])
        restored = server.api_recycle_restore(result["batchId"])
        self.assertEqual(restored["restoredCount"], actual)
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM findings WHERE is_deleted=0").fetchone()[0], 4)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tube_states WHERE is_deleted=0").fetchone()[0], 4)

    def test_every_scope_preview_matches_changed_rows_and_restore(self):
        scopes = [
            ("finding", {"findingId": 1}),
            ("selected", {"findingIds": [1, 3]}),
            ("tube_outage", {"outage": "D101", "unitId": 1, "tubeId": 1}),
            ("tube_all", {"siteCode": "D", "unitId": 1, "tubeId": 1}),
            ("outage", {"outage": "D101"}),
            ("unit", {"siteCode": "D", "unitId": 1}),
            ("site", {"siteCode": "D"}),
            ("all", {}),
        ]
        for scope, data in scopes:
            with self.subTest(scope=scope):
                self.assert_scope(scope, data)

    def test_tube_history_does_not_delete_same_tube_at_another_site(self):
        data = {"siteCode": "D", "unitId": 1, "tubeId": 1}
        result = server.api_data_delete({"scope": "tube_all", "data": data})
        self.assertEqual(result["deletedCount"], 4)
        with server.connect() as db:
            for table in ("findings", "tube_states"):
                self.assertEqual(db.execute(f"SELECT is_deleted FROM {table} WHERE outage='F101'").fetchone()[0], 0)
        with self.assertRaises(ValueError):
            server.api_delete_preview({"scope": "tube_all", "data": {"unitId": 1, "tubeId": 1}})
        with self.assertRaises(ValueError):
            server.api_data_delete({"scope": "tube_all", "data": {"unitId": 1, "tubeId": 1}})

    def test_purge_removes_exactly_the_deleted_findings_states_and_batches(self):
        result = server.api_data_delete({"scope": "outage", "data": {"outage": "D101"}})
        purged = server.api_recycle_purge(result["batchId"])
        self.assertEqual(purged["purgedCount"], result["deletedCount"])
        with server.connect() as db:
            for table in ("findings", "tube_states", "import_batches"):
                self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table} WHERE delete_batch_id=?",
                                            (result["batchId"],)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM findings WHERE outage='F101'").fetchone()[0], 1)
        with self.assertRaises(ValueError):
            server.api_recycle_restore(result["batchId"])

    def test_unit_scope_preserves_other_units_even_with_the_same_outage(self):
        with server.connect() as db:
            other = db.execute(
                "INSERT INTO findings(outage,unit_id,thimble_id,imported_at) VALUES('D101',2,1,'test')"
            ).lastrowid
        data = {"siteCode": "D", "unitId": 1}
        self.assertEqual(server.api_delete_preview({"scope": "unit", "data": data})["findings"], 3)
        result = server.api_data_delete({"scope": "unit", "data": data})
        self.assertEqual(result["deletedCount"], 3)
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT is_deleted FROM findings WHERE id=?", (other,)).fetchone()[0], 0)

    def test_repeated_restore_is_idempotent_and_preserves_restored_history(self):
        result = server.api_data_delete({"scope": "outage", "data": {"outage": "D101"}})
        first = server.api_recycle_restore(result["batchId"])
        second = server.api_recycle_restore(result["batchId"])
        self.assertEqual(first["restoredCount"], result["deletedCount"])
        self.assertEqual(first["batchId"], result["batchId"])
        self.assertFalse(first["alreadyRestored"])
        self.assertEqual(second["restoredCount"], 0)
        self.assertTrue(second["alreadyRestored"])
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM operation_logs WHERE operation_type='restore'").fetchone()[0], 1)
        with self.assertRaisesRegex(ValueError, "已恢复"):
            server.api_recycle_purge(result["batchId"])

    def test_restore_audit_failure_rolls_back_all_associated_rows(self):
        result = server.api_data_delete({"scope": "outage", "data": {"outage": "D101"}})
        with patch.object(server, "_log_operation", side_effect=ValueError("audit failure")):
            with self.assertRaisesRegex(ValueError, "audit failure"):
                server.api_recycle_restore(result["batchId"])
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT is_restored FROM delete_batches WHERE id=?", (result["batchId"],)).fetchone()[0], 0)
            count = sum(db.execute(f"SELECT COUNT(*) FROM {table} WHERE delete_batch_id=? AND is_deleted=1",
                                   (result["batchId"],)).fetchone()[0]
                        for table in ("findings", "tube_states", "import_batches"))
            self.assertEqual(count, result["deletedCount"])


if __name__ == "__main__":
    unittest.main()
