"""Real assembly cap pixels and independent structure visibility."""
from __future__ import annotations

from PySide6.QtCore import QObject


def verify_assembly(page, root, work, wait, pixels):
    from qt_shell.native_components import workspace_styles
    from qt_shell.native_geometry import assembly_caps
    parts = assembly_caps()
    page.mode_tabs.setCurrentIndex(0)
    page.scene_settings_button.setChecked(False)
    page.data_details_button.setChecked(False)
    page._hide_part_info()
    page.explode.setValue(0)
    page.section_axis.setCurrentIndex(0)
    page.section_offset.setValue(0)
    page.section.setChecked(True)
    for name in ("showVessel", "showSupports", "showPlates"):
        page.visibility_checks[name].setChecked(True)
    for control in page.column_buttons.values():
        control.setChecked(True)
    wait(150)
    nodes = {part["id"]: root.findChild(QObject, part["id"]) for part in parts}
    assert all(nodes.values()) and all(node.property("visible") for node in nodes.values())
    for part in parts:
        material = root.findChild(QObject, "material-" + part["id"])
        assert material.property("tint").name() == part["material"]["color"]
        assert abs(material.property("metalnessValue")-part["material"]["metalness"]) < 1e-6
        assert abs(material.property("roughnessValue")-part["material"]["roughness"]) < 1e-6
        assert not nodes[part["id"]].property("pickable")
    assert abs(root.findChild(QObject, "vesselMaterial").property("alphaValue")-.14) < 1e-6
    checks = []
    for width, height, theme in ((800, 650, "dark"), (1480, 920, "light")):
        page.resize(width, height)
        page.setStyleSheet(workspace_styles(theme))
        page.set_theme(theme)
        root.setProperty("yaw", 90)
        root.setProperty("pitch", 0)
        wait(150)
        closed = page.view.grabWindow()
        root.setProperty("showAssemblyCaps", False)
        wait(100)
        opened = page.view.grabWindow()
        changed = sum(a != b for a, b in zip(pixels(closed, 1), pixels(opened, 1)))
        assert changed > 100, ("Assembly cut caps have no actual material pixels", width, changed)
        root.setProperty("showAssemblyCaps", True)
        wait(80)
        page.grab().save(str(work / f"assembly-section-{width}-{theme}.png"))
        checks.append({"width": width, "theme": theme, "changed_pixels": changed})
    # Static reference faces are only valid at the original x=0 section.
    for axis, offset in ((1, 0), (2, 0), (0, 100)):
        page.section_axis.setCurrentIndex(axis)
        page.section_offset.setValue(offset)
        wait(50)
        assert not any(node.property("visible") for node in nodes.values())
    page.section_axis.setCurrentIndex(0)
    page.section_offset.setValue(0)
    wait(50)
    for property_name, target in (("showVessel", "vessel"), ("showPlates", "plate"), ("showSupports", "column")):
        page.visibility_checks[property_name].setChecked(False)
        wait(50)
        assert all(node.property("visible") == (part["target"] != target)
                   for part in parts for node in [nodes[part["id"]]])
        page.visibility_checks[property_name].setChecked(True)
        wait(50)
    for kind, control in page.column_buttons.items():
        control.setChecked(False)
        wait(50)
        assert all(node.property("visible") == (part["columnType"] != kind)
                   for part in parts for node in [nodes[part["id"]]])
        control.setChecked(True)
    page.explode.setValue(65)
    wait(80)
    assert all(abs(nodes[part["id"]].property("y")-.65*part["explodeOffset"]) < 1e-6
               for part in parts)
    page.explode.setValue(0)
    page.mode_tabs.setCurrentIndex(1)
    wait(80)
    assert not any(node.property("visible") for node in nodes.values())
    page.mode_tabs.setCurrentIndex(0)
    page.section.setChecked(False)
    wait(80)
    assert not any(node.property("visible") for node in nodes.values())
    assert abs(root.findChild(QObject, "vesselMaterial").property("alphaValue")-.085) < 1e-6
    page._reset_three_d_view()
    wait(80)
    return {"cap_count": len(parts), "column_caps": 8, "actual_pixels": checks,
            "non_pickable": True, "materials_match": True,
            "independent_group_visibility": True, "plate_explosion_follows_geometry": True,
            "invalid_axis_offset_hides_static_reference_faces": True,
            "detail_mode_and_disabled_clear": True}
