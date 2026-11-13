"""Compare live native render state with a capture of the actual reference scene."""
from array import array
import hashlib
import json
import math
from pathlib import Path
import time

from PySide6.QtCore import QObject, QTimer, Qt, QUrl
from PySide6.QtGui import QVector3D
from PySide6.QtTest import QTest


def verify_render_materials(page, root, work, capture_path, wait, pixels):
    reference = json.loads(Path(capture_path).read_text(encoding="utf-8-sig"))
    project = Path(__file__).resolve().parents[2]
    page.resize(1480, 920)
    page.mode_tabs.setCurrentIndex(0)
    page.section.setChecked(False)
    page.explode.setValue(0)
    page.scene_settings_button.setChecked(False)
    page.data_details_button.setChecked(False)
    page._hide_part_info()
    page._reset_three_d_view()
    wait(250)
    checked_materials = []

    def material(name, expected):
        node = root.findChild(QObject, name)
        assert node, name
        for field, value in expected.items():
            actual = node.property(field)
            if isinstance(value, str):
                actual = actual.name()
                assert actual.lower() == value.lower(), (name, field, actual, value)
            else:
                assert math.isclose(actual, value, abs_tol=1e-6), (name, field, actual, value)
        checked_materials.append(name)
        return node

    def source_material(part, kind):
        return next(item for item in reference["materials"] if item["id"] == part and item.get("kind") == kind)

    def values(source):
        return {"tint": "#" + source["color"], "roughnessValue": source["roughness"],
                "metalnessValue": source["metalness"], "alphaValue": source["opacity"]}

    lights = []
    for name, source in zip(("Key", "Fill", "Rim"), reference["lights"][:3], strict=True):
        light = root.findChild(QObject, "reference" + name + "Light")
        assert light and light.property("color").name() == "#" + source["color"]
        assert math.isclose(light.property("brightness"), source["intensity"], abs_tol=1e-6)
        direction = light.property("sceneRotation").rotatedVector(QVector3D(0, 0, -1))
        expected = -QVector3D(*source["position"]).normalized()
        assert (direction - expected).length() < 1e-6, (name, direction, expected)
        lights.append({"name": name, "direction": direction.toTuple(), "intensity": source["intensity"]})
    ambient = root.findChild(QObject, "referenceAmbientLight").property("ambientColor").redF()
    ambient_linear = ((ambient + .055) / 1.055) ** 2.4
    assert math.isclose(ambient_linear, reference["lights"][3]["intensity"], abs_tol=3e-5)
    assert root.property("renderExposure") == reference["exposure"]
    environment = root.findChild(QObject, "referenceEnvironment")
    probe = environment.findChild(QObject, "referenceProbeTexture")
    image_path = QUrl.fromLocalFile(str(project / "qt_shell/native_model.qml")).resolved(
        probe.property("source")).toLocalFile()
    expected_path = project / "qt_shell/assets/reference-neutral-environment.png"
    assert Path(image_path).resolve() == expected_path.resolve(), image_path
    assert hashlib.sha256(Path(image_path).read_bytes()).digest() == hashlib.sha256(
        Path(capture_path).with_name("reference-neutral-environment.png").read_bytes()).digest()
    material("vesselMaterial", values(source_material("PRV", "vessel")))
    material("domeMaterial", values(source_material("RPV_DOME", "dome")))
    for key in ("ucsPlate", "secondaryGrid"):
        material("plateMaterial-" + key, values(source_material("UCS", "structure")))
    for column in root.property("columns"):
        source = next(item for item in reference["materials"] if item.get("columnType") == column["type"])
        material("columnMaterial-" + column["meshId"], values(source))
    for tube in root.property("tubes"):
        number = str(tube["tube"])
        source = source_material("TUBES", "tubes")
        material("tubeMaterial-" + number, {
            "roughnessValue": source["roughness"], "metalnessValue": source["metalness"],
            "emissiveTint": "#" + source["emissive"], "emissiveIntensity": source["emissiveIntensity"],
            "alphaValue": source["opacity"]})
        material("socketMaterial-" + number, values(source_material("P02", "part")))
        material("penetrationMaterial-" + number, values(source_material("P05", "part")))
    for source in reference["materials"]:
        if source["id"] not in ("P01", "P02", "P03", "P04", "P05", "P06") or source.get("kind") == "part":
            continue
        material("detailMaterial-" + source["id"], values(source))

    wire = root.findChild(QObject, "vesselWire")
    wire_geometry = root.findChild(QObject, "vesselWireGeometry")
    original = array("f", reference["vesselWire"]["positions"]).tobytes()
    assert bytes(wire_geometry.vertexData()) == original
    for axis, offset_index in (("x", 0), ("y", 1), ("z", 2)):
        page.section_axis.setCurrentIndex(page.section_axis.findData(axis))
        page.section.setChecked(True)
        wait(100)
        clipped = array("f", bytes(wire_geometry.vertexData()))
        assert clipped and max(clipped[offset_index::3]) <= .001, axis
        assert len(clipped) < len(original) // 4
        page.section.setChecked(False)
    page.section_axis.setCurrentIndex(0)
    assert bytes(wire_geometry.vertexData()) == original
    page._reset_three_d_view()
    wait(200)
    wire_material = root.findChild(QObject, "vesselWireMaterial")
    assert wire_material.property("diffuseColor").name() == reference["vesselWire"]["color"]
    assert math.isclose(wire_material.property("opacity"), reference["vesselWire"]["opacity"], abs_tol=1e-6)
    present = pixels(page.view.grabWindow(), 1)
    wire_material.setProperty("opacity", 0.)
    wait(150)
    absent = pixels(page.view.grabWindow(), 1)
    wire_change = sum(a != b for a, b in zip(present, absent))
    assert wire_change > 100, ("Wire not rendered", wire_change)
    wire_material.setProperty("opacity", .18)
    page.visibility_checks["showVessel"].setChecked(False)
    assert not wire.property("visible")
    page.visibility_checks["showVessel"].setChecked(True)
    assert wire.property("visible")

    penetrations = [root.findChild(QObject, "penetration-" + str(tube["tube"])) for tube in root.property("tubes")]
    assert len(penetrations) == 50 and all(node and node.property("visible") for node in penetrations)
    wait(250)
    present = pixels(page.view.grabWindow(), 1)
    # Scan real render targets; properties alone cannot establish geometry visibility or picking.
    targets = [(x, y) for y in range(0, page.view.height(), 5) for x in range(0, page.view.width(), 5)
               if root.pickPart(x, y) == "P05"]
    assert targets, "Assembly penetrations have no actual pick targets"
    checkbox = page.visibility_checks["showPenetrations"]
    page.scene_settings_button.setChecked(True)
    page.scene_settings_host.ensureWidgetVisible(checkbox)
    wait(100)
    QTest.mouseClick(checkbox, Qt.MouseButton.LeftButton)
    assert not root.property("showPenetrations") and all(not node.property("visible") for node in penetrations)
    page.scene_settings_button.setChecked(False)
    wait(200)
    absent = pixels(page.view.grabWindow(), 1)
    penetration_change = sum(a != b for a, b in zip(present, absent))
    assert penetration_change > 100, penetration_change
    assert all(root.pickPart(x, y) != "P05" for x, y in targets)
    checkbox.setChecked(True)
    page.mode_tabs.setCurrentIndex(1)
    assert not wire.property("visible") and all(not node.property("visible") for node in penetrations)
    page.mode_tabs.setCurrentIndex(0)
    page._reset_three_d_view()
    wait(200)
    page.grab().save(str(work / "reference-lighting-native.png"))

    beats, frames = [], []
    heartbeat = QTimer()
    heartbeat.setInterval(16)
    heartbeat.timeout.connect(lambda: beats.append(time.perf_counter()))
    record_frame = lambda: frames.append(time.perf_counter())
    page.view.quickWindow().afterRendering.connect(record_frame)
    heartbeat.start()
    page.auto_rotate.setChecked(True)
    wait(2000)
    page.auto_rotate.setChecked(False)
    heartbeat.stop()
    page.view.quickWindow().afterRendering.disconnect(record_frame)
    gaps = sorted((b - a) * 1000 for a, b in zip(beats, beats[1:]))
    frame_gaps = sorted((b - a) * 1000 for a, b in zip(frames, frames[1:]))
    assert beats and frames
    page._reset_three_d_view()
    page.resize(1100, 800)
    wait(150)
    return {"reference_revision": reference["revision"], "lights": lights, "ambient_linear": ambient_linear,
            "exposure": reference["exposure"], "materials_verified": checked_materials,
            "environment_sha256": hashlib.sha256(expected_path.read_bytes()).hexdigest(),
            "wire_segments": len(original) // 24, "wire_changed_pixels": wire_change,
            "wire_clipped_axes": ["x", "y", "z"], "penetration_count": len(penetrations),
            "penetration_pick_targets": len(targets), "penetration_changed_pixels": penetration_change,
            "rotation_sample_ms": 2000, "frames": len(frames),
            "frame_gap_ms_median": frame_gaps[len(frame_gaps) // 2] if frame_gaps else None,
            "heartbeat_gap_ms_p95": gaps[int(len(gaps) * .95)], "heartbeat_gap_ms_max": max(gaps)}
