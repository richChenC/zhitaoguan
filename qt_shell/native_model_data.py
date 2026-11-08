"""Reference geometry mapping and source-preserving axial defect placement."""
from __future__ import annotations

from functools import lru_cache
import json
import math
import re
import unicodedata

from .constants import UI_DIR

MODEL_DATA = UI_DIR / "visualizations" / "reference-thimble" / "data"


@lru_cache(maxsize=1)
def reference_layout():
    return json.loads((MODEL_DATA / "vessel_layout.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def reference_stations():
    return {row["id"]: row for row in json.loads(
        (MODEL_DATA / "p1p6_stations.json").read_text(encoding="utf-8"))["stations"]}


def defect_placement(record, channel, *, maintenance_preview=False):
    raw = str(record.get("location_raw") or record.get("location") or "")
    text = unicodedata.normalize("NFKC", raw).strip().translate(str.maketrans("\u2212\u2013\u2014", "---"))
    match = re.fullmatch(r"P(?:oint)?\s*([1-6])\s*(?:([+-])\s*([+-]?\d+(?:\.\d+)?))?\s*(?:mm|毫米)?",
                         text, re.IGNORECASE)
    if not match:
        return None
    station = reference_stations()["P" + match[1]]
    distance = channel["L"] if station["fromTop"] == "L" else float(station["fromTop"])
    offset = float(match[3] or 0) * (-1 if match[2] == "-" else 1)
    maintenance = record.get("offset_mm")
    confirmed = (str(record.get("state") or "").lower() == "shifted"
                 and record.get("state_recorded") not in (0, False)
                 and record.get("offset_confirmed") not in (0, False)
                 and maintenance is not None and maintenance != "")
    try:
        maintenance = float(maintenance) if confirmed else 0
        confirmed = confirmed and math.isfinite(maintenance)
    except (TypeError, ValueError):
        confirmed, maintenance = False, 0
    applied = maintenance if confirmed and maintenance_preview else 0
    y = channel["yTop"] - distance - offset - applied
    if not math.isfinite(y):
        return None
    note = (f"{station['id']} {offset:+g} mm；基面{station['status']}；{station['basis']}；"
            "位置示意，非电厂实测标定")
    if applied:
        note += f"；维护后预览：叠加本次移位 {applied:+g} mm"
    return {"y": y, "zone": station["id"], "offset_mm": offset,
            "effective_offset_mm": offset + applied, "status": station["status"],
            "basis": station["basis"], "schematic": True, "calibrated": False,
            "maintenance_applied": bool(applied), "note": note}


def scene_data(data, *, maintenance_preview=False):
    channels = {channel["pos"]: channel for channel in reference_layout()["channels"]}
    colors = {"defect": "#bc493c", "incomplete": "#d18b22", "ndd": "#27816b", "missing": "#87949a"}
    labels = {"defect": "存在缺陷", "incomplete": "待复核", "ndd": "NDD", "missing": "无记录"}
    rows, tubes, positions = {}, [], set()
    for row in data.get("plate") or []:
        position = str(row.get("position") or "").upper()
        channel = channels.get(position)
        number = int(row.get("tube") or 0)
        if not channel or not 1 <= number <= 50 or number in rows or position in positions:
            raise ValueError("管板编号或位置无效，未显示数据")
        positions.add(position)
        category = ("defect" if row.get("defects") else "ndd" if row.get("ndd")
                    else "incomplete" if row.get("records") else "missing")
        rows[number] = {**row, "category_label": labels[category], "channel_geometry": channel}
        tubes.append({"tube": number, "x": channel["x"], "z": channel["z"],
                      "yBase": channel["yBase"], "length": channel["L"], "color": colors[category],
                      "category": category, "type": channel["type"], "position": position})
    if len(tubes) != 50:
        raise ValueError("管板数据不完整，未显示数据")
    defects, details, unresolved = [], {}, []
    for record in data.get("records") or []:
        try:
            number = int(record.get("thimble_id") or 0)
        except (TypeError, ValueError):
            continue
        if number not in rows:
            continue
        channel = rows[number]["channel_geometry"]
        placement = defect_placement(record, channel, maintenance_preview=maintenance_preview)
        details.setdefault(number, []).append({**record, "placement": placement})
        if record.get("category") != "defect":
            continue
        if placement is None:
            unresolved.append(record)
            continue
        defects.append({"tube": number, "id": record.get("id"), "x": channel["x"], "z": channel["z"],
                        "y": placement["y"], "yBase": channel["yBase"], "length": channel["L"],
                        "position": channel["pos"], "note": placement["note"]})
    return rows, tubes, defects, details, unresolved
