"""Filesystem permissions used by both native Qt and WebEngine modes."""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from .constants import USER_DATA


def protect_directory(directory: Path = USER_DATA) -> None:
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
