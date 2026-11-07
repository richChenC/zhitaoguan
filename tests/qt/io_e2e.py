"""Qt 移植版 · 导入/导出业务端到端实测。

只在隔离目录（05_测试与验证/03_自动化临时产物/）启动冻结后端，使用独立 DB 与端口，
绝不触碰原版业务库。验证：建管理员→登录→导入真实 xlsx→核对入库→导出 docx/xlsx 落盘。
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

QT_ROOT = Path(__file__).resolve().parents[2]
EXE = QT_ROOT / "build" / "backend" / "thimble-backend.exe"
REAL_XLSX = (
    QT_ROOT.parent
    / "05_测试与验证" / "01_模拟数据"
    / "全基地全机组全大修_模拟数据_非真实"
    / "软件导入专用_检测记录及管状态.xlsx"
)
TMP_ROOT = QT_ROOT.parent / "05_测试与验证" / "03_自动化临时产物"
TS = datetime.now().strftime("%Y%m%d-%H%M%S")
WORK = TMP_ROOT / f"qt-io-e2e-{TS}"
PORT = 20131

RESULT = {
    "generated_at": datetime.now().isoformat(timespec="seconds"),
    "real_xlsx": str(REAL_XLSX),
    "steps": {},
    "errors": [],
}

PROG_FILE = None


def log(stage: str, **kw):
    RESULT["steps"][stage] = kw
    line = f"[io_e2e] {stage}: {kw}"
    print(line, flush=True)
    if PROG_FILE is not None:
        try:
            with open(PROG_FILE, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass


def _post(url, payload, cookie=None, raw=False, timeout=300):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Thimble-Request", "1")  # 后端本地交互校验，缺此头所有 POST 被拒
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            if raw:
                return r.headers, body
            return r.headers, json.loads(body.decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:800]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def _get(url, cookie=None, timeout=120):
    req = urllib.request.Request(url, method="GET")
    if cookie:
        req.add_header("Cookie", cookie)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.headers, r.read()


def _wait_health(base, timeout=40):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base}/api/health", timeout=2) as r:
                if json.loads(r.read()).get("ok") is True:
                    return True
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(0.5)
    return False


def _find_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _count_findings(db_path):
    try:
        c = sqlite3.connect(str(db_path))
        n = c.execute("SELECT COUNT(*) FROM findings WHERE is_deleted=0").fetchone()[0]
        c.close()
        return n
    except Exception as exc:
        return f"ERR:{exc}"


def _pairs(db_path):
    c = sqlite3.connect(str(db_path))
    rows = c.execute(
        "SELECT outage, unit_id, COUNT(*) FROM findings WHERE is_deleted=0 "
        "GROUP BY outage, unit_id ORDER BY COUNT(*) DESC LIMIT 5"
    ).fetchall()
    units = c.execute(
        "SELECT unit_id, COUNT(DISTINCT outage) c FROM findings WHERE is_deleted=0 "
        "GROUP BY unit_id HAVING c>=2 LIMIT 3"
    ).fetchall()
    c.close()
    return rows, units


def _verify_office(buf, expect_zip_member):
    if not buf or len(buf) < 4 or buf[:4] != b"PK\x03\x04":
        return False, f"非合法 OOXML(zip) 头: {buf[:4]!r}"
    import zipfile
    try:
        with zipfile.ZipFile(io_bytes(buf)) as z:
            names = z.namelist()
        ok = any(m in names for m in expect_zip_member)
        return ok, f"zip成员数={len(names)}, 含{expect_zip_member}={ok}"
    except zipfile.BadZipFile as exc:
        return False, f"BadZip: {exc}"


def io_bytes(buf):
    import io
    return io.BytesIO(buf)


def main():
    if not EXE.is_file():
        RESULT["errors"].append("thimble-backend.exe 缺失")
        print(json.dumps(RESULT, ensure_ascii=False, indent=2))
        return
    if not REAL_XLSX.is_file():
        RESULT["errors"].append(f"真实测试 xlsx 缺失: {REAL_XLSX}")
        print(json.dumps(RESULT, ensure_ascii=False, indent=2))
        return

    WORK.mkdir(parents=True, exist_ok=True)
    global PROG_FILE
    PROG_FILE = WORK / "progress.log"
    with open(PROG_FILE, "w", encoding="utf-8") as fh:
        fh.write(f"# io_e2e start {datetime.now().isoformat(timespec='seconds')}\n")
    for d in ("data", "output/excel", "output/reports", "logs"):
        (WORK / d).mkdir(parents=True, exist_ok=True)
    db_path = WORK / "isolated.db"

    port = _find_free_port()
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ)
    env.update({
        "THIMBLE_DB_PATH": str(db_path),
        "THIMBLE_DATA_DIR": str(WORK / "data"),
        "THIMBLE_OUTPUT_DIR": str(WORK / "output" / "excel"),
        "THIMBLE_REPORT_DIR": str(WORK / "output" / "reports"),
        "THIMBLE_LOG_PATH": str(WORK / "logs" / "server.log"),
        "THIMBLE_PORT": str(port),
        "THIMBLE_DESKTOP_INSTANCE": "qt-io-e2e",
    })
    # 明确不迁移历史数据
    env.pop("THIMBLE_MIGRATE_LEGACY", None)
    env.pop("THIMBLE_LEGACY_DATA_DIRS", None)

    creation = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    proc = subprocess.Popen(
        [str(EXE)], cwd=str(QT_ROOT), env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=creation,
    )
    log("backend_launch", pid=proc.pid, base=base, exe=str(EXE))

    try:
        if not _wait_health(base):
            out = proc.stdout.read(2000) if proc.poll() is None else b""
            RESULT["errors"].append("后端健康检查超时")
            print("STDOUT:", out.decode("utf-8", "replace")[:1000])
            return
        log("health", ok=True)

        # 1) 建管理员（空库才允许）
        try:
            h, body = _post(f"{base}/api/auth/setup", {
                "username": "iotest", "password": "iotest123", "display_name": "IO测试",
            })
            log("auth_setup", status=body.get("ok"), detail=body)
        except Exception as exc:
            RESULT["errors"].append(f"setup失败: {exc}")

        # 2) 登录拿 cookie
        cookie = None
        try:
            h, body = _post(f"{base}/api/auth/login", {
                "username": "iotest", "password": "iotest123",
            })
            sc = h.get("Set-Cookie", "")
            if "thimble_session=" in sc:
                cookie = "thimble_session=" + sc.split("thimble_session=")[1].split(";")[0]
            log("auth_login", ok=body.get("ok"), has_cookie=bool(cookie))
        except Exception as exc:
            RESULT["errors"].append(f"login失败: {exc}")
            return

        if not cookie:
            RESULT["errors"].append("未拿到会话 cookie，后续需鉴权接口无法继续")
            return

        # 3) 导入前计数
        before = _count_findings(db_path)
        log("findings_before", count=before)

        # 4) 导入真实 xlsx（走 /api/import-excel，后端按磁盘路径读盘）
        #    blank_indication_policy 传 "review" 等价于用户在“空白三字符”对话框选了
        #    “逐组人工确认/继续”，跳过交互等待、真正落库（空字符串会触发 check 阶段
        #    发现空白三字符后 wait_for_confirmation 暂停，导致 inserted=0）。
        try:
            h, body = _post(f"{base}/api/import-excel", {
                "path": str(REAL_XLSX), "blank_indication_policy": "review", "mapping": None,
            }, cookie=cookie, timeout=300)
            log("import_excel", response=body)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            RESULT["errors"].append(f"import HTTP {exc.code}: {detail}")
        except Exception as exc:
            RESULT["errors"].append(f"import异常: {exc}")

        # 5) 导入后计数 + 取 (outage,unit) 与可对比单元
        after = _count_findings(db_path)
        pairs, multi = _pairs(db_path)
        log("findings_after", count=after, delta=(after - before if isinstance(after, int) and isinstance(before, int) else None), top_pairs=pairs, multi_outage_units=multi)

        # 6) 导出检验报告单 docx
        if pairs:
            outage, unit, _ = pairs[0]
            try:
                h, body = _post(f"{base}/api/export-report", {
                    "outage": outage, "unit": int(unit), "metadata": {}, "finding_ids": [],
                }, cookie=cookie, timeout=120)
                du = body.get("download_url")
                if du:
                    hh, buf = _get(f"{base}{du}", cookie=cookie)
                    out = WORK / body.get("filename", "report.docx")
                    out.write_bytes(buf)
                    ok, info = _verify_office(buf, ["word/document.xml"])
                    log("export_report_docx", url=du, bytes=len(buf), saved=str(out), valid=ok, info=info)
                else:
                    log("export_report_docx", url=None, response=body)
            except Exception as exc:
                RESULT["errors"].append(f"export-report失败: {exc}")

        # 7) 导出综合台账 xlsx（全量）
        try:
            h, body = _post(f"{base}/api/data-ledger/export", {}, cookie=cookie, timeout=120)
            du = body.get("download_url")
            if du:
                hh, buf = _get(f"{base}{du}", cookie=cookie)
                out = WORK / body.get("filename", "ledger.xlsx")
                out.write_bytes(buf)
                ok, info = _verify_office(buf, ["xl/workbook.xml", "xl/"])
                log("export_ledger_xlsx", url=du, bytes=len(buf), saved=str(out), valid=ok, info=info, rows=body.get("rows"))
            else:
                log("export_ledger_xlsx", url=None, response=body)
        except Exception as exc:
            RESULT["errors"].append(f"export-ledger失败: {exc}")

        # 8) 导出检验结果比对表 docx（需同单元>=2 大修）
        if multi:
            unit = multi[0][0]
            c = sqlite3.connect(str(db_path))
            outs = [r[0] for r in c.execute(
                "SELECT DISTINCT outage FROM findings WHERE is_deleted=0 AND unit_id=? ORDER BY outage", (unit,)
            ).fetchall()]
            c.close()
            if len(outs) >= 2:
                try:
                    h, body = _post(f"{base}/api/export-comparison", {
                        "old": outs[0], "new": outs[1], "unit": int(unit),
                    }, cookie=cookie, timeout=120)
                    du = body.get("download_url")
                    if du:
                        hh, buf = _get(f"{base}{du}", cookie=cookie)
                        out = WORK / body.get("filename", "comparison.docx")
                        out.write_bytes(buf)
                        ok, info = _verify_office(buf, ["word/document.xml"])
                        log("export_comparison_docx", unit=unit, old=outs[0], new=outs[1], bytes=len(buf), saved=str(out), valid=ok, info=info)
                    else:
                        log("export_comparison_docx", url=None, response=body)
                except Exception as exc:
                    RESULT["errors"].append(f"export-comparison失败: {exc}")
            else:
                log("export_comparison_docx", skipped="该单元大修数<2")
        else:
            log("export_comparison_docx", skipped="无同单元多大修数据")

    finally:
        # 关闭后端
        try:
            subprocess.run(
                [str(Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "taskkill.exe"),
                 "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    out_json = WORK / "io_e2e.json"
    out_json.write_text(json.dumps(RESULT, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n==== IO E2E RESULT ====")
    print(json.dumps(RESULT, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
