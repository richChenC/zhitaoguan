"""本地数据服务生命周期（后端 exe 子进程）。

对应 main.cjs:94-226（stopServer / pythonCandidates / serverCandidates /
isServerReady / availablePort / selectPort / ensureServer）。

硬约束：
- 源码运行时优先使用源码后端；冻结运行时优先使用冻结后端；
- 所有 THIMBLE_* 目录都指向 QT/user-data，绝不指向正式业务库；
- 不注入 THIMBLE_MIGRATE_LEGACY（避免把历史数据灌进隔离库）。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .constants import (
    BACKEND_EXE, BACKEND_SOURCE, DATA_DIR, LOG_DIR, OUTPUT_DIR, QT_ROOT,
    REPORT_DIR, RUNTIME, SERVER_LOG_PATH, SERVICE_INSTANCE, SERVICE_NAME, USER_DATA,
    SERVICE_VERSION, VENDOR_DIR,
)
from .log_utils import ServiceLog


class ServiceStartError(RuntimeError):
    def __init__(self, message: str = "本地数据服务启动失败", code: str = "SERVICE_START_FAILED"):
        super().__init__(message)
        self.code = code


class BackendService:
    def __init__(self, log: ServiceLog | None = None) -> None:
        self.log = log or ServiceLog()
        self.process: subprocess.Popen | None = None
        self.stdout_thread = None
        self.stderr_thread = None

    # ---- 端口 ----------------------------------------------------------
    @staticmethod
    def _try_bind(port: int) -> int | None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", port))
            return sock.getsockname()[1]
        except OSError:
            return None
        finally:
            sock.close()

    def _select_port(self, preferred: int) -> int:
        if not isinstance(preferred, int) or not 1 <= preferred <= 65535:
            raise ServiceStartError("本地数据服务端口设置无效。")
        return self._try_bind(preferred) or self._try_bind(0) or preferred

    # ---- 握手 ----------------------------------------------------------
    def _health_ok(self) -> bool:
        url = f"{RUNTIME.base_url}/api/health"
        try:
            with urllib.request.urlopen(url, timeout=1.2) as response:
                if response.status != 200:
                    return False
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
            return (
                payload.get("ok") is True
                and payload.get("service") == SERVICE_NAME
                and payload.get("version") == SERVICE_VERSION
                and payload.get("desktop_instance") == SERVICE_INSTANCE
            )
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            return False

    # ---- 候选与环境变量 ------------------------------------------------
    def _candidates(self) -> list[tuple[str, list[str]]]:
        candidates: list[tuple[str, list[str]]] = []
        source = (sys.executable, [str(BACKEND_SOURCE)])
        if not getattr(sys, "frozen", False) and BACKEND_SOURCE.is_file():
            candidates.append(source)
        if BACKEND_EXE.is_file():
            candidates.append((str(BACKEND_EXE), []))
        return candidates

    def _environment(self) -> dict[str, str]:
        env = dict(os.environ)
        env["THIMBLE_DESKTOP_INSTANCE"] = SERVICE_INSTANCE
        test_root_value = env.get("THIMBLE_QT_TEST_DATA_ROOT")
        if test_root_value:
            if env.get("THIMBLE_ALLOW_MULTI_INSTANCE") != "1":
                raise ServiceStartError("隔离测试数据目录仅可用于多实例测试进程。")
            test_root = Path(test_root_value).expanduser().resolve()

            def test_path(name: str, default: Path) -> str:
                resolved = Path(env.get(name) or default).expanduser().resolve()
                if resolved != test_root and test_root not in resolved.parents:
                    raise ServiceStartError("Qt 隔离测试路径必须位于测试数据目录内。")
                return str(resolved)

            env["THIMBLE_USER_DATA_DIR"] = str(test_root)
            env["THIMBLE_DATA_DIR"] = test_path("THIMBLE_DATA_DIR", test_root / "data")
            env["THIMBLE_DB_PATH"] = test_path(
                "THIMBLE_DB_PATH", test_root / "data" / "thimble.db"
            )
            env["THIMBLE_OUTPUT_DIR"] = test_path(
                "THIMBLE_OUTPUT_DIR", test_root / "output" / "excel"
            )
            env["THIMBLE_REPORT_DIR"] = test_path(
                "THIMBLE_REPORT_DIR", test_root / "output" / "reports"
            )
            env["THIMBLE_LOG_PATH"] = test_path(
                "THIMBLE_LOG_PATH", test_root / "logs" / "server.log"
            )
        else:
            # Do not let inherited shell variables redirect the app to another
            # database or output directory during normal launches.
            env["THIMBLE_USER_DATA_DIR"] = str(USER_DATA)
            env["THIMBLE_DATA_DIR"] = str(DATA_DIR)
            env["THIMBLE_DB_PATH"] = str(DATA_DIR / "thimble.db")
            env["THIMBLE_OUTPUT_DIR"] = str(OUTPUT_DIR)
            env["THIMBLE_REPORT_DIR"] = str(REPORT_DIR)
            env["THIMBLE_LOG_PATH"] = str(SERVER_LOG_PATH)
        env["THIMBLE_PORT"] = str(RUNTIME.port)
        env["PYTHONPATH"] = os.pathsep.join(
            part for part in (str(VENDOR_DIR), env.get("PYTHONPATH", "")) if part
        )
        # 明确不启用历史数据迁移（对应 main.cjs:180-183 的反向约束）
        env.pop("THIMBLE_MIGRATE_LEGACY", None)
        env.pop("THIMBLE_LEGACY_DATA_DIRS", None)
        return env

    # ---- 启动 ----------------------------------------------------------
    def start(self) -> str:
        for directory in (DATA_DIR, OUTPUT_DIR, REPORT_DIR, LOG_DIR):
            directory.mkdir(parents=True, exist_ok=True)
        candidates = self._candidates()
        if not candidates:
            raise ServiceStartError("未找到本地数据服务程序（thimble-backend.exe）。")

        for command, args in candidates:
            port = self._select_port(RUNTIME.port if RUNTIME.port else 18767)
            RUNTIME.set_port(port)
            if port != 18767:
                self.log.write(f"[desktop] port 18767 is occupied; using {port}\n")
            env = self._environment()
            env["THIMBLE_PORT"] = str(port)
            creation = 0
            if os.name == "nt":
                creation = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
                    subprocess, "CREATE_NEW_PROCESS_GROUP", 0
                )
            try:
                self.process = subprocess.Popen(
                    [command, *args],
                    cwd=str(QT_ROOT),
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=creation,
                )
            except OSError as exc:
                self.log.write(f"[desktop] spawn failed: {command} - {exc}\n")
                continue

            self._start_pipe_readers()
            started = time.monotonic()
            deadline = started + 30
            while time.monotonic() < deadline:
                if self._health_ok():
                    self.log.write(f"[desktop] service ready on {RUNTIME.base_url} ({time.monotonic() - started:.2f}s)\n")
                    return RUNTIME.base_url
                if self.process.poll() is not None:
                    break
                time.sleep(0.1)
            self.log.write(f"[desktop] runtime failed: {command} - health check timed out\n")
            self.stop()

        raise ServiceStartError()

    def _start_pipe_readers(self) -> None:
        import threading

        def pump(stream) -> None:
            try:
                for raw in iter(lambda: stream.readline(), b""):
                    self.log.write(raw)
            except (OSError, ValueError):
                pass

        if self.process is None:
            return
        self.stdout_thread = threading.Thread(target=pump, args=(self.process.stdout,), daemon=True)
        self.stderr_thread = threading.Thread(target=pump, args=(self.process.stderr,), daemon=True)
        self.stdout_thread.start()
        self.stderr_thread.start()

    # ---- 停止 ----------------------------------------------------------
    def stop(self) -> None:
        process, self.process = self.process, None
        if process is None or process.poll() is not None:
            return
        if os.name == "nt":
            system_root = os.environ.get("SystemRoot", r"C:\Windows")
            taskkill = Path(system_root) / "System32" / "taskkill.exe"
            try:
                result = subprocess.run(
                    [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, timeout=6,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if result.returncode == 0:
                    return
            except (OSError, subprocess.TimeoutExpired):
                pass
        try:
            process.terminate()
            process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass
