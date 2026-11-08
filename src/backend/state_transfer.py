
try:
    from . import local_security
except ImportError:
    import local_security

"""Explicit human-maintained states only; never infer normal from inspection depth."""
import base64
import csv
import io
import tempfile
import json
import re
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from pathlib import Path
from datetime import datetime

LABELS = {"normal": "正常", "plugged": "堵管", "shifted": "移位", "replaced": "换管"}
try:
    from . import artifact_naming, task_progress, tube_lifecycle, state_preferences
    from .state_recognition import MAX_STATE_ROWS, parse_direction
except ImportError:
    import artifact_naming
    import task_progress
    import tube_lifecycle
    import state_preferences
    from state_recognition import MAX_STATE_ROWS, parse_direction


def save_workbook_exact(book, target):
    # The Windows stdlib XML writer translates literal CR/LF in worksheet temp files.
    # Restore original CR-containing cells and encode CR as an XML character reference.
    book.properties.creator = local_security.actor()
    book.properties.lastModifiedBy = local_security.actor()
    raw = io.BytesIO()
    book.save(raw)
    corrected = {}
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    with ZipFile(raw) as archive:
        for index, sheet in enumerate(book.worksheets, 1):
            originals = {cell.coordinate: cell.value for row in sheet for cell in row
                         if isinstance(cell.value, str) and "\r" in cell.value}
            if not originals:
                continue
            name = f"xl/worksheets/sheet{index}.xml"
            document = ET.fromstring(archive.read(name))
            for cell in document.iter(f"{{{namespace}}}c"):
                if cell.get("r") in originals:
                    for child in list(cell):
                        cell.remove(child)
                    cell.set("t", "inlineStr")
                    text = ET.SubElement(ET.SubElement(cell, f"{{{namespace}}}is"), f"{{{namespace}}}t")
                    text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                    text.text = originals[cell.get("r")]
            corrected[name] = ET.tostring(document, encoding="utf-8").replace(b"\r", b"&#13;")
        with ZipFile(target, "w") as output:
            for entry in archive.infolist():
                output.writestr(entry, corrected.get(entry.filename, archive.read(entry.filename)))


def validate_rows(server, rows, *, default_direction=True):
    if not isinstance(rows, list) or not rows or len(rows) > MAX_STATE_ROWS:
        raise ValueError(f"请提供 1 至 {MAX_STATE_ROWS} 条明确的管状态记录")
    result, seen = [], set()
    direction = None
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f"第 {index} 条记录格式无效")
        row = dict(row)
        try:
            raw_direction = row.get("direction")
            direction = parse_direction(raw_direction)
            if str(raw_direction or "").strip():
                direction = direction or "pending"
            raw_offset = row.get("offset_mm")
            # A dedicated direction column is authoritative only for an
            # unsigned distance. Explicit +/- values remain unchanged.
            if direction in {"1", "-1"} and raw_offset not in (None, ""):
                raw_text = str(raw_offset).strip()
                if raw_text not in {"", "/", "-", "—"} and not raw_text.startswith(("+", "-")):
                    amount = float(raw_offset)
                    row["offset_mm"] = float(direction) * abs(amount)
                    row["unsigned_offset_mm"] = None
            elif direction in {"1", "-1"} and row.get("unsigned_offset_mm") not in (None, ""):
                amount = float(row["unsigned_offset_mm"])
                row["offset_mm"] = float(direction) * abs(amount)
                row["unsigned_offset_mm"] = None
            for key in ("unit_id", "thimble_id"):
                number = float(row.get(key, ""))
                if not number.is_integer():
                    raise ValueError("机组与管号必须是整数")
                row[key] = int(number)
            outage, unit, tube, state, offset, note = server.validate_state_payload(row)
            row["unsigned_offset_mm"] = (server.number(row.get("unsigned_offset_mm"), float)
                                         if row.get("unsigned_offset_mm") not in (None, "") else None)
            events, stage = tube_lifecycle.validate(row, state)
            if (default_direction and direction != "pending" and "shifted" in events
                    and offset is None and row["unsigned_offset_mm"] is not None):
                if direction is None:
                    direction = state_preferences.direction(server)
                offset, unsigned = state_preferences.resolve(row["unsigned_offset_mm"], direction)
                row["offset_mm"] = offset
                row["unsigned_offset_mm"] = unsigned
            if "shifted" not in events and offset != 0:
                raise ValueError("非移位状态的位移量应为 0")
        except (ValueError, TypeError) as error:
            raise ValueError(f"第 {index} 条：{error}") from error
        key = (outage, unit, tube)
        if key in seen:
            raise ValueError(f"第 {index} 条：同一大修、机组和管号重复，请先核对")
        seen.add(key)
        result.append(dict(outage=outage, unit_id=unit, thimble_id=tube,
                           state=tube_lifecycle.projection(events), events=events, replacement_stage=stage,
                           offset_mm=offset, note=note,
                           unsigned_offset_mm=row.get("unsigned_offset_mm") if "shifted" in events and offset is None else None,
                           **({"expected_updated_at": row["expected_updated_at"]} if "expected_updated_at" in row else {}),
                           **({"source": str(row["source"] or "")} if "source" in row else {})))
    return result


def prepare_batch(server, db, data, *, history=None):
    clean = validate_rows(server, data.get("rows"))
    if history is None:
        history = tube_lifecycle.StateHistory(tube_lifecycle.rows(db))
    prepared, skipped = [], []
    for row in sorted(clean, key=lambda r: (tube_lifecycle.scope_key(r["outage"]), r["thimble_id"])):
        key = row["outage"], row["unit_id"], row["thimble_id"]
        existing = history.get(*key)
        if data.get("only_unmaintained"):
            inherited = history.effective(*key)
            if existing or inherited["plugged"] or inherited["needs_review"]:
                reason = "本次已有维护记录" if existing else "历史堵管仍有效" if inherited["plugged"] else "历史状态待核对"
                skipped.append({"outage": row["outage"], "unit_id": row["unit_id"],
                                "thimble_id": row["thimble_id"], "reason": reason})
                continue
        if data.get("mode") == "append":
            # New processing is added to this outage's facts; a bulk note never erases per-tube evidence.
            old_events = tube_lifecycle.events(existing) if existing else []
            new_events = list(dict.fromkeys(old_events + row["events"]))
            if "shifted" in old_events and "shifted" in row["events"] and existing and not data.get("bulk_edit"):
                old_offset = existing["offset_mm"] if existing.get("offset_confirmed", 1) else None
                if (old_offset != row["offset_mm"] or
                        existing.get("unsigned_offset_mm") != row["unsigned_offset_mm"]):
                    raise ValueError(f"{row['outage']} 管{row['thimble_id']}已有移位距离，请单管核对，不能批量覆盖")
            if existing and "shifted" not in row["events"] and "shifted" in old_events:
                row["offset_mm"] = existing["offset_mm"] if existing.get("offset_confirmed", 1) else None
                row["unsigned_offset_mm"] = existing.get("unsigned_offset_mm")
            if existing:
                note = row["note"]
                row["note"] = existing["note"] + ("\n" + note if note and note != existing["note"] else "")
                source = row.get("source", "")
                old_source = existing.get("source", "")
                row["source"] = old_source + ("\n" + source if source and source != old_source else "")
                if "replaced" in old_events:
                    row["replacement_stage"] = (existing.get("replacement_stage", "unknown")
                                                if set(row["events"]).issubset(old_events) else "unknown")
                elif "replaced" not in row["events"]:
                    row["replacement_stage"] = (existing.get("replacement_stage", "unknown")
                                                if set(row["events"]).issubset(old_events) else "unknown")
            row["events"] = new_events
            row["state"] = tube_lifecycle.projection(new_events)
        elif existing and "plugged" in tube_lifecycle.events(existing) and "replaced" not in row["events"]:
            # Imported/confirmed updates cannot imply that a plugged tube was unblocked.
            # Keep the existing plug fact while allowing co-events such as a later shift.
            old_events = tube_lifecycle.events(existing)
            if "shifted" in old_events and "shifted" not in row["events"]:
                row["offset_mm"] = existing["offset_mm"] if existing.get("offset_confirmed", 1) else None
                row["unsigned_offset_mm"] = existing.get("unsigned_offset_mm")
            row["events"] = list(dict.fromkeys(old_events + row["events"]))
            row["state"] = tube_lifecycle.projection(row["events"])
            row["replacement_stage"] = existing.get("replacement_stage", "unknown")
            old_note, note = existing.get("note", ""), row.get("note", "")
            row["note"] = old_note + ("\n" + note if note and note != old_note else "")
            old_source, source = existing.get("source", ""), row.get("source", "")
            row["source"] = old_source + ("\n" + source if source and source != old_source else "")
        prepared.append(row)
        history.upsert(row)
    return prepared, skipped


def preview_batch(server, data):
    with server.connect() as db:
        db.execute("BEGIN")
        revision = tube_lifecycle.revision(db)
        records = tube_lifecycle.rows(db)
        before = tube_lifecycle.StateHistory(records)
        after = tube_lifecycle.StateHistory(records)
        prepared, skipped = prepare_batch(server, db, data, history=after)
        items = []
        for row in prepared:
            key = row["outage"], row["unit_id"], row["thimble_id"]
            items.append({**row, "before": before.effective(*key),
                          "after": after.effective(*key)})
    return {"rows": items, "revision": revision, "skipped": len(skipped), "skipped_rows": skipped,
            "affected": len(items), "warnings": sum(bool(r["after"]["warnings"]) for r in items)}


def apply_batch(server, data):
    if data.get("confirmed") is not True:
        raise ValueError("批量维护必须预览并确认")
    validate_rows(server, data.get("rows"))
    changed = skipped = 0
    with server.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if "revision" in data and tube_lifecycle.revision(db) != data["revision"]:
            raise ValueError("预览后维护记录已变化，请重新预览；本次未保存任何记录")
        if data.get("import_revision") is not None and tube_lifecycle.revision(db) != data["import_revision"]:
            raise ValueError("预览后维护记录已变化，请重新导入预览；本次未保存任何记录")
        if data.get("import_revision") is not None:
            incoming_by_key = {(item["outage"], int(item["unit_id"]), int(item["thimble_id"])): item
                               for item in data["rows"]}
            for row in validate_rows(server, data.get("rows")):
                existing = db.execute("SELECT * FROM tube_states WHERE outage=? AND unit_id=? AND thimble_id=?",
                                      (row["outage"], row["unit_id"], row["thimble_id"])).fetchone()
                original = incoming_by_key[row["outage"], row["unit_id"], row["thimble_id"]]
                if existing and not existing["is_deleted"] and original.get("overwrite_existing") is not True:
                    raise ValueError(f"{row['outage']} 管{row['thimble_id']}已有维护状态，本次导入已拦截覆盖；请刷新预览后确认")
                if existing and existing["is_deleted"]:
                    raise ValueError(f"{row['outage']} 管{row['thimble_id']}存在已撤销维护记录，本次导入已拦截恢复覆盖；请逐管处理")
        rows, skipped_rows = prepare_batch(server, db, data)
        skipped = len(skipped_rows)
        originals = {(r["outage"], int(r["unit_id"]), int(r["thimble_id"])): r for r in data["rows"]}
        for row in task_progress.iterate(rows, "保存维护记录", len(rows)):
            original = originals[row["outage"], row["unit_id"], row["thimble_id"]]
            existing = db.execute("SELECT * FROM tube_states WHERE outage=? AND unit_id=? AND thimble_id=?",
                                  (row["outage"], row["unit_id"], row["thimble_id"])).fetchone()
            candidate_batch = None
            if original.get("recognition_id") is not None:
                try:
                    from . import inspection_states
                except ImportError:
                    import inspection_states
                candidate_batch = inspection_states.confirm_candidate(db, original)
            server.save_tube_state(row, connection=db)
            if candidate_batch is not None:
                inspection_states.remember_state_change(db, candidate_batch, row, dict(existing) if existing else None)
            changed += 1
    return {"ok": True, "changed": changed, "skipped": skipped}


def delete_batch(server, data):
    if data.get("confirmed") is not True:
        raise ValueError("请先确认要删除的维护记录")
    records = data.get("rows")
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_STATE_ROWS:
        raise ValueError(f"请选择 1 至 {MAX_STATE_ROWS} 条维护记录")
    keys, selected = set(), []
    for record in records:
        # Deletion compares the original stored facts, including legacy records
        # whose direction was unconfirmed. Do not normalize this snapshot.
        clean = validate_rows(server, [record], default_direction=False)[0]
        key = clean["outage"], clean["unit_id"], clean["thimble_id"]
        if key in keys:
            raise ValueError("删除列表存在重复的维护记录")
        keys.add(key)
        selected.append((key, clean, record.get("updated_at")))
    with server.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        # Check the entire selection before deleting any row.
        for key, expected, updated in selected:
            current = db.execute("SELECT * FROM tube_states WHERE outage=? AND unit_id=? AND thimble_id=?", key).fetchone()
            if not current or current["is_deleted"] or updated is None or any(
                (current[k] if k != "offset_mm" or current["offset_confirmed"] else None) != expected[k]
                for k in ("state", "offset_mm", "unsigned_offset_mm", "note") + (("source",) if "source" in expected else ())
            ) or current["updated_at"] != updated or (
                tube_lifecycle.events(dict(current)) != expected["events"] or
                (current["replacement_stage"] or "unknown") != expected["replacement_stage"]):
                raise ValueError("所选维护记录已变化，请刷新后重新选择；本次未删除任何记录")
        for _, row, _ in selected:
            server.save_tube_state(row, revoke=True, connection=db)
        db.execute("""INSERT INTO operation_logs(operation_type,scope,scope_detail,record_count,operator,created_at,note)
                      VALUES('state_delete','tube_states',?,?,?,?,'仅删除所选维护记录，检测数据保留')""",
                   (json.dumps([dict(outage=k[0], unit_id=k[1], thimble_id=k[2]) for k in keys], ensure_ascii=False),
                    len(selected), local_security.actor(), datetime.now().isoformat(timespec="seconds")))
    return {"ok": True, "deleted": len(selected)}


def recognize_note(server, data):
    try:
        from .state_recognition import parse_description, text, CODE
    except ImportError:
        from state_recognition import parse_description, text, CODE
    outage, unit, tube, *_ = server.validate_state_payload({**data, "state": "normal", "offset_mm": 0})
    original = str(data.get("note") or "")
    if not original.strip():
        raise ValueError("请先填写或粘贴外部维护说明")
    if len(original) > 20000:
        raise ValueError("维护说明过长，请只粘贴当前管的处理信息")
    normalized = text(original)
    if any(value != outage for value in re.findall(CODE, normalized.upper())):
        raise ValueError("说明中的大修与当前范围不一致，请核对后再识别")
    tubes = re.findall(r"(?:通道(?:号|编号)?|管号|指套管编号)\s*0*(\d{1,2})(?!\d)", normalized)
    if any(int(value) != tube for value in tubes):
        raise ValueError("说明中包含其他管号，请只粘贴当前管的处理信息")
    facts, reason = parse_description(original, default_direction=state_preferences.direction(server))
    if not facts:
        raise ValueError(reason)
    row = dict(outage=outage, unit_id=unit, thimble_id=tube, **facts,
               note=original, source=str(data.get("source") or ""))
    validate_rows(server, [row])
    return {"rows": [row], "warnings": [], "requires_direction": row["offset_mm"] is None and row["unsigned_offset_mm"] is not None}


def preview(server, data):
    direction_policy = data.get("direction_policy", "default")
    if direction_policy not in {"default", "pending"}:
        raise ValueError("状态表方向策略无效")
    if data.get('outage'):
        server.validate_state_payload({**data, 'thimble_id': 1, 'state': 'normal', 'offset_mm': 0})
    name = Path(str(data.get("filename", "")))
    overrides = data.get("scope_overrides") or {}
    if not isinstance(overrides, dict) or len(overrides) > 200:
        raise ValueError("补充范围格式无效")
    for outage in overrides.values():
        outage = str(outage).strip().upper()
        if not re.fullmatch(r"[A-Z]{1,2}\d{3}", outage):
            raise ValueError("补充的大修编号格式应为 F102、N101 等")
        server.validate_state_payload(dict(outage=outage, unit_id=int(re.search(r"\d", outage)[0]),
                                           thimble_id=1, state="normal", offset_mm=0))
    if len(str(data.get("content", ""))) > 16_000_000:
        raise ValueError("状态表格不可超过 12 MB")
    raw = base64.b64decode(data.get("content", ""), validate=True)
    if len(raw) > 12_000_000:
        raise ValueError('状态表格不可超过 12 MB')
    suffix = name.suffix.lower()
    if suffix == ".csv":
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("gb18030")
        tables = [(name.name, list(task_progress.iterate(csv.reader(io.StringIO(text)), "读取 CSV 维护记录", span=(0, 20))))]
    elif suffix in {".xls", ".xlsx", ".xlsm"}:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / ("state" + suffix)
            target.write_bytes(raw)
            book = server.open_excel_workbook(target)
            try:
                tables = [(sheet.title, server.read_excel_rows(sheet, 0)) for sheet in
                          task_progress.iterate(book.worksheets, "读取维护工作表", unit="表", span=(0, 20), partitions=True)]
            finally:
                book.close()
        # The exported history is a display of the primary sheet, not a second input.
        if any(title == "管状态维护" and rows and list(rows[0][:6]) ==
               ["大修批次", "机组号", "通道编号", "管状态", "位移量(mm)", "备注"] for title, rows in tables):
            tables = [(title, rows) for title, rows in tables
                      if title not in {"填写说明", "历次维护汇总", "历次状态统计", "来源"}]
    elif suffix == '.docx':
        with ZipFile(io.BytesIO(raw)) as archive:
            if sum(i.file_size for i in archive.infolist()) > 40_000_000:
                raise ValueError('Word 表格展开后过大')
            document = ET.fromstring(archive.read('word/document.xml'))
        namespace = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        def paragraph_text(paragraph):
            return ''.join(node.text or '' if node.tag == '{' + namespace['w'] + '}t'
                           else '\t' if node.tag == '{' + namespace['w'] + '}tab'
                           else '\n' if node.tag in {'{' + namespace['w'] + '}br', '{' + namespace['w'] + '}cr'}
                           else '' for node in paragraph.iter())

        tables = []
        paragraphs = []
        for table in document.find('w:body', namespace):
            if table.tag == '{' + namespace['w'] + '}p':
                paragraph = paragraph_text(table)
                if paragraph.strip():
                    paragraphs.append([paragraph])
                continue
            if table.tag != '{' + namespace['w'] + '}tbl':
                continue
            values = paragraphs[-8:]
            paragraphs = []
            for row in table.findall('w:tr', namespace):
                cells = []
                for cell in row.findall('w:tc', namespace):
                    value = '\n'.join(paragraph_text(p) for p in cell.findall('w:p', namespace))
                    span = cell.find('w:tcPr/w:gridSpan', namespace)
                    width = int(span.get('{' + namespace['w'] + '}val', '1')) if span is not None else 1
                    cells.extend([value] + [''] * (max(1, min(width, 100)) - 1))
                values.append(cells)
            tables.append((f'表{len(tables) + 1}', values))
        detail_header = ['大修', '通道', '状态', '位移(mm)', '备注', '来源']
        canonical = [(title, values) for title, values in tables if any(row[:6] == detail_header for row in values)]
        if canonical:
            tables = canonical
    else:
        raise ValueError("请选择 Excel、Word (.docx) 或 CSV 状态表格")
    try:
        from .state_recognition import recognize
    except ImportError:
        from state_recognition import recognize
    unresolved = []
    task_progress.step("识别维护表格结构")
    with task_progress.phase(20, 95):
        candidates, warnings, recognized = recognize(tables, data, name.name, unresolved,
                                                     default_direction=("pending" if direction_policy == "pending"
                                                                        else state_preferences.direction(server)))
    if not recognized:
        raise ValueError("未找到管号与维护信息；支持状态列、备注说明、横向通道表、历次大修矩阵及 Word 处理记录")
    safe = []
    for row in task_progress.iterate(candidates, "校验识别到的维护记录", span=(95, 99)):
        try:
            clean = validate_rows(server, [row], default_direction=direction_policy != "pending")[0]
            # Retain the distances resolved with the current saved preference.
            safe.append(clean)
        except ValueError as error:
            warnings.append(f"{row['outage']} 管{row['thimble_id']}：{error}。{row['note']}")
    if len(safe) > MAX_STATE_ROWS:
        raise ValueError(f"识别记录超过 {MAX_STATE_ROWS} 条，请分批导入")
    missing = {}
    for row in unresolved:
        group = missing.setdefault(row["key"], dict(key=row["key"], title=row["title"],
                                                   site=row["site"], unit_id=row["unit_id"], rows=0))
        group["rows"] += 1
    with server.connect() as db:
        db.execute("BEGIN")
        revision = tube_lifecycle.revision(db)
        existing_rows = [dict(row) for row in db.execute("SELECT * FROM tube_states")]
    existing_by_key = {(row["outage"], int(row["unit_id"]), int(row["thimble_id"])): row for row in existing_rows}
    for row in safe:
        existing = existing_by_key.get((row["outage"], row["unit_id"], row["thimble_id"]))
        if existing:
            row["existing_status"] = "revoked" if existing["is_deleted"] else "same" if (
                set(tube_lifecycle.events(existing)) == set(row["events"]) and
                (existing.get("replacement_stage") or "unknown") == row["replacement_stage"] and
                (existing["offset_mm"] if existing.get("offset_confirmed", 1) else None) == row["offset_mm"] and
                existing.get("unsigned_offset_mm") == row["unsigned_offset_mm"] and
                (existing.get("note") or "") == row["note"]
            ) else "different"
            row["existing_state"] = tube_lifecycle.event_label(existing)
            row["existing_note"] = existing.get("note") or ""
            row["existing_offset_mm"] = existing["offset_mm"] if existing.get("offset_confirmed", 1) else None
    return {'rows': safe, 'warnings': warnings, 'requires_direction': any(r['offset_mm'] is None and r['unsigned_offset_mm'] is not None for r in safe),
            'filename': name.name, 'missing_scopes': list(missing.values()), 'revision': revision}


def export(server, data):
    outage, unit, *_ = server.validate_state_payload({**data, "thimble_id": 1, "state": "normal", "offset_mm": 0})
    fmt = data.get('format', 'xlsx')
    if fmt not in {'xlsx', 'docx', 'summary'}:
        raise ValueError('维护统计仅支持 Word 或 Excel')
    with server.connect() as db:
        records = {row["thimble_id"]: dict(row) for row in db.execute(
            "SELECT * FROM tube_states WHERE outage=? AND unit_id=? AND is_deleted=0", (outage, unit))}
        prefix = server.outage_code(outage)
        # Only actual maintained records, not inferred cut counts or replacement counts.
        history = [dict(row) for row in db.execute(
            "SELECT * FROM tube_states WHERE unit_id=? AND is_deleted=0 AND outage LIKE ? ORDER BY outage,thimble_id",
            (unit, prefix + '%')) if server.outage_code(row['outage']) == prefix]
    history = [r for r in history if r['outage'] <= outage]
    for row in [*history, *records.values()]:
        if not row.get("offset_confirmed", 1):
            row["offset_mm"] = None
    outages = sorted({r['outage'] for r in history} | {outage})
    positions = server.ODD_POSITIONS if unit % 2 else server.EVEN_POSITIONS
    def description(row):
        if not row:
            return ''
        detail = tube_lifecycle.event_label(row)
        if "shifted" in tube_lifecycle.events(row):
            detail += (f" {row['offset_mm']:+g} mm" if row["offset_mm"] is not None else
                       f" {row['unsigned_offset_mm']:g} mm（方向未注明）" if row.get("unsigned_offset_mm") is not None else "（距离未注明）")
        stage = {"before_replacement": "；其他处理在换管前", "after_replacement": "；其他处理在换管后"}
        if "replaced" in tube_lifecycle.events(row) and len(tube_lifecycle.events(row)) > 1:
            detail += stage.get(row.get("replacement_stage"), "；换管顺序待核对")
        return detail + ('；' + row['note'] if row.get('note') else '')
    def event_columns(row):
        return ["、".join(LABELS[name] for name in tube_lifecycle.events(row)),
                row.get("replacement_stage") or "unknown"] if row else ["", ""]
    indexed = {(r['outage'], r['thimble_id']): r for r in history}
    if fmt == 'summary':
        book = server.Workbook()
        sheet = book.active
        sheet.title = "历次状态统计"
        site = {"D": "大亚湾", "L": "岭澳", "H": "红沿河", "N": "宁德",
                "F": "防城港", "Y": "阳江", "T": "台山", "C": "苍南",
                "P": "惠州", "LF": "陆丰"}.get(prefix, prefix)
        sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=51)
        sheet.cell(1, 1, f"{site}基地 {unit}号机组 指套管状态统计表")
        sheet.cell(2, 1, "数据范围")
        sheet.cell(2, 2, f"截至 {outage}；仅含数据库中该机组已维护记录")
        sheet.cell(3, 1, "统计口径")
        sheet.cell(3, 2, "割管次数未单独记录，故不推算；空白表示未维护，不代表正常")
        for cell in sheet[1]:
            cell.fill = server.PatternFill(fill_type=None)
            cell.font = server.Font(name=server.PLAIN_EXCEL_FONT, size=14, bold=True, color="000000")
        for title_row in (2, 3):
            sheet.cell(title_row, 1).font = server.Font(name="宋体", size=10, bold=True)
        row_number = 5
        source_rows = [["大修批次", "通道号", "来源"]]
        status_codes = {"normal": "正常", "plugged": "堵管", "shifted": "移位", "replaced": "换管"}
        for code in outages:
            sheet.cell(row_number, 1, f"{code} · 通道号")
            for tube in range(1, 51):
                sheet.cell(row_number, tube + 1, tube)
            sheet.cell(row_number + 1, 1, "在堆芯内的位置")
            for tube in range(1, 51):
                sheet.cell(row_number + 1, tube + 1, positions[tube - 1])
            for offset, label in enumerate(("管状态", "移位量(mm)", "备注"), 2):
                sheet.cell(row_number + offset, 1, label)
            for tube in range(1, 51):
                record = indexed.get((code, tube))
                if not record:
                    continue
                sheet.cell(row_number + 2, tube + 1, tube_lifecycle.event_label(record))
                distance = record.get("offset_mm")
                if "shifted" in tube_lifecycle.events(record) and distance is None:
                    distance = record.get("unsigned_offset_mm")
                sheet.cell(row_number + 3, tube + 1, distance)
                sheet.cell(row_number + 4, tube + 1, record.get("note", ""))
                state_colors = {"normal": "DCEFE6", "plugged": "E4E8EB",
                                "shifted": "FFF0C9", "replaced": "DDEBFA"}
                sheet.cell(row_number + 2, tube + 1).fill = server.PatternFill(
                    "solid", fgColor=state_colors.get(record["state"], "FFFFFF"))
                source_rows.append([code, tube, record.get("source", "")])
            row_number += 6
        for row in sheet.iter_rows(min_row=5, max_row=row_number - 1, max_col=51):
            for cell in row:
                cell.font = server.Font(name="宋体", size=10, bold=cell.column == 1)
                cell.alignment = server.Alignment(horizontal="center", vertical="center", wrap_text=True)
                cell.border = server.Border(**{edge: server.Side(style="thin", color="AEBAC2")
                                               for edge in ("left", "right", "top", "bottom")})
                if isinstance(cell.value, str):
                    cell.data_type = "s"
        sheet.column_dimensions["A"].width = 20
        for column in range(2, 52):
            sheet.column_dimensions[server.get_column_letter(column)].width = 13
        sheet.freeze_panes = "B6"
        sheet.sheet_view.showGridLines = False
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.paperSize = sheet.PAPERSIZE_A3
        sheet.page_setup.fitToWidth = 3
        sheet.page_setup.fitToHeight = 0
        sheet.print_title_rows = "1:4"
        sheet.print_title_cols = "A:A"
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.sheet_properties.pageSetUpPr.autoPageBreaks = False
        sources = book.create_sheet("来源")
        for item in source_rows:
            sources.append(item)
        sources.column_dimensions["A"].width = 18
        sources.column_dimensions["B"].width = 12
        sources.column_dimensions["C"].width = 80
        server.apply_plain_excel_table(sources)
        for row in sources.iter_rows(min_row=2):
            for cell in row:
                cell.font = server.Font(name="宋体", size=10)
                cell.alignment = server.Alignment(vertical="top", wrap_text=True)
                if isinstance(cell.value, str):
                    cell.data_type = "s"
        detail = book.create_sheet("管状态维护")
        detail.append(["大修批次", "机组号", "通道编号", "管状态", "位移量(mm)", "备注", "来源", "未确认方向的距离(mm)", "维护事件", "换管顺序"])
        for tube in range(1, 51):
            record = records.get(tube, {})
            detail.append([outage, unit, tube, tube_lifecycle.event_label(record) if record else "",
                           record.get("offset_mm"), record.get("note", ""), record.get("source", ""),
                           record.get("unsigned_offset_mm"), *event_columns(record)])
        detail.freeze_panes = "A2"
        detail.auto_filter.ref = detail.dimensions
        server.apply_plain_excel_table(detail)
        for column, width in enumerate((16, 12, 12, 24, 18, 56, 56, 24, 24, 24), 1):
            detail.column_dimensions[server.get_column_letter(column)].width = width
        for row in detail.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = server.Alignment(vertical="top", wrap_text=True)
                if isinstance(cell.value, str):
                    cell.data_type = "s"
        server.EXCEL_DIR.mkdir(parents=True, exist_ok=True)
        filename = artifact_naming.filename("历次管状态统计", f"机组{unit}_{outage}", "xlsx")
        save_workbook_exact(book, server.EXCEL_DIR / filename)
        book.close()
        return {"filename": filename, "download_url": f"/api/download-excel?name={server.quote(filename)}",
                "rows": len(source_rows) - 1}
    if fmt == 'docx':
        blocks = [server._w_paragraph(f'{outage} 机组{unit} 指套管维护信息统计', bold=True, size=24)]
        # Horizontal outage headings follow the supplied Fangchenggang/Hongyanhe tables.
        for start in range(0, len(outages), 3):
            selected = outages[start:start + 3]
            entries = []
            for code in selected:
                entries.append('\n'.join(f"通道{tube:03d}，{positions[tube - 1]}：{description(indexed[code, tube])}" for tube in range(1, 51) if (code, tube) in indexed) or '无维护记录（不代表正常）')
            blocks.append(server._w_table(selected, [entries], widths=[9600 // len(selected)] * len(selected), font_size=18))
        blocks.append(server._w_paragraph('维护明细', bold=True, size=22))
        blocks.append(server._w_table(['大修', '通道', '状态', '位移(mm)', '备注', '来源', '未确认方向的距离(mm)', '维护事件', '换管顺序'],
            [[r['outage'], str(r['thimble_id']), tube_lifecycle.event_label(r), r['offset_mm'],
              r['note'], r.get('source', ''), r.get('unsigned_offset_mm'), *event_columns(r)] for r in history],
            widths=[700, 400, 650, 650, 2100, 1800, 900, 900, 1100], font_size=18))
        blocks.append(server._w_paragraph('空白状态表示未维护。移位可仅记录状态；距离或方向未明确时不自动换算位置。不得由割管次数推断换管次数。', 'left', size=18))
        result = server._write_docx(artifact_naming.filename("管状态维护", f"机组{unit}_{outage}", "docx"), blocks, landscape=False, margin=1000)
        return {**result, 'rows': len(history)}
    book = server.Workbook()
    sheet = book.active
    sheet.title = "管状态维护"
    sheet.append(["大修批次", "机组号", "通道编号", "管状态", "位移量(mm)", "备注", "来源", "未确认方向的距离(mm)", "维护事件", "换管顺序"])
    for tube in range(1, 51):
        row = records.get(tube, {})
        sheet.append([outage, unit, tube, tube_lifecycle.event_label(row) if row else "", row.get("offset_mm"), row.get("note", ""), row.get("source", ""), row.get("unsigned_offset_mm"), *event_columns(row)])
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value, str):
                cell.data_type = "s"
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    server.apply_plain_excel_table(sheet)
    for col in "ABCDEFGHIJ":
        sheet.column_dimensions[col].width = 56 if col in "FG" else 20
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = server.Alignment(vertical="top", wrap_text=True)
    notes = book.create_sheet("填写说明")
    notes.append(["规则", "内容"])
    notes.append(["空白状态", "保持未维护，导入时跳过；不推断为正常。"])
    notes.append(["管状态", "可同时记录堵管、移位、换管；维护事件以顿号分隔。移位距离可空；明确方向后填写有符号毫米值。堵管持续到换管。"])
    notes.append(["换管顺序", "unknown=未确认；before_replacement=其他处理在换管前，作用于旧管；after_replacement=其他处理在换管后，作用于新管。"])
    notes.append(["范围", "大修批次与机组号必须一致；相同大修、机组、管号不允许重复。"])
    notes.column_dimensions["A"].width = 20
    notes.column_dimensions["B"].width = 100
    matrix = book.create_sheet('历次维护汇总')
    matrix.append(['通道', '在堆芯内的位置', *[label for code in outages for label in (code, code + ' 来源')]])
    for tube in range(1, 51):
        matrix.append([tube, positions[tube - 1], *[value for code in outages for value in
                      (description(indexed.get((code, tube))), indexed.get((code, tube), {}).get("source", ""))]])
    matrix.freeze_panes = 'C2'
    matrix.auto_filter.ref = matrix.dimensions
    matrix.sheet_view.showGridLines = False
    matrix.print_title_rows = '1:1'
    matrix.page_setup.orientation = 'landscape'
    matrix.page_setup.paperSize = matrix.PAPERSIZE_A4
    matrix.page_setup.fitToWidth = 1
    matrix.sheet_properties.pageSetUpPr.fitToPage = True
    server.apply_plain_excel_table(matrix)
    for row in matrix:
        for cell in row:
            if cell.row > 1:
                cell.font = server.Font(name=server.PLAIN_EXCEL_FONT, size=10, color="000000")
                cell.alignment = server.Alignment(horizontal='center', vertical='center', wrap_text=True)
            if isinstance(cell.value, str):
                cell.data_type = 's'
    matrix.column_dimensions['A'].width = 10
    matrix.column_dimensions['B'].width = 18
    for col in range(3, len(outages) * 2 + 3):
        matrix.column_dimensions[server.get_column_letter(col)].width = 34
    server.EXCEL_DIR.mkdir(parents=True, exist_ok=True)
    filename = artifact_naming.filename("管状态维护", f"机组{unit}_{outage}", "xlsx")
    save_workbook_exact(book, server.EXCEL_DIR / filename)
    book.close()
    return {"filename": filename, "download_url": f"/api/download-excel?name={server.quote(filename)}", "rows": 50}
