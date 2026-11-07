"""Read-only source inventory and extraction; never execute supplied binaries."""
import hashlib
import json
import os
import re
import struct
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "reference-review"
sys.path.insert(0, str(ROOT / "tmp_pylibs"))
sys.path.insert(0, str(ROOT / "src" / "tools"))


def extract(path):
    ext = path.suffix.lower()
    if ext in {".md", ".txt", ".html", ".js", ".json", ".step", ".stp", ".css"}:
        text = path.read_text(encoding="utf-8", errors="replace")
        if ext == ".html":
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(text, "html.parser")
            for node in soup(["script", "style"]): node.decompose()
            text = soup.get_text("\n", strip=True)
        if ext in {".step", ".stp"}:
            return {"type": "cad", "header": text[:1600], "entities": len(re.findall(r"^#\d+", text, re.M)), "status": "indexed-not-geometrically-validated"}
        if ext == ".json":
            data = json.loads(text)
            return {"type": "json", "keys": list(data)[:40] if isinstance(data, dict) else len(data), "text": text if len(text) < 100000 else "", "status": "extracted"}
        return {"type": "text", "text": text, "status": "extracted"}
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if "word/document.xml" in names:
                root = ET.fromstring(archive.read("word/document.xml"))
                ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                lines = ["".join(p.itertext()) for p in root.findall(".//w:p", ns)]
                media = [n for n in names if n.startswith("word/media/")]
                return {"type": "docx", "text": "\n".join(lines), "media": media, "status": "extracted"}
            if "xl/workbook.xml" in names:
                import openpyxl
                with path.open("rb") as handle:
                    book = openpyxl.load_workbook(handle, read_only=True, data_only=True)
                    sheets = []
                    for ws in book:
                        values = [{"row": i, "cells": [str(v) if v is not None else None for v in row]} for i, row in enumerate(ws.iter_rows(values_only=True), 1) if any(v is not None for v in row)]
                        sheets.append({"name": ws.title, "rows": ws.max_row, "columns": ws.max_column, "data": values})
                    return {"type": "xlsx", "sheets": sheets, "status": "extracted"}
            slides = sorted([n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)], key=lambda n: int(re.search(r"slide(\d+)", n).group(1)))
            if slides:
                data = []
                for name in slides:
                    root = ET.fromstring(archive.read(name))
                    lines = [n.text or "" for n in root.iter() if n.tag.endswith("}t")]
                    data.append({"slide": name, "text": "\n".join(lines)})
                charts = []
                for n in names:
                    if re.fullmatch(r"ppt/charts/chart\d+\.xml", n):
                        root = ET.fromstring(archive.read(n))
                        charts.append({"name": n, "text": " | ".join(t.text or "" for t in root.iter() if t.tag.endswith(("}v", "}f")))})
                return {"type": "pptx", "slides": data, "charts": charts, "status": "extracted"}
    if ext == ".pdf":
        import fitz
        with fitz.open(path) as doc:
            pages = [{"page": i + 1, "text": p.get_text(sort=True), "images": len(p.get_images())} for i, p in enumerate(doc)]
        return {"type": "pdf", "pages": pages, "status": "needs-visual-or-ocr" if any(len(p["text"].strip()) < 40 for p in pages) else "extracted"}
    if ext in {".doc", ".wps"}:
        from _extract_doc import extract_text
        return {"type": "legacy-word", "text": extract_text(str(path)), "status": "legacy-extraction-review-required"}
    if ext == ".ppt":
        import olefile
        with olefile.OleFileIO(str(path)) as ole:
            stream = ole.openstream("PowerPoint Document").read()
        def records(data):
            parts, offset = [], 0
            while offset + 8 <= len(data):
                ver, typ, length = struct.unpack_from("<HHI", data, offset)
                body = data[offset + 8:offset + 8 + length]
                if length > len(data) - offset - 8: break
                if ver & 15 == 15: parts.extend(records(body))
                elif typ == 4000: parts.append(body.decode("utf-16-le", errors="replace"))
                elif typ == 4008: parts.append(body.decode("gb18030", errors="replace"))
                offset += 8 + length
            return parts
        return {"type": "legacy-ppt", "text": "\n".join(records(stream)), "status": "extracted-text-visual-pending"}
    if ext == ".xls":
        try:
            import xlrd
            book = xlrd.open_workbook(str(path))
            return {"type": "xls", "sheets": [{"name": s.name, "rows": s.nrows, "columns": s.ncols, "data": [{"row": i + 1, "cells": s.row_values(i)} for i in range(s.nrows)]} for s in book.sheets()], "status": "extracted"}
        except ImportError:
            return {"type": "xls", "status": "reader-required"}
    if ext in {".png", ".jpg", ".jpeg", ".wmf"}:
        from PIL import Image
        with Image.open(path) as image:
            return {"type": "image", "size": list(image.size), "status": "visual-pending"}
    return {"type": ext, "status": "indexed-not-executed"}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest, seen = [], {}
    for folder in ("项目资料/02_业务参考资料/孔姐发的", "项目资料/01_需求与记忆/记忆"):
        for parent, dirs, files in os.walk(ROOT / folder):
            dirs[:] = [d for d in dirs if d not in {"node_modules", "lib", "occt", "__pycache__", ".git"}]
            for name in sorted(files):
                path = Path(parent) / name
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                row = {"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size, "sha256": digest}
                if digest in seen:
                    row.update(status="duplicate", duplicate_of=seen[digest])
                else:
                    seen[digest] = row["path"]
                    try: result = extract(path)
                    except Exception as error: result = {"status": "extraction-error", "error": str(error)}
                    row.update({k: v for k, v in result.items() if k in {"status", "type", "size", "error"}})
                    output = OUT / (digest[:16] + ".json")
                    output.write_text(json.dumps({"source": row["path"], **result}, ensure_ascii=False, indent=2), encoding="utf-8")
                    row["extracted"] = output.name
                manifest.append(row)
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    from collections import Counter
    print(json.dumps({"files": len(manifest), "unique": len(seen), "statuses": dict(Counter(r["status"] for r in manifest))}, ensure_ascii=False))


if __name__ == "__main__": main()
