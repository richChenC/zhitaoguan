"""Compare real mesh cross sections with the reference, including material holes."""
from __future__ import annotations

from array import array
import json
import math
from pathlib import Path
import subprocess
import unittest

import native_test_env
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QVector3D
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from qt_shell.native_sections import SectionGeometry, section_engine


class SectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_cross_sections_match_actual_reference_triangles(self):
        states = [{"part": key, "axis": axis, "offset": offset, "scale": scale}
                  for key in ("P01", "P02", "P03", "P04", "P05", "P06")
                  for axis, offset in (("x", -3), ("x", 0), ("x", 3), ("x", 10000),
                                       ("y", 50), ("z", 0))
                  for scale in ((1, 1, 1), (4, 1.095, 4))]
        process = subprocess.run(
            ["node", str(Path(__file__).with_name("reference_sections.mjs")),
             str(Path(__file__).resolve().parents[3] / "10_TRAEqt优化版"), json.dumps(states)],
            capture_output=True, text=True, encoding="utf-8", check=True)
        expected = json.loads(process.stdout)
        for state, reference in zip(states, expected, strict=True):
            with self.subTest(**state):
                data, faces, _, _, _ = section_engine().mesh(
                    state["part"], state["axis"], state["offset"], state["scale"])
                vertices, indices = array("f"), array("I")
                vertices.frombytes(data)
                indices.frombytes(faces)
                self.assertEqual(len(indices), len(reference["indices"]))
                # The world-plane ShapeGeometry uses (u=z,v=y); native positions are local XYZ.
                axes = {"x": (0, 1, 2), "y": (1, 2, 0), "z": (2, 0, 1)}[state["axis"]]
                self.assertEqual([indices[index+j] for index in range(0, len(indices), 3) for j in (0, 2, 1)],
                                 reference["indices"])
                self.assertEqual(len(vertices)//6, len(reference["positions"])//3)
                for index in range(len(vertices)//6):
                    # Native float32 local coordinates are scaled by the GPU; reference stores world float32.
                    self.assertAlmostEqual(vertices[index*6+axes[2]]*state["scale"][axes[2]],
                                           reference["positions"][index*3], delta=.0003)
                    self.assertAlmostEqual(vertices[index*6+axes[1]]*state["scale"][axes[1]],
                                           reference["positions"][index*3+1], delta=.0003)

    def test_transverse_hollow_tube_preserves_hole_and_area(self):
        data, faces, _, loops, holes = section_engine().mesh("P01", "y", 1000, (1, 1, 1))
        vertices, indices = array("f"), array("I")
        vertices.frombytes(data)
        indices.frombytes(faces)
        self.assertEqual((loops, holes), (2, 1))
        area = 0.
        for index in range(0, len(indices), 3):
            a, b, c = [vertices[indices[index+j]*6:indices[index+j]*6+3] for j in range(3)]
            area += abs((b[0]-a[0])*(c[2]-a[2])-(b[2]-a[2])*(c[0]-a[0]))/2
            center = [(a[j]+b[j]+c[j])/3 for j in (0, 2)]
            self.assertGreater(math.hypot(*center), 2.59)
        self.assertAlmostEqual(area, math.pi*(4.3**2-2.6**2), delta=.05)

    def test_geometry_coalesces_options_and_clears_when_inactive(self):
        geometry = SectionGeometry()
        geometry.partId, geometry.clipAxis, geometry.active = "P01", "y", True
        geometry.partScale = QVector3D(1, 1.1, 1)
        for offset in range(100, 180):
            geometry.clipOffset = offset
        self.assertEqual(geometry.triangleCount, 0)
        for _ in range(300):
            if geometry.triangleCount:
                break
            QTest.qWait(10)
        self.assertGreater(geometry.triangleCount, 0)
        self.assertEqual(geometry.holeCount, 1)
        vertices = array("f")
        vertices.frombytes(bytes(geometry.vertexData()))
        self.assertAlmostEqual(vertices[1]*1.1, 179, places=4)
        geometry.active = False
        QTest.qWait(20)
        self.assertEqual(geometry.triangleCount, 0)
        self.assertEqual(bytes(geometry.vertexData()), b"")
        # A new request followed by hiding must not resurrect an old worker result.
        geometry.active = True
        geometry.clipOffset = 1000
        self.app.processEvents()
        geometry.active = False
        QTest.qWait(150)
        self.assertEqual(geometry.triangleCount, 0)
        geometry.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_cached_section_buffers_are_bounded_and_reused(self):
        engine = section_engine()
        original = engine.mesh("P04", "x", 0, (1, 1, 1))
        self.assertIs(engine.mesh("P04", "x", 0, (1, 1, 1)), original)
        for value in range(60):
            engine.mesh("P05", "x", 1000+value, (1, 1, 1))
        self.assertLessEqual(len(engine.cache), 48)


if __name__ == "__main__":
    unittest.main()
