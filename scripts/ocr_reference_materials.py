"""Offline, resumable OCR of reference images and scanned PDF pages.

Recognition is reference evidence only, never automatically imported as inspection data.
"""
import json
import os
from pathlib import Path

import fitz
import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "reference-review"


def main():
    engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)
    manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest:
        if entry.get("type") not in {"image", "pdf"}:
            continue
        target = OUT / (entry["sha256"][:16] + ".ocr.json")
        if target.exists():
            continue
        source = ROOT / entry["path"]
        result = {"source": entry["path"], "engine": "RapidOCR offline", "pages": []}
        try:
            if entry["type"] == "pdf":
                document = fitz.open(source)
                for index, page in enumerate(document):
                    text = page.get_text(sort=True)
                    if len(text.strip()) >= 100:
                        result["pages"].append({"page": index + 1, "method": "text", "text": text})
                        continue
                    scale = min(2.0, 2100 / max(page.rect.width, page.rect.height))
                    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    items, _ = engine(np.asarray(image))
                    result["pages"].append({"page": index + 1, "method": "ocr", "text": "\n".join(x[1] for x in items or []), "confidence_min": min((x[2] for x in items or []), default=None)})
                    print(f"PAGE {index + 1}/{len(document)} {source.name}", flush=True)
                document.close()
            else:
                with Image.open(source) as original:
                    image = original.convert("RGB")
                    image.thumbnail((2200, 8000))
                    items, _ = engine(np.asarray(image))
                    result["pages"].append({"page": 1, "method": "ocr", "text": "\n".join(x[1] for x in items or []), "confidence_min": min((x[2] for x in items or []), default=None)})
            result["status"] = "recognized-review-required"
        except Exception as error:
            result.update(status="ocr-error", error=str(error))
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"DONE {entry['path']} {result['status']}", flush=True)


if __name__ == "__main__":
    main()
