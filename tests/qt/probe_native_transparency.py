"""Inspect real model alpha on a transparent Qt Quick 3D render target."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sys

from PySide6.QtCore import QEventLoop, QObject, QTimer, QUrl
from PySide6.QtGui import QColor, QImage
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication


def wait(milliseconds):
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def main():
    project = Path(__file__).resolve().parents[2]
    work = Path(sys.argv[1]).resolve()
    test_root = project.parent / "05_测试与验证" / "03_自动化临时产物"
    if not work.is_relative_to(test_root.resolve()):
        raise ValueError("Transparency probe outputs must be isolated")
    work.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(project))
    from qt_shell.native_geometry import register_geometry
    register_geometry()
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    view = QQuickWidget()
    view.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
    view.setClearColor(QColor(0, 0, 0, 0))
    view.resize(900, 700)
    view.setSource(QUrl.fromLocalFile(str(project / "qt_shell/native_model.qml")))
    view.show()
    wait(400)
    root = view.rootObject()
    assert root, view.errors()
    root.setProperty("displayMode", "joint")
    root.setProperty("color", QColor(0, 0, 0, 0))
    root.setProperty("partVisibility", {f"P{i:02}": i == 2 for i in range(1, 7)})
    root.setProperty("showStations", False)
    material = root.findChild(QObject, "detailMaterial-P02")
    assert material
    material.setProperty("cullMode", 0)  # One visible face of the closed source mesh.
    wait(300)
    material.setProperty("alphaValue", 1)
    wait(150)
    opaque = view.grabFramebuffer().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    opaque.save(str(work / "opaque.png"))
    probes = []
    for opacity in (.5, .22, .085):
        material.setProperty("alphaValue", opacity)
        wait(180)
        image = view.grabFramebuffer().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        image.save(str(work / f"alpha-{opacity}.png"))
        alphas, invalid = Counter(), 0
        for y in range(image.height()):
            for x in range(image.width()):
                if opaque.pixelColor(x, y).alpha() != 255:
                    continue
                pixel = image.pixel(x, y)
                alpha = (pixel >> 24) & 255
                if not alpha:
                    continue
                alphas[alpha] += 1
                invalid += max((pixel >> 16) & 255, (pixel >> 8) & 255, pixel & 255) > alpha+1
        covered_pixels = sum(count for alpha, count in alphas.items()
                             if any(abs(alpha-(1-(1-opacity)**layers)*255) <= 1 for layers in range(1, 13)))
        probes.append({"opacity": opacity, "alpha_histogram": dict(alphas),
                       "source_over_pixels": covered_pixels, "invalid_premultiplied_pixels": invalid,
                       "passed": covered_pixels > 100 and invalid == 0})
    result = {"platform": app.platformName(), "probes": probes,
              "passed": all(probe["passed"] for probe in probes)}
    (work / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)
    view.close()
    view.setSource(QUrl())
    view.deleteLater()
    wait(100)
    app.quit()
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
