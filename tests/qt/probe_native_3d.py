"""Desktop-only QtQuick3D render and interaction probe; uses synthetic data."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import QEventLoop, QPoint, QPointF, QTimer, Qt, QUrl
from PySide6.QtGui import QGuiApplication, QWheelEvent
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


def wait(milliseconds):
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def pixels(image):
    return [image.pixel(x, y) for y in range(0, image.height(), 4)
            for x in range(0, image.width(), 4)]


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
    for mode in ("plate", "full", "socket"):
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

    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    page = NativeThreeDPage(Client())
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
    assert page.tube_selector.value() == tube
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
    page.measurement.setChecked(True)
    root.measureAt(*points[0][:2])
    root.measureAt(*points[-1][:2])
    assert root.property("measurementCount") == 2 and "mm" in page.measurement_value.text()
    output["measurement"] = page.measurement_value.text()
    output["mode_colors"] = {}
    for mode in ("plate", "full", "socket"):
        page.display_mode.setCurrentIndex(page.display_mode.findData(mode))
        wait(200)
        frame = page.view.grabWindow()
        output["mode_colors"][mode] = len(set(pixels(frame)))
        frame.save(str(work / (mode + ".png")))
        assert output["mode_colors"][mode] > 12, (mode, output["mode_colors"], tube)
    output["passed"] = len(tubes) == 50 and actual == expected and colors > 12
    (work / "result.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False), flush=True)
    print("closing page", flush=True)
    page.close()
    print("page closed", flush=True)
    page.deleteLater()
    wait(100)
    print("deferred deletes processed", flush=True)
    app.quit()
    return 0 if output["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
