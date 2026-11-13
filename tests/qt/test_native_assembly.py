"""Actual reference assembly captures and native persistent mesh buffers."""
from __future__ import annotations

from array import array
import json
from pathlib import Path
import subprocess
import unittest

import native_test_env
from qt_shell.native_geometry import assembly_caps, geometry_data, model_parts
from qt_shell.native_model_data import reference_layout


class AssemblyTests(unittest.TestCase):
    def test_caps_match_actual_reference_vertices_indices_and_materials(self):
        root = Path(native_test_env.test_data.name)
        caps_path, geometry_path = root / "assembly-caps.json", root / "assembly-surfaces.json"
        subprocess.run(
            ["node", str(Path(__file__).with_name("capture_reference_assembly.mjs")),
             str(Path(__file__).resolve().parents[3] / "10_TRAEqt优化版"), str(caps_path), str(geometry_path)],
            check=True, capture_output=True, encoding="utf-8")
        expected = json.loads(caps_path.read_text(encoding="utf-8"))
        self.assertEqual(assembly_caps(), expected["parts"])
        self.assertEqual(expected["summary"], {"capCount": 13, "capColumns": 8,
                                                "plateHoles": 192, "assemblyMeshes": 100})
        for part in assembly_caps():
            data, faces, _bounds = geometry_data(part["id"])
            values, indices = array("f"), array("I")
            values.frombytes(data)
            indices.frombytes(faces)
            self.assertEqual(indices.tolist(), part["indices"])
            self.assertEqual([values[i+j] for i in range(0, len(values), 6) for j in range(3)],
                             part["positions"])
            self.assertTrue(all(abs(values[i]+.4) < 1e-7 for i in range(0, len(values), 6)))
        surfaces = json.loads(geometry_path.read_text(encoding="utf-8"))["parts"]
        for number in range(len(reference_layout()["structure"]["columns"])):
            expected_positions, expected_normals, expected_indices = [], [], []
            for surface in surfaces:
                if surface["kind"] != "column" or surface["column"] != number:
                    continue
                offset = len(expected_positions)//3
                expected_positions.extend(surface["positions"])
                expected_normals.extend(surface["normals"])
                expected_indices.extend(index+offset for index in surface["indices"])
            key = f"column-{number}"
            part = model_parts()[key]
            self.assertEqual(part["positions"], expected_positions, key)
            self.assertEqual(part["normals"], expected_normals, key)
            self.assertEqual(part["indices"], expected_indices, key)
        caps_path.unlink()
        geometry_path.unlink()

    def test_assembly_cap_groups_and_column_surfaces_are_complete(self):
        from collections import Counter
        self.assertEqual(Counter(part["target"] for part in assembly_caps()),
                         {"vessel": 1, "plate": 4, "column": 8})
        self.assertEqual(Counter(part["columnType"] for part in assembly_caps() if part["target"] == "column"),
                         {"core-hollow": 2, "core-solid": 4, "sec-hollow": 1, "sec-solid": 1})
        for index, column in enumerate(reference_layout()["structure"]["columns"]):
            part = model_parts()[f"column-{index}"]
            self.assertEqual(len(part["indices"])//3, 72)
            self.assertEqual(len(part["positions"])//3, 76 if column.get("bore") else 112)


if __name__ == "__main__":
    unittest.main()
