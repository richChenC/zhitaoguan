"""Qt Quick 3D geometry loaded from the preserved reference model meshes."""
from __future__ import annotations

from array import array
from functools import lru_cache
import json
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
        self.setStride(32 if value == "plateOverlay" else 24)
        self.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
        attribute = QQuick3DGeometry.Attribute
        self.addAttribute(attribute.Semantic.PositionSemantic, 0, attribute.ComponentType.F32Type)
        self.addAttribute(attribute.Semantic.NormalSemantic, 12, attribute.ComponentType.F32Type)
        if value == "plateOverlay":
            self.addAttribute(attribute.Semantic.TexCoord0Semantic, 24, attribute.ComponentType.F32Type)
        self.addAttribute(attribute.Semantic.IndexSemantic, 0, attribute.ComponentType.U32Type)
        self.setBounds(QVector3D(*bounds[0]), QVector3D(*bounds[1]))
        self.update()
        self.partChanged.emit()

    partId = Property(str, get_part, set_part, notify=partChanged)


_registered = False


def register_geometry():
    global _registered
    if not _registered:
        from .native_plate_texture import PlateTextureData
        qmlRegisterType(ReferenceGeometry, "Thimble.Native", 1, 0, "ReferenceGeometry")
        qmlRegisterType(PlateTextureData, "Thimble.Native", 1, 0, "PlateTextureData")
        _registered = True
