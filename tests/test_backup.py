"""数据库备份与恢复（WAL 安全）的单元测试。

覆盖：
- 默认目录备份落盘、写 restore_points、返回 sha256 与大小；
- 指定目录备份（导出备份）落到目标文件夹；
- 列表接口汇报当前记录数与备份文件；
- 校验拒绝当前库自身与缺失文件；
- 恢复能找回被删除的记录，且恢复前自动创建安全备份。
"""
import tempfile
import sqlite3
import unittest
import time
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from src.backend import backup_service, server


class BackupRestoreTests(unittest.TestCase):
    def setUp(self):
        artifact_root = Path(__file__).resolve().parents[2] / "05_测试与验证" / "03_自动化临时产物"
        artifact_root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix="backup-unit-", dir=artifact_root)
        self.db = Path(self.tmp.name) / "db.db"
        self.patcher = patch.object(server, "DB_PATH", self.db)
        self.patcher.start()
        server.init_db()

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def _insert_finding(self):
        with server.connect() as db:
            db.execute(_INSERT, ("H101", 1, 1, "WAR", "P1+10", 20, 80, "A", "C1", "f.ect",
                                 "z\\f.ect", "P1: 4-6", 1.2, 0, "Point", "u", "k", "b", "now"))

    def test_create_backup_writes_file_and_records_restore_point(self):
        info = server.create_database_backup(note="t")
        self.assertTrue(Path(info["path"]).is_file())
        self.assertEqual(info["kind"], "manual")
        self.assertEqual(info["kind_label"], "手动备份")
        self.assertTrue(info["name"].startswith("TH_数据库备份_手动_"))
        self.assertTrue(info["sha256"])
        self.assertGreater(info["size_bytes"], 0)

    def test_backup_to_target_directory(self):
        target = Path(self.tmp.name) / "exports"
        target.mkdir()
        info = server.create_database_backup(target=str(target))
        self.assertEqual(info["kind"], "exported")
        self.assertEqual(Path(info["path"]).parent.resolve(), target.resolve())

    def test_full_backup_disk_reports_capacity_without_claiming_database_corruption(self):
        self._insert_finding()
        before = backup_service.digest(self.db)
        def fail_snapshot(source, target):
            Path(target).write_bytes(b"partial snapshot")
            raise sqlite3.OperationalError("database or disk is full")
        with patch.object(backup_service, "snapshot", side_effect=fail_snapshot):
            with self.assertRaisesRegex(ValueError, "备份失败：磁盘空间不足.*本次操作未继续执行"):
                server.create_database_backup(kind="auto:state_delete")
        self.assertEqual(backup_service.digest(self.db), before)
        self.assertEqual(list(server._backup_dir().glob("TH_*")), [])
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM restore_points").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM findings").fetchone()[0], 1)

    def test_list_backups_reports_current_findings(self):
        self._insert_finding()
        server.create_database_backup()
        listing = server.list_database_backups()
        self.assertGreaterEqual(listing["current"]["findings"], 1)
        self.assertTrue(any(Path(i["path"]).is_file() for i in listing["items"]))

    def test_backup_categories_describe_purpose_without_guessing_legacy_files(self):
        automatic = server.create_database_backup(kind="auto:startup")
        self.assertEqual(automatic["kind_label"], "启动前自动备份")
        self.assertTrue(automatic["name"].startswith("TH_数据库备份_启动前自动_"))
        legacy = server._backup_dir() / "old-auto-backup.db"
        backup_service.snapshot(self.db, legacy)
        items = {item["path"]: item for item in server.list_database_backups()["items"]}
        self.assertEqual(items[str(legacy)]["kind"], "legacy")
        self.assertEqual(items[str(legacy)]["kind_label"], "历史备份（未登记）")
        self.assertFalse(items[str(legacy)]["recorded"])
        self.assertEqual(items[automatic["path"]]["kind"], "auto:startup")

    def test_validate_rejects_current_database(self):
        with self.assertRaises(ValueError):
            server.validate_backup_file(str(server.DB_PATH))

    def test_validate_rejects_missing_file(self):
        with self.assertRaises(ValueError):
            server.validate_backup_file(str(Path(self.tmp.name) / "nope.db"))

    def test_validate_backup_reports_findings(self):
        self._insert_finding()
        info = server.create_database_backup()
        validated = server.validate_backup_file(info["path"])
        self.assertEqual(validated["integrity"], "ok")
        self.assertEqual(validated["findings"], 1)

    def test_restore_recovers_deleted_finding_and_creates_safety_backup(self):
        self._insert_finding()
        info = server.create_database_backup()
        with server.connect() as db:
            db.execute("DELETE FROM findings WHERE id=1")
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM findings").fetchone()[0], 0)
        result = server.restore_database(info["path"])
        self.assertEqual(result["findings_after"], 1)
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM findings").fetchone()[0], 1)
        listing = server.list_database_backups()
        safety = [i for i in listing["items"] if i["kind"] == "safety"]
        self.assertTrue(safety)
        self.assertEqual(safety[0]["kind_label"], "恢复前备份")
        self.assertTrue(safety[0]["name"].startswith("TH_数据库备份_恢复前_"))
        self.assertTrue(Path(safety[0]["path"]).is_file())

    def test_locked_destination_backup_has_deadline_and_preserves_committed_data(self):
        source = Path(self.tmp.name) / "source.db"
        target = Path(self.tmp.name) / "target.db"
        with closing(sqlite3.connect(source)) as db, db:
            db.execute("CREATE TABLE sample(value)")
            db.execute("INSERT INTO sample VALUES('source')")
        with closing(sqlite3.connect(target)) as db, db:
            db.execute("CREATE TABLE sample(value)")
            db.execute("INSERT INTO sample VALUES('target')")
        holder = sqlite3.connect(target)
        holder.execute("BEGIN IMMEDIATE")
        try:
            started = time.monotonic()
            with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(target, timeout=.01)) as dst:
                with self.assertRaisesRegex(ValueError, "持续忙碌"):
                    backup_service.copy_database(src, dst, timeout=.1)
            self.assertLess(time.monotonic() - started, 1)
        finally:
            holder.rollback()
            holder.close()
        with closing(sqlite3.connect(target)) as db:
            self.assertEqual(db.execute("SELECT value FROM sample").fetchone()[0], "target")


_INSERT = """INSERT INTO findings(
  outage,unit_id,thimble_id,indication,location,percent,datapoint,analyst,calgroup,
  filename,report_path,channel,volts,degrees,measurement_type,uid,source_key,business_key,imported_at
) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""


if __name__ == "__main__":
    unittest.main()
