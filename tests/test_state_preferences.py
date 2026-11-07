import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.backend import server, state_preferences, state_transfer, state_recognition, state_reference_import, local_security, schema_migrations


class StatePreferencesTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        patcher = patch.object(server, 'DB_PATH', self.root / 'test.db')
        patcher.start()
        self.addCleanup(patcher.stop)
        server.init_db()

    def set_direction(self, value):
        return state_preferences.save(server, {'shift_direction': value})

    def row(self, tube=1):
        return dict(outage='F102', unit_id=1, thimble_id=tube, state='shifted',
                    offset_mm=None, unsigned_offset_mm=42, note='移位42mm')

    def test_each_direction_reaches_note_preview_validation_and_save(self):
        for tube, direction, expected in [(1, '1', 42), (2, '-1', -42), (3, 'pending', None)]:
            with self.subTest(direction=direction):
                self.set_direction(direction)
                note = state_transfer.recognize_note(server, {**self.row(tube), 'unsigned_offset_mm': None})['rows'][0]
                content = f'大修,通道,备注\nF102,{tube},移位42mm'.encode()
                preview = state_transfer.preview(server, {'filename': 'test.csv',
                    'content': base64.b64encode(content).decode()})
                # Use the same unsigned distance payload as a legacy event worksheet.
                validated = state_transfer.validate_rows(server, [self.row(tube)])[0]
                for row in [note, preview['rows'][0], validated]:
                    self.assertEqual(row['offset_mm'], expected)
                    self.assertEqual(row['unsigned_offset_mm'], 42 if expected is None else None)
                server.save_tube_state(self.row(tube))
                saved = next(r for r in server.query_states()['items'] if r['thimble_id'] == tube)
                self.assertEqual(saved['offset_mm'], expected)
                self.assertEqual(saved['unsigned_offset_mm'], 42 if expected is None else None)

    def test_explicit_signs_and_signed_export_columns_override_defaults(self):
        for direction in ('1', '-1', 'pending'):
            self.set_direction(direction)
            for text, expected in [('移位+42mm', 42), ('移位-42mm', -42), ('移位－４２ｍｍ', -42)]:
                row = state_transfer.recognize_note(server, {**self.row(), 'unsigned_offset_mm': None, 'note': text})['rows'][0]
                self.assertEqual(row['offset_mm'], expected)
                self.assertIsNone(row['unsigned_offset_mm'])
            for value in (42, -42):
                row, _ = state_recognition.parse_description('移位', value, True, default_direction=direction)
                self.assertEqual(row['offset_mm'], value)
            rows, warnings, _ = state_reference_import.recognize(
                [('历史表', [['F102'], ['通道1移位42mm']])], {}, 'history.docx', default_direction=direction)
            self.assertFalse(warnings)
            self.assertEqual(rows[0]['offset_mm'], None if direction == 'pending' else int(direction)*42)

    def test_setting_survives_restart_and_does_not_rewrite_history(self):
        self.set_direction('1')
        server.save_tube_state(self.row())
        self.set_direction('-1')
        server.init_db()
        self.assertEqual(state_preferences.direction(server), '-1')
        saved = server.query_states()['items'][0]
        self.assertEqual(saved['offset_mm'], 42)
        # Even a signed preview made before changing the default stays signed.
        server.save_tube_state({**self.row(2), 'offset_mm': 42, 'unsigned_offset_mm': None})
        self.assertEqual(server.query_states()['items'][1]['offset_mm'], 42)
        with server.connect() as db:
            logs = db.execute("SELECT operator FROM operation_logs WHERE operation_type='state_direction_setting'").fetchall()
        self.assertEqual(len(logs), 2)

    def test_initialize_once_validates_input_and_protects_readonly_accounts(self):
        self.assertFalse(state_preferences.settings(server)['initialized'])
        state_preferences.save(server, {'shift_direction': '-1', 'initialize_only': True})
        state_preferences.save(server, {'shift_direction': '1', 'initialize_only': True})
        self.assertEqual(state_preferences.direction(server), '-1')
        for invalid in (1, -1, None, '', 'bad'):
            with self.assertRaises(ValueError):
                self.set_direction(invalid)
        with local_security.identity({'id':'viewer', 'username':'reader', 'permissions':['data.read']}):
            self.assertFalse(state_preferences.settings(server)['writable'])
            with self.assertRaises(local_security.AccessError):
                self.set_direction('1')
        with local_security.identity({'id':'editor', 'username':'editor', 'permissions':['state.write']}):
            self.set_direction('pending')
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT operator FROM operation_logs ORDER BY id DESC LIMIT 1").fetchone()[0], 'editor')

    def test_version_three_database_upgrades_without_changing_states(self):
        server.save_tube_state({**self.row(), 'offset_mm': -42, 'unsigned_offset_mm': None})
        with server.connect() as db:
            db.execute('DROP TABLE state_preferences')
            db.execute('DELETE FROM schema_migrations WHERE version>=4')
            db.execute('PRAGMA user_version=3')
        server.init_db()
        self.assertEqual(schema_migrations.validate(server.DB_PATH, current=True), schema_migrations.VERSION)
        self.assertEqual(server.query_states()['items'][0]['offset_mm'], -42)

    def test_backup_restores_direction_together_with_the_business_data(self):
        self.set_direction('-1')
        server.save_tube_state(self.row())
        backup = server.create_database_backup()
        self.set_direction('pending')
        server.restore_database(backup['path'])
        self.assertEqual(state_preferences.direction(server), '-1')
        self.assertEqual(server.query_states()['items'][0]['offset_mm'], -42)

    def test_inspection_excel_import_uses_negative_and_pending_preferences(self):
        for direction, tube in [('-1', 1), ('pending', 2)]:
            self.set_direction(direction)
            book = server.Workbook()
            book.active.append(['大修号', '机组号', '通道编号', '三字码', '幅值', '备注'])
            book.active.append(['F102', 1, tube, 'WAR', 1.2, '移位42mm'])
            source = self.root / f'{tube}.xlsx'
            book.save(source)
            result = server.import_excel_file(str(source), 'review')
            self.assertEqual(result['state_recognition']['applied'], 1 if direction == '-1' else 0)
            self.assertEqual(result['state_recognition']['pending'], 1 if direction == 'pending' else 0)
        data = server.query_states()
        self.assertEqual(data['items'][0]['offset_mm'], -42)
        self.assertEqual(data['pending'][0]['unsigned_offset_mm'], 42)
        self.assertIsNone(data['pending'][0]['offset_mm'])

    def test_changing_direction_resolves_saved_unsigned_distance_without_reimport(self):
        book = server.Workbook()
        book.active.append(['大修号', '机组号', '通道编号', '三字码', '幅值', '备注'])
        book.active.append(['F102', 1, 1, 'WAR', 1.2, '移位42mm'])
        source = self.root / 'reimport-direction.xlsx'
        book.save(source)

        self.set_direction('pending')
        first = server.import_excel_file(str(source), 'review')
        self.assertEqual(first['state_recognition']['pending'], 1)
        pending = server.query_states()['pending']
        self.assertEqual(pending[0]['unsigned_offset_mm'], 42)

        self.set_direction('1')
        saved = next(row for row in server.query_states()['items'] if row['thimble_id'] == 1)
        self.assertEqual(saved['offset_mm'], 42)
        self.assertIsNone(saved['unsigned_offset_mm'])

        second = server.import_excel_file(str(source), 'review')
        self.assertEqual(second['state_recognition']['applied'], 0)
        self.assertEqual(second['state_recognition']['skipped'], 1)
        saved = next(row for row in server.query_states()['items'] if row['thimble_id'] == 1)
        self.assertEqual(saved['offset_mm'], 42)
        self.assertIsNone(saved['unsigned_offset_mm'])


if __name__ == '__main__':
    unittest.main()
