"""Verify frozen native code and visual assets against the current sources."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import types

from PyInstaller.archive.readers import CArchiveReader


def normalized(code):
    if isinstance(code, types.CodeType):
        return code.replace(co_filename="<source>",
                            co_consts=tuple(normalized(item) for item in code.co_consts))
    return code


def verify(executable, root):
    archive = CArchiveReader(str(executable))
    pyz = archive.open_embedded_archive(next(name for name in archive.toc if name.endswith(".pyz")))
    errors, modules, resources = [], [], []
    for name in sorted(pyz.toc):
        if not name.startswith("qt_shell."):
            continue
        source = root / (name.replace(".", "/") + ".py")
        if not source.is_file():
            continue
        frozen = pyz.extract(name)
        current = compile(source.read_bytes(), str(source), "exec", dont_inherit=True, optimize=0)
        if normalized(frozen) != normalized(current):
            errors.append(f"stale code: {name}")
        modules.append(name)
    required = {"qt_shell.native_notifications", "qt_shell.native_charts", "qt_shell.native_geometry",
                "qt_shell.native_import", "qt_shell.native_report_view", "qt_shell.native_windows",
                "qt_shell.native_plate_texture"}
    errors.extend(f"missing module: {name}" for name in sorted(required - set(modules)))
    internal = executable.parent / "_internal"
    pairs = [(root / "qt_shell/native_model.qml", internal / "qt_shell/native_model.qml"),
             (root / "qt_shell/model_assets/structure.json", internal / "qt_shell/model_assets/structure.json")]
    for folder, destination in (
        (root / "qt_shell/shaders", internal / "qt_shell/shaders"),
        (root / "qt_shell/assets", internal / "qt_shell/assets"),
        (root / "src/desktop-ui/assets/icons", internal / "native_resources/assets/icons"),
        (root / "src/desktop-ui/visualizations/reference-thimble/data",
         internal / "native_resources/visualizations/reference-thimble/data"),
    ):
        pairs.extend((source, destination / source.relative_to(folder))
                     for source in folder.rglob("*") if source.is_file())
    for source, destination in pairs:
        if not destination.is_file() or hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(destination.read_bytes()).digest():
            errors.append(f"missing/stale asset: {source.relative_to(root)}")
        resources.append(str(source.relative_to(root)))
    browser = [str(path.relative_to(executable.parent)) for path in executable.parent.rglob("*")
               if path.is_file() and any(term in str(path.relative_to(executable.parent)).lower()
                                         for term in ("webengine", "webchannel", "chromium"))]
    errors.extend(f"browser payload: {name}" for name in browser)
    return {"passed": not errors, "errors": errors, "native_modules": len(modules),
            "visual_resources": len(resources), "browser_files": len(browser)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify(args.executable.resolve(), Path(__file__).resolve().parents[1])
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
