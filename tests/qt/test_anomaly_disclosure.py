"""Exercise the real anomaly-details template in Qt WebEngine."""
import json
import os
from pathlib import Path
import re
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/desktop-ui/modules/analytics/official-workspace.js"


class AnomalyDisclosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_default_open_and_manual_toggle(self):
        source = SOURCE.read_text(encoding="utf-8")
        match = re.search(
            r'\?\s*(`<details class="tt-anomaly-details".*?)\s*\n\s*: picks\.length',
            source,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "anomaly-details template not found")
        template = match.group(1)

        view = QWebEngineView()
        view.resize(900, 600)
        view.show()
        page = view.page()
        loop = QEventLoop()
        loaded = []
        page.loadFinished.connect(lambda ok: (loaded.append(ok), loop.quit()))
        page.setHtml('<!doctype html><html><body><div id="test"></div></body></html>')
        QTimer.singleShot(10000, loop.quit)
        loop.exec()
        self.assertEqual(loaded, [True], "test page did not load")

        script = """
        (() => {
          const anomalies = [{tube: 1, position: 'B5', reasons: ['达到关注'],
            point: {order: 1, outage: 'D101', max_depth: 35, delta: null}}];
          const outageByOrder = new Map([[1, {label: '第1次'}]]);
          const esc = value => String(value ?? '');
          document.querySelector('#test').innerHTML = TEMPLATE;
          const detail = document.querySelector('.tt-anomaly-details');
          const summary = detail.querySelector('summary');
          const row = detail.querySelector('tbody tr');
          const before = {open: detail.open, visible: row.checkVisibility(),
            text: row.textContent};
          summary.click();
          const collapsed = {open: detail.open, visible: row.checkVisibility()};
          summary.click();
          const reopened = {open: detail.open, visible: row.checkVisibility()};
          return JSON.stringify({before, collapsed, reopened});
        })()
        """.replace("TEMPLATE", template)
        results = []
        loop = QEventLoop()
        page.runJavaScript(script, lambda result: (results.append(result), loop.quit()))
        QTimer.singleShot(10000, loop.quit)
        loop.exec()
        self.assertTrue(results and results[0], "JavaScript result timed out")
        result = json.loads(results[0])
        self.assertTrue(result["before"]["open"])
        self.assertTrue(result["before"]["visible"])
        self.assertIn("D101", result["before"]["text"])
        self.assertIn("达到关注", result["before"]["text"])
        self.assertEqual(result["collapsed"], {"open": False, "visible": False})
        self.assertEqual(result["reopened"], {"open": True, "visible": True})
        view.close()


if __name__ == "__main__":
    unittest.main()
