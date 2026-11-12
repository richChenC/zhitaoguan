from enterprise_fixtures import mark_legacy
import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.backend import server, state_transfer


class StateTransferTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        for name, value in (("DB_PATH", self.root / "test.db"), ("EXCEL_DIR", self.root / "exports"), ("REPORT_DIR", self.root / "reports")):
            patcher = patch.object(server, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        server.init_db()

    def row(self, tube=1, state="normal", offset=0):
        return dict(outage="D117", unit_id=1, thimble_id=tube, state=state, offset_mm=offset, note="test")

    def test_append_batch_keeps_each_tubes_evidence_and_unknown_direction(self):
        originals = [
            {**self.row(1, "shifted", -12), "events": ["shifted"], "note": "管1原始备注", "source": "台账1"},
            {**self.row(2, "shifted", None), "events": ["shifted"], "unsigned_offset_mm": 42,
             "direction": "pending", "note": "管2原始备注", "source": "台账2"},
        ]
        for row in originals:
            server.save_tube_state(row)
        payload = {"mode": "append", "bulk_edit": True, "only_unmaintained": False,
                   "rows": [{**self.row(tube, "plugged"), "events": ["plugged"],
                             "note": "本批维护依据", "source": "", "direction": "pending"} for tube in (1, 2)]}
        preview = state_transfer.preview_batch(server, payload)
        self.assertEqual(preview["affected"], 2)
        for row, original in zip(preview["rows"], originals):
            self.assertEqual(set(row["events"]), {"shifted", "plugged"})
            self.assertEqual(row["note"], original["note"] + "\n本批维护依据")
            self.assertEqual(row["source"], original["source"])
            self.assertEqual(row["offset_mm"], original["offset_mm"])
        result = state_transfer.apply_batch(server, {**payload, "confirmed": True, "revision": preview["revision"]})
        self.assertEqual(result["changed"], 2)
        with server.connect() as db:
            rows = [dict(row) for row in db.execute("SELECT * FROM tube_states ORDER BY thimble_id")]
            self.assertEqual(rows[0]["offset_mm"], -12)
            self.assertEqual(rows[1]["offset_confirmed"], 0)
            self.assertEqual(rows[1]["unsigned_offset_mm"], 42)
            self.assertEqual([row["source"] for row in rows], ["台账1", "台账2"])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tube_state_history").fetchone()[0], 4)
        with self.assertRaisesRegex(ValueError, "预览后维护记录已变化"):
            state_transfer.apply_batch(server, {**payload, "confirmed": True, "revision": preview["revision"]})
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tube_state_history").fetchone()[0], 4)

    def test_fill_normal_keeps_maintained_states_and_audit(self):
        server.save_tube_state(self.row(state="shifted", offset=-42))
        rows = [self.row(tube=i) for i in range(1, 51)]
        result = state_transfer.apply_batch(server, dict(rows=rows, confirmed=True, only_unmaintained=True))
        self.assertEqual((result["changed"], result["skipped"]), (49, 1))
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tube_states").fetchone()[0], 50)
            self.assertEqual(db.execute("SELECT state,offset_mm FROM tube_states WHERE thimble_id=1").fetchone()["offset_mm"], -42)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tube_state_history").fetchone()[0], 50)

    def test_invalid_batch_and_duplicate_never_partially_write(self):
        for rows in ([self.row(), self.row(tube=51)], [self.row(), self.row()], [self.row(tube=1.5)]):
            with self.assertRaises(ValueError):
                state_transfer.apply_batch(server, dict(rows=rows, confirmed=True))
        with self.assertRaises(ValueError):
            state_transfer.apply_batch(server, dict(rows=[self.row()]))
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tube_states").fetchone()[0], 0)

    def test_fill_normal_inherits_earlier_plug_from_same_batch(self):
        rows = [{**self.row(), "outage": "D119"},
                {**self.row(state="plugged"), "outage": "D118"}]
        payload = dict(rows=rows, only_unmaintained=True)
        preview = state_transfer.preview_batch(server, payload)
        self.assertEqual((preview["affected"], preview["skipped"]), (1, 1))
        self.assertEqual(preview["skipped_rows"], [
            dict(outage="D119", unit_id=1, thimble_id=1, reason="历史堵管仍有效")])
        self.assertTrue(preview["rows"][0]["after"]["plugged"])
        result = state_transfer.apply_batch(server, {
            **payload, "confirmed": True, "revision": preview["revision"]})
        self.assertEqual((result["changed"], result["skipped"]), (1, 1))
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tube_states").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tube_state_history").fetchone()[0], 1)
        scope = server.tube_state_scope(dict(outage=["D119"], unit_id=["1"]))
        self.assertEqual(len(scope["items"]), 50)
        self.assertTrue(scope["items"][0]["inherited_plug"])
        self.assertEqual(scope["items"][0]["plug_since"], "D118")

    def test_fill_normal_distinguishes_missing_from_eligible(self):
        server.save_tube_state({**self.row(tube=1), "outage": "D119"})
        server.save_tube_state({**self.row(tube=2, state="plugged"), "outage": "D118"})
        server.save_tube_state({**self.row(tube=3, state="shifted", offset=None), "outage": "D118"})
        rows = [{**self.row(tube=i), "outage": "D119"} for i in range(1, 5)]
        preview = state_transfer.preview_batch(server, dict(rows=rows, only_unmaintained=True))
        self.assertEqual([row["thimble_id"] for row in preview["rows"]], [4])
        self.assertEqual({row["thimble_id"]: row["reason"] for row in preview["skipped_rows"]},
                         {1: "本次已有维护记录", 2: "历史堵管仍有效", 3: "历史状态待核对"})
        result = state_transfer.apply_batch(server, dict(rows=rows, only_unmaintained=True,
                                                         confirmed=True, revision=preview["revision"]))
        self.assertEqual((result["changed"], result["skipped"]), (1, 3))

    def test_fill_normal_keeps_review_created_in_same_batch(self):
        for initial in (
                self.row(state="shifted", offset=None),
                {**self.row(state="replaced"), "events": ["replaced", "shifted"],
                 "offset_mm": -12, "replacement_stage": "unknown"}):
            with self.subTest(events=initial.get("events", initial["state"])):
                payload = dict(rows=[{**self.row(), "outage": "D119"},
                                     {**initial, "outage": "D118"}], only_unmaintained=True)
                preview = state_transfer.preview_batch(server, payload)
                self.assertEqual((preview["affected"], preview["skipped"]), (1, 1))
                self.assertEqual(preview["skipped_rows"][0]["reason"], "历史状态待核对")
                self.assertTrue(preview["rows"][0]["after"]["needs_review"])
                with server.connect() as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM tube_states").fetchone()[0], 0)

    def test_multi_outage_preview_and_save_agree_after_replacement(self):
        rows = [{**self.row(), "outage": "D120"},
                {**self.row(state="replaced"), "outage": "D119"},
                {**self.row(state="plugged"), "outage": "D118"}]
        preview = state_transfer.preview_batch(server, dict(rows=rows))
        self.assertEqual([row["after"]["state"] for row in preview["rows"]],
                         ["plugged", "replaced", "normal"])
        self.assertEqual(preview["rows"][-1]["after"]["generation"], 2)
        state_transfer.apply_batch(server, dict(rows=rows, confirmed=True, revision=preview["revision"]))
        for row in preview["rows"]:
            scope = server.tube_state_scope(dict(outage=[row["outage"]], unit_id=["1"]))
            self.assertEqual({k: v for k, v in scope["items"][0].items() if k != "thimble_id"},
                             row["after"])

    def test_explicit_overwrite_resets_offset_and_keeps_history(self):
        server.save_tube_state(self.row(state="shifted", offset=-42))
        result = state_transfer.apply_batch(server, dict(rows=[self.row()], confirmed=True))
        self.assertEqual(result["changed"], 1)
        with server.connect() as db:
            row = db.execute("SELECT state,offset_mm FROM tube_states").fetchone()
            self.assertEqual((row["state"], row["offset_mm"]), ("normal", 0))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tube_state_history").fetchone()[0], 2)

    def test_import_revision_protects_existing_rows_until_explicitly_selected(self):
        existing = {**self.row(state="plugged"), "note": "当前记录"}
        server.save_tube_state(existing)
        with server.connect() as db:
            revision = state_transfer.tube_lifecycle.revision(db)
        incoming = {**self.row(state="shifted", offset=-12), "note": "导入记录"}
        with self.assertRaisesRegex(ValueError, "已拦截覆盖"):
            state_transfer.apply_batch(server, {
                "rows": [incoming], "confirmed": True, "import_revision": revision})
        result = state_transfer.apply_batch(server, {
            "rows": [{**incoming, "overwrite_existing": True}], "confirmed": True,
            "import_revision": revision})
        self.assertEqual(result["changed"], 1)
        self.assertEqual(server.query_states()["items"][0]["state"], "plugged")
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tube_state_history").fetchone()[0], 2)

    def test_import_revision_rejects_changes_after_preview(self):
        with server.connect() as db:
            revision = state_transfer.tube_lifecycle.revision(db)
        server.save_tube_state(self.row(state="plugged"))
        with self.assertRaisesRegex(ValueError, "预览后维护记录已变化"):
            state_transfer.apply_batch(server, {
                "rows": [self.row(tube=2)], "confirmed": True, "import_revision": revision})

    def test_import_preview_reports_same_different_and_revoked(self):
        server.save_tube_state(self.row())
        server.save_tube_state(self.row(tube=2, state="shifted", offset=-12))
        server.save_tube_state(self.row(tube=3))
        server.save_tube_state(self.row(tube=3), revoke=True)
        content = "大修批次,机组号,通道编号,管状态,位移量(mm),备注\n"
        content += "\n".join(f"D117,1,{tube},正常,0,test" for tube in range(1, 5))
        preview = state_transfer.preview(server, {"filename": "states.csv",
            "content": base64.b64encode(content.encode("utf-8")).decode()})
        self.assertEqual([row.get("existing_status") for row in preview["rows"]],
                         ["same", "different", "revoked", None])
        self.assertEqual(preview["rows"][1]["existing_offset_mm"], -12)
        self.assertTrue(preview["revision"])

    def test_plug_cannot_be_removed_by_edit_without_replacement(self):
        server.save_tube_state({**self.row(state="plugged"), "events": ["plugged"]})
        with self.assertRaisesRegex(ValueError, "堵管不能"):
            server.save_tube_state({**self.row(state="shifted", offset=12), "events": ["shifted"]})
        current = server.query_states()["items"][0]
        self.assertEqual(current["events"], ["plugged"])

    def test_bulk_import_stacks_shift_on_existing_plug_and_preserves_evidence(self):
        server.save_tube_state({**self.row(state="plugged"), "events": ["plugged"],
                                "note": "堵管原始备注", "source": "堵管台账.xlsx"})
        incoming = {**self.row(state="shifted", offset=-12), "events": ["shifted"],
                    "note": "后续移位", "source": "移位记录.docx"}
        state_transfer.apply_batch(server, {"rows": [incoming], "confirmed": True})
        current = server.query_states()["items"][0]
        self.assertEqual(current["events"], ["plugged", "shifted"])
        self.assertEqual(current["state"], "plugged")
        self.assertEqual(current["offset_mm"], -12)
        self.assertEqual(current["note"], "堵管原始备注\n后续移位")
        self.assertEqual(current["source"], "堵管台账.xlsx\n移位记录.docx")

    def test_append_batch_preserves_note_and_rejects_stale_preview(self):
        server.save_tube_state({**self.row(state="shifted", offset=-12),
                                "events": ["shifted"], "note": "原始记录", "source": "台账.xlsx"})
        row = {**self.row(state="plugged"), "events": ["plugged"], "note": "补充堵管",
               "replacement_stage": "unknown"}
        preview = state_transfer.preview_batch(server, {"rows": [row], "mode": "append"})
        self.assertEqual(preview["rows"][0]["after"]["state"], "plugged")
        server.save_tube_state({**self.row(2), "note": "并发修改"})
        with self.assertRaisesRegex(ValueError, "重新预览"):
            state_transfer.apply_batch(server, {"rows": [row], "mode": "append",
                                                "confirmed": True, "revision": preview["revision"]})
        current = server.query_states()["items"]
        tube = next(item for item in current if item["thimble_id"] == 1)
        self.assertEqual(tube["note"], "原始记录")
        self.assertEqual(tube["source"], "台账.xlsx")
        self.assertEqual(tube["events"], ["shifted"])

    def test_import_normal_keeps_composite_plug_shift_distance(self):
        server.save_tube_state({**self.row(state="plugged", offset=-42),
                                "events": ["plugged", "shifted"]})
        state_transfer.apply_batch(server, {"rows": [self.row()], "confirmed": True})
        current = server.query_states()["items"][0]
        self.assertEqual(current["events"], ["plugged", "shifted"])
        self.assertEqual(current["offset_mm"], -42)

    def test_append_new_event_to_replacement_requires_new_order_review(self):
        server.save_tube_state({**self.row(state="replaced"), "events": ["replaced"]})
        preview = state_transfer.preview_batch(server, {
            "rows": [{**self.row(state="plugged"), "events": ["plugged"]}], "mode": "append"})
        self.assertTrue(preview["rows"][0]["after"]["needs_review"])
        self.assertIn("待核对", preview["rows"][0]["after"]["state_label"])

    def test_composite_events_and_replacement_order_roundtrip(self):
        for tube, stage in [(1, "before_replacement"), (2, "after_replacement"), (3, "unknown")]:
            server.save_tube_state({**self.row(tube, "plugged", -42),
                                    "events": ["plugged", "shifted", "replaced"],
                                    "replacement_stage": stage, "note": "原始复合处理"})
        for fmt in ("xlsx", "summary", "docx"):
            with self.subTest(format=fmt):
                result = state_transfer.export(server, dict(outage="D117", unit_id=1, format=fmt))
                path = Path(result.get("file_path") or server.EXCEL_DIR / result["filename"])
                preview = state_transfer.preview(server, dict(filename=result["filename"],
                    content=base64.b64encode(path.read_bytes()).decode()))
                self.assertEqual(preview["warnings"], [])
                self.assertEqual(len(preview["rows"]), 3)
                for row, stage in zip(preview["rows"], ("before_replacement", "after_replacement", "unknown")):
                    self.assertEqual(row["events"], ["plugged", "shifted", "replaced"])
                    self.assertEqual(row["replacement_stage"], stage)
                    self.assertEqual(row["offset_mm"], -42)
                    self.assertEqual(row["note"], "原始复合处理")

    def test_history_timeline_keeps_plug_until_replacement(self):
        server.save_tube_state({**self.row(state="plugged"), "outage": "D115"})
        server.save_tube_state({**self.row(state="shifted", offset=-42), "outage": "D116"})
        server.save_tube_state({**self.row(state="replaced"), "outage": "D117"})
        result = server.tube_state_history({"site": ["D"], "unit_id": ["1"], "thimble_id": ["1"]})
        self.assertEqual([row["outage"] for row in result["timeline"]], ["D115", "D116", "D117"])
        self.assertEqual([row["effective"]["state_label"] for row in result["timeline"]],
                         ["堵管", "堵管 · 移位", "换管"])
        self.assertEqual(result["timeline"][-1]["effective"]["generation"], 2)
        self.assertEqual(len(result["items"]), 3)

    def test_database_failure_rolls_back_all_rows(self):
        original = server.save_tube_state
        def fail_second(row, **kwargs):
            if row["thimble_id"] == 2:
                raise ValueError("injected failure")
            return original(row, **kwargs)
        with patch.object(server, "save_tube_state", side_effect=fail_second):
            with self.assertRaises(ValueError):
                state_transfer.apply_batch(server, dict(rows=[self.row(), self.row(tube=2)], confirmed=True))
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tube_states").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tube_state_history").fetchone()[0], 0)

    def test_excel_roundtrip_skips_blank_states(self):
        server.save_tube_state(self.row(state="shifted", offset=-42))
        result = state_transfer.export(server, dict(outage="D117", unit_id=1))
        content = (server.EXCEL_DIR / result["filename"]).read_bytes()
        imported = state_transfer.preview(server, dict(filename=result["filename"], content=base64.b64encode(content).decode()))
        self.assertEqual(len(imported["rows"]), 1)
        self.assertEqual(imported["rows"][0]["offset_mm"], -42)
        self.assertEqual(imported["rows"][0]["state"], "shifted")

    def test_history_summary_export_preserves_states_notes_and_sources_without_fake_cut_counts(self):
        note = " \t割管移位\r\n原文完全保留　 "
        source = "原始台账.xlsx · Sheet1!D18"
        server.save_tube_state({**self.row(1, "shifted", None), "outage": "D116",
                                "unsigned_offset_mm": 42, "note": note, "source": source})
        server.save_tube_state({**self.row(2, "plugged"), "outage": "D117",
                                "note": "封堵原文", "source": "堵管记录.docx"})
        server.save_tube_state({**self.row(3, "replaced"), "outage": "D117",
                                "note": "已换管", "source": "维护表.xlsx"})
        result = state_transfer.export(server, dict(outage="D117", unit_id=1, format="summary"))
        book = server.open_excel_workbook(server.EXCEL_DIR / result["filename"])
        try:
            matrix = book["历次状态统计"]
            self.assertEqual(matrix["A1"].value, "大亚湾基地 1号机组 指套管状态统计表")
            self.assertIsNone(matrix["A1"].fill.fill_type)
            self.assertEqual(matrix["A5"].value, "D116 · 通道号")
            self.assertEqual(matrix["B7"].value, "移位")
            self.assertEqual(matrix["B8"].value, 42)
            self.assertEqual(matrix["B9"].value, note)
            self.assertEqual(matrix["A11"].value, "D117 · 通道号")
            self.assertEqual(matrix["C13"].value, "堵管")
            self.assertEqual(matrix["D13"].value, "换管")
            self.assertNotIn("割管次数", [cell.value for row in matrix.iter_rows() for cell in row])
            self.assertIn("不推算", matrix["B3"].value)
            self.assertEqual(book["来源"]["C2"].value, source)
            self.assertEqual(book["管状态维护"]["F3"].value, "封堵原文")
            self.assertIsNone(book["来源"]["A1"].fill.fill_type)
            self.assertIsNone(book["管状态维护"]["A1"].fill.fill_type)
        finally:
            book.close()
        exported = state_transfer.preview(server, dict(filename=result["filename"],
            content=base64.b64encode((server.EXCEL_DIR / result["filename"]).read_bytes()).decode()))
        self.assertEqual(exported["warnings"], [])
        self.assertEqual({row["note"] for row in exported["rows"]}, {"封堵原文", "已换管"})

    def test_csv_aliases_current_scope_and_invalid_offsets(self):
        text = "管号,状态,位移量,备注\n1,移位,+42,人工记录\n2,正常,0,正常记录\n3,,,\n"
        payload = dict(filename="state.csv", content=base64.b64encode(text.encode("utf-8-sig")).decode(), outage="D117", unit_id=1)
        rows = state_transfer.preview(server, payload)["rows"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["offset_mm"], 42)
        self.assertIsNone(state_transfer.validate_rows(server, [self.row(state="shifted", offset="")])[0]["offset_mm"])
        unsigned = state_transfer.validate_rows(server, [{**self.row(state="shifted", offset=None), "unsigned_offset_mm": "42"}])[0]
        self.assertEqual(unsigned["offset_mm"], 42)
        self.assertIsNone(unsigned["unsigned_offset_mm"])
        with self.assertRaises(ValueError):
            state_transfer.validate_rows(server, [self.row(state="shifted", offset="invalid")])
        for value in ("invalid", "nan", -1, 1001):
            with self.subTest(unsigned=value), self.assertRaises(ValueError):
                state_transfer.validate_rows(server, [{**self.row(state="shifted", offset=None), "unsigned_offset_mm": value}])
        with self.assertRaises(ValueError):
            state_transfer.validate_rows(server, [self.row(state="normal", offset=42)])

    def test_preview_pending_policy_does_not_guess_unsigned_direction(self):
        text = "管号,状态,位移量,备注\n1,移位,42,人工记录\n2,移位,-25,已明确方向\n"
        payload = dict(filename="state.csv", content=base64.b64encode(text.encode("utf-8-sig")).decode(),
                       outage="D117", unit_id=1)
        default_rows = state_transfer.preview(server, payload)["rows"]
        pending_rows = state_transfer.preview(server, {**payload, "direction_policy": "pending"})["rows"]
        self.assertEqual(default_rows[0]["offset_mm"], 42)
        self.assertIsNone(pending_rows[0]["offset_mm"])
        self.assertEqual(pending_rows[0]["unsigned_offset_mm"], 42)
        self.assertEqual(pending_rows[1]["offset_mm"], -25)
        with self.assertRaisesRegex(ValueError, "方向策略"):
            state_transfer.preview(server, {**payload, "direction_policy": "invalid"})

    def test_export_reimport_preserves_notes_without_reclassifying_history(self):
        notes = {
            1: "  历史曾移位４２ｍｍ；\n本次人工确认正常（原文）。　 ",
            2: "\t检查后移位４２ｍｍ；\r\n切除４２ｍｍ，方向按处理记录确认。 ",
            3: "=原文符号保留；\n后换管（请保留原文）。来源：这也是原文",
        }
        sources = {tube: f"原台账.xlsx · 第{tube}行\r\n另一条来源\t " for tube in notes}
        for tube, state, offset in [(1, "normal", 0), (2, "shifted", -42), (3, "replaced", 0)]:
            server.save_tube_state({**self.row(tube, state, offset), "note": notes[tube], "source": sources[tube]})
        for _ in range(2):
            result = state_transfer.export(server, dict(outage="D117", unit_id=1))
            raw = (server.EXCEL_DIR / result["filename"]).read_bytes()
            preview = state_transfer.preview(server, dict(filename=result["filename"], content=base64.b64encode(raw).decode()))
            self.assertEqual(preview["warnings"], [])
            self.assertEqual({r["thimble_id"]: r["note"] for r in preview["rows"]}, notes)
            self.assertEqual({r["thimble_id"]: r["source"] for r in preview["rows"]}, sources)
            self.assertEqual({r["thimble_id"]: r["state"] for r in preview["rows"]}, {1: "normal", 2: "shifted", 3: "replaced"})
            state_transfer.apply_batch(server, {"rows": preview["rows"], "confirmed": True})
            self.assertEqual({r["thimble_id"]: r["note"] for r in server.query_states()["items"]}, notes)

    def test_word_roundtrip_retains_raw_notes_and_separate_sources(self):
        note = " \t原文：此前移位４２ｍｍ；\r\n现在堵管。来源：本句就是原文　 "
        source = "维护表.docx · 表1\r\n第2行\t "
        server.save_tube_state({**self.row(state="plugged"), "note": note, "source": source})
        result = state_transfer.export(server, dict(outage="D117", unit_id=1, format="docx"))
        preview = state_transfer.preview(server, dict(filename=result["filename"],
            content=base64.b64encode(Path(result["file_path"]).read_bytes()).decode()))
        self.assertEqual(preview["warnings"], [])
        self.assertEqual(len(preview["rows"]), 1)
        self.assertEqual((preview["rows"][0]["note"], preview["rows"][0]["source"]), (note, source))

    def test_manual_save_keeps_source_and_stale_source_blocks_deletion(self):
        server.save_tube_state({**self.row(), "source": "原表.xlsx"})
        server.save_tube_state({**self.row(), "note": "人工更新"})
        selected = server.query_states()["items"]
        self.assertEqual(selected[0]["source"], "原表.xlsx")
        server.save_tube_state({**self.row(), "note": "人工更新", "source": "来源已更新"})
        with self.assertRaisesRegex(ValueError, "已变化"):
            state_transfer.delete_batch(server, {"confirmed": True, "rows": selected})

    def test_missing_and_unsigned_distances_save_export_reimport_and_delete(self):
        notes = {1: " \t割管移位\r\n原文　 ", 2: "割管移位（切除42mm）", 3: "移位+0mm", 4: "移位+42mm"}
        for tube, offset, unsigned in [(1, None, None), (2, None, 42), (3, 0, None), (4, 42, None)]:
            server.save_tube_state({**self.row(tube, "shifted", offset), "unsigned_offset_mm": unsigned,
                                   "note": notes[tube], "source": "原表"})
        for fmt in ("xlsx", "docx"):
            exported = state_transfer.export(server, dict(outage="D117", unit_id=1, format=fmt))
            preview = state_transfer.preview(server, dict(filename=exported["filename"],
                content=base64.b64encode(Path(exported.get("file_path") or server.EXCEL_DIR / exported["filename"]).read_bytes()).decode()))
            self.assertEqual(preview["warnings"], [])
            rows = {r["thimble_id"]: r for r in preview["rows"]}
            self.assertEqual(len(rows), 4)
            self.assertEqual((rows[1]["offset_mm"], rows[1]["unsigned_offset_mm"]), (None, None))
            self.assertEqual((rows[2]["offset_mm"], rows[2]["unsigned_offset_mm"]), (42, None))
            self.assertEqual(rows[3]["offset_mm"], 0)
            self.assertEqual(rows[4]["offset_mm"], 42)
            self.assertIsNone(rows[4]["unsigned_offset_mm"])
            self.assertEqual({tube: row["note"] for tube, row in rows.items()}, notes)
            state_transfer.apply_batch(server, {"rows": list(rows.values()), "confirmed": True})
        selected = server.query_states()["items"]
        state_transfer.delete_batch(server, {"rows": selected, "confirmed": True})
        self.assertEqual(server.query_states()["items"], [])

    def test_missing_distance_stays_pending_but_unsigned_distance_defaults_positive(self):
        with server.connect() as db:
            for outage in ("F101", "F102"):
                db.execute("""INSERT INTO findings(outage,unit_id,thimble_id,position,indication,percent,location,imported_at)
                    VALUES(?,1,1,?,'WAR',20,'P1','now')""", (outage, server.position_for(1, 1)))
        base = dict(outage="F101", unit_id=1, thimble_id=1, state="割管移位", note="割管移位")
        server.save_tube_state({**base, "unsigned_offset_mm": None})
        maintained = server.query_states()["items"][0]
        self.assertEqual(maintained["state"], "shifted")
        self.assertIsNone(maintained["offset_mm"])
        self.assertIsNone(maintained["unsigned_offset_mm"])
        result = server.compare("F101", "F102", 1)
        self.assertEqual(result["summary"]["待确认"], 1)
        self.assertIsNone(result["items"][0]["shift_mm"])
        self.assertIsNone(result["items"][0]["old_id"])
        self.assertIn("距离或方向未明确", result["items"][0]["comparison_note"])

        server.save_tube_state({**base, "unsigned_offset_mm": 42})
        maintained = server.query_states()["items"][0]
        self.assertEqual(maintained["offset_mm"], 42)
        self.assertIsNone(maintained["unsigned_offset_mm"])
        result = server.compare("F101", "F102", 1)
        item = next(row for row in result["items"] if row.get("thimble_id") == 1)
        self.assertEqual(result["summary"]["待确认"], 1)
        self.assertEqual(item["shift_mm"], 42)
        self.assertEqual(item["comparison"], "待确认")
        server.save_tube_state({**base, "offset_mm": 0})
        self.assertEqual(server.compare("F101", "F102", 1)["summary"]["R"], 1)

    def test_legacy_unsigned_records_remain_readable_and_deletable(self):
        with server.connect() as db:
            db.execute("""INSERT INTO tube_states(
                outage,unit_id,thimble_id,state,offset_mm,offset_confirmed,unsigned_offset_mm,note)
                VALUES('D117',1,1,'shifted',0,0,42,'旧记录')""")
        record = server.query_states()["items"][0]
        self.assertEqual((record["offset_mm"], record["unsigned_offset_mm"]), (None, 42))
        normalized = state_transfer.validate_rows(server, [record])[0]
        self.assertEqual((normalized["offset_mm"], normalized["unsigned_offset_mm"]), (42, None))
        self.assertEqual(server.query_states()["items"][0], record)
        state_transfer.delete_batch(server, dict(rows=[record], confirmed=True))
        self.assertEqual(server.query_states()["items"], [])

    def test_direct_save_validates_unsigned_distance_before_applying_default(self):
        for value in (-1, 1001, "invalid", "nan", "inf"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                server.save_tube_state({**self.row(state="shifted", offset=None), "unsigned_offset_mm": value})
        self.assertEqual(server.query_states()["items"], [])
        composite = {**self.row(state="plugged", offset=None), "events": ["plugged", "shifted"],
                     "unsigned_offset_mm": 42}
        normalized = state_transfer.validate_rows(server, [composite])[0]
        self.assertEqual((normalized["offset_mm"], normalized["unsigned_offset_mm"]), (42, None))
        server.save_tube_state(composite)
        saved = server.query_states()["items"][0]
        self.assertEqual((saved["offset_mm"], saved["unsigned_offset_mm"]), (42, None))

    def test_existing_signed_shift_survives_schema_upgrade(self):
        with server.connect() as db:
            db.execute("DROP TABLE tube_states")
            db.execute("""CREATE TABLE tube_states (
                outage TEXT NOT NULL, unit_id INTEGER NOT NULL, thimble_id INTEGER NOT NULL,
                state TEXT NOT NULL DEFAULT 'normal', offset_mm REAL NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT '', PRIMARY KEY(outage,unit_id,thimble_id))""")
            db.execute("INSERT INTO tube_states VALUES('F101',1,1,'shifted',-42,'原记录')")
        mark_legacy(server)
        server.init_db()
        row = server.query_states()["items"][0]
        self.assertEqual((row["offset_mm"], row["note"]), (-42, "原记录"))
        self.assertIsNone(row["unsigned_offset_mm"])


if __name__ == "__main__":
    unittest.main()
