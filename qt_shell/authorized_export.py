"""导出权限二次校验。

对应 main.cjs:509-532 authorizedExport()：
GET /api/auth/me 校验 export.create 权限；POST /api/security/image-export 登记导出。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from .constants import RUNTIME


class ExportAuthError(RuntimeError):
    pass


def authorized_export(cookie_header: str, data: dict | None = None) -> dict:
    route = "/api/security/image-export" if data is not None else "/api/auth/me"
    url = RUNTIME.base_url + route
    headers = {"Cookie": cookie_header}
    body = None
    if data is not None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        headers.update({
            "Content-Type": "application/json",
            "X-Thimble-Request": "1",
            "Content-Length": str(len(body)),
        })
    request = urllib.request.Request(
        url, data=body, headers=headers, method="POST" if body is not None else "GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status = response.status
            raw = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ExportAuthError(f"导出权限校验失败：{exc}") from exc
    try:
        result = json.loads(raw)
    except ValueError as exc:
        raise ExportAuthError("导出权限校验返回格式无效") from exc
    if status != 200:
        raise ExportAuthError(
            result.get("error") or "请先登录具有导出权限的本地账户"
        )
    if data is None:
        user = result.get("user") or {}
        if "export.create" not in (user.get("permissions") or []):
            raise ExportAuthError("当前账户没有导出权限")
    return result
