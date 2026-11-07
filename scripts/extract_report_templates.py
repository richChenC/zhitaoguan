"""Distill sanitized, source-formatted report tables from read-only Word copies."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W}
ET.register_namespace('w', W)


def text(cell, value):
    paragraph = cell.find('w:p', NS)
    if paragraph is None:
        paragraph = ET.SubElement(cell, f'{{{W}}}p')
    prototype = paragraph.find('w:r', NS)
    properties = deepcopy(prototype.find('w:rPr', NS)) if prototype is not None else None
    for child in list(cell):
        if child.tag not in (f'{{{W}}}tcPr', f'{{{W}}}p') or child.tag == f'{{{W}}}p' and child is not paragraph:
            cell.remove(child)
    for child in list(paragraph):
        if child.tag != f'{{{W}}}pPr':
            paragraph.remove(child)
    run = ET.SubElement(paragraph, f'{{{W}}}r')
    if properties is not None:
        run.append(properties)
    ET.SubElement(run, f'{{{W}}}t').text = str(value)


def main():
    source = next((ROOT / 'tmp/reference-docx-20261020').glob('AB141208632*.docx'))
    destination = ROOT / 'assets/report-templates'
    destination.mkdir(parents=True, exist_ok=True)
    with ZipFile(source) as archive:
        original = ET.fromstring(archive.read('word/document.xml'))
        body = original.find('w:body', NS)
        tables = body.findall('w:tbl', NS)
        records = []
        for kind, index in [('inspection', 11), ('comparison', 7)]:
            table = deepcopy(tables[index])
            rows = table.findall('w:tr', NS)
            if kind == 'inspection':
                slots = {0: {0: '设备/部件编号：{{设备/部件编号}}', 2: '报告单编码：{{报告单编号}}'},
                         1: {1: '{{电厂名称}}', 3: '{{机组}}', 5: '{{检查类型}}'},
                         2: {1: '{{设备/部件名称}}', 3: '{{安全等级}}', 5: '{{房间号}}'},
                         3: {1: '{{检验范围}}', 3: '{{材料}}', 5: '{{尺寸}}'},
                         4: {1: '{{涡流仪型号}}', 3: '{{涡流仪出厂编号}}', 5: '{{标定管编号}}'},
                         5: {1: '{{探头类型}}', 3: '{{探头型号}}', 5: '{{探头规格}}'},
                         6: {1: '{{检验速度}}', 3: '{{采样率}}'},
                         7: {1: '{{检验频率}}', 3: '{{检验程序/版次}}'}}
                for row_index, cells in slots.items():
                    for col, value in cells.items():
                        text(rows[row_index].findall('w:tc', NS)[col], value)
                for row in rows[10:30]:
                    for cell in row.findall('w:tc', NS):
                        text(cell, '')
                        merge = cell.find('w:tcPr/w:vMerge', NS)
                        if merge is not None:
                            cell.find('w:tcPr', NS).remove(merge)
                text(rows[30].find('w:tc', NS), '备注：{{备注}}')
                # Blank all signature values; never reuse source personnel or dates.
                for row in rows[32:]:
                    for cell in row.findall('w:tc', NS)[1:]:
                        text(cell, '')
            else:
                for cell, value in zip(rows[0].findall('w:tc', NS), ['序号', '通道编号', '堆芯位置', '{{本次大修}}', '{{历史大修}}', '备注']):
                    text(cell, value)
                for row in rows[3:-1]:
                    table.remove(row)
                for cell in rows[2].findall('w:tc', NS):
                    text(cell, '')
                    merge = cell.find('w:tcPr/w:vMerge', NS)
                    if merge is not None:
                        cell.find('w:tcPr', NS).remove(merge)
                text(rows[-1].find('w:tc', NS), '备注：{{备注}}')
            # A section's geometry is declared by its following section break.
            following = list(body)[list(body).index(tables[index]) + 1:]
            section = None
            for element in following:
                section = element if element.tag == f'{{{W}}}sectPr' else element.find('w:pPr/w:sectPr', NS)
                if section is not None:
                    break
            section = deepcopy(section)
            for child in list(section):
                if child.tag in (f'{{{W}}}headerReference', f'{{{W}}}footerReference', f'{{{W}}}pgNumType'):
                    section.remove(child)
            document = ET.Element(f'{{{W}}}document')
            target_body = ET.SubElement(document, f'{{{W}}}body')
            target_body.append(table)
            target_body.append(section)
            path = destination / f'{kind}.docx'
            parts = ['styles.xml', 'fontTable.xml', 'theme/theme1.xml']
            content = '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            rels = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            for i, part in enumerate(parts):
                name = 'theme' if part.startswith('theme/') else part[:-4]
                content += f'<Override PartName="/word/{part}" ContentType="application/vnd.openxmlformats-officedocument.{"theme" if name == "theme" else "wordprocessingml." + name}+xml"/>'
                rels += f'<Relationship Id="rId{i+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/{name}" Target="{part}"/>'
            with ZipFile(path, 'w', ZIP_DEFLATED) as output:
                output.writestr('[Content_Types].xml', content + '</Types>')
                output.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
                output.writestr('word/_rels/document.xml.rels', rels + '</Relationships>')
                output.writestr('word/document.xml', ET.tostring(document, encoding='utf-8', xml_declaration=True))
                for part in parts:
                    output.writestr('word/' + part, archive.read('word/' + part))
            records.append({'kind': kind, 'source': source.name, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                            'source_table_index': index, 'template_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                            'section': ET.tostring(section, encoding='unicode')})
    (destination / 'provenance.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(records, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
