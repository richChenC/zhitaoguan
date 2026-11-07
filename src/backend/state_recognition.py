"""Extract explicit maintenance facts from variable table layouts."""
import re
try:
    from . import task_progress, tube_lifecycle, state_preferences
except ImportError:
    import task_progress
    import tube_lifecycle
    import state_preferences
import unicodedata

CODE = r"(?<![A-Z0-9])([A-Z]{1,2}\d{3})(?![A-Z0-9])"
LABELS = {"normal": "正常", "plugged": "堵管", "shifted": "移位", "replaced": "换管"}
MAX_STATE_ROWS = 50000
STATE_WORDS = {
    "plugged": r"堵管|封堵|封管|堵头|堵塞|\bplugged\b",
    "replaced": r"换管|更换|替换|\breplaced\b",
    "shifted": r"割管移位|切管移位|割管(?!次数|数量|总数|统计|情况)|切管(?!次数|数量|总数|统计|情况)|移位|位移|\bshifted\b",
}
STATE_PATTERN = "|".join(STATE_WORDS.values())
SITES = {"大亚湾": "D", "岭澳": "L", "红沿河": "H", "宁德": "N", "防城港": "F",
         "阳江": "Y", "台山": "T", "苍南": "C", "惠州": "P", "太平岭": "P", "陆丰": "LF"}
FIELDS = {
    "tube": {"管号", "通道", "通道号", "通道编号", "指套管编号", "套管号", "thimble_id"},
    "outage": {"大修", "大修号", "大修批次", "大修编号", "outage"},
    "unit": {"机组", "机组号", "机组编号", "unit_id"},
    "state": {"状态", "管状态", "处理状态", "维护状态", "state"},
    "detail": {"堵管移位信息", "割管移位信息", "处理信息", "维护信息", "处理情况", "处理措施", "处理记录"},
    "note": {"备注", "说明", "处理说明", "note"},
    "source": {"来源", "备注来源", "记录来源", "source"},
    "offset": {"位移", "位移量", "移位量", "移位距离", "位移距离", "轴向位移", "有符号轴向位移",
               "有符号位移", "有符号位移mm", "有符号轴向位移mm", "offset_mm", "signed offset mm"},
    "unsigned": {"未确认方向的距离", "未注明方向的距离", "方向未确认距离mm",
                 "unsigned_offset_mm", "unsigned offset mm"},
    "direction": {"方向", "移位方向", "位移方向", "轴向方向", "方向（正负）", "direction", "shift direction"},
    "blocked": {"是否堵管", "堵管", "是否封堵", "封堵", "是否封管", "封管"},
    "replaced": {"是否换管", "是否更换", "换管"},
    "cuts": {"割管次数"},
    "events": {"维护事件", "maintenance_events"},
    "stage": {"换管顺序", "replacement_stage"},
}


def parse_direction(value):
    """Return an explicit sign, or None when the source does not state one.

    Words such as ``后移位`` are deliberately not treated as a negative sign:
    in maintenance records they commonly mean "after the outage", not an axial
    direction.  A dedicated direction column must therefore contain an
    unambiguous sign or direction word.
    """
    value = text(value).casefold()
    if not value:
        return None
    compact = re.sub(r"[\s_()（）\[\]【】：]", "", value)
    if any(token in compact for token in ("正负", "正/负", "不明", "待确认", "未确认", "未知", "pending", "unknown")):
        return "pending"
    if compact in {"+", "正", "正向", "正方向", "positive", "forward", "向前", "前向"}:
        return "1"
    if compact in {"-", "负", "负向", "负方向", "negative", "backward", "向后", "后向"}:
        return "-1"
    if re.search(r"positive|forward|正向|正方向|向前|前向", compact):
        return "1"
    if re.search(r"negative|backward|负向|负方向|向后|后向", compact):
        return "-1"
    if re.fullmatch(r"\+?1(?:\.0+)?", compact):
        return "1"
    if re.fullmatch(r"-1(?:\.0+)?", compact):
        return "-1"
    return None


def text(value):
    return unicodedata.normalize("NFKC", str(value if value is not None else "")).strip()


def field(value):
    label = re.sub(r"\s+|\((?:mm|毫米)\)", "", text(value).lower())
    return next((key for key, aliases in FIELDS.items() if label in aliases), None)


def integer(value):
    value = text(value)
    match = re.fullmatch(r"(?:通道|管号|#)?\s*0*(\d{1,2})(?:\.0)?(?:号(?:管|机组)?)?", value)
    return int(match[1]) if match else None


def code(value):
    found = re.findall(CODE, text(value).upper())
    return found[0] if len(set(found)) == 1 else ""


def scope_hint(value, site="", unit=None):
    value = text(value)
    explicit = code(value)
    if explicit:
        return explicit
    sites = {prefix for name, prefix in SITES.items() if name in value}
    site = next(iter(sites)) if len(sites) == 1 else site if not sites else ""
    number = r"\d{1,2}|[一二三四五六七八九十]{1,3}"

    def ordinal(raw):
        if raw.isdigit():
            return int(raw)
        digits = dict(zip("一二三四五六七八九", range(1, 10)))
        if "十" in raw:
            left, right = raw.split("十", 1)
            return digits.get(left, 1) * 10 + digits.get(right, 0)
        return digits.get(raw, 0)

    units = {ordinal(m) for m in re.findall(rf"({number})\s*号机(?:组)?", value)}
    unit = next(iter(units)) if len(units) == 1 else unit if not units else None
    outages = {ordinal(m) for m in re.findall(rf"第\s*({number})\s*次大修", value)}
    if site and unit and len(outages) == 1 and 1 <= unit <= 9:
        outage = next(iter(outages))
        if 1 <= outage <= 99:
            return f"{site}{unit}{outage:02d}"
    return ""


def parse_description(description, offset=None, signed_column=False, *, default_direction='1'):
    """Resolve unsigned distances using the saved preference; explicit signs win."""
    original = text(description)
    clean = re.sub(r"(?:割管|切管)(?:移位)?\s*(?:(?:次数|数量|总数)\s*[:：]?\s*\d*|\d+(?:\.\d+)?\s*次)", "", original)
    negation = rf"(?:未曾|未见|没有|无需|不需|未|无|不)\s*(?:(?:进行|实施|发生|安装|已|再)\s*)*(?:{STATE_PATTERN})"
    clean = re.sub(negation, "", clean, flags=re.I)
    if re.search(r"计划|建议|拟|待确认|待处理|待更换|待换管|待堵管|待封堵|待移位|待割管|待切管|尚未实施", clean):
        return None, "仅有计划或待确认的处理信息"
    if re.search(r"(?:打开|拆除|取下|移除|解除)\s*(?:了|已)?\s*(?:堵头|封堵|封管)|取消封堵", clean):
        return None, "说明含解除封堵或打开堵头，需核对当前状态"
    kinds = []
    if re.search(STATE_WORDS["plugged"], clean, re.I):
        kinds.append("plugged")
    if re.search(STATE_WORDS["replaced"], clean, re.I):
        kinds.append("replaced")
    if len(kinds) > 1:
        return None, "同时记载堵管与换管，需人工核查"
    has_shift = bool(re.search(STATE_WORDS["shifted"], clean, re.I))
    if kinds and not has_shift:
        if offset is not None and text(offset) not in {"", "/", "-", "—", "0", "0.0"}:
            return None, "非移位状态的独立位移字段不为零，请人工核查"
        return dict(state=kinds[0], offset_mm=0, unsigned_offset_mm=None), ""
    if has_shift:
        distances = []
        if offset is not None and text(offset) not in {"", "/", "-", "—"}:
            distances = [text(offset)]
        else:
            pattern = r"(?:移位|位移|切除|割管)\s*(?:[,;]\s*)?(?:距离|量)?\s*(?:了|为|约|共)?\s*[:：]?\s*\(?\s*([+-]?\d+(?:\.\d+)?)(?![\d.])\s*(mm|毫米|cm|厘米)?(?!\s*%)"
            for match in re.finditer(pattern, clean, re.I):
                value = float(match[1])
                if match[2] and match[2].lower() in {"cm", "厘米"}:
                    value *= 10
                distances.append(("+" if match[1].startswith("+") else "-" if match[1].startswith("-") else "") + f"{abs(value):g}")
        parsed = []
        for value in distances:
            match = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)\s*(mm|毫米|cm|厘米)?", value, re.I)
            if not match:
                return None, "移位距离无效"
            number = float(match[1]) * (10 if match[2] and match[2].lower() in {"cm", "厘米"} else 1)
            parsed.append((number, None) if signed_column or match[1].startswith(('+', '-'))
                          else state_preferences.resolve(number, default_direction))
        parsed = list(dict.fromkeys(parsed))
        if len(parsed) > 1:
            return None, "移位距离不唯一，需人工核查"
        if not parsed:
            facts = dict(state="shifted", offset_mm=None, unsigned_offset_mm=None)
            if kinds == ["plugged"]:
                facts.update(state="plugged", events=["plugged", "shifted"])
            return facts, ""
        facts = dict(state="shifted", offset_mm=parsed[0][0], unsigned_offset_mm=parsed[0][1])
        if kinds == ["plugged"]:
            facts.update(state="plugged", events=["plugged", "shifted"])
        return facts, ""
    if re.fullmatch(r"(?:正常|normal)(?:[;；,，:：].*)?", clean, re.I):
        if offset is not None and text(offset) not in {"", "/", "-", "—", "0", "0.0"}:
            return None, "正常状态的独立位移字段不为零，请人工核查"
        return dict(state="normal", offset_mm=0, unsigned_offset_mm=None), ""
    return None, "未记载明确的维护状态，不推断为正常、移位或换管"


def recognize(tables, data, filename, unresolved=None, *, default_direction='1'):
    candidates, warnings = [], []
    matched = False
    scope = text(data.get("outage")).upper()
    scope_unit = integer(data.get("unit_id"))
    overrides = data.get("scope_overrides") or {}

    def add(outage, tube, description, source, offset=None, signed=False, unit=None, original=None, note_override=None, source_override=None, event_override=None, stage_override=None, direction=None):
        nonlocal matched
        matched = True
        outage = text(outage).upper()
        if scope and outage and outage != scope:
            return
        if not outage and unresolved is not None:
            facts, _ = parse_description(description, offset, signed,
                                         default_direction=parse_direction(direction) or default_direction)
            tube_number = integer(tube)
            if facts and tube_number and 1 <= tube_number <= 50:
                unresolved.append(dict(key=title, title=title, source=source, site=prefix,
                                       unit_id=unit or table_unit, thimble_id=tube_number))
        if not re.fullmatch(r"[A-Z]{1,2}\d{3}", outage):
            warnings.append(f"{source}：无法确定大修编号；{description}")
            return
        inferred_unit = int(re.search(r"\d", outage)[0])
        if unit is not None and (integer(unit) != inferred_unit):
            warnings.append(f"{source}：机组与大修{outage}不一致；{description}")
            return
        if scope_unit and inferred_unit != scope_unit:
            return
        tube = integer(tube)
        if not tube or not 1 <= tube <= 50:
            warnings.append(f"{source}：管号无效；{description}")
            return
        if event_override:
            tokens = re.split(r"[、,，;；·\s]+", text(event_override))
            aliases = {**{label: name for name, label in LABELS.items()}, "割管": "shifted", "切管": "shifted"}
            names = [aliases.get(token, token) for token in tokens]
            stage = {"未确认": "unknown", "换管前": "before_replacement",
                     "换管后": "after_replacement"}.get(text(stage_override), text(stage_override) or "unknown")
            try:
                names, stage = tube_lifecycle.validate(
                    {"events": names, "replacement_stage": stage}, "normal")
                facts, reason = (parse_description("移位", offset, signed,
                                                   default_direction=parse_direction(direction) or default_direction)
                                 if "shifted" in names else
                                 (dict(offset_mm=0, unsigned_offset_mm=None), ""))
                if facts:
                    facts.update(state=tube_lifecycle.projection(names), events=names, replacement_stage=stage)
            except (ValueError, TypeError):
                facts, reason = None, "维护事件或换管顺序无效，请人工核查"
        else:
            facts, reason = parse_description(description, offset, signed,
                                              default_direction=parse_direction(direction) or default_direction)
        if not facts:
            warnings.append(f"{outage} 管{tube}：{reason}。{filename} · {source}：{description}")
            return
        candidates.append(dict(outage=outage, unit_id=inferred_unit, thimble_id=tube, **facts,
                               note=note_override if note_override is not None else str(description if original is None else original),
                               source=source_override if source_override is not None else f"{filename} · {source}",
                               _note_exact=note_override is not None))

    def events(outage, content, source, original):
        # Also accept grouped channels such as "4、15、34更换".
        pattern = rf"(?:通道(?:编号|号)?|指套管(?:编号)?|管号)\s*([0-9、,，\s]+)|(?<![\dA-Z])(\d{{1,2}}(?:[、,，]\s*\d{{1,2}})+)\s*(?=(?:{STATE_PATTERN}))"
        found = list(re.finditer(pattern, text(content)))
        for i, event in enumerate(found):
            description = text(content)[event.end():found[i + 1].start() if i + 1 < len(found) else len(text(content))]
            for tube in re.findall(r"\d+", event[1] or event[2]):
                add(outage, tube, description.lstrip("，,:： "), source, original=original)

    for title, raw_rows in task_progress.iterate(tables, "识别维护工作表", unit="表", partitions=True):
        source_rows = [[str(v) if v is not None else "" for v in row] for row in raw_rows]
        rows = [[text(v) for v in row] for row in task_progress.iterate(raw_rows, f"整理维护字段 · {title}", span=(0, 15))]
        def source_value(ri, ci):
            return source_rows[ri][ci] if ci < len(source_rows[ri]) else ""

        first_header = next((i for i, row in enumerate(rows) if any(field(v) == "tube" for v in row)), 0)
        preamble = "\n".join(" ".join(row) for row in rows[:first_header])
        sheet_unit = re.match(r"([A-Z]{1,2})(\d)(?:总表)?$", text(title).upper())
        if not sheet_unit:
            sheet_unit = re.match(r"(YJ)(\d)", text(title).upper())
        prefix = ("Y" if sheet_unit and sheet_unit[1] == "YJ" else sheet_unit[1]) if sheet_unit else ""
        unit = int(sheet_unit[2]) if sheet_unit else None
        hint = f"{title}\n{preamble}\n{filename}"
        sites = {p for name, p in SITES.items() if name in hint}
        if not prefix and len(sites) == 1:
            prefix = next(iter(sites))
        sheet_code = scope_hint(title, prefix, unit) or scope_hint(preamble, prefix, unit)
        if not sheet_code:
            file_code = scope_hint(filename, prefix, unit)
            if file_code and (not prefix or re.fullmatch(prefix + r"\d{3}", file_code)) and (
                    not unit or int(re.search(r"\d", file_code)[0]) == unit):
                sheet_code = file_code
        if sheet_code:
            prefix = re.match(r"[A-Z]+", sheet_code)[0]
            unit = int(re.search(r"\d", sheet_code)[0])
        table_unit = unit
        fallback = text(overrides.get(title)).upper()
        if fallback and (not re.fullmatch(r"[A-Z]{1,2}\d{3}", fallback)
                         or prefix and not re.fullmatch(prefix + r"\d{3}", fallback)
                         or unit and int(re.search(r"\d", fallback)[0]) != unit):
            raise ValueError(f"{title}：补充的大修编号与表内基地或机组不一致")
        # Outage headings above Word paragraphs of channel events.
        for ri, row in enumerate(rows[:-1]):
            for ci, value in enumerate(row):
                if re.fullmatch(r"[A-Z]{1,2}\d{3}", value.upper()):
                    content = rows[ri + 1][ci] if ci < len(rows[ri + 1]) else ""
                    if re.search(r"通道|" + STATE_PATTERN, content, re.I):
                        matched = True
                        events(value.upper(), content, f"{title}第{ri + 2}行", source_value(ri + 1, ci))
        # Horizontal channel blocks with labeled fact rows or text events.
        for ri, row in enumerate(task_progress.iterate(rows, f"识别维护信息 · {title}", span=(15, 50))):
            for label_col, label in enumerate(row):
                if field(label) != "tube":
                    continue
                tubes = [(ci, integer(v)) for ci, v in enumerate(row) if ci > label_col and integer(v) and 1 <= integer(v) <= 50]
                if not tubes:
                    continue
                if not rows[ri + 1:]:
                    continue
                matched = True
                context = code(" ".join(row[:label_col])) or sheet_code or scope or fallback
                if scope and context == scope and not sheet_code and prefix and not scope.startswith(prefix):
                    continue
                block = []
                for below in rows[ri + 1:]:
                    if any(field(v) == "tube" for v in below):
                        break
                    block.append(below)
                    if len(block) >= 8:
                        break
                fields = {field(r[label_col]): r for r in block if label_col < len(r) and field(r[label_col])}
                for ci, tube in tubes:
                    if fields:
                        def value(key):
                            values = fields.get(key, [])
                            return values[ci] if ci < len(values) else ""
                        descriptions = []
                        if value("state"):
                            descriptions.append(value("state"))
                        if value("blocked").lower() in {"是", "已堵管", "堵管", "已封堵", "封堵", "已封管", "封管", "1", "yes", "true"}:
                            descriptions.append("堵管")
                        if value("replaced") in {"是", "已更换", "换管", "1", "yes"}:
                            descriptions.append("换管")
                        if value("detail"):
                            descriptions.append(value("detail"))
                        if value("note") and not value("detail"):
                            descriptions.append(value("note"))
                        if descriptions:
                            original = "；".join(descriptions)
                            if value("cuts"):
                                original += f"；割管次数：{value('cuts')}"
                            # Explicit status overrides narrative notes, but dedicated
                            # detail/flag columns remain independent maintenance facts.
                            facts = descriptions[:]
                            if value("note") and not value("detail"):
                                facts.pop()
                            parse_text = "；".join(facts) if value("state") else original
                            originals = [source_value(ri + 1 + bi, ci) for bi, below in enumerate(block)
                                         if label_col < len(below) and field(below[label_col]) in
                                         {"state", "blocked", "replaced", "detail", "note", "cuts"}
                                         and source_value(ri + 1 + bi, ci)]
                            add(context, tube, parse_text, f"{title}第{ri + 1}行", value("offset") or value("unsigned") or None,
                                signed=any(label_col < len(below) and field(below[label_col]) == "offset"
                                           and ("有符号" in below[label_col] or below[label_col] == "offset_mm") for below in block),
                                unit=unit, original="\n".join(originals),
                                note_override=next((source_value(ri + 1 + bi, ci) for bi, below in enumerate(block)
                                                    if label_col < len(below) and field(below[label_col]) == "note"), None),
                                source_override=next((source_value(ri + 1 + bi, ci) for bi, below in enumerate(block)
                                                      if label_col < len(below) and field(below[label_col]) == "source"), None),
                                direction=value("direction"))
                        elif value("cuts") and value("cuts") != "0" and (not scope or scope == context):
                            warnings.append(f"{context} 管{tube}：割管{value('cuts')}次，缺少明确移位距离/方向，保留未维护。")
                    elif block and ci < len(block[0]) and block[0][ci]:
                        content = block[0][ci]
                        found = list(re.finditer(CODE, content.upper()))
                        if found:
                            for i, event in enumerate(found):
                                add(event[1], tube, content[event.end():found[i + 1].start() if i + 1 < len(found) else len(content)], f"{title}第{ri + 2}行",
                                    original=source_value(ri + 1, ci))
                        else:
                            add(context, tube, content, f"{title}第{ri + 2}行", unit=unit, original=source_value(ri + 1, ci))
        # Vertical tables and multi-row headings. Each maintenance column is
        # paired with the nearest channel column in the same horizontal block.
        header_indices = [ri for ri, row in enumerate(rows)
                          if any(field(v) == "tube" for v in row)
                          and not any(integer(v) and 1 <= integer(v) <= 50 for v in row if field(v) != "tube")]
        for hi, header in enumerate(task_progress.iterate(header_indices, f"识别维护表头 · {title}",
                                                         span=(50, 99), partitions=True)):
            end = header_indices[hi + 1] if hi + 1 < len(header_indices) else len(rows)
            heading = rows[header]
            tube_cols = [ci for ci, v in enumerate(heading) if field(v) == "tube"]
            columns = {}
            for ci, value in enumerate(heading):
                kind = field(value)
                if kind:
                    columns.setdefault(kind, []).append(ci)
            # Matrix outage columns (N101 / 101, etc.).
            matrix = [(ci, code(v) or (prefix + v if re.fullmatch(r"\d{3}", v) and prefix else ""))
                      for ci, v in enumerate(heading)]
            matrix = [(ci, v) for ci, v in matrix if v]
            if matrix:
                matched = True
                for ri in task_progress.iterate(range(header + 1, end), f"识别历次维护矩阵 · {title}"):
                    for ci, outage in matrix:
                        if ci < len(rows[ri]) and rows[ri][ci]:
                            tube = rows[ri][tube_cols[0]] if tube_cols[0] < len(rows[ri]) else ""
                            add(outage, tube, rows[ri][ci], f"{title}第{ri + 1}行", original=source_value(ri, ci))
                continue
            maintenance = []
            for ri in range(header, min(header + 3, end)):
                if ri > header and any(c < len(rows[ri]) and integer(rows[ri][c]) for c in tube_cols):
                    break
                for ci, value in enumerate(rows[ri]):
                    if field(value) in {"state", "detail", "note", "blocked", "replaced"}:
                        maintenance.append((ri, ci, field(value)))
            if not maintenance:
                continue
            matched = True
            has_fact = any(kind != "note" for _, _, kind in maintenance)
            maintenance = [m for m in maintenance if m[2] != "note" or not has_fact or m[0] == header]
            last_tubes = {}
            start = max(m[0] for m in maintenance) + 1
            for ri in task_progress.iterate(range(start, end), f"识别管号与状态 · {title}"):
                row = rows[ri]
                for tc in tube_cols:
                    if tc < len(row) and row[tc]:
                        last_tubes[tc] = row[tc]
                # Flat status/notes/flags describe one event, not separate facts.
                flat = all(m[0] == header for m in maintenance)
                groups = [maintenance] if flat else [[m] for m in maintenance]
                for group in groups:
                    ci = group[0][1]
                    tc = max((c for c in tube_cols if c < ci), default=tube_cols[0])
                    if tc not in last_tubes:
                        continue
                    descriptions = []
                    fact_descriptions = []
                    for _, col, kind in group:
                        content = row[col] if col < len(row) else ""
                        if content in {"", "/", "-", "—"}:
                            continue
                        if kind in {"blocked", "replaced"}:
                            if content.lower() in {"是", "1", "yes", "true", "已堵管", "堵管", "已封堵", "封堵", "已封管", "封管", "已更换", "换管"}:
                                content = "堵管" if kind == "blocked" else "换管"
                                descriptions.append(content)
                                fact_descriptions.append(content)
                        else:
                            if kind == "note" and flat and any(
                                    c < len(row) and row[c] for c in columns.get("detail", [])):
                                continue
                            descriptions.append(content)
                            if kind != "note":
                                fact_descriptions.append(content)
                    if not descriptions:
                        continue
                    description = "；".join(descriptions)
                    state_cols = columns.get("state", [])
                    explicit_state = row[state_cols[0]] if flat and state_cols and state_cols[0] < len(row) else ""
                    parse_text = "；".join(fact_descriptions) if explicit_state else description
                    outage_col = columns.get("outage", [])
                    raw_outage = row[outage_col[0]] if outage_col and outage_col[0] < len(row) else ""
                    column_code = ""
                    for v in reversed(heading[:ci + 1]):
                        match = re.fullmatch(r"C(\d+)(?:/\d{4})?", v, re.I)
                        if match and prefix and unit:
                            column_code = f"{prefix}{unit}{int(match[1]):02d}"
                            break
                    context = raw_outage or sheet_code or column_code or scope or fallback
                    if scope and context == scope and not raw_outage and not sheet_code and not column_code and prefix and not scope.startswith(prefix):
                        continue
                    unit_cols = columns.get("unit", [])
                    row_unit = row[unit_cols[0]] if unit_cols and unit_cols[0] < len(row) else unit
                    offsets = columns.get("offset", [])
                    raw_offset = row[offsets[0]] if flat and offsets and offsets[0] < len(row) else None
                    unsigned_cols = columns.get("unsigned", [])
                    signed = bool(offsets and ("有符号" in heading[offsets[0]] or heading[offsets[0]] == "offset_mm"
                                  or heading[:6] in [
                                      ["大修批次", "机组号", "通道编号", "管状态", "位移量(mm)", "备注"],
                                      ["大修", "通道", "状态", "位移(mm)", "备注", "来源"]]))
                    if text(raw_offset) in {"", "/", "-", "—"} and flat and unsigned_cols and unsigned_cols[0] < len(row):
                        raw_offset = row[unsigned_cols[0]]
                        signed = False
                    direction_cols = columns.get("direction", [])
                    raw_direction = row[direction_cols[0]] if flat and direction_cols and direction_cols[0] < len(row) else None
                    found = list(re.finditer(CODE, description.upper()))
                    original = "\n".join(source_value(ri, col) for _, col, _ in group if source_value(ri, col))
                    note_cols = columns.get("note", [])
                    note_override = "\n".join(source_value(ri, col) for col in note_cols) if flat and note_cols else None
                    source_cols = columns.get("source", [])
                    source_override = "\n".join(source_value(ri, col) for col in source_cols) if flat and source_cols else None
                    event_cols, stage_cols = columns.get("events", []), columns.get("stage", [])
                    event_override = row[event_cols[0]] if flat and event_cols and event_cols[0] < len(row) else None
                    stage_override = row[stage_cols[0]] if flat and stage_cols and stage_cols[0] < len(row) else None
                    if found and not raw_outage and (not explicit_state or re.search(CODE, explicit_state.upper())):
                        for i, event in enumerate(found):
                            add(event[1], last_tubes[tc], description[event.end():found[i + 1].start() if i + 1 < len(found) else len(description)], f"{title}第{ri + 1}行",
                                raw_offset, signed, row_unit, original, note_override, source_override,
                                direction=raw_direction)
                    else:
                        add(context, last_tubes[tc], parse_text, f"{title}第{ri + 1}行",
                            raw_offset, signed, row_unit, original, note_override, source_override,
                            event_override, stage_override, raw_direction)
    unique, conflicts = {}, set()
    for row in candidates:
        key = row["outage"], row["unit_id"], row["thimble_id"]
        old = unique.get(key)
        if old and (any(row[k] != old[k] for k in ("state", "offset_mm", "unsigned_offset_mm")) or
                    tube_lifecycle.events(row) != tube_lifecycle.events(old) or
                    row.get("replacement_stage", "unknown") != old.get("replacement_stage", "unknown")):
            conflicts.add(key)
        elif old:
            if row["_note_exact"] and not old["_note_exact"]:
                old["note"], old["_note_exact"] = row["note"], True
            elif row["_note_exact"] == old["_note_exact"] and row["note"] != old["note"]:
                conflicts.add(key)
            if row["source"] != old["source"]:
                old["source"] += "\n" + row["source"]
        else:
            unique[key] = row
    for key in conflicts:
        unique.pop(key, None)
        warnings.append(f"{key[0]} 管{key[2]}：同一范围有多个不同处理事件，需人工确定，不自动覆盖。")
    for row in unique.values():
        row.pop("_note_exact")
    return list(unique.values()), list(dict.fromkeys(warnings)), matched
