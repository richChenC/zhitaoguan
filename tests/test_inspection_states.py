import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.backend import server, import_audit, inspection_states, state_transfer
from tests import xls_fixtures
from src.tools._paths import REFERENCE_DIR


class InspectionStateTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        patcher = patch.object(server, "DB_PATH", self.root / "test.db")
        patcher.start()
        self.addCleanup(patcher.stop)
        server.init_db()

    def workbook(self, entries, filename="inspection.xlsx"):
        rows = [["大修号", "机组号", "通道编号", "三字码", "幅值", "备注", "堵管移位信息"]]
        rows += [["F102", 1, tube, "WAR", 1.2, note, detail] for tube, note, detail in entries]
        source = self.root / filename
        if source.suffix == ".xls":
            xls_fixtures.build_xls(source, [("检查记录", rows)])
        else:
            book = server.Workbook()
            book.active.title = "检查记录"
            for row in rows:
                book.active.append(row)
            state_transfer.save_workbook_exact(book, source)
            book.close()
        return source

    def import_entries(self, entries, filename="inspection.xlsx"):
        return server.import_excel_file(str(self.workbook(entries, filename)), "review")

    def test_excel_remarks_and_maintenance_fields_recognized_verbatim(self):
        for suffix in (".xlsx", ".xls"):
            with self.subTest(suffix=suffix):
                note = " \t本次检查后堵管；\r\n现场　复核（保留全角）。  "
                detail = " 后移位－４２ｍｍ；\n来源：这句话本身属于原文 "
                tube = 1 if suffix == ".xlsx" else 3
                result = self.import_entries([(tube, note, ""), (tube + 1, "", detail)], "inspection" + suffix)
                self.assertEqual(result["state_recognition"], dict(applied=2, pending=0, skipped=0))
                states = {r["thimble_id"]: r for r in server.query_states()["items"]}
                self.assertEqual(states[tube]["note"], note)
                self.assertEqual(states[tube + 1]["note"], detail)
                self.assertEqual(states[tube + 1]["offset_mm"], -42)
                self.assertIn(f"检查记录 第2行 · 备注", states[tube]["source"])
                with server.connect() as db:
                    self.assertEqual(db.execute("SELECT analysis FROM findings WHERE thimble_id=?", (tube,)).fetchone()[0], note)

    def test_dry_run_and_nonmaintenance_remarks_never_write_states(self):
        source = self.workbook([(1, "检查后堵管", ""), (2, "未见缺陷", "")])
        result = server.import_excel_file(str(source), "check")
        self.assertEqual(result["state_recognition"]["applied"], 0)
        self.assertEqual(server.query_states(), {"items": [], "pending": []})
        self.assertEqual(server.query_findings({})["total"], 0)
        self.import_entries([(2, "未见缺陷", ""), (3, "二次分析合格", "")])
        self.assertEqual(server.query_states(), {"items": [], "pending": []})

    def test_uncertain_scopes_history_plans_and_distinct_notes_are_pending(self):
        originals = [
            (1, "检查后移位42mm", ""),
            (2, "建议换管", ""),
            (3, "此前堵管，本次可检查", ""),
            (4, "F103换管", ""),
            (5, "通道006堵管", ""),
            (6, "移位+42mm并堵管", ""),
            (7, "堵管，原始说明一", "堵管，原始说明二"),
        ]
        result = self.import_entries(originals)
        self.assertEqual(result["state_recognition"], dict(applied=2, pending=6, skipped=0))
        pending = server.query_states()["pending"]
        self.assertEqual(len(pending), 6)
        self.assertEqual({r["note"] for r in pending}, {s for tube, n, d in originals if tube not in (1, 6) for s in (n, d) if s})
        self.assertTrue(all(r["source"] and r["review_reason"] for r in pending))
        self.assertEqual(server.query_states()["items"][0]["offset_mm"], 42)
        self.assertIsNone(server.query_states()["items"][0]["unsigned_offset_mm"])

    def test_unsigned_distance_applies_without_direction_review_in_excel_import(self):
        for suffix, first_tube in [(".xlsx", 1), (".xls", 5)]:
            notes = ["移位42mm", "割管移位42mm", "位移距离42mm", "移位-42mm"]
            with self.subTest(suffix=suffix):
                result = self.import_entries(
                    [(first_tube + i, note, "") for i, note in enumerate(notes)], "default-direction" + suffix)
                self.assertEqual(result["state_recognition"], dict(applied=4, pending=0, skipped=0))
                states = {r["thimble_id"]: r for r in server.query_states()["items"]}
                for i, expected in enumerate([42, 42, 42, -42]):
                    row = states[first_tube + i]
                    self.assertEqual((row["state"], row["offset_mm"], row["unsigned_offset_mm"]),
                                     ("shifted", expected, None))
                    self.assertEqual(row["note"], notes[i])
                self.assertEqual(server.query_states()["pending"], [])

    def test_legacy_event_sheet_normalizes_distance_but_rejects_invalid_values(self):
        from openpyxl import load_workbook
        source = self.workbook([(i, "", "") for i in range(1, 6)], "legacy-events.xlsx")
        book = load_workbook(source)
        sheet = book.create_sheet("管状态事件")
        sheet.append(["基地", "基地代码", "状态", "大修号", "机组号", "通道编号", "堆芯位置",
                      "状态代码", "有符号位移mm", "方向未确认距离mm", "方向已确认", "备注原文", "维护来源", "移位方向"])
        for tube, signed, unsigned, confirmed in [
            (1, None, 42, "否"), (2, -12, None, "是"), (3, None, None, "否"),
            (4, None, -1, "否"), (5, 0, None, "是"),
        ]:
            sheet.append(["防城港", "F", "移位", "F102", 1, tube, server.position_for(1, tube),
                          "shifted", signed, unsigned, confirmed, f"原记录{tube}", "旧导出表",
                          "负向" if tube == 1 else ""])
        state_transfer.save_workbook_exact(book, source)
        book.close()
        result = server.import_excel_file(str(source), "review")
        self.assertEqual(result["state_recognition"], dict(applied=4, pending=0, skipped=1))
        states = {r["thimble_id"]: r for r in server.query_states()["items"]}
        self.assertEqual({tube: r["offset_mm"] for tube, r in states.items()},
                         {1: -42, 2: -12, 3: None, 5: 0})
        self.assertTrue(all(r["unsigned_offset_mm"] is None for r in states.values()))
        self.assertEqual(states[1]["source"], "旧导出表")

    def test_existing_and_revoked_states_are_never_overwritten(self):
        for tube in (1, 2):
            row = dict(outage="F102", unit_id=1, thimble_id=tube, state="normal", offset_mm=0, note="人工状态", source="人工来源")
            server.save_tube_state(row)
            if tube == 2:
                server.save_tube_state(row, revoke=True)
        result = self.import_entries([(1, "检查后换管", ""), (2, "检查后堵管", "")])
        self.assertEqual(result["state_recognition"]["pending"], 2)
        items = server.query_states()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0]["state"], items[0]["note"], items[0]["source"]), ("normal", "人工状态", "人工来源"))
        self.assertTrue(all("已有" in r["review_reason"] for r in server.query_states()["pending"]))

    def test_repeated_import_is_idempotent_and_combines_source_separately(self):
        result = self.import_entries([(1, "检查后堵管", ""), (1, "检查后堵管", "")])
        self.assertEqual(result["state_recognition"], dict(applied=1, pending=0, skipped=0))
        row = server.query_states()["items"][0]
        self.assertEqual(row["note"], "检查后堵管")
        self.assertIn("第2行", row["source"])
        self.assertIn("第3行", row["source"])
        duplicate = self.import_entries([(1, "检查后堵管", "")], "duplicate.xlsx")
        self.assertEqual(duplicate["state_recognition"], dict(applied=0, pending=0, skipped=1))
        self.assertEqual(len(server.query_states()["items"]), 1)
        self.assertEqual(server.query_states()["pending"], [])

    def test_explicit_direction_column_is_imported_and_overrides_default(self):
        from openpyxl import Workbook

        source = self.root / "explicit-direction.xlsx"
        book = Workbook()
        sheet = book.active
        sheet.title = "检查记录"
        sheet.append(["大修号", "机组号", "通道编号", "三字码", "幅值", "备注", "有符号位移mm", "位移量(mm)", "移位方向"])
        sheet.append(["F102", 1, 1, "WAR", 1.2, "检查后移位42mm", None, None, "负向"])
        sheet.append(["F102", 1, 2, "WAR", 1.2, "检查后移位42mm", None, 42, "+"])
        sheet.append(["F102", 1, 3, "WAR", 1.2, "检查后移位42mm", -18, None, "正向"])
        sheet.append(["F102", 1, 4, "WAR", 1.2, "检查后移位42mm", None, -9, "正向"])
        state_transfer.save_workbook_exact(book, source)
        book.close()

        result = server.import_excel_file(str(source), "review")
        self.assertEqual(result["state_recognition"], dict(applied=4, pending=0, skipped=0))
        rows = {row["thimble_id"]: row for row in server.query_states()["items"]}
        self.assertEqual({tube: rows[tube]["offset_mm"] for tube in rows}, {1: -42, 2: 42, 3: -18, 4: -9})
        self.assertEqual(rows[1]["note"], "检查后移位42mm")
        self.assertEqual(rows[1]["unsigned_offset_mm"], None)

    def test_changing_default_direction_resolves_existing_unsigned_candidates(self):
        with server.connect() as db:
            db.execute("INSERT INTO state_preferences VALUES(1,'pending')")
        result = self.import_entries([(1, "移位41mm", ""), (2, "计划换管", "")])
        self.assertEqual(result["state_recognition"], dict(applied=0, pending=2, skipped=0))
        before = server.query_states()
        self.assertEqual(before["pending"][0]["unsigned_offset_mm"], 41)
        self.assertIsNone(before["pending"][0]["offset_mm"])
        self.assertEqual(before["pending"][0]["thimble_id"], 1)
        from src.backend import state_preferences
        state_preferences.save(server, {"shift_direction": "1"})
        after = server.query_states()
        self.assertEqual(after["pending"][0]["thimble_id"], 2)
        self.assertEqual(len(after["items"]), 1)
        self.assertEqual((after["items"][0]["offset_mm"], after["items"][0]["unsigned_offset_mm"]),
                         (41, None))

    def test_changing_default_direction_can_apply_negative_signed_value(self):
        with server.connect() as db:
            db.execute("INSERT INTO state_preferences VALUES(1,'pending')")
        self.import_entries([(1, "移位41mm", "")])
        from src.backend import state_preferences
        state_preferences.save(server, {"shift_direction": "-1"})
        row = server.query_states()["items"][0]
        self.assertEqual((row["offset_mm"], row["unsigned_offset_mm"]), (-41, None))

    def test_changing_default_direction_keeps_conflicting_shift_candidates_pending(self):
        with server.connect() as db:
            db.execute("INSERT INTO state_preferences VALUES(1,'pending')")
        self.import_entries([(1, "移位41mm", "")])
        self.import_entries([(1, "移位42mm", "")], "second-shift.xlsx")
        from src.backend import state_preferences
        state_preferences.save(server, {"shift_direction": "1"})
        self.assertEqual(server.query_states()["items"], [])
        pending = server.query_states()["pending"]
        self.assertEqual(len(pending), 2)
        self.assertTrue(all("留待核对" in row["review_reason"] for row in pending))

    def test_pending_confirm_dismiss_and_batch_rollback_restore(self):
        server.save_tube_state(dict(outage="F102", unit_id=1, thimble_id=1, state="normal", offset_mm=0, note="原记录"))
        result = self.import_entries([(1, "移位42mm", ""), (2, "计划换管", ""), (3, "检查后堵管", "")])
        pending = server.query_states()["pending"]
        first = {**pending[0], "offset_mm": -42}
        state_transfer.apply_batch(server, dict(rows=[first], confirmed=True))
        inspection_states.dismiss(server, dict(ids=[pending[1]["recognition_id"]], confirmed=True))
        self.assertEqual(server.query_states()["pending"], [])
        self.assertEqual(len(server.query_states()["items"]), 2)
        import_audit.change_batch(server, result["batch_id"], "rollback")
        self.assertEqual([(r["state"], r["note"]) for r in server.query_states()["items"]], [("normal", "原记录")])
        self.assertEqual(server.query_states()["pending"], [])
        self.assertEqual(server.query_findings({})["total"], 0)
        import_audit.change_batch(server, result["batch_id"], "restore")
        self.assertEqual(len(server.query_states()["items"]), 2)
        self.assertEqual(server.query_states()["pending"], [])
        self.assertEqual(server.query_findings({})["total"], 3)

    def test_pending_confirmation_rejects_stale_scope_or_maintenance(self):
        server.save_tube_state(dict(outage="F102", unit_id=1, thimble_id=1, state="normal", offset_mm=0, note="原记录"))
        self.import_entries([(1, "移位42mm", "")])
        candidate = {**server.query_states()["pending"][0], "offset_mm": -42}
        with self.assertRaisesRegex(ValueError, "范围"):
            state_transfer.apply_batch(server, dict(rows=[{**candidate, "thimble_id": 2}], confirmed=True))
        server.save_tube_state({**candidate, "note": "后续人工记录"})
        with self.assertRaisesRegex(ValueError, "已变化"):
            state_transfer.apply_batch(server, dict(rows=[candidate], confirmed=True))
        self.assertEqual(len(server.query_states()["pending"]), 1)
        self.assertEqual(server.query_states()["items"][0]["note"], "后续人工记录")

    def test_distance_free_shift_and_blocking_synonyms_apply_with_raw_notes(self):
        notes = [" \t割管移位\r\n现场　确认 ", "割管移位（切除42mm）",
                 "指套管自动阀后安装堵头进行封堵", "已封管"]
        result = self.import_entries([(i, note, "") for i, note in enumerate(notes, 1)])
        self.assertEqual(result["state_recognition"], dict(applied=4, pending=0, skipped=0))
        rows = {r["thimble_id"]: r for r in server.query_states()["items"]}
        self.assertEqual([rows[i]["state"] for i in range(1, 5)], ["shifted", "shifted", "plugged", "plugged"])
        self.assertIsNone(rows[1]["offset_mm"])
        self.assertIsNone(rows[1]["unsigned_offset_mm"])
        self.assertEqual((rows[2]["offset_mm"], rows[2]["unsigned_offset_mm"]), (42, None))
        self.assertEqual([rows[i]["note"] for i in range(1, 5)], notes)
        import_audit.change_batch(server, result["batch_id"], "rollback")
        self.assertEqual(server.query_states(), {"items": [], "pending": []})
        import_audit.change_batch(server, result["batch_id"], "restore")
        self.assertEqual([r["note"] for r in server.query_states()["items"]], notes)

    def test_negated_and_planned_synonyms_do_not_auto_apply(self):
        notes = ["未进行割管移位", "未封堵", "未发生堵塞", "拟封堵", "打开堵头检查"]
        result = self.import_entries([(i, note, "") for i, note in enumerate(notes, 1)])
        self.assertEqual(result["state_recognition"]["applied"], 0)
        self.assertEqual(server.query_states()["items"], [])
        self.assertEqual({r["note"] for r in server.query_states()["pending"]}, set(notes))

    def test_cut_shift_field_alias_and_queries_preserve_unknown_distance(self):
        source = self.root / "aliases.xlsx"
        book = server.Workbook()
        book.active.append(["大修号", "机组号", "通道编号", "三字码", "幅值", "磨损位置", "割管移位信息"])
        book.active.append(["F102", 1, 1, "WAR", 1.2, "P1", "割管移位"])
        state_transfer.save_workbook_exact(book, source)
        book.close()
        result = server.import_excel_file(str(source), "review")
        self.assertEqual(result["state_recognition"], dict(applied=1, pending=0, skipped=0))
        findings = server.query_findings({"outage": ["F102"]})["items"]
        self.assertEqual(findings[0]["state"], "shifted")
        self.assertIsNone(findings[0]["offset_mm"])
        self.assertIsNone(server.tube_history("F", 1, 1)["items"][0]["offset_mm"])
        self.assertIn("割管移位信息", server.query_states()["items"][0]["source"])

    def test_legacy_state_snapshots_rollback_restore_without_rewriting_audit(self):
        server.save_tube_state(dict(outage="F102", unit_id=1, thimble_id=1, state="normal", note="旧记录"))
        result = self.import_entries([(1, "移位+42mm", "")])
        candidate = server.query_states()["pending"][0]
        state_transfer.apply_batch(server, dict(rows=[candidate], confirmed=True))
        with server.connect() as db:
            change = db.execute("SELECT * FROM import_state_changes WHERE batch_id=?", (result["batch_id"],)).fetchone()
            legacy = []
            for name in ("before_json", "after_json"):
                values = json.loads(change[name])
                values.pop("offset_confirmed")
                values.pop("unsigned_offset_mm")
                legacy.append(json.dumps(values, ensure_ascii=False))
            db.execute("UPDATE import_state_changes SET before_json=?,after_json=? WHERE batch_id=?",
                       (*legacy, result["batch_id"]))
        server.init_db()
        import_audit.change_batch(server, result["batch_id"], "rollback")
        self.assertEqual(server.query_states()["items"][0]["note"], "旧记录")
        import_audit.change_batch(server, result["batch_id"], "restore")
        self.assertEqual(server.query_states()["items"][0]["offset_mm"], 42)
        with server.connect() as db:
            retained = db.execute("SELECT before_json,after_json FROM import_state_changes WHERE batch_id=?",
                                 (result["batch_id"],)).fetchone()
        self.assertEqual(list(retained), legacy)

    def test_import_failure_rolls_back_findings_states_and_candidates(self):
        source = self.workbook([(1, "检查后堵管", ""), (2, "检查后换管", "")])
        original = server.save_tube_state
        def fail(row, **kwargs):
            if row["thimble_id"] == 2:
                raise RuntimeError("state failure")
            return original(row, **kwargs)
        with patch.object(server, "save_tube_state", side_effect=fail), self.assertRaises(RuntimeError):
            server.import_excel_file(str(source), "review")
        self.assertEqual(server.query_findings({})["total"], 0)
        self.assertEqual(server.query_states(), {"items": [], "pending": []})
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM inspection_state_candidates").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM import_state_changes").fetchone()[0], 0)

    def test_later_manual_maintenance_prevents_partial_import_rollback(self):
        result = self.import_entries([(1, "检查后堵管", ""), (2, "移位42mm", "")])
        row = server.query_states()["items"][0]
        server.save_tube_state({**row, "note": "后续人工维护"})
        with self.assertRaisesRegex(ValueError, "后续维护"):
            import_audit.change_batch(server, result["batch_id"], "rollback")
        self.assertEqual(server.query_findings({})["total"], 2)
        self.assertEqual(len(server.query_states()["pending"]), 0)

    def test_directory_report_maintenance_remarks_are_recognized(self):
        from tests.test_server import write_sum, write_ect, write_report, report_entry
        group = self.root / "TH2I09CAL00001"
        group.mkdir()
        write_sum(group)
        write_ect(group, "DIR001C001I001.ECT", 1, 1, 1)
        note = " 本次检查后堵管；现场　复核。 "
        entry = report_entry("DIR001C001I001.ECT", 1, 1, 1, "a")
        entry = entry.replace("<Comment>note</Comment>", f"<Comment>{note}</Comment>")
        write_report(group, [entry])
        result = server.import_directory(str(self.root))
        self.assertEqual(result["state_recognition"], dict(applied=1, pending=0, skipped=0))
        row = server.query_states()["items"][0]
        self.assertEqual(row["note"], note)
        self.assertIn("comment", row["source"])

    def test_real_original_cell_enters_pending_verbatim_without_changing_source(self):
        source = Path(REFERENCE_DIR) / "指套管数据测试 202007/大亚湾/大亚湾基地各机组指套管割管统计.xlsx"
        raw = source.read_bytes()
        before = hashlib.sha256(raw).hexdigest()
        book = server.open_excel_workbook(source)
        try:
            note = list(book.worksheets[0].iter_rows(values_only=True))[1][2]
        finally:
            book.close()
        self.import_entries([(2, note, "")])
        pending = server.query_states()["pending"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["note"], note)
        self.assertIn("其他大修", pending[0]["review_reason"])
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)

    def test_manual_scopes_are_idempotent_and_survive_clear_restore(self):
        first = server.save_tube_state_scope({"site": "D", "unit_id": 1, "outage": "D117"})
        duplicate = server.save_tube_state_scope({"site": "D", "unit_id": 1, "outage": "D117"})
        self.assertTrue(first["created"])
        self.assertFalse(duplicate["created"])
        self.assertEqual(server.query_states()["scopes"], [{"outage": "D117", "unit_id": 1, "site": "D"}])
        with self.assertRaisesRegex(ValueError, "机组号与大修编号不一致"):
            server.save_tube_state_scope({"site": "F", "unit_id": 2, "outage": "F102"})

        export_dir = self.root / "backup-export"
        export_dir.mkdir()
        backup = server.create_database_backup(target=str(export_dir), note="scope roundtrip")
        cleared = server.clear_database()
        self.assertIn("tube_state_scopes", cleared["cleared"])
        self.assertNotIn("scopes", server.query_states())
        server.restore_database(backup["path"])
        self.assertEqual(server.query_states()["scopes"], [{"outage": "D117", "unit_id": 1, "site": "D"}])


if __name__ == "__main__":
    unittest.main()
