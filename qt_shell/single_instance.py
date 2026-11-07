"""Wake the existing desktop window when the application is launched again."""
from __future__ import annotations

import hashlib
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def server_name() -> str:
    identity = str(Path(tempfile.gettempdir()).resolve()).casefold()
    return "thimble-qt-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def wake_existing(timeout_ms: int = 1000) -> bool:
    socket = QLocalSocket()
    socket.connectToServer(server_name())
    if not socket.waitForConnected(timeout_ms):
        return False
    if socket.write(b"show\n") < 0:
        socket.abort()
        return False
    if socket.bytesToWrite() and not socket.waitForBytesWritten(timeout_ms):
        socket.abort()
        return False
    if not socket.bytesAvailable() and not socket.waitForReadyRead(timeout_ms):
        socket.abort()
        return False
    acknowledged = bytes(socket.readAll()) == b"ok"
    socket.disconnectFromServer()
    return acknowledged


def wake_existing_until_ready(
    total_timeout_ms: int = 12000,
    attempt_timeout_ms: int = 400,
    retry_delay_ms: int = 150,
) -> bool:
    """Wait through the first instance's backend/window startup.

    The desktop lock is acquired before the local backend and WebEngine window
    are ready. A second click during that short interval used to show a false
    "cannot wake window" warning after a single one-second attempt. Retrying
    keeps the hand-off quiet while the original process finishes startup, but
    still returns ``False`` when a genuinely stale or broken instance remains.
    """
    deadline = time.monotonic() + max(0, total_timeout_ms) / 1000
    while True:
        if wake_existing(max(1, attempt_timeout_ms)):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(max(0, retry_delay_ms) / 1000)


class InstanceWakeServer(QObject):
    wake_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.server = QLocalServer(self)
        self._clients = set()
        self.server.newConnection.connect(self._accept)

    def listen(self) -> bool:
        # Only the process holding the single-instance lock may clear this name.
        QLocalServer.removeServer(server_name())
        return self.server.listen(server_name())

    def _accept(self) -> None:
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self._clients.add(socket)
            socket.readyRead.connect(lambda s=socket: self._read(s))
            socket.disconnected.connect(lambda s=socket: self._release(s))
            if socket.bytesAvailable():
                self._read(socket)

    def _read(self, socket) -> None:
        if bytes(socket.readAll()).strip() == b"show":
            self.wake_requested.emit()
            socket.write(b"ok")
            socket.flush()

    def _release(self, socket) -> None:
        self._clients.discard(socket)
        socket.deleteLater()
