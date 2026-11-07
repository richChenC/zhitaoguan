"""Maintenance events and derived service state; inspection results stay immutable."""
import hashlib
import json
import math
import re

LABELS = {"normal": "正常", "plugged": "堵管", "shifted": "移位", "replaced": "换管"}
STAGES = {"unknown", "before_replacement", "after_replacement"}
ALIASES = {"HZ": "P", "CN": "C"}


def scope_key(outage):
    match = re.fullmatch(r"([A-Z]{1,2})([1-9])(\d{2})", str(outage).upper())
    if not match:
        raise ValueError("大修编号格式无效")
    return ALIASES.get(match[1], match[1]), int(match[2]), int(match[3])


def events(row):
    if row.get("events") is not None:
        return list(row["events"])
    if row.get("events_json") is not None:
        return json.loads(row["events_json"])
    return [row["state"]] if row.get("state") in LABELS and row["state"] != "normal" else []


def projection(names):
    return next((name for name in ("plugged", "replaced", "shifted") if name in names), "normal")


def event_label(row):
    names = events(row)
    return " · ".join(LABELS[name] for name in names) if names else "正常"


def validate(data, state):
    names = data.get("events", [state] if state != "normal" else [])
    if not isinstance(names, list) or len(names) != len(set(names)) or any(
            name not in {"plugged", "shifted", "replaced"} for name in names):
        raise ValueError("维护事件应为不重复的堵管、移位、换管列表")
    names = [name for name in ("plugged", "shifted", "replaced") if name in names]
    stage = str(data.get("replacement_stage") or "unknown")
    if stage not in STAGES:
        raise ValueError("换管前后顺序无效")
    if "replaced" not in names or len(names) == 1:
        stage = "unknown"
    if "shifted" not in names and any(data.get(key) not in (None, "", 0, 0.0, "0", "0.0")
                                      for key in ("offset_mm", "unsigned_offset_mm")):
        raise ValueError("没有移位事件时不能填写移位距离")
    return names, stage


def effective(records, outage, unit, tube, inclusive=True):
    target = scope_key(outage)
    relevant = [dict(row) for row in records if not row.get("is_deleted")
                and int(row["unit_id"]) == int(unit) and int(row["thimble_id"]) == int(tube)
                and scope_key(row["outage"])[:2] == target[:2]
                and (scope_key(row["outage"])[2] <= target[2] if inclusive
                     else scope_key(row["outage"])[2] < target[2])]
    relevant.sort(key=lambda row: scope_key(row["outage"])[2])
    plugged, plug_since, generation, cumulative, review, shifted = False, "", 1, 0.0, False, False
    warnings, current, last = [], None, None
    for row in relevant:
        names = events(row)
        replace = "replaced" in names
        stage = row.get("replacement_stage") or "unknown"
        ambiguous = replace and len(names) > 1 and stage == "unknown"
        if replace:
            generation += 1
            # An explicit replacement ends the old physical tube's history.
            plugged, plug_since, cumulative, review = False, "", 0.0, False
            shifted = False
            warnings = []
        if ambiguous:
            # Do not guess whether co-recorded events belong to the removed or
            # replacement tube. The replacement is known; the other facts are not.
            review, cumulative = True, None
            warnings.append(f"{row['outage']} 换管与其他处理的先后顺序待确认")
        elif not replace or stage == "after_replacement":
            if "plugged" in names:
                plugged, plug_since = True, plug_since or row["outage"]
            if "shifted" in names:
                shifted = True
                distance = row.get("offset_mm")
                if row.get("offset_confirmed", 1) == 0 or distance is None or not math.isfinite(float(distance)):
                    cumulative = None
                    review = True
                    unsigned = row.get("unsigned_offset_mm")
                    detail = f"（原记录距离 {unsigned:g} mm，方向未确认）" if unsigned is not None else ""
                    warnings.append(f"{row['outage']} 移位距离或方向未确认{detail}")
                elif cumulative is not None:
                    cumulative += float(distance)
        if scope_key(row["outage"])[2] == target[2]:
            current = row
        last = row
    current_events = events(current) if current else []
    badges = (["plugged"] if plugged else []) + (["shifted"] if shifted else []) + (
        ["replaced"] if "replaced" in current_events else [])
    if review:
        warnings.append("维护顺序未核实，不自动沿用旧管缺陷或换算位置")
    state = "plugged" if plugged else "replaced" if "replaced" in current_events else (
        "shifted" if shifted else "unknown" if review or not last else "normal")
    label = " · ".join(LABELS[name] for name in badges) if badges else (
        "移位" if state == "shifted" else "未维护" if state == "unknown" else "正常")
    if review:
        label = (label + " · 待核对") if badges else "状态待核对"
    return dict(state=state, state_label=label, plugged=plugged, shifted=shifted, plug_since=plug_since,
                inherited_plug=bool(plugged and "plugged" not in current_events),
                generation=generation, cumulative_offset_mm=cumulative,
                needs_review=review, warnings=list(dict.fromkeys(warnings)),
                maintained=bool(current), last_maintenance=last["outage"] if last else "",
                current_events=current_events)


class StateHistory:
    """Request-local history grouped by physical tube, including site aliases."""

    def __init__(self, records):
        self._groups = {}
        for row in records:
            self.upsert(row)

    @staticmethod
    def _key(outage, unit, tube):
        return scope_key(outage)[:2], int(unit), int(tube)

    def get(self, outage, unit, tube):
        return self._groups.get(self._key(outage, unit, tube), {}).get(outage)

    def upsert(self, row):
        key = self._key(row["outage"], row["unit_id"], row["thimble_id"])
        group = self._groups.setdefault(key, {})
        if row.get("is_deleted"):
            group.pop(row["outage"], None)
        else:
            group[row["outage"]] = dict(row)

    def effective(self, outage, unit, tube, inclusive=True):
        group = self._groups.get(self._key(outage, unit, tube), {})
        return effective(group.values(), outage, unit, tube, inclusive=inclusive)


def rows(db):
    return [dict(row) for row in db.execute("SELECT * FROM tube_states WHERE is_deleted=0")]


def revision(db):
    # Includes deletions/restores/import rollback as well as ordinary edits.
    data = [dict(row) for row in db.execute("SELECT * FROM tube_states ORDER BY outage,unit_id,thimble_id")]
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def check_expected(current, data):
    if "expected_updated_at" in data:
        actual = current.get("updated_at") if current and not current.get("is_deleted") else None
        if actual != data["expected_updated_at"]:
            raise ValueError("维护记录已变化，请刷新后重新预览；本次未保存")


def public(row):
    row = dict(row)
    row["events"] = events(row)
    row["event_label"] = event_label(row)
    return row
