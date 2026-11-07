"""日志与中文启动失败诊断。

对应 main.cjs:63-66 / 170-178 与 service-diagnostics.cjs 全文。
"""
from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

from .constants import LOW_SPACE_BYTES, SERVICE_LOG_PATH


class ServiceLog:
    def __init__(self, path: Path = SERVICE_LOG_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, chunk: str | bytes) -> None:
        try:
            if isinstance(chunk, bytes):
                chunk = chunk.decode("utf-8", errors="replace")
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(chunk)
        except OSError:
            pass

    def window(self, kind: str, message: str) -> None:
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        self.write(f"[{stamp}] [{kind}] {message}\n")


def available_bytes(location) -> int | None:
    """复刻 service-diagnostics.cjs:6-21（逐级回溯到存在的父目录）。"""
    if not location:
        return None
    current = Path(os.path.abspath(str(location)))
    while True:
        try:
            usage = shutil.disk_usage(str(current))
            return usage.free
        except OSError:
            parent = current.parent
            if parent == current:
                return None
            current = parent


def startup_failure_message(error: BaseException, *, data_directory: str = "",
                            temp_directory: str = "", log_path: str = "") -> str:
    """复刻 service-diagnostics.cjs:23-54 的中文文案。"""
    code = getattr(error, "code", None)
    lines = ["本地数据服务启动失败。"]
    if code == "ENOSPC":
        lines.append("磁盘空间不足，请释放空间后重新启动软件。")
    elif code in ("EACCES", "EPERM"):
        lines.append("无法访问所需目录，请检查当前用户的访问权限后重试。")
        if getattr(error, "path", None):
            lines.append(f"目录或文件：{error.path}")
    elif code in ("ENOTDIR", "EEXIST"):
        lines.append("数据目录路径不可用，请检查路径中是否有同名文件。")
        if getattr(error, "path", None):
            lines.append(f"目录或文件：{error.path}")
    elif code != "SERVICE_START_FAILED" and str(error):
        lines.append(str(error))
    else:
        locations = [
            ("临时目录", temp_directory),
            ("数据目录", data_directory),
        ]
        low = [
            (label, path) for label, path in locations
            if (free := available_bytes(path)) is not None and free < LOW_SPACE_BYTES
        ]
        if low:
            lines.append("以下目录所在磁盘可用空间较少，可能影响启动，请释放空间后重试：")
            lines.extend(f"{label}：{path}" for label, path in low)
        else:
            lines.append("请检查临时目录及数据目录的可用空间和访问权限，然后重新启动软件。")
    if log_path:
        lines.append(f"启动日志（如已生成）：{log_path}")
    return "\n".join(lines)
