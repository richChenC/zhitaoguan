"""Schedule and apply a recoverable reset while the backend is stopped."""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path


def _is_link(path: Path) -> bool:
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def schedule(root: Path) -> None:
    root = Path(root)
    marker = root / "factory-reset.json"
    if marker.exists():
        raise RuntimeError("已有待执行的恢复出厂设置，请重新启动软件。")
    temporary = root / ("factory-reset-" + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps({"id": uuid.uuid4().hex}), encoding="utf-8")
    os.replace(temporary, marker)


def apply(root: Path) -> bool:
    root = Path(root).resolve()
    marker = root / "factory-reset.json"
    if not marker.exists():
        return False
    if _is_link(marker):
        raise RuntimeError("恢复出厂设置标记无效。")
    ident = json.loads(marker.read_text(encoding="utf-8")).get("id", "")
    if not isinstance(ident, str) or not re.fullmatch(r"[0-9a-f]{32}", ident):
        raise RuntimeError("恢复出厂设置标记无效。")
    data = root / "data"
    backups = data / "backups"
    for path in (data, backups, root / "qtwebengine"):
        if _is_link(path):
            raise RuntimeError(f"恢复出厂设置不能处理链接目录：{path}")
    backups.mkdir(parents=True, exist_ok=True)
    recovery = backups / ("factory-reset-" + ident)
    recovery.mkdir(exist_ok=True)
    if _is_link(recovery):
        raise RuntimeError("恢复目录不能是链接。")
    for source, destination in [
        (data / "thimble.db", recovery / "thimble.db"),
        (data / "thimble.db-wal", recovery / "thimble.db-wal"),
        (data / "thimble.db-shm", recovery / "thimble.db-shm"),
        (root / "qtwebengine", recovery / "qtwebengine"),
    ]:
        if _is_link(source):
            raise RuntimeError(f"恢复出厂设置不能处理链接：{source}")
        if source.exists():
            if destination.exists():
                raise RuntimeError(f"恢复出厂设置遇到重复文件：{destination}")
            source.rename(destination)
    marker.unlink()
    return True
