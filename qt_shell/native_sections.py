"""Actual mesh cross sections, triangulated with the reference Earcut in Qt."""
from __future__ import annotations

from array import array
from collections import OrderedDict
import atexit
import base64
from itertools import count
import json
import math
from pathlib import Path
import sys
import weakref

from PySide6.QtCore import QByteArray, QCoreApplication, QObject, Property, QProcess, QTimer, Signal, qWarning
from PySide6.QtGui import QVector3D
from PySide6.QtQml import QJSEngine
from PySide6.QtQuick3D import QQuick3DGeometry
from shiboken6 import isValid


ASSETS = Path(__file__).with_name("model_assets")
_identities = count()


class SectionEngine(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        from .native_geometry import model_parts
        self.engine = QJSEngine(self)
        self.parts = self.engine.toScriptValue({
            key: {"positions": array("f", part["positions"]).tolist(), "indices": part["indices"]}
            for key, part in model_parts().items() if key in ("P01", "P02", "P03", "P04", "P05", "P06")
        })
        source = "\n".join((ASSETS / filename).read_text(encoding="utf-8")
                           for filename in ("earcut.js", "section-loops.js", "section-mesh.js"))
        value = self.engine.evaluate(source, "native-section-algorithms.js")
        if value.isError():
            raise RuntimeError(value.toString())
        self.function = self.engine.globalObject().property("sectionMesh")
        self.cache = OrderedDict()

    def mesh(self, part_id, axis, offset, scale):
        key = (part_id, axis, offset, tuple(scale))
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        part = self.parts.property(part_id)
        if part.isUndefined():
            raise ValueError(f"Unsupported section part: {part_id}")
        result = self.function.call([part, self.engine.toScriptValue(axis),
                                     self.engine.toScriptValue(offset), self.engine.toScriptValue(list(scale))])
        if result.isError():
            raise RuntimeError(result.toString())
        mesh = result.toVariant()
        positions, indices, normal = mesh["positions"], mesh["indices"], mesh["normal"]
        if (len(positions) % 3 or len(indices) % 3 or
                any(not math.isfinite(value) for value in positions) or
                any(index < 0 or index >= len(positions)//3 for index in indices)):
            raise ValueError("Section triangulation returned invalid vertices or faces")
        vertices = array("f")
        for index in range(0, len(positions), 3):
            vertices.extend((*positions[index:index+3], *normal))
        bounds = ([min(positions[j::3]) if positions else 0 for j in range(3)],
                  [max(positions[j::3]) if positions else 0 for j in range(3)])
        data = (vertices.tobytes(), array("I", indices).tobytes(), bounds, mesh["loops"], mesh["holes"])
        self.cache[key] = data
        while len(self.cache) > 48:
            self.cache.popitem(last=False)
        return data


def section_engine():
    app = QCoreApplication.instance()
    if app is None:
        raise RuntimeError("Sections require a running Qt application")
    if not hasattr(app, "_thimble_sections"):
        app._thimble_sections = SectionEngine(app)
    return app._thimble_sections


class SectionService(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.pending, self.targets = {}, {}
        self.busy, self.stopped = False, False
        self.inflight, self.buffer, self.stderr = [], b"", ""
        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(Path(__file__).resolve().parents[1]))
        self.process.started.connect(self._dispatch)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.readyReadStandardError.connect(self._read_errors)
        self.process.errorOccurred.connect(lambda _error: self._failed(self.process.errorString()))
        self.process.finished.connect(lambda code, _status: self._failed(f"Section process exited: {code}"))
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._dispatch)
        app.aboutToQuit.connect(self.shutdown)
        atexit.register(self.shutdown)

    def request(self, geometry, revision, options):
        identity = geometry._identity
        self.targets[identity] = weakref.ref(geometry)
        self.pending[identity] = (revision, options)
        if not self.busy:
            self.timer.start()

    def _dispatch(self):
        if self.stopped or self.busy or not self.pending:
            return
        if self.process.state() == QProcess.ProcessState.NotRunning:
            self.buffer = b""
            args = (["--native-section-worker"] if getattr(sys, "frozen", False)
                    else ["-m", "qt_shell.native_section_worker"])
            self.process.start(sys.executable, args)
            return
        if self.process.state() != QProcess.ProcessState.Running:
            return
        jobs = []
        for identity, (revision, options) in self.pending.items():
            target = self.targets[identity]()
            if target is not None and isValid(target) and target._revision == revision:
                jobs.append((identity, revision, options))
        self.pending.clear()
        if jobs:
            self.busy = True
            self.inflight = jobs
            self.process.write((json.dumps(jobs) + "\n").encode("ascii"))

    def _completed(self, results):
        if self.stopped:
            return
        self.busy = False
        self.inflight = []
        for identity, revision, data, error in results:
            target = self.targets.get(identity, lambda: None)()
            if target is not None and isValid(target) and target._revision == revision:
                target._apply(data, error)
        self.targets = {key: value for key, value in self.targets.items()
                        if value() is not None and isValid(value())}
        self._dispatch()

    def _read_errors(self):
        self.stderr = (self.stderr + bytes(self.process.readAllStandardError()).decode("utf-8", "replace"))[-8192:]

    def _read(self):
        self.buffer += bytes(self.process.readAllStandardOutput())
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            try:
                results = json.loads(line)
                decoded = []
                for identity, revision, data, error in results:
                    if data is not None:
                        data = (base64.b64decode(data[0]), base64.b64decode(data[1]), *data[2:])
                    decoded.append((identity, revision, data, error))
                self._completed(decoded)
            except (ValueError, TypeError, IndexError) as error:
                self._failed(f"Invalid section response: {error}")

    def _failed(self, error):
        if self.stopped:
            return
        jobs = self.inflight + [(identity, revision, options)
                                for identity, (revision, options) in self.pending.items()]
        self.inflight, self.pending, self.busy = [], {}, False
        for identity, revision, _options in jobs:
            target = self.targets.get(identity, lambda: None)()
            if target is not None and isValid(target) and target._revision == revision:
                target._apply(None, error + ("\n" + self.stderr if self.stderr else ""))

    def shutdown(self):
        if self.stopped or not isValid(self.process):
            return
        self.stopped = True
        self.pending.clear()
        self.process.closeWriteChannel()
        if not self.process.waitForFinished(3000):
            self.process.terminate()
            if not self.process.waitForFinished(1000):
                self.process.kill()
                self.process.waitForFinished(1000)


def section_service():
    app = QCoreApplication.instance()
    if app is None:
        raise RuntimeError("Sections require a running Qt application")
    if not hasattr(app, "_thimble_section_service"):
        app._thimble_section_service = SectionService(app)
    return app._thimble_section_service


class SectionGeometry(QQuick3DGeometry):
    optionsChanged = Signal()
    meshChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._part, self._axis, self._offset = "", "x", 0.
        self._scale, self._active = QVector3D(1, 1, 1), False
        self._triangles, self._loops, self._holes = 0, 0, 0
        self._revision = 0
        self._identity = next(_identities)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._rebuild)

    def _set_option(self, name, value):
        if getattr(self, name) != value:
            setattr(self, name, value)
            self._revision += 1
            self._timer.start()
            self.optionsChanged.emit()

    def _rebuild(self):
        self.clear()
        self._triangles, self._loops, self._holes = 0, 0, 0
        self.update()
        self.meshChanged.emit()
        scale = (self._scale.x(), self._scale.y(), self._scale.z())
        if self._active and self._part and self._axis in ("x", "y", "z") and all(
                math.isfinite(value) and value > 0 for value in scale) and math.isfinite(self._offset):
            section_service().request(self, self._revision, (self._part, self._axis, self._offset, scale))

    def _apply(self, data, error):
        if error:
            qWarning(f"Native section generation failed: {error}")
            return
        vertices, indices, bounds, self._loops, self._holes = data
        self.setVertexData(QByteArray(vertices))
        self.setIndexData(QByteArray(indices))
        self.setStride(24)
        self.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
        attribute = QQuick3DGeometry.Attribute
        self.addAttribute(attribute.Semantic.PositionSemantic, 0, attribute.ComponentType.F32Type)
        self.addAttribute(attribute.Semantic.NormalSemantic, 12, attribute.ComponentType.F32Type)
        self.addAttribute(attribute.Semantic.IndexSemantic, 0, attribute.ComponentType.U32Type)
        self.setBounds(QVector3D(*bounds[0]), QVector3D(*bounds[1]))
        self._triangles = len(indices)//12
        self.update()
        self.meshChanged.emit()

    partId = Property(str, lambda self: self._part,
                      lambda self, value: self._set_option("_part", value), notify=optionsChanged)
    clipAxis = Property(str, lambda self: self._axis,
                        lambda self, value: self._set_option("_axis", value), notify=optionsChanged)
    clipOffset = Property(float, lambda self: self._offset,
                          lambda self, value: self._set_option("_offset", value), notify=optionsChanged)
    partScale = Property(QVector3D, lambda self: self._scale,
                         lambda self, value: self._set_option("_scale", value), notify=optionsChanged)
    active = Property(bool, lambda self: self._active,
                      lambda self, value: self._set_option("_active", value), notify=optionsChanged)
    triangleCount = Property(int, lambda self: self._triangles, notify=meshChanged)
    loopCount = Property(int, lambda self: self._loops, notify=meshChanged)
    holeCount = Property(int, lambda self: self._holes, notify=meshChanged)
