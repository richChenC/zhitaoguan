import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.backend import analysis_reporting as rules, cross_group_review as reviews, import_audit, server


class CrossGroupReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = patch.object(server, 'DB_PATH', Path(self.temp.name) / 'test.db')
        patcher.start()
        self.addCleanup(patcher.stop)
        server.init_db()
        self.first = self.insert('F101', 'CAL1')
        self.second = self.insert('F101', 'CAL2')
        self.current = self.insert('F102', 'CAL1')

    def insert(self, outage, group, analyst='A', location='P1', measurement='wear'):
        with server.connect() as db:
            finding_id = db.execute('''INSERT INTO findings(outage,unit_id,thimble_id,position,indication,
                percent,location,analyst,calgroup,measurement_type,imported_at)
                VALUES(?,1,1,'L11','WAR',20,?,?,?,?, 'now')''',
                (outage, location, analyst, group, measurement)).lastrowid
            row = dict(db.execute('SELECT * FROM findings WHERE id=?', (finding_id,)).fetchone())
            db.execute('UPDATE findings SET business_key=?,site_code=? WHERE id=?',
                       (server.finding_business_key(row), outage[0], finding_id))
            return finding_id

    def choose(self, action='representative', **changes):
        group = reviews.listing(server)['items'][0]
        payload = dict(group_key=group['group_key'], revision=group['revision'], action=action,
                       representative_id=self.second, reason='原始报告复核', operator='复核员')
        payload.update(changes)
        reviews.save(server, payload)
        return payload

    def test_all_consumers_share_selection_and_raw_records_survive(self):
        self.assertEqual(server.compare('F101', 'F102', 1)['summary']['待确认'], 1)
        self.choose()
        self.assertEqual(len(rules.rows_for(server, outage='F101')), 1)
        self.assertEqual(server.query_findings({'outage':['F101'], 'raw':['1']})['total'], 1)
        self.assertEqual(server.query_findings({'outage':['F101'], 'sources':['1']})['total'], 2)
        self.assertEqual(server.overview()['stats']['findings'], 2)
        self.assertEqual(server.overview()['stats']['source_findings'], 3)
        self.assertEqual(rules.analysis(server, {})['summary']['records'], 2)
        self.assertEqual(len(server.tube_history('F', 1, 1)['items']), 2)
        self.assertEqual(server.compare('F101', 'F102', 1)['summary']['R'], 1)
        self.assertEqual(server.compare_many(['F101','F102'], 1)['items'][0]['comparison'], 'R')
        self.assertEqual(len(server.inspection_report_rows('F101', 1)), 1)
        self.assertEqual(server.api_analytics_bases()[0]['findingCount'], 2)
        self.assertEqual(server.api_analytics_summary('F')['activeDefects'], 2)
        self.assertEqual(server.api_analytics_group_trend('F')['series'][0]['points'][0]['findingCount'], 1)
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM findings').fetchone()[0], 3)

    def test_statistical_findings_uses_finding_exclusion_index(self):
        with server.connect() as db:
            plan = [row[3] for row in db.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM statistical_findings WHERE is_deleted=0"
            )]
        self.assertTrue(any('idx_cross_group_exclusions_finding' in detail for detail in plan), plan)
        self.assertFalse(any('SCAN e' in detail for detail in plan), plan)

    def test_report_snapshot_evidence_and_optimistic_concurrency(self):
        payload = dict(site='F', unit=1, outage='F101', kind='inspection')
        old = rules.report_snapshot(server, payload)
        stale = self.choose()
        snapshot = rules.report_snapshot(server, payload)
        self.assertNotEqual(old['snapshot_id'], snapshot['snapshot_id'])
        self.assertEqual(snapshot['rows'], 1)
        self.assertEqual(len(snapshot['sources']), 2)
        self.assertIn('否', snapshot['sources'][1][-1])
        self.assertEqual(snapshot['cross_group_reviews'][0]['operator'], "system:maintenance")
        with self.assertRaisesRegex(ValueError, '变化'):
            reviews.save(server, stale)
        with self.assertRaisesRegex(ValueError, '变化'):
            rules.export(server, {**payload, 'snapshot_id':old['snapshot_id'], 'format':'csv'})
        with self.assertRaises(ValueError):
            rules.report_snapshot(server, {**payload, 'finding_ids':[self.first]})

    def test_delete_restore_never_reactivates_review(self):
        stale = self.choose()
        group = reviews.listing(server)['items'][0]
        stale['revision'] = group['revision']
        with server.connect() as db:
            db.execute('UPDATE findings SET is_deleted=1 WHERE id=?', (self.second,))
        with server.connect() as db:
            db.execute('UPDATE findings SET is_deleted=0 WHERE id=?', (self.second,))
        group = reviews.listing(server)['items'][0]
        self.assertEqual(group['status'], 'pending')
        self.assertEqual(len(rules.rows_for(server, outage='F101')), 2)
        self.assertEqual(group['history'][0]['active'], 0)
        with self.assertRaisesRegex(ValueError, '变化'):
            reviews.save(server, stale)

    def test_membership_change_invalidates_choice_and_stale_payload(self):
        stale = self.choose()
        self.insert('F101', 'CAL3')
        self.assertEqual(reviews.listing(server)['items'][0]['status'], 'pending')
        self.assertEqual(len(rules.rows_for(server, outage='F101')), 3)
        with self.assertRaisesRegex(ValueError, '变化'):
            reviews.save(server, stale)

    def test_keep_all_reset_and_history(self):
        self.choose()
        self.choose('keep_all')
        self.assertEqual(len(rules.rows_for(server, outage='F101')), 2)
        self.assertEqual(reviews.listing(server)['items'][0]['status'], 'keep_all')
        snapshot = rules.report_snapshot(server, dict(site='F',unit=1,outage='F101',kind='inspection'))
        self.assertIn('已人工复核', snapshot['warnings'][0]['reason'])
        self.choose('reset')
        group = reviews.listing(server)['items'][0]
        self.assertEqual(group['status'], 'reset')
        self.assertEqual(len(group['history']), 3)
        self.assertEqual(len(json.loads(group['history'][0]['members_json'])), 2)

    def test_distinct_analyst_location_measurement_are_not_collapsed(self):
        self.insert('F101', 'CAL3', analyst='B')
        self.insert('F101', 'CAL4', location='P2')
        self.insert('F101', 'CAL5', measurement='other')
        self.choose()
        self.assertEqual(len(rules.rows_for(server, outage='F101')), 4)
        self.assertEqual(reviews.listing(server)['total'], 1)
        with self.assertRaisesRegex(ValueError, '组内'):
            self.choose(representative_id=self.current)

    def test_repeat_initialization_does_not_invalidate_valid_review(self):
        self.choose()
        server.init_db()
        server.init_db()
        self.assertEqual(reviews.listing(server)['items'][0]['status'], 'representative')
        self.assertEqual(len(rules.rows_for(server, outage='F101')), 1)

    def test_quality_export_includes_review_history_and_all_sources(self):
        self.choose()
        self.choose('reset')
        from openpyxl import load_workbook
        with patch.object(server, 'EXCEL_DIR', Path(self.temp.name)):
            result = import_audit.export_quality(server)
        book = load_workbook(result['file_path'])
        self.assertEqual(book['跨组复核历史'].max_row, 3)
        self.assertEqual(book['跨组复核来源'].max_row, 5)
        self.assertEqual(book['跨组复核历史']['H2'].value, '原始报告复核')
        book.close()

    def test_defect_dimensions_are_not_silently_merged(self):
        with server.connect() as db:
            db.execute('UPDATE findings SET length=? WHERE id=?', ('12', self.second))
        self.assertEqual(reviews.listing(server)['total'], 0)
        self.assertEqual(len(rules.rows_for(server, outage='F101')), 2)
