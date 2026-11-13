"""Actual section cap pixels, visibility, holes, motion, and cache response."""
from __future__ import annotations

from statistics import median
from time import perf_counter
from array import array
import os

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QVector3D
from PySide6.QtQml import QQmlExpression, qmlContext


def verify_sections(page, root, work, wait, pixels):
    from qt_shell.native_geometry import geometry_data
    def ready(geometry):
        for _ in range(300):
            if geometry and geometry.property("triangleCount") > 0:
                return
            wait(10)
        raise AssertionError("Asynchronous section mesh did not become ready")
    page.scene_settings_button.setChecked(False)
    page.data_details_button.setChecked(False)
    page._hide_part_info()
    page.dimensions.setChecked(False)
    page.stations.setChecked(False)
    page.detail_axis.setChecked(False)
    page.measurement.setChecked(False)
    page.explode.setValue(0)
    page.mode_tabs.setCurrentIndex(1)
    page.section.setChecked(True)
    checks = []
    for key in ("P01", "P02", "P03", "P04", "P05", "P06"):
        for part in page._part_visibility:
            page._part_visibility[part] = part == key
        page._sync_part_tree()
        page._reset_three_d_view()
        for index, axis in enumerate(("x", "y", "z")):
            page.section_axis.setCurrentIndex(index)
            bounds = geometry_data(key)[2]
            offset = 50 if axis == "y" and key in ("P01", "P02", "P03", "P04") else (
                -100 if axis == "y" else 0)
            page.section_offset.setValue(offset)
            root.setProperty("yaw", 90 if axis == "x" else 0)
            root.setProperty("pitch", -90 if axis == "y" else 0)
            wait(100)
            geometry = root.findChild(QObject, "detailCapGeometry-" + key)
            ready(geometry)
            assert geometry and geometry.property("triangleCount") > 0, (
                key, axis, offset, geometry.property("triangleCount") if geometry else None, bounds)
            frame = page.view.grabWindow()
            root.setProperty("showSectionCaps", False)
            wait(80)
            open_frame = page.view.grabWindow()
            changed = sum(a != b for a, b in zip(pixels(frame, 1), pixels(open_frame, 1)))
            assert changed > 5, ("Real cap did not change rendered material pixels", key, axis, changed)
            root.setProperty("showSectionCaps", True)
            wait(60)
            page.grab().save(str(work / f"section-{key}-{axis}.png"))
            checks.append({"part": key, "axis": axis, "offset": offset,
                           "triangles": geometry.property("triangleCount"),
                           "holes": geometry.property("holeCount"), "changed_pixels": changed})
    # An isolated P05 transverse cut must show material around a genuinely empty bore.
    for key in page._part_visibility:
        page._part_visibility[key] = key == "P05"
    page._sync_part_tree()
    page.section_axis.setCurrentIndex(1)
    page.section_offset.setValue(-100)
    root.setProperty("yaw", 0)
    root.setProperty("pitch", -90)
    wait(100)
    part = root.findChild(QObject, "detailPart-P05")
    center = part.mapPositionToScene(QVector3D(0, -100, 0))
    projected = root.projectPoint(center)
    def picked_name(point):
        expression = QQmlExpression(qmlContext(root), root,
            f"((hit) => hit ? hit.objectHit.objectName : '')(pickVisible({point.x()}, {point.y()}))")
        name, undefined = expression.evaluate()
        assert not expression.hasError() and not undefined, expression.error().toString()
        return name
    # The off-axis perspective ray can reach the inner wall farther down the bore.
    # It must never hit a cap triangle at the empty center of this section.
    bore_hit = picked_name(projected)
    assert bore_hit != "detailCap-P05", ("Section cap filled the P05 bore", bore_hit)
    ring = root.projectPoint(part.mapPositionToScene(QVector3D(24, -100, 0)))
    hit_name = picked_name(ring)
    assert hit_name == "detailCap-P05", ("Material ring is not pickable as actual cap geometry", hit_name)
    page.explode.setValue(70)
    wait(100)
    geometry = root.findChild(QObject, "detailCapGeometry-P05")
    moved = part.mapPositionToScene(QVector3D(24, -100, 0))
    assert abs(moved.y()-center.y()+84) < .001
    assert geometry.property("holeCount") == 1
    page._part_visibility["P05"] = False
    page._sync_part_tree()
    wait(80)
    assert geometry.property("triangleCount") == 0, "Hidden part retained active cap geometry"
    page._part_visibility["P05"] = True
    page._sync_part_tree()
    wait(80)
    assert geometry.property("triangleCount") > 0
    for key in page._part_visibility:
        page._part_visibility[key] = page._parts[key]["visible"]
    page._sync_part_tree()
    page.explode.setValue(0)
    wait(100)
    intervals, samples = [], []
    previous = [perf_counter()]
    timer = QTimer(page)
    timer.setInterval(16)
    def heartbeat():
        now = perf_counter()
        intervals.append((now-previous[0])*1000)
        previous[0] = now
    timer.timeout.connect(heartbeat)
    timer.start()
    for offset in range(-12, 13):
        started = perf_counter()
        page.section_axis.setCurrentIndex(0)
        page.section_offset.setValue(offset)
        wait(20)
        samples.append((perf_counter()-started)*1000)
    timer.stop()
    timer.deleteLater()
    settled = perf_counter()
    page.section_offset.setValue(3)
    wait(20)
    final_planes = {}
    for key, visible in page._part_visibility.items():
        if visible:
            geometry = root.findChild(QObject, "detailCapGeometry-" + key)
            ready(geometry)
            vertices = array("f")
            vertices.frombytes(bytes(geometry.vertexData()))
            scale = root.findChild(QObject, "detailPart-" + key).property("scale").x()
            assert all(abs(vertices[i]*scale-3) < .0001 for i in range(0, len(vertices), 6)), (
                "Rapid requests applied a stale section", key)
            final_planes[key] = 3
    from qt_shell.native_sections import section_service
    worker_pid = section_service().process.processId()
    assert worker_pid and worker_pid != os.getpid()
    page.grab().save(str(work / "section-rapid-latest-result.png"))
    page.section.setChecked(False)
    page.section_offset.setValue(0)
    page.section_axis.setCurrentIndex(0)
    page.explode.setValue(0)
    page.mode_tabs.setCurrentIndex(0)
    page._reset_three_d_view()
    wait(100)
    assert all(root.findChild(QObject, "detailCapGeometry-" + key).property("triangleCount") == 0
               for key in page._part_visibility), "Switch to assembly left detail caps active"
    return {"cuts": checks, "bore_empty": True, "bore_ray_hit": bore_hit, "cap_pick_name": hit_name,
            "explode_follows_part": True, "hidden_and_mode_clear_geometry": True,
            "slider_active_parts": sum(page._part_visibility.values()),
            "final_planes": final_planes, "settled_ms": (perf_counter()-settled)*1000,
            "separate_compute_process": True,
            "slider_samples": len(samples), "slider_elapsed_median_ms": median(samples),
            "heartbeat_max_ms": max(intervals), "heartbeat_median_ms": median(intervals)}
