"""阶段 0 只读基线采集。

严格约束：
- 不创建/修改/删除 APP 下任何文件；
- 不打开（写）正式业务库，只读计算指纹；
- 所有产物只写入 QT/验证/02_基线与对拍/。
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path("D:/work-projects/在役检查系统-指套管数据管理工具")
APP = ROOT / "01_当前软件" / "软件正式版_20261021"
QT = ROOT / "08_Qt移植版"
OUT = QT / "验证" / "02_基线与对拍"
OUT.mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprint_tree(base: Path) -> dict:
    if not base.is_dir():
        return {"exists": False, "file_count": 0, "files": {}}
    files = sorted(p for p in base.rglob("*") if p.is_file())
    result = {}
    for p in files:
        try:
            result[str(p.relative_to(base)).replace("\\", "/")] = sha256_file(p)
        except OSError as exc:
            result[str(p.relative_to(base)).replace("\\", "/")] = "ERROR:" + str(exc)
    return {"exists": True, "file_count": len(files), "files": result}


def write_json(name: str, payload) -> None:
    target = OUT / name
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", target.name, target.stat().st_size, "bytes")


def main() -> int:
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    print("BASELINE", stamp)

    # 1) 源码与后端产物指纹
    fingerprints = {"generated_at": stamp, "app_root": str(APP), "trees": {}}
    for rel in ("src/desktop-ui", "src/backend", "src/desktop", "assets", "scripts", "tests", "docs", ".vendor"):
        fingerprints["trees"][rel] = fingerprint_tree(APP / rel)
        print("TREE", rel, fingerprints["trees"][rel]["file_count"], "files")
    for rel in ("build/backend/thimble-backend.exe", "package.json", "server.py", "启动正式版.cmd", "启动指套管软件.cmd"):
        p = APP / rel
        fingerprints["trees"][rel] = (
            {"exists": True, "size": p.stat().st_size, "sha256": sha256_file(p)}
            if p.is_file() else {"exists": False}
        )
        print("FILE", rel, fingerprints["trees"][rel].get("sha256", "-")[:16])
    write_json("基线指纹.json", fingerprints)

    # 2) API 路由清单（纯文本静态抽取，不导入后端）
    server_py = APP / "src/backend/server.py"
    text = server_py.read_text(encoding="utf-8", errors="replace")
    routes = set()
    for pattern in (
        r'parsed\.path\s*==\s*["\'](/api/[A-Za-z0-9_./-]+)["\']',
        r'parsed\.path\.startswith\(\s*["\'](/api/[A-Za-z0-9_./-]+)["\']',
        r'\bpath\s*==\s*["\'](/api/[A-Za-z0-9_./-]+)["\']',
        r'url\.path\s*==\s*["\'](/api/[A-Za-z0-9_./-]+)["\']',
    ):
        routes.update(re.findall(pattern, text))
    # 兜底：所有字面量 /api/ 路径（含前端 fetch 用到的）
    for p in [APP / "src/desktop-ui/app.js"] + sorted((APP / "src/desktop-ui").rglob("*.js"))[:0]:
        if p.is_file():
            routes.update(re.findall(r'["\'](/api/[A-Za-z0-9_./-]+)["\']', p.read_text(encoding="utf-8", errors="replace")))
    route_list = sorted(routes)
    write_json("api_routes.json", {
        "generated_at": stamp,
        "source": str(server_py),
        "count": len(route_list),
        "routes": route_list,
    })
    print("API ROUTES", len(route_list))

    # 3) 截图矩阵（只列目录，不复制、不改动）
    shot_sources = [
        ROOT / "04_开发归档/04_开发过程记录/重新遍历截图_20261101",
        ROOT / "04_开发归档/04_开发过程记录/图标语义批次截图_20261031",
    ]
    rows = []
    for src in shot_sources:
        if not src.is_dir():
            print("MISSING SHOT DIR", src)
            continue
        for shot in sorted(src.glob("*.png")):
            name = shot.name
            stem = shot.stem
            theme = "dark" if ("dark" in stem.lower() or "暗色" in stem or "夜间" in stem) else "light"
            size = ""
            m = re.search(r"(800|1100|1440)", stem)
            if m:
                size = m.group(1)
            rows.append({
                "id": f"{len(rows)+1:02d}",
                "source_dir": str(src.relative_to(ROOT)).replace("\\", "/"),
                "filename": name,
                "stem": stem,
                "theme_hint": theme,
                "size_hint": size,
                "bytes": shot.stat().st_size,
            })
    matrix = OUT / "基线矩阵.csv"
    with matrix.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["id", "source_dir", "filename", "stem", "theme_hint", "size_hint", "bytes"])
        writer.writeheader()
        writer.writerows(rows)
    print("WROTE", matrix.name, len(rows), "rows")

    # 4) Git 状态快照（只读）
    git_status = subprocess.run(
        ["git", "-C", str(APP), "status", "--porcelain"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    head = subprocess.run(
        ["git", "-C", str(APP), "log", "-1", "--oneline"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    snapshot = "HEAD: " + head.stdout.strip() + "\n\n" + git_status.stdout
    (OUT / "git_status_基线.txt").write_text(snapshot, encoding="utf-8")
    print("GIT modified entries", len([x for x in git_status.stdout.splitlines() if x.strip()]))

    # 5) 正式业务库只读指纹
    db_dir = ROOT / "06_软件运行数据/开发数据库"
    db = db_dir / "thimble.db"
    db_info = {"generated_at": stamp, "path": str(db), "files": {}}
    for p in sorted(db_dir.glob("thimble.db*")):
        db_info["files"][p.name] = {"size": p.stat().st_size, "sha256": sha256_file(p)}
        print("DB FILE", p.name, p.stat().st_size, db_info["files"][p.name]["sha256"][:16])
    write_json("正式库基线指纹.json", db_info)

    # 6) 结论
    summary = [
        "# 阶段 0 基线采集结论",
        "",
        "- 采集时间：" + stamp,
        "- APP 路径：" + str(APP),
        "- 产物目录：" + str(OUT),
        "- 源码树指纹：" + ", ".join(
            f"{k}={v.get('file_count', 1)}" for k, v in fingerprints["trees"].items()
        ),
        "- API 路由（静态抽取）：" + str(len(route_list)) + " 条",
        "- 截图基线矩阵：" + str(len(rows)) + " 张",
        "- APP git 未提交条目：" + str(len([x for x in git_status.stdout.splitlines() if x.strip()])) + " 项（既有用户改动，全程不动）",
        "- 正式库 thimble.db：" + str(db_info["files"].get("thimble.db", {}).get("size", "-")) + " 字节，wal=" + str(db_info["files"].get("thimble.db-wal", {}).get("size", "-")),
        "",
        "## 未执行项（后续补）",
        "- 原版冷启动性能基线：直接跑 ROOT/启动软件正式版_20261021.cmd 会让后端对正式库执行 init_db/自动备份，",
        "  为守住「不动正式库」红线，改在阶段 1 复制出隔离库后，用 THIMBLE_USER_DATA_DIR 指向隔离目录再采集。",
        "- Chromium 能力表：待 PySide6 安装完成后由 capability_probe.py 实测。",
        "",
        "## 合规声明",
        "本脚本对 APP 仅做读取与 git 只读查询，未创建/修改/删除任何 APP 文件；未连接或写入正式业务库。",
    ]
    (OUT / "基线采集结论.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
