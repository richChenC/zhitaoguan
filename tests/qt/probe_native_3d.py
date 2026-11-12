"""Desktop-only QtQuick3D render and interaction probe; uses synthetic data."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import QEventLoop, QPoint, QPointF, QTimer, Qt, QtMsgType, QUrl, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication, QVector3D, QWheelEvent
from PySide6.QtQuick import QQuickItem, QQuickView
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton


def wait(milliseconds):
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def pixels(image, step=4):
    return [image.pixel(x, y) for y in range(0, image.height(), step)
            for x in range(0, image.width(), step)]


def verify_camera_views(page, root, work):
    """Check actual projection, bounds, picking and panel insets on the desktop renderer."""
    from qt_shell.native_components import workspace_styles
    results = []
    for width, height, model_settings in ((800, 650, False), (1024, 768, False),
                                          (1024, 768, True), (1480, 920, True)):
        theme = "light" if width == 1024 else "dark"
        page.setStyleSheet(workspace_styles(theme))
        page.set_theme(theme)
        wait(50)
        page.resize(width, height)
        page.scene_settings_button.setChecked(model_settings)
        page.data_details_button.setChecked(width == 1480)
        wait(200)
        assert page.width() == width, ("Settings increased window width", width, page.width())
        assert page.scene_settings_host.horizontalScrollBar().maximum() == 0
        if model_settings:
            assert page.scene_settings_host.height() <= page.scene_host.height() - page.scene_footer.height() - 16
            heading, body = page.scene_sections["整体布置"]
            page.scene_settings_host.ensureWidgetVisible(heading)
            wait(50)
            QTest.mouseClick(heading, Qt.MouseButton.LeftButton)
            assert body.isHidden(), "Actual disclosure click did not collapse the section"
            QTest.mouseClick(heading, Qt.MouseButton.LeftButton)
            assert not body.isHidden(), "Actual disclosure click did not expand the section"
            page.scene_settings_host.ensureWidgetVisible(page.image_export)
            wait(50)
            export_center = page.image_export.mapTo(
                page.scene_settings_host.viewport(), page.image_export.rect().center())
            assert page.scene_settings_host.viewport().rect().contains(export_center)
            page.scene_settings_host.verticalScrollBar().setValue(0)
        if width == 800:
            page.detection_filter_button.click()
            wait(100)
            assert page.scope.isVisible() and page.width() == width
            assert page.scope.mapTo(page, page.scope.rect().bottomRight()).x() < page.width()
            page.detection_filter_button.click()
            wait(100)
        for index in range(page.camera_preset.count()):
            page.camera_buttons[index].click()
            wait(100)
            assert bool(root.property("orthographicActive")) == (index > 0)
            assert bool(root.property("mirroredActive")) == (index == 5)
            assert root.property("domeAlpha") == (.07 if index > 0 else .26)
            assert root.property("plateAlpha") == (.13 if index > 0 else .42)
            low, high = root.property("fittedMinimum"), root.property("fittedMaximum")
            if index > 0:
                from qt_shell.native_geometry import geometry_data
                assert low.y() <= geometry_data("dome")[2][0][1], ("Dome bounds omitted", low)
            points = [root.projectPoint(QVector3D(
                high.x() if mask & 1 else low.x(),
                high.y() if mask & 2 else low.y(),
                high.z() if mask & 4 else low.z())) for mask in range(8)]
            visible_w = page.view.width() - root.property("coveredRight")
            visible_h = page.view.height() - root.property("coveredBottom")
            bounds = [min(p.x() for p in points), min(p.y() for p in points),
                      max(p.x() for p in points), max(p.y() for p in points)]
            assert all(0 < p.z() < 50000 for p in points), (index, "depth", points)
            assert root.property("coveredLeft") <= bounds[0] < bounds[2] <= visible_w, (
                width, index, bounds, root.property("coveredLeft"), visible_w)
            assert 0 <= bounds[1] < bounds[3] <= visible_h, (width, index, bounds, visible_h)
            if index in (5, 6):
                a = root.projectPoint(QVector3D(-100, 0, 0))
                b = root.projectPoint(QVector3D(100, 0, 0))
                assert (b.x() < a.x()) == (index == 5), (index, a, b)
            frame = page.view.grabWindow()
            colors = len(set(pixels(frame)))
            assert colors > 12, (width, index, colors)
            suffix = "-settings" if model_settings else ""
            frame.save(str(work / f"camera-{width}-{index}{suffix}.png"))
            page.grab().save(str(work / f"camera-ui-{width}-{index}{suffix}.png"))
            results.append({"width": width, "height": height,
                            "theme": theme,
                            "model_settings": model_settings,
                            "view": page.camera_preset.itemText(index),
                            "orthographic": index > 0, "mirrored": index == 5,
                            "available": [root.property("coveredLeft"), visible_w, visible_h],
                            "bounds": bounds, "colors": colors})

    page.camera_buttons[5].click()
    wait(150)
    points = [(x, y, root.pickTube(x, y))
              for y in range(0, int(page.view.height() - root.property("coveredBottom")), 12)
              for x in range(int(root.property("coveredLeft")), int(page.view.width() - root.property("coveredRight")), 12)]
    points = [point for point in points if point[2]]
    assert points, "Mirrored orthographic top cannot pick any real tube"
    all_targets = {}
    for row in page.rows.values():
        model = next(item for item in root.property("tubes") if item["tube"] == row["tube"])
        for dx, dz in ((0, 0), (8, 0), (14, 0), (18, 0), (0, 8), (0, 14), (0, 18)):
            p = root.projectPoint(QVector3D(model["x"] + dx, model["yBase"], model["z"] + dz))
            if root.pickTube(p.x(), p.y()) == model["tube"]:
                all_targets[model["tube"]] = [p.x(), p.y()]
                break
    assert len(all_targets) == 50, ("Projected top targets", sorted(all_targets))
    from qt_shell.native_plate_texture import PlateTextureData
    page.plate_view.setChecked(True)
    wait(200)
    texture = root.findChild(PlateTextureData)
    assert texture and texture.projectionMirror
    page.grab().save(str(work / "top-overlay-readable.png"))
    page.camera_buttons[0].click()
    wait(200)
    assert not texture.projectionMirror
    page.camera_buttons[5].click()
    wait(200)
    assert texture.projectionMirror
    page.plate_view.setChecked(False)
    dome_bottom = root.property("fittedMinimum").y()
    page.explode.setValue(75)
    wait(100)
    assert root.property("fittedMinimum").y() <= dome_bottom - 600 + .01
    page.explode.setValue(0)
    page.visibility_checks["showDome"].setChecked(False)
    wait(100)
    assert root.property("fittedMinimum").y() > dome_bottom
    page.visibility_checks["showDome"].setChecked(True)
    clipping = []
    for axis in ("x", "y", "z"):
        page.section_axis.setCurrentIndex(page.section_axis.findData(axis))
        page.section.setChecked(True)
        page._fit_scene()
        wait(100)
        low, high = root.property("fittedMinimum"), root.property("fittedMaximum")
        assert getattr(high, axis)() <= 0
        corners = [root.projectPoint(QVector3D(
            high.x() if mask & 1 else low.x(),
            high.y() if mask & 2 else low.y(),
            high.z() if mask & 4 else low.z())) for mask in range(8)]
        assert all(root.property("coveredLeft") <= p.x() <= page.view.width() - root.property("coveredRight")
                   and 0 <= p.y() <= page.view.height() - root.property("coveredBottom") for p in corners), axis
        clipping.append(axis)
    page.section.setChecked(False)
    page.section_axis.setCurrentIndex(0)
    wait(150)
    x, y, tube = points[len(points) // 2]
    QTest.mouseClick(page.view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x, y))
    assert page.tube_selector.value() == tube, (tube, page.tube_selector.value())
    free_point = QPoint(int(root.property("coveredLeft")) + 50, 150)
    drag_point = free_point + QPoint(30, 20)
    free_global = page.view.mapToGlobal(free_point)
    for overlay_widget in (page.scene_settings_host, page.scene_detail_host, page.scene_footer):
        if overlay_widget.isVisible():
            assert not overlay_widget.rect().contains(overlay_widget.mapFromGlobal(free_global)), (
                "Pointer target is covered by a widget", overlay_widget)
    before_pan = float(root.property("panX"))
    QTest.mousePress(page.view, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, free_point)
    QTest.mouseMove(page.view, drag_point, 50)
    QTest.mouseRelease(page.view, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, drag_point)
    assert root.property("panX") > before_pan, "Mirrored pan moved in the wrong direction"
    wheel = QWheelEvent(QPointF(free_point), QPointF(free_global), QPoint(), QPoint(0, 120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.ScrollUpdate, False)
    QApplication.instance().sendEvent(page.view, wheel)
    wait(100)
    assert root.property("zoomFactor") > 1
    page._fit_scene()
    assert page.camera_preset.currentIndex() == -1 and root.property("zoomFactor") == 1
    assert root.property("pitch") == -90 and root.property("domeAlpha") == .26
    QTest.mousePress(page.view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, free_point)
    QTest.mouseMove(page.view, drag_point, 50)
    QTest.mouseRelease(page.view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, drag_point)
    assert page.camera_preset.currentIndex() == -1
    assert not any(control.isChecked() for control in page.camera_buttons)
    assert root.property("domeAlpha") == .26 and root.property("plateAlpha") == .42
    page.camera_buttons[5].click()
    QTest.mouseDClick(page.view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, free_point)
    QTest.mouseRelease(page.view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, free_point)
    wait(100)
    assert page.camera_preset.currentIndex() == 0 and page.camera_buttons[0].isChecked()
    assert not root.property("orthographicActive") and not root.property("mirrorTop")
    page.camera_buttons[1].click()
    page.auto_rotate.setChecked(True)
    wait(150)
    assert not root.property("orthographicActive") and page.camera_preset.currentIndex() == -1
    page.auto_rotate.setChecked(False)
    page._reset_three_d_view()
    page.setStyleSheet(workspace_styles("light"))
    page.set_theme("light")
    page.scene_settings_button.setChecked(False)
    page.data_details_button.setChecked(False)
    page.resize(1100, 800)
    wait(500)
    return {"views": results, "top_picked_tubes": sorted({p[2] for p in points}),
            "all_top_targets_verified": sorted(all_targets),
            "top_overlay_glyph_compensation": True,
            "clipped_axes_fitted": clipping, "dome_visibility_and_explode": True,
            "clicked_tube": tube, "mirrored_pan_zoom": True, "free_rotation": True,
            "double_click_reset": True, "auto_rotation": True}


def verify_tube_colors(page, root, work, data):
    from PySide6.QtCore import QObject
    from qt_shell.native_components import icon, workspace_styles
    from qt_shell.native_model_data import color_tubes, reference_specs

    project = Path(__file__).resolve().parents[2]
    reference = project.parent / "10_TRAEqt优化版"
    cases = [{"mode": mode, "type_filter": kind, "tubes": page._scene_tubes,
              "records": data["records"], "levels": [30, 50],
              "colors": ["#79b98c", "#e5a83b", "#df4b45"]}
             for mode in ("base", "length", "type", "depth")
             for kind in ("", *page.type_buttons)]
    completed = subprocess.run(
        ["node", "--no-warnings", str(Path(__file__).with_name("reference_tube_colors.mjs")), str(reference)],
        input=json.dumps(cases), text=True, encoding="utf-8", capture_output=True, check=True)
    expected = json.loads(completed.stdout)
    for case, colors in zip(cases, expected["outputs"], strict=True):
        actual = color_tubes(case["tubes"], case["records"], mode=case["mode"],
                             type_filter=case["type_filter"])
        assert [tube["color"] for tube in actual] == colors, (case["mode"], case["type_filter"])

    page.resize(1480, 920)
    page.scene_settings_button.setChecked(True)
    page.data_details_button.setChecked(False)
    page.camera_buttons[0].click()
    wait(150)
    modes = {}
    original_node = root.findChild(QObject, "tubeNode-1")
    for theme in ("light", "dark"):
        page.setStyleSheet(workspace_styles(theme))
        page.set_theme(theme)
        for control in page.findChildren(QPushButton):
            if control.property("iconName"):
                control.setIcon(icon(control.property("iconName"), theme))
        wait(100)
        for mode in ("length", "type", "depth"):
            for control in page.color_checks.values():
                control.setChecked(False)
            control = page.color_checks[mode]
            page.scene_settings_host.ensureWidgetVisible(control)
            wait(75)
            QTest.mouseClick(control, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                             QPoint(8, control.height() // 2))
            wait(100)
            assert control.isChecked() and page._tube_color_mode() == mode
            tubes = root.property("tubes")
            matching = next(colors for case, colors in zip(cases, expected["outputs"], strict=True)
                            if case["mode"] == mode and not case["type_filter"])
            actual_colors = root.property("tubeColors")
            assert [actual_colors[str(tube["tube"])] for tube in tubes] == matching
            assert root.findChild(QObject, "tubeNode-1") == original_node, "Color change rebuilt tube geometry"
            viewport = page.scene_settings_host.viewport()
            background_point = viewport.mapTo(page, QPoint(4, 4))
            panel_background = page.grab().toImage().pixelColor(background_point).name()
            assert panel_background == ("#1c2527" if theme == "dark" else "#ffffff"), (
                theme, "Settings body background", panel_background)
            modes[mode] = {"unique_colors": sorted(set(matching)), "tubes": len(tubes)}
            page.grab().save(str(work / f"color-{mode}-{theme}.png"))
        target = page.type_buttons["II"]
        page.scene_settings_host.ensureWidgetVisible(target)
        wait(50)
        QTest.mouseClick(target, Qt.MouseButton.LeftButton)
        wait(100)
        assert page.type_filter.currentData() == "II"
        assert len(root.property("tubes")) == 50
        for tube in root.property("tubes"):
            node = root.findChild(QObject, "tubeNode-" + str(tube["tube"]))
            assert node and node.property("visible"), ("Type filter hid a tube", tube["tube"])
            if tube["type"] != "II":
                assert root.property("tubeColors")[str(tube["tube"])] == "#6b7480"
        page.grab().save(str(work / f"color-filter-depth-{theme}.png"))
        QTest.mouseClick(target, Qt.MouseButton.LeftButton)
        assert page.type_filter.currentData() == ""
    page.set_severity([20, 40], ["#112233", "#557799", "#bb5533"])
    wait(100)
    custom = color_tubes(page._scene_tubes, data["records"], mode="depth",
                         levels=[20, 40], colors=["#112233", "#557799", "#bb5533"])
    assert root.property("tubeColors") == {str(tube["tube"]): tube["color"] for tube in custom}
    page.set_severity([30, 50], ["#79b98c", "#e5a83b", "#df4b45"])
    for control in page.color_checks.values():
        control.setChecked(False)
    for _ in range(5):
        page._rebuild_scene()
        wait(75)
    page._set_scene_property("tubes", [])
    wait(75)
    page._rebuild_scene()
    wait(75)
    page.scene_settings_button.setChecked(False)
    page._reset_three_d_view()
    page.resize(1100, 800)
    wait(200)
    return {"reference_cases": len(cases), "reference_tube_colors": sum(len(c["tubes"]) for c in cases),
            "three_revision": expected["revision"], "modes": modes,
            "model_counts": {m["type"]: m["count"] for m in reference_specs()["models"]},
            "filter_fades_preserves_50_visible_tubes": True, "live_severity": True,
            "color_changes_reuse_geometry": True, "scene_rebuilds": 5, "empty_scene_reload": True}


def main():
    if len(sys.argv) > 1:
        return real_data_probe(Path(sys.argv[1]))
    app = QGuiApplication(sys.argv)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from qt_shell.native_geometry import register_geometry
    from qt_shell.native_model_data import reference_layout
    register_geometry()
    view = QQuickView()
    view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    view.resize(960, 720)
    view.setSource(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[2] / "qt_shell" / "native_model.qml")))
    if view.status() != QQuickView.Status.Ready:
        print(json.dumps({"errors": [error.toString() for error in view.errors()]}, ensure_ascii=False), flush=True)
        return 1
    view.show()
    root = view.rootObject()
    root.setProperty("tubes", [
        {"tube": i + 1, "x": channel["x"], "z": channel["z"], "yBase": channel["yBase"],
         "length": channel["L"],
         "category": "defect" if i == 0 else "ndd",
         "color": "#bc493c" if i == 0 else "#27816b"}
        for i, channel in enumerate(reference_layout()["channels"])
    ])
    wait(1500)
    first = view.grabWindow()
    before = pixels(first)
    hits = set()
    point = None
    for y in range(0, 720, 16):
        for x in range(0, 960, 16):
            hit = root.pickTube(x, y)
            if hit:
                hits.add(hit)
                point = (x, y, hit)
    selected = []
    root.tubeSelected.connect(selected.append)
    if point:
        QTest.mouseClick(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(point[0], point[1]))
    QTest.mousePress(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(350, 300))
    QTest.mouseMove(view, QPoint(510, 350), 50)
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(510, 350))
    wheel = QWheelEvent(QPointF(480, 360), QPointF(480, 360), QPoint(), QPoint(0, 120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.ScrollUpdate, False)
    app.sendEvent(view, wheel)
    wait(500)
    second = view.grabWindow()
    after = pixels(second)
    output = {
        "platform": app.platformName(), "qt_qpa_platform": os.environ.get("QT_QPA_PLATFORM"),
        "status": str(view.status()), "width": first.width(), "height": first.height(),
        "colors": len(set(before)), "changed_pixels_sampled": sum(a != b for a, b in zip(before, after)),
        "picked_tubes": sorted(hits), "clicked_tube": selected[-1] if selected else None,
        "expected_clicked_tube": point[2] if point else None,
        "yaw": root.property("yaw"), "pitch": root.property("pitch"),
        "zoom": root.property("zoomFactor"),
    }
    mode_colors = {}
    root.setProperty("selectedTube", 1)
    for mode in ("plate", "full", "socket", "joint"):
        root.setProperty("displayMode", mode)
        root.resetView()
        wait(250)
        mode_colors[mode] = len(set(pixels(view.grabWindow())))
    output["mode_colors"] = mode_colors
    root.setProperty("displayMode", "assembly")
    root.resetView()
    root.setProperty("clipEnabled", True)
    root.setProperty("clipAxis", "x")
    root.setProperty("clipOffset", 0)
    wait(250)
    clipped = view.grabWindow()
    clipped_hits = set()
    points = []
    for y in range(0, 720, 24):
        for x in range(0, 960, 24):
            tube = root.pickTube(x, y)
            if tube:
                clipped_hits.add(tube)
                points.append((x, y))
    output["clipped_tubes"] = sorted(clipped_hits)
    output["clip_changed_pixels"] = sum(a != b for a, b in zip(before, pixels(clipped)))
    root.setProperty("clipEnabled", False)
    measured = []
    root.measurementChanged.connect(measured.append)
    root.setProperty("measurementEnabled", True)
    if len(points) > 1:
        root.measureAt(*points[0])
        root.measureAt(*points[-1])
    wait(100)
    output["measurement_count"] = root.property("measurementCount")
    output["measurement"] = measured[-1] if measured else ""
    root.setProperty("explode", .75)
    root.setProperty("showAxes", True)
    wait(100)
    print(json.dumps(output, ensure_ascii=False), flush=True)
    view.setSource(QUrl())
    view.close()
    view.deleteLater()
    wait(50)
    return 0 if (output["colors"] > 12 and output["changed_pixels_sampled"] > 100 and hits
                 and output["clicked_tube"] == output["expected_clicked_tube"]
                 and output["yaw"] != 0 and output["pitch"] != -34 and output["zoom"] > 1
                 and output["clip_changed_pixels"] > 100 and 0 < len(clipped_hits) < len(hits)
                 and output["measurement_count"] == 2 and "mm" in output["measurement"]
                 and all(value > 12 for value in mode_colors.values())) else 1


def verify_parts(page, root, work):
    from PySide6.QtCore import QObject
    from PySide6.QtGui import QContextMenuEvent
    from qt_shell.native_components import workspace_styles
    from qt_shell.native_model_data import reference_parts
    checks = []
    page.dimensions.setChecked(False)
    page.stations.setChecked(False)
    page.measurement.setChecked(False)
    page.section.setChecked(False)
    page.explode.setValue(0)
    page.plate_view.setChecked(False)
    page.axes.setChecked(False)
    page.mode_tabs.setCurrentIndex(0)
    page.scene_settings_button.setChecked(True)
    page.data_details_button.setChecked(False)
    page.scene_settings_host.verticalScrollBar().setValue(0)
    for width, height, theme in ((800, 650, "dark"), (1480, 920, "light")):
        page.setStyleSheet(workspace_styles(theme))
        page.set_theme(theme)
        page.resize(width, height)
        wait(200)
        for part in reference_parts():
            key = part["id"]
            page.scene_settings_host.ensureWidgetVisible(page.part_tree)
            wait(50)
            item = page.part_items[key]
            point = page.part_tree.visualItemRect(item).center()
            QTest.mouseClick(page.part_tree.viewport(), Qt.MouseButton.LeftButton, pos=point)
            wait(150)
            assert page.display_mode.currentData() == "joint"
            assert page.mode_tabs.currentIndex() == 1
            assert page.part_info_host.isVisible() and page._selected_part == key
            assert root.property("partVisibility")[key]
            assert page.part_note.text() == part["note"]
            assert f"{part['triCount']:,} 三角面" in page.part_tags.text()
            assert page.width() == width
            assert page.scene_settings_host.horizontalScrollBar().maximum() == 0
            assert page.part_tree.horizontalScrollBar().maximum() == 0
            assert page.part_info_host.horizontalScrollBar().maximum() == 0
            assert page.part_tree.columnWidth(0) >= 180
            assert page.scene_settings_host.geometry().right() < page.scene_detail_host.geometry().left()
            assert page.scene_detail_host.geometry().bottom() < page.scene_footer.geometry().top()
            assert page.part_info_body.minimumSizeHint().width() <= page.part_info_host.viewport().width()
            page.grab().save(str(work / f"part-info-{key}-{width}-{theme}.png"))
            event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point,
                                      page.part_tree.viewport().mapToGlobal(point))
            QApplication.sendEvent(page.part_tree.viewport(), event)
            wait(60)
            assert not root.property("partVisibility")[key], key
            assert not page.part_info_host.isVisible()
            QTest.mouseClick(page.part_tree.viewport(), Qt.MouseButton.LeftButton, pos=point)
            wait(60)
            assert root.property("partVisibility")[key] and page.part_info_host.isVisible()
            checks.append({"part": key, "width": width, "theme": theme, "source_triangles": part["triCount"]})

    page.scene_settings_button.setChecked(False)
    page._hide_part_info()
    page.data_details_button.setChecked(False)
    page.mode_tabs.setCurrentIndex(1)
    for key in page._part_visibility:
        page._part_visibility[key] = False
    page._sync_part_tree()
    page._reset_three_d_view()
    wait(200)
    empty = pixels(page.view.grabWindow())
    mesh_checks = []
    for part in reference_parts():
        key = part["id"]
        page._part_visibility[key] = True
        page._sync_part_tree()
        wait(120)
        node = root.findChild(QObject, "detailPart-" + key)
        assert node and node.property("visible"), key
        frame = page.view.grabWindow()
        change = sum(a != b for a, b in zip(empty, pixels(frame)))
        assert change > 20, (key, "mesh failed to render", change)
        targets = [(x, y) for y in range(0, page.view.height(), 5)
                   for x in range(0, page.view.width(), 5) if root.pickPart(x, y) == key]
        assert targets, (key, "visible mesh cannot be picked")
        canvas_targets = [point for point in targets if point[0] < page.scene_detail_host.x()
                          and point[1] < page.scene_footer.y()]
        assert canvas_targets, (key, "mesh only renders under overlays")
        x, y = canvas_targets[len(canvas_targets)//2]
        QTest.mouseClick(page.view, Qt.MouseButton.LeftButton, pos=QPoint(x, y))
        wait(80)
        assert page._selected_part == key and page.part_info_host.isVisible()
        page._hide_part_info()
        page.grab().save(str(work / f"isolated-{key}.png"))
        page._part_visibility[key] = False
        page._sync_part_tree()
        wait(120)
        assert not root.pickPart(x, y), (key, "hidden mesh still intercepts picks")
        after_hide = pixels(page.view.grabWindow())
        assert sum(a != b for a, b in zip(empty, after_hide)) < 5, (
            key, "hidden mesh left pixels", sum(a != b for a, b in zip(empty, after_hide)))
        mesh_checks.append({"part": key, "changed_pixels": change, "pick_targets": len(targets)})
    for key in page._part_visibility:
        page._part_visibility[key] = page._parts[key]["visible"]
    page._sync_part_tree()
    page.ghost.setChecked(True)
    wait(120)
    ghosted = pixels(page.view.grabWindow())
    page.ghost.click()
    wait(120)
    opaque = pixels(page.view.grabWindow())
    ghost_change = sum(a != b for a, b in zip(ghosted, opaque))
    assert ghost_change > 20, ghost_change
    for key in ("P05", "P06"):
        material = root.findChild(QObject, "detailMaterial-" + key)
        assert material and material.property("alphaValue") == 1
    page.ghost.click()
    wait(100)
    assert material.property("alphaValue") == .22
    page.mode_tabs.setCurrentIndex(0)
    saved_scope = page._scope_data
    page.scope.setCurrentIndex(0)
    wait(100)
    assert not root.property("tubes")
    page.show_part("P02")
    wait(150)
    assert root.property("singleMode") and page.part_info_host.isVisible()
    assert len(set(pixels(page.view.grabWindow()))) > 12
    for number in (1, 25, 50):
        page.tube_selector.setValue(number)
        wait(50)
        assert root.property("selectedTube") == number
        assert root.property("detailLength") == page._detail_channel()["L"]
    page.scope.setCurrentIndex(next(i for i in range(page.scope.count())
                                    if (page.scope.itemData(i) or {}).get("outage") == "H209"))
    assert page._scope_data == saved_scope
    page.mode_tabs.setCurrentIndex(0)
    page.resize(1100, 800)
    page.dimensions.setChecked(True)
    page.stations.setChecked(True)
    wait(150)
    return {"metadata_checks": checks, "isolated_mesh_checks": mesh_checks,
            "ghost_changed_pixels": ghost_change, "hide_removes_pixels_and_picking": True,
            "reference_geometry_without_inspection_scope": True}


def verify_annotations(page, root, work):
    from PySide6.QtCore import QObject
    from PySide6.QtWidgets import QToolTip
    from qt_shell.native_components import workspace_styles
    from qt_shell.native_model_data import dimension_annotations
    checks = []
    page.scene_settings_button.setChecked(False)
    page.data_details_button.setChecked(False)
    page.detection_filter_button.setChecked(False)
    page._hide_part_info()
    page.dimensions.setChecked(True)
    page.stations.setChecked(True)
    for width, height, theme in ((800, 650, "dark"), (1024, 768, "light"), (1480, 920, "dark")):
        page.setStyleSheet(workspace_styles(theme))
        page.set_theme(theme)
        page.resize(width, height)
        for tab, mode in ((1, "joint"), (3, "socket"), (2, "full")):
            page.mode_tabs.setCurrentIndex(tab)
            wait(200)
            assert root.property("darkTheme") == (theme == "dark")
            background = page.view.grabWindow().pixelColor(2, 2).name()
            assert background == ("#101617" if theme == "dark" else "#f2f5f7"), background
            expected = dimension_annotations(mode, root.property("detailLength"), page._part_visibility,
                                             page.visibility_checks["enlargeTubes"].isChecked())
            assert root.property("dimensionLabels") == expected
            labels = root.property("projectedAnnotations").toVariant()
            dimensions = [label for label in labels if not label["station"]]
            assert dimensions, (width, mode, "No projected dimensions", labels)
            for i, label in enumerate(labels):
                assert root.property("coveredLeft") <= label["x"] < label["x"]+label["w"] <= page.view.width()-root.property("coveredRight")
                assert 0 <= label["y"] < label["y"]+label["h"] <= page.view.height()-root.property("coveredBottom")
                for other in labels[i+1:]:
                    assert (label["x"]+label["w"] <= other["x"] or other["x"]+other["w"] <= label["x"] or
                            label["y"]+label["h"] <= other["y"] or other["y"]+other["h"] <= label["y"]), (label, other)
            before = pixels(page.view.grabWindow())
            page.dimensions.setChecked(False)
            wait(100)
            after = pixels(page.view.grabWindow())
            changed = sum(a != b for a, b in zip(before, after))
            assert changed > 10, (mode, "Dimensions did not change actual pixels", changed)
            assert not any(not label["station"] for label in root.property("projectedAnnotations").toVariant())
            page.dimensions.setChecked(True)
            wait(100)
            scale = root.findChild(QQuickItem, "stationScale")
            assert scale and bool(scale.property("visible")) == (mode == "full")
            checks.append({"width": width, "theme": theme, "mode": mode,
                           "dimension_labels": [label["id"] for label in dimensions], "changed_pixels": changed})
            page.grab().save(str(work / f"annotations-{mode}-{width}-{theme}.png"))
    page.mode_tabs.setCurrentIndex(1)
    wait(150)
    previous_anchors = {label["id"]: (label["anchorX"], label["anchorY"])
                        for label in root.property("projectedAnnotations").toVariant()}
    QTest.mousePress(page.view, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
    QTest.mouseMove(page.view, QPoint(165, 120), 60)
    QTest.mouseRelease(page.view, Qt.MouseButton.LeftButton, pos=QPoint(165, 120))
    wait(150)
    moved = root.property("projectedAnnotations").toVariant()
    assert any(label["id"] in previous_anchors and
               abs(label["anchorX"]-previous_anchors[label["id"]][0])+
               abs(label["anchorY"]-previous_anchors[label["id"]][1]) > 1 for label in moved)
    definitions = {label["id"]: label for label in root.property("dimensionLabels")}
    for label in moved:
        if label["station"]:
            continue
        anchor = definitions[label["id"]]["anchor"]
        projected = root.projectPoint(QVector3D(anchor[0], anchor[1]-root.property("detailTarget"), anchor[2]))
        assert abs(projected.x()-label["anchorX"]) < .5 and abs(projected.y()-label["anchorY"]) < .5
    page.mode_tabs.setCurrentIndex(2)
    page.tube_selector.setValue(25)
    wait(150)
    length = root.property("detailLength")
    stations = root.property("stations")
    assert [mark["distance"] for mark in stations] == [0, 851, 1024.5, 1867.5, 2397.5, length]
    assert stations[4]["label"] == "P5?" and stations[4]["status"] == "推定"
    assert stations[-1]["y"] == 0 and stations[0]["y"] == length
    for mark in stations:
        ring = root.findChild(QObject, "stationRing-" + mark["id"])
        assert ring and ring.property("visible") and abs(ring.property("y")-mark["y"]) < .01
    baseline = pixels(page.view.grabWindow(), step=1)
    page.stations.setChecked(False)
    wait(150)
    ring_change = sum(a != b for a, b in zip(baseline, pixels(page.view.grabWindow(), step=1)))
    assert ring_change > 20, ring_change
    page.stations.setChecked(True)
    scale = root.findChild(QQuickItem, "stationScale")
    assert scale.property("visible")
    tick = next(item for item in scale.childItems() if item.objectName() == "scaleTick-P5")
    QTest.mouseClick(page.view, Qt.MouseButton.LeftButton,
                    pos=QPoint(int(scale.property("x")+tick.property("x")+65),
                               int(scale.property("y")+tick.property("y"))))
    wait(100)
    assert "推定" in QToolTip.text() and "待实测复核" in QToolTip.text(), QToolTip.text()
    QToolTip.hideText()
    for control in (page.scene_settings_button, page.detection_filter_button, page.data_details_button):
        control.setChecked(True)
        wait(100)
        assert not scale.property("visible"), control.text()
        control.setChecked(False)
        wait(100)
        assert scale.property("visible"), control.text()
    page.show_part("P01")
    wait(100)
    assert not scale.property("visible")
    page._hide_part_info()
    wait(100)
    assert scale.property("visible")
    page.mode_tabs.setCurrentIndex(0)
    wait(100)
    assert not scale.property("visible") and root.property("projectedAnnotations").toVariant() == []
    return {"layout_checks": checks, "station_ring_changed_pixels": ring_change,
            "source_positions_preserved": True, "p5_click_explains_uncertainty": True,
            "auxiliary_panels_hide_scale": True, "drag_updates_projected_leaders": True,
            "theme_background_pixels_match": True}


def real_data_probe(database):
    project = Path(__file__).resolve().parents[2]
    test_root = (project.parent / "05_测试与验证" / "03_自动化临时产物").resolve()
    database = database.resolve(strict=True)
    if not database.is_relative_to(test_root):
        raise ValueError("Real-data probe only accepts an isolated test database")
    sys.path.insert(0, str(project))
    from src.backend import analysis_reporting, cross_group_review, server
    from qt_shell.native_windows import NativeThreeDPage

    def connect():
        db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        cross_group_review.attach_view(db)
        return db

    server.connect = connect
    overview = server.overview()
    scope = next(item for item in overview["combinations"] if item["outage"] == "H209")
    data = analysis_reporting.analysis(
        server, {"site": scope["site"], "unit": scope["unit_id"], "outage": scope["outage"]}
    )

    class Client:
        def get(self, path, callback):
            callback(overview if path == "/api/overview" else data, None)

    messages = []
    def qt_message(kind, context, text):
        if kind in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            messages.append({"type": str(kind), "text": text})
        print(text, file=sys.stderr, flush=True)

    previous_handler = qInstallMessageHandler(qt_message)
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    page = NativeThreeDPage(Client())
    page.setObjectName("appRoot")
    page.resize(1100, 800)
    page.show()
    index = next(i for i in range(page.scope.count())
                 if (page.scope.itemData(i) or {}).get("outage") == "H209")
    page.scope.setCurrentIndex(index)
    wait(1500)
    image = page.view.grabWindow()
    root = page.view.rootObject()
    tubes = root.property("tubes") if root else []
    colors = len(set(pixels(image)))
    actual = {number: row["category_label"] for number, row in page.rows.items()}
    expected = {
        row["tube"]: ("存在缺陷" if row["defects"] else "NDD" if row["ndd"]
                      else "待复核" if row["records"] else "无记录")
        for row in data["plate"]
    }
    output = {"scope": scope, "records": data["summary"]["records"], "tubes": len(tubes),
              "categories_match": actual == expected, "colors": colors, "platform": app.platformName()}
    work = test_root / ("native-3d-widget-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    work.mkdir()
    image.save(str(work / "assembly.png"))
    if "--annotations-only" not in sys.argv:
        output["cameras"] = verify_camera_views(page, root, work)
        output["coloring"] = verify_tube_colors(page, root, work, data)
        output["parts"] = verify_parts(page, root, work)
    output["annotations"] = verify_annotations(page, root, work)
    image = page.view.grabWindow()
    page.plate_view.setChecked(True)
    wait(400)
    overlay = page.view.grabWindow()
    output["overlay_changed_pixels"] = sum(a != b for a, b in zip(pixels(image), pixels(overlay)))
    assert output["overlay_changed_pixels"] > 100, "Reference plate overlay was not rendered"
    assert page.display_mode.currentData() == "assembly"
    overlay.save(str(work / "plate-overlay.png"))
    page.plate_view.setChecked(False)
    wait(150)
    points = []
    for y in range(0, image.height(), 12):
        for x in range(0, image.width(), 12):
            tube = root.pickTube(x, y)
            if tube:
                points.append((x, y, tube))
    assert points, "No real tube can be picked"
    x, y, tube = points[len(points) // 2]
    QTest.mouseClick(page.view, Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier, QPoint(x, y))
    wait(50)
    assert page.tube_selector.value() == tube, (
        "perspective click", tube, page.tube_selector.value(), root.pickTube(x, y),
        root.property("measurementEnabled"), root.property("yaw"), root.property("pitch"))
    output["picked_tubes"] = sorted({p[2] for p in points})
    output["clicked_tube"] = tube
    QTest.mousePress(page.view, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, QPoint(250, 250))
    QTest.mouseMove(page.view, QPoint(350, 280), 50)
    QTest.mouseRelease(page.view, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier, QPoint(350, 280))
    wheel = QWheelEvent(QPointF(350, 280), QPointF(350, 280), QPoint(), QPoint(0, 120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.ScrollUpdate, False)
    app.sendEvent(page.view, wheel)
    wait(150)
    assert root.property("yaw") != 0 and root.property("zoomFactor") > 1
    root.resetView()
    wait(150)
    baseline = pixels(page.view.grabWindow())
    page.section.setChecked(True)
    wait(150)
    clipped = page.view.grabWindow()
    output["clip_changed_pixels"] = sum(a != b for a, b in zip(baseline, pixels(clipped)))
    assert output["clip_changed_pixels"] > 100
    clipped.save(str(work / "clipped.png"))
    page.section.setChecked(False)
    wait(200)
    page.measurement.setChecked(True)
    measurement_points = [(x, y) for x, y, _ in points if root.pickTube(x, y)]
    assert len(measurement_points) > 1, "Restored perspective has no measurement targets"
    root.measureAt(*measurement_points[0])
    root.measureAt(*measurement_points[-1])
    assert root.property("measurementCount") == 2 and "mm" in page.measurement_value.text()
    output["measurement"] = page.measurement_value.text()
    output["mode_colors"] = {}
    page.plate_view.setChecked(True)
    for mode in ("plate", "full", "socket", "joint"):
        page.display_mode.setCurrentIndex(page.display_mode.findData(mode))
        wait(200)
        assert not root.property("orthographicActive"), (mode, "detail remained orthographic")
        from PySide6.QtCore import QObject
        overlay_model = root.findChild(QObject, "plateOverlayModel")
        assert overlay_model and not overlay_model.property("visible"), mode
        assert not page.plate_view.isChecked() and page.plate_view.text() == "管板图：关", mode
        frame = page.view.grabWindow()
        output["mode_colors"][mode] = len(set(pixels(frame)))
        frame.save(str(work / (mode + ".png")))
        node = root.findChild(QObject, "tubeNode-" + str(tube))
        assert output["mode_colors"][mode] > 12, (
            mode, output["mode_colors"], tube, len(root.property("tubes")),
            root.property("selectedTube"), node.property("visible") if node else None,
            [(child.metaObject().className(), child.property("visible"),
              str(child.property("geometry"))) for child in node.children()] if node else None)
    page.plate_view.click()
    wait(200)
    assert page.display_mode.currentData() == "assembly" and page.mode_tabs.currentIndex() == 0
    assert overlay_model.property("visible") and page.plate_view.isChecked()
    output["overlay_mode_sync"] = True
    output["passed"] = len(tubes) == 50 and actual == expected and colors > 12
    output["qml_messages"] = messages
    assert not messages, messages
    (work / "result.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False), flush=True)
    print("closing page", flush=True)
    page.close()
    print("page closed", flush=True)
    page.deleteLater()
    wait(100)
    print("deferred deletes processed", flush=True)
    app.quit()
    qInstallMessageHandler(previous_handler)
    return 0 if output["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
