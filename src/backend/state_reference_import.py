"""Recognize historical maintenance layouts using the selected direction."""
import re
try:
    from . import state_preferences
except ImportError:
    import state_preferences

OUTAGE = r'[A-Z]{1,2}\d{3}'


def recognize(tables, data, filename, *, default_direction='1'):
    candidates, warnings, matched = [], [], False
    scope = str(data.get('outage') or '').upper()

    def add(outage, tube, description, source):
        nonlocal matched
        matched = True
        if scope and outage != scope:
            return
        if not re.fullmatch(OUTAGE, outage):
            return
        description = str(description or '').strip()
        if not description:
            return
        note = f'{filename} · {source}：{description}'
        kinds = []
        # Keep negative statements from becoming positive maintenance events.
        # 割管/切管 are historical synonyms for 移位, but a bare count still
        # must not be promoted to a state without a distance/direction record.
        affirmative = re.sub(
            r'(?:未|无|不|无需|未进行)(?:堵管|封堵|换管|更换|移位|割管|切管)(?:移位)?',
            '',
            description,
        )
        if re.search(r'堵管|封堵|堵头|堵塞', affirmative):
            kinds.append('plugged')
        if re.search(r'换管|更换|替换', affirmative):
            kinds.append('replaced')
        if len(kinds) > 1:
            warnings.append(f'{outage} 管{tube}：同一条同时记载堵管与换管，需人工核查。{note}')
            return
        if kinds:
            state, offset, unsigned = kinds[0], 0, None
        elif re.search(r'移位|割管|切管', affirmative):
            state = 'shifted'
            lengths = re.findall(r'(?:移位|切除|割管|切管)\s*[（(]?\s*([+\-＋－]?\d+(?:\.\d+)?)\s*(?:mm|毫米)', description, re.I)
            if not lengths:
                lengths = re.findall(r'移位\s*([+\-＋－]?\d+(?:\.\d+)?)(?![\d.％%])', description)
            lengths = list(dict.fromkeys(s.replace('＋', '+').replace('－', '-') for s in lengths))
            if len(lengths) != 1:
                warnings.append(f'{outage} 管{tube}：移位距离缺失或不唯一，不自动写入。{note}')
                return
            value = lengths[0]
            offset, unsigned = ((float(value), None) if value.startswith(('+', '-'))
                                else state_preferences.resolve(float(value), default_direction))
        elif re.fullmatch(r'正常|normal', description, re.I):
            state, offset, unsigned = 'normal', 0, None
        else:
            warnings.append(f'{outage} 管{tube}：仅记录割管次数或非明确状态，未推断正常、移位或换管。{note}')
            return
        unit = int(re.search(r'\d', outage)[0])
        candidates.append(dict(outage=outage, unit_id=unit, thimble_id=int(tube), state=state,
                               offset_mm=offset, unsigned_offset_mm=unsigned, note=note))

    for title, rows in tables:
        # Word distance tables: outage headings above free-text channel events.
        for ri, row in enumerate(rows[:-1]):
            for ci, value in enumerate(row):
                code = str(value or '').strip().upper()
                if re.fullmatch(OUTAGE, code):
                    content = str(rows[ri + 1][ci] or '') if ci < len(rows[ri + 1]) else ''
                    events = list(re.finditer(r'通道\s*0*(\d{1,2})(?!\d)', content))
                    if events:
                        matched = True
                    for i, event in enumerate(events):
                        add(code, event[1], content[event.end():events[i + 1].start() if i + 1 < len(events) else len(content)], f'{title}第{ri+2}行')
        # Daya Bay: alternating channel-number and textual event rows.
        for ri, row in enumerate(rows[:-1]):
            if str(row[0] or '').strip() not in {'通道号', '通道编号'}:
                continue
            if any(re.search(OUTAGE, str(v or '')) for v in rows[ri + 1]):
                matched = True
                for ci, tube in enumerate(row[1:], 1):
                    if not str(tube or '').isdigit() or ci >= len(rows[ri + 1]):
                        continue
                    content = str(rows[ri + 1][ci] or '')
                    events = list(re.finditer(OUTAGE, content))
                    for i, event in enumerate(events):
                        add(event[0], tube, content[event.end():events[i + 1].start() if i + 1 < len(events) else len(content)], f'{title}第{ri+2}行')
        # Ningde: tube rows, outages in matrix columns, unit on sheet title.
        if re.fullmatch(r'N[1-4]', title.upper()) and rows and str(rows[0][0]).strip() == '通道':
            matched = True
            for ri, row in enumerate(rows[1:], 2):
                if not str(row[0] or '').isdigit():
                    continue
                for ci, code in enumerate(rows[0][2:], 2):
                    if str(code or '').isdigit() and ci < len(row) and row[ci]:
                        add('N' + str(code), row[0], row[ci], f'{title}第{ri}行')
        # Fleet summary: channel headings followed by cut counts/blocking/notes.
        for ri, row in enumerate(rows):
            if len(row) < 4 or str(row[2] or '').strip() != '通道号':
                continue
            code = re.search(OUTAGE, str(row[1] or '').upper())
            if not code:
                continue
            matched = True
            if scope and code[0] != scope:
                continue
            block = rows[ri + 1:ri + 5]
            lookup = {str(r[2] or '').strip(): r for r in block if len(r) > 2}
            for ci, tube in enumerate(row[3:], 3):
                if not str(tube or '').isdigit():
                    continue
                def value(label):
                    r = lookup.get(label, [])
                    return str(r[ci] or '') if ci < len(r) else ''
                blocked, note, cuts = value('是否堵管'), value('备注'), value('割管次数')
                details = ('堵管；' if blocked == '是' else '') + note
                if details:
                    add(code[0], tube, details, f'{title}第{ri+1}行')
                elif cuts and cuts != '0':
                    warnings.append(f'{code[0]} 管{tube}：割管{cuts}次，缺少明确移位距离/方向，保留未维护。')
    unique = {}
    conflicts = set()
    for row in candidates:
        key = row['outage'], row['unit_id'], row['thimble_id']
        if key in unique and (row['state'], row['offset_mm'], row['unsigned_offset_mm']) != (unique[key]['state'], unique[key]['offset_mm'], unique[key]['unsigned_offset_mm']):
            conflicts.add(key)
        else:
            unique[key] = row
    for key in conflicts:
        unique.pop(key, None)
        warnings.append(f'{key[0]} 管{key[2]}：同一范围有多个不同处理事件，需人工确定，不自动覆盖。')
    return list(unique.values()), warnings, matched
