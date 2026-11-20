import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook, load_workbook
from src.backend import server, import_audit
from test_server import write_sum, write_ect, write_report, report_entry


class ImportAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_patch = patch.object(server, "DB_PATH", self.root / "test.db")
        self.output_patch = patch.object(server, "EXCEL_DIR", self.root / "exports")
        self.db_patch.start()
        self.output_patch.start()
        server.init_db()

    def tearDown(self):
        self.output_patch.stop()
        self.db_patch.stop()
        self.temp.cleanup()

    def workbook(self, rows, filename="import.xlsx"):
        source = self.root / filename
        book = Workbook()
        book.active.append(["大修号", "机组号", "通道编号", "在堆芯内的位置", "三字码", "磨损位置"])
        for row in rows:
            book.active.append(row)
        book.save(source)
        book.close()
        return source

    def test_excel_records_hash_operator_all_invalid_rows_and_safe_export(self):
        rows = [["H209", 2, 1, "B5", "WAR", "P1"]]
        rows.extend([["H209", 2, 90, "", "", ""]] * 125)
        rows.append(["H209", 1, 2, "", "", ""])
        rows.append(["H209", 2, 3, "A1", "WAR", "P2"])
        source = self.workbook(rows, "=source.xlsx")
        result = server.import_excel_file(str(source), operator="检验员A")
        self.assertEqual(result["inserted"], 2)
        quality = import_audit.quality(server, result["batch_id"])
        self.assertEqual(quality["totals"]["issues"], 127)
        self.assertEqual(len(quality["issues"]), 50)
        batch = quality["batches"][0]
        self.assertEqual(batch["operator"], "system:maintenance")
        self.assertEqual(batch["parser_version"], server.SERVICE_VERSION)
        self.assertEqual(batch["error_count"], 127)
        self.assertEqual(len(quality["artifacts"][0]["sha256"]), 64)
        exported = import_audit.export_quality(server, result["batch_id"])
        book = load_workbook(exported["file_path"])
        self.assertEqual(book["校验问题"].max_row, 128)
        self.assertEqual(book["文件校验"].max_row, 2)
        self.assertEqual(book["记录原值"].max_row, 3)
        book.close()

    def test_rollback_and_restore_only_affects_selected_batch_and_keeps_audit(self):
        source = self.workbook([["H209", 2, 1, "B5", "WAR", "P1"]])
        first = server.import_excel_file(str(source))
        second = server.import_excel_file(str(source))
        self.assertEqual(second["skipped"], 1)
        other = self.workbook([["H209", 2, 2, "C8", "WAR", "P1"]], "other.xlsx")
        third = server.import_excel_file(str(other))
        with server.connect() as db:
            db.execute("INSERT INTO tube_states(outage,unit_id,thimble_id,state) VALUES('H209',2,1,'plugged')")
        import_audit.change_batch(server, first["batch_id"], "rollback")
        self.assertEqual(server.query_findings({})["total"], 1)
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM findings").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tube_states").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM duplicate_records").fetchone()[0], 1)
        self.assertTrue(source.exists())
        self.assertEqual(import_audit.quality(server, third["batch_id"])["batches"][0]["status"], "completed")
        import_audit.change_batch(server, first["batch_id"], "restore")
        self.assertEqual(server.query_findings({})["total"], 2)

    def test_batch_updates_can_be_undone_without_removing_existing_records(self):
        source = self.workbook([["H209", 2, 1, "B5", "", "P1"]])
        original = server.import_excel_file(str(source), "review")
        change = server.import_excel_file(str(source), "fill_war")
        with self.assertRaisesRegex(ValueError, "后续"):
            import_audit.change_batch(server, original["batch_id"], "rollback")
        import_audit.change_batch(server, change["batch_id"], "rollback")
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT indication FROM findings").fetchone()[0], "")
        import_audit.change_batch(server, change["batch_id"], "restore")
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT indication FROM findings").fetchone()[0], "WAR")

    def test_fill_ndd_persists_ndd_and_audits_source(self):
        source = self.workbook([["H209", 2, 1, "B5", "", "P1"]])
        result = server.import_excel_file(str(source), "fill_ndd")
        self.assertEqual(result["inserted"], 1)
        with server.connect() as db:
            row = db.execute(
                "SELECT indication,indication_resolution,source_indication FROM findings").fetchone()
            audit = db.execute(
                "SELECT action,resolved_indication,source_indication FROM indication_resolution_audit").fetchall()
        self.assertEqual(tuple(row), ("NDD", "bulk_ndd", ""))
        self.assertEqual([tuple(item) for item in audit], [("bulk_ndd", "NDD", "")])

    def test_changed_record_prevents_partial_rollback(self):
        source = self.workbook([
            ["H209", 2, 1, "B5", "WAR", "P1"],
            ["H209", 2, 2, "C8", "WAR", "P1"],
        ])
        result = server.import_excel_file(str(source))
        with server.connect() as db:
            db.execute("UPDATE findings SET location='P6' WHERE thimble_id=2")
        with self.assertRaisesRegex(ValueError, "修改"):
            import_audit.change_batch(server, result["batch_id"], "rollback")
        self.assertEqual(server.query_findings({})["total"], 2)

    def test_failed_import_is_audited_and_data_transaction_rolls_back(self):
        source = self.workbook([["H209", 2, 1, "B5", "WAR", "P1"]])
        with patch.object(import_audit, "remember_change", side_effect=RuntimeError("write failure")):
            with self.assertRaises(RuntimeError):
                server.import_excel_file(str(source), "review")
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM findings").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM file_artifacts").fetchone()[0], 0)
        quality = import_audit.quality(server)
        self.assertEqual(quality["batches"][0]["status"], "failed")
        self.assertEqual(quality["issues"][0]["code"], "IMPORT_FAILED")

    def test_directory_preserves_unselected_versions_and_unreported_ect(self):
        group = self.root / "TH2I09CAL00001"
        group.mkdir()
        write_sum(group)
        write_ect(group, "DIR001C001I001.ECT", 1, 1, 1)
        write_ect(group, "DIR002C002I001.ECT", 2, 2, 1)
        write_report(group, [report_entry("DIR001C001I001.ECT", 1, 1, 1, "a")], "first.rpt")
        write_report(group, [report_entry("DIR001C001I001.ECT", 1, 1, 1, "b")], "second.rpt")
        with self.assertRaisesRegex(ValueError, "人工确认"):
            server.import_directory(str(self.root))
        result = server.import_directory(str(self.root), [str(group / "first.rpt")])
        data = import_audit.quality(server, result["batch_id"])
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(len(data["versions"]), 2)
        self.assertEqual(sum(row["batch_selected"] for row in data["versions"]), 1)
        self.assertIn("MISSING_REPORT", data["codes"])
        self.assertEqual(data["totals"]["artifacts"], 5)

    def test_native_directory_preflight_returns_rows_without_any_database_writes(self):
        group = self.root / "TH2I09CAL00001"
        group.mkdir()
        write_sum(group)
        write_ect(group, "DIR001C001I001.ECT", 1, 1, 1)
        write_report(group, [report_entry("DIR001C001I001.ECT", 1, 1, 1, "a")])
        options = server.report_options(str(self.root))
        confirmation = {"confirmed": True, "candidates": [
            {key: row.get(key) or "" for key in ("path", "sha256", "sum_sha256")}
            for row in options if not row.get("error")]}
        with server.connect() as db:
            before = db.total_changes
            tables_before = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                             for table in ("findings", "import_batches", "validation_issues", "restore_points")}
        result = server.preview_directory_import(str(self.root), [options[0]["path"]], confirmation)
        self.assertEqual(result["parsed"], 1)
        self.assertEqual(result["preview_rows"][0]["indication"], "WAR")
        with server.connect() as db:
            self.assertEqual(tables_before, {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                                            for table in tables_before})

    def test_native_excel_inspection_has_source_row_numbers_and_preflight_rows(self):
        source = self.workbook([["H209", 2, 1, "B5", "WAR", "P1"]])
        inspected = server.inspect_excel_file(str(source))
        self.assertEqual(inspected["sheets"][0]["sample_rows"][0]["row_number"], 2)
        preview = server.import_excel_file(str(source), "check")
        self.assertEqual(preview["preview_rows"][0]["thimble_id"], 1)
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM findings").fetchone()[0], 0)

    def test_records_with_different_phase_do_not_share_import_identity(self):
        source = self.root / "phases.xlsx"
        book = Workbook()
        book.active.append(["大修号", "机组号", "通道编号", "三字码", "磨损位置", "相位"])
        book.active.append(["H209", 2, 1, "WAR", "P1", 0])
        book.active.append(["H209", 2, 1, "WAR", "P1", 90])
        book.save(source)
        book.close()
        result = server.import_excel_file(str(source))
        self.assertEqual(result["inserted"], 2)
        self.assertEqual(server.import_excel_file(str(source))["skipped"], 2)

    def test_explicit_selection_rejects_multiple_versions_for_one_group(self):
        group = self.root / "TH2I09CAL00001"
        group.mkdir()
        write_sum(group)
        write_ect(group, "DIR001C001I001.ECT", 1, 1, 1)
        write_report(group, [report_entry("DIR001C001I001.ECT", 1, 1, 1, "a")], "first.rpt")
        write_report(group, [report_entry("DIR001C001I001.ECT", 1, 1, 1, "b")], "second.rpt")
        with self.assertRaisesRegex(ValueError, "一个报告版本"):
            server.import_directory(str(self.root), [str(group / "first.rpt"), str(group / "second.rpt")])
        self.assertEqual(server.query_findings({})["total"], 0)

    def test_missing_sum_is_quarantined_and_keeps_report_original_values(self):
        group = self.root / "TH2I09CAL00001"
        group.mkdir()
        write_ect(group, "DIR001C001I001.ECT", 1, 1, 1)
        write_report(group, [report_entry("DIR001C001I001.ECT", 1, 1, 1, "a")])
        result = server.import_directory(str(self.root))
        self.assertEqual(result["inserted"], 0)
        data = import_audit.quality(server, result["batch_id"])
        self.assertIn("SUM_WARNING", data["codes"])
        self.assertIn("UNIT_OUTAGE_MISMATCH", data["codes"])

    def raw_group(self):
        group = self.root / "TH2I09CAL00001"
        group.mkdir()
        write_sum(group)
        write_ect(group, "DIR001C001I001.ECT", 1, 1, 1)
        return group

    def test_rpt_unit_conflict_is_quarantined_with_original_evidence(self):
        group = self.raw_group()
        entry = report_entry("DIR001C001I001.ECT", 1, 1, 1, "a")
        write_report(group, [entry.replace("<Row>", "<Id>3</Id><Row>")])
        result = server.import_directory(str(self.root))
        self.assertEqual(result["inserted"], 0)
        quality = import_audit.quality(server, result["batch_id"])
        self.assertIn("RPT_UNIT_MISMATCH", quality["codes"])
        conflict = next(item for item in quality["issues"] if item["code"] == "RPT_UNIT_MISMATCH")
        self.assertIn('"report_unit_raw": "3"', conflict["payload_json"])
        self.assertIn('"unit_id": 2', conflict["payload_json"])
        with self.assertRaisesRegex(ValueError, "未解析出检测记录"):
            server.export_directory_excel(str(self.root))

    def test_matching_rpt_unit_is_retained_in_findings(self):
        group = self.raw_group()
        entry = report_entry("DIR001C001I001.ECT", 1, 1, 1, "a")
        write_report(group, [entry.replace("<Row>", "<Id>2</Id><Row>")])
        self.assertEqual(server.import_directory(str(self.root))["inserted"], 1)
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT report_unit_raw FROM findings").fetchone()[0], "2")

    def test_manual_confirmation_rejects_missing_stale_and_incomplete_choices(self):
        group = self.raw_group()
        write_report(group, [report_entry("DIR001C001I001.ECT", 1, 1, 1, "a")])
        options = server.report_options(str(self.root))
        paths = [options[0]["path"]]
        manifest = {"confirmed": True, "candidates": options}
        with self.assertRaisesRegex(ValueError, "人工确认"):
            server.validate_report_confirmation(str(self.root), paths, None)
        with self.assertRaisesRegex(ValueError, "遗漏"):
            server.validate_report_confirmation(str(self.root), [], manifest)
        result = server.import_directory(str(self.root), paths, report_confirmation=manifest)
        with server.connect() as db:
            evidence = db.execute("SELECT selection_json FROM import_batches WHERE id=?", (result["batch_id"],)).fetchone()[0]
            self.assertIn(options[0]["sha256"], evidence)
            self.assertIn("confirmed_at", evidence)
        write_sum(group, unit="3")
        with self.assertRaisesRegex(ValueError, "已变化"):
            server.validate_report_confirmation(str(self.root), paths, manifest)
        write_sum(group)
        write_report(group, [report_entry("DIR001C001I001.ECT", 1, 1, 1, "changed")])
        with self.assertRaisesRegex(ValueError, "已变化"):
            server.validate_report_confirmation(str(self.root), paths, manifest)

    def test_set_is_archived_without_claiming_successful_parsing(self):
        group = self.raw_group()
        write_report(group, [report_entry("DIR001C001I001.ECT", 1, 1, 1, "a")])
        (group / "test.SET").write_bytes(b"not a parsed setup")
        result = server.import_directory(str(self.root))
        quality = import_audit.quality(server, result["batch_id"])
        artifact = next(item for item in quality["artifacts"] if item["extension"] == ".set")
        self.assertEqual(artifact["parse_status"], "archived_unparsed")
        self.assertIn("SET_UNPARSED", quality["codes"])

    def test_set_configuration_preserves_channels_and_calibration_without_assuming_mm(self):
        import json
        group = self.raw_group()
        write_report(group, [report_entry("DIR001C001I001.ECT", 1, 1, 1, "a")])
        (group / "test.SET").write_text(
            '<ETerSetup xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            '<DataChannelList><DataChannel xsi:type="RawDataChannel">'
            '<ChannelID>0</ChannelID><ChannelName>1</ChannelName><ChannelType>Diff</ChannelType>'
            '<Frequency><Val>160000</Val></Frequency><Voltscale>0.005</Voltscale>'
            '<CalibrationClass><IDList><Point>2</Point><Point>3</Point></IDList>'
            '</CalibrationClass></DataChannel></DataChannelList></ETerSetup>', encoding="utf-8")
        result = server.import_directory(str(self.root))
        quality = import_audit.quality(server, result["batch_id"])
        artifact = next(item for item in quality["artifacts"] if item["extension"] == ".set")
        self.assertEqual(artifact["parse_status"], "parsed_configuration")
        config = json.loads(artifact["parsed_json"])
        self.assertEqual(config["channels"][0]["frequency"], {"Val": ["160000"]})
        self.assertEqual(config["channels"][0]["configuration"]["CalibrationClass"][0]["IDList"],
                         [{"Point": ["2", "3"]}])
        self.assertEqual(config["physical_calibration"], "unconfirmed")
        exported = import_audit.export_quality(server, result["batch_id"])
        book = load_workbook(exported["file_path"], read_only=True)
        self.assertIn("配置原始字段", next(book["文件校验"].values))
        book.close()

    def test_cross_group_duplicate_import_keeps_both_sources_and_raises_issue(self):
        for index in (1, 2):
            name = f"TH2I09CAL0000{index}"
            group = self.root / name
            group.mkdir()
            write_sum(group)
            write_ect(group, "DIR001C001I001.ECT", 1, 1, 1)
            write_report(group, [report_entry("DIR001C001I001.ECT", 1, 1, 1, str(index), calgroup=name)])
        result = server.import_directory(str(self.root))
        self.assertEqual(result["inserted"], 2)
        self.assertIn("CROSS_GROUP_DUPLICATE", import_audit.quality(server, result["batch_id"])["codes"])
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM import_finding_sources").fetchone()[0], 2)

    def test_folder_excel_roundtrip_keeps_indication_and_version_confirmation(self):
        group = self.raw_group()
        write_report(group, [report_entry("DIR001C001I001.ECT", 1, 1, 1, "a")])
        candidates = server.report_options(str(self.root))
        exported = server.export_directory_excel(
            str(self.root), [candidates[0]["path"]],
            report_confirmation={"confirmed": True, "candidates": candidates})
        result = server.import_excel_file(exported["file_path"])
        self.assertFalse(result.get("requires_indication_decision", False))
        self.assertEqual(result["inserted"], 1)
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT indication FROM findings").fetchone()[0], "WAR")
            evidence = db.execute("SELECT selection_json FROM import_batches WHERE id=?", (result["batch_id"],)).fetchone()[0]
            self.assertIn("imported_workbook", evidence)
            self.assertIn(candidates[0]["sha256"], evidence)

    def test_folder_workbook_sheets_and_edited_row_do_not_restore_stale_values(self):
        for index in (9, 10):
            group = self.root / f"TH2I{index:02}CAL00001"
            group.mkdir()
            write_sum(group, outage=f"H2{index:02}")
            write_ect(group, "DIR001C001I001.ECT", 1, 1, 1)
            write_report(group, [report_entry("DIR001C001I001.ECT", 1, 1, 1, str(index),
                                             calgroup=group.name)])
        exported = server.export_directory_excel(str(self.root))
        book = load_workbook(exported["file_path"])
        self.assertEqual(book.sheetnames, ["H209", "H210"])
        sheet = book["H209"]
        self.assertEqual(sheet.max_column, 14)
        self.assertEqual(sheet["N2"].value, "/")
        self.assertEqual(sheet["A2"].border.left.style, "thin")
        self.assertEqual(sheet["A2"].alignment.horizontal, "center")
        sheet["C2"] = 9.5
        book.save(exported["file_path"])
        book.close()
        imported = server.import_excel_file(exported["file_path"])
        self.assertEqual(imported["inserted"], 2)
        with server.connect() as db:
            edited = db.execute("SELECT volts FROM findings WHERE outage='H209'").fetchone()
            self.assertEqual(edited[0], 9.5)
            edited_source = db.execute("SELECT report_path,entry_no FROM findings WHERE outage='H209'").fetchone()
            self.assertTrue(edited_source[0].lower().endswith(".rpt"))
            self.assertEqual(edited_source[1], 1)
            unchanged = db.execute("SELECT report_path,entry_no FROM findings WHERE outage='H210'").fetchone()
            self.assertTrue(unchanged[0].lower().endswith(".rpt"))
            self.assertEqual(unchanged[1], 1)

    def test_quality_export_includes_legacy_findings_and_explains_empty_audit(self):
        result = server.import_excel_file(str(self.workbook([["H209", 2, 1, "B5", "WAR", "P1"]])))
        with server.connect() as db:
            db.execute("UPDATE findings SET import_batch_id=NULL")
        exported = import_audit.export_quality(server, category="MAPPING_ERROR")
        self.assertEqual(exported["finding_rows"], 1)
        self.assertEqual(exported["legacy_rows"], 1)
        book = load_workbook(exported["file_path"])
        try:
            self.assertEqual(book.sheetnames[0], "导出概览")
            self.assertEqual(book["有效检测记录"].max_row, 2)
            self.assertEqual(book["有效检测记录"].cell(2, 2).value, "H209")
            overview = dict(book["导出概览"].iter_rows(min_row=2, values_only=True))
            self.assertEqual(overview["无批次历史记录"], 1)
            self.assertIn("不能据此认定校验通过", overview["历史记录说明"])
        finally:
            book.close()
        scoped = import_audit.export_quality(server, result["batch_id"])
        self.assertEqual(scoped["finding_rows"], 0)

    def test_recycle_restore_does_not_restore_unrelated_import_metadata(self):
        with server.connect() as db:
            for tag in ("deletion_a", "deletion_b"):
                db.execute("""INSERT INTO import_batches(started_at,source_path,import_kind,is_deleted,delete_batch_id)
                    VALUES('now','source','excel',1,?)""", (tag,))
                db.execute("""INSERT INTO delete_batches(id,scope,record_count,deleted_at)
                    VALUES(?,'outage',0,'now')""", (tag,))
        server.api_recycle_restore("deletion_a")
        with server.connect() as db:
            self.assertEqual([row[0] for row in db.execute("SELECT is_deleted FROM import_batches ORDER BY id")], [0, 1])

    def test_large_quality_export_preserves_all_rows_and_literal_formula_text(self):
        with server.connect() as db:
            db.executemany(
                "INSERT INTO findings(outage,unit_id,thimble_id,position,indication,analyst,report_path,imported_at) "
                "VALUES('D101',1,?,'L11','NDD',?,?,'fixture')",
                [(index % 50 + 1, "=1+1", f"原始报告-{index}.rpt") for index in range(2000)],
            )
        exported = import_audit.export_quality(server)
        self.assertEqual(exported["finding_rows"], 2000)
        book = load_workbook(exported["file_path"], read_only=True)
        try:
            sheet = book["有效检测记录"]
            self.assertEqual(sheet.max_row, 2001)
            self.assertIsNone(sheet["A1"].fill.fill_type)
            self.assertEqual(sheet["A1"].font.color.rgb[-6:], "000000")
            self.assertEqual(sheet["A1"].font.name, server.PLAIN_EXCEL_FONT)
            self.assertEqual(sheet["A1"].border.left.style, "thin")
            rows = list(sheet.iter_rows(min_row=2))
            self.assertEqual(len({row[12].value for row in rows}), 2000)
            self.assertTrue(all(row[10].value == "=1+1" and row[10].data_type == "s" for row in rows))
            self.assertEqual(sum(row[3].value == 50 for row in rows), 40)
        finally:
            book.close()


if __name__ == "__main__":
    unittest.main()
