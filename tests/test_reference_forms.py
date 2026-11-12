import base64
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from src.backend import server, analysis_reporting, report_forms, state_transfer


class ReferenceFormsTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        for name, value in [('DB_PATH', root / 'test.db'), ('EXCEL_DIR', root / 'excel'), ('REPORT_DIR', root / 'reports')]:
            patcher = patch.object(server, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        server.init_db()

    def snapshot(self, kind='inspection', count=41):
        values = [[i, 1 if i < 4 else i % 50 + 1, 'L11', 'WAR', 1.25, 25, 'P1+42', 'M1', 'TEST'] for i in range(1, count + 1)]
        if kind == 'comparison':
            values = [[i, 1 if i < 4 else i % 50 + 1, 'L11', 1.25, 25, 'P1+42', 1.2, 24, 'P1+42', 'R', 0, '同位置'] for i in range(1, count + 1)]
        return dict(kind=kind, unit=1, outage='N108', old='N107', rows=count, values=values, metadata={'电厂名称': '验证电厂', '报告单编码': 'TEST-N108'}, warnings=[])

    def test_source_table_geometry_fonts_and_no_old_metadata(self):
        for kind in ['inspection', 'comparison']:
            before = hashlib.sha256((server.ROOT / 'assets/report-templates' / (kind + '.docx')).read_bytes()).hexdigest()
            parts, doc = report_forms.documents(server, self.snapshot(kind))
            exported = ET.fromstring(parts['word/document.xml'])
            for run in exported.findall('.//w:r', report_forms.NS):
                fonts = run.find('w:rPr/w:rFonts', report_forms.NS)
                self.assertIsNotNone(fonts)
                for attribute in ('ascii', 'hAnsi', 'eastAsia', 'cs'):
                    self.assertEqual(fonts.get(f'{{{report_forms.W}}}{attribute}'), '宋体')
            template = ET.fromstring(ZipFile(server.ROOT / 'assets/report-templates' / (kind + '.docx')).read('word/document.xml'))
            tables = doc.findall('w:body/w:tbl', report_forms.NS)
            self.assertEqual(len(tables), 3 if kind == 'inspection' else 1)
            original = template.find('w:body/w:tbl', report_forms.NS)
            for table in tables:
                for tag in ['w:tblGrid', 'w:tblPr']:
                    self.assertEqual(ET.tostring(table.find(tag, report_forms.NS)), ET.tostring(original.find(tag, report_forms.NS)))
            text = ''.join(doc.itertext())
            for token in ['{{', '宁德核电厂', 'N108ET632', 'ETbox8i-1026', '快照']:
                self.assertNotIn(token, text)
            self.assertIn('验证电厂' if kind == 'inspection' else 'N107', text)
            rendered = report_forms.preview(server, self.snapshot(kind))
            self.assertIn('rowspan="3"', rendered)
            self.assertIn('宋体', rendered)
            self.assertNotIn('仿宋', rendered)
            self.assertEqual(before, hashlib.sha256((server.ROOT / 'assets/report-templates' / (kind + '.docx')).read_bytes()).hexdigest())

    def test_explicit_ndd_measurements_are_preserved_and_missing_values_not_fabricated(self):
        snapshot = self.snapshot(count=1)
        snapshot['values'][0][3] = 'NDD'
        _, doc = report_forms.documents(server, snapshot)
        row = doc.findall('w:body/w:tbl/w:tr', report_forms.NS)[10]
        self.assertEqual([''.join(c.itertext()) for c in row.findall('w:tc', report_forms.NS)][4:],
                         ['1.25', '25', 'P1+42', 'M1'])
        snapshot['values'][0][4:8] = [None, None, '', '']
        _, doc = report_forms.documents(server, snapshot)
        row = doc.findall('w:body/w:tbl/w:tr', report_forms.NS)[10]
        self.assertEqual([''.join(c.itertext()) for c in row.findall('w:tc', report_forms.NS)][4:],
                         ['', '', '', ''])

    def test_missing_positions_do_not_merge_distinct_findings(self):
        snapshot = self.snapshot(count=2)
        for row in snapshot['values']:
            row[2] = None
        _, doc = report_forms.documents(server, snapshot)
        rows = doc.findall('w:body/w:tbl/w:tr', report_forms.NS)[10:12]
        self.assertTrue(all(row.find('.//w:vMerge', report_forms.NS) is None for row in rows))

    def test_csv_numeric_unit_scope_matches_without_truncation(self):
        content = '大修批次,机组号,通道编号,管状态,位移量(mm)\n N108 ,1.0,1,堵管,0\nN208,2,2,换管,0\n'
        result = state_transfer.preview(server, dict(filename='states.csv', content=base64.b64encode(content.encode()).decode(), outage='N108', unit_id=1))
        self.assertEqual([row['thimble_id'] for row in result['rows']], [1])

    def test_excel_report_has_original_grid_numeric_values_and_literal_text(self):
        snapshot = self.snapshot(count=21)
        snapshot.update(source_headers=['来源'], sources=[['=HYPERLINK("bad")']])
        snapshot['metadata']['电厂名称'] = '=UNTRUSTED'
        result = report_forms.workbook(server, snapshot, 'form.xlsx')
        from openpyxl import load_workbook
        book = load_workbook(Path(result['file_path']))
        self.addCleanup(book.close)
        sheet = book.worksheets[0]
        self.assertEqual(sheet.max_column, 17)
        self.assertIsInstance(sheet['A11'].value, int)
        self.assertEqual(book['来源追溯']['A2'].data_type, 's')
        self.assertFalse(any(c.data_type == 'f' for row in sheet for c in row))
        self.assertTrue(all(cell.font.name == '宋体' for row in sheet for cell in row if cell.value is not None))
        self.assertTrue(sheet.merged_cells.ranges)
        self.assertTrue(any(c.number_format == '0.00' for row in sheet for c in row))
        book.close()

    def test_negative_language_and_conflicting_events_not_applied(self):
        from src.backend.state_reference_import import recognize
        tables = [('表1', [['F102'], ['通道1，未堵管；未换管；未移位']])]
        rows, warnings, _ = recognize(tables, {'outage': 'F102'}, 'source.docx')
        self.assertEqual(rows, [])
        self.assertTrue(warnings)
        tables = [('表1', [['F102'], ['通道1，堵管；换管']])]
        rows, warnings, _ = recognize(tables, {'outage': 'F102'}, 'source.docx')
        self.assertEqual(rows, [])
        self.assertIn('同时', warnings[0])

    def test_cut_pipe_synonyms_are_shifted_only_with_a_distance(self):
        from src.backend.state_reference_import import recognize

        for description, expected, unsigned in [('割管42mm', 42, None), ('切管 -12mm', -12, None)]:
            with self.subTest(description=description):
                rows, warnings, _ = recognize(
                    [('表1', [['F102'], [f'通道1，{description}']])],
                    {'outage': 'F102'},
                    'source.docx',
                )
                self.assertEqual(warnings, [])
                self.assertEqual(len(rows), 1)
                self.assertEqual(
                    (rows[0]['state'], rows[0]['offset_mm'], rows[0]['unsigned_offset_mm']),
                    ('shifted', expected, unsigned),
                )

        for description in ['割管', '切管', '割管次数3次', '未割管', '未切管']:
            with self.subTest(description=description):
                rows, warnings, _ = recognize(
                    [('表1', [['F102'], [f'通道1，{description}']])],
                    {'outage': 'F102'},
                    'source.docx',
                )
                self.assertEqual(rows, [])

    def preview_file(self, path, outage):
        if not path.exists():
            self.skipTest('User reference not installed: ' + str(path))
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        result = state_transfer.preview(server, dict(filename=path.name, content=base64.b64encode(path.read_bytes()).decode(), outage=outage, unit_id=int(next(c for c in outage if c.isdigit()))))
        self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertTrue(all(r['outage'] == outage for r in result['rows']))
        return result

    def test_actual_word_maintenance_tables_default_distance_direction(self):
        base = server.ROOT / '项目资料/02_业务参考资料/孔姐发的/指套管数据测试 202007'
        for name, outage, count in [('防城港', 'F102', 4), ('红沿河', 'H105', 6)]:
            result = self.preview_file(base / name / (name + '指套管割管距离统计.docx'), outage)
            self.assertEqual(len(result['rows']), count)
            self.assertFalse(result['requires_direction'])
            state_transfer.apply_batch(server, dict(rows=result['rows'], confirmed=True))
            maintained = [r for r in server.query_states()["items"] if r["outage"] == outage]
            self.assertTrue(all(r["state"] == "shifted" and r["offset_mm"] is not None and r["unsigned_offset_mm"] is None for r in maintained))

    def test_actual_daya_bay_text_matrix(self):
        path = server.ROOT / '项目资料/02_业务参考资料/孔姐发的/指套管数据测试 202007/大亚湾/大亚湾基地各机组指套管割管统计.xlsx'
        result = self.preview_file(path, 'D118')
        self.assertTrue(result['rows'])
        row = next(r for r in result['rows'] if r['thimble_id'] == 2)
        self.assertEqual((row['state'], row['offset_mm'], row['unsigned_offset_mm']), ('shifted', 40, None))

    def test_actual_ningde_xls_and_fleet_summary(self):
        base = server.ROOT / '项目资料/02_业务参考资料/孔姐发的/指套管数据测试 202007'
        result = self.preview_file(base / '宁德/宁德4台机组指套管割管移位信息汇总20200804.xls', 'N101')
        row = next(r for r in result['rows'] if r['thimble_id'] == 1)
        self.assertEqual(row['offset_mm'], 41)
        self.assertIsNone(row['unsigned_offset_mm'])
        result = self.preview_file(base / '指套管割管移位统计（含阳江、防城港、红沿河）.xlsx', 'Y104')
        self.assertEqual({r['thimble_id'] for r in result['rows']}, {14, 17})
        self.assertTrue(result['warnings'])
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM tube_states').fetchone()[0], 0)

    def test_maintenance_exports_roundtrip_and_historical_scope(self):
        for code, state, offset in [('N107', 'shifted', -42), ('N108', 'plugged', 0), ('N109', 'replaced', 0)]:
            server.save_tube_state(dict(outage=code, unit_id=1, thimble_id=1, state=state, offset_mm=offset, note='验证'))
        xlsx = state_transfer.export(server, dict(outage='N108', unit_id=1))
        book = server.open_excel_workbook(server.EXCEL_DIR / xlsx['filename'])
        try:
            self.assertEqual([c.value for c in book['历次维护汇总'][1]],
                             ['通道', '在堆芯内的位置', 'N107', 'N107 来源', 'N108', 'N108 来源'])
            self.assertIn('-42', book['历次维护汇总']['C2'].value)
            self.assertEqual(book['管状态维护']['G1'].value, '来源')
            cell = book['历次维护汇总']['C2']
            self.assertEqual(cell.font.name, server.PLAIN_EXCEL_FONT)
            for edge in ("left", "right", "top", "bottom"):
                self.assertEqual(getattr(cell.border, edge).style, "thin")
                self.assertEqual(getattr(cell.border, edge).color.rgb[-6:], "000000")
        finally:
            book.close()
        docx = state_transfer.export(server, dict(outage='N108', unit_id=1, format='docx'))
        result = self.preview_file(Path(docx['file_path']), 'N107')
        self.assertEqual(result['rows'][0]['offset_mm'], -42)


if __name__ == '__main__':
    unittest.main()
