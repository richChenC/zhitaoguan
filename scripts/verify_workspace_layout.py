"""Read-only verification of classified paths, launchers and the business DB."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
CLASSIFIED_TARGET_OVERRIDES = {
    # The complete model project is retained in the software reference set;
    # its dated source snapshot remains in the development archive.
    "指套管三维模型_完整工程": Path(
        "02_项目原始资料/06_当前软件引用资料/04_三维模型工程/指套管三维模型_完整工程"
    ),
}


def verify(workspace: Path) -> dict:
    workspace = workspace.resolve(strict=True)
    latest, hashes = {}, {}
    logs = sorted((workspace / "04_开发归档/05_整理记录").glob("目录整理_*.jsonl"))
    if not logs:
        raise ValueError("No workspace classification logs found")
    for log in logs:
        for line in log.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            # Dry runs are not evidence that a planned operation was applied.
            if row["status"] == "planned":
                continue
            latest[row["old"]] = row
            if row.get("sha256"):
                hashes[row["old"]] = row["sha256"]
    checks, pending = [], []
    for name, row in latest.items():
        old, new = workspace / name, workspace / row["new"]
        if name in CLASSIFIED_TARGET_OVERRIDES:
            new = workspace / CLASSIFIED_TARGET_OVERRIDES[name]
        if not old.is_relative_to(workspace) or not new.is_relative_to(workspace):
            raise ValueError(f"Unexpected log path: {name}")
        if row["status"] == "temporary_lock_gone" and Path(name).name.startswith("~$"):
            checks.append({"old": name, "new": row["new"], "status": row["status"]})
            continue
        if Path(name).name.startswith("~$") and not new.exists():
            checks.append({"old": name, "new": row["new"], "status": "temporary_lock_gone"})
            continue
        if row["status"] not in {"classified_in_use", "moved", "already_organized"}:
            raise ValueError(f"Unresolved classification: {row}")
        if not new.exists():
            raise ValueError(f"Classified target missing: {new}")
        if row["compatibility"] and old.exists() and old.resolve() != new.resolve():
            raise ValueError(f"Compatibility path points to a different target: {old}")
        if old.exists():
            pending.append(name)
        if name in hashes and new.is_file():
            digest = hashlib.sha256(new.read_bytes()).hexdigest().upper()
            if digest != hashes[name]:
                raise ValueError(f"Moved file content changed: {new}")
        checks.append({"old": name, "new": str(new.relative_to(workspace)), "status": row["status"]})

    baseline = json.loads((ROOT / "output/migration/verification.json").read_text(encoding="utf-8"))
    launcher = workspace / "启动Qt主版本.cmd"
    if launcher.read_bytes() != (ROOT / "scripts/start-current-version.cmd").read_bytes():
        raise ValueError("Workspace launcher differs from the version-controlled template")
    if set(workspace.glob("*.cmd")) != {launcher}:
        raise ValueError("Workspace contains additional software launcher entries")
    shortcut_files = [*workspace.glob("*.lnk"), *workspace.glob("*.url")]
    if shortcut_files:
        raise ValueError(f"Workspace contains shortcut entries: {shortcut_files}")
    with sqlite3.connect((ROOT / "data/thimble.db").as_uri() + "?mode=ro", uri=True) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        counts = {table: db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                  for table in ("findings", "tube_states")}
    if integrity != "ok":
        raise ValueError(f"Business database integrity: {integrity}")
    return {
        "created_at": datetime.now().isoformat(), "ok": True,
        "physical_relocation_complete": not pending,
        "checked_entries": len(checks), "pending_physical_moves": pending,
        "small_file_sha256_checks": len(hashes),
        "historical_baseline_file_records": len(baseline["files"]),
        "database_integrity": integrity, "database_rows": counts,
        "current_launcher": str(launcher), "items": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=ROOT.parent.parent)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "output/migration/workspace-organization-verification_20261021.json")
    args = parser.parse_args()
    report = verify(args.workspace)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "items"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
