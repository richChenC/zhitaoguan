"""One official, filterable dataset for the desktop visualization workspace."""
from collections import Counter, defaultdict

try:
    from . import analysis_reporting as analysis
    from . import tube_lifecycle
except ImportError:
    import analysis_reporting as analysis
    import tube_lifecycle


def report_category(row):
    """Preserve raw conclusions; classify documented no-signal placeholders as NDD."""
    code = str(row.get("indication") or "").strip().upper()
    if code == "WAR":
        return "defect"
    if analysis.no_defect_basis(row):
        return "NDD"
    return "incomplete"

def explicit_ndd(row):
    """Zero baselines require a documented conclusion, never an inferred blank."""
    return bool(analysis.no_defect_basis(row, auto_ndd=False))


def matched_increments(service, grouped, repairs_by_tube, query):
    """Adjacent, one-to-one WAR pairs; never subtract independently summed reports."""
    sites, unit_code, outage_code = query["sites"], query["unit"], query["outage"]
    allow_ndd_zero = str(query.get("ndd_zero", "1")).strip().lower() not in ("0", "false")
    rule_loader = getattr(service, "active_analysis_rules", None)
    rules = rule_loader() if callable(rule_loader) else analysis.DEFAULT_RULES
    rounds = {(site, unit, order): (outage, records)
              for (site, unit, order, outage), records in grouped.items()}
    result = []

    def evidence(row):
        if row is None:
            return None
        return {"id": row.get("id"), "outage": row["outage"],
                "location": row.get("location_raw", row.get("location")) or "",
                "percent": row.get("percent") if analysis.numeric(row.get("percent")) else None,
                "channel": row.get("channel") or "",
                "source": row.get("report_path") or row.get("filename") or ""}

    for (site, unit, order, outage), current in sorted(grouped.items()):
        code = f"{site}{unit}"
        if (not current or (sites and site not in sites) or (unit_code and code != unit_code)
                or (outage_code and outage != outage_code)):
            continue
        old, before = rounds.get((site, unit, order - 1), (None, []))
        wear = [row for row in current if str(row.get("indication") or "").strip().upper() == "WAR"]
        repairs = [event for tube in range(1, 51)
                   for event in repairs_by_tube[(site, unit, tube)]]
        compared = analysis.compare_rows(old, outage, unit, before, wear, repairs, rules=rules)["items"] if before else []
        old_rows = {row["id"]: row for row in before if row.get("id") is not None}
        before_by_tube = defaultdict(list)
        for row in before:
            try:
                before_by_tube[int(row.get("thimble_id"))].append(row)
            except (TypeError, ValueError):
                continue
        ndd_baseline_tubes = {tube for tube, rows in before_by_tube.items()
                              if rows and all(explicit_ndd(row) for row in rows)}

        def replaced_between(tube):
            for event in repairs_by_tube.get((site, unit, tube), []):
                if "replaced" not in tube_lifecycle.events(event):
                    continue
                try:
                    if analysis.sequence(event["outage"])[2] in (order - 1, order):
                        return True
                except ValueError:
                    continue
            return False

        # Independent current matches may reuse one historical indication. Neither
        # occurrence is a trustworthy one-to-one pair in that case.
        used = Counter(row["old_id"] for row in compared if row.get("old_id") is not None)
        entries, positions = [], Counter()
        for index, row in enumerate(wear):
            pair = compared[index] if compared else {}
            previous = old_rows.get(pair.get("old_id"))
            reason = ""
            ndd_baseline = False
            if not before:
                reason = "首次记录，无相邻上轮检测基准" if order == 1 else "缺少相邻上轮检测记录，不跨轮补算"
            elif int(row["thimble_id"]) in ndd_baseline_tubes and not replaced_between(int(row["thimble_id"])):
                if allow_ndd_zero:
                    ndd_baseline = True
                else:
                    reason = "前次结论为 NDD；已关闭“NDD 记 0 深度”，不按零起算"
            elif pair.get("comparison") != "R":
                reason = ("新显示或换管后新基准，无历史 WAR 配对，不按零计算"
                          if pair.get("comparison") == "NI" else pair.get("comparison_note") or "未形成确定匹配")
            elif previous is None or row.get("id") is None:
                reason = "缺少可追溯的原始记录编号"
            elif used[pair["old_id"]] != 1:
                reason = "同一历史记录对应多条本次记录，需人工确认"
            elif str(previous.get("indication") or "").strip().upper() != "WAR":
                reason = "历史结论不是 WAR"
            elif any(not analysis.numeric(value) or not 0 <= value <= 100
                     for value in (row.get("percent"), previous.get("percent"))):
                reason = "前后深度缺失或超出 0–100%，不按零计算"
            if ndd_baseline and (not analysis.numeric(row.get("percent")) or not 0 <= row["percent"] <= 100):
                ndd_baseline = False
                reason = "本次深度缺失或超出 0–100%，不按零计算"
            delta = (None if reason else
                     row["percent"] if ndd_baseline else row["percent"] - previous["percent"])
            bucket = analysis.position_resolution(row)["position_bucket"]
            if delta is not None:
                positions[bucket] += delta
            entries.append({"tube": int(row["thimble_id"]), "position_bucket": bucket,
                            "previous": evidence(previous), "current": evidence(row),
                            "delta": delta, "reason": reason, "ndd_baseline": ndd_baseline,
                            "note": ("前次结论为明确 NDD，按 0 深度起算（判定值，非实测）"
                                     if ndd_baseline else pair.get("comparison_note") or reason),
                            "shift_mm": pair.get("shift_mm")})
        matched = [entry for entry in entries if entry["delta"] is not None]
        matched_old = {entry["previous"]["id"] for entry in matched
                       if entry["previous"] and entry["previous"].get("id") is not None}
        unmatched_history = sum(str(row.get("indication") or "").strip().upper() == "WAR"
                                and row.get("id") not in matched_old for row in before)
        partial = (len(matched) < len(wear) or unmatched_history > 0 or not before
                   or any(len({row["thimble_id"] for row in rows}) < 50
                          or any(report_category(row) == "incomplete" for row in rows)
                          for rows in (before, current)))
        result.append({"site": site, "unit": code, "outage": outage, "order": order,
                       "old_outage": old, "total": sum(entry["delta"] for entry in matched) if matched else None,
                       "positions": dict(positions), "matched": len(matched), "wear_records": len(wear),
                       "excluded": len(wear) - len(matched), "unmatched_history": unmatched_history,
                       "ndd_baseline": sum(1 for entry in matched if entry["ndd_baseline"]),
                       "ndd_zero": allow_ndd_zero,
                       "partial": partial, "items": entries,
                       "rules": {"version": rules.get("version", 0), "name": rules.get("name", ""),
                                 "match_tolerance_mm": analysis.rule_tolerance(rules)}})
    return result


def build(service, query):
    rows = analysis.rows_for(service)
    positions = {id(row): analysis.position_resolution(row) for row in rows}
    repairs = analysis.repairs_for(service)

    # 计划清单分母加载（保守：无计划时回退 50；有计划时使用 actual plan 管数）
    plan_map = {}
    try:
        with service.connect() as _db:
            try:
                for _row in _db.execute(
                        "SELECT p.id, p.site_code, p.unit_id, p.outage, "
                        "COALESCE(p.status,'') AS status, COUNT(pt.thimble_id) AS tubes_count "
                        "FROM outage_plans p LEFT JOIN outage_plan_tubes pt ON pt.plan_id=p.id "
                        "WHERE p.status IN ('active','archived') "
                        "GROUP BY p.id ORDER BY p.id"):
                    plan_map[(_row[1], int(_row[2]) if _row[2] and str(_row[2]).isdigit() else 0,
                              str(_row[3] or "").strip().upper())] = int(_row[5]) or 50
            except Exception:
                plan_map = {}
    except Exception:
        plan_map = {}
    def _plan_denominator(site, unit, outage):
        return plan_map.get((site, unit, str(outage or "").strip().upper()), 50)

    units = {}
    invalid = 0
    valid = []
    for row in rows:
        try:
            site, unit, order = analysis.sequence(row["outage"])
        except ValueError:
            invalid += 1
            continue
        code = f"{site}{unit}"
        units.setdefault(code, {"code": code, "site": site, "unit": unit, "outages": set()})
        units[code]["outages"].add(row["outage"])
        valid.append((site, unit, order, row))
    repairs_by_tube = defaultdict(list)
    for event in repairs:
        try:
            site, unit, order = analysis.sequence(event["outage"])
            tube = int(event["thimble_id"])
            if not 1 <= tube <= 50:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        event = {**event, "unit_id": unit}
        repairs_by_tube[(site, unit, tube)].append(event)
        code = f"{site}{unit}"
        units.setdefault(code, {"code": code, "site": site, "unit": unit, "outages": set()})
        units[code]["outages"].add(event["outage"])
    for events in repairs_by_tube.values():
        events.sort(key=lambda event: analysis.sequence(event["outage"])[2])
    sites = {v for v in str(query.get("sites", "")).upper().split(",") if v}
    if sites - set(analysis.SITE_LABELS):
        raise ValueError("基地代号无效")
    thresholds = sorted({int(value) for value in str(query.get("levels", "")).split(",")
                         if value.strip().isdigit() and 0 <= int(value) <= 100}) or [30, 50]
    selected_unit = str(query.get("unit", "")).upper()
    selected_outage = str(query.get("outage", "")).upper()
    if selected_unit and selected_unit not in units:
        raise ValueError("机组没有可视化数据")
    if selected_unit and sites and units[selected_unit]["site"] not in sites:
        raise ValueError("机组不属于所选基地")
    if selected_outage and not any(
        selected_outage in item["outages"] and (not sites or item["site"] in sites)
        and (not selected_unit or item["code"] == selected_unit) for item in units.values()):
        raise ValueError("大修不属于所选范围")
    scoped = [(s, u, n, r) for s, u, n, r in valid
              if (not sites or s in sites) and (not selected_unit or f"{s}{u}" == selected_unit)
              and (not selected_outage or r["outage"] == selected_outage)]
    # Keep physical outage numbers. A missing import must never renumber D120 as round 2.
    grouped = defaultdict(list)
    for s, u, n, r in valid:
        grouped[(s, u, n, r["outage"])].append(r)
    for item in units.values():
        for outage in item["outages"]:
            grouped.setdefault((*analysis.sequence(outage), outage), [])
    trends, snapshots, all_snapshots = [], [], []
    history_by_unit = defaultdict(list)
    unknown_positions = missing_depth = 0
    replacement_events = defaultdict(set)
    for key, events in repairs_by_tube.items():
        replacement_events[key] = {event["outage"] for event in events
                                   if "replaced" in tube_lifecycle.events(event)}
    for (site, unit, order, outage), records in sorted(grouped.items()):
        in_scope = ((not sites or site in sites) and (not selected_unit or f"{site}{unit}" == selected_unit)
                    and (not selected_outage or outage == selected_outage))
        sums = Counter()
        valid_wear = 0
        position_stats = {}
        wear_rows = [r for r in records if str(r.get("indication") or "").strip().upper() == "WAR"]
        for r in wear_rows:
            bucket = positions[id(r)]["position_bucket"]
            stats = position_stats.setdefault(bucket, {"records": 0, "valid": 0, "missing": 0,
                                                       "total": None, "max_depth": None, "tubes": set()})
            stats["records"] += 1
            stats["tubes"].add(int(r["thimble_id"]))
            if bucket == "未解析" and in_scope:
                unknown_positions += 1
            depth = r.get("percent")
            if not analysis.numeric(depth) or not 0 <= depth <= 100:
                missing_depth += int(in_scope)
                stats["missing"] += 1
                continue
            sums[bucket] += depth
            stats["valid"] += 1
            stats["total"] = (stats["total"] or 0) + depth
            stats["max_depth"] = max(stats["max_depth"] or 0, depth)
            valid_wear += 1
        # Explicit NDD is zero; missing conclusions or unquantified defects are not zero.
        total = sum(sums.values()) if valid_wear else (0 if records and all(report_category(r) == "NDD" for r in records) else None)
        outage_index = order
        by_tube = defaultdict(list)
        for r in records:
            by_tube[int(r["thimble_id"])].append(r)
        tubes = []
        for tube in range(1, 51):
            source = by_tube[tube]
            kinds = {report_category(r) for r in source}
            coverage = "defect" if "defect" in kinds else "incomplete" if "incomplete" in kinds else "NDD" if source else "missing"
            depths = [r["percent"] for r in source if report_category(r) == "defect"
                      and analysis.numeric(r.get("percent")) and 0 <= r["percent"] <= 100]
            events = [e for e in repairs_by_tube[(site, unit, tube)]
                      if analysis.sequence(e["outage"])[2] <= order]
            last = events[-1] if events else {}
            current = next((e for e in events if e["outage"] == outage), None)
            lifecycle = tube_lifecycle.effective(events, outage, unit, tube)
            badges = ([key for key in ("plugged", "shifted") if lifecycle[key]]
                      + (["replaced"] if "replaced" in lifecycle["current_events"] else []))
            tubes.append({"tube": tube, "position": service.position_for(unit, tube),
                          "coverage": coverage, "max_depth": max(depths) if depths else None,
                          "state": lifecycle["state"] if last else None,
                          "state_label": lifecycle["state_label"] if last else "管子状态未记录",
                          "state_badges": badges, "state_recorded": bool(last),
                          "state_current_recorded": lifecycle["maintained"],
                          "needs_review": lifecycle["needs_review"], "state_warnings": lifecycle["warnings"],
                          "plug_since": lifecycle["plug_since"], "inherited_plug": lifecycle["inherited_plug"],
                          "shifted": lifecycle["shifted"],
                          "current_events": lifecycle["current_events"],
                          "replacement_record": {
                              "key": f"{outage}/{unit}/{tube}", "outage": outage, "tube": tube,
                              "source": current.get("source") or "",
                              "note": current.get("note") or "",
                              "updated_at": current.get("updated_at") or "",
                          } if current and "replaced" in tube_lifecycle.events(current) else None,
                          "offset_mm": lifecycle["cumulative_offset_mm"] if last else None,
                          "unsigned_offset_mm": last.get("unsigned_offset_mm"),
                          "state_outage": last.get("outage"), "remarks": last.get("note", ""),
                          "source": last.get("source", ""),
                          "replacements": len({e["outage"] for e in events
                                               if "replaced" in tube_lifecycle.events(e)}),
                          "lifetime_replacements": len(replacement_events[(site, unit, tube)]),
                          "lifetime_replacement_outages": sorted(replacement_events[(site, unit, tube)],
                              key=lambda code: analysis.sequence(code)[2]),
                          "records": len(source),
                          "incomplete_records": sum(report_category(r) == "incomplete" for r in source),
                          "missing_depth": sum(report_category(r) == "defect" and
                                               (not analysis.numeric(r.get("percent")) or
                                                not 0 <= r["percent"] <= 100) for r in source),
                          "findings": [{"indication": r.get("indication") or "",
                                        "classification_basis": analysis.no_defect_basis(r),
                                        **positions[id(r)],
                                        "location": r.get("location_raw", r.get("location")) or "",
                                        "depth": r.get("percent") if analysis.numeric(r.get("percent"))
                                                 and 0 <= r["percent"] <= 100 else None,
                                        "analyst": r.get("analyst") or "",
                                        "source": r.get("report_path") or r.get("filename") or ""}
                                       for r in source]})
        if in_scope and records:
            missing_tubes = sum(tube["coverage"] == "missing" for tube in tubes)
            incomplete_tubes = sum(any(report_category(r) == "incomplete" for r in by_tube[tube])
                                   for tube in range(1, 51))
            unquantified = len(wear_rows) - valid_wear
            trends.append({"site": site, "unit": f"{site}{unit}", "outage": outage, "order": order,
                           "outage_index": outage_index,
                           "total": total, "positions": dict(sums), "records": len(records),
                           "wear_records": len(wear_rows), "valid_wear": valid_wear,
                           "missing_depth": unquantified,
                           "reported_tubes": 50 - missing_tubes, "missing_tubes": missing_tubes,
                           "incomplete_tubes": incomplete_tubes,
                           "partial": bool(missing_tubes or incomplete_tubes or unquantified),
                           "position_stats": {key: {**value, "tubes": len(value["tubes"])}
                                              for key, value in position_stats.items()}})
        plan_denom = _plan_denominator(site, unit, outage)
        snapshot = {"site": site, "unit": f"{site}{unit}", "outage": outage, "order": order,
                    "outage_index": outage_index, "tubes": tubes,
                    "plan_denominator": plan_denom}
        # Keep an unfiltered copy for the fixed base selector summaries.  The
        # visible workspace may be scoped to one base, but the selector cards
        # must retain the same global denominator after a click.
        all_snapshots.append(snapshot)
        if in_scope:
            snapshots.append(snapshot)
        history_by_unit[f"{site}{unit}"].append(history_summary(snapshot))
    latest = {}
    for item in snapshots:
        if item["unit"] not in latest or item["order"] > latest[item["unit"]]["order"]:
            latest[item["unit"]] = item
    latest_all = {}
    for item in all_snapshots:
        if item["unit"] not in latest_all or item["order"] > latest_all[item["unit"]]["order"]:
            latest_all[item["unit"]] = item
    # Keep every earlier report in-scope so users can choose an explicit baseline.
    comparison_baselines = []
    if selected_outage:
        for current in snapshots:
            preceding = [item for item in all_snapshots
                         if item["unit"] == current["unit"] and item["order"] < current["order"]]
            comparison_baselines.extend(preceding)
    comparison_baselines = list({
        (item["unit"], item["outage"]): item for item in comparison_baselines
    }.values())
    site_summary = {}
    for site in analysis.SITE_LABELS:
        site_latest = [item for item in latest_all.values() if item["site"] == site]
        total = sum(len(item["tubes"]) for item in site_latest)
        reported = sum(sum(tube["coverage"] != "missing" for tube in item["tubes"]) for item in site_latest)
        site_summary[site] = {
            "units": len(site_latest),
            "coverageRate": reported / total * 100 if total else 0,
            "total": total,
            "reported": reported,
            "findings": sum(sum(tube["coverage"] == "defect" for tube in item["tubes"]) for item in site_latest),
        }
    all_total = sum(item["total"] for item in site_summary.values())
    all_reported = sum(item["reported"] for item in site_summary.values())
    site_summary[""] = {
        "units": len(latest_all),
        "coverageRate": all_reported / all_total * 100 if all_total else 0,
        "total": all_total,
        "reported": all_reported,
        "findings": sum(item["findings"] for key, item in site_summary.items() if key),
    }
    coverage = []
    for item in latest.values():
        denom = _plan_denominator(item["site"], item["unit"], item["outage"])
        counts = dict(Counter(t["coverage"] for t in item["tubes"]))
        reported_vs_plan = counts.get("defect", 0) + counts.get("incomplete", 0) + counts.get("NDD", 0)
        coverage.append({
            "unit": item["unit"], "outage": item["outage"],
            "counts": counts,
            "plan_denominator": denom,
            "reported_vs_plan": reported_vs_plan,
            "coverageRate_vs_plan": round(reported_vs_plan / denom * 100, 2) if denom else 0,
        })
    map_stats = {}
    for site in analysis.SITE_LABELS:
        data = [(s, u, n, r) for s, u, n, r in scoped if s == site]
        map_stats[site] = {"findings": len(data), "units": len({u for _, u, _, _ in data}),
                           "outages": len({r["outage"] for _, _, _, r in data})}
    options = []
    for item in units.values():
        ordered_outages = sorted(item["outages"], key=lambda o: (analysis.sequence(o)[2], o))
        latest_order = max(analysis.sequence(outage)[2] for outage in ordered_outages)
        recorded = {analysis.sequence(outage)[2] for outage in ordered_outages}
        missing_outages = [f"{item['code']}{order:02d}" for order in range(1, latest_order + 1)
                           if order not in recorded]
        options.append({**item, "outages": ordered_outages,
                        "history": sorted(history_by_unit[item["code"]], key=lambda entry: entry["order"]),
                        "latest_order": latest_order, "missing_outages": missing_outages,
                        "detection_outages": [entry["outage"] for entry in history_by_unit[item["code"]]
                                             if entry["records"]],
                        "outage_entries": [{"code": outage,
                                            "index": analysis.sequence(outage)[2],
                                            "label": f"第{analysis.sequence(outage)[2]:03d}次大修"}
                                           for outage in ordered_outages]})
    labels = [f"0–{thresholds[0]}%"] + [
        f"{low}–{high}%" for low, high in zip(thresholds, thresholds[1:])
    ] + [f"≥{thresholds[-1]}%"]
    buckets = [{"label": label, "tubes": 0, "defects": 0} for label in labels]
    tube_total = defect_total = 0
    for item in latest.values():
        for tube in item["tubes"]:
            if tube["coverage"] != "missing":
                tube_total += 1
            if tube["max_depth"] is not None:
                buckets[sum(tube["max_depth"] >= threshold for threshold in thresholds)]["tubes"] += 1
            for finding in tube["findings"]:
                if str(finding.get("indication") or "").strip().upper() != "WAR":
                    continue
                defect_total += 1
                depth = finding.get("depth")
                if depth is not None:
                    buckets[sum(depth >= threshold for threshold in thresholds)]["defects"] += 1
    new_counts = []
    for item in latest.values():
        earlier = [entry for entry in snapshots
                   if entry["unit"] == item["unit"] and entry["order"] < item["order"]]
        if not earlier:
            continue
        previous = max(earlier, key=lambda entry: entry["order"])
        old = {tube["tube"] for tube in previous["tubes"] if tube["coverage"] == "defect"}
        new_counts.append(sum(tube["coverage"] == "defect" and tube["tube"] not in old
                              for tube in item["tubes"]))
    return {"source": "当前数据库 / statistical_findings（当前版本及人工统计选择）",
            "scope": {"sites": sorted(sites), "unit": selected_unit, "outage": selected_outage},
            "sites": analysis.SITE_LABELS, "site_summary": site_summary,
            "units": sorted(options, key=lambda x: x["code"]),
            "trends": trends,
            "increments": matched_increments(service, grouped, repairs_by_tube,
                                             {"sites": sites, "unit": selected_unit, "outage": selected_outage,
                                              "ndd_zero": query.get("ndd_zero", "1")}),
            "snapshots": snapshots, "comparison_baselines": comparison_baselines,
            "coverage": coverage, "map": map_stats,
            "summary": {"records": len(scoped), "units": len(latest), "outages": len(snapshots),
                        "expected_tubes": len(latest) * 50,
                        "tube_total": tube_total, "defect_total": defect_total,
                        "bucket_defects": buckets,
                        "new_defects": sum(new_counts) if new_counts else None,
                        "reported_tubes": sum(50 - c["counts"].get("missing", 0) for c in coverage),
                        "missing_tubes": sum(c["counts"].get("missing", 0) for c in coverage)},
            "quality": {"invalid_outage_rows": invalid, "unparsed_wear_positions": unknown_positions,
                        "unquantified_wear_rows": missing_depth,
                        "cross_group_duplicate_sets": len(analysis.cross_group_duplicates([r for _, _, _, r in scoped]))}}


def history_summary(snapshot):
    """Keep detection coverage and effective maintenance coverage independent."""
    tubes = snapshot["tubes"]
    states = {key: [tube["tube"] for tube in tubes if key in tube["state_badges"]]
              for key in ("plugged", "shifted", "replaced")}
    states["normal"] = [tube["tube"] for tube in tubes if tube["state"] == "normal"]
    return {"outage": snapshot["outage"], "order": snapshot["order"],
            "records": sum(tube["records"] for tube in tubes),
            "conclusion_records": dict(Counter(finding["indication"] for tube in tubes
                                              for finding in tube["findings"])),
            "detection_tubes": {key: [tube["tube"] for tube in tubes if tube["coverage"] == key]
                                for key in ("defect", "NDD", "incomplete")},
            "counts": dict(Counter(tube["coverage"] for tube in tubes)),
            "missing_tubes": [tube["tube"] for tube in tubes if tube["coverage"] == "missing"],
            "incomplete_tubes": [tube["tube"] for tube in tubes if tube["incomplete_records"]],
            "unquantified_tubes": [tube["tube"] for tube in tubes if tube["missing_depth"]],
            "state_tubes": states,
            "state_missing_tubes": [tube["tube"] for tube in tubes if not tube["state_recorded"]],
            "state_current_tubes": [tube["tube"] for tube in tubes if tube["state_current_recorded"]],
            "state_current_missing_tubes": [tube["tube"] for tube in tubes if not tube["state_current_recorded"]],
            "state_sources": [
                {"tube": tube["tube"], "outage": tube["state_outage"], "label": tube["state_label"],
                 "source": tube["source"], "note": tube["remarks"], "warnings": tube["state_warnings"]}
                for tube in tubes if tube["state_recorded"]],
            "replacement_records": [tube["replacement_record"] for tube in tubes
                                    if tube["replacement_record"] is not None],
            "state_review_tubes": [tube["tube"] for tube in tubes if tube["needs_review"]],
            "inherited_plug_tubes": [tube["tube"] for tube in tubes if tube["inherited_plug"]]}
