"""Native disclosures, persisted choices and source-reference automatic fitting."""
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

import native_test_env
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QScrollArea, QToolButton, QVBoxLayout, QWidget

from qt_shell.native_model_panel import DEFAULT_COLLAPSED, GROUPS, ModelPanelGroups


class ModelPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.path = Path(native_test_env.test_data.name) / "disclosure-test.json"
        self.panels = []

    def tearDown(self):
        for panel in self.panels:
            panel.close()
            panel.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.path.unlink(missing_ok=True)

    def panel(self):
        panel = QScrollArea()
        panel.setWidgetResizable(True)
        panel.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        panel.setFrameShape(QScrollArea.Shape.NoFrame)
        panel.resize(320, 800)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(3)
        layout.setContentsMargins(2, 2, 2, 2)
        panel.setWidget(content)
        sections = {}
        for key in reversed(GROUPS):
            heading = QToolButton()
            heading.setText(key)
            heading.setCheckable(True)
            heading.setFixedHeight(24)
            body = QWidget()
            body.setFixedHeight(100)
            heading.toggled.connect(body.setVisible)
            layout.addWidget(heading)
            layout.addWidget(body)
            sections[key] = (heading, body)
        layout.addStretch()
        self.panels.append(panel)
        groups = ModelPanelGroups(panel, sections, lambda: None, self.path)
        panel.show()
        self.app.processEvents()
        return groups

    def state(self, groups):
        return {"collapsed": sorted(key for key in GROUPS if not groups.sections[key][0].isChecked()),
                "automatic": sorted(groups.auto_folded)}

    def test_order_defaults_and_atomic_manual_state_reload(self):
        groups = self.panel()
        layout = groups.panel.widget().layout()
        self.assertEqual([layout.itemAt(i*2).widget().text() for i in range(5)], list(GROUPS))
        self.assertEqual(self.state(groups)["collapsed"], sorted(DEFAULT_COLLAPSED))
        groups.sections["disp"][0].click()
        groups.sections["asm"][0].click()
        self.assertEqual(json.loads(self.path.read_text()), ["asm", "cut", "explode", "parts"])
        reloaded = self.panel()
        self.assertEqual(self.state(reloaded)["collapsed"], self.state(groups)["collapsed"])
        self.assertFalse(reloaded.auto_folded)
        self.assertFalse(list(self.path.parent.glob("disclosure-test.json.*")))

    def test_malformed_or_unknown_state_falls_back_to_reference_defaults(self):
        for text in ('{', '{}', '["asm",17]', '["foreign"]', 'null'):
            with self.subTest(text=text):
                self.path.write_text(text, encoding="utf-8")
                groups = self.panel()
                self.assertEqual(self.state(groups)["collapsed"], sorted(DEFAULT_COLLAPSED))

    def test_fitting_and_user_choices_match_actual_reference_handlers(self):
        groups = self.panel()
        default_height = groups._height()
        groups._set_expanded("disp", True)
        contribution = groups._height() - default_height
        groups._set_expanded("disp", False)
        base = default_height - contribution
        actions = [
            {"click": "disp"}, {"click": "cut"}, {"click": "explode"}, {"click": "parts"},
            {"height": base+contribution*2}, {"height": 2000},
            {"click": "cut"}, {"height": base+contribution}, {"height": 2000},
            {"click": "parts"}, {"height": 1}, {"height": 2000},
            {"click": "asm"}, {"click": "disp"}, {"height": base}, {"height": 2000},
        ]
        payload = {"base": base, "bodies": {key: contribution for key in GROUPS},
                   "height": 2000, "actions": actions}
        reference = subprocess.run(
            ["node", str(Path(__file__).with_name("reference_model_panel.mjs")),
             str(Path(__file__).resolve().parents[3] / "10_TRAEqt优化版"),
             json.dumps(payload)], capture_output=True, text=True, encoding="utf-8", check=True)
        expected = json.loads(reference.stdout)
        height = payload["height"]
        groups.fit(height)
        self.assertEqual(self.state(groups), expected[0])
        for index, action in enumerate(actions, 1):
            with self.subTest(action=action, index=index):
                if "click" in action:
                    heading = groups.sections[action["click"]][0]
                    opening = not heading.isChecked()
                    heading.click()
                    if opening:
                        groups.fit(height)
                else:
                    height = action["height"]
                    groups.fit(height)
                self.assertEqual(self.state(groups), expected[index])
                # An overlay's own resize notification must not re-collapse the opened group.
                groups.fit(height)
                self.assertEqual(self.state(groups), expected[index])

    def test_write_failure_is_reported_without_changing_controls(self):
        groups = self.panel()
        groups.path = Path(native_test_env.test_data.name)
        errors = []
        groups.saveFailed.connect(errors.append)
        groups.sections["disp"][0].click()
        self.assertTrue(groups.sections["disp"][0].isChecked())
        self.assertEqual(len(errors), 1)
        self.assertIn("无法保存", errors[0])
