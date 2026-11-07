from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

try:
    from PyInstaller.archive.readers import CArchiveReader
except ImportError as exc:
    raise SystemExit(
        "PyInstaller is required to verify the backend bundle; run through build-backend.ps1."
    ) from exc


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def verify(ui_dir: Path, executable: Path) -> list[str]:
    ui_dir = ui_dir.resolve()
    archive = CArchiveReader(str(executable.resolve()))
    prefix = "src/desktop-ui/"
    packaged = {
        normalized[len(prefix):]: name
        for name in archive.toc
        if (normalized := name.replace("\\", "/")).startswith(prefix)
    }
    errors: list[str] = []

    for source in sorted(path for path in ui_dir.rglob("*") if path.is_file()):
        relative = source.relative_to(ui_dir).as_posix()
        if relative not in packaged:
            errors.append(f"missing: {relative}")
            continue
        if digest(source.read_bytes()) != digest(archive.extract(packaged[relative])):
            errors.append(f"stale or changed: {relative}")

    source_files = {
        path.relative_to(ui_dir).as_posix()
        for path in ui_dir.rglob("*")
        if path.is_file()
    }
    for relative in sorted(packaged.keys() - source_files):
        errors.append(f"unexpected: {relative}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify packaged Qt backend UI resources.")
    parser.add_argument("--ui", type=Path, required=True)
    parser.add_argument("--exe", type=Path, required=True)
    args = parser.parse_args()

    errors = verify(args.ui, args.exe)
    if errors:
        print("Backend UI resource verification failed:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    count = sum(1 for path in args.ui.rglob("*") if path.is_file())
    print(f"Verified {count} packaged UI resources against source.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
