"""Read-only source/copy audit for the dated project reorganization."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
# Write the audit against the physical classified folder.  The software's
# `项目资料` junction remains only as a runtime compatibility path.
WORKSPACE_ROOT = ROOT.parent.parent
MATERIALS = WORKSPACE_ROOT / "02_项目原始资料" / "06_当前软件引用资料"
DIRECTORIES = {
    "记忆": MATERIALS / "01_需求与记忆" / "记忆",
    "孔姐发的": MATERIALS / "02_业务参考资料" / "孔姐发的",
    "测试数据": MATERIALS / "03_原始验证数据" / "测试数据",
    "指套管模型工程": MATERIALS / "04_三维模型工程" / "指套管模型工程",
    "指套管三维模型_完整工程": MATERIALS / "04_三维模型工程" / "指套管三维模型_完整工程",
    ".workbuddy": MATERIALS / "07_历史开发资料" / "开发过程" / ".workbuddy",
    "wy": MATERIALS / "07_历史开发资料" / "网页参考采集" / "wy",
    "tmp_pylibs": MATERIALS / "07_历史开发资料" / "历史调试文件" / "tmp_pylibs",
}
FILES = {
    "对话记录与记忆导出_2026-08-26.md": "01_需求与记忆/对话记录与记忆导出_2026-08-26.md",
    "TH_三字符缺失记录_20261016_101108.xlsx": "05_历史导出与验证输出/TH_三字符缺失记录_20261016_101108.xlsx",
    "导入台账_全量72次大修.xlsx": "06_台账与计划/导入台账_全量72次大修.xlsx",
    "岭澳核电厂_报告表头设置.json": "06_台账与计划/岭澳核电厂_报告表头设置.json",
    "指套管数据管理工具_年度计划表.xlsx": "06_台账与计划/指套管数据管理工具_年度计划表.xlsx",
    "_check.mjs": "07_历史开发资料/历史调试文件/_check.mjs",
    "tmp_check.mjs": "07_历史开发资料/历史调试文件/tmp_check.mjs",
    "--full-page": "07_历史开发资料/历史调试文件/历史界面截图.png",
    "新建 文本文档.html": "07_历史开发资料/网页参考采集/新建 文本文档.html",
}
SOURCE_LOCATIONS = {
    "记忆": "02_项目原始资料/01_需求与记忆/记忆",
    "孔姐发的": "02_项目原始资料/02_业务参考资料/孔姐发的",
    "测试数据": "02_项目原始资料/03_原始检测数据/测试数据",
    "指套管模型工程": "02_项目原始资料/04_三维模型工程/指套管模型工程",
    "指套管三维模型_完整工程": "04_开发归档/05_完整工程_20261021/指套管三维模型_完整工程",
    ".workbuddy": "04_开发归档/04_开发过程记录/.workbuddy",
    "wy": "04_开发归档/01_网页原型与采集/wy",
    "tmp_pylibs": "04_开发归档/02_调试脚本与临时依赖/tmp_pylibs",
    "对话记录与记忆导出_2026-08-26.md": "02_项目原始资料/01_需求与记忆/对话记录与记忆导出_2026-08-26.md",
    "TH_三字符缺失记录_20261016_101108.xlsx": "04_开发归档/03_历史导出与截图/TH_三字符缺失记录_20261016_101108.xlsx",
    "导入台账_全量72次大修.xlsx": "02_项目原始资料/05_台账与计划/导入台账_全量72次大修.xlsx",
    "岭澳核电厂_报告表头设置.json": "02_项目原始资料/05_台账与计划/岭澳核电厂_报告表头设置.json",
    "指套管数据管理工具_年度计划表.xlsx": "02_项目原始资料/05_台账与计划/指套管数据管理工具_年度计划表.xlsx",
    "_check.mjs": "04_开发归档/02_调试脚本与临时依赖/_check.mjs",
    "tmp_check.mjs": "04_开发归档/02_调试脚本与临时依赖/tmp_check.mjs",
    "--full-page": "04_开发归档/03_历史导出与截图/历史界面截图.png",
    "新建 文本文档.html": "04_开发归档/01_网页原型与采集/新建 文本文档.html",
}


def source_path(source: Path, name: str) -> Path:
    """Support both the categorized workspace and the earlier flat layout."""
    organized = source / SOURCE_LOCATIONS[name]
    return organized if organized.exists() else source / name


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-project", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "migration" / "verification.json")
    parser.add_argument("--update-group", choices=tuple(DIRECTORIES),
                        help="Recheck one actively edited source group and retain previous file hashes elsewhere.")
    options = parser.parse_args()
    source = options.source_project.resolve(strict=True)
    report = {"created_at": datetime.now().isoformat(), "source_project": str(source),
              "new_version": str(ROOT), "groups": [], "mismatches": [], "files": [],
              "skipped_temporary_files": []}
    groups = DIRECTORIES
    if options.update_group:
        previous = json.loads(options.output.read_text(encoding="utf-8"))
        if (Path(previous["source_project"]).resolve() != source
                or Path(previous["new_version"]).resolve() != ROOT):
            parser.error("Previous report belongs to a different source or destination.")
        original = source_path(source, options.update_group)

        def in_group(row):
            return Path(row["source"]).resolve().is_relative_to(original.resolve())

        previous["files"] = [row for row in previous["files"] if not in_group(row)]
        previous["mismatches"] = [row for row in previous["mismatches"] if not in_group(row)]
        previous["groups"] = [row for row in previous["groups"] if row["source"] != options.update_group]
        previous["skipped_temporary_files"] = [
            path for path in previous.get("skipped_temporary_files", [])
            if not Path(path).resolve().is_relative_to(original.resolve())]
        previous.setdefault("group_rechecks", []).append({
            "source": options.update_group, "started_at": report["created_at"]})
        report = previous
        groups = {options.update_group: DIRECTORIES[options.update_group]}

    def verify(original: Path, copied: Path) -> None:
        record = {"source": str(original), "copy": str(copied)}
        try:
            record["bytes"] = original.stat().st_size
            if not copied.is_file():
                raise ValueError("missing copy")
            if copied.stat().st_size != record["bytes"]:
                raise ValueError("file size differs")
            record["sha256"] = digest(original)
            if digest(copied) != record["sha256"]:
                raise ValueError("SHA-256 differs")
            record["status"] = "matched"
        except (OSError, ValueError) as error:
            record["status"] = str(error)
            report["mismatches"].append(record.copy())
        report["files"].append(record)

    for name, copied in groups.items():
        original = source_path(source, name)
        start = len(report["files"])
        if not original.is_dir():
            report["mismatches"].append({"source": str(original), "status": "missing source directory"})
        else:
            for path in sorted(original.rglob("*")):
                if path.is_file():
                    if path.name.startswith("~$") and path.suffix.lower() in {
                            ".xls", ".xlsx", ".doc", ".docx", ".ppt", ".pptx"}:
                        report["skipped_temporary_files"].append(str(path))
                        continue
                    verify(path, copied / path.relative_to(original))
        count = len(report["files"]) - start
        report["groups"].append({"source": name, "files": count})
        print(f"AUDIT {name}: {count} files", flush=True)
    if not options.update_group:
        for name, relative in FILES.items():
            verify(source_path(source, name), MATERIALS / relative)

    report["checked_files"] = len(report["files"])
    report["checked_bytes"] = sum(row.get("bytes", 0) for row in report["files"])
    report["ok"] = not report["mismatches"]
    report["completed_at"] = datetime.now().isoformat()
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "files": report["checked_files"],
                      "bytes": report["checked_bytes"], "mismatches": len(report["mismatches"]),
                      "output": str(options.output)}, ensure_ascii=False), flush=True)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
