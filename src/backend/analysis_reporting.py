"""Database-backed analysis and report snapshots. No repair state is inferred."""
from __future__ import annotations

try:
    from . import local_security
except ImportError:
    import local_security

import csv
import getpass
import hashlib
import html
import io
import json
import re
import math
import threading
import unicodedata
from collections import Counter, OrderedDict, defaultdict
from datetime import datetime

try:
    from . import artifact_naming, tube_lifecycle, official_comparison_evidence
except ImportError:
    import artifact_naming
    import tube_lifecycle
    import official_comparison_evidence

STATE_LABELS = {"normal": "正常", "plugged": "堵管", "shifted": "移位", "replaced": "换管"}
SITE_LABELS = {"D": "大亚湾", "L": "岭澳", "N": "宁德", "H": "红沿河", "F": "防城港", "Y": "阳江", "T": "台山", "P": "惠州", "LF": "陆丰", "C": "苍南"}
RULE_NOTE = "显示分级不是验收判据。缺失字段留白；检测字段全部为空或 / 的记录按 NDD 展示；堵管不排除实际检测数据。处理记录暂按该次检查后生效；移位仅跨下一次相邻大修换算；换管保留历史并建立新基准。报告需人工复核。"
# 对比规则缺省值。数据库中未创建任何规则版本时使用；一旦建立规则版本，以激活版本为准。
DEFAULT_RULES = {"version": 0, "name": "系统初始规则", "match_tolerance_mm": 0.01,
                 "note": "系统内置初始匹配容差，未建立规则版本前的兜底值"}

# Import/display use the same source-value semantics. These are source
# placeholders, not measurements: a numeric zero remains a real supplied
# value and therefore must not be silently converted to NDD.
EMPTY_SOURCE_MARKERS = frozenset({
    "", "/", "NONE", "NO DATA", "NO DEFECT", "N/A", "NA", "NULL", "-", "—", "–",
})


def _row_value(row, name, default=None):
    """Read both sqlite rows/dicts and Finding-like dataclass objects."""
    if isinstance(row, dict):
        return row.get(name, default)
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return getattr(row, name, default)


def is_empty_source_value(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return unicodedata.normalize("NFKC", value).strip().upper() in EMPTY_SOURCE_MARKERS
    return False


def has_wear_information(row) -> bool:
    """Whether a blank indication has source evidence that can be WAR.

    Tube/thimble number is deliberately excluded: it identifies the record,
    but by itself is not wear evidence. A provided numeric zero is retained as
    source data and counts as supplied evidence; only explicit placeholders
    count as empty.
    """
    measured_fields = ("volts", "degrees", "percent", "location", "location_raw")
    if any(not is_empty_source_value(_row_value(row, field)) for field in measured_fields):
        return True

    # CH-01/CH-02 style values are record identifiers used by some exports,
    # not evidence of wear. Real recorded channels carry a measured section
    # (for example P1: 4-6) and are therefore retained as evidence.
    channel = _row_value(row, "channel")
    if not is_empty_source_value(channel):
        channel_text = unicodedata.normalize("NFKC", str(channel)).strip().upper()
        if not re.fullmatch(r"CH[-_ ]?\d+", channel_text):
            return True

    measurement = _row_value(row, "measurement_type")
    return (not is_empty_source_value(measurement)
            and str(measurement).strip().upper() not in {"POINT", "VMAX"})


def blank_indication_class(row) -> str:
    """Return source resolution class for a missing or slash indication."""
    code = str(_row_value(row, "indication", "") or "").strip().upper()
    if code not in {"", "/"}:
        return "source"
    return "war_candidate" if has_wear_information(row) else "ndd"


def rule_tolerance(rules=None) -> float:
    """取当前生效的轴向匹配容差（mm）。rules 为 None 时用 DEFAULT_RULES。"""
    try:
        value = float((rules or DEFAULT_RULES).get("match_tolerance_mm", DEFAULT_RULES["match_tolerance_mm"]))
    except (TypeError, ValueError):
        return DEFAULT_RULES["match_tolerance_mm"]
    if not math.isfinite(value) or value <= 0:
        return DEFAULT_RULES["match_tolerance_mm"]
    return value


def rule_label(rules=None) -> str:
    rules = rules or DEFAULT_RULES
    version = rules.get("version") or 0
    return f"匹配规则 v{version}（{rules.get('name') or '系统初始规则'}，轴向容差 ±{rule_tolerance(rules):g} mm）"


def site_of_outage(outage: str) -> str:
    """取大修号开头的电站代号：第二位是字母则取两位（陆丰 LF），否则取一位（岭澳 L）。

    不依赖代号清单——大修号格式恒为「电站代号 + 机组数字 + 两位序号」，
    故第二位是字母即可判定为两位代号。与 site_prefix_sql 规则一致。
    """
    text = str(outage or "").strip().upper()
    return text[:2] if len(text) > 1 and text[1].isalpha() else text[:1]


def site_prefix_sql(column: str = "outage") -> str:
    """site_of_outage 的 SQL 版本，供 GROUP BY / DISTINCT / 等值比较使用。"""
    return (f"CASE WHEN UPPER(SUBSTR({column},2,1)) GLOB '[A-Z]' "
            f"THEN SUBSTR({column},1,2) ELSE SUBSTR({column},1,1) END")


def sequence(outage):
    match = re.fullmatch(r"([A-Z]+)(\d)(\d{2,})", str(outage).upper())
    if not match:
        raise ValueError("大修编号格式无效")
    return match.group(1), int(match.group(2)), int(match.group(3))


def no_defect_basis(row, *, auto_ndd=True):
    code = str(_row_value(row, "indication") or "").strip().upper()
    if code in {"NDD", "NONE", "NO DEFECT"}:
        return "原始结论为 NDD 类代码"
    if auto_ndd and code in {"", "/"} and not has_wear_information(row):
        return "空白或 / 结论；幅值、相位、磨损深度、测量通道、磨损位置均为空或 /，按 NDD 统计"
    return ""


def category(row, *, auto_ndd=True):
    code = str(row.get("indication") or "").strip().upper()
    if no_defect_basis(row, auto_ndd=auto_ndd):
        return "NDD"
    if code:
        return "defect"
    return "incomplete"


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def parse_location(raw):
    text = unicodedata.normalize("NFKC", str(raw or "")).strip().translate(
        str.maketrans({"−": "-", "–": "-", "—": "-"}))
    match = re.fullmatch(r"P(?:oint)?\s*([1-6])\s*(?:([+-])\s*([+-]?\d+(?:\.\d+)?))?\s*(?:mm|毫米)?", text, re.I)
    if not match:
        return None
    offset = float(match.group(3)) * (-1 if match.group(2) == "-" else 1) if match.group(3) else 0.0
    return (f"P{match.group(1)}", offset) if math.isfinite(offset) else None


def location(row):
    return parse_location(row.get("location_raw", row.get("location")))


def report_location(raw):
    parsed = parse_location(raw)
    if parsed is None:
        return raw
    point, distance = parsed
    explicit = re.search(r"[+-]", unicodedata.normalize("NFKC", str(raw)).translate(
        str.maketrans({"−": "-", "–": "-", "—": "-"})))
    return f"{point}{distance:+g}mm" if distance or explicit else point


def report_order(rows):
    def key(row):
        parsed = location(row)
        return (int(row["thimble_id"]), int(parsed[0][1:]) if parsed else 7,
                parsed[1] if parsed else 0)
    return sorted(rows, key=key)


def detection_summary(rows, outage):
    """Count source records separately from mutually exclusive tube groups."""
    tubes, counts = defaultdict(list), Counter()
    for row in rows:
        code = str(row.get("indication") or "").strip().upper()
        kind = "ndd" if category(row) == "NDD" else "war" if code == "WAR" else "other"
        counts[kind] += 1
        tubes[row["thimble_id"]].append(kind)
    groups = {"war": [], "ndd": [], "other": []}
    mixed = []
    for tube, kinds in sorted(tubes.items()):
        kind = "war" if "war" in kinds else "other" if "other" in kinds else "ndd"
        groups[kind].append(tube)
        if "ndd" in kinds and kind != "ndd":
            mixed.append(tube)
    return {"outage": outage, "records": len(rows), "tubes": len(tubes),
            **{f"{kind}_records": counts[kind] for kind in groups},
            **{f"{kind}_tubes": len(ids) for kind, ids in groups.items()},
            "tube_ids": groups, "mixed_ndd_tubes": mixed,
            "missing_tubes": sorted(set(range(1, 51)) - set(tubes))}


def position_resolution(row):
    """Map the confirmed Point/P aliases without modifying source evidence."""
    raw = str(row.get("location_raw", row.get("location")) or "").strip()
    text = unicodedata.normalize("NFKC", raw).strip()
    parsed = location(row)
    if parsed:
        alias = bool(re.match(r"Point", text, re.I))
        return {"position_bucket": parsed[0], "position_status": "parsed",
                "position_note": f"按 {parsed[0]} 统计；原始标识保留" if alias else ""}
    missing = text.upper() in {"", "/", "-", "—", "NA", "N/A", "NULL"}
    return {"position_bucket": "未解析", "position_status": "missing" if missing else "source_label",
            "position_note": "未提供原始位置标识；检测结论和有效深度照常统计"
            if missing else "保留原始标识，未换算为 P 位；检测结论和有效深度照常统计"}


def duplicate_signature(row):
    fields = ("outage", "unit_id", "thimble_id", "analyst", "location", "channel",
              "volts", "degrees", "percent", "indication", "measurement_type",
              "analysis", "probe", "channel_id", "distance", "extent", "length", "width")
    return tuple(str(row.get(key) if row.get(key) is not None else "").strip().casefold() for key in fields)


def cross_group_duplicates(rows):
    """Find identical reported defects across groups without discarding evidence."""
    groups = defaultdict(list)
    for row in rows:
        if category(row) != "defect" or not str(row.get("analyst") or "").strip() or not str(row.get("calgroup") or "").strip():
            continue
        signature = duplicate_signature(row)
        groups[signature].append(row)
    return [group for group in groups.values()
            if len({str(row["calgroup"]).strip().casefold() for row in group}) > 1]


def rows_for(service, site="", unit=0, outage=""):
    where, args = ["is_deleted=0"], []
    if site:
        where.append(site_prefix_sql() + "=?")
        args.append(site.upper())
    if unit:
        where.append("unit_id=?")
        args.append(int(unit))
    if outage:
        where.append("outage=?")
        args.append(outage.upper())
    with service.connect() as db:
        rows = [dict(r) for r in db.execute("SELECT * FROM statistical_findings WHERE " + " AND ".join(where) + " ORDER BY outage,thimble_id,entry_no,datapoint,id", args)]
    return [r for r in rows if 1 <= int(r.get("thimble_id") or 0) <= 50 and not str(r.get("filename") or "").upper().startswith(("DIR999", "DIR000"))]


def repairs_for(service, site="", unit=0):
    with service.connect() as db:
        rows = [dict(r) for r in db.execute("SELECT * FROM tube_states WHERE is_deleted=0 ORDER BY outage,thimble_id")]
    for row in rows:
        if not row.get("offset_confirmed", 1):
            row["offset_mm"] = None
    return [r for r in rows if (not site or site_of_outage(r["outage"]) == site.upper()) and (not unit or r["unit_id"] == int(unit))]


def compare(service, old, new, unit, rules=None):
    old, new, unit = str(old).upper(), str(new).upper(), int(unit)
    if not old:
        raise ValueError("请选择历史大修")
    old_key, new_key = sequence(old), sequence(new)
    if old_key[:2] != new_key[:2] or new_key[1] != unit:
        raise ValueError("仅允许对比相同基地、相同机组的不同大修")
    if old_key[2] >= new_key[2]:
        raise ValueError("历史大修必须早于本次大修")
    before, current = rows_for(service, old_key[0], unit, old), rows_for(service, new_key[0], unit, new)
    if not before and not current:
        raise ValueError("所选大修缺少检测数据，不能生成对比")
    repairs = repairs_for(service, old_key[0], unit)
    result = compare_rows(old, new, unit, before, current, repairs, rules=rules)
    return complete_comparison(service, result, before, current)


def tube_coverage(outage, rows):
    present = {r["thimble_id"] for r in rows if r.get("thimble_id") in range(1, 51)}
    missing = sorted(set(range(1, 51)) - present)
    return {"outage": outage, "expected": 50, "present": len(present),
            "missing": missing, "complete": not missing}


def unmatched_history_detail(previous, current_rows, new, new_kind, tolerance, shift=0):
    defects = [row for row in current_rows if category(row) == "defect"]
    detail = {"state": new_kind, "records": len(current_rows), "defects": len(defects), "nearest": None}
    if new_kind == "missing":
        return f"本次 {new} 该管没有检测记录，无法建立对应关系", detail
    if new_kind == "NDD":
        return f"本次 {new} 该管全部为 NDD 或无显示记录，未出现对应显示", detail
    if not defects:
        return f"本次 {new} 该管有检测记录，但没有可匹配的缺陷显示", detail
    target = location(previous)
    if target is None:
        return "历史记录缺少可解析的磨损位置，无法按轴向位置自动匹配", detail
    if shift is None:
        return "维护导致历史与本次的位置关系未确定，无法计算换算后的距离", detail
    target = (target[0], target[1] + shift)
    transformed = f"{target[0]}{target[1]:+g}" if target[1] else target[0]
    shift_note = f"（历史位置加有符号移位量 {shift:+g} mm 后为 {transformed}）" if shift else ""
    same = sorted(((abs(pos[1] - target[1]), row, pos) for row in defects
                   if (pos := location(row)) is not None and pos[0] == target[0]), key=lambda item: item[0])
    if same:
        distance, row, pos = same[0]
        detail["nearest"] = {"location": row.get("location") or pos[0], "datapoint": row.get("datapoint"),
                             "distance_mm": round(distance, 3), "zone": pos[0]}
        if distance > tolerance:
            return (f"本次同 {target[0]} 位最近显示在 {row.get('location') or pos[0]}，{shift_note}"
                    f"轴向相距约 {distance:g} mm，超出当前规则 ±{tolerance:g} mm 容差"), detail
        return "本次同位置存在显示，但未形成一对一的唯一匹配，需人工确认", detail
    others = [pos for row in defects if (pos := location(row)) is not None]
    if others:
        detail["other_zones"] = sorted({pos[0] for pos in others})
        return f"历史 {target[0]} 位本次没有同 P 位显示；其他 P 位不能仅凭轴向距离对应", detail
    return "本次该管显示缺少可解析的位置，无法自动匹配", detail


def complete_comparison(service, result, before, current):
    """Keep the 50-tube roster separate from the number of indication rows.

    Missing records are presentation-only placeholders, never database findings
    or NDD evidence. Historical indications without a match remain visible.
    """
    coverage = [tube_coverage(result["old"], before), tube_coverage(result["new"], current)]
    warnings = result["warnings"]
    tolerance = rule_tolerance(result.get("rules"))
    for scope in coverage:
        for tube in scope["missing"]:
            warnings.append({"thimble_id": tube, "outage": scope["outage"],
                             "code": "missing_tube", "reason": f"{scope['outage']} 缺少该管检测记录，不得视为 NDD；请核查原始报告、导入记录和回收站"})
    items = []
    for tube in range(1, 51):
        old_rows = [r for r in before if r["thimble_id"] == tube]
        new_rows = [r for r in current if r["thimble_id"] == tube]
        old_kind = "missing" if not old_rows else "NDD" if all(category(r) == "NDD" for r in old_rows) else "recorded"
        new_kind = "missing" if not new_rows else "NDD" if all(category(r) == "NDD" for r in new_rows) else "recorded"
        position = service.position_for(result["unit"], tube)
        tube_items = [{**r, "row_kind": "indication", "current_kind": new_kind,
                       "old_kind": old_kind, "position": r.get("position") or position}
                      for r in result["items"] if r["thimble_id"] == tube]
        used = {r["old_id"] for r in tube_items if r.get("old_id") is not None}
        covered = {r["official_covered_old_id"]: r for r in tube_items
                   if r.get("official_covered_old_id") is not None}
        replaced = tube in result.get("replaced_tubes", [])
        for previous in old_rows:
            if category(previous) == "NDD" or previous.get("id") in used:
                continue
            if previous.get("id") in covered:
                evidence = covered[previous["id"]]
                tube_items.append({
                    "id": None, "outage": result["new"], "unit_id": result["unit"],
                    "thimble_id": tube, "position": position, "indication": "",
                    "volts": None, "percent": None, "location": evidence["official_covered_position"],
                    "old_id": previous["id"], "old_volts": previous.get("volts"),
                    "old_percent": previous.get("percent"), "old_location": previous.get("location", ""),
                    "old_datapoint": previous.get("datapoint"), "old_report_path": previous.get("report_path", ""),
                    "comparison": "R1", "comparison_note": evidence["comparison_note"],
                    "official_evidence": evidence["official_evidence"], "row_kind": "official_covered",
                    "current_kind": new_kind, "old_kind": old_kind,
                })
                continue
            reason = ("该历史显示属于换管前的旧管，仅保留追溯，不与新管配对" if replaced else
                      "历史显示本次未匹配，需人工复核；不得自动判定为消失或 NDD")
            history_item = {"id": None, "outage": result["new"], "unit_id": result["unit"],
                            "thimble_id": tube, "position": position, "indication": "",
                            "volts": None, "percent": None, "location": "", "datapoint": None,
                            "old_id": previous.get("id"), "old_volts": previous.get("volts"),
                            "old_percent": previous.get("percent"), "old_location": previous.get("location", ""),
                            "old_datapoint": previous.get("datapoint"), "old_report_path": previous.get("report_path", ""),
                            "shift_mm": None, "delta_percent": None, "comparison": "旧管历史" if replaced else "待确认",
                            "comparison_note": reason, "row_kind": "historical_replaced" if replaced else "historical_only",
                            "current_kind": new_kind, "old_kind": old_kind}
            tube_items.append(history_item)
            if replaced:
                continue
            indication_items = [item for item in tube_items if item["row_kind"] == "indication"]
            shifts = {item.get("shift_mm") for item in indication_items}
            shift = next(iter(shifts)) if len(shifts) == 1 else None
            if any("换管" in item.get("comparison_note", "") for item in indication_items):
                shift = None
            detail_reason, detail = unmatched_history_detail(
                previous, new_rows, result["new"], new_kind, tolerance, shift)
            warnings.append({"thimble_id": tube, "outage": result["new"], "code": "unmatched_history",
                             "reason": detail_reason, "old_id": previous.get("id"),
                             "historical": {"outage": previous.get("outage") or result["old"],
                                            "location": previous.get("location") or previous.get("location_raw") or "",
                                            "volts": previous.get("volts"), "percent": previous.get("percent"),
                                            "datapoint": previous.get("datapoint")},
                             "current": detail, "tolerance_mm": tolerance})
        if not tube_items:
            missing = old_kind == "missing" or new_kind == "missing"
            confirmed_ndd = old_kind == new_kind == "NDD"
            reason = "；".join(f"{code} 缺少该管检测记录" for code, kind in
                              ((result["old"], old_kind), (result["new"], new_kind)) if kind == "missing")
            if not missing and not confirmed_ndd:
                reason = "存在未形成确定匹配的非 NDD 或不完整记录，需人工复核"
            source = new_rows[0] if new_rows else {}
            tube_items.append({**source, "id": source.get("id"), "outage": result["new"],
                               "unit_id": result["unit"], "thimble_id": tube, "position": position,
                               "indication": "" if missing else "NDD", "volts": None, "percent": None,
                               "location": "", "datapoint": None, "old_volts": None, "old_percent": None,
                               "old_location": "", "old_datapoint": None, "old_id": None,
                               "shift_mm": None, "delta_percent": None, "comparison": "NDD" if confirmed_ndd else "待确认",
                               "comparison_note": reason or "双方均有明确 NDD 检测记录，无可记录显示",
                               "row_kind": "missing" if missing else "ndd" if confirmed_ndd else "no_match",
                               "current_kind": new_kind, "old_kind": old_kind})
            if not missing and not confirmed_ndd:
                warnings.append({"thimble_id": tube, "code": "incomplete_tube_result",
                                 "reason": "存在非 NDD 或不完整结论，但没有确定缺陷匹配，不能判为 NDD"})
        for item in tube_items:
            for kind, source_rows, key in ((new_kind, new_rows, "ndd_current_location"),
                                           (old_kind, old_rows, "ndd_old_location")):
                if kind == "NDD":
                    item[key] = "、".join(dict.fromkeys(str(row.get("location") or "").strip()
                                                     for row in source_rows
                                                     if str(row.get("location") or "").strip() not in ("", "/")))
        items.extend(tube_items)
    result.update(items=items, coverage=coverage, expected_tubes=50, displayed_tubes=50,
                  coverage_complete=all(c["complete"] for c in coverage),
                  missing_tubes={c["outage"]: c["missing"] for c in coverage},
                  pending_tubes=sorted({r["thimble_id"] for r in items if r["comparison"] == "待确认"}))
    result["summary"] = {key: sum(r["comparison"] == key and r["row_kind"] in {"indication", "ndd"} for r in items)
                         for key in ("R", "NI", "待确认", "NDD")}
    result["summary"]["historical_unmatched"] = sum(r["row_kind"] == "historical_only" for r in items)
    result["summary"]["R1"] = sum(r["row_kind"] == "official_covered" for r in items)
    result["summary"]["R*"] = sum(r.get("comparison_display") == "R*" for r in items)
    result["summary"]["missing_tubes"] = len({tube for c in coverage for tube in c["missing"]})
    return result


def comparison_values(rows):
    """The formal table has exactly ten columns; evidence stays outside it."""
    values = []
    number, last_tube = 0, None
    for row in report_order(rows):
        if row.get("row_kind") not in {"indication", "official_covered"}:
            continue
        if row["thimble_id"] != last_tube:
            number += 1
            last_tube = row["thimble_id"]
        current_location = "缺少检测记录" if row.get("current_kind") == "missing" else (row.get("ndd_current_location") or "/") if row.get("current_kind") == "NDD" else row.get("location")
        old_location = "缺少检测记录" if row.get("old_kind") == "missing" else "/" if row.get("old_kind") == "NDD" else row.get("old_location")
        values.append([number, row["thimble_id"], row.get("position"), row.get("volts"), row.get("percent"),
                       report_location(current_location), row.get("old_volts"), row.get("old_percent"),
                       report_location(old_location), row.get("comparison_display") or row["comparison"]])
    return values


def apply_official_comparisons(old, new, unit, before, items, warnings):
    """Use verified report adjudications only for an exact, unique source pair."""
    for evidence in official_comparison_evidence.VERIFIED:
        if (evidence["old"], evidence["new"], evidence["unit"]) != (old, new, unit):
            continue
        tube = evidence["tube"]

        def agrees(row, expected):
            pos, volts, percent = expected
            return (location(row) == location({"location": pos})
                    and row.get("volts") == volts and row.get("percent") == percent
                    and category(row) == "defect")

        old_rows = [row for row in before if row["thimble_id"] == tube and agrees(row, evidence["historical"])]
        new_rows = [row for row in items if row["thimble_id"] == tube and agrees(row, evidence["current"])]
        if len(old_rows) != 1 or len(new_rows) != 1:
            continue
        previous, item = old_rows[0], new_rows[0]
        lifecycle = item["maintenance_state"]
        if lifecycle["needs_review"] or lifecycle["plugged"]:
            continue
        if (sum(row["thimble_id"] == tube and category(row) == "defect"
                and location(row) == location(previous) for row in before) != 1
                or sum(row["thimble_id"] == tube and category(row) == "defect"
                       and location(row) == location(item) for row in items) != 1):
            continue
        if evidence.get("covered_position") and any(
                row["thimble_id"] == tube and category(row) == "defect"
                and location(row) == location({"location": evidence["covered_position"]})
                for row in items):
            continue
        pending = (item["comparison"] == "待确认" and item["comparison_note"].startswith((
            "同一 P 位存在超出当前容差", "维护移位换算与完整原位历史对应冲突")))
        corrected_ni = evidence.get("permit_ni") and item["comparison"] == "NI"
        if (not (pending or corrected_ni) or item.get("shift_mm") != evidence["shift"]
                or previous.get("id") is None
                or any(row.get("old_id") == previous["id"] for row in items)):
            continue
        if evidence["comparison"] == "R":
            item.update(comparison="R", old_id=previous["id"],
                        old_volts=previous.get("volts"), old_percent=previous.get("percent"),
                        old_location=previous.get("location", ""), old_datapoint=previous.get("datapoint"),
                        old_report_path=previous.get("report_path", ""),
                        delta_percent=(item["percent"] - previous["percent"]
                                       if numeric(item.get("percent")) and numeric(previous.get("percent")) else None))
            if evidence.get("historical_report_location"):
                item["old_source_location"] = previous.get("location", "")
                item["old_location"] = evidence["historical_report_location"]
        else:
            item["comparison"] = "NI"
            if evidence.get("covered_position"):
                item["official_covered_old_id"] = previous["id"]
                item["official_covered_position"] = evidence["covered_position"]
        old_note = item["comparison_note"].split("；沿用 ", 1)[0]
        item["comparison_note"] = "已按官方报告逐条核对：" + evidence["source"]
        item["official_evidence"] = evidence["source"]
        if evidence.get("display"):
            item["comparison_display"] = evidence["display"]
        warnings[:] = [warning for warning in warnings
                       if not (warning["thimble_id"] == tube
                               and warning.get("current_location") == item.get("location"))]
        if not any(row["thimble_id"] == tube and row["comparison"] == "待确认"
                   and row["comparison_note"].startswith(old_note) for row in items):
            warnings[:] = [warning for warning in warnings
                           if not (warning["thimble_id"] == tube and warning["reason"] == old_note)]


def compare_rows(old, new, unit, before, current, repairs, rules=None):
    """Shared matching for reports and tube evolution; repairs follow inspection."""
    old_key, new_key = sequence(old), sequence(new)
    tolerance = rule_tolerance(rules)
    items, warnings = [], []
    before_by_tube = defaultdict(list)
    repairs_by_tube = defaultdict(list)
    for row in before:
        before_by_tube[row["thimble_id"]].append(row)
    for repair in repairs:
        if int(repair.get("unit_id", unit)) == unit and sequence(repair["outage"])[:2] == new_key[:2]:
            repairs_by_tube[repair["thimble_id"]].append(repair)
    lifecycle_cache = {}
    for row in current:
        if category(row) == "NDD":
            continue
        tube = row["thimble_id"]
        # A repair recorded at Cn follows that inspection and affects C(n+1).
        events = [s for s in repairs_by_tube.get(tube, ())
                  if old_key[2] <= sequence(s["outage"])[2] < new_key[2]]
        shifts = [s for s in events if "shifted" in tube_lifecycle.events(s)]
        replaced = any("replaced" in tube_lifecycle.events(s) for s in events)
        if tube not in lifecycle_cache:
            lifecycle_cache[tube] = tube_lifecycle.effective(repairs, new, unit, tube, inclusive=False)
        lifecycle = lifecycle_cache[tube]
        reason = ""
        if lifecycle["needs_review"]:
            uncertain_shift = any(s.get("offset_confirmed", 1) == 0 or not numeric(s.get("offset_mm"))
                                  for s in shifts)
            reason = ("已确认移位状态，但移位距离或方向未明确，不能自动换算位置"
                      if uncertain_shift else
                      "维护状态需人工核查：" + "；".join(lifecycle["warnings"]))
        elif lifecycle["plugged"]:
            reason = f"该管自 {lifecycle['plug_since']} 起持续堵管；虽保留检测记录，本次对比须人工核查"
        elif category(row) == "incomplete":
            reason = "原始三字符/检测结论缺失，待人工确认"
        elif not replaced and shifts and new_key[2] != old_key[2] + 1:
            reason = "移位管仅允许与处理后的下一次相邻大修比较"
        elif not replaced and any(s.get("offset_confirmed", 1) == 0 or not numeric(s.get("offset_mm")) for s in shifts):
            reason = "已确认移位状态，但移位距离或方向未明确，不能自动换算位置"
        elif location(row) is None:
            reason = "磨损位置无法解析，不以数据点猜测物理坐标"
        old_tube = before_by_tube.get(tube, ())
        candidates = [r for r in old_tube if category(r) == "defect"]
        shift = 0 if replaced else None if any(s.get("offset_confirmed", 1) == 0 or not numeric(s.get("offset_mm")) for s in shifts) else sum(float(s["offset_mm"]) for s in shifts)
        target = location(row)
        matches = [r for r in candidates if shift is not None and location(r) is not None and target is not None and location(r)[0] == target[0] and abs(location(r)[1] + shift - target[1]) <= tolerance]
        opposite_matches = [r for r in candidates if shifts and shift is not None
                            and location(r) is not None and target is not None
                            and location(r)[0] == target[0]
                            and abs(location(r)[1] - shift - target[1]) <= tolerance]
        previous = matches[0] if len(matches) == 1 and not replaced else None
        if not reason and len(matches) > 1 and not replaced:
            reason = "历史同位置存在多条候选，需人工确认，未任意覆盖"
        if not reason and not replaced and not matches and opposite_matches:
            reason = "移位反方向存在历史候选，与当前有符号移位方向冲突，需核对原始报告和方向"
        if not reason and not replaced and not old_tube:
            reason = "历史大修无该管检测记录，不能直接判 NI"
        if not reason and not replaced and not previous and any(category(r) == "incomplete" or (category(r) == "defect" and location(r) is None) for r in old_tube):
            reason = "历史结论或磨损位置不完整，不能直接判 NI"
        if not reason and not replaced and not previous and target is not None and any(
                location(r) is not None and location(r)[0] == target[0] for r in candidates):
            reason = "同一 P 位存在超出当前容差的历史显示，不能仅凭容差判定为新显示，需人工复核"
        if not reason and previous and str(previous.get("indication") or "").strip().upper() != str(row.get("indication") or "").strip().upper():
            reason = "同位置显示类型不同，需人工复核"
        result = "待确认" if reason else "R" if previous else "NI"
        if reason:
            previous = None
        item = {**row, "comparison": result, "old_volts": previous.get("volts") if previous else None,
                "old_percent": previous.get("percent") if previous else None, "old_location": previous.get("location", "") if previous else "",
                "old_datapoint": previous.get("datapoint") if previous else None, "old_id": previous.get("id") if previous else None,
                "old_report_path": previous.get("report_path", "") if previous else "", "shift_mm": shift,
                "delta_percent": row["percent"] - previous["percent"] if previous and numeric(row.get("percent")) and numeric(previous.get("percent")) and not reason else None,
                "maintenance_state": lifecycle,
                "_candidate_previous": [id(candidate) for candidate in matches] if not replaced else [],
                "comparison_note": (reason or ("换管后首次检查，建立新基准" if replaced else f"历史原位置加上有符号移位量 {shift:+g} mm 后比较" if shifts else "同管、同 P 位、同轴向位置和显示类型比较")) + (
                    f"；沿用 {lifecycle['plug_since']} 堵管状态，检测记录保留，需复核检查范围" if lifecycle["plugged"] else "")}
        items.append(item)
        if reason:
            warnings.append({"thimble_id": tube, "reason": reason,
                             "current_location": row.get("location") or "",
                             "historical_locations": [r.get("location") or "" for r in candidates
                                                      if location(r) is not None and target is not None
                                                      and location(r)[0] == target[0]],
                             "shift_mm": shift})
    match_counts = Counter(key for item in items for key in item["_candidate_previous"])
    for item in items:
        candidate_ids = item.pop("_candidate_previous")
        if any(match_counts[key] > 1 for key in candidate_ids):
            reason = "多条本次显示对应同一条历史显示，无法确定一对一匹配，需人工复核"
            item.update(comparison="待确认", comparison_note=reason, old_id=None,
                        old_volts=None, old_percent=None, old_location="", old_datapoint=None,
                        old_report_path="", delta_percent=None)
            warnings.append({"thimble_id": item["thimble_id"], "reason": reason})
    # A complete unchanged pattern can contradict the recorded displacement.
    groups = defaultdict(list)
    for item in items:
        pos = location(item)
        if item.get("shift_mm") and pos is not None:
            groups[(item["thimble_id"], pos[0])].append(item)
    for (tube, station), group in groups.items():
        historical = [row for row in before_by_tube.get(tube, ())
                      if category(row) == "defect" and location(row) is not None
                      and location(row)[0] == station]
        if len(group) < 2 or len(group) != len(historical):
            continue
        original = []
        for item in group:
            pos = location(item)
            original.append([row for row in historical
                             if abs(location(row)[1] - pos[1]) <= tolerance
                             and str(row.get("indication") or "").strip().upper()
                             == str(item.get("indication") or "").strip().upper()])
        if (not all(len(candidates) == 1 for candidates in original)
                or len({id(candidates[0]) for candidates in original}) != len(group)):
            continue
        if not any(item["comparison"] == "R" and item.get("old_id") is not None
                   and item["old_id"] != candidates[0].get("id")
                   for item, candidates in zip(group, original)):
            continue
        reason = "维护移位换算与完整原位历史对应冲突，需核对原始报告及维护生效时间"
        for item in group:
            item.update(comparison="待确认", comparison_note=reason, old_id=None,
                        old_volts=None, old_percent=None, old_location="", old_datapoint=None,
                        old_report_path="", delta_percent=None)
        warnings.append({"thimble_id": tube, "reason": reason})
    # An original-position indication is new only after every old indication
    # at that station has been uniquely matched at its displaced position.
    for item in items:
        note = item["comparison_note"].split("；沿用 ", 1)[0]
        if (note not in {
                "同一 P 位存在超出当前容差的历史显示，不能仅凭容差判定为新显示，需人工复核",
                "移位反方向存在历史候选，与当前有符号移位方向冲突，需核对原始报告和方向"}
                or not item.get("shift_mm")):
            continue
        target = location(item)
        historical = [row for row in before_by_tube.get(item["thimble_id"], ())
                      if category(row) == "defect" and location(row) is not None
                      and location(row)[0] == target[0]]
        claimed = {row["old_id"] for row in items if row["thimble_id"] == item["thimble_id"]
                   and row["comparison"] == "R" and row.get("old_id") is not None}
        if historical and all(row.get("id") is not None and row["id"] in claimed for row in historical):
            item.update(comparison="NI",
                        comparison_note="该 P 位历史显示已按移位量唯一对应其他本次显示；本次该位置为新显示")
            for index, warning in enumerate(warnings):
                if warning["thimble_id"] == item["thimble_id"] and warning["reason"] == note:
                    warnings.pop(index)
                    break
    apply_official_comparisons(old, new, unit, before, items, warnings)
    return {"old": old, "new": new, "unit": unit, "items": items, "warnings": warnings,
            "replaced_tubes": sorted({s["thimble_id"] for s in repairs
                                      if int(s.get("unit_id", unit)) == unit
                                      and sequence(s["outage"])[:2] == new_key[:2]
                                      and old_key[2] <= sequence(s["outage"])[2] < new_key[2]
                                      and "replaced" in tube_lifecycle.events(s)}),
            "summary": {k: sum(r["comparison"] == k for r in items) for k in ("R", "NI", "待确认")},
            "rules": {"version": (rules or DEFAULT_RULES).get("version", 0),
                      "name": (rules or DEFAULT_RULES).get("name", ""),
                      "match_tolerance_mm": tolerance},
            "rule_note": RULE_NOTE}


def analysis(service, scope, rules=None):
    site, unit, outage = str(scope.get("site") or "").upper(), int(scope.get("unit") or 0), str(scope.get("outage") or "").upper()
    history = rows_for(service, site, unit)
    rows = [r for r in history if not outage or r["outage"] == outage]
    events = repairs_for(service, site, unit)
    groups = defaultdict(list)
    for row in history:
        groups[row["outage"]].append(row)
    trends = []
    for code, values in groups.items():
        peaks = {}
        for row in values:
            pos = location(row)
            if category(row) == "defect" and pos and numeric(row.get("percent")):
                key = (row["thimble_id"], pos[0])
                peaks[key] = max(peaks.get(key, float("-inf")), row["percent"])
        by_p = {p: sum(v for (_, zone), v in peaks.items() if zone == p) for p in ("P1", "P2", "P3", "P4", "P5", "P6")}
        trends.append({"outage": code, "site": site_of_outage(code), "unit": values[0]["unit_id"], "seq": sequence(code)[2], "total": sum(peaks.values()), "by_p": by_p, "tubes": len({r["thimble_id"] for r in values}), "records": len(values), "max_percent": max((r["percent"] for r in values if category(r) == "defect" and numeric(r.get("percent"))), default=None)})
    trends.sort(key=lambda t: (t["site"], t["unit"], t["seq"]))
    defects = [r for r in rows if category(r) == "defect"]
    tube_key = lambda r: (site_of_outage(r["outage"]), r["unit_id"], r["thimble_id"])
    latest = {}
    for row in rows:
        key = (site_of_outage(row["outage"]), row["unit_id"])
        if key not in latest or sequence(row["outage"])[2] > sequence(latest[key])[2]: latest[key] = row["outage"]
    current_rows = [r for r in rows if r["outage"] == latest[(site_of_outage(r["outage"]), r["unit_id"])]]
    current_defects = [r for r in current_rows if category(r) == "defect"]
    summary = {"records": len(rows), "tubes": len({tube_key(r) for r in current_rows}), "defects": len(defects),
               "defect_tubes": len({tube_key(r) for r in defects}), "ndd_tubes": len({tube_key(r) for r in rows if category(r) == "NDD"} - {tube_key(r) for r in defects}),
               "incomplete": sum(category(r) == "incomplete" for r in rows), "max_percent": max((r["percent"] for r in defects if numeric(r.get("percent"))), default=None),
               "current_defect_tubes": len({tube_key(r) for r in current_defects}), "current_ndd_tubes": len({tube_key(r) for r in current_rows if category(r) == "NDD"} - {tube_key(r) for r in current_rows if category(r) != "NDD"}),
               "expected_tubes": 50 * len(latest), "missing_tubes": 50 * len(latest) - len({tube_key(r) for r in current_rows}),
               "units": len({(site_of_outage(r["outage"]), r["unit_id"]) for r in rows}), "outages": len({r["outage"] for r in rows})}
    plate = []
    if site and unit and outage:
        for tube in range(1, 51):
            values = [r for r in rows if r["thimble_id"] == tube]
            repairs = [s for s in events if s["thimble_id"] == tube and sequence(s["outage"])[2] <= sequence(outage)[2]]
            maintained = repairs[-1] if repairs else None
            lifecycle = tube_lifecycle.effective(repairs, outage, unit, tube)
            numbers = [r["percent"] for r in values if category(r) == "defect" and numeric(r.get("percent"))]
            plate.append({"tube": tube, "position": service.position_for(unit, tube), "records": len(values),
                          "defects": sum(category(r) == "defect" for r in values), "max_percent": max(numbers, default=None),
                          "ndd": bool(values) and all(category(r) == "NDD" for r in values), "state": lifecycle["state"],
                          "lifecycle": lifecycle, "state_label": lifecycle["state_label"],
                          "replacements": lifecycle["generation"] - 1, "offset_mm": lifecycle["cumulative_offset_mm"] if maintained else None,
                          "mapping_warning": any(r.get("position") and r["position"] != service.position_for(unit, tube) for r in values)})
    public_rows = [{**r, "category": category(r)} for r in rows]
    distributions = [{"zone": p, "count": sum(category(r) == "defect" and location(r) is not None and location(r)[0] == p for r in rows)} for p in ("P1", "P2", "P3", "P4", "P5", "P6")]
    increments = []
    if site and unit:
        ordered = sorted(groups, key=lambda code: sequence(code)[2])
        for previous, code in zip(ordered, ordered[1:]):
            if outage and code != outage: continue
            result = compare(service, previous, code, unit, rules=rules)
            matched = [r for r in result["items"] if r["comparison"] == "R" and r["delta_percent"] is not None]
            increments.append({"old": previous, "new": code, "matched": len(matched), "sum_delta": sum(r["delta_percent"] for r in matched) if matched else None, "positive": sum(r["delta_percent"] > 0 for r in matched), "negative": sum(r["delta_percent"] < 0 for r in matched), **result["summary"]})
    return {"scope": {"site": site, "unit": unit, "outage": outage}, "summary": summary, "trends": trends, "plate": plate, "distribution": distributions, "increments": increments,
            "records": public_rows, "states": events,
            "rules": {"version": (rules or DEFAULT_RULES).get("version", 0),
                      "name": (rules or DEFAULT_RULES).get("name", ""),
                      "match_tolerance_mm": rule_tolerance(rules)},
            "rule_note": RULE_NOTE,
            "source": "本机 SQLite 正式检测记录（排除回收站、标定文件与越界管号）", "generated_at": datetime.now().isoformat(timespec="seconds")}


def report_snapshot(service, payload, rules=None):
    kind = payload.get("kind", "inspection")
    if kind not in {"inspection", "comparison"}:
        raise ValueError("报告中心仅支持检验报告单和检验结果比对表")
    site, unit, outage = str(payload.get("site") or "").upper(), int(payload.get("unit") or 0), str(payload.get("outage") or "").upper()
    if not site or not unit or not outage or sequence(outage)[:2] != (site, unit):
        raise ValueError("请选择一致的基地、机组和大修")
    rows = rows_for(service, site, unit, outage)
    selected = payload.get("finding_ids") or []
    if kind == "comparison" and selected:
        raise ValueError("历次大修对比必须覆盖全部50根管，不支持仅导出勾选记录")
    if selected:
        ids = {int(i) for i in selected}
        if not ids.issubset({r["id"] for r in rows}):
            raise ValueError("勾选记录与报告范围不一致，请重新选择")
        rows = [r for r in rows if r["id"] in ids]
    if not rows and kind != "comparison":
        raise ValueError("当前范围没有可导出的检测记录")
    detection_counts = [detection_summary(rows, outage)]
    metadata = {str(k): str(v or "") for k, v in (payload.get("metadata") or {}).items()}
    summary, warnings = {}, []
    # Fill only unambiguous source metadata; never reuse the template's old equipment IDs.
    for label, column in [('电厂名称', 'site_owner'), ('涡流仪型号', 'tester'), ('探头型号', 'probe')]:
        available = sorted({str(r.get(column) or '').strip() for r in rows} - {''})
        if not metadata.get(label) and len(available) == 1:
            metadata[label] = available[0]
    if kind == "comparison":
        result = compare(service, payload.get("old", ""), outage, unit, rules=rules)
        detection_counts.append(detection_summary(rows_for(service, site, unit, result["old"]), result["old"]))
        rows, summary, warnings = result["items"], result["summary"], result["warnings"]
        title = f"{outage} 与 {result['old']} 指套管检验结果对比表"
        headers = ["序号", "通道编号", "堆芯位置", "本次幅值(V)", "本次磨损深度(壁厚%)", "本次磨损位置(mm)", "历史幅值(V)", "历史磨损深度(壁厚%)", "历史磨损位置(mm)", "备注"]
        values = comparison_values(rows)
    elif kind == "inspection":
        title = f"{outage} 指套管涡流检验汇总报告"
        headers = ["序号", "通道编号", "堆芯位置", "显示类型", "幅值(V)", "壁厚(%)", "磨损位置", "测量通道", "分析人员"]
        values = []
        for number, r in enumerate(report_order(rows), 1):
            values.append([number, r["thimble_id"], r.get("position"), r.get("indication"),
                           r.get("volts"), r.get("percent"), report_location(r.get("location")),
                           r.get("channel"), r.get("analyst")])
        warnings = [{"thimble_id": r["thimble_id"], "reason": "原始结论缺失，报告留空待确认"} for r in rows if category(r) == "incomplete"]
    elif kind == "data":
        title = f"{outage} 标准检测数据与来源追溯"
        keys = ["outage", "unit_id", "thimble_id", "position", "indication", "volts", "degrees", "percent", "location", "channel", "datapoint", "analyst", "analysis", "calgroup", "filename", "report_path", "source_indication", "indication_resolution"]
        headers = ["大修", "机组", "通道编号", "堆芯位置", "三字符", "幅值(V)", "相位(°)", "壁厚(%)", "磨损位置", "测量通道", "数据点", "分析人员", "分析阶段", "数据组", "数据文件", "来源报告", "原始三字符", "确认方式"]
        values = [[r.get(k) for k in keys] for r in rows]
    elif kind == "validation":
        title = f"{outage} 数据质量核查清单"
        headers = ["通道编号", "记录ID", "核查类型", "说明", "来源报告", "数据文件"]
        values = []
        for r in rows:
            issues = []
            if category(r) == "incomplete": issues.append(("结论缺失", "三字符/检测结论不完整"))
            if category(r) == "defect" and r.get("percent") is None: issues.append(("数值缺失", "缺陷壁厚百分比未填写"))
            if category(r) == "defect" and location(r) is None: issues.append(("位置待确认", "缺少可解析的 P 位和轴向位置"))
            if not r.get("position"): issues.append(("坐标缺失", "堆芯坐标未确认"))
            for issue, note in issues: values.append([r["thimble_id"], r["id"], issue, note, r.get("report_path"), r.get("filename")])
        if not selected:
            for tube in sorted(set(range(1, 51)) - {r["thimble_id"] for r in rows}): values.append([tube, None, "缺少检测记录", "不得视为 NDD；请核查未关联报告/原始采集", None, None])
    else:
        raise ValueError("不支持的报告类型")
    duplicate_groups = cross_group_duplicates(rows)
    source_headers = ["记录ID", "大修", "通道编号", "数据组", "数据文件", "来源报告", "原始三字符", "历史匹配ID", "历史来源报告"]
    sources = [[r.get("id"), r.get("outage"), r.get("thimble_id"), r.get("calgroup"), r.get("filename"), r.get("report_path"), r.get("source_indication"), r.get("old_id"), r.get("old_report_path")] for r in rows]
    evidence = {"rows": rows, "states": repairs_for(service, site, unit),
                "rules": {"version": (rules or DEFAULT_RULES).get("version", 0),
                          "match_tolerance_mm": rule_tolerance(rules)}}
    review_scopes = [outage]
    if kind == "comparison":
        evidence["historical_rows"] = rows_for(service, site, unit, result["old"])
        evidence["current_rows"] = rows_for(service, site, unit, outage)
        review_scopes.append(result["old"])
    with service.connect() as db:
        placeholders = ",".join("?" for _ in review_scopes)
        reviews = [dict(r) for r in db.execute(
            f"SELECT * FROM cross_group_reviews WHERE unit_id=? AND outage IN ({placeholders}) ORDER BY id",
            [unit, *review_scopes])]
        original_rows = [dict(r) for r in db.execute(
            f"SELECT * FROM findings WHERE is_deleted=0 AND unit_id=? AND outage IN ({placeholders}) ORDER BY id",
            [unit, *review_scopes])]
    evidence["cross_group_reviews"] = reviews
    evidence["original_rows"] = original_rows
    for group in duplicate_groups:
        key = hashlib.sha256(json.dumps(duplicate_signature(group[0]), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        latest = next((r for r in reversed(reviews) if r["group_key"] == key and r["active"]), None)
        warnings.append({"thimble_id": group[0]["thimble_id"],
                         "reason": "跨数据组相同缺陷已人工复核保留全部，当前结果包含这些记录" if latest and latest["action"] == "keep_all" else "跨数据组相同分析人员、相同缺陷信息，全部来源保留待复核；当前结果包含这些记录",
                         "finding_ids": [r["id"] for r in group]})
    effective_ids = {r["id"] for r in rows}
    source_headers.append("参与本次统计")
    sources = [r + ["是"] for r in sources]
    # Include excluded originals from the selected scope, even for an ID-filtered report.
    with service.connect() as db:
        excluded = {r[0] for r in db.execute("""SELECT e.finding_id FROM cross_group_exclusions e
            JOIN cross_group_reviews r ON r.id=e.review_id WHERE r.active=1""")}
    for row in original_rows:
        if row["id"] in excluded and row["outage"] == outage and row["id"] not in effective_ids:
            sources.append([row.get(k) for k in ("id", "outage", "thimble_id", "calgroup", "filename",
                            "report_path", "source_indication")] + [None, None, "否：人工指定其他统计代表"])
    result = {"title": title, "kind": kind, "site": site, "unit": unit, "outage": outage, "old": payload.get("old", ""), "metadata": metadata,
              "headers": headers, "values": values, "rows": len(values), "summary": summary, "warnings": warnings, "source_headers": source_headers, "sources": sources,
              "rules": {"version": (rules or DEFAULT_RULES).get("version", 0),
                        "name": (rules or DEFAULT_RULES).get("name", ""),
                        "match_tolerance_mm": rule_tolerance(rules)},
              "rule_note": RULE_NOTE,
              "detection_counts": detection_counts,
              "cross_group_reviews": reviews,
              "evidence_digest": hashlib.sha256(json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode()).hexdigest()}
    if kind == "comparison":
        result["coverage"] = [tube_coverage(code, rows_for(service, site, unit, code)) for code in review_scopes]
        result["coverage_complete"] = all(c["complete"] for c in result["coverage"])
        result["displayed_tubes"] = len({r[1] for r in values})
        result["expected_tubes"] = 50
    if payload.get("template_id"):
        try:
            from . import reference_report
        except ImportError:
            import reference_report
        result = reference_report.prepare(service, result, payload)
    elif payload.get("draft_edits"):
        raise ValueError("请先选择报告表式，再修改报告内容")
    result["snapshot_id"] = hashlib.sha256(json.dumps(result, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return result


def preview(snapshot, service=None):
    if service is not None and snapshot.get("template_id"):
        try:
            from . import reference_report
        except ImportError:
            import reference_report
        return {**snapshot, "html": reference_report.preview(service, snapshot)}
    if service is not None and snapshot['kind'] in {'inspection', 'comparison'}:
        try:
            from . import report_forms
        except ImportError:
            import report_forms
        return {**snapshot, 'html': report_forms.preview(service, snapshot)}
    escape = lambda v: html.escape("/" if v is None or v == "" else str(v))
    parts = []
    pages = [snapshot["values"][i:i + 20] for i in range(0, snapshot["rows"], 20)] or [[]]
    for index, rows in enumerate(pages, 1):
        fields = "".join(f"<div><span>{escape(k)}</span><b>{escape(v)}</b></div>" for k, v in snapshot["metadata"].items())
        body = "".join("<tr>" + "".join(f"<td>{escape(v)}</td>" for v in r) + "</tr>" for r in rows)
        parts.append(f"<article class='report-sheet'><div class='report-page-mark'>{index}/{len(pages)}</div><h1>{escape(snapshot['title'])}</h1><section class='report-info'>{fields}</section><table><thead><tr>{''.join(f'<th>{escape(h)}</th>' for h in snapshot['headers'])}</tr></thead><tbody>{body}</tbody></table><footer>{escape(RULE_NOTE)}<br>分析：____________　审核：____________　批准：____________</footer></article>")
    return {**snapshot, "html": "".join(parts)}


# 预览结果缓存：同一份「参数 + 数据版本」只构建一次。
# 数据版本不用文件 mtime：审计事件每次请求都写库（WAL），文件指纹会被无谓刷新。
# 改用只覆盖预览输入的聚合指纹；取不到指纹时不缓存，宁可慢也不返回过期结果。
_PREVIEW_CACHE = OrderedDict()
_PREVIEW_CACHE_LIMIT = 8
_PREVIEW_CACHE_LOCK = threading.Lock()
_PREVIEW_BUILD_LOCK = threading.Lock()


def data_fingerprint(service):
    try:
        with service.connect() as db:
            findings = db.execute(
                "SELECT COUNT(*), COALESCE(MAX(id),0), COALESCE(MAX(imported_at),'') "
                "FROM findings WHERE is_deleted=0").fetchone()
            history = db.execute(
                "SELECT COUNT(*), COALESCE(MAX(edited_at),'') FROM finding_edit_history").fetchone()
            reviews = db.execute(
                "SELECT COUNT(*), COALESCE(MAX(id),0) FROM cross_group_reviews").fetchone()
            states = db.execute(
                "SELECT COUNT(*), COALESCE(MAX(updated_at),'') FROM tube_states").fetchone()
    except Exception:
        return None
    return {"findings": tuple(findings), "history": tuple(history),
            "reviews": tuple(reviews), "states": tuple(states)}


def _preview_cache_key(service, payload, rules):
    fingerprint = data_fingerprint(service)
    if fingerprint is None:
        return None
    material = json.dumps({"payload": payload, "rules": rules or {},
                           "data": fingerprint},
                          ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(material.encode()).hexdigest()


def _preview_cache_get(key):
    with _PREVIEW_CACHE_LOCK:
        cached = _PREVIEW_CACHE.get(key)
        if cached is not None:
            _PREVIEW_CACHE.move_to_end(key)
        return cached


def _preview_cache_put(key, result):
    with _PREVIEW_CACHE_LOCK:
        _PREVIEW_CACHE[key] = result
        _PREVIEW_CACHE.move_to_end(key)
        while len(_PREVIEW_CACHE) > _PREVIEW_CACHE_LIMIT:
            _PREVIEW_CACHE.popitem(last=False)


def preview_cached(service, payload, rules=None):
    """GET 预览入口：命中缓存直接返回，未命中时同一时刻只构建一份相同请求。"""
    key = _preview_cache_key(service, payload, rules)
    if key is None:
        return preview(report_snapshot(service, payload, rules=rules), service)
    cached = _preview_cache_get(key)
    if cached is not None:
        return cached
    with _PREVIEW_BUILD_LOCK:
        cached = _preview_cache_get(key)
        if cached is not None:
            return cached
        result = preview(report_snapshot(service, payload, rules=rules), service)
        _preview_cache_put(key, result)
        return result


def export(service, payload, rules=None):
    snapshot = report_snapshot(service, payload, rules=rules)
    if not payload.get("snapshot_id") or payload["snapshot_id"] != snapshot["snapshot_id"]:
        raise ValueError("数据或配置已变化，请刷新预览后再导出")
    if snapshot["kind"] == "comparison" and not snapshot.get("coverage_complete", False):
        missing = "；".join(f"{c['outage']} 缺少通道 {'、'.join(map(str, c['missing']))}" for c in snapshot["coverage"] if c["missing"])
        raise ValueError(f"50根管完整性检查未通过：{missing}。请核查并补齐真实检测记录后导出正式报告，不得用 NDD 补数")
    fmt = payload.get("format", "docx")
    kind_labels = {
        "inspection": "检验报告单",
        "comparison": "检验结果比对表",
        "data": "检测数据清单",
        "validation": "数据校验清单",
    }
    scope = f"机组{payload['unit']}_{payload.get('old') + '-' if payload.get('old') else ''}{snapshot['outage']}"
    name = artifact_naming.filename(kind_labels.get(snapshot["kind"], "检测结果"), scope, fmt)
    if snapshot.get("template_id"):
        try:
            from . import reference_report
        except ImportError:
            import reference_report
        if fmt not in {"docx", "xlsx"}:
            raise ValueError("原文表式仅支持 Word 和 Excel")
        writer = reference_report.write if fmt == "docx" else reference_report.workbook
        result = writer(service, snapshot, name)
    elif fmt == "docx" and snapshot['kind'] in {'inspection', 'comparison'}:
        try:
            from . import report_forms
        except ImportError:
            import report_forms
        result = report_forms.write(service, snapshot, name)
    elif fmt == "docx":
        blocks = []
        pages = [snapshot["values"][i:i + 20] for i in range(0, snapshot["rows"], 20)] or [[]]
        for index, rows in enumerate(pages, 1):
            blocks.extend([service._w_paragraph(f"{index}/{len(pages)}", "right", size=14), service._w_paragraph(snapshot["title"], bold=True, size=24)])
            if snapshot["metadata"]: blocks.append(service._w_table(["报告信息", "内容"], list(map(list, snapshot["metadata"].items()))))
            widths = [int(14000 / len(snapshot["headers"]))] * len(snapshot["headers"])
            blocks.append(service._w_table(snapshot["headers"], rows, widths=widths, font_size=14))
            blocks.extend([service._w_paragraph(RULE_NOTE, "left", size=14), service._w_paragraph("分析：____________  审核：____________  批准：____________", "left", size=14)])
            if index < len(pages): blocks.append(service._w_page_break())
        result = service._write_docx(name, blocks)
    elif fmt == 'xlsx' and snapshot['kind'] in {'inspection', 'comparison'}:
        try:
            from . import report_forms
        except ImportError:
            import report_forms
        result = report_forms.workbook(service, snapshot, name)
    elif fmt == "xlsx":
        book = service.Workbook()
        sheet = book.active
        sheet.title = "报告结果"
        sheet.append(snapshot["headers"])
        for row in snapshot["values"]: sheet.append(row)
        source_sheet = book.create_sheet("来源追溯")
        source_sheet.append(snapshot["source_headers"])
        for row in snapshot["sources"]: source_sheet.append(row)
        info = book.create_sheet("报告信息")
        for row in [["标题", snapshot["title"]], ["报告凭证编号", snapshot["snapshot_id"]], ["统计规则", RULE_NOTE], *map(list, snapshot["metadata"].items())]: info.append(row)
        issues = book.create_sheet("核查提醒")
        issues.append(["通道编号", "说明"])
        for row in snapshot["warnings"]: issues.append([row.get("thimble_id"), row.get("reason")])
        for ws in (sheet, source_sheet, issues):
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            service.apply_plain_excel_table(ws)
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(54, max(13, max(len(str(c.value or "")) for c in col) + 2))
            ws.page_setup.orientation = "landscape"
            ws.page_setup.fitToWidth = 1
            ws.page_setup.fitToHeight = 0
            ws.sheet_properties.pageSetUpPr.fitToPage = True
            ws.print_title_rows = "1:1"
        service.apply_plain_excel_table(info, header_rows=(), data_start=1)
        result = service.workbook_result(name, book)
    elif fmt == "csv":
        service.EXCEL_DIR.mkdir(parents=True, exist_ok=True)
        path = service.EXCEL_DIR / name
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(snapshot["headers"])
            for row in snapshot["values"]:
                writer.writerow(["'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v for v in row])
        result = {"filename": path.name, "file_path": str(path), "download_url": "/api/download-excel?name=" + service.quote(path.name)}
    else:
        raise ValueError("仅支持 Word、Excel 和 CSV")
    file_path = service.Path(result["file_path"])
    digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
    evidence = {"snapshot_id": snapshot["snapshot_id"], "format": fmt, "sha256": digest,
                "operator": local_security.actor(),
                "parser_version": service.SERVICE_VERSION, "rule_note": RULE_NOTE,
                "metadata": snapshot["metadata"], "rows": snapshot["rows"],
                "detection_counts": snapshot["detection_counts"],
                "source_headers": snapshot["source_headers"], "sources": snapshot["sources"],
                "warnings": snapshot["warnings"], "cross_group_reviews": snapshot["cross_group_reviews"],
                "coverage": snapshot.get("coverage", []), "coverage_complete": snapshot.get("coverage_complete"),
                "template_id": snapshot.get("template_id"),
                "reference_version": snapshot.get("reference_version"),
                "draft_audit": snapshot.get("draft_audit", [])}
    provenance = file_path.with_name(file_path.name + ".provenance.json")
    temporary = provenance.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        temporary.replace(provenance)
    finally:
        temporary.unlink(missing_ok=True)
    evidence["provenance_sha256"] = hashlib.sha256(provenance.read_bytes()).hexdigest()
    evidence["provenance_path"] = str(provenance)
    with service.connect() as db:
        audit_id = db.execute("""INSERT INTO report_exports(
            created_at,export_kind,outage,old_outage,new_outage,unit_id,path,metadata_json
        ) VALUES(?,?,?,?,?,?,?,?)""", (
            datetime.now().isoformat(timespec="seconds"), snapshot["kind"], snapshot["outage"],
            str(payload.get("old") or ""), snapshot["outage"], int(payload["unit"]),
            str(file_path), json.dumps(evidence, ensure_ascii=False, default=str),
        )).lastrowid
    return {**result, "rows": snapshot["rows"], "snapshot_id": snapshot["snapshot_id"],
            "export_audit_id": audit_id, "sha256": digest,
            "provenance_file_path": str(provenance), "provenance_filename": provenance.name,
            "provenance_download_url": result["download_url"].split("?")[0] + "?name=" + service.quote(provenance.name)}
