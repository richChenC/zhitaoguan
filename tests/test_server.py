from enterprise_fixtures import mark_legacy
import hashlib
import json
import tempfile
import unittest
import sqlite3
import zipfile
from pathlib import Path
from unittest.mock import patch

from src.backend import server
from openpyxl import Workbook, load_workbook

DATA_ROOT = server.ROOT / "项目资料" / "03_原始验证数据" / "测试数据"
H209_ROOT = DATA_ROOT / "指套管数据1" / "H209"
N208_ROOT = DATA_ROOT / "指套管数据1" / "N208"


def write_sum(group: Path, unit="2", outage="H209"):
    (group / "SUR000C000I000.SUM").write_text(
        f'<?xml version="1.0" encoding="utf-8"?><Summary><Site><Owner>LHNP</Owner><SiteCode>LHNP</SiteCode><Unit>{unit}</Unit><Component>TH</Component><Outage>{outage}</Outage></Site><Equipment><Tester>TEDDY+A</Tester></Equipment><Probe><Model>TH048NAF25A</Model></Probe></Summary>',
        encoding="utf-8",
    )


def write_ect(group: Path, name: str, row: int, col: int, entry: int, marker=""):
    xml = f'xx<?xml version="1.0" encoding="utf-8"?><HeaderTube><Entry>{entry}</Entry><Row>{row}</Row><Col>{col}</Col><DateTime>2026/1/1 {marker}</DateTime></HeaderTube>yy'
    (group / name).write_bytes(xml.encode("utf-8"))


def report_entry(filename, row, col, entry, uid, indication="WAR", location="P1+10", channel="P1: 4-6", percent="20", calgroup="TH2I09CAL00001", measurement="Point"):
    return f'<ReportEntry><Row>{row}</Row><Column>{col}</Column><Entry>{entry}</Entry><Volts>1.2</Volts><Degrees>0</Degrees><Percent>{percent}</Percent><Indication>{indication}</Indication><Channel>{channel}</Channel><ChannelID>4</ChannelID><Location>{location}</Location><MeasurementType>{measurement}</MeasurementType><Probe>TH048NAF25A</Probe><Analyst>A</Analyst><Analysis>Secondary</Analysis><Datapoint>80</Datapoint><Uid>{uid}</Uid><Filename>{filename}</Filename><Filepath>Z:\\old\\{filename}</Filepath><Calgroup>{calgroup}</Calgroup><Distance>10</Distance><Extent>2</Extent><Length>3</Length><Width>4</Width><Comment>note</Comment></ReportEntry>'


def write_report(group: Path, entries: list[str], name="Report-final.rpt"):
    (group / name).write_text('<?xml version="1.0" encoding="utf-8"?><CitecReport>' + "".join(entries) + "</CitecReport>", encoding="utf-8")


class ParserTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = patch.multiple(server, DB_PATH=Path(folder.name) / "parser.db",
                                 DATA_DIR=Path(folder.name) / "data",
                                 EXCEL_DIR=Path(folder.name) / "excel",
                                 REPORT_DIR=Path(folder.name) / "reports")
        patcher.start()
        self.addCleanup(patcher.stop)
        server.init_db()

    def test_health_status_identifies_expected_local_service(self):
        health = server.health_status()
        self.assertTrue(health["ok"])
        self.assertEqual(health["service"], "thimble-local")
        self.assertEqual(health["version"], server.SERVICE_VERSION)

    def test_position_mappings(self):
        self.assertEqual(server.position_for(1, 1), "L11")
        self.assertEqual(server.position_for(2, 1), "B5")
        self.assertEqual(server.position_for(2, 27), "J15")
        self.assertEqual(server.position_for(1, 15), "N5")
        self.assertEqual(server.position_for(2, 42), "N5")
        self.assertEqual(server.position_for(2, 3), "E11")
        self.assertEqual(server.position_for(2, 47), "L5")
        self.assertEqual(server.position_for(2, 50), "L4")
        self.assertEqual(len({server.position_for(1, tube) for tube in range(1, 51)}), 50)
        self.assertEqual(len({server.position_for(2, tube) for tube in range(1, 51)}), 50)

    def test_database_removes_out_of_range_legacy_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "test.db"
            with patch.object(server, "DB_PATH", db):
                server.init_db()
                with server.connect() as connection:
                    connection.execute("INSERT INTO findings(outage,unit_id,thimble_id,imported_at) VALUES('N208',2,82,'now')")
                mark_legacy(server)
                server.init_db()
                with server.connect() as connection:
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM findings").fetchone()[0], 0)

    def test_database_deduplication_is_audited_and_preserves_distinct_uid(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "dedup.db"
            with patch.object(server, "DB_PATH", db):
                server.init_db()
                with server.connect() as connection:
                    row = ("H209", 2, 1, "B5", 4, "NDD", None, "same.ect", "TH2I09CAL00001", "uid-a", "now")
                    connection.executemany("""INSERT INTO findings(
                        outage,unit_id,thimble_id,position,entry_no,indication,percent,filename,calgroup,uid,imported_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""", [row, row, row[:-2] + ("uid-b", "now")])
                mark_legacy(server)
                server.init_db()
                with server.connect() as connection:
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM findings").fetchone()[0], 2)
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM duplicate_records WHERE action='removed'").fetchone()[0], 1)
                summary = server.duplicate_summary()
                self.assertEqual(summary["findings"], 2)
                self.assertEqual(summary["duplicates"], 1)

    def test_manual_deduplication_removes_stale_key_duplicates_and_keeps_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "manual-dedup.db"
            with patch.object(server, "DB_PATH", db):
                server.init_db()
                with server.connect() as connection:
                    values = ("H209", 2, 3, "E11", 4, "WAR", 22, "P1+10", "P1: 4-6", "uid-a", "now")
                    connection.execute("""INSERT INTO findings(
                        outage,unit_id,thimble_id,position,entry_no,indication,percent,location,channel,uid,imported_at,business_key
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,'legacy-key-a')""", values)
                    connection.execute("""INSERT INTO findings(
                        outage,unit_id,thimble_id,position,entry_no,indication,percent,location,channel,uid,imported_at,business_key
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,'legacy-key-b')""", values)
                result = server.deduplicate_database()
                summary = server.duplicate_summary()
            self.assertEqual((result["before"], result["removed"], result["after"]), (2, 1, 1))
            self.assertEqual(summary["current_duplicates"], 0)
            self.assertTrue(Path(result["backup_path"]).is_file())
            self.assertTrue(summary["items"][0]["payload_json"])
            self.assertTrue(summary["items"][0]["kept_payload_json"])

    def test_clear_database_removes_records_and_related_audits(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "clear.db"
            with patch.object(server, "DB_PATH", db):
                server.init_db()
                with server.connect() as connection:
                    connection.execute("INSERT INTO findings(outage,unit_id,thimble_id,imported_at) VALUES('H209',2,1,'now')")
                    finding_id = connection.execute("SELECT id FROM findings").fetchone()[0]
                    connection.execute("INSERT INTO tube_states(outage,unit_id,thimble_id) VALUES('H209',2,1)")
                    connection.execute("INSERT INTO duplicate_records(detected_at,kept_finding_id,business_key,reason,payload_json,action) VALUES('now',?,'key','duplicate','{}','skipped')", (finding_id,))
                    connection.execute("INSERT INTO indication_resolution_audit(finding_id,changed_at,resolved_indication,action) VALUES(?,'now','WAR','bulk_war')", (finding_id,))
                    preserved_tables = (
                        "users", "roles", "permissions", "role_permissions", "user_roles",
                        "security_events", "export_audits", "analysis_rules", "backup_policy",
                        "grid_positions", "ledger_identity", "state_preferences",
                    )
                    preserved_before = {
                        table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                        for table in preserved_tables
                    }
                result = server.clear_database()
                with server.connect() as connection:
                    remaining = [connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("findings", "tube_states", "duplicate_records", "indication_resolution_audit")]
                    other_remaining = {
                        table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                        for table in result["cleared"] if table != "operation_logs"
                    }
                    clear_logs = [row[0] for row in connection.execute("SELECT operation_type FROM operation_logs")]
                    restore_points = connection.execute("SELECT COUNT(*) FROM restore_points").fetchone()[0]
                    preserved_after = {
                        table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                        for table in preserved_tables
                    }
            for table in ("findings", "tube_states", "duplicate_records", "indication_resolution_audit"):
                self.assertEqual(result["cleared"][table], 1)
            self.assertEqual(remaining, [0, 0, 0, 0])
            self.assertTrue(all(count == 0 for count in other_remaining.values()), other_remaining)
            self.assertEqual(clear_logs, ["backup", "clear_database"])
            self.assertGreaterEqual(restore_points, 1)
            self.assertEqual(preserved_after, preserved_before)
            self.assertTrue(set(preserved_tables) <= set(result["preserved"]))
            self.assertEqual(server.overview()["stats"]["findings"], 0)
            self.assertEqual(server.overview()["stats"]["source_findings"], 0)
            self.assertEqual(server.overview()["combinations"], [])
            self.assertTrue(Path(result["backup"]["path"]).is_file())

    def test_core_severity_uses_valid_percent_and_ignores_ndd(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "severity.db"
            with patch.object(server, "DB_PATH", db):
                server.init_db()
                with server.connect() as connection:
                    connection.executemany(
                        """INSERT INTO findings(
                            outage,unit_id,thimble_id,position,indication,percent,location,measurement_type,imported_at
                        ) VALUES(?,?,?,?,?,?,?,?,?)""",
                        [
                            ("H209", 2, 42, "M5", "WAR", 22, "P1", "Vmax", "now"),
                            ("H209", 2, 20, "D7", "NDD", 80, "P1+10", "Vmax", "now"),
                            ("H209", 2, 21, "G7", "WAR", None, "P1", "Vmax", "now"),
                            ("H209", 2, 1, "B5", "WAR", 47, "P1", "Vmax", "now"),
                            ("H209", 2, 3, "E11", "", 35, "P4+20", "Vmax", "now"),
                        ],
                    )
                result = server.query_findings({"unit": ["2"], "page": ["1"], "size": ["1"]})
                fast = server.query_findings({"unit": ["2"], "page": ["1"], "size": ["1"], "core": ["0"]})
                tube_result = server.query_findings({"unit": ["2"], "thimble": ["1"], "page": ["1"], "size": ["100"]})
            severity = {item["thimble_id"]: item["percent"] for item in result["core_items"]}
            self.assertEqual(severity, {1: 47, 3: 35, 42: 22})
            self.assertEqual(len(result["items"]), 1)
            self.assertEqual(fast["items"], result["items"])
            self.assertEqual(fast["core_items"], [])
            self.assertEqual(fast["total"], result["total"])
            self.assertEqual(tube_result["total"], 1)
            self.assertEqual(server.display_indication({"indication": "", "location": "P4+20", "measurement_type": "Vmax"}), "未标注")
            self.assertEqual(server.display_indication({"indication": "", "location": "", "measurement_type": "None", "datapoint": 0}), "NDD")
            self.assertEqual(server.display_indication({"indication": "", "location": "", "measurement_type": "None"}), "NDD")
            self.assertEqual(server.display_indication({"indication": "/", "location": "/", "measurement_type": "None", "datapoint": 0}), "NDD")
            self.assertEqual(server.display_indication({"indication": "/", "location": "/", "measurement_type": "None"}), "NDD")

    def test_blank_indication_classifies_measurement_evidence_and_ndd(self):
        self.assertEqual(server.analysis_reporting.blank_indication_class({
            "indication": "", "volts": 0, "degrees": None, "percent": None,
            "channel": "/", "location": "/", "measurement_type": "NONE",
        }), "war_candidate")
        self.assertEqual(server.analysis_reporting.blank_indication_class({
            "indication": "", "volts": None, "degrees": None, "percent": None,
            "channel": "P1: 4-6", "location": "/", "measurement_type": "NONE",
        }), "war_candidate")
        self.assertEqual(server.analysis_reporting.blank_indication_class({
            "indication": "", "volts": None, "degrees": None, "percent": None,
            "channel": "CH-02", "location": "/", "measurement_type": "NONE",
        }), "ndd")
        self.assertEqual(server.analysis_reporting.blank_indication_class({
            "indication": "/", "volts": "/", "degrees": "/", "percent": "/",
            "channel": "/", "location": "/", "measurement_type": "/",
        }), "ndd")
        self.assertEqual(server.analysis_reporting.blank_indication_class({
            "indication": "", "volts": None, "degrees": None, "percent": None,
            "channel": "", "location": "", "measurement_type": "NONE",
        }), "ndd")

    def test_blank_indication_summary_excludes_ndd_from_war_batch(self):
        def finding(indication="", **values):
            base = dict(
                outage="H209", unit_id=2, thimble_id=1, position="B5",
                entry_no=1, volts=None, degrees=None, indication=indication,
                percent=None, channel="", location="", datapoint=0,
                liss_region_size=None, analyst="", analysis="", filepath="",
                filename="a.ect", calgroup="G", report_path="r.rpt",
            )
            base.update(values)
            return server.Finding(**base)

        summary = server.blank_indication_summary([
            finding(volts=4.9, percent=None, channel="/", location="/"),
            finding(thimble_id=2, indication="/", volts="/", degrees="/",
                    percent="/", channel="/", location="/", measurement_type="/"),
        ])
        self.assertEqual(summary["count"], 1)
        self.assertEqual(summary["ndd_count"], 1)
        self.assertEqual(len(summary["items"]), 1)
        self.assertEqual(len(summary["ndd_items"]), 1)

    def test_blank_indication_fill_war_does_not_change_auto_ndd(self):
        finding = server.Finding(
            outage="H209", unit_id=2, thimble_id=1, position="B5",
            entry_no=1, volts=None, degrees=None, indication="/",
            percent="/", channel="/", location="/", datapoint=0,
            liss_region_size=None, analyst="", analysis="", filepath="",
            filename="a.ect", calgroup="G", report_path="r.rpt",
            measurement_type="/",
        )
        columns = server.indication_columns(finding, "fill_war")
        self.assertEqual(columns["indication"], "NDD")
        self.assertEqual(columns["indication_resolution"], "auto_ndd")

    def test_site_filter_uses_explicit_site_code(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "site-filter.db"
            with patch.object(server, "DB_PATH", db):
                server.init_db()
                with server.connect() as connection:
                    connection.executemany(
                        "INSERT INTO findings(outage,unit_id,thimble_id,site_code,position,imported_at) VALUES(?,?,?,?,?,?)",
                        [("H209", 2, 1, "LHNP", "B5", "now"), ("H209", 2, 2, "DNP", "C8", "now")],
                    )
                result = server.query_findings({"site": ["LHNP"], "page": ["1"], "size": ["50"]})
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["items"][0]["site_code"], "LHNP")

    def test_site_filter_supports_legacy_blank_site_code_and_backfills_it(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "legacy-site.db"
            with patch.object(server, "DB_PATH", db):
                server.init_db()
                with server.connect() as connection:
                    connection.execute(
                        "INSERT INTO findings(outage,unit_id,thimble_id,site_code,position,imported_at) VALUES(?,?,?,?,?,?)",
                        ("H209", 2, 1, "", "B5", "now"),
                    )
                result = server.query_findings({"site": ["H"], "page": ["1"], "size": ["50"]})
                mark_legacy(server)
                server.init_db()
                with server.connect() as connection:
                    site_code = connection.execute("SELECT site_code FROM findings").fetchone()[0]
            self.assertEqual(result["total"], 1)
            self.assertEqual(site_code, "H")

    def test_core_severity_keeps_outages_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "core-scope.db"
            with patch.object(server, "DB_PATH", db):
                server.init_db()
                with server.connect() as connection:
                    connection.executemany(
                        "INSERT INTO findings(outage,unit_id,thimble_id,position,indication,percent,location,imported_at) VALUES(?,?,?,?,?,?,?,?)",
                        [("H208", 2, 1, "B5", "WAR", 20, "P1", "now"),
                         ("H209", 2, 1, "B5", "WAR", 45, "P1", "now")],
                    )
                all_outages = server.query_findings({"unit": ["2"], "page": ["1"], "size": ["50"]})
                one_outage = server.query_findings({"unit": ["2"], "outage": ["H209"], "page": ["1"], "size": ["50"]})
            self.assertEqual({row["outage"] for row in all_outages["core_items"]}, {"H208", "H209"})
            self.assertEqual([(row["outage"], row["percent"]) for row in one_outage["core_items"]], [("H209", 45)])

    def test_compare_many_preserves_all_defects_per_tube(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "compare-many.db"
            with patch.object(server, "DB_PATH", db):
                server.init_db()
                with server.connect() as connection:
                    connection.executemany(
                        "INSERT INTO findings(outage,unit_id,thimble_id,position,indication,percent,volts,location,measurement_type,imported_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        [("H208", 2, 1, "B5", "WAR", 20, 1.0, "P1", "Vmax", "now"),
                         ("H208", 2, 1, "B5", "WAR", 30, 2.0, "P4", "Vmax", "now"),
                         ("H209", 2, 1, "B5", "WAR", 22, 1.1, "P1", "Vmax", "now"),
                         ("H209", 2, 1, "B5", "WAR", 32, 2.1, "P4", "Vmax", "now")],
                    )
                result = server.compare_many(["H208", "H209"], 2)
            self.assertEqual(len(result["items"]), 50)
            self.assertEqual(result["coverage"][0]["present"], 1)
            self.assertEqual(result["items"][0]["comparison"], "R")
            self.assertEqual(result["items"][0]["history"]["H208"]["count"], 2)
            self.assertIn("P1", result["items"][0]["history"]["H208"]["location"])
            self.assertIn("P4", result["items"][0]["history"]["H209"]["location"])

    def test_findings_page_size_supports_500_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "page-size.db"
            with patch.object(server, "DB_PATH", db):
                server.init_db()
                with server.connect() as connection:
                    connection.executemany(
                        "INSERT INTO findings(outage,unit_id,thimble_id,position,indication,percent,imported_at) VALUES(?,?,?,?,?,?,?)",
                        [("H209", 2, index % 50 + 1, "B5", "WAR", 20, "now") for index in range(550)],
                    )
                result = server.query_findings({"page": ["1"], "size": ["500"], "raw": ["1"]})
            self.assertEqual(result["size"], 500)
            self.assertEqual(len(result["items"]), 500)
            self.assertEqual(result["pages"], 2)

    def test_workspace_consolidates_ndd_acquisitions_but_keeps_defects(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(server, "DB_PATH", Path(directory) / "display.db"):
                server.init_db()
                with server.connect() as connection:
                    connection.executemany(
                        """INSERT INTO findings(outage,unit_id,thimble_id,position,indication,percent,location,filename,calgroup,analyst,uid,imported_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                        [("H209", 2, 1, "B5", "NDD", None, "", "DIR001C001I006.ECT", "TH2I09CAL00001", "KYY", "n1", "now"),
                         ("H209", 2, 1, "B5", "NDD", None, "", "DIR001C001I019.ECT", "TH2I09CAL00004", "KYY", "n2", "now"),
                         ("H209", 2, 2, "C8", "WAR", 28, "P1", "DIR002C002I018.ECT", "TH2I09CAL00004", "KYY", "w1", "now"),
                         ("H209", 2, 2, "C8", "WAR", 21, "P4", "DIR002C002I018.ECT", "TH2I09CAL00004", "KYY", "w2", "now")],
                    )
                display = server.query_findings({"outage": ["H209"], "unit": ["2"], "page": ["1"], "size": ["100"]})
                raw = server.query_findings({"outage": ["H209"], "unit": ["2"], "page": ["1"], "size": ["100"], "raw": ["1"]})
            self.assertEqual(display["total"], 3)
            self.assertEqual(raw["total"], 4)
            self.assertEqual(display["items"][0]["source_count"], 2)
            self.assertEqual(len([row for row in display["items"] if row["indication"] == "WAR"]), 2)

    def test_ndd_report_display_is_consistent_without_changing_source(self):
        from openpyxl import load_workbook

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(server, "DB_PATH", root / "report.db"), \
                 patch.object(server, "EXCEL_DIR", root / "excel"), \
                 patch.object(server, "REPORT_DIR", root / "reports"):
                server.init_db()
                with server.connect() as connection:
                    connection.executemany(
                        """INSERT INTO findings(outage,unit_id,thimble_id,position,indication,percent,volts,location,channel,imported_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        [("H209", 2, 1, "B5", "NDD", 13, 1.25, "P1+10", "M1", "now"),
                         ("H209", 2, 2, "C8", "WAR", 28, 2.5, "P4+20", "M2", "now")],
                    )
                preview = server.build_inspection_preview("H209", 2, {})
                self.assertIn("<td>NDD</td><td>/</td><td>/</td><td>/</td><td>/</td>", preview["html"])
                self.assertIn("<td>WAR</td><td>2.5</td><td>28.0</td>", preview["html"])
                result = server.export_inspection_report("H209", 2, {})
                book = load_workbook(result["file_path"], data_only=True)
                try:
                    self.assertEqual([book.active.cell(8, col).value for col in range(4, 9)],
                                     ["NDD", "/", "/", "/", "/"])
                    self.assertEqual([book.active.cell(9, col).value for col in range(4, 9)],
                                     ["WAR", 2.5, 28, "P4+20", "M2"])
                finally:
                    book.close()
                word = server.export_inspection_docx("H209", 2, {})
                with zipfile.ZipFile(word["file_path"]) as archive:
                    xml = archive.read("word/document.xml").decode("utf-8")
                self.assertNotIn("1.25", xml)
                with server.connect() as connection:
                    original = connection.execute(
                        "SELECT percent,volts,location,channel FROM findings WHERE outage='H209' AND thimble_id=1"
                    ).fetchone()
                self.assertEqual(tuple(original), (13, 1.25, "P1+10", "M1"))

    def test_word_reports_use_selected_rows_and_comparison_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "reports.db"
            with patch.object(server, "DB_PATH", db), patch.object(server, "REPORT_DIR", root / "output"):
                server.init_db()
                with server.connect() as connection:
                    connection.executemany(
                        """INSERT INTO findings(outage,unit_id,thimble_id,position,indication,percent,volts,location,channel,datapoint,analyst,imported_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                        [("H208", 2, 1, "B5", "WAR", 28, 1.2, "P1+10", "P1: 4-6", 80, "A", "now"),
                         ("H209", 2, 1, "B5", "WAR", 30, 1.4, "P1+10", "P1: 4-6", 80, "B", "now"),
                         ("H209", 2, 2, "C8", "WAR", 45, 2.1, "P4+20", "P3: 4-6", 90, "B", "now")],
                    )
                    selected_id = connection.execute("SELECT id FROM findings WHERE outage='H209' AND thimble_id=1").fetchone()[0]
                preview = server.build_inspection_preview("H209", 2, {}, [selected_id])
                self.assertEqual(preview["rows"], 1)
                self.assertEqual(preview["html"].count("class='wide-value'"), 4)
                self.assertNotIn("<section class='report-info'><div>", preview["html"])
                result = server.export_inspection_docx("H209", 2, {}, [selected_id])
                with zipfile.ZipFile(result["file_path"]) as archive:
                    document_xml = archive.read("word/document.xml").decode("utf-8")
                self.assertIn("涡流检验报告单（TH）", document_xml)
                with self.assertRaisesRegex(ValueError, "50根管完整性检查未通过"):
                    server.export_comparison_docx("H208", "H209", 2)
                self.assertEqual(server.compare("H208", "H209", 2)["summary"]["待确认"], 1)
                with server.connect() as connection:
                    connection.executemany(
                        "INSERT INTO findings(outage,unit_id,thimble_id,position,indication,imported_at) VALUES(?,2,?,?,'NDD','test')",
                        [(outage, tube, server.position_for(2, tube)) for outage in ("H208", "H209")
                         for tube in range(2, 51) if (outage, tube) != ("H209", 2)],
                    )
                comparison = server.export_comparison_docx("H208", "H209", 2)
                self.assertEqual(comparison["R"], 1)
                self.assertEqual(comparison["NI"], 1)
                self.assertEqual(server.compare("H208", "H209", 2)["summary"]["待确认"], 0)
                self.assertTrue(Path(comparison["file_path"]).is_file())
                with zipfile.ZipFile(comparison["file_path"]) as archive:
                    comparison_xml = archive.read("word/document.xml").decode("utf-8")
                self.assertIn('<w:gridSpan w:val="3"/>', comparison_xml)
                self.assertIn("R</w:t>", comparison_xml)
                self.assertIn("结果比对栏内", comparison_xml)
                excel = server.export_comparison_excel("H208", "H209", 2)
                workbook = load_workbook(excel["file_path"])
                comparison_sheet = workbook.active
                self.assertIn("D2:F2", {str(item) for item in comparison_sheet.merged_cells.ranges})
                self.assertIn("G2:I2", {str(item) for item in comparison_sheet.merged_cells.ranges})
                self.assertTrue(str(comparison_sheet.cell(comparison_sheet.max_row, 1).value).startswith("备注："))

    def test_comparison_note_only_describes_present_results(self):
        self.assertIn("R", server.comparison_note({"R": 1, "NI": 0}))
        self.assertNotIn("NI", server.comparison_note({"R": 1, "NI": 0}))
        self.assertIn("NI", server.comparison_note({"R": 0, "NI": 1}))
        self.assertNotIn("“R”", server.comparison_note({"R": 0, "NI": 1}))
        self.assertNotIn("NI", server.comparison_note({"R": 0, "NI": 0}))

    def test_inspection_docx_repeats_fixed_layout_on_every_page(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(server, "DB_PATH", root / "report.db"), patch.object(server, "REPORT_DIR", root / "output"):
                server.init_db()
                with server.connect() as connection:
                    connection.executemany(
                        """INSERT INTO findings(outage,unit_id,thimble_id,position,indication,percent,volts,location,channel,uid,imported_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        [("H209", 2, index % 50 + 1, server.position_for(2, index % 50 + 1), "WAR", 20 + index % 30,
                          1.2, f"P{index % 6 + 1}+10", "P1: 4-6", f"uid-{index}", "now") for index in range(45)],
                    )
                result = server.export_inspection_docx("H209", 2, {})
                with zipfile.ZipFile(result["file_path"]) as archive:
                    xml = archive.read("word/document.xml").decode("utf-8")
            self.assertEqual(xml.count('<w:br w:type="page"/>'), 2)
            self.assertEqual(xml.count("涡流检验报告单（TH）"), 3)
            self.assertEqual(xml.count("备注：无。"), 3)
            self.assertEqual(xml.count("分析人员/级别"), 3)
            self.assertEqual(xml.count('<w:gridCol w:w="2350"/>'), 3)
            self.assertNotIn("反应堆中子通量测量指套管涡流检验报告单", xml)

    def test_report_merges_only_matching_channel_and_core_position(self):
        rows = [
            {"thimble_id": 1, "position": "L11"},
            {"thimble_id": 1, "position": "L11"},
            {"thimble_id": 1, "position": "G14"},
            {"thimble_id": 2, "position": "L11"},
            {"thimble_id": 2, "position": "L11"},
            {"thimble_id": 3, "position": ""},
            {"thimble_id": 3, "position": ""},
        ]
        self.assertEqual(server.report_tube_rowspans(rows), [2, 0, 1, 2, 0, 1, 1])

        xml = server._w_table(
            ["序号", "通道编号", "堆芯位置"],
            [[1, 1, "L11"], [2, 1, "L11"], [3, 1, "G14"]],
            merge_group_columns=(1, 2), merge_columns=(1, 2),
        )
        self.assertEqual(xml.count('<w:vMerge w:val="restart"/>'), 2)
        self.assertEqual(xml.count("<w:vMerge/>") , 2)

    def test_export_query_is_not_truncated_at_ui_page_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "export.db"
            with patch.object(server, "DB_PATH", db):
                server.init_db()
                with server.connect() as connection:
                    connection.executemany(
                        "INSERT INTO findings(outage,unit_id,thimble_id,position,imported_at) VALUES(?,?,?,?,?)",
                        [("H209", 2, index % 50 + 1, "B5", "now") for index in range(205)],
                    )
                rows = server.query_all_findings({"unit": ["2"]})
            self.assertEqual(len(rows), 205)

    def test_state_payload_validation_rejects_invalid_values(self):
        with self.assertRaises(ValueError):
            server.validate_state_payload({"outage": "bad", "unit_id": 2, "thimble_id": 1, "state": "normal"})
        with self.assertRaises(ValueError):
            server.validate_state_payload({"outage": "H209", "unit_id": 2, "thimble_id": 51, "state": "normal"})
        with self.assertRaises(ValueError):
            server.validate_state_payload({"outage": "H209", "unit_id": 2, "thimble_id": 1, "state": "unknown"})

    def test_database_migration_backs_up_and_preserves_legacy_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "legacy.db"
            connection = sqlite3.connect(db)
            connection.execute("""CREATE TABLE findings (
                id INTEGER PRIMARY KEY, outage TEXT NOT NULL, unit_id INTEGER NOT NULL,
                thimble_id INTEGER NOT NULL, position TEXT, entry_no INTEGER, volts REAL,
                degrees REAL, indication TEXT, percent REAL, channel TEXT, location TEXT,
                datapoint INTEGER, liss_region_size INTEGER, analyst TEXT, analysis TEXT,
                filepath TEXT, filename TEXT, calgroup TEXT, report_path TEXT, imported_at TEXT NOT NULL)""")
            connection.execute("INSERT INTO findings(outage,unit_id,thimble_id,position,filename,calgroup,imported_at) VALUES('H209',2,3,'E11','DIR003C003I004.ECT','TH2I09CAL00001','now')")
            connection.commit(); connection.close()
            with patch.object(server, "DB_PATH", db):
                server.init_db()
                with server.connect() as migrated:
                    row = migrated.execute("SELECT outage,unit_id,thimble_id,position,source_key FROM findings").fetchone()
                    columns = {item[1] for item in migrated.execute("PRAGMA table_info(findings)")}
            self.assertEqual(tuple(row), ("H209", 2, 3, "E11", None))
            self.assertIn("uid", columns)
            self.assertTrue(any((Path(directory)/"backups").glob("migration-*.db")))

    def test_outage_ignores_calgroup_digits(self):
        path = Path(r"D:\data\H209\TH2I09CAL00005\Report-x.rpt")
        self.assertEqual(server.infer_outage(path), "H209")

    def test_parse_real_report(self):
        reports = [path for path in DATA_ROOT.rglob("Report*.rpt") if path.parent.name.upper().startswith("TH")]
        self.assertTrue(reports)
        findings = server.parse_report(reports[0])
        self.assertTrue(findings)
        self.assertTrue(all(1 <= x.thimble_id <= 50 for x in findings))
        self.assertTrue(all(x.position for x in findings))

    def test_import_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "test.db"
            with patch.object(server, "DB_PATH", db):
                server.init_db()
                first = server.import_directory(str(H209_ROOT))
                second = server.import_directory(str(H209_ROOT))
            self.assertGreater(first["inserted"], 0)
            self.assertEqual(second["inserted"], 0)
            self.assertEqual(second["skipped"], first["parsed"])

    def test_overview_contains_compact_outage_history(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(server, "DB_PATH", Path(directory) / "history.db"):
                server.init_db()
                server.import_directory(str(H209_ROOT))
                history = server.overview()["history"]
                self.assertTrue(history)
                self.assertEqual({item["outage"] for item in history}, {"H209"})
                self.assertTrue(all(item["findings"] > 0 and item["tubes"] > 0 for item in history))

    def test_import_excludes_steam_generator_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "test.db"
            with patch.object(server, "DB_PATH", db):
                server.init_db()
                options = server.report_options(str(N208_ROOT))
                selected = {}
                for option in options:
                    if not option.get("error"):
                        selected.setdefault((option["unit_id"], option["outage"], option["group"]), option["path"])
                server.import_directory(str(N208_ROOT), list(selected.values()))
                with server.connect() as connection:
                    maximum = connection.execute("SELECT MAX(thimble_id) FROM findings").fetchone()[0]
                self.assertLessEqual(maximum, 50)

    def test_ect_coverage_excludes_calibration_and_steam_generator(self):
        h209 = server.scan_thimble_directory(str(H209_ROOT))
        n208 = server.scan_thimble_directory(str(N208_ROOT))
        self.assertEqual(h209["unique_tubes"], list(range(1, 51)))
        self.assertEqual(n208["unique_tubes"], list(range(1, 51)))
        self.assertEqual(h209["missing_tubes"], [])
        self.assertEqual(n208["missing_tubes"], [])
        self.assertGreater(h209["calibration_count"], 0)
        self.assertGreater(n208["calibration_count"], 0)
        self.assertTrue(all(Path(row["path"]).parent.name.upper().startswith("TH") for row in n208["ect"]))

    def test_folder_exports_real_xlsx(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(server, "EXCEL_DIR", Path(directory)):
                result = server.export_directory_excel(str(H209_ROOT))
                target = Path(result["file_path"])
                self.assertTrue(target.is_file())
                book = load_workbook(target, read_only=True)
                self.assertEqual(book.sheetnames, ["H209"])
                sheet = book["H209"]
                self.assertEqual(sheet.max_row - 1, result["rows"])
                self.assertEqual([cell.value for cell in sheet[1]], [
                    "通道编号", "堆芯位置", "幅值（V）", "相位", "磨损深度", "三字符",
                    "测量通道（记录通道）", "磨损位置", "探头类型", "分析人员", "数据", "数据组", "备注", "堵管移位信息"])
                self.assertTrue(all(row[13] == "/"
                                    for row in sheet.iter_rows(min_row=2, values_only=True)))
                book.close()

    def test_converted_rpt_preserves_remarks_without_inventing_tube_states(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            group = root / "TH2I09CAL00001"
            group.mkdir()
            write_sum(group)
            write_ect(group, "DIR001C001I001.ECT", 1, 1, 1)
            write_ect(group, "DIR002C002I001.ECT", 2, 2, 1)
            notes = ["检查后换管", "检查后堵管"]
            write_report(group, [
                report_entry(f"DIR00{tube}C00{tube}I001.ECT", tube, tube, 1, f"raw-{tube}")
                .replace("<Analysis>Secondary</Analysis>", f"<Analysis>{note}</Analysis>")
                for tube, note in enumerate(notes, 1)
            ])
            with patch.object(server, "EXCEL_DIR", root / "exports"):
                exported = server.export_directory_excel(str(root))
            book = load_workbook(exported["file_path"], read_only=True)
            rows = list(book["H209"].values)
            headers = {value: index for index, value in enumerate(rows[0])}
            self.assertEqual([row[headers["备注"]] for row in rows[1:]], notes)
            self.assertEqual([row[headers["堵管移位信息"]] for row in rows[1:]], ["/", "/"])
            book.close()
            server.save_tube_state(dict(outage="H209", unit_id=2, thimble_id=1,
                                        state="normal", note="人工确认记录"))
            with server.connect() as db:
                before = [dict(row) for row in db.execute("SELECT * FROM tube_states")]
            imported = server.import_excel_file(exported["file_path"])
            repeated = server.import_excel_file(exported["file_path"])
            self.assertEqual(imported["inserted"], 2)
            self.assertEqual(imported["state_recognition"], dict(applied=0, pending=0, skipped=0))
            self.assertEqual(repeated["skipped"], 2)
            with server.connect() as db:
                self.assertEqual([dict(row) for row in db.execute("SELECT * FROM tube_states")], before)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM inspection_state_candidates WHERE status='pending'").fetchone()[0], 0)
                self.assertEqual([row[0] for row in db.execute("SELECT analysis FROM findings ORDER BY thimble_id")], notes)

    def test_imports_custom_standard_excel_by_header_name(self):
        with tempfile.TemporaryDirectory() as directory:
            source, db = Path(directory) / "custom.xlsx", Path(directory) / "test.db"
            book = Workbook()
            sheet = book.active
            sheet.title = "用户自定义数据"
            sheet.append(["备注", "数据组", "RPT来源", "磨损位置", "分析人员", "通道编号", "机组号", "电站名称", "三字码", "磨损深度", "幅值", "相位"])
            sheet.append(["人工备注", "TH1I20CAL00001", r"D:\source\Report-TH1I20CAL00001.rpt", "P1+40", "MQQ", 2, 1, "大亚湾", "WAR", 48, 5.07, 258])
            book.save(source)
            with patch.object(server, "DB_PATH", db):
                server.init_db()
                result = server.import_excel_file(str(source))
                repeated = server.import_excel_file(str(source))
                self.assertEqual(result["parsed"], 1)
                self.assertEqual(repeated["inserted"], 0)
                self.assertEqual(repeated["skipped"], 1)
                with server.connect() as connection:
                    row = connection.execute("SELECT outage,unit_id,thimble_id,position,location,report_path FROM findings").fetchone()
                self.assertEqual(tuple(row), ("D120", 1, 2, "G14", "P1+40", r"D:\source\Report-TH1I20CAL00001.rpt"))

    def test_imports_case_insensitive_english_template_without_column_shift(self):
        with tempfile.TemporaryDirectory() as directory:
            source, db = Path(directory) / "english.xlsx", Path(directory) / "test.db"
            book = Workbook(); sheet = book.active
            sheet.append(["Outage", "Unit Number", "Thimble ID", "Core Position", "Amplitude", "Phase", "Wear Percent", "Defect", "Measurement Channel", "Wear Location", "Analyst", "Filename", "Data Group", "Notes"])
            sheet.append(["H209", 2, 42, "M5", 5.07, 258, 22, "WAR", "P1: 4-6", "P1+10", "MQQ", "DIR042C042I001.ECT", "TH2I09CAL00001", "english import"])
            book.save(source); book.close()
            with patch.object(server, "DB_PATH", db):
                server.init_db(); result = server.import_excel_file(str(source))
                with server.connect() as connection:
                    row = connection.execute("SELECT outage,unit_id,thimble_id,position,percent,location,analyst,calgroup FROM findings").fetchone()
            self.assertEqual(result["inserted"], 1)
            self.assertEqual(tuple(row), ("H209", 2, 42, "N5", 22, "P1+10", "MQQ", "TH2I09CAL00001"))

    def test_excel_import_requires_confirmation_for_blank_indication_measurement(self):
        with tempfile.TemporaryDirectory() as directory:
            source, db = Path(directory) / "warning.xlsx", Path(directory) / "test.db"
            book = Workbook(); sheet = book.active
            sheet.append(["Outage", "Unit Number", "Thimble ID", "Core Position", "Amplitude", "Wear Percent", "Defect", "Measurement Channel", "Wear Location", "Analyst"])
            sheet.append(["F107", 1, 12, "F13", 4.91, 51, "", "P1: 4-6", "P1+42", "ZWY"])
            book.save(source); book.close()
            with patch.object(server, "DB_PATH", db):
                server.init_db(); warning = server.import_excel_file(str(source))
                with server.connect() as connection:
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM findings").fetchone()[0], 0)
                confirmed = server.import_excel_file(str(source), "review")
                resolved = server.import_excel_file(str(source), "fill_war")
                with server.connect() as connection:
                    resolved_row = connection.execute("SELECT indication,source_indication,indication_resolution FROM findings").fetchone()
            self.assertTrue(warning["requires_indication_decision"])
            self.assertEqual(warning["blank_indication"]["count"], 1)
            self.assertEqual(warning["blank_indication"]["items"][0]["volts"], 4.91)
            self.assertEqual(confirmed["inserted"], 1)
            self.assertEqual(resolved["inserted"], 0)
            self.assertEqual(tuple(resolved_row), ("WAR", "", "bulk_war"))

    def test_exports_complete_blank_indication_table(self):
        with tempfile.TemporaryDirectory() as directory:
            items = [{"outage": "H209", "unit_id": 2, "thimble_id": index % 50 + 1, "position": "B5",
                      "volts": 1.2, "degrees": 0, "percent": 22, "location": "P1", "channel": "P1: 4-6",
                      "filename": f"DIR{index:03d}.ECT", "calgroup": "TH2I09CAL00001", "analyst": "KYY",
                      "source": "Report-test.rpt"} for index in range(465)]
            with patch.object(server, "EXCEL_DIR", Path(directory)):
                result = server.export_indication_warnings(items)
                book = load_workbook(result["file_path"], read_only=True)
                sheet = book.active
                self.assertEqual(result["rows"], 465)
                self.assertEqual(sheet.max_row, 466)
                self.assertEqual(sheet.cell(2, 7).value, 1.2)
                self.assertEqual(sheet.cell(2, 15).value, "Report-test.rpt")
                book.close()

    def test_excel_import_can_bulk_resolve_blank_indications_to_war_with_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            source, db = Path(directory) / "bulk-war.xlsx", Path(directory) / "test.db"
            book = Workbook(); sheet = book.active
            sheet.append(["Outage", "Unit Number", "Thimble ID", "Core Position", "Amplitude", "Wear Percent", "Defect", "Measurement Channel", "Wear Location", "Analyst"])
            sheet.append(["F107", 1, 12, "F13", 4.91, 51, "", "P1: 4-6", "P1+42", "ZWY"])
            book.save(source); book.close()
            with patch.object(server, "DB_PATH", db):
                server.init_db(); result = server.import_excel_file(str(source), "fill_war")
                with server.connect() as connection:
                    row = connection.execute("SELECT indication,source_indication,indication_resolution FROM findings").fetchone()
                    audit = connection.execute("SELECT source_indication,resolved_indication,action FROM indication_resolution_audit").fetchone()
            self.assertEqual(result["inserted"], 1)
            self.assertEqual(tuple(row), ("WAR", "", "bulk_war"))
            self.assertEqual(tuple(audit), ("", "WAR", "bulk_war"))

    def test_folder_import_requires_confirmation_for_blank_indication_measurement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); group = root / "TH1I07CAL00001"; group.mkdir()
            write_sum(group, unit="1", outage="F107")
            write_ect(group, "DIR012C012I006.ECT", 12, 12, 6)
            write_report(group, [report_entry("DIR012C012I006.ECT", 12, 12, 6, "blank", indication="", location="P1+42", percent="51", calgroup="TH1I07CAL00001")])
            db = root / "test.db"
            with patch.object(server, "DB_PATH", db):
                server.init_db(); warning = server.import_directory(str(root))
                with server.connect() as connection:
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM findings").fetchone()[0], 0)
                confirmed = server.import_directory(str(root), blank_indication_policy="review")
            self.assertTrue(warning["requires_indication_decision"])
            self.assertEqual(warning["blank_indication"]["count"], 1)
            self.assertEqual(confirmed["inserted"], 1)

    def test_discovers_server_thimble_directories_without_fixed_depth(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "2--------红沿河项目" / "LHNP2" / "9.H209" / "2. 数据" / "2.3 指套管"
            (target / "TH2I09CAL00001").mkdir(parents=True)
            unrelated = root / "3--------宁德项目" / "NDNP1" / "N109" / "2.数据" / "2.1蒸发器"
            (unrelated / "SG1").mkdir(parents=True)
            result = server.discover_server_sources(str(root))
            self.assertEqual(len(result["items"]), 1)
            self.assertEqual(result["items"][0]["outage"], "H209")
            self.assertEqual(result["items"][0]["station"], "红沿河")
            self.assertEqual(result["items"][0]["unit_folder"], "LHNP2")
            self.assertEqual(Path(result["items"][0]["path"]), target)

    def test_infers_station_from_documented_project_and_unit_paths(self):
        samples = {
            r"DATA\1--------大亚湾项目\CNPS1\D110": "大亚湾",
            r"DATA\1--------大亚湾项目\LNPS2\L210": "岭澳",
            r"DATA\3--------宁德项目\NDNP4\N409": "宁德",
            r"DATA\4--------阳江项目\YJNP6\Y603": "阳江",
            r"DATA\5--------防城港项目\BLNP1\F107": "防城港",
            r"DATA\6--------台山项目\TSNP2\T205": "台山",
            r"DATA\7--------太平岭（惠州）项目\HENP1\P101": "惠州",
            r"DATA\8--------苍南项目\CNMP2\C201": "苍南",
        }
        for path, expected in samples.items():
            with self.subTest(path=path):
                self.assertEqual(server.infer_station(Path(path))[0], expected)

    def test_infers_outage_from_sum_when_parent_path_has_no_outage(self):
        report = DATA_ROOT / "指套管数据2" / "2.3 指套管" / "TH2I09CAL00001" / "Report-TH2I09CAL00001-KYY-SEC.rpt"
        self.assertEqual(server.infer_outage(report), "H209")

    def test_report_options_merge_byte_identical_copies(self):
        options = server.report_options(str(DATA_ROOT))
        h209 = [item for item in options if item.get("outage") == "H209" and item.get("group") == "TH2I09CAL00001"]
        self.assertEqual(len(h209), 1)
        self.assertGreaterEqual(len(h209[0]["duplicate_paths"]), 1)
        self.assertEqual(h209[0]["modified_ns"], Path(h209[0]["path"]).stat().st_mtime_ns)
        self.assertTrue(h209[0]["modified_at"])

    def test_report_policy_rejects_mixing_multiple_analysis_reports(self):
        with self.assertRaisesRegex(ValueError, "不能同时使用多份 RPT"):
            server.export_directory_excel(str(H209_ROOT), report_policy="all")
        selected = server.automatic_report_selection(str(N208_ROOT), "auto_latest")
        self.assertTrue(selected)
        self.assertEqual(len(selected), len(set(selected)))

    def test_report_option_distinguishes_entries_from_unique_tubes(self):
        options = server.report_options(str(DATA_ROOT / "指套管数据2"))
        y108 = next(item for item in options if item.get("outage") == "Y108" and item.get("group") == "TH1I08CAL00002" and "LYY" in item.get("name", ""))
        self.assertEqual(y108["records"], 41)
        self.assertEqual(y108["tube_count"], 24)
        self.assertEqual(y108["indication_count"], 32)
        f107 = [item for item in options if item.get("outage") == "F107"]
        self.assertEqual(sum(item["blank_indication"]["count"] for item in f107), 54)

    def test_strict_group_processing_and_layered_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); group = root / "TH2I09CAL00001"; group.mkdir()
            write_sum(group)
            write_ect(group, "DIR003C003I004.ECT", 3, 3, 4)
            write_ect(group, "DIR003C003I005.ECT", 3, 3, 5)
            write_ect(group, "DIR004C004I006.ECT", 5, 4, 6)
            write_ect(group, "DIR999C999I001.ECT", 999, 999, 1)
            write_report(group, [
                report_entry("DIR003C003I004.ECT", 3, 3, 4, "u1"),
                report_entry("DIR003C003I004.ECT", 3, 3, 4, "u2"),
                report_entry("DIR999C999I001.ECT", 999, 999, 1, "cal"),
                report_entry("DIR050C050I999.ECT", 50, 50, 999, "missing"),
            ])
            ignored = root / "整合一起看" / "TH2I09CAL00002"; ignored.mkdir(parents=True)
            write_sum(ignored); write_ect(ignored, "DIR001C001I001.ECT", 1, 1, 1)
            (root / "TH2I09CAL00001-copy").mkdir()
            result = server.process_directory(str(root))
            self.assertEqual(len(result["contexts"]), 1)
            self.assertEqual(len(result["report_rows"]), 4)
            self.assertEqual(len(result["findings"]), 2)
            tube = next(row for row in result["tube_summary"] if row["thimble_id"] == 3)
            self.assertEqual((tube["entry_count"], tube["raw_indication_count"], tube["position_group_count"]), (2, 2, 1))
            self.assertEqual(tube["position"], "E11")
            self.assertEqual(len(result["calibration_ect"]), 1)
            self.assertEqual(len(result["ect_mismatches"]), 1)
            self.assertEqual(len(result["report_reference_errors"]), 2)
            self.assertEqual(len(result["unreported_ect"]), 2)
            db = root / "test.db"
            with patch.object(server, "DB_PATH", db):
                server.init_db()
                imported = server.import_directory(str(root))
                self.assertEqual(imported["inserted"], 2)
                with server.connect() as connection:
                    rows = connection.execute("SELECT degrees,uid,measurement_type,distance,extent,length,width,comment FROM findings ORDER BY uid").fetchall()
                self.assertEqual([row["uid"] for row in rows], ["u1", "u2"])
                self.assertTrue(all(row["degrees"] == 0 for row in rows))
                self.assertTrue(all(tuple(row[key] for key in ("measurement_type", "distance", "extent", "length", "width", "comment")) == ("Point", "10", "2", "3", "4", "note") for row in rows))

    def test_missing_sum_never_guesses_unit_or_position(self):
        with tempfile.TemporaryDirectory() as directory:
            group = Path(directory) / "TH2I09CAL00001"; group.mkdir()
            write_ect(group, "DIR003C003I004.ECT", 3, 3, 4)
            write_report(group, [report_entry("DIR003C003I004.ECT", 3, 3, 4, "u1")])
            result = server.process_directory(directory)
            self.assertEqual(result["findings"][0].unit_id, 0)
            self.assertEqual(result["findings"][0].position, "")
            self.assertTrue(result["sum_warnings"])
            self.assertTrue(result["mapping_failures"])

    def test_physical_duplicate_hash_classification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for branch, marker in (("a", "same"), ("b", "same"), ("c", "different")):
                group = root / branch / "TH2I09CAL00001"; group.mkdir(parents=True)
                write_sum(group); write_ect(group, "DIR003C003I004.ECT", 3, 3, 4, marker)
            result = server.process_directory(directory)
            self.assertEqual(len(result["duplicate_same_hash"]), 1)
            self.assertEqual(len(result["same_name_different_hash"]), 3)

    def test_file_exports_write_provenance_and_audit_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(server, "DB_PATH", root / "audit.db"), \
                 patch.object(server, "REPORT_DIR", root / "output"), \
                 patch.object(server, "EXCEL_DIR", root / "excel"):
                server.init_db()
                with server.connect() as connection:
                    connection.executemany(
                        """INSERT INTO findings(outage,unit_id,thimble_id,position,indication,percent,volts,location,channel,datapoint,analyst,imported_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                        [("H209", 2, 1, "B5", "WAR", 28, 1.2, "P1+10", "P1: 4-6", 80, "A", "now")],
                    )
                form = server.export_inspection_docx("H209", 2, {})
                self.assertTrue(form["export_audit_id"] > 0)
                self.assertEqual(form["sha256"], hashlib.sha256(Path(form["file_path"]).read_bytes()).hexdigest())
                self.assertIn("provenance.json", form["provenance_download_url"])
                provenance = Path(form["provenance_file_path"])
                self.assertEqual(provenance, Path(form["file_path"]).with_name(Path(form["file_path"]).name + ".provenance.json"))
                self.assertTrue(provenance.is_file())
                payload = json.loads(provenance.read_text(encoding="utf-8"))
                self.assertEqual(payload["export_kind"], "inspection_form")
                self.assertEqual(payload["sha256"], form["sha256"])
                self.assertEqual(payload["outage"], "H209")
                self.assertEqual(payload["unit"], 2)
                self.assertEqual(payload["rows"], 1)
                self.assertEqual(payload["finding_ids"], [1])
                self.assertEqual(payload["parser_version"], server.SERVICE_VERSION)
                self.assertTrue(payload["operator"])
                self.assertTrue(payload["rule_note"])

                warnings = server.export_indication_warnings([
                    {"outage": "H209", "unit_id": 2, "thimble_id": 1, "position": "B5", "indication": "", "percent": 28, "id": 1},
                ])
                self.assertTrue(warnings["export_audit_id"] > 0)
                warning_payload = json.loads(Path(warnings["provenance_file_path"]).read_text(encoding="utf-8"))
                self.assertEqual(warning_payload["export_kind"], "indication_warnings")
                self.assertEqual(warning_payload["outages"], ["H209"])
                self.assertEqual(warning_payload["finding_ids"], [1])
                self.assertIn("人工确认", warning_payload["note"])

                evolution = server.export_evolution_excel("H", 2)
                evolution_payload = json.loads(Path(evolution["provenance_file_path"]).read_text(encoding="utf-8"))
                self.assertEqual(evolution_payload["export_kind"], "evolution")
                self.assertEqual(evolution_payload["site"], "H")
                self.assertEqual(evolution_payload["outages"], ["H209"])

                with server.connect() as connection:
                    audits = connection.execute(
                        "SELECT export_kind,outage,unit_id,path,metadata_json FROM report_exports ORDER BY id").fetchall()
                self.assertEqual([row["export_kind"] for row in audits],
                                 ["inspection_form", "indication_warnings", "evolution"])
                self.assertEqual([row["outage"] for row in audits], ["H209", "", ""])
                self.assertEqual([row["unit_id"] for row in audits], [2, 0, 2])
                self.assertEqual(audits[0]["path"], form["file_path"])
                self.assertIn("provenance_sha256", json.loads(audits[0]["metadata_json"]))
                self.assertIn("provenance_path", json.loads(audits[0]["metadata_json"]))


if __name__ == "__main__": unittest.main()
