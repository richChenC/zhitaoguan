"""Reject stale or unwanted files embedded in the frozen backend."""
from pathlib import Path
import marshal
import sys

from PyInstaller.archive.readers import CArchiveReader
from verify_native_bundle import normalized


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
    source_root = Path(__file__).resolve().parents[1] / "src/backend"
    if "server" not in archive.toc:
        violations.append("missing backend entry point")
    elif normalized(marshal.loads(archive.extract("server"))) != normalized(
            compile((source_root / "server.py").read_bytes(), "<source>", "exec", dont_inherit=True, optimize=0)):
        violations.append("stale backend entry point")
    pyz = archive.open_embedded_archive(next(name for name in archive.toc if name.endswith(".pyz")))
    checked = 0
    for name in pyz.toc:
        source = source_root / (name.replace(".", "/") + ".py")
        if source.is_file():
            checked += 1
            if normalized(pyz.extract(name)) != normalized(compile(source.read_bytes(), "<source>", "exec", dont_inherit=True, optimize=0)):
                violations.append(f"stale backend module: {name}")
    if violations:
        print("Backend release content verification failed:", file=sys.stderr)
        for name in violations:
            print(f"  {name}", file=sys.stderr)
        return 1
    print(f"Backend release content verification passed ({checked} source modules and entry point).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
