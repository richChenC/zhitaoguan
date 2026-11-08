"""Native projections matching the reviewed desktop analytics semantics."""
from __future__ import annotations

from collections import Counter
from math import isfinite


def valid_depth(tube):
    value = (tube or {}).get("max_depth")
    return value if ((tube or {}).get("coverage") == "defect"
                     and isinstance(value, (int, float)) and not isinstance(value, bool)
                     and isfinite(value) and 0 <= value <= 100) else None


def depth_distribution(snapshots):
    counts = [0] * 20
    ndd = excluded = 0
    for snapshot in snapshots:
        for tube in snapshot.get("tubes") or []:
            value = valid_depth(tube)
            if tube.get("coverage") == "NDD":
                ndd += 1
            elif value is None or tube.get("missing_depth") or tube.get("incomplete_records"):
                excluded += 1
            else:
                counts[min(19, int(value // 5))] += 1
    return {"bins": [(f"{i * 5}–{(i + 1) * 5}", value) for i, value in enumerate(counts)],
            "NDD": ndd, "excluded": excluded, "quantified": sum(counts)}


def channel_frequency(snapshots, threshold):
    """One effective maximum per unit/outage/physical channel; strictly > threshold."""
    observed, counts = set(), Counter()
    for snapshot in snapshots:
        for tube in snapshot.get("tubes") or []:
            key = (snapshot["unit"], snapshot["outage"], int(tube["tube"]))
            value = valid_depth(tube)
            if key not in observed:
                observed.add(key)
                if value is not None and value > threshold:
                    counts[tube.get("position") or f"{snapshot['unit']}/{tube['tube']}"] += 1
    return counts


def status_change(snapshots, unit, outage, high=50, baseline=None):
    history = sorted((s for s in snapshots if s["unit"] == unit), key=lambda s: s["order"])
    current = next((s for s in history if s["outage"] == outage), None)
    if current is None:
        return {"rows": [], "counts": {}, "earlier": [], "previous": None}
    earlier = [s for s in history if s["order"] < current["order"]]
    previous = (next((s for s in earlier if s["outage"] == baseline), None)
                if baseline is not None else (earlier[-1] if earlier else None))
    old_tubes = {int(t["tube"]): t for t in (previous or {}).get("tubes", [])}
    rows = []
    for tube in current.get("tubes") or []:
        old = old_tubes.get(int(tube["tube"]))
        depth, old_depth = valid_depth(tube), valid_depth(old)
        events = [e for e in tube.get("current_events") or [] if e in ("plugged", "shifted", "replaced")]
        interval = [t for s in history
                    if previous and previous["order"] < s["order"] <= current["order"]
                    for t in s.get("tubes") or [] if t["tube"] == tube["tube"]]
        interval_events = {e for t in interval for e in t.get("current_events") or []}
        replaced = "replaced" in events or bool(old and (tube.get("replacements") or 0) > (old.get("replacements") or 0))
        shifted = "shifted" in events or bool(old and (
            tube.get("offset_mm") != old.get("offset_mm")
            or tube.get("unsigned_offset_mm") != old.get("unsigned_offset_mm")))
        review = bool(tube.get("needs_review") or tube.get("coverage") == "incomplete"
                      or tube.get("incomplete_records") or tube.get("missing_depth")
                      or (tube.get("coverage") == "defect" and depth is None))
        reason = ""
        if previous is None:
            reason = "无历史基线"
        elif old is None:
            reason = "前轮缺少通道记录"
        elif replaced or "replaced" in interval_events:
            reason = "对比期间换管，不计算差值"
        elif shifted or "shifted" in interval_events:
            reason = "对比期间移位，不计算差值"
        elif tube.get("needs_review") or old.get("needs_review"):
            reason = "维护状态待核对"
        elif tube.get("incomplete_records") or old.get("incomplete_records"):
            reason = "存在待核对检测结论"
        elif tube.get("missing_depth") or old.get("missing_depth"):
            reason = "存在未量化 WAR，最大值不完整"
        elif tube.get("position") != old.get("position") or (
                any(t.get("position") != old.get("position") for t in interval)
                and any(t.get("position") != tube.get("position") for t in interval)):
            reason = "对比期间堆芯位置变化"
        elif depth is None or old_depth is None:
            reason = "两轮缺少可比量化值"
        delta = None if reason else round(depth - old_depth, 4)
        active = lambda t: sorted(e for e in (t or {}).get("state_badges", []) if e != "replaced")
        coverage_changed = bool(old and old.get("coverage") != tube.get("coverage"))
        state_changed = bool(old and (bool(old.get("state_recorded")) != bool(tube.get("state_recorded"))
                                     or active(old) != active(tube)))
        row = {"tube": int(tube["tube"]), "current": tube, "old": old,
               "depth": depth, "oldDepth": old_depth, "delta": delta, "exclusion": reason,
               "review": review, "newWar": bool(old and old.get("coverage") == "NDD" and tube.get("coverage") == "defect"),
               "maintenance": bool(events), "high": depth is not None and depth >= high,
               "missing": tube.get("coverage") == "missing",
               "changed": bool((delta is not None and delta != 0) or coverage_changed or state_changed or events)}
        rows.append(row)
    counts = {"all": len(rows), "comparable": sum(r["delta"] is not None for r in rows)}
    for key in ("changed", "newWar", "maintenance", "review", "missing", "high"):
        counts[key] = sum(bool(r[key]) for r in rows)
    counts.update(up=sum(r["delta"] is not None and r["delta"] > 0 for r in rows),
                  down=sum(r["delta"] is not None and r["delta"] < 0 for r in rows))
    return {"rows": sorted(rows, key=lambda r: r["tube"]), "counts": counts,
            "current": current, "earlier": earlier, "previous": previous}
