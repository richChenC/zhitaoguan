"""Local storage boundary and non-connecting future business API settings."""
from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
from urllib.parse import urlsplit
try:
    from .database_runtime import GATE
except ImportError:
    from database_runtime import GATE


DEFAULT_PROFILE = {
    "server_url": "",
    "timeout_seconds": 10,
    "source_directory": "",
}
_CONFIG_LOCK = threading.RLock()
_MAX_CONFIG_BYTES = 64 * 1024


class ClosingConnection(sqlite3.Connection):
    def close(self):
        try:
            return super().close()
        finally:
            if getattr(self, '_gate_held', False):
                self._gate_held = False
                GATE.leave()

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class SQLiteProvider:
    """Keep SQLite behavior explicit; a server adapter is not implemented."""

    def __init__(self, path: Path):
        self.path = Path(path).expanduser().resolve()

    def connect(self, attach_view=None) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        GATE.enter()
        try:
            db = sqlite3.connect(self.path, factory=ClosingConnection)
            db._gate_held = True
        except Exception:
            GATE.leave()
            raise
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("PRAGMA synchronous=NORMAL")
            # Keep temporary GROUP BY/ORDER BY work in memory and give SQLite
            # a larger page cache for repeated desktop filter queries.
            db.execute("PRAGMA temp_store=MEMORY")
            db.execute("PRAGMA cache_size=-16000")
            db.execute("PRAGMA mmap_size=268435456")
            if attach_view is not None:
                attach_view(db)
            return db
        except Exception:
            db.close()
            raise

    def describe(self) -> dict:
        try:
            exists = self.path.is_file()
            size = self.path.stat().st_size if exists else 0
        except OSError:
            exists, size = False, 0
        return {
            "mode": "local", "engine": "sqlite", "path": str(self.path),
            "exists": exists, "size_bytes": size,
        }

    def validate(self) -> dict:
        if not self.path.is_file():
            return {
                "ok": False, "connected": False,
                "message": "本地数据库文件不存在；未创建空数据库。",
                "checks": {"exists": False, "read_only": True},
            }
        try:
            # mode=ro never creates a missing database or changes its contents.
            with sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True,
                                 factory=ClosingConnection, timeout=5) as db:
                db.execute("PRAGMA query_only=ON")
                check = db.execute("PRAGMA quick_check(1)").fetchone()[0]
                tables = {row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                required = {"findings", "tube_states"}
                missing = sorted(required - tables)
            healthy = check == "ok" and not missing
            return {
                "ok": healthy, "connected": healthy,
                "message": ("本地数据库连接正常，完整性检查通过。" if healthy else
                            "本地数据库检查未通过；文件未作修改。"),
                "checks": {
                    "exists": True, "read_only": True,
                    "integrity": check == "ok", "missing_tables": missing,
                },
            }
        except (sqlite3.Error, OSError):
            return {
                "ok": False, "connected": False,
                "message": "无法只读打开本地数据库，请检查文件格式或访问权限。",
                "checks": {"exists": True, "read_only": True, "integrity": False},
            }


def _server_url(value) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("服务器地址应为不超过 2048 字符的 HTTP/HTTPS 业务接口地址")
    value = value.strip()
    if not value:
        return ""
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise ValueError("服务器地址不能包含空白或控制字符")
    if any(character in value for character in ("\\", "?", "#")):
        raise ValueError("服务器地址不能包含反斜杠、查询参数或片段")
    try:
        parsed = urlsplit(value)
        if (parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None):
            raise ValueError
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError
        hostname = parsed.hostname
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            hostname = hostname.encode("idna").decode("ascii")
            if len(hostname) > 253 or not all(
                re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                for label in hostname.rstrip(".").split(".")
            ):
                raise ValueError
    except (ValueError, UnicodeError):
        raise ValueError("服务器地址必须为 HTTP/HTTPS 地址，不能包含账号、密码或数据库连接串") from None
    return value


def normalize_profile(values: dict, current: dict | None = None) -> dict:
    if not isinstance(values, dict):
        raise ValueError("数据源设置应为对象")
    if set(values) - set(DEFAULT_PROFILE):
        raise ValueError("数据源设置包含不支持的字段；请勿保存数据库密码或连接串")
    profile = {**DEFAULT_PROFILE, **(current or {}), **values}
    profile["server_url"] = _server_url(profile["server_url"])
    timeout = profile["timeout_seconds"]
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 120:
        raise ValueError("请求超时应为 1 至 120 秒的整数")
    directory = profile["source_directory"]
    if (not isinstance(directory, str) or len(directory) > 4096
            or any(ord(character) < 32 for character in directory)):
        raise ValueError("资料目录格式无效")
    profile["source_directory"] = directory.strip()
    return profile


def config_path(db_path: Path) -> Path:
    # Binding configuration to the selected local DB also isolates test runs.
    return Path(db_path).expanduser().resolve().parent / "data-source.json"


def _load_profile(path: Path) -> tuple[dict, list[str]]:
    if not path.exists():
        return dict(DEFAULT_PROFILE), []
    try:
        if path.stat().st_size > _MAX_CONFIG_BYTES:
            raise ValueError
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            raise ValueError
        profile = normalize_profile(data["profile"])
        return profile, []
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        return dict(DEFAULT_PROFILE), [
            "本地数据源配置无法读取，当前仍使用本地数据库；原配置文件已保留，请备份并修复后再保存。"
        ]


def settings(db_path: Path) -> dict:
    with _CONFIG_LOCK:
        profile, warnings = _load_profile(config_path(db_path))
    return {
        "active": SQLiteProvider(db_path).describe(),
        "profile": profile,
        "capabilities": {"local": True, "server": False},
        "boundary": "当前版本仅支持本地数据库；远程服务器功能尚未启用；不会发起外部网络请求。",
        "warnings": warnings,
    }


def _request_profile(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("数据源设置请求应为对象")
    if "profile" in data:
        if set(data) != {"profile"}:
            raise ValueError("当前仅支持保存预留配置，不能切换或指定活动数据库")
        return data["profile"]
    return data


def save_settings(db_path: Path, data: dict) -> dict:
    path = config_path(db_path)
    with _CONFIG_LOCK:
        current, warnings = _load_profile(path)
        if warnings:
            raise ValueError(warnings[0])
        profile = normalize_profile(_request_profile(data), current)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=".data-source-", suffix=".tmp", delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump({"schema_version": 1, "profile": profile}, stream,
                          ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
    return settings(db_path)


def validate_settings(db_path: Path, data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("数据源检查请求应为对象")
    if set(data) - {"target", "profile"}:
        raise ValueError("数据源检查包含不支持的字段")
    target = data.get("target", "local")
    snapshot = settings(db_path)
    if target == "local":
        result = SQLiteProvider(db_path).validate()
    elif target == "server":
        try:
            profile = normalize_profile(data.get("profile", {}), snapshot["profile"])
            valid = bool(profile["server_url"])
            result = {
                "ok": valid, "connected": False,
                "message": ("地址格式检查通过。服务器业务接口尚未接入；未连接服务器、未上传本地数据。"
                            if valid else "请填写未来服务器业务接口的 HTTP/HTTPS 地址。"),
                "checks": {"format_valid": valid, "network_requested": False},
            }
        except ValueError as exc:
            result = {
                "ok": False, "connected": False, "message": str(exc),
                "checks": {"format_valid": False, "network_requested": False},
            }
    else:
        raise ValueError("检查目标应为 local 或 server")
    return {**snapshot, **result, "target": target}
