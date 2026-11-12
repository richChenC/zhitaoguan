import tempfile
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from src.backend import analysis_reporting as rules, server


class BusinessRulesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_patch = patch.object(server, 'DB_PATH', Path(self.temp.name) / 'rules.db')
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        server.init_db()

    def finding(self, outage, location='P1', tube=1, indication='WAR', percent=20):
        with server.connect() as db:
            db.execute('''INSERT INTO findings(outage,unit_id,thimble_id,position,indication,percent,location,imported_at)
                          VALUES(?,1,?,?,?,?,?,?)''',
                       (outage, tube, server.position_for(1, tube), indication, percent, location, 'now'))

    def state(self, outage, state, offset=0):
        with server.connect() as db:
            db.execute('INSERT INTO tube_states(outage,unit_id,thimble_id,state,offset_mm) VALUES(?,1,1,?,?)',
                       (outage, state, offset))

    def test_comparison_requires_explicit_history_choice(self):
        with self.assertRaisesRegex(ValueError, '请选择历史大修'):
            rules.compare(server, '', 'F102', 1)

    def test_shift_only_next_adjacent_inspection(self):
        self.finding('F101')
        self.finding('F102', 'P1+42')
        self.finding('F103', 'P1+42')
        self.state('F101', 'shifted', 42)
        self.assertEqual(server.compare('F101', 'F102', 1)['summary']['R'], 1)
        self.assertEqual(server.compare('F101', 'F103', 1)['summary']['待确认'], 1)
        self.assertEqual(server.tube_history('F', 1, 1)['items'][1]['comparison'], 'R')

    def test_plugging_does_not_block_history_or_export(self):
        for outage in ('F101', 'F102', 'F103'):
            self.finding(outage)
        self.state('F101', 'plugged')
        history = server.tube_history('F', 1, 1)['items']
        self.assertEqual([r['comparison'] for r in history], ['NI', '待确认', '待确认'])
        self.assertTrue(all('持续堵管' in r['comparison_note'] for r in history[1:]))
        with patch.object(server, 'EXCEL_DIR', Path(self.temp.name)):
            result = server.export_evolution_excel('F', 1)
            from openpyxl import load_workbook
            book = load_workbook(result['file_path'])
            # 摘要工作表插在最前（打开文件先见结论），明细行数断言指向数据工作表本身
            self.assertEqual(book["指套管纵向演变"].max_row, 4)
            self.assertEqual(book.sheetnames[0], "可视化摘要")
            book.close()

    def test_replacement_applies_after_inspection(self):
        for outage in ('F101', 'F102', 'F103', 'F104'):
            self.finding(outage)
        self.state('F102', 'replaced')
        self.assertEqual([r['comparison'] for r in server.tube_history('F', 1, 1)['items']], ['NI', 'R', 'NI', 'R'])

    def test_missing_location_is_not_inferred_from_datapoint(self):
        self.finding('F101', '')
        self.finding('F102', '')
        self.assertEqual(server.compare('F101', 'F102', 1)['summary']['待确认'], 1)
        self.assertTrue(all(r['comparison'] == '待确认' for r in server.tube_history('F', 1, 1)['items']))

    def test_invalid_state_scope_and_offsets_are_rejected(self):
        base = dict(outage='F101', unit_id=1, thimble_id=1, state='shifted')
        for change in ({'offset_mm': 'bad'}, {'offset_mm': 'nan'}, {'offset_mm': 'inf'}, {'unit_id': 2}, {'thimble_id': None}, {'state': '垫管'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                server.validate_state_payload({**base, **change})

    def test_historical_changes_invalidate_comparison_snapshot(self):
        self.finding('F101', 'P1', tube=1)
        self.finding('F101', 'P2', tube=2)
        self.finding('F102', 'P1', tube=1)
        payload = dict(site='F', unit=1, outage='F102', old='F101', kind='comparison')
        snapshot = rules.report_snapshot(server, payload)
        with server.connect() as db:
            db.execute("UPDATE findings SET percent=35 WHERE outage='F101' AND thimble_id=2")
        with self.assertRaisesRegex(ValueError, '变化'):
            rules.export(server, {**payload, 'snapshot_id': snapshot['snapshot_id'], 'format': 'csv'})

    def test_state_changes_and_revocation_keep_before_after_history(self):
        payload = dict(outage='F101', unit_id=1, thimble_id=1, state='shifted',
                       offset_mm=42, note='现场记录', operator='操作员A')
        server.save_tube_state(payload)
        server.save_tube_state({**payload, 'offset_mm': -42, 'operator': '操作员B'})
        server.save_tube_state(payload, revoke=True)
        self.assertEqual(server.query_states()['items'], [])
        history = server.tube_state_history({'outage':['F101']})['items']
        self.assertEqual([r['action'] for r in history], ['revoke', 'update', 'create'])
        self.assertEqual(json.loads(history[1]['before_json'])['offset_mm'], 42)
        self.assertEqual(json.loads(history[1]['after_json'])['offset_mm'], -42)
        self.assertEqual(history[1]['operator'], "system:maintenance")
        self.assertEqual(history[0]['effective_timing'], 'after_inspection')
        with self.assertRaisesRegex(ValueError, '已撤销'):
            server.save_tube_state(payload, revoke=True)
        self.assertEqual(len(server.tube_state_history({})['items']), 3)
        server.save_tube_state(payload)
        self.assertEqual(len(server.query_states()['items']), 1)
        self.assertEqual(len(server.tube_state_history({})['items']), 4)

    def test_state_revocation_invalidates_report_snapshot(self):
        self.finding('F101')
        payload = dict(site='F', unit=1, outage='F101', kind='inspection')
        state = dict(outage='F101', unit_id=1, thimble_id=1, state='plugged')
        server.save_tube_state(state)
        snapshot = rules.report_snapshot(server, payload)
        server.save_tube_state(state, revoke=True)
        with self.assertRaisesRegex(ValueError, '变化'):
            rules.export(server, {**payload, 'snapshot_id': snapshot['snapshot_id'], 'format': 'csv'})

    def test_revoked_state_note_is_absent_from_multi_outage_comparison(self):
        self.finding('F101')
        self.finding('F102')
        state = dict(outage='F102', unit_id=1, thimble_id=1, state='plugged', note='已撤销的处理')
        server.save_tube_state(state)
        server.save_tube_state(state, revoke=True)
        self.assertEqual(server.compare_many(['F101', 'F102'], 1)['items'][0]['note'], '')

    def test_successful_export_has_hash_scope_and_source_audit(self):
        self.finding('F101')
        payload = dict(site='F', unit=1, outage='F101', kind='inspection')
        snapshot = rules.report_snapshot(server, payload)
        with patch.object(server, 'EXCEL_DIR', Path(self.temp.name)):
            result = rules.export(server, {**payload, 'snapshot_id': snapshot['snapshot_id'],
                                          'format': 'csv', 'operator': '导出员'})
        with server.connect() as db:
            row = db.execute('SELECT * FROM report_exports').fetchone()
        self.assertRegex(result["filename"],
                         r"^TH_检验报告单_机组1_F101_\d{8}-\d{6}_[0-9a-f]{8}\.csv$")
        self.assertEqual(Path(result["provenance_filename"]).name,
                         result["filename"] + ".provenance.json")
        evidence = json.loads(row['metadata_json'])
        self.assertEqual(row['id'], result['export_audit_id'])
        self.assertEqual(row['outage'], 'F101')
        self.assertEqual(evidence['sha256'], hashlib.sha256(Path(result['file_path']).read_bytes()).hexdigest())
        self.assertEqual(evidence['snapshot_id'], snapshot['snapshot_id'])
        self.assertEqual(evidence['sources'], snapshot['sources'])
        self.assertEqual(evidence['operator'], "system:maintenance")
        companion = Path(result['provenance_file_path'])
        portable = json.loads(companion.read_text(encoding='utf-8'))
        self.assertEqual(portable['snapshot_id'], snapshot['snapshot_id'])
        self.assertEqual(portable['sources'], snapshot['sources'])
        self.assertEqual(portable['warnings'], snapshot['warnings'])
        self.assertEqual(portable['sha256'], result['sha256'])
        self.assertEqual(evidence['provenance_sha256'], hashlib.sha256(companion.read_bytes()).hexdigest())

    def test_cross_group_duplicates_exclude_other_analysts_defects_outages_and_ndd(self):
        row = dict(outage='F101', unit_id=1, thimble_id=1, analyst='A', calgroup='group1',
                   location='P1', channel='CH1', volts=1.2, degrees=0, percent=20,
                   indication='WAR', measurement_type='Point', uid='u1', datapoint=10)
        duplicate = {**row, 'calgroup':'group2', 'uid':'u2', 'datapoint':20}
        self.assertEqual(len(rules.cross_group_duplicates([row, duplicate])), 1)
        for change in ({'analyst':'B'}, {'percent':21}, {'outage':'F102'},
                       {'calgroup':'group1'}, {'thimble_id':2}, {'indication':'NDD'}):
            with self.subTest(change=change):
                self.assertEqual(rules.cross_group_duplicates([row, {**duplicate, **change}]), [])


if __name__ == '__main__':
    unittest.main()
