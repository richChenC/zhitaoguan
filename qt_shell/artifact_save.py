"""导出文件原子落盘、错误码中文映射、PNG 作者信息。

对应 artifact-save.cjs 全文、png-author.cjs 全文、main.cjs:42-50 (artifactName)。
命名有两套：后端/前端为 8 位 token，本文件仅实现 main.cjs 的 PNG/JSON
**12 位 token + 毫秒** 兜底命名，不可混用。
"""
from __future__ import annotations

import os
import re
import secrets
import struct
import zlib
from datetime import datetime
from pathlib import Path

from .constants import PNG_SIGNATURE

_ERROR_MESSAGES = {
    "ENOSPC": "保存失败：磁盘空间不足，请释放空间或选择其他磁盘后重试。",
    "EACCES": "保存失败：文件被占用或没有写入权限，请关闭文件或更换位置后重试。",
    "EPERM": "保存失败：文件被占用或没有写入权限，请关闭文件或更换位置后重试。",
    "ENOENT": "保存失败：目标文件夹不存在，请重新选择保存位置。",
    "EISDIR": "保存失败：目标路径是文件夹，请重新选择文件名。",
}


class ArtifactSaveError(RuntimeError):
    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = code


def save_artifact(file_path: str | Path, content: bytes | str) -> str:
    """临时文件 wx 独占写 + os.replace，对应 artifact-save.cjs:5-26。"""
    target = Path(file_path)
    data = content.encode("utf-8") if isinstance(content, str) else bytes(content)
    temporary = target.parent / f".thimble-export-{secrets.token_hex(12)}.tmp"
    try:
        with temporary.open("xb") as fh:
            fh.write(data)
        os.replace(temporary, target)
    except OSError as exc:
        err_name = {
            28: "ENOSPC", 13: "EACCES", 1: "EPERM", 2: "ENOENT", 21: "EISDIR",
        }.get(exc.errno, "")
        # Windows 上 winerror 5 对应 EACCES，errno 可能为 13 或 1
        if getattr(exc, "winerror", None) == 5:
            err_name = "EACCES"
        raise ArtifactSaveError(
            _ERROR_MESSAGES.get(err_name, "文件保存失败，请检查保存位置后重试。"), err_name
        ) from exc
    finally:
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            pass
    return str(target)


def _segment(value) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f\s]+', "-", str(value or "范围未指定").strip())
    text = re.sub(r"-+", "-", text)
    text = re.sub(r"^[ ._-]+|[ ._-]+$", "", text)[:36]
    return text or "范围未指定"


def artifact_name(kind: str, scope: str, extension: str) -> str:
    """main.cjs:42-50 —— 12 位 hex token + 毫秒时间戳。"""
    now = datetime.now()
    stamp = (
        f"{now.year:04d}{now.month:02d}{now.day:02d}-"
        f"{now.hour:02d}{now.minute:02d}{now.second:02d}-"
        f"{now.microsecond // 1000:03d}"
    )
    return f"TH_{_segment(kind)}_{_segment(scope)}_{stamp}_{secrets.token_hex(6)}.{extension}"


def sanitize_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name or ""))


# ---- PNG tEXt 作者信息（png-author.cjs 全文） --------------------------
def _png_chunk(chunk_type: str, data: bytes) -> bytes:
    name = chunk_type.encode("ascii")
    return (
        struct.pack(">I", len(data)) + name + data
        + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)
    )


def with_png_author(image: bytes, username: str) -> bytes:
    if (
        not isinstance(image, (bytes, bytearray))
        or bytes(image[:8]) != PNG_SIGNATURE
        or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{1,63}", username or "")
    ):
        raise ArtifactSaveError("图片或账户信息无效")

    image = bytes(image)
    offset = 8
    parts = [PNG_SIGNATURE]
    ended = False
    while offset + 12 <= len(image):
        length = struct.unpack_from(">I", image, offset)[0]
        end = offset + 12 + length
        if end > len(image):
            raise ArtifactSaveError("图片数据不完整")
        chunk_type = image[offset + 4: offset + 8].decode("ascii", errors="replace")
        data = image[offset + 8: offset + 8 + length]
        if chunk_type == "IEND":
            parts.append(_png_chunk("tEXt", f"Author\0{username}".encode("ascii")))
            parts.append(_png_chunk(
                "tEXt", f"Creation Time\0{datetime.now().astimezone().isoformat()}".encode("ascii")
            ))
            parts.append(image[offset:end])
            ended = True
            offset = end
            break
        if not (chunk_type == "tEXt" and data.startswith((b"Author\0", b"Creation Time\0"))):
            parts.append(image[offset:end])
        offset = end
    if not ended or offset != len(image):
        raise ArtifactSaveError("图片数据不完整")
    return b"".join(parts)
