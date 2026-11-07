"""离线白名单与请求拦截。

对应 offline-policy.cjs 全文 + main.cjs:324-331 的 webRequest/session 策略。
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import QObject
from PySide6.QtWebEngineCore import QWebEngineUrlRequestInterceptor

from .constants import USER_DATA


def _origin(value: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(value)
        scheme = (parsed.scheme or "").lower()
        host = (parsed.hostname or "").lower()
        port = parsed.port or (80 if scheme == "http" else 443 if scheme == "https" else 0)
        return scheme, host, port
    except ValueError:
        return None


def allowed_url(value: str, base: str) -> bool:
    """复刻 offline-policy.cjs:5-12。"""
    if not isinstance(value, str):
        return False
    try:
        if value == "about:blank":
            return True
        parsed = urlsplit(value)
        scheme = (parsed.scheme or "").lower()
        if scheme == "data":
            return True
        base_origin = _origin(base)
        if base_origin is None:
            return False
        if scheme == "blob":
            inner = value[5:] if value.lower().startswith("blob:") else ""
            return _origin(inner) == base_origin
        return scheme in ("http", "https") and _origin(value) == base_origin
    except (ValueError, TypeError):
        return False


def protect_directory(directory: Path = USER_DATA) -> None:
    """复刻 offline-policy.cjs:14-25（失败不阻断启动，仅记日志）。"""
    resolved = Path(directory).resolve()
    if resolved == Path(resolved.anchor):
        raise RuntimeError("用户数据目录不能是磁盘根目录")
    resolved.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            resolved.chmod(0o700)
        except OSError:
            pass
        return
    system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    try:
        who = subprocess.run(
            [str(system / "whoami.exe"), "/user", "/fo", "csv", "/nh"],
            capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        match = re.search(r"S-1-5-[0-9-]+", who.stdout or "")
        if who.returncode != 0 or not match:
            return
        sid = match.group(0)
        subprocess.run(
            [str(system / "icacls.exe"), str(resolved), "/grant:r",
             f"*{sid}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F", "/inheritance:r"],
            capture_output=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


class OfflineInterceptor(QWebEngineUrlRequestInterceptor):
    """只放行 data:/about:blank/同源 blob:/同源 http:，其余一律拦截。"""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.base_url = ""
        self.blocked_count = 0
        self.blocked_samples: list[str] = []

    def set_base_url(self, url: str) -> None:
        self.base_url = url

    def interceptRequest(self, info) -> None:  # noqa: N802 (Qt 覆写)
        url = info.requestUrl().toString()
        if allowed_url(url, self.base_url):
            return
        self.blocked_count += 1
        if len(self.blocked_samples) < 20:
            self.blocked_samples.append(url)
        info.block(True)
