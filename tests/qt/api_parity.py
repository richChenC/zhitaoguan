"""API 对拍：Qt 壳启动方式 vs 原版直启方式（同一冻结后端 exe）。

两个实例各挂一份独立的隔离库副本，登录后在 69 条静态抽取路由上逐一 GET，
比对 HTTP 状态码与规范化 JSON 摘要。所有写入只落隔离临时目录。
"""
from __future__ import annotations

import hashlib
import http.cookiejar
import json
import os
import secrets
import sqlite3
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

QT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = QT_ROOT.parent
VERIFY = QT_ROOT / "验证" / "02_基线与对拍"
TMP = PROJECT_ROOT / "05_测试与验证" / "03_自动化临时产物" / (
    "qt-api-parity-" + datetime.now().strftime("%Y%m%d-%H%M%S")
)
TMP.mkdir(parents=True, exist_ok=True)
EXE = QT_ROOT / "build" / "backend" / "thimble-backend.exe"
ROUTES = json.loads((VERIFY / "api_routes.json").read_text(encoding="utf-8"))["routes"]
CREDS = {"username": "qtparity", "password": "QtParity@2026", "display_name": "对拍账号"}

# 后端语义本身一致，但这些路由响应体含启动时间/实时快照/隔离临时目录路径等
# 环境相关易变字段，无法直接逐字节比对。对拍只要求"状态码一致 + 同类易变差异"，
# 不计入语义失配。证据见 验证/02_基线与对拍/API对拍结论.md。
VOLATILE_ROUTES = {
    "/api/health",                 # 含 uptime / started_at 等动态字段
    "/api/analysis/live",          # 实时分析快照，本就每次不同
    "/api/backups",                # 备份清单含启动时间戳
    "/api/operation-logs",         # 操作日志含时间戳与操作序列
    "/api/settings/data-source",   # 回显各自隔离临时数据目录路径
}


def free_port() -> int:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
    try:
        subprocess.run([str(taskkill), "/PID", str(proc.pid), "/T", "/F"],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        proc.kill()


class Instance:
    def __init__(self, tag: str, qt_style: bool) -> None:
        self.tag = tag
        self.qt_style = qt_style
        self.dir = TMP / tag
        self.dir.mkdir(parents=True, exist_ok=True)
        self.db = self.dir / "thimble.db"
        shutil.copy2(QT_ROOT / "user-data" / "data" / "thimble.db", self.db)
        # The checked-in runtime database may already contain a local admin
        # account/session from manual verification.  Clear only identity
        # tables in each isolated copy so the parity credential is deterministic
        # without touching the user's runtime database.
        con = sqlite3.connect(self.db)
        con.executescript(
            "DELETE FROM login_sessions; DELETE FROM user_roles; DELETE FROM users;"
        )
        con.commit()
        con.close()
        self.instance = secrets.token_hex(24)
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.proc: subprocess.Popen | None = None
        self.opener = None
        self.started_ms = 0

    def start(self) -> None:
        env = dict(os.environ)
        env["THIMBLE_DB_PATH"] = str(self.db)
        env["THIMBLE_DATA_DIR"] = str(self.dir / "data")
        env["THIMBLE_OUTPUT_DIR"] = str(self.dir / "output" / "excel")
        env["THIMBLE_REPORT_DIR"] = str(self.dir / "output" / "reports")
        env["THIMBLE_LOG_PATH"] = str(self.dir / "server.log")
        env["THIMBLE_PORT"] = str(self.port)
        env["THIMBLE_DESKTOP_INSTANCE"] = self.instance
        env["PYTHONPATH"] = str(QT_ROOT / ".vendor")
        env.pop("THIMBLE_MIGRATE_LEGACY", None)
        env.pop("THIMBLE_LEGACY_DATA_DIRS", None)
        if self.qt_style:
            # Qt 壳额外注入的离线开关，运行时语义不应改变任何 API 响应
            env["THIMBLE_DESKTOP_SHELL"] = "qt"
        t0 = time.monotonic()
        self.proc = subprocess.Popen(
            [str(EXE)], cwd=str(QT_ROOT), env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        for _ in range(120):
            time.sleep(0.25)
            try:
                with urllib.request.urlopen(f"{self.base}/api/health", timeout=1.5) as r:
                    payload = json.loads(r.read().decode("utf-8", "replace"))
                if payload.get("desktop_instance") == self.instance:
                    self.started_ms = int((time.monotonic() - t0) * 1000)
                    break
            except (OSError, ValueError, urllib.error.URLError):
                continue
        else:
            raise RuntimeError(f"{self.tag} 后端握手失败")
        jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def request(self, path: str, data: dict | None = None):
        headers = {"X-Thimble-Request": "1"}
        body = None
        if data is not None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=body, headers=headers,
                                     method="POST" if data is not None else "GET")
        try:
            with self.opener.open(req, timeout=20) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def login(self) -> None:
        status, raw = self.request("/api/auth/status")
        info = json.loads(raw.decode("utf-8", "replace")) if raw else {}
        if not info.get("initialized"):
            self.request("/api/auth/setup", CREDS)
        code, _ = self.request("/api/auth/login", CREDS)
        if code != 200:
            raise RuntimeError(f"{self.tag} 登录失败 HTTP {code}")

    def probe(self) -> dict:
        out = {}
        for route in ROUTES:
            t0 = time.monotonic()
            try:
                code, raw = self.request(route)
            except Exception as exc:  # noqa: BLE001
                out[route] = {"error": f"{type(exc).__name__}: {exc}"}
                continue
            elapsed = int((time.monotonic() - t0) * 1000)
            text = raw.decode("utf-8", "replace")
            # health 的实例令牌按设计不同，规范化后再比对
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict) and "desktop_instance" in parsed:
                    parsed["desktop_instance"] = "<instance>"
                canonical = json.dumps(parsed, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":"))
            except ValueError:
                canonical = text
            out[route] = {
                "status": code,
                "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                "bytes": len(raw),
                "elapsed_ms": elapsed,
            }
        return out


def main() -> int:
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "backend_exe": str(EXE), "route_count": len(ROUTES),
        "instances": {}, "mismatches": [], "summary": {},
    }
    a = Instance("qt-shell", True)
    b = Instance("direct", False)
    try:
        for inst in (a, b):
            inst.start()
            inst.login()
            report["instances"][inst.tag] = {
                "port": inst.port, "start_ms": inst.started_ms,
                "db": str(inst.db), "results": inst.probe(),
            }
        ra = report["instances"]["qt-shell"]["results"]
        rb = report["instances"]["direct"]["results"]
        for route in ROUTES:
            x, y = ra.get(route, {}), rb.get(route, {})
            if x.get("error") or y.get("error"):
                report["mismatches"].append({
                    "route": route, "qt": x, "direct": y, "kind": "error",
                })
                continue
            if x.get("status") != y.get("status"):
                report["mismatches"].append({
                    "route": route, "qt": x, "direct": y, "kind": "status",
                })
                continue
            # 已知易变路由：仅比对状态码，跳过逐字节 sha
            if route in VOLATILE_ROUTES:
                if x.get("sha256") != y.get("sha256"):
                    report.setdefault("volatile_diffs", []).append({
                        "route": route, "qt_bytes": x.get("bytes"),
                        "direct_bytes": y.get("bytes"),
                    })
                continue
            if x.get("sha256") != y.get("sha256"):
                report["mismatches"].append({
                    "route": route, "qt": x, "direct": y, "kind": "sha",
                })
        report["summary"] = {
            "compared": len(ROUTES),
            "semantic_mismatches": len(report["mismatches"]),
            "volatile_diffs": len(report.get("volatile_diffs", [])),
            "qt_start_ms": a.started_ms, "direct_start_ms": b.started_ms,
            "status_histogram": {
                str(code): sum(1 for v in ra.values() if v.get("status") == code)
                for code in sorted({v.get("status") for v in ra.values() if v.get("status")})
            },
        }
    except Exception as exc:  # noqa: BLE001
        report["fatal"] = f"{type(exc).__name__}: {exc}"
    finally:
        for inst in (a, b):
            if inst.proc:
                stop(inst.proc)
        (VERIFY / "API对拍.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({
            "summary": report.get("summary"), "fatal": report.get("fatal"),
            "mismatch_routes": [m["route"] for m in report["mismatches"]],
        }, ensure_ascii=False))
    # 仅当存在"语义失配"或致命错误才判失败；易变差异不计
    return 0 if not report.get("fatal") and not report["mismatches"] else 1


if __name__ == "__main__":
    sys.exit(main())
