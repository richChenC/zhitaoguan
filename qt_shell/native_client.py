"""Native Qt client for the local JSON API.

The client deliberately keeps transport asynchronous so a slow import or
large query never blocks the Widgets event loop. QNetworkCookieJar owns the
session cookie returned by the local service.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkCookieJar,
    QNetworkReply,
    QNetworkRequest,
)


Callback = Callable[[dict[str, Any] | None, str | None], None]


class NativeClient(QObject):
    requestStarted = Signal(str, str, str)
    activityFinished = Signal(str, str, str, str)
    requestFinished = Signal(str, object, str)
    mutationFinished = Signal(str, object, str)
    requestFailed = Signal(str, str)

    def __init__(self, base_url: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.base_url = base_url.rstrip("/")
        self.manager = QNetworkAccessManager(self)
        self.jar = QNetworkCookieJar(self)
        self.manager.setCookieJar(self.jar)
        self._callbacks: dict[int, Callback | None] = {}
        self._replies: dict[int, QNetworkReply] = {}
        self._failed_reads = {}
        self._activity_ids = {}
        self._next_activity = 0

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        callback: Callback | None = None,
        task_token: str | None = None,
    ) -> QNetworkReply:
        url = QUrl(f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}")
        request = QNetworkRequest(url)
        request.setRawHeader(b"Accept", b"application/json")
        if method.upper() == "POST":
            request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
            request.setRawHeader(b"X-Thimble-Request", b"1")
            if task_token:
                request.setRawHeader(b"X-Thimble-Task", task_token.encode("ascii"))
        body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8") if method.upper() == "POST" else b""
        reply = self.manager.post(request, body) if method.upper() == "POST" else self.manager.get(request)
        request_id = id(reply)
        self._callbacks[request_id] = callback
        self._replies[request_id] = reply
        reply.finished.connect(lambda r=reply, p=path, m=method.upper(): self._finish(r, p, m))
        self._next_activity += 1
        self._activity_ids[request_id] = str(self._next_activity)
        self.requestStarted.emit(str(self._next_activity), method.upper(), path)
        return reply

    def retry_read(self, request_id: str) -> bool:
        item = self._failed_reads.pop(request_id, None)
        if item is None:
            return False
        path, callback = item
        self.get(path, callback)
        return True

    def get(self, path: str, callback: Callback | None = None,
            task_token: str | None = None) -> QNetworkReply:
        return self.request("GET", path, callback=callback, task_token=task_token)

    def post(self, path: str, payload: dict[str, Any], callback: Callback | None = None,
             task_token: str | None = None) -> QNetworkReply:
        return self.request("POST", path, payload, callback=callback, task_token=task_token)

    def _finish(self, reply: QNetworkReply, path: str, method: str = "GET") -> None:
        request_id = id(reply)
        if request_id not in self._replies:
            reply.deleteLater()
            return
        callback = self._callbacks.pop(request_id, None)
        activity_id = self._activity_ids.pop(request_id, str(request_id))
        self._replies.pop(request_id, None)
        reply.finished.disconnect()
        error: str | None = None
        payload: dict[str, Any] | None = None
        if reply.error() != QNetworkReply.NetworkError.NoError:
            error = reply.errorString() or "本地服务请求失败"
        raw = bytes(reply.readAll())
        if raw:
            try:
                decoded = json.loads(raw.decode("utf-8", errors="replace"))
                if isinstance(decoded, dict):
                    payload = decoded
                    if isinstance(decoded.get("error"), str) and decoded["error"]:
                        error = decoded["error"]
            except (TypeError, ValueError):
                error = error or "本地服务返回了无效数据"
        if callback:
            try:
                callback(payload, error)
            except RuntimeError as exc:
                # A page can be deleted while its asynchronous request is
                # finishing. PySide raises here when a callback touches a
                # widget whose C++ object is already gone.
                if "Internal C++ object" not in str(exc):
                    raise
        self.requestFinished.emit(path, payload, error or "")
        if method == "POST":
            self.mutationFinished.emit(path, payload, error or "")
        if error:
            if method == "GET" and not path.startswith("/api/auth/"):
                self._failed_reads[activity_id] = (path, callback)
                while len(self._failed_reads) > 200:
                    self._failed_reads.pop(next(iter(self._failed_reads)))
            self.requestFailed.emit(path, error)
        self.activityFinished.emit(activity_id, method, path, error or "")
        reply.deleteLater()

    def abort_all(self) -> None:
        """Stop callbacks before a window is torn down."""
        callbacks = self._callbacks
        self._callbacks = {}
        replies = list(self._replies.values())
        self._replies.clear()
        for reply in replies:
            try:
                reply.finished.disconnect()
            except (RuntimeError, TypeError):
                pass
            reply.abort()
            reply.deleteLater()
        callbacks.clear()
        self._failed_reads.clear()
        self._activity_ids.clear()
