import base64
import hashlib
import json
import tempfile
import unittest
import io
from zipfile import ZipFile
from pathlib import Path
from unittest.mock import patch

from src.backend import server, state_transfer
from src.backend.state_recognition import recognize, parse_description
from src.tools._paths import REFERENCE_DIR


REFERENCE_DATA = Path(REFERENCE_DIR) / "指套管数据测试 202007"


class StateRecognitionTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = patch.object(server, "DB_PATH", Path(folder.name) / "test.db")
        patcher.start()
        self.addCleanup(patcher.stop)
        server.init_db()

    def preview(self, tables, outage="F102"):
        return recognize(tables, {"outage": outage, "unit_id": int(outage[1])}, "来源.xlsx")

    def record(self, tube=1, outage="F102", state="plugged"):
        return dict(outage=outage, unit_id=int(outage[1]), thimble_id=tube,
                    state=state, offset_mm=0, note="原始备注")

    def test_variable_columns_repeated_headers_and_notes_only(self):
        rows, warnings, matched = self.preview([("随意工作表", [
            ["维护台账"], ["说明", "通道号", "大修编号"],
            ["移位 -4.2 cm；现场复核", "001", "F102"],
            ["堵管处理", 2, "F102"], ["", 3, "F102"],
            ["说明", "通道号", "大修编号"], ["已更换", 4, "F102"],
        ])])
        self.assertTrue(matched)
        self.assertEqual(warnings, [])
        self.assertEqual({r["thimble_id"] for r in rows}, {1, 2, 4})
        first = next(r for r in rows if r["thimble_id"] == 1)
        self.assertEqual(first["offset_mm"], -42)
        self.assertIn("现场复核", first["note"])
        self.assertEqual(first["note"], "移位 -4.2 cm；现场复核")
        self.assertIn("来源.xlsx", first["source"])

    def test_unsigned_percent_negation_plans_and_conflicts(self):
        facts, _ = parse_description("割管移位50％（切除41mm）")
        self.assertEqual(facts["offset_mm"], 41)
        self.assertIsNone(facts["unsigned_offset_mm"])
        for value in ["未堵管；未换管；未移位", "建议移位42mm", "待堵管", "堵管并已更换"]:
            with self.subTest(value=value):
                self.assertIsNone(parse_description(value)[0])
        composite, reason = parse_description("割管移位42mm；堵管")
        self.assertEqual(reason, "")
        self.assertEqual(composite["state"], "plugged")
        self.assertEqual(composite["events"], ["plugged", "shifted"])
        self.assertEqual(composite["offset_mm"], 42)
        rows, warnings, _ = self.preview([("F102", [
            ["通道号", "处理情况"], [1, "移位42mm"], [1, "移位43mm"],
            [2, "堵管"], [2, "堵管"], [3, "正常"],
        ])])
        self.assertEqual({r["thimble_id"] for r in rows}, {2, 3})
        self.assertTrue(any("不同处理事件" in w for w in warnings))
        duplicate = next(r for r in rows if r["thimble_id"] == 2)
        self.assertEqual(duplicate["note"], "堵管")
        self.assertIn("第4行", duplicate["source"])
        self.assertIn("第5行", duplicate["source"])

    def test_default_positive_direction_preserves_explicit_signs_and_conflicts(self):
        for description, offset, expected in [
            ("移位42mm", None, 42), ("割管移位42mm", None, 42),
            ("位移距离42mm", None, 42), ("移位＋４２毫米", None, 42),
            ("移位－４.２厘米", None, -42), ("移位0mm", None, 0),
            ("移位42mm；移位+42mm", None, 42), ("移位", "42", 42),
            ("移位", "-42", -42),
        ]:
            with self.subTest(description=description, offset=offset):
                facts, reason = parse_description(description, offset)
                self.assertEqual(reason, "")
                self.assertEqual(facts, dict(state="shifted", offset_mm=expected, unsigned_offset_mm=None))
        self.assertIsNone(parse_description("移位42mm；移位-42mm")[0])

    def test_horizontal_flags_and_grouped_word_channels(self):
        rows, _, _ = self.preview([("任意表", [
            ["F102", "通道号", 1, 2, 3],
            ["", "是否堵管", "是", "否", "否"],
            ["", "备注", "现场封堵", "割管移位42mm", ""],
        ]), ("Word表", [["F102"], ["4、5、6更换通道007，L11移位41mm"]])])
        self.assertEqual({r["thimble_id"] for r in rows}, {1, 2, 4, 5, 6, 7})
        self.assertEqual(next(r for r in rows if r["thimble_id"] == 1)["state"], "plugged")
        shifted = next(r for r in rows if r["thimble_id"] == 2)
        self.assertEqual(shifted["offset_mm"], 42)
        self.assertIsNone(shifted["unsigned_offset_mm"])

    def test_horizontal_plugged_and_shifted_fields_are_combined(self):
        rows, warnings, _ = self.preview([("任意表", [
            ["F102", "通道号", 1],
            ["", "状态", "堵管"],
            ["", "堵管移位信息", "移位42mm"],
        ])])
        self.assertEqual(warnings, [])
        self.assertEqual(rows[0]["events"], ["plugged", "shifted"])
        self.assertEqual(rows[0]["offset_mm"], 42)

    def test_explicit_state_combines_dedicated_details_and_flags(self):
        note = " \t此前换管；原始备注保留\r\n本次复核。 "
        for values in [
            [["通道", "状态", "堵管移位信息", "是否封堵", "备注"],
             [1, "堵管", "移位42mm", "", note],
             [2, "移位", "", "是", note]],
            [["通道", 1, 2],
             ["状态", "堵管", "移位"],
             ["堵管移位信息", "移位42mm", ""],
             ["是否封堵", "", "是"],
             ["备注", note, note]],
        ]:
            with self.subTest(values=values):
                rows, warnings, _ = self.preview([("F102", values)])
                self.assertEqual(warnings, [])
                self.assertEqual(len(rows), 2)
                self.assertTrue(all(r["events"] == ["plugged", "shifted"] for r in rows))
                self.assertEqual(rows[0]["offset_mm"], 42)
                self.assertIsNone(rows[1]["offset_mm"])
                self.assertTrue(all(r["note"] == note for r in rows))

    def test_scope_is_not_reassigned_and_invalid_rows_warn(self):
        rows, warnings, _ = self.preview([("F103", [
            ["通道编号", "堵管移位信息"], [1, "移位42mm"],
        ]), ("F102", [
            ["机组号", "通道编号", "处理信息"], [2, 2, "堵管"], [1, 51, "换管"],
        ])])
        self.assertEqual(rows, [])
        self.assertTrue(any("不一致" in w for w in warnings))
        self.assertTrue(any("管号无效" in w for w in warnings))
        for title in ["N2", "F2"]:
            result, _, _ = self.preview([(title, [["管号", "状态"], [1, "堵管"]])])
            self.assertEqual(result, [])

    def test_mixed_user_source_preserves_full_event_in_warning(self):
        path = REFERENCE_DATA / "阳江/阳江RIC DATA(20200508).xlsx"
        result = state_transfer.preview(server, dict(filename=path.name, content=base64.b64encode(path.read_bytes()).decode(),
                                                    outage="Y104", unit_id=1))
        self.assertEqual({r["thimble_id"] for r in result["rows"]}, {6, 14, 16, 17})
        composite = [r for r in result["rows"] if r["thimble_id"] == 14]
        self.assertEqual(composite[0]["events"], ["plugged", "shifted"])
        self.assertEqual(composite[0]["offset_mm"], 42)

    def test_manual_note_identity_and_distance(self):
        data = {**self.record(), "note": "F102 通道001，割管移位（切除42mm），复核"}
        result = state_transfer.recognize_note(server, data)
        self.assertFalse(result["requires_direction"])
        self.assertEqual(result["rows"][0]["offset_mm"], 42)
        self.assertIn("复核", result["rows"][0]["note"])
        for note in ["F103 通道001堵管", "F102 通道002堵管", "建议更换", "未移位"]:
            with self.subTest(note=note), self.assertRaises(ValueError):
                state_transfer.recognize_note(server, {**data, "note": note})

    def test_explicit_state_preserves_historical_notes_without_reclassification(self):
        rows, warnings, _ = self.preview([("F102", [
            ["管号", "状态", "位移量", "备注"],
            [1, "正常", 0, "此前移位42mm，检查后人工确认恢复正常"],
            [2, "堵管", 0, "原文：割管移位50%（切除41mm）；已堵管"],
        ])])
        self.assertEqual(warnings, [])
        self.assertEqual([r["state"] for r in rows], ["normal", "plugged"])
        self.assertIn("此前移位42mm", rows[0]["note"])

    def test_batch_delete_is_exact_audited_and_keeps_findings(self):
        for row in [self.record(), self.record(2), self.record(1, "N101"), self.record(3, state="replaced")]:
            server.save_tube_state(row)
        with server.connect() as db:
            db.execute("INSERT INTO findings(outage,unit_id,thimble_id,imported_at) VALUES('F102',1,1,'test')")
        selection = [r for r in server.query_states()["items"] if r["outage"] == "F102" and r["state"] == "plugged"]
        result = state_transfer.delete_batch(server, dict(rows=selection, confirmed=True))
        self.assertEqual(result["deleted"], 2)
        self.assertEqual({(r["outage"], r["thimble_id"]) for r in server.query_states()["items"]}, {("N101", 1), ("F102", 3)})
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM findings WHERE is_deleted=0").fetchone()[0], 1)
            history = db.execute("SELECT * FROM tube_state_history WHERE action='revoke'").fetchall()
            self.assertEqual(len(history), 2)
            self.assertTrue(all(json.loads(h["before_json"])["note"] == "原始备注" for h in history))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM operation_logs WHERE operation_type='state_delete'").fetchone()[0], 1)

    def test_batch_delete_stale_selection_and_failure_roll_back(self):
        server.save_tube_state(self.record())
        server.save_tube_state(self.record(2))
        selection = server.query_states()["items"]
        with self.assertRaises(ValueError):
            state_transfer.delete_batch(server, dict(rows=selection))
        server.save_tube_state({**self.record(2), "note": "已更改"})
        with self.assertRaisesRegex(ValueError, "已变化"):
            state_transfer.delete_batch(server, dict(rows=selection, confirmed=True))
        selection = server.query_states()["items"]
        original = server.save_tube_state
        calls = 0
        def fail(row, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValueError("模拟写入失败")
            return original(row, **kwargs)
        with patch.object(server, "save_tube_state", side_effect=fail), self.assertRaises(ValueError):
            state_transfer.delete_batch(server, dict(rows=selection, confirmed=True))
        self.assertEqual(len(server.query_states()["items"]), 2)
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tube_state_history WHERE action='revoke'").fetchone()[0], 0)

    def test_all_seven_user_files(self):
        base = REFERENCE_DATA
        cases = [
            ("大亚湾/大亚湾基地各机组指套管割管统计.xlsx", "D118", {2, 12}),
            ("防城港/防城港指套管割管距离统计.docx", "F102", {1, 20, 41, 42}),
            ("防城港/F1 F2.xlsx", "F102", {1, 20, 41, 42}),
            ("红沿河/红沿河指套管割管距离统计.docx", "H204", {4, 15, 25, 34, 39, 43, 45, 46, 47}),
            ("宁德/宁德4台机组指套管割管移位信息汇总20200804.xls", "N101", {1, 16, 19, 25}),
            ("阳江/阳江RIC DATA(20200508).xlsx", "Y203", {14, 15, 19, 23, 25, 26, 39, 40, 45, 46, 48, 49}),
            ("指套管割管移位统计（含阳江、防城港、红沿河）.xlsx", "Y104", {14, 17}),
        ]
        for relative, outage, tubes in cases:
            with self.subTest(file=relative):
                path = base / relative
                self.assertTrue(path.is_file(), str(path))
                raw = path.read_bytes()
                before = hashlib.sha256(raw).hexdigest()
                result = state_transfer.preview(server, dict(filename=path.name, content=base64.b64encode(raw).decode(),
                                                            outage=outage, unit_id=int(outage[1])))
                self.assertEqual({r["thimble_id"] for r in result["rows"]}, tubes)
                self.assertTrue(all(r["outage"] == outage and path.name in r["source"] for r in result["rows"]))
                self.assertTrue(all("来源：" not in r["note"] for r in result["rows"]))
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
        self.assertEqual(server.query_states()["items"], [])

    def test_user_files_auto_detect_all_scopes_without_editor_selection(self):
        base = REFERENCE_DATA
        cases = [
            ("大亚湾/大亚湾基地各机组指套管割管统计.xlsx", 41, 15, {"D", "L"}),
            ("防城港/防城港指套管割管距离统计.docx", 25, 4, {"F"}),
            ("防城港/F1 F2.xlsx", 25, 4, {"F"}),
            ("红沿河/红沿河指套管割管距离统计.docx", 64, 16, {"H"}),
            ("宁德/宁德4台机组指套管割管移位信息汇总20200804.xls", 62, 14, {"N"}),
            ("阳江/阳江RIC DATA(20200508).xlsx", 56, 11, {"Y"}),
            ("指套管割管移位统计（含阳江、防城港、红沿河）.xlsx", 18, 7, {"Y", "F", "H"}),
        ]
        for relative, count, outages, sites in cases:
            with self.subTest(file=relative):
                path = base / relative
                raw = path.read_bytes()
                result = state_transfer.preview(server, dict(filename=path.name, content=base64.b64encode(raw).decode()))
                self.assertEqual(len(result["rows"]), count)
                self.assertEqual(len({r["outage"] for r in result["rows"]}), outages)
                self.assertEqual({server.outage_code(r["outage"]) for r in result["rows"]}, sites)
                self.assertEqual(result["missing_scopes"], [])
                self.assertTrue(all(r["unit_id"] == int(next(c for c in r["outage"] if c.isdigit())) for r in result["rows"]))
                self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(server.query_states()["items"], [])

    def test_filename_sheet_and_heading_scope_detection(self):
        cases = [
            ("F102维护.csv", "Sheet1", [], "F102"),
            ("维护.xlsx", "Sheet1", [["宁德一号机组第十三次大修维护台账"]], "N113"),
            ("防城港1号机组第二次大修维护.xlsx", "随意表", [], "F102"),
            ("维护.xlsx", "LF201", [], "LF201"),
        ]
        for filename, title, before, outage in cases:
            with self.subTest(file=filename):
                rows, warnings, _ = recognize([(title, before + [["管号", "状态"], [2, "堵管"]])], {}, filename)
                self.assertEqual([r["outage"] for r in rows], [outage])
                self.assertEqual(warnings, [])
        unresolved = []
        rows, _, _ = recognize([("N2", [["管号", "状态"], [2, "堵管"]])], {}, "F102.xlsx", unresolved)
        self.assertEqual(rows, [])
        self.assertEqual((unresolved[0]["site"], unresolved[0]["unit_id"]), ("N", 2))

    def test_missing_scope_is_supplemented_only_for_unscoped_records(self):
        content = base64.b64encode("管号,状态\n1,堵管\n2,F103 换管".encode()).decode()
        data = dict(filename="维护.csv", content=content)
        result = state_transfer.preview(server, data)
        self.assertEqual([r["outage"] for r in result["rows"]], ["F103"])
        self.assertEqual(result["missing_scopes"][0]["rows"], 1)
        result = state_transfer.preview(server, {**data, "scope_overrides": {"维护.csv": "N101"}})
        self.assertEqual({(r["outage"], r["thimble_id"]) for r in result["rows"]}, {("N101", 1), ("F103", 2)})
        self.assertEqual(result["missing_scopes"], [])
        self.assertEqual(server.query_states()["items"], [])
        with self.assertRaises(ValueError):
            state_transfer.preview(server, {**data, "scope_overrides": {"维护.csv": "bad"}})
        with self.assertRaisesRegex(ValueError, "不一致"):
            recognize([("N2", [["管号", "状态"], [1, "堵管"]])],
                      {"scope_overrides": {"N2": "F102"}}, "维护.xlsx")

    def test_word_heading_supplies_scope_without_current_filter(self):
        raw = io.BytesIO()
        xml = '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
        <w:p><w:r><w:t>防城港1号机组第二次大修维护</w:t></w:r></w:p>
        <w:tbl><w:tr><w:tc><w:p><w:r><w:t>管号</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>状态</w:t></w:r></w:p></w:tc></w:tr>
        <w:tr><w:tc><w:p><w:r><w:t>1</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>堵管</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
        </w:body></w:document>'''
        with ZipFile(raw, "w") as archive:
            archive.writestr("word/document.xml", xml)
        result = state_transfer.preview(server, dict(filename="维护.docx", content=base64.b64encode(raw.getvalue()).decode()))
        self.assertEqual([(r["outage"], r["thimble_id"]) for r in result["rows"]], [("F102", 1)])
        self.assertEqual(result["missing_scopes"], [])

    def test_original_cell_survives_normalization_and_event_splitting(self):
        original = " Ｄ１１７后换管；\nＤ１１８后移位４０ｍｍ（现场复核）　 "
        for title, values in [
            ("D1", [["通道号", 2], ["", original]]),
            ("D1", [["通道号", "处理情况"], [2, original]]),
        ]:
            with self.subTest(title=title, values=values):
                rows, warnings, _ = recognize([(title, values)], {}, "原表.xlsx")
                self.assertEqual(warnings, [])
                self.assertEqual({r["outage"] for r in rows}, {"D117", "D118"})
                shifted = next(r for r in rows if r["outage"] == "D118")
                self.assertEqual(shifted["offset_mm"], 40)
                self.assertIsNone(shifted["unsigned_offset_mm"])
                self.assertTrue(all(r["note"] == original for r in rows))
        for values in [
            [["通道号", "D118"], [2, " 后移位４０ｍｍ（现场复核）\n保留说明　 "]],
            [["D118"], ["通道002，后移位４０ｍｍ（现场复核）\n保留说明　 "]],
        ]:
            rows, _, _ = recognize([("D1", values)], {}, "原表.xlsx")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["note"], values[1][1 if len(values[1]) > 1 else 0])

    def test_explicit_note_and_manual_recognition_are_verbatim(self):
        note = " \t此前移位４２ｍｍ；本次检查后换管（原文）\n现场　复核。  "
        rows, warnings, _ = self.preview([("F102", [["管号", "管状态", "备注"], [1, "换管", note]])])
        self.assertEqual(warnings, [])
        self.assertEqual(rows[0]["note"], note)
        server.save_tube_state(rows[0])
        self.assertEqual(server.query_states()["items"][0]["note"], note)
        original = " \tＦ１０２ 通道００１，割管移位（切除４２ｍｍ）；\n现场　复核。  "
        result = state_transfer.recognize_note(server, {**self.record(), "note": original})
        self.assertEqual(result["rows"][0]["note"], original)
        self.assertEqual(result["rows"][0]["offset_mm"], 42)
        self.assertIsNone(result["rows"][0]["unsigned_offset_mm"])
        for note in ["Ｆ１０３ 通道００１堵管", "Ｆ１０２ 通道００２堵管"]:
            with self.subTest(note=note), self.assertRaises(ValueError):
                state_transfer.recognize_note(server, {**self.record(), "note": note})

    def test_word_preserves_tabs_breaks_and_fullwidth_punctuation(self):
        raw = io.BytesIO()
        xml = '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
        <w:tbl><w:tr><w:tc><w:p><w:r><w:t>管号</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>处理情况</w:t></w:r></w:p></w:tc></w:tr>
        <w:tr><w:tc><w:p><w:r><w:t>2</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r>
        <w:t xml:space="preserve"> 后移位４２ｍｍ（原文）；</w:t><w:br/><w:tab/>
        <w:t xml:space="preserve">现场复核。  </w:t></w:r></w:p></w:tc></w:tr></w:tbl>
        </w:body></w:document>'''
        with ZipFile(raw, "w") as archive:
            archive.writestr("word/document.xml", xml)
        result = state_transfer.preview(server, dict(filename="F102.docx", content=base64.b64encode(raw.getvalue()).decode()))
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["rows"][0]["note"], " 后移位４２ｍｍ（原文）；\n\t现场复核。  ")

    def test_explicit_notes_sources_and_horizontal_states_are_independent(self):
        note = " \t此前移位４２ｍｍ；\r\n本次正常。来源：这也是原文　 "
        source = "原台账.xlsx · 记录1\r\n第二来源"
        for values in [
            [["通道", "状态", "备注", "来源"], [1, "正常", note, source], [2, "堵管", "", ""]],
            [["通道", 1, 2], ["状态", "正常", "堵管"], ["备注", note, ""], ["来源", source, ""]],
        ]:
            with self.subTest(values=values):
                rows, warnings, _ = self.preview([("F102", values)])
                self.assertEqual(warnings, [])
                self.assertEqual([(r["state"], r["note"], r["source"]) for r in rows],
                                 [("normal", note, source), ("plugged", "", "")])
        rows, warnings, _ = recognize([("D1", [
            ["通道", "处理情况", "备注", "来源"],
            [2, "D117后换管；D118后移位40", note, source],
        ])], {}, "原表.xlsx")
        self.assertEqual(warnings, [])
        self.assertEqual(len(rows), 2)
        self.assertTrue(all((r["note"], r["source"]) == (note, source) for r in rows))

    def test_same_state_different_original_notes_require_review(self):
        rows, warnings, _ = self.preview([("F102", [
            ["通道", "状态", "备注"], [1, "堵管", "原始说明一"], [1, "堵管", "原始说明二"],
        ])])
        self.assertEqual(rows, [])
        self.assertTrue(any("不同处理事件" in w for w in warnings))

    def test_shift_without_distance_and_synonymous_blocking(self):
        for value in ["割管移位", "切管移位", "已移位", "已实施割管移位", "移位50%", "割管移位５０％"]:
            with self.subTest(value=value):
                facts, reason = parse_description(value)
                self.assertEqual(reason, "")
                self.assertEqual(facts, dict(state="shifted", offset_mm=None, unsigned_offset_mm=None))
        for value in ["封堵", "已封管", "指套管自动阀后安装堵头进行封堵", "堵管处理", "已安装堵头"]:
            with self.subTest(value=value):
                facts, reason = parse_description(value)
                self.assertEqual((facts["state"], reason), ("plugged", ""))
        for value in ["未割管移位", "未进行割管移位", "未封堵", "未发生堵塞", "没有安装堵头",
                      "拟封堵", "建议封管", "待封堵", "打开堵头进行检查", "拆除堵头"]:
            with self.subTest(value=value):
                self.assertIsNone(parse_description(value)[0])
        for value, distance in [("割管移位，距离为42mm", 42), ("移位距离：４.２厘米", 42),
                                ("割管移位50%（切除41mm）", 41), ("移位（42.5mm）", 42.5)]:
            with self.subTest(value=value):
                facts, reason = parse_description(value)
                self.assertEqual(reason, "")
                self.assertEqual(facts["offset_mm"], distance)
                self.assertIsNone(facts["unsigned_offset_mm"])
        self.assertIsNone(parse_description("割管移位41mm，移位42mm")[0])
        self.assertIsNone(parse_description("割管次数2")[0])

    def test_flags_grouped_events_and_raw_notes_without_distance(self):
        for values in [
            [["通道", "是否封堵"], [1, "是"], [2, "已封堵"], [3, "否"]],
            [["通道", 1, 2, 3], ["是否封堵", "是", "已封堵", "否"]],
        ]:
            rows, warnings, _ = self.preview([("F102", values)])
            self.assertEqual(warnings, [])
            self.assertEqual([(r["thimble_id"], r["state"]) for r in rows], [(1, "plugged"), (2, "plugged")])
        original = " \t4、5、6封堵；通道007，割管移位　 "
        rows, warnings, _ = self.preview([("F102", [["F102"], [original]])])
        self.assertEqual(warnings, [])
        self.assertEqual({r["thimble_id"]: r["state"] for r in rows}, {4: "plugged", 5: "plugged", 6: "plugged", 7: "shifted"})
        self.assertTrue(all(r["note"] == original for r in rows))
        rows, warnings, _ = self.preview([("F102", [["F102"], ["4、5、6封堵"]])])
        self.assertEqual(warnings, [])
        self.assertEqual({r["thimble_id"]: r["state"] for r in rows}, {4: "plugged", 5: "plugged", 6: "plugged"})

    def test_real_ningde_distance_free_cells_are_not_skipped(self):
        path = REFERENCE_DATA / "宁德/宁德4台机组指套管割管移位信息汇总20200804.xls"
        raw = path.read_bytes()
        result = state_transfer.preview(server, dict(filename=path.name, content=base64.b64encode(raw).decode()))
        book = server.open_excel_workbook(path)
        expected = {}
        try:
            for sheet in book.worksheets:
                values = list(sheet.iter_rows(values_only=True))
                prefix = sheet.title[0]
                for cells in values[1:]:
                    for index, value in enumerate(cells[2:], 2):
                        if value == "割管移位":
                            expected[prefix + str(values[0][index]), int(cells[0])] = value
        finally:
            book.close()
        self.assertEqual(len(expected), 18)
        actual = {(r["outage"], r["thimble_id"]): r for r in result["rows"]}
        for key, original in expected.items():
            self.assertIn(key, actual)
            row = actual[key]
            self.assertEqual((row["state"], row["offset_mm"], row["unsigned_offset_mm"], row["note"]),
                             ("shifted", None, None, original))
        self.assertEqual(path.read_bytes(), raw)


if __name__ == "__main__":
    unittest.main()
