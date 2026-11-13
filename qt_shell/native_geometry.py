"""Qt Quick 3D geometry loaded from the preserved reference model meshes."""
from __future__ import annotations

from array import array
from functools import lru_cache
import json
import math
from pathlib import Path

from PySide6.QtCore import QByteArray, Property, Signal
from PySide6.QtGui import QVector3D
from PySide6.QtQml import qmlRegisterType
from PySide6.QtQuick3D import QQuick3DGeometry

from .native_model_data import MODEL_DATA, reference_layout


@lru_cache(maxsize=1)
def model_parts():
    data = json.loads((MODEL_DATA / "thimble_assembly.json").read_text(encoding="utf-8"))
    structure = json.loads((Path(__file__).with_name("model_assets") / "structure.json").read_text(encoding="utf-8"))
    return {part["id"]: part for part in data["parts"] + structure["parts"]}


@lru_cache(maxsize=160)
def geometry_data(part_id):
    if part_id in ("detail-grid", "detail-axes"):
        vertices = array("f")
        if part_id == "detail-grid":
            def linear(value):
                return value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4

            for step in range(21):
                coordinate = -200 + step * 20
                color = tuple(linear(int(value, 16) / 255)
                              for value in (("c9", "d7", "e6") if step == 10 else ("e4", "ec", "f5")))
                for point in ((-200, 0, coordinate), (200, 0, coordinate),
                              (coordinate, 0, -200), (coordinate, 0, 200)):
                    vertices.extend((*point, 0, 1, 0, *color, 1))
            bounds = ([-200, 0, -200], [200, 0, 200])
        else:
            for point, color in (
                ((0, 0, 0), (1, 0, 0)), ((90, 0, 0), (1, .6, 0)),
                ((0, 0, 0), (0, 1, 0)), ((0, 90, 0), (.6, 1, 0)),
                ((0, 0, 0), (0, 0, 1)), ((0, 0, 90), (0, .6, 1)),
            ):
                vertices.extend((*point, 0, 1, 0, *color, 1))
            bounds = ([0, 0, 0], [90, 90, 90])
        return vertices.tobytes(), array("I", range(len(vertices) // 10)).tobytes(), bounds
    if part_id in ("station-ring", "station-ring-enlarged"):
        radius, thickness = (27, 1.2) if part_id.endswith("-enlarged") else (6.6, .55)
        vertices, indices = array("f"), array("I")
        for i in range(49):
            angle = i * math.tau / 48
            for j in range(9):
                radial = j * math.tau / 8
                nx, ny, nz = math.cos(radial)*math.cos(angle), math.sin(radial), math.cos(radial)*math.sin(angle)
                vertices.extend((radius*math.cos(angle)+thickness*nx, thickness*ny,
                                 radius*math.sin(angle)+thickness*nz, nx, ny, nz))
        for i in range(48):
            for j in range(8):
                a = i*9+j
                indices.extend((a, a+9, a+1, a+1, a+9, a+10))
        edge = radius + thickness
        return vertices.tobytes(), indices.tobytes(), ([-edge, -thickness, -edge], [edge, thickness, edge])
    if part_id == "plateOverlay":
        from .native_plate_texture import plate_corners
        points = plate_corners()
        vertices = array("f")
        for point, uv in zip(points, ((0, 0), (1, 0), (0, 1), (1, 1))):
            vertices.extend((*point, 0, 1, 0, *uv))
        bounds = ([min(point[j] for point in points) for j in range(3)],
                  [max(point[j] for point in points) for j in range(3)])
        return vertices.tobytes(), array("I", (0, 1, 2, 2, 1, 3)).tobytes(), bounds
    if part_id == "dome":
        part = json.loads((MODEL_DATA / "dome.json").read_text(encoding="utf-8"))
    else:
        part = model_parts()[part_id]
    positions, indices = part["positions"], part["indices"]
    normals = part.get("normals") or []
    if len(normals) != len(positions):
        normals = [0.] * len(positions)
        for i in range(0, len(indices), 3):
            a, b, c = (indices[i + j] * 3 for j in range(3))
            u = [positions[b + j] - positions[a + j] for j in range(3)]
            v = [positions[c + j] - positions[a + j] for j in range(3)]
            normal = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
            for vertex in (a, b, c):
                for j in range(3):
                    normals[vertex + j] += normal[j]
        for i in range(0, len(normals), 3):
            length = sum(value * value for value in normals[i:i+3]) ** .5 or 1
            normals[i:i+3] = [value / length for value in normals[i:i+3]]
    interleaved = array("f")
    for i in range(0, len(positions), 3):
        interleaved.extend(positions[i:i+3])
        interleaved.extend(normals[i:i+3])
    bounds = ([min(positions[j::3]) for j in range(3)], [max(positions[j::3]) for j in range(3)])
    return interleaved.tobytes(), array("I", indices).tobytes(), bounds


class ReferenceGeometry(QQuick3DGeometry):
    partChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._part = ""

    def get_part(self):
        return self._part

    def set_part(self, value):
        if self._part == value:
            return
        self._part = value
        self.clear()
        vertices, indices, bounds = geometry_data(value)
        self.setVertexData(QByteArray(vertices))
        self.setIndexData(QByteArray(indices))
        helper = value in ("detail-grid", "detail-axes")
        self.setStride(40 if helper else 32 if value == "plateOverlay" else 24)
        self.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Lines if helper
                              else QQuick3DGeometry.PrimitiveType.Triangles)
        attribute = QQuick3DGeometry.Attribute
        self.addAttribute(attribute.Semantic.PositionSemantic, 0, attribute.ComponentType.F32Type)
        self.addAttribute(attribute.Semantic.NormalSemantic, 12, attribute.ComponentType.F32Type)
        if value == "plateOverlay":
            self.addAttribute(attribute.Semantic.TexCoord0Semantic, 24, attribute.ComponentType.F32Type)
        if helper:
            self.addAttribute(attribute.Semantic.ColorSemantic, 24, attribute.ComponentType.F32Type)
        self.addAttribute(attribute.Semantic.IndexSemantic, 0, attribute.ComponentType.U32Type)
        self.setBounds(QVector3D(*bounds[0]), QVector3D(*bounds[1]))
        self.update()
        self.partChanged.emit()

    partId = Property(str, get_part, set_part, notify=partChanged)


_registered = False


@lru_cache(maxsize=1)
def vessel_wire_positions():
    data = json.loads((Path(__file__).with_name("model_assets") / "vessel-wire.json").read_text(encoding="utf-8"))
    return tuple(data["positions"])


class VesselWireGeometry(QQuick3DGeometry):
    clipChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active, self._axis, self._offset = False, "x", 0.
        self._rebuild()

    def _set_option(self, name, value):
        if getattr(self, name) != value:
            setattr(self, name, value)
            self._rebuild()
            self.clipChanged.emit()

    def _rebuild(self):
        original = vessel_wire_positions()
        if self._active:
            points = array("f")
            axis = {"x": 0, "y": 1, "z": 2}[self._axis]
            for i in range(0, len(original), 6):
                a, b = original[i:i+3], original[i+3:i+6]
                da, db = a[axis]-self._offset, b[axis]-self._offset
                if da > 0 and db > 0:
                    continue
                if (da > 0) != (db > 0):
                    fraction = da/(da-db)
                    intersection = tuple(a[j]+(b[j]-a[j])*fraction for j in range(3))
                    a, b = (intersection, b) if da > 0 else (a, intersection)
                points.extend((*a, *b))
        else:
            points = array("f", original)
        self.clear()
        self.setVertexData(QByteArray(points.tobytes()))
        self.setStride(12)
        self.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Lines)
        attribute = QQuick3DGeometry.Attribute
        self.addAttribute(attribute.Semantic.PositionSemantic, 0, attribute.ComponentType.F32Type)
        minimum = [min(points[i::3]) if points else 0 for i in range(3)]
        maximum = [max(points[i::3]) if points else 0 for i in range(3)]
        self.setBounds(QVector3D(*minimum), QVector3D(*maximum))
        self.update()

    clipActive = Property(bool, lambda self: self._active,
                          lambda self, value: self._set_option("_active", value), notify=clipChanged)
    clipAxis = Property(str, lambda self: self._axis,
                        lambda self, value: self._set_option("_axis", value), notify=clipChanged)
    clipOffset = Property(float, lambda self: self._offset,
                          lambda self, value: self._set_option("_offset", value), notify=clipChanged)


def register_geometry():
    global _registered
    if not _registered:
        from .native_plate_texture import PlateTextureData
        qmlRegisterType(ReferenceGeometry, "Thimble.Native", 1, 0, "ReferenceGeometry")
        qmlRegisterType(PlateTextureData, "Thimble.Native", 1, 0, "PlateTextureData")
        qmlRegisterType(VesselWireGeometry, "Thimble.Native", 1, 0, "VesselWireGeometry")
        _registered = True
