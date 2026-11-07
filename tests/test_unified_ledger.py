from enterprise_fixtures import mark_legacy
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook, load_workbook
from src.backend import import_audit, server, state_transfer
from test_server import write_ect, write_report, write_sum, report_entry


class UnifiedLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [
            patch.object(server, "DB_PATH", self.root / "ledger.db"),
            patch.object(server, "EXCEL_DIR", self.root / "exports"),
        ]
        for item in self.patches:
            item.start()
        server.init_db()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def source(self, note="原文第一行\r\n  第二行，不能删改。", maintenance="割管移位 20mm"):
        book = Workbook()
        book.active.title = "L301"
        book.active.append(["通道编号", "堆芯位置", "幅值（V)", "相位", "磨损深度",
                            "三字符", "记录通道", "磨损位置", "探头类型", "分析人员",
                            "数据", "数据组", "备注", "堵管移位信息"])
        book.active.append([1, "L11", 1.2, 256, 30, "WAR", "CH1", "P1+20", "ET",
                            "分析员甲", "tube.ect", "TH3I01CAL00001", note, maintenance])
        book.active.cell(2, 13).data_type = "s"
        source = self.root / "source.xlsx"
        state_transfer.save_workbook_exact(book, source)
        book.close()
        return source

    def import_source(self, **kwargs):
        result = server.import_excel_file(str(self.source(**kwargs)), "review")
        self.assertEqual(result["inserted"], 1)
        return result

    def row(self):
        with server.connect() as db:
            return dict(db.execute("SELECT * FROM findings WHERE is_deleted=0 LIMIT 1").fetchone())

    def test_sheet_scope_aliases_and_original_notes(self):
        result = self.import_source()
        self.assertEqual(result["invalid_count"], 0)
        row = self.row()
        self.assertEqual((row["outage"], row["unit_id"], row["channel"], row["probe"]),
                         ("L301", 3, "CH1", "ET"))
        self.assertEqual(row["analysis"], "原文第一行\r\n  第二行，不能删改。")
        state = server.query_states()["items"][0]
        self.assertEqual(state["state"], "shifted")
        self.assertEqual(state["offset_mm"], 20)
        self.assertIsNone(state["unsigned_offset_mm"])

    def test_roundtrip_to_empty_database_preserves_all_user_fields_and_state(self):
        self.import_source(note="=原始文字\n第二行")
        original = self.row()
        original_state = server.query_states()["items"][0]
        result = server.export_data_ledger({})
        with patch.object(server, "DB_PATH", self.root / "other.db"):
            server.init_db()
            imported = server.import_excel_file(result["file_path"], "review")
            restored = self.row()
            state = server.query_states()["items"][0]
        self.assertEqual(imported["inserted"], 1)
        self.assertEqual(imported["invalid_count"], 0)
        for field in ("outage", "unit_id", "thimble_id", "position", *server.EDITABLE_FINDING_FIELDS):
            self.assertEqual(restored[field], original[field], field)
        for field in ("state", "offset_mm", "unsigned_offset_mm", "note", "source"):
            self.assertEqual(state[field], original_state[field], field)
        book = load_workbook(result["file_path"], data_only=False)
        try:
            header = book["综合台账"]["A1"]
            self.assertIsNone(header.fill.fill_type)
            self.assertEqual(header.font.color.type, "rgb")
            self.assertEqual(header.font.color.rgb[-6:], "000000")
            self.assertEqual(header.font.name, server.PLAIN_EXCEL_FONT)
            self.assertEqual(header.border.left.style, "thin")
            self.assertEqual(book["综合台账"].cell(2, 16).data_type, "s")
            self.assertEqual(book["_ledger_metadata"].sheet_state, "hidden")
        finally:
            book.close()

    def test_same_database_roundtrip_is_idempotent_and_excel_edit_updates(self):
        self.import_source()
        result = server.export_data_ledger({})
        imported = server.import_excel_file(result["file_path"], "review")
        self.assertEqual((imported["inserted"], imported["updated"], imported["skipped"]), (0, 0, 1))
        book = load_workbook(result["file_path"])
        book["综合台账"].cell(2, 13, "新分析员")
        book.save(result["file_path"])
        book.close()
        updated = server.import_excel_file(result["file_path"], "review")
        self.assertEqual((updated["inserted"], updated["updated"]), (0, 1))
        self.assertEqual(self.row()["analyst"], "新分析员")
        import_audit.change_batch(server, updated["batch_id"], "rollback")
        self.assertEqual(self.row()["analyst"], "分析员甲")

    def test_filtered_export_names_and_summary_identify_actual_scope(self):
        self.import_source()
        for filters, expected in (
            ({"analyst": "分析员甲"}, ["分析人员 分析员甲"]),
            ({"thimble": 1}, ["通道编号 1"]),
            ({"channel": "CH1", "calgroup": "TH3I01CAL00001"},
             ["测量通道 CH1", "数据组 TH3I01CAL00001"]),
        ):
            with self.subTest(filters=filters):
                result = server.export_data_ledger(filters)
                self.assertEqual(result["rows"], 1)
                self.assertNotIn("_全量_", result["filename"])
                book = load_workbook(result["file_path"], data_only=True)
                try:
                    text = "\n".join(str(cell.value or "") for row in book.worksheets[0] for cell in row)
                    for label in expected:
                        self.assertIn(label, text)
                    self.assertNotIn("范围：全量", text)
                    self.assertIn("管状态事件按基地、机组、大修和通道编号筛选", text)
                    self.assertTrue(book.worksheets[0]["A2"].alignment.wrap_text)
                    self.assertIn("A2:H2", {str(item) for item in book.worksheets[0].merged_cells.ranges})
                finally:
                    book.close()

    def test_editor_preserves_null_and_rejects_stale_values(self):
        self.import_source()
        row = self.row()
        changed = server.update_finding_field({"id": row["id"], "field": "degrees",
                                               "value": "0", "expected_value": 256})
        self.assertEqual(changed["value"], 0)
        with self.assertRaisesRegex(ValueError, "其他操作"):
            server.update_finding_field({"id": row["id"], "field": "degrees",
                                         "value": "1", "expected_value": 256})
        server.update_finding_field({"id": row["id"], "field": "degrees", "value": "/"})
        self.assertIsNone(self.row()["degrees"])
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM finding_edit_history").fetchone()[0], 2)

    def test_code_edit_changes_original_code_export(self):
        self.import_source()
        server.update_finding_field({"id": self.row()["id"], "field": "indication", "value": "NDD"})
        result = server.export_data_ledger({})
        book = load_workbook(result["file_path"])
        self.assertEqual(book["综合台账"].cell(2, 9).value, "NDD")
        book.close()

    def test_export_preserves_windows_newlines_exactly(self):
        note = "第一行\r\n  第二行\r第三行"
        self.import_source(note=note)
        result = server.export_data_ledger({})
        book = load_workbook(result["file_path"])
        self.assertEqual(book["综合台账"].cell(2, 16).value, note)
        book.close()

    def test_ambiguous_maintenance_edit_is_saved_without_guessing(self):
        self.import_source(maintenance="")
        original = "此前割管移位，可能 20mm 或 40mm。"
        result = server.update_finding_field({"id": self.row()["id"], "field": "maintenance_text",
                                              "value": original})
        self.assertEqual(self.row()["maintenance_text"], original)
        self.assertEqual(result["state_recognition"]["pending"], 1)
        self.assertEqual(len(server.query_states()["items"]), 0)

    def test_remark_edit_recognizes_state_but_preserves_original(self):
        self.import_source(maintenance="")
        original = "封堵，原始备注\n  第二行"
        result = server.update_finding_field({"id": self.row()["id"], "field": "analysis", "value": original})
        self.assertEqual(self.row()["analysis"], original)
        self.assertEqual(result["state_recognition"]["applied"], 1)
        self.assertEqual(server.query_states()["items"][0]["note"], original)

    def test_clear_verifies_backup_and_rotates_identity(self):
        self.import_source()
        with server.connect() as db:
            token = db.execute("SELECT token FROM ledger_identity").fetchone()[0]
        result = server.clear_database()
        self.assertEqual(result["backup"]["verification"]["integrity"], "ok")
        with closing(sqlite3.connect(result["backup"]["path"])) as backup:
            self.assertEqual(backup.execute("SELECT COUNT(*) FROM findings").fetchone()[0], 1)
        with server.connect() as db:
            self.assertNotEqual(db.execute("SELECT token FROM ledger_identity").fetchone()[0], token)
            for table in result["cleared"]:
                if table != "operation_logs":
                    self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0, table)

    def test_migration_adds_maintenance_field_without_losing_records(self):
        self.import_source()
        with server.connect() as db:
            db.execute("DROP TRIGGER IF EXISTS invalidate_cross_group_update")
            db.execute("ALTER TABLE findings DROP COLUMN maintenance_text")
        mark_legacy(server)
        server.init_db()
        self.assertEqual(self.row()["filename"], "tube.ect")
        self.assertEqual(self.row()["maintenance_text"], "")

    def test_site_filter_does_not_mix_lingao_and_lufeng(self):
        self.import_source()
        server.save_tube_state({"outage": "LF101", "unit_id": 1, "thimble_id": 1, "state": "plugged"})
        result = server.export_data_ledger({"site": "L"})
        book = load_workbook(result["file_path"])
        self.assertEqual(book["管状态事件"].max_row, 2)
        self.assertEqual(book["管状态事件"].cell(2, 4).value, "L301")
        book.close()

    def test_outage_contains_filter_keeps_matching_state_events(self):
        self.import_source()
        server.save_tube_state({
            "outage": "L301", "unit_id": 3, "thimble_id": 1,
            "state": "shifted", "offset_mm": 20, "offset_confirmed": 1,
        })
        for outage_filter in ("L30", " l30 ", "L3_1", "L3%1", "   "):
            with self.subTest(outage_filter=outage_filter):
                result = server.export_data_ledger({"outage": outage_filter})
                self.assertEqual(result["rows"], 1)
                self.assertEqual(result["state_events"], 1)
                book = load_workbook(result["file_path"], data_only=True)
                try:
                    self.assertEqual(book["管状态事件"].max_row, 2)
                    self.assertEqual(book["管状态事件"].cell(2, 4).value, "L301")
                finally:
                    book.close()

    def test_raw_folder_conversion_can_be_imported_with_explicit_outage(self):
        group = self.root / "H209" / "TH2I09CAL00001"
        group.mkdir(parents=True)
        write_sum(group)
        write_ect(group, "DIR001C001I001.ECT", 1, 1, 1)
        write_report(group, [report_entry("DIR001C001I001.ECT", 1, 1, 1, "原始分析人员")])
        direct = server.process_directory(str(self.root / "H209"))["findings"][0]
        converted = server.export_directory_excel(str(self.root / "H209"))
        imported = server.import_excel_file(converted["file_path"], "review")
        self.assertEqual(imported["inserted"], 1)
        restored = self.row()
        for field in ("outage", "unit_id", "thimble_id", "volts", "degrees", "indication",
                      "percent", "channel", "location", "probe", "analysis", "comment", "measurement_type"):
            self.assertEqual(restored[field], getattr(direct, field), field)


if __name__ == "__main__":
    unittest.main()
