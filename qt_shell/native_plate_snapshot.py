"""Render the reference plate export directly into a native 1500x1390 image."""
from __future__ import annotations

from collections import Counter
import math
import re
import struct

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen, QRawFont

from .native_components import canonical_site
from .native_workbench_table import finding_scope


def selected_statistics(rows):
    defects = [row for row in rows
               if str(row.get("display_conclusion") or row.get("indication") or "").upper() != "NDD"
               and row.get("detection_status") != "ndd" and (row.get("percent") or 0) > 0]
    maximums = {}
    zones = Counter()
    for row in defects:
        key = (int(row["unit_id"]), int(row["thimble_id"]))
        maximums[key] = max(maximums.get(key, 0), float(row["percent"]))
        match = re.search(r"P[1-6]", row.get("location") or "", re.I)
        zones[match[0].upper() if match else "未标注"] += 1
    dense, count = sorted(zones.items(), key=lambda item: (-item[1], item[0]))[0] if zones else ("/", 0)
    return {"records": len(rows), "tube_maximums": maximums,
            "max_percent": max(maximums.values(), default=0), "dense": dense, "dense_count": count}


def create_plate_snapshot(rows, channels, levels, colors):
    rows = list(rows)
    if not rows:
        raise ValueError("请先勾选需要导出的检测记录")
    if len({finding_scope(row) for row in rows}) != 1:
        raise ValueError("缺陷分布图只能导出同一基地、同一机组、同一次大修的数据")
    unit = int(rows[0]["unit_id"])
    site = canonical_site(rows[0].get("site_code") or re.sub(r"\d.*", "", rows[0]["outage"]))
    outage = str(rows[0]["outage"])
    stats = selected_statistics(rows)
    image = QImage(1500, 1390, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#ffffff"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    font = QFont("Microsoft YaHei")
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)

    def text(value, x, y, size, color, bold=False, align=Qt.AlignmentFlag.AlignLeft, width=1300):
        font.setPixelSize(size)
        font.setWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(color))
        metrics = QFontMetricsF(font)
        raw_font = QRawFont.fromFont(font)
        table = bytes(raw_font.fontTable("OS/2"))
        # Canvas middle baseline uses the normalized typographic em box.
        offset = (metrics.ascent() - metrics.descent()) / 2
        if len(table) >= 72:
            ascent, descent = struct.unpack_from(">hh", table, 68)
            if ascent > 0 and descent <= 0:
                offset = round(size * (ascent + descent) / (2 * (ascent - descent)) * 64) / 64
        advance = metrics.horizontalAdvance(str(value))
        if align & Qt.AlignmentFlag.AlignHCenter:
            x += (width - advance) / 2
        elif align & Qt.AlignmentFlag.AlignRight:
            x += width - advance
        painter.drawText(QPointF(x, y + offset), str(value))

    def arrow(x1, y1, x2, y2):
        angle = math.atan2(y2 - y1, x2 - x1)
        painter.setPen(QPen(QColor("#263a43"), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        path = QPainterPath(QPointF(x2, y2))
        path.lineTo(x2 - 16 * math.cos(angle - math.pi / 6), y2 - 16 * math.sin(angle - math.pi / 6))
        path.lineTo(x2 - 16 * math.cos(angle + math.pi / 6), y2 - 16 * math.sin(angle + math.pi / 6))
        path.closeSubpath()
        painter.fillPath(path, QColor("#263a43"))

    text("指套管缺陷分布图", 90, 70, 42, "#1d2b31", True)
    text(f"{site}基地 · {unit}号机组 · {outage} · 当前勾选 {len(rows)} 条记录",
         90, 120, 24, "#5b6971")
    columns = "RPNMLKJHGFEDCBA"
    widths = (3, 7, 9, 11, 13, 13, 15, 15, 15, 13, 13, 11, 9, 7, 3)
    cell, left, top = 62, 260, 190
    for row, width in enumerate(widths):
        for column in range((15 - width) // 2, (15 + width) // 2):
            painter.fillRect(QRectF(left + column * cell, top + row * cell, cell, cell), QColor("#fbfcfc"))
            painter.setPen(QPen(QColor("#9aa5ad"), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(left + column * cell, top + row * cell, cell, cell))
    for column, label in enumerate(columns):
        text(label, left + column * cell, top - 24, 18, "#52616c", True,
             Qt.AlignmentFlag.AlignCenter, cell)
    for row in range(15):
        text(f"{row + 1:02}", left - 60, top + (row + .5) * cell, 18, "#52616c", True,
             Qt.AlignmentFlag.AlignRight, 42)
    field = "serialOdd" if unit % 2 else "serialEven"
    for channel in channels:
        tube = int(channel[field])
        position = re.fullmatch(r"([A-Z])(\d+)", channel["pos"])
        x = left + (columns.index(position[1]) + .5) * cell
        y = top + (int(position[2]) - .5) * cell
        value = stats["tube_maximums"].get((unit, tube), 0)
        color = colors[sum(value >= level for level in levels)] if value > 0 else "#ffffff"
        painter.setPen(QPen(QColor("#24313a" if value > 0 else "#6f7b82"), 4 if value > 0 else 2))
        painter.setBrush(QColor(color))
        painter.drawEllipse(QPointF(x, y), 21, 21)
        text(tube, x - 21, y + 1, 15, "#17252c", True, Qt.AlignmentFlag.AlignCenter, 42)
    center_x, center_y = left + 7.5 * cell, top + 7 * cell
    for value, x, y in (("180°", center_x, top - 58), ("90°", left - 105, center_y + 29),
                        ("OUTLET", left + 15 * cell + 105, center_y - 29),
                        ("270°", left + 15 * cell + 105, center_y + 29),
                        ("INLET", left + 13.15 * cell, top + 6),
                        ("0°", center_x, top + 15 * cell + 72)):
        text(value, x - 65, y, 18, "#263a43", True, Qt.AlignmentFlag.AlignCenter, 130)
    arrow(left - 150, center_y, left - 60, center_y)
    arrow(left + 15 * cell + 60, center_y, left + 15 * cell + 150, center_y)
    arrow(left + 12.7 * cell, top + 2, left + 11.8 * cell, top + 50)
    arrow(left + 3.2 * cell, top + 50, left + 2.3 * cell, top + 2)
    arrow(left + 3.2 * cell, top + 15 * cell - 50, left + 2.3 * cell, top + 15 * cell - 2)
    arrow(left + 12.7 * cell, top + 15 * cell - 2, left + 11.8 * cell, top + 15 * cell - 50)
    painter.fillRect(QRectF(90, 1220, 1320, 92), QColor("#eef2f3"))
    text(f"缺陷管 {len(stats['tube_maximums'])} 根", 125, 1260, 22, "#263840", True)
    maximum = f"{stats['max_percent']:g}%" if stats["max_percent"] else "/"
    text(f"最大磨损 {maximum}", 440, 1260, 22, "#263840", True)
    dense = stats["dense"] + (f"（{stats['dense_count']}条）" if stats["dense_count"] else "")
    text(f"密集区域 {dense}", 790, 1260, 22, "#263840", True)
    grade = " · ".join(f"{level}%" for level in levels)
    if len(levels) == 2:
        grade = f"一级 < {levels[0]}% · 二级 {levels[0]}-{levels[1]}% · 三级 ≥ {levels[1]}%"
    text(f"分级：{grade}", 125, 1294, 16, "#68767f")
    painter.end()
    return image, {"site": site, "unit": unit, "outage": outage, **stats}
