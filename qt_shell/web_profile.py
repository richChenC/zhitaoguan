"""共享 QWebEngineProfile：会话持久化、离线拦截、注入脚本、QWebChannel。

对应 Electron 的 session.defaultSession + preload + main.cjs:322-331。
所有窗口必须共用同一 profile，否则 local-auth.js 的 BroadcastChannel
登录态同步会失效。
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtNetwork import QNetworkCookie
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (
    QWebEngineProfile, QWebEngineScript, QWebEngineSettings,
)

from .constants import WEBENGINE_DIR
from .offline_policy import OfflineInterceptor

_VENDOR = Path(__file__).resolve().parent / "vendor"


def _script(name: str, source: str) -> QWebEngineScript:
    script = QWebEngineScript()
    script.setName(name)
    script.setSourceCode(source)
    script.setInjectionPoint(QWebEngineScript.DocumentCreation)
    script.setWorldId(QWebEngineScript.MainWorld)
    script.setRunsOnSubFrames(True)
    return script


class ShellProfile:
    def __init__(self, desktop_api) -> None:
        WEBENGINE_DIR.mkdir(parents=True, exist_ok=True)
        (WEBENGINE_DIR / "cache").mkdir(parents=True, exist_ok=True)
        self.profile = QWebEngineProfile("thimble-qt", None)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.ForcePersistentCookies)
        self.profile.setPersistentStoragePath(str(WEBENGINE_DIR))
        self.profile.setCachePath(str(WEBENGINE_DIR / "cache"))
        # 后端对静态资源强制 no-store，磁盘 HTTP 缓存无命中，用内存缓存避免无效 IO
        self.profile.setHttpCacheType(QWebEngineProfile.MemoryHttpCache)

        settings = self.profile.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.AllowWindowActivationFromJavaScript, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, False)

        self.interceptor = OfflineInterceptor(self.profile)
        self.profile.setUrlRequestInterceptor(self.interceptor)

        self.session_cookie: str = ""
        store = self.profile.cookieStore()
        store.cookieAdded.connect(self._on_cookie_added)
        store.cookieRemoved.connect(self._on_cookie_removed)

        self.channel = QWebChannel(self.profile)
        self.channel.registerObject("desktop", desktop_api)
        self.desktop_api = desktop_api

        collection = self.profile.scripts()
        qwc = (_VENDOR / "qwebchannel.js").read_text(encoding="utf-8")
        shim = (Path(__file__).resolve().parent / "bridge_shim.js").read_text(encoding="utf-8")
        collection.insert(_script("qt-qwebchannel", qwc))
        collection.insert(_script("thimble-desktop-api", shim))

    # ---- Cookie --------------------------------------------------------
    def _on_cookie_added(self, cookie: QNetworkCookie) -> None:
        name = bytes(cookie.name()).decode("utf-8", errors="replace")
        if name == "thimble_session":
            value = bytes(cookie.value()).decode("utf-8", errors="replace")
            self.session_cookie = f"{name}={value}"

    def _on_cookie_removed(self, cookie: QNetworkCookie) -> None:
        name = bytes(cookie.name()).decode("utf-8", errors="replace")
        if name == "thimble_session":
            self.session_cookie = ""

    def cookie_header(self) -> str:
        return self.session_cookie

    # ---- 运行时 URL ----------------------------------------------------
    def set_base_url(self, base_url: str) -> None:
        self.interceptor.set_base_url(base_url)

    def blocked_report(self) -> dict:
        return {
            "blocked_count": self.interceptor.blocked_count,
            "samples": list(self.interceptor.blocked_samples),
        }

    def emit_download_status(self, state: str, filename: str) -> None:
        self.desktop_api.emit_download_status(json.dumps(
            {"state": state, "filename": filename}, ensure_ascii=False
        ))

    def emit_settings_section(self, section: str) -> None:
        self.desktop_api.emit_settings_section(section)
