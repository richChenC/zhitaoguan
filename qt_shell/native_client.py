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
    requestFinished = Signal(str, object, str)
    requestFailed = Signal(str, str)

    def __init__(self, base_url: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.base_url = base_url.rstrip("/")
        self.manager = QNetworkAccessManager(self)
        self.jar = QNetworkCookieJar(self)
        self.manager.setCookieJar(self.jar)
        self._callbacks: dict[int, Callback | None] = {}

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        callback: Callback | None = None,
    ) -> QNetworkReply:
        url = QUrl(f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}")
        request = QNetworkRequest(url)
        request.setRawHeader(b"Accept", b"application/json")
        if method.upper() == "POST":
            request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
            request.setRawHeader(b"X-Thimble-Request", b"1")
        body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8") if method.upper() == "POST" else b""
        reply = self.manager.post(request, body) if method.upper() == "POST" else self.manager.get(request)
        request_id = id(reply)
        self._callbacks[request_id] = callback
        reply.finished.connect(lambda r=reply, p=path: self._finish(r, p))
        return reply

    def get(self, path: str, callback: Callback | None = None) -> QNetworkReply:
        return self.request("GET", path, callback=callback)

    def post(self, path: str, payload: dict[str, Any], callback: Callback | None = None) -> QNetworkReply:
        return self.request("POST", path, payload, callback=callback)

    def _finish(self, reply: QNetworkReply, path: str) -> None:
        request_id = id(reply)
        callback = self._callbacks.pop(request_id, None)
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
                    if not error and isinstance(decoded.get("error"), str):
                        error = decoded["error"]
            except (TypeError, ValueError):
                error = error or "本地服务返回了无效数据"
        if callback:
            callback(payload, error)
        self.requestFinished.emit(path, payload, error or "")
        if error:
            self.requestFailed.emit(path, error)
        reply.deleteLater()
