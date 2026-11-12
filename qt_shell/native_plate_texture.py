"""Render the reference drawing on its authoritative model plane."""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import math
import xml.etree.ElementTree as ET

from PySide6.QtCore import QByteArray, Property, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPainter
from PySide6.QtQuick3D import QQuick3DTextureData
from PySide6.QtSvg import QSvgRenderer

from .native_model_data import MODEL_DATA, reference_layout

NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", NS)


def tag(name):
    return "{" + NS + "}" + name


@lru_cache(maxsize=1)
def plate_mapping():
    drawing = ET.parse(MODEL_DATA / "plate_plan.svg").getroot()
    channels = {row["pos"]: row for row in reference_layout()["channels"]}
    anchors = []
    for group in drawing.findall(tag("g")):
        if group.get("class") != "thimble":
            continue
        circle = group.find(tag("circle"))
        channel = channels.get(group.get("data-pos"))
        if circle is not None and channel:
            anchors.append((float(circle.get("cx")), float(circle.get("cy")), channel))
    if len(anchors) != 50:
        raise ValueError("管板孔位数量不完整")
    p = anchors[0]
    q = next(row for row in anchors if math.hypot(row[0] - p[0], row[1] - p[1]) > 1)
    r = next(row for row in anchors
             if abs((q[0] - p[0]) * (row[1] - p[1]) - (row[0] - p[0]) * (q[1] - p[1])) > 1)
    determinant = (q[0] - p[0]) * (r[1] - p[1]) - (r[0] - p[0]) * (q[1] - p[1])

    def solve(key):
        a = ((q[2][key] - p[2][key]) * (r[1] - p[1]) -
             (r[2][key] - p[2][key]) * (q[1] - p[1])) / determinant
        b = ((q[0] - p[0]) * (r[2][key] - p[2][key]) -
             (r[0] - p[0]) * (q[2][key] - p[2][key])) / determinant
        return a, b, p[2][key] - a * p[0] - b * p[1]

    x, z = solve("x"), solve("z")
    for u, v, channel in anchors:
        if abs(x[0] * u + x[1] * v + x[2] - channel["x"]) > .01 or abs(
                z[0] * u + z[1] * v + z[2] - channel["z"]) > .01:
            raise ValueError("管板图与模型孔位不一致")
    return drawing, x, z, max(row["yTop"] for row in channels.values()) + 18


def plate_corners():
    _drawing, x, z, height = plate_mapping()
    return [(x[0] * u + x[1] * v + x[2], height, z[0] * u + z[1] * v + z[2])
            for u, v in ((0, 96), (1060, 96), (0, 1056), (1060, 1056))]


def plate_svg(unit=0, selected=0):
    original, x, z, _height = plate_mapping()
    drawing = deepcopy(original)
    channels = reference_layout()["channels"]
    selected_position = next((row["pos"] for row in channels if int(
        row["serialOdd" if unit % 2 else "serialEven"]) == selected), "")
    for node in list(drawing):
        kind = node.tag.rsplit("}", 1)[-1]
        u = float(node.get("x", node.get("x1", node.get("cx", 0))))
        v = float(node.get("y", node.get("y1", 96)))
        if node.get("width") == "100%" or not (
                node.get("class") == "thimble" or kind in ("path",) or
                (kind == "rect" and node.get("fill") == "none") or (u <= 1000 and 96 <= v <= 1040)):
            drawing.remove(node)
            continue
        if ((kind == "text" and node.text in ("180°", "90°", "270°", "0°", "INLET", "OUTLET"))
                or (kind == "line" and ((v == 112 and u in (178, 824)) or (u == 914 and v == 678)))
                or (kind == "path" and any(value in (node.get("transform", "") + node.get("d", ""))
                                          for value in ("248.0,158.0", "754.0,158.0", "M960.0,678.0")))):
            drawing.remove(node)
    background = ET.Element(tag("g"), {"opacity": ".5"})
    for node in drawing.findall(tag("rect")):
        if node.get("fill") == "none":
            cell = deepcopy(node)
            cell.set("fill", "#f7fafc")
            cell.set("stroke", "none")
            background.append(cell)
            node.set("stroke", "#516a80")
            node.set("stroke-width", "1.6")
    drawing.insert(0, background)
    marks = ET.SubElement(drawing, tag("g"))
    for u, v, end_u, end_v in ((2, 597, 48, 597), (932, 597, 1000, 597),
                               (265, 240, 230, 190), (772, 190, 737, 240),
                               (265, 950, 230, 1000), (772, 1000, 737, 950)):
        ET.SubElement(marks, tag("line"), {"x1": str(u), "y1": str(v), "x2": str(end_u),
                                          "y2": str(end_v), "stroke": "#263a43", "stroke-width": "3"})
        angle = math.atan2(end_v - v, end_u - u)
        points = f"{end_u},{end_v} " + " ".join(
            f"{end_u - 13 * math.cos(angle + turn)},{end_v - 13 * math.sin(angle + turn)}"
            for turn in (-.45, .45))
        ET.SubElement(marks, tag("polygon"), {"points": points, "fill": "#263a43"})
    for text, u, v in (("180°", 501, 112), ("0°", 501, 1034), ("90°", 25, 630),
                        ("270°", 966, 630), ("INLET", 810, 190), ("OUTLET", 966, 580)):
        ET.SubElement(marks, tag("text"), {"x": str(u), "y": str(v), "text-anchor": "middle",
                                         "font-family": "Arial", "font-size": "17",
                                         "font-weight": "700", "fill": "#263a43"}).text = text
    for group in drawing.findall(tag("g")):
        if group.get("class") != "thimble":
            continue
        circle = group.find(tag("circle"))
        labels = group.findall(tag("text"))
        if unit:
            keep = labels[0 if unit % 2 else 1]
            for node in labels:
                if node is not keep:
                    group.remove(node)
            line = group.find(tag("line"))
            if line is not None:
                group.remove(line)
            keep.set("x", circle.get("cx"))
            keep.set("font-size", "21")
            keep.set("font-weight", "700")
        if group.get("data-pos") == selected_position:
            circle.set("fill", "#ffe09b")
            circle.set("stroke", "#b35e00")
            circle.set("stroke-width", "4")
    if x[0] * z[1] - x[1] * z[0] < 0:
        for text in drawing.iter(tag("text")):
            text.set("transform", f"translate({2 * float(text.get('x', 0))} 0) scale(-1 1)")
    drawing.set("viewBox", "0 96 1060 960")
    drawing.set("width", "2120")
    drawing.set("height", "1920")
    return ET.tostring(drawing, encoding="utf-8")


def plate_image(unit, selected):
    image = QImage(QSize(2120, 1920), QImage.Format.Format_RGBA8888)
    image.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(plate_svg(unit, selected)))
    painter = QPainter(image)
    renderer.render(painter, QRectF(0, 0, 2120, 1920))
    painter.end()
    return image


class PlateTextureData(QQuick3DTextureData):
    optionsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._unit, self._selected, self._active = 0, 0, False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self._render)

    def _set_option(self, name, value):
        if getattr(self, name) != value:
            setattr(self, name, value)
            if self._active:
                self.timer.start()
            self.optionsChanged.emit()

    def _render(self):
        if not self._active:
            return
        image = plate_image(self._unit, self._selected)
        self.setSize(image.size())
        self.setFormat(QQuick3DTextureData.Format.RGBA8)
        self.setHasTransparency(True)
        self.setTextureData(QByteArray(image.constBits().tobytes()))
        self.update()

    unitNumber = Property(int, lambda self: self._unit,
                          lambda self, value: self._set_option("_unit", value), notify=optionsChanged)
    selectedTube = Property(int, lambda self: self._selected,
                            lambda self, value: self._set_option("_selected", value), notify=optionsChanged)
    active = Property(bool, lambda self: self._active,
                      lambda self, value: self._set_option("_active", value), notify=optionsChanged)
