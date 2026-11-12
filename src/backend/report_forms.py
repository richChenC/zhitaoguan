"""Populate sanitized original report forms without rebuilding their formatting."""
from copy import deepcopy
import html
import math
import re
import unicodedata
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W}
ET.register_namespace('w', W)

FONT_NAME = "宋体"


def fit_form_labels(root):
    changed = False
    for index, cell in enumerate(root.findall(".//w:tc", NS), 1):
        label = "".join(node.text or "" for node in cell.findall(".//w:t", NS))
        if label != "设备/部件名称":
            continue
        width = cell.find("w:tcPr/w:tcW", NS)
        if width is None:
            continue
        set_text(cell, label)
        run = cell.find("w:p/w:r", NS)
        properties = run.find("w:rPr", NS)
        if properties is None:
            properties = ET.Element(f"{{{W}}}rPr")
            run.insert(0, properties)
        for old in properties.findall("w:fitText", NS):
            properties.remove(old)
        ET.SubElement(properties, f"{{{W}}}fitText", {
            f"{{{W}}}val": str(max(1, int(width.get(f"{{{W}}}w")) - 216)),
            f"{{{W}}}id": str(index),
        })
        changed = True
    return changed


def wrapped_note_height(text, width_points, size):
    usable = max(size, (width_points - 14) * .9)
    lines = sum(max(1, math.ceil(sum(size * (1 if unicodedata.east_asian_width(char) in "WF" else .6)
                                   for char in line) / usable))
                for line in str(text).split("\n"))
    return lines * size * 1.35 + 6


def _normalize_docx_fonts(parts):
    """Force generated Word text to use 宋体 without changing layout styles."""
    for name, raw in list(parts.items()):
        if not (name.startswith("word/") and name.endswith(".xml")):
            continue
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            continue
        changed = fit_form_labels(root)
        for run in root.findall(".//w:r", NS):
            properties = run.find("w:rPr", NS)
            if properties is None:
                properties = ET.Element(f"{{{W}}}rPr")
                run.insert(0, properties)
            fonts = properties.find("w:rFonts", NS)
            if fonts is None:
                fonts = ET.Element(f"{{{W}}}rFonts")
                # w:rStyle precedes w:rFonts in the WordprocessingML order.
                style = properties.find("w:rStyle", NS)
                if style is not None:
                    properties.insert(list(properties).index(style) + 1, fonts)
                else:
                    properties.insert(0, fonts)
            for attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
                key = f"{{{W}}}{attribute}"
                if fonts.get(key) != FONT_NAME:
                    fonts.set(key, FONT_NAME)
                    changed = True
        if changed:
            parts[name] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return parts


def set_text(cell, value):
    paragraphs = cell.findall('w:p', NS)
    paragraph = paragraphs[0] if paragraphs else ET.SubElement(cell, f'{{{W}}}p')
    run = paragraph.find('w:r', NS)
    properties = deepcopy(run.find('w:rPr', NS)) if run is not None else None
    for other in paragraphs[1:]:
        cell.remove(other)
    for child in list(paragraph):
        if child.tag != f'{{{W}}}pPr':
            paragraph.remove(child)
    run = ET.SubElement(paragraph, f'{{{W}}}r')
    if properties is not None:
        run.append(properties)
    for i, line in enumerate(str('' if value is None else value).split('\n')):
        if i:
            ET.SubElement(run, f'{{{W}}}br')
        node = ET.SubElement(run, f'{{{W}}}t')
        node.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
        node.text = line


def _field(node, path, attribute='val', default=None):
    item = node.find(path, NS)
    return item.get(f'{{{W}}}{attribute}', default) if item is not None else default


def _merge_rows(rows, values):
    """Merge only consecutive identical tube/position pairs, independently per page."""
    for i, (row, value) in enumerate(zip(rows, values)):
        pair = tuple(value[1:3])
        complete = all(x is not None and str(x).strip() for x in pair)
        same_before = i > 0 and pair == tuple(values[i - 1][1:3]) and complete
        same_after = i + 1 < len(values) and pair == tuple(values[i + 1][1:3]) and complete
        for col in (1, 2):
            cell = row.findall('w:tc', NS)[col]
            properties = cell.find('w:tcPr', NS)
            for old in properties.findall('w:vMerge', NS):
                properties.remove(old)
            if same_before or same_after:
                merge = ET.SubElement(properties, f'{{{W}}}vMerge')
                if not same_before:
                    merge.set(f'{{{W}}}val', 'restart')
                else:
                    set_text(cell, '')


def comparison_layout(table, values):
    """Repeat the authentic header and keep bounded tube groups on one page."""
    rows = table.findall('w:tr', NS)
    for row in rows[:2]:
        properties = row.find('w:trPr', NS)
        if properties is None:
            properties = ET.Element(f'{{{W}}}trPr')
            row.insert(0, properties)
        if properties.find('w:tblHeader', NS) is None:
            ET.SubElement(properties, f'{{{W}}}tblHeader')
    data = rows[2:-1]
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[end][1:3] == values[start][1:3]:
            end += 1
        # Long groups restart with explicit channel/position every twenty rows.
        for first in range(start, end, 20):
            last = min(first + 20, end)
            group = data[first:last]
            _merge_rows(group, values[first:last])
            for offset, row in enumerate(group):
                for paragraph in row.findall('w:tc/w:p', NS):
                    properties = paragraph.find('w:pPr', NS)
                    if properties is None:
                        properties = ET.Element(f'{{{W}}}pPr')
                        paragraph.insert(0, properties)
                    for old in properties.findall('w:keepNext', NS):
                        properties.remove(old)
                    if offset < len(group) - 1:
                        ET.SubElement(properties, f'{{{W}}}keepNext')
        start = end


def documents(service, snapshot):
    kind = snapshot['kind']
    path = service.ROOT / 'assets/report-templates' / (kind + '.docx')
    with ZipFile(path) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    document = ET.fromstring(parts['word/document.xml'])
    body = document.find('w:body', NS)
    prototype = deepcopy(body.find('w:tbl', NS))
    for table in body.findall('w:tbl', NS):
        body.remove(table)
    values = [list(row[:8]) for row in snapshot['values']] if kind == 'inspection' else [list(row[:10]) for row in snapshot['values']]
    for row in values:
        for column in ((4, 5) if kind == 'inspection' else (3, 4, 6, 7)):
            if isinstance(row[column], (float, int)):
                row[column] = f'{row[column]:.2f}' if column in ((4,) if kind == 'inspection' else (3, 6)) else f'{row[column]:g}'
    page_size = 20 if kind == 'inspection' else max(1, len(values))
    pages = [values[i:i + page_size] for i in range(0, len(values), page_size)] or [[]]
    fields = {**snapshot['metadata'], '机组': snapshot['unit'], '本次大修': snapshot['outage'],
              '历史大修': snapshot.get('old', ''), '检查类型': snapshot['metadata'].get('检查类型') or snapshot['outage'],
              '报告单编号': snapshot['metadata'].get('报告单编码', ''),
              '备注': ('无。' if not snapshot['warnings'] else '存在待确认记录，详见随附来源与核查凭证。') if kind == 'inspection' else
              service.comparison_note(snapshot.get('summary') or {})}
    for page_index, page in enumerate(pages):
        table = deepcopy(prototype)
        for cell in table.findall('.//w:tc', NS):
            current = ''.join(t.text or '' for t in cell.findall('.//w:t', NS))
            if '{{' in current:
                set_text(cell, re.sub(r'\{\{([^}]+)\}\}', lambda m: str(fields.get(m[1], '')), current))
        rows = table.findall('w:tr', NS)
        if kind == 'inspection':
            target = rows[10:30]
            padded = page + [[''] * 8 for _ in range(page_size - len(page))]
            for row, data in zip(target, padded):
                for cell, value in zip(row.findall('w:tc', NS), data):
                    set_text(cell, value)
            _merge_rows(target, padded)
        else:
            sample = rows[2]
            table.remove(sample)
            target = []
            for data in page:
                row = deepcopy(sample)
                for cell, value in zip(row.findall('w:tc', NS), data):
                    set_text(cell, '/' if value is None else value)
                table.insert(len(list(table)) - 1, row)
                target.append(row)
            comparison_layout(table, page)
        if kind == 'comparison':
            caption = ET.Element(f'{{{W}}}p')
            properties = ET.SubElement(caption, f'{{{W}}}pPr')
            ET.SubElement(properties, f'{{{W}}}jc', {f'{{{W}}}val': 'center'})
            ET.SubElement(properties, f'{{{W}}}keepNext')
            run = ET.SubElement(caption, f'{{{W}}}r')
            ET.SubElement(run, f'{{{W}}}t').text = '表5 涡流检验结果比对表'
            body.insert(len(list(body)) - 1, caption)
        body.insert(len(list(body)) - 1, table)
        if page_index < len(pages) - 1:
            p = ET.Element(f'{{{W}}}p')
            r = ET.SubElement(p, f'{{{W}}}r')
            ET.SubElement(r, f'{{{W}}}br', {f'{{{W}}}type': 'page'})
            body.insert(len(list(body)) - 1, p)
    parts['word/document.xml'] = ET.tostring(document, encoding='utf-8', xml_declaration=True)
    _normalize_docx_fonts(parts)
    document = ET.fromstring(parts['word/document.xml'])
    return parts, document


def write(service, snapshot, filename):
    parts, _ = documents(service, snapshot)
    service.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = service.REPORT_DIR / filename
    temporary = path.with_suffix('.tmp')
    try:
        with ZipFile(temporary, 'w', ZIP_DEFLATED) as archive:
            for name, value in parts.items():
                archive.writestr(name, value)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return {'filename': filename, 'file_path': str(path), 'download_url': '/api/download-report?name=' + service.quote(filename)}


def workbook(service, snapshot, filename):
    _, document = documents(service, snapshot)
    book = service.Workbook()
    sheet = book.active
    sheet.title = '检验结果' if snapshot['kind'] == 'inspection' else '历次大修对比'
    if snapshot['kind'] == 'comparison':
        sheet.print_title_rows = '1:2'
        sheet.oddHeader.center.text = '表5 涡流检验结果比对表'
    sheet.sheet_view.showGridLines = False
    offset = 1
    for table in document.findall('w:body/w:tbl', NS):
        grid = [int(c.get(f'{{{W}}}w')) for c in table.findall('w:tblGrid/w:gridCol', NS)]
        for ci, width in enumerate(grid, 1):
            sheet.column_dimensions[service.get_column_letter(ci)].width = max(1.5, width / 20 / 5.3)
        vertical = {}
        for ri, row in enumerate(table.findall('w:tr', NS), offset):
            sheet.row_dimensions[ri].height = max(17, float(_field(row, 'w:trPr/w:trHeight', default='340')) / 20)
            ci = 1
            for cell in row.findall('w:tc', NS):
                span = int(_field(cell, 'w:tcPr/w:gridSpan', default='1'))
                merge = cell.find('w:tcPr/w:vMerge', NS)
                if merge is not None and merge.get(f'{{{W}}}val') != 'restart':
                    origin = vertical.get(ci)
                    if origin:
                        # Extend the original merged range, not a second overlapping merge.
                        for old in list(sheet.merged_cells.ranges):
                            if old.min_row == origin and old.min_col == ci:
                                sheet.unmerge_cells(str(old))
                        sheet.merge_cells(start_row=origin, end_row=ri, start_column=ci, end_column=ci + span - 1)
                    ci += span
                    continue
                vertical.pop(ci, None)
                if merge is not None:
                    vertical[ci] = ri
                text = '\n'.join(''.join(t.text or '' for t in p.findall('.//w:t', NS)) for p in cell.findall('w:p', NS))
                target = sheet.cell(ri, ci, text)
                # Numeric data remain numeric; identifiers/header values stay literal text.
                data_row = (10 <= ri - offset < 30) if snapshot['kind'] == 'inspection' else (2 <= ri - offset < len(table.findall('w:tr', NS)) - 1)
                if data_row and re.fullmatch(r'\d+(?:\.\d+)?', text):
                    target.value = float(text) if '.' in text else int(text)
                    if re.fullmatch(r'\d+\.\d{2}', text):
                        target.number_format = '0.00'
                else:
                    target.data_type = 's'
                paragraph = cell.find('w:p', NS)
                run = paragraph.find('w:r', NS) if paragraph is not None else None
                size = float(_field(run, 'w:rPr/w:sz', default='18')) / 2 if run is not None else 9
                font = FONT_NAME
                bold = run.find('w:rPr/w:b', NS) if run is not None else None
                target.font = service.Font(name=font, size=size, bold=bold is not None and bold.get(f'{{{W}}}val', '1') != '0')
                target.alignment = service.Alignment(horizontal='center', vertical='center', wrap_text=True)
                if snapshot['kind'] == 'comparison' and ri - offset == len(table.findall('w:tr', NS)):
                    sheet.row_dimensions[ri].height = max(
                        sheet.row_dimensions[ri].height or 0,
                        wrapped_note_height(text, sum(grid) / 20, size))
                target.border = service.Border(**{edge: service.Side(style='thin', color='000000') for edge in ('left', 'right', 'top', 'bottom')})
                if span > 1:
                    sheet.merge_cells(start_row=ri, end_row=ri, start_column=ci, end_column=ci + span - 1)
                ci += span
        offset += len(table.findall('w:tr', NS)) + 2
        if offset > 3:
            from openpyxl.worksheet.pagebreak import Break
            sheet.row_breaks.append(Break(id=offset - 3))
    sheet.page_setup.orientation = 'portrait'
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_margins.left = sheet.page_margins.right = 20 / 25.4
    sheet.page_margins.top = sheet.page_margins.bottom = 25 / 25.4
    sheet.print_area = sheet.dimensions
    sources = book.create_sheet('来源追溯')
    sources.append(snapshot['source_headers'])
    for row in snapshot['sources']:
        sources.append(row)
    issues = book.create_sheet('核查提醒')
    issues.append(['通道编号', '说明'])
    for item in snapshot['warnings']:
        issues.append([item.get('thimble_id'), item.get('reason')])
    for ws in (sources, issues):
        ws.freeze_panes = 'A2'
        ws.auto_filter.ref = ws.dimensions
        for row in ws:
            for cell in row:
                if isinstance(cell.value, str):
                    cell.data_type = 's'
                cell.font = service.Font(name='宋体', size=10, bold=cell.row == 1)
                cell.alignment = service.Alignment(wrap_text=True, vertical='center')
        for column in ws.columns:
            ws.column_dimensions[column[0].column_letter].width = 26
    return service.workbook_result(filename, book)


def _paragraph_html(paragraph):
    align = _field(paragraph, 'w:pPr/w:jc', default='center')
    result = []
    for run in paragraph.findall('w:r', NS):
        size = float(_field(run, 'w:rPr/w:sz', default='18')) / 2
        family = _field(run, 'w:rPr/w:rFonts', 'eastAsia', '宋体')
        bold = run.find('w:rPr/w:b', NS)
        weight = 'bold' if bold is not None and bold.get(f'{{{W}}}val', '1') != '0' else 'normal'
        text = ''.join('<br>' if child.tag == f'{{{W}}}br' else html.escape(child.text or '') if child.tag == f'{{{W}}}t' else '' for child in run)
        result.append(f'<span style="font:{weight} {size}pt &quot;{html.escape(family, quote=True)}&quot;">{text}</span>')
    return f'<p style="text-align:{html.escape(align)}">{"".join(result) or "&nbsp;"}</p>'


def preview(service, snapshot):
    _, document = documents(service, snapshot)
    result = []
    for table in document.findall('w:body/w:tbl', NS):
        grid = [int(c.get(f'{{{W}}}w')) for c in table.findall('w:tblGrid/w:gridCol', NS)]
        trs = []
        rows = table.findall('w:tr', NS)
        for ri, row in enumerate(rows):
            cells, column = [], 0
            for cell in row.findall('w:tc', NS):
                span = int(_field(cell, 'w:tcPr/w:gridSpan', default='1'))
                merge = cell.find('w:tcPr/w:vMerge', NS)
                if merge is not None and merge.get(f'{{{W}}}val') != 'restart':
                    column += span
                    continue
                rowspan = 1
                if merge is not None:
                    for following in rows[ri + 1:]:
                        position, continuation = 0, False
                        for next_cell in following.findall('w:tc', NS):
                            if position == column:
                                m = next_cell.find('w:tcPr/w:vMerge', NS)
                                continuation = m is not None and m.get(f'{{{W}}}val') != 'restart'
                                break
                            position += int(_field(next_cell, 'w:tcPr/w:gridSpan', default='1'))
                        if not continuation:
                            break
                        rowspan += 1
                content = ''.join(_paragraph_html(p) for p in cell.findall('w:p', NS))
                cells.append(f'<td colspan="{span}" rowspan="{rowspan}">{content}</td>')
                column += span
            height = float(_field(row, 'w:trPr/w:trHeight', default='0')) / 20
            trs.append(f'<tr style="height:{height}pt">{"".join(cells)}</tr>')
        cols = ''.join(f'<col style="width:{width / sum(grid) * 100:.5f}%">' for width in grid)
        caption = '<caption>表5 涡流检验结果比对表</caption>' if snapshot['kind'] == 'comparison' else ''
        result.append(f'<article class="report-sheet source-form"><table>{caption}<colgroup>{cols}</colgroup><tbody>{"".join(trs)}</tbody></table></article>')
    return ''.join(result)
