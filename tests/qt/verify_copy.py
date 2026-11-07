"""阶段 1 校验：QT 副本与 APP 基线逐文件指纹一致，且无联接/无 node_modules。

只读 APP；产物只写 QT/验证/。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path("D:/work-projects/在役检查系统-指套管数据管理工具")
APP = ROOT / "01_当前软件" / "软件正式版_20261021"
QT = ROOT / "08_Qt移植版"
OUT = QT / "验证" / "02_基线与对拍"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    baseline = json.loads((OUT / "基线指纹.json").read_text(encoding="utf-8"))
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "checked": 0, "matched": 0, "missing": [], "mismatch": [],
        "trees": {},
    }
    for rel, spec in baseline["trees"].items():
        if "files" in spec and isinstance(spec["files"], dict):
            base = QT / rel
            checked = matched = 0
            for name, expected in spec["files"].items():
                p = base / name
                checked += 1
                if not p.is_file():
                    report["missing"].append(rel + "/" + name)
                    continue
                actual = sha256_file(p)
                if actual == expected:
                    matched += 1
                else:
                    report["mismatch"].append({"path": rel + "/" + name, "expected": expected, "actual": actual})
            report["trees"][rel] = {"checked": checked, "matched": matched}
            report["checked"] += checked
            report["matched"] += matched
        elif "sha256" in spec:
            p = QT / rel
            report["checked"] += 1
            if not p.is_file():
                report["missing"].append(rel)
            elif sha256_file(p) == spec["sha256"]:
                report["matched"] += 1
                report["trees"][rel] = {"checked": 1, "matched": 1}
            else:
                report["mismatch"].append({"path": rel, "expected": spec["sha256"], "actual": sha256_file(p)})

    # 数据库副本
    db_baseline = json.loads((OUT / "正式库基线指纹.json").read_text(encoding="utf-8"))
    expected_db = db_baseline["files"]["thimble.db"]["sha256"]
    db_copy = QT / "user-data/data/thimble.db"
    db_ok = db_copy.is_file() and sha256_file(db_copy) == expected_db
    report["database_copy"] = {
        "path": str(db_copy),
        "exists": db_copy.is_file(),
        "size": db_copy.stat().st_size if db_copy.is_file() else 0,
        "sha256": sha256_file(db_copy) if db_copy.is_file() else "",
        "matches_source": db_ok,
    }
    # 只读完整性检查（ro URI，避免创建 wal/shm）
    if db_ok:
        try:
            con = sqlite3.connect("file:" + str(db_copy).replace("\\", "/") + "?mode=ro", uri=True)
            report["database_copy"]["integrity_check"] = con.execute("PRAGMA integrity_check").fetchone()[0]
            report["database_copy"]["table_count"] = con.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0]
            con.close()
        except Exception as exc:
            report["database_copy"]["integrity_check"] = "ERROR: " + str(exc)

    # 合规检查
    report["compliance"] = {
        "qt_has_node_modules": (QT / "node_modules").exists(),
        "qt_has_app_venv": (QT / ".venv").exists(),
        "qt_root_junctions": [
            p.name for p in QT.iterdir()
            if p.is_symlink() or (p.is_dir() and p.stat().st_dev != QT.stat().st_dev)
        ],
        "excluded_junction_names_present": [
            n for n in ("data", "output", ".user-data", "release", "tmp", "项目资料") if (QT / n).exists()
        ],
    }
    # 原库原件指纹未变
    report["source_db_unchanged"] = (
        sha256_file(ROOT / "06_软件运行数据/开发数据库/thimble.db") == expected_db
    )

    report["passed"] = (
        not report["missing"] and not report["mismatch"]
        and db_ok and report["source_db_unchanged"]
        and not report["compliance"]["qt_has_node_modules"]
        and not report["compliance"]["excluded_junction_names_present"]
    )
    (OUT / "复制校验报告.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 阶段 1 复制校验报告", "",
        "- 时间：" + report["generated_at"],
        "- 逐文件指纹：" + str(report["matched"]) + " / " + str(report["checked"]) + " 一致",
        "- 缺失：" + str(len(report["missing"])) + "，不一致：" + str(len(report["mismatch"])),
        "- 数据库副本指纹一致：" + str(db_ok),
        "- 副本完整性：" + str(report["database_copy"].get("integrity_check", "-")),
        "- 副本表数：" + str(report["database_copy"].get("table_count", "-")),
        "- 原正式库未变：" + str(report["source_db_unchanged"]),
        "- QT 无 node_modules / 无 APP 联接：" + str(not report["compliance"]["qt_has_node_modules"] and not report["compliance"]["excluded_junction_names_present"]),
        "- **总判定：" + ("通过" if report["passed"] else "未通过") + "**", "",
        "## 各树", "",
    ]
    for k, v in report["trees"].items():
        lines.append("- " + k + ": " + str(v["matched"]) + " / " + str(v["checked"]))
    (OUT / "复制校验结论.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("checked", report["checked"], "matched", report["matched"])
    print("missing", len(report["missing"]), "mismatch", len(report["mismatch"]))
    print("db_copy_matches", db_ok, "source_unchanged", report["source_db_unchanged"])
    print("PASSED", report["passed"])
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
