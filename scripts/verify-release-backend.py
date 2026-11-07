"""Reject stale or unwanted files embedded in the frozen backend."""
from pathlib import Path
import sys

from PyInstaller.archive.readers import CArchiveReader


def main() -> int:
    archive = CArchiveReader(str(Path(sys.argv[1]).resolve()))
    names = [name.replace("\\", "/") for name in archive.toc]
    forbidden_suffixes = (".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3",
                          ".log", ".csv", ".xls", ".xlsx", ".xlsm")
    violations = [
        name for name in names
        if (name.startswith("docs/") and not name.startswith("docs/使用手册/"))
        or name.lower().endswith(forbidden_suffixes)
        or any(part.casefold() in {"user-data", ".user-data", "tests", "__pycache__"}
               for part in name.split("/"))
    ]
    if not any(name.startswith("docs/使用手册/") for name in names):
        violations.append("missing embedded user manuals")
    if violations:
        print("Backend release content verification failed:", file=sys.stderr)
        for name in violations:
            print(f"  {name}", file=sys.stderr)
        return 1
    print("Backend release content verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
