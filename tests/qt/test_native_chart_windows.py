"""Chart focus and independent comparisons retain controls, scope and ownership."""
from copy import deepcopy
import unittest

import native_test_env  # noqa: F401
from PySide6.QtCore import QCoreApplication, QEvent, QTimer, QUrl, Qt
from PySide6.QtNetwork import QNetworkCookie
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox

from qt_shell.native_charts import ChartPanel, VisualizationWorkspace
from qt_shell.native_client import NativeClient
from qt_shell.native_windows import NativeMainWindow
from test_native_workflows import Client


class WindowClient(Client):
    def __init__(self):
        super().__init__()
        self.aborted = False

    def fork(self, parent):
        return WindowClient()

    def abort_all(self):
        self.aborted = True


class ChartWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def tearDown(self):
        for widget in self.app.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    @staticmethod
    def data(total=20):
        return {"trends": [{"unit": "N1", "order": 1, "outage": "N101", "total": total}],
                "snapshots": [{"unit": "N1", "outage": "N101", "order": 1, "tubes": []}],
                "summary": {"records": 1, "units": 1, "outages": 1}}

    def source(self):
        client = WindowClient()
        window = NativeMainWindow(client, {"username": "viewer", "permissions": ["data.read"]})
        page = window.stack.widget(3)
        page.scope_bar.selected_sites = {"N"}
        page.scope_bar._loaded({"combinations": [{"site": "N", "unit_id": 1, "outage": "N101"}]}, None)
        page.set_workspace_scope({"site": "N", "unit": "1", "outage": "N101"})
        page.visualization.set_data(self.data())
        return window, page, client

    def test_fullscreen_moves_complete_controls_and_restores_same_layout_twice(self):
        panel = ChartPanel()
        panel.lines("Chart", {"N1": [(1, 20)]}, "Source")
        choice = QComboBox()
        choice.addItems(["first", "second"])
        panel.layout().insertWidget(0, choice)
        panel.show()
        layout = panel.layout()
        observations = []

        def inspect():
            dialog = self.app.activeModalWidget()
            if dialog is None:
                observations.append((False, False, False))
                for top in self.app.topLevelWidgets():
                    if top is not panel:
                        top.close()
                return
            try:
                observations.append((True, dialog.isAncestorOf(choice), dialog.isAncestorOf(panel.view)))
                choice.setCurrentIndex(1)
                panel.lines("Live", {"N1": [(1, 30)]}, "Updated")
            finally:
                QTest.keyClick(dialog, Qt.Key.Key_Escape)

        for _ in range(2):
            QTimer.singleShot(0, inspect)
            panel.fullscreen()
            self.assertIs(panel.layout(), layout)
            self.assertTrue(panel.isAncestorOf(choice))
            self.assertTrue(panel.isAncestorOf(panel.view))
            self.assertEqual(choice.currentIndex(), 1)
            self.assertTrue(panel.expand_button.isEnabled())
        self.assertEqual(observations, [(True, True, True)] * 2)

    def test_detached_chart_keeps_main_view_and_refreshes_own_scope(self):
        window, source, client = self.source()
        source.visualization.comparison_mode.setCurrentIndex(1)
        source.visualization.total_metric.setCurrentIndex(0)
        source.visualization.comparison_units = {"N1"}
        original = deepcopy(source.visualization.total.contract)
        dialog = source.open_chart_window("total")
        self.app.processEvents()
        self.assertIsNot(dialog.client, client)
        self.assertFalse(dialog.isModal())
        self.assertEqual(dialog.page.scope_bar.values(), {"site": "N", "unit": "1", "outage": "N101"})
        self.assertEqual(dialog.page.scope_bar.selected_sites, {"N"})
        self.assertEqual(dialog.page.visualization.comparison_units, {"N1"})
        self.assertTrue(dialog.panel.isVisible())
        self.assertTrue(dialog.page.filter_band.isVisible())
        self.assertEqual(dialog.panel.contract, original)
        self.assertIsNot(dialog.panel.view, source.visualization.total.view)
        dialog.page.visualization.comparison_mode.setCurrentIndex(0)
        self.assertEqual(source.visualization.comparison_mode.currentIndex(), 1)
        client.requests.clear()
        dialog.client.requests.clear()
        window.context.dataChanged.emit()
        dialog._refresh_timer.stop()
        dialog._reload()
        paths = [entry[1] for entry in dialog.client.requests]
        self.assertTrue(any("sites=N&unit=N1&outage=N101" in path for path in paths), paths)
        dialog.page._complex_loaded(self.data(40), None)
        self.assertEqual(source.visualization.total.contract, original)
        self.assertEqual(dialog.panel.contract["groups"]["群厂汇总"], [(1, 40)])
        child_client = dialog.client
        dialog.close()
        self.assertTrue(child_client.aborted)
        self.assertFalse(client.aborted)
        self.assertEqual(source._chart_windows, [])

    def test_toolbar_click_nested_window_and_escape_release_only_closed_window(self):
        window, source, client = self.source()
        window.show()
        window.nav.setCurrentIndex(2)
        source.visualization.setCurrentIndex(1)
        source.visualization.trends.setCurrentWidget(source.visualization.total)
        self.app.processEvents()
        QTest.mouseClick(source.visualization.total.popout_button, Qt.MouseButton.LeftButton)
        self.assertEqual(len(source._chart_windows), 1)
        first = source._chart_windows[0]
        QTest.mouseClick(first.panel.popout_button, Qt.MouseButton.LeftButton)
        self.assertEqual(len(source._chart_windows), 2)
        second = source._chart_windows[1]
        first.refresh()
        child_client = first.client
        QTest.keyClick(first, Qt.Key.Key_Escape)
        self.assertTrue(child_client.aborted)
        self.assertFalse(first._refresh_timer.isActive())
        self.assertTrue(first._closed)
        first.client.requests.clear()
        first._reload()
        self.assertEqual(first.client.requests, [])
        self.assertEqual(source._chart_windows, [second])
        self.assertFalse(second.client.aborted)
        self.assertFalse(client.aborted)
        window.close()
        self.assertTrue(second.client.aborted)

    def test_snapshot_identity_survives_insertion_and_reordering(self):
        workspace = VisualizationWorkspace()
        initial = self.data()
        initial["snapshots"].append({"unit": "N1", "outage": "N102", "order": 2, "tubes": []})
        workspace.set_data(initial)
        workspace.snapshot.setCurrentIndex(1)
        updated = deepcopy(initial)
        updated["snapshots"].insert(0, {"unit": "F1", "outage": "F101", "order": 1, "tubes": []})
        workspace.set_data(updated)
        self.assertEqual(workspace.current_snapshot()["outage"], "N102")
        workspace.set_data({"snapshots": []})
        self.assertIsNone(workspace.current_snapshot())

    def test_owner_close_during_focus_cancels_child_and_unwinds_modal_loop(self):
        window, source, _ = self.source()
        window.show()
        dialog = source.open_chart_window("total")
        self.app.processEvents()
        client = dialog.client
        closed = []

        def close_owner():
            focused = self.app.activeModalWidget()
            closed.append(focused is not None)
            window.close()
            if focused:
                focused.reject()

        QTimer.singleShot(50, close_owner)
        dialog.panel.fullscreen()
        self.assertEqual(closed, [True])
        self.assertTrue(client.aborted)
        self.assertEqual(source._chart_windows, [])

    def test_preferences_and_owner_close_reach_detached_chart(self):
        window, source, client = self.source()
        dialog = source.open_chart_window("total")
        window.context.preferences.values.update(theme="dark", point_labels=True, ndd_zero=False)
        window.apply_preferences()
        self.assertEqual(dialog.panel.theme, "dark")
        self.assertTrue(dialog.panel.point_labels)
        self.assertFalse(dialog.page.visualization.ndd_zero)
        child_client = dialog.client
        window.close()
        self.assertTrue(child_client.aborted)
        self.assertTrue(client.aborted)

    def test_session_fork_shares_cookie_but_aborts_only_its_own_pending_requests(self):
        client = NativeClient("http://127.0.0.1:9", self.app)
        cookie = QNetworkCookie(b"local_session", b"test-only-session")
        client.jar.setCookiesFromUrl([cookie], QUrl(client.base_url))
        child = client.fork(self.app)
        self.assertIsNot(client.jar, child.jar)
        self.assertEqual(child.jar.cookiesForUrl(QUrl(child.base_url))[0].value(), cookie.value())
        client.get("/source")
        child.get("/detached")
        child.abort_all()
        self.assertFalse(child._replies)
        self.assertEqual(len(client._replies), 1)
        client.abort_all()
        child.deleteLater()
        client.deleteLater()


if __name__ == "__main__":
    unittest.main()
