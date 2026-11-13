"""Reference viewer group order, persistent disclosure state and automatic fitting."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QIODevice, QObject, QSaveFile, QTimer, Qt, Signal

from .constants import USER_DATA


GROUPS = ("asm", "disp", "cut", "explode", "parts")
DEFAULT_COLLAPSED = ("disp", "cut", "explode", "parts")
AUTO_FOLD_ORDER = ("parts", "explode", "cut", "disp")


class ModelPanelGroups(QObject):
    saveFailed = Signal(str)

    def __init__(self, panel, sections, request_layout, state_path: Path | None = None):
        super().__init__(panel)
        self.panel = panel
        self.sections = sections
        self.request_layout = request_layout
        self.path = state_path or USER_DATA / "model-panel-state.json"
        self.auto_folded = set()
        self.keep = None
        self._fitting = False
        self._last_layout = None
        self._available_height = None
        self._scroll_target = None
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.timeout.connect(lambda: self._scroll_opened(self._scroll_target))
        collapsed = list(DEFAULT_COLLAPSED)
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(saved, list) and all(isinstance(key, str) and key in GROUPS for key in saved):
                collapsed = saved
        except (OSError, ValueError):
            pass
        self._saved = set(collapsed)
        layout = panel.widget().layout()
        for index, key in enumerate(GROUPS):
            heading, body = sections[key]
            layout.insertWidget(index*2, heading)
            layout.insertWidget(index*2+1, body)
            self._set_expanded(key, key not in collapsed)
            heading.clicked.connect(lambda _checked, name=key: self._user_changed(name))

    def _set_expanded(self, key, expanded):
        heading, body = self.sections[key]
        blocked = heading.blockSignals(True)
        heading.setChecked(expanded)
        heading.blockSignals(blocked)
        heading.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        body.setVisible(expanded and not heading.isHidden())
        self.panel.widget().layout().invalidate()

    def _user_changed(self, key):
        self.auto_folded.discard(key)
        self.keep = key if self.sections[key][0].isChecked() else None
        if not self.keep and self._available_height is not None:
            self._last_layout = self._layout_signature(self._available_height)
        self._save()
        self.request_layout()
        if self.keep:
            self._scroll_target = key
            self._scroll_timer.start()

    def _scroll_opened(self, key):
        if key not in self.sections:
            return
        heading, body = self.sections[key]
        if self.panel.isVisible() and heading.isChecked() and not heading.isHidden():
            target = body if body.height() <= self.panel.viewport().height() else heading
            self.panel.ensureWidgetVisible(target, 0, 6)

    def _height(self):
        widget = self.panel.widget()
        width = self.panel.viewport().width()
        layout = widget.layout()
        return layout.totalHeightForWidth(width) if layout.hasHeightForWidth() else layout.totalSizeHint().height()

    def fit(self, available_height):
        if self._fitting or not self.panel.isVisible():
            return
        signature = self._layout_signature(available_height)
        if signature == self._last_layout:
            return
        self._fitting = True
        try:
            self._available_height = available_height
            limit = max(0, available_height - 2*self.panel.frameWidth())
            for key in reversed(AUTO_FOLD_ORDER):
                if key not in self.auto_folded:
                    continue
                self._set_expanded(key, True)
                if self._height() <= limit:
                    self.auto_folded.remove(key)
                else:
                    self._set_expanded(key, False)
            for key in AUTO_FOLD_ORDER:
                if self._height() <= limit:
                    break
                heading, _body = self.sections[key]
                if key == self.keep or not heading.isChecked() or heading.isHidden():
                    continue
                self._set_expanded(key, False)
                self.auto_folded.add(key)
            self.keep = None
            self._save()
            # Resizing the overlay to its contents emits another layout event.
            # Do not let that event undo protection of the user's opened group.
            self._last_layout = self._layout_signature(available_height)
        finally:
            self._fitting = False

    def _layout_signature(self, available_height):
        return (available_height, self.panel.viewport().width(), self._height(),
                tuple((heading.isChecked(), heading.isHidden()) for heading, _body in self.sections.values()))

    def _save(self):
        collapsed = {key for key, (heading, _body) in self.sections.items() if not heading.isChecked()}
        if collapsed == self._saved:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            stream = QSaveFile(str(self.path))
            content = json.dumps([key for key in GROUPS if key in collapsed]).encode("utf-8")
            if (not stream.open(QIODevice.OpenModeFlag.WriteOnly)
                    or stream.write(content) != len(content) or not stream.commit()):
                raise OSError(stream.errorString())
            self._saved = collapsed
        except OSError as error:
            self.saveFailed.emit("无法保存三维面板展开状态：" + str(error))
