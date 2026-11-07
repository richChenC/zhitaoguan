"""Qt 移植版性能实测。

测量项（全部落 05_测试与验证/03_自动化临时产物/ 与 08_Qt移植版/验证/03_专项报告/）：
  1. 静态磁盘体积：QT 目录 vs APP 目录（对照 250MB 目标）。
  2. 后端冷启动：隔离库上从 exe 拉起到 /api/health 握手耗时（迁移 143MB 库主导）。
  3. Qt 壳到 UI 就绪：从 python -m qt_shell.main 启动到冒烟自检报告落盘耗时。
  4. 进程数 + 空闲常驻内存：UI 空闲期采样 Qt 主进程 + QtWebEngineProcess + 后端 exe 的 RSS 之和。

与 Electron 原版的对比基线由 验证/03_专项报告/perf_基线注记.md 记录（受限于当前环境，
Electron 版需 npm 构建且依赖 Node，本机以冻结后端 + 同等数据规模做等价对照）。
"""
from __future__ import annotations

import json
import os
import secrets
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
APP_ROOT = PROJECT_ROOT / "01_当前软件" / "软件正式版_20261021"
VERIFY = QT_ROOT / "验证" / "03_专项报告"
TMP = PROJECT_ROOT / "05_测试与验证" / "03_自动化临时产物" / (
    "qt-perf-" + datetime.now().strftime("%Y%m%d-%H%M%S")
)
TMP.mkdir(parents=True, exist_ok=True)
EXE = QT_ROOT / "build" / "backend" / "thimble-backend.exe"
SRC_DB = QT_ROOT / "user-data" / "data" / "thimble.db"


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


def dir_size_mb(path: Path, skip_names=frozenset({"项目资料"})) -> float:
    total = 0
    for root, dirs, files in os.walk(path):
        # 跳过目录联接（如 项目资料 → 外部原始资料）与指定目录
        rel = os.path.relpath(root, path)
        top = rel.split(os.sep)[0] if rel != "." else ""
        if top in skip_names:
            dirs[:] = []
            continue
        for name in files:
            try:
                fp = os.path.join(root, name)
                if os.path.islink(fp):  # 联接文件不计
                    continue
                total += os.path.getsize(fp)
            except OSError:
                continue
    return total / (1024 * 1024)


def backend_cold_start() -> dict:
    db = TMP / "backend" / "thimble.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SRC_DB, db)
    port = free_port()
    instance = secrets.token_hex(24)
    env = dict(os.environ)
    env.update({
        "THIMBLE_DB_PATH": str(db), "THIMBLE_PORT": str(port),
        "THIMBLE_DESKTOP_INSTANCE": instance,
        "THIMBLE_DATA_DIR": str(TMP / "backend" / "data"),
        "THIMBLE_OUTPUT_DIR": str(TMP / "backend" / "output" / "excel"),
        "THIMBLE_REPORT_DIR": str(TMP / "backend" / "output" / "reports"),
    })
    env.pop("THIMBLE_MIGRATE_LEGACY", None)
    env.pop("THIMBLE_LEGACY_DATA_DIRS", None)
    t0 = time.monotonic()
    proc = subprocess.Popen([str(EXE)], cwd=str(QT_ROOT), env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    ready = None
    try:
        for _ in range(180):
            time.sleep(0.25)
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.5) as r:
                    payload = json.loads(r.read().decode("utf-8", "replace"))
                if payload.get("desktop_instance") == instance:
                    ready = int((time.monotonic() - t0) * 1000)
                    break
            except (OSError, ValueError, urllib.error.URLError):
                continue
    finally:
        stop(proc)
    return {"port": port, "cold_start_ms": ready, "status": "ok" if ready else "timeout"}


def _sample_rss_tree(root_pid: int) -> int | None:
    ps = (
        f"$root={root_pid}; "
        "$tree=@($root); "
        "$tree+=Get-CimInstance Win32_Process | "
        "Where-Object{$_.ParentProcessId -eq $root} | "
        "Select-Object -ExpandProperty ProcessId; "
        "$p=Get-Process -Id $tree -ErrorAction SilentlyContinue; "
        "($p | Measure-Object WorkingSet -Sum).Sum"
    )
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        return int(out) if out.isdigit() else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def qt_shell_metrics() -> dict:
    db = TMP / "shell" / "thimble.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SRC_DB, db)
    port = free_port()
    env = dict(os.environ)
    env.update({
        "THIMBLE_DB_PATH": str(db), "THIMBLE_PORT": str(port),
        "THIMBLE_ALLOW_MULTI_INSTANCE": "1", "THIMBLE_QT_SMOKE": "8",
        "THIMBLE_DATA_DIR": str(TMP / "shell" / "data"),
        "THIMBLE_OUTPUT_DIR": str(TMP / "shell" / "output" / "excel"),
        "THIMBLE_REPORT_DIR": str(TMP / "shell" / "output" / "reports"),
        "THIMBLE_USER_DATA_DIR": str(TMP / "shell" / "user-data"),
    })
    env.pop("THIMBLE_MIGRATE_LEGACY", None)
    env.pop("THIMBLE_LEGACY_DATA_DIRS", None)
    py = str(QT_ROOT / ".venv-qt" / "Scripts" / "python.exe")
    t0 = time.time()  # 墙钟，与文件 st_mtime 同量纲
    proc = subprocess.Popen([py, "-m", "qt_shell.main"], cwd=str(QT_ROOT), env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    report_path = VERIFY / "启动冒烟.json"
    # 先把可能残留的旧报告移走，确保只认本次新报告
    stale = report_path.with_suffix(".stale.json")
    if report_path.exists():
        try:
            report_path.replace(stale)
        except OSError:
            pass
    ready_ms = None
    backend_ready_ms = None
    samples = []
    try:
        for _ in range(60):
            time.sleep(1.0)
            # 后端就绪时刻（独立探测，不依赖报告）
            if backend_ready_ms is None and port:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.0) as r:
                        json.loads(r.read().decode("utf-8", "replace"))
                    backend_ready_ms = int((time.time() - t0) * 1000)
                except (OSError, ValueError, urllib.error.URLError):
                    pass
            rss = _sample_rss_tree(proc.pid)
            if rss is not None:
                samples.append(rss)
            if report_path.exists() and report_path.stat().st_mtime >= t0 - 1.0:
                ready_ms = int((time.time() - t0) * 1000)
                # 再采样几秒取空闲稳态
                for _ in range(4):
                    time.sleep(1.0)
                    r = _sample_rss_tree(proc.pid)
                    if r is not None:
                        samples.append(r)
                break
    finally:
        stop(proc)
    idle_rss = max(samples) if samples else None
    return {
        "ui_ready_ms": ready_ms,
        "backend_ready_ms": backend_ready_ms,
        "process_count_in_tree": None,
        "idle_rss_bytes": idle_rss,
        "idle_rss_mb": round(idle_rss / (1024 * 1024), 1) if idle_rss else None,
        "rss_samples": len(samples),
    }


def main() -> int:
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "static_size": {},
        "backend_cold_start": {},
        "qt_shell": {},
        "targets": {
            "qt_static_max_mb": 250,
            "cold_start_max_ms": 3500,
            "idle_rss_max_mb": 450,
        },
    }
    # 1. 静态体积（跳过 junction；分三档）
    qt_code_mb = round(dir_size_mb(QT_ROOT, skip_names={"项目资料", "user-data", ".venv-qt"}), 1)
    qt_with_runtime_mb = round(dir_size_mb(QT_ROOT, skip_names={"项目资料", "user-data"}), 1)
    qt_total_mb = round(dir_size_mb(QT_ROOT, skip_names={"项目资料"}), 1)
    app_code_mb = round(dir_size_mb(APP_ROOT, skip_names={"项目资料", "node_modules"}), 1)
    report["static_size"] = {
        "qt_code_only_mb": qt_code_mb,
        "qt_with_runtime_mb": qt_with_runtime_mb,
        "qt_total_incl_data_mb": qt_total_mb,
        "app_code_only_mb": app_code_mb,
        "note": "code_only 不含 venv/运行数据/junction；with_runtime 含 PySide6 venv（形态A 绿色目录交付内容）；total 含 143MB 用户库副本",
    }
    # 2. 后端冷启动
    report["backend_cold_start"] = backend_cold_start()
    # 3+4. Qt 壳
    report["qt_shell"] = qt_shell_metrics()

    (VERIFY / "性能实测.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
