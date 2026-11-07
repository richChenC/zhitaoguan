from __future__ import annotations

import re
import uuid
from datetime import datetime


def _segment(value: object, limit: int = 36) -> str:
    text = str(value or "").strip()
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f\s]+', "-", text)
    text = re.sub(r"-{2,}", "-", text).strip(" .-_")
    return text[:limit].rstrip(" .-_") or "范围未指定"


def filename(kind: str, scope: object = "", extension: str = "") -> str:
    """Build a readable, bounded, collision-resistant name for a user-facing artifact."""
    suffix = str(extension or "").strip().lstrip(".").lower()
    if not re.fullmatch(r"[a-z0-9]{1,8}", suffix):
        raise ValueError("导出文件扩展名无效")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    token = uuid.uuid4().hex[:8]
    scope_label = str(scope or "范围未指定").replace("全部基地_全部机组_全部大修", "全范围")
    parts = ["TH", _segment(kind), _segment(scope_label), stamp, token]
    return "_".join(parts) + "." + suffix
