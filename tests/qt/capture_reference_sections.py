"""Reproduce standalone section algorithms from the read-only reference sources."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def main():
    project = Path(__file__).resolve().parents[2]
    reference = project.parent / "10_TRAEqt优化版"
    viewer = reference / "src/desktop-ui/visualizations/reference-thimble/app.js"
    earcut_file = reference / "node_modules/three/src/extras/lib/earcut.js"
    license_file = reference / "node_modules/three/LICENSE"
    source = viewer.read_text(encoding="utf-8")
    start = source.index("  const triCount", source.index("function sliceLoops("))
    end = source.index("\n/** 把若干闭环转成", start)
    slicing = source[start:end]
    slicing = slicing.replace("index.count / 3 : n / 3", "index.length / 3 : P.length / 9")
    slicing = slicing.replace("index.getX(t * 3 + k)", "index[t * 3 + k]")
    slicing = "const SEG_EPS = 1e-6, KEY_Q = 1000;\nfunction sliceLoops(P, index, px) {\n" + slicing
    earcut = earcut_file.read_text(encoding="utf-8").replace("export default ", "").replace("export function ", "function ")
    destination = project / "qt_shell/model_assets"
    for name, text in (("section-loops.js", slicing), ("earcut.js", earcut),
                       ("section-algorithms.LICENSE", license_file.read_text(encoding="utf-8"))):
        (destination / name).write_text(text, encoding="utf-8", newline="\n")
    provenance = {
        "reference_viewer": str(viewer.relative_to(reference)),
        "reference_viewer_sha256": hashlib.sha256(viewer.read_bytes()).hexdigest(),
        "earcut": "mapbox/earcut 3.0.1, from three.js 0.180.0",
        "earcut_source_sha256": hashlib.sha256(earcut_file.read_bytes()).hexdigest(),
        "adaptation": "Array input replaces BufferAttribute and identity matrix conversion; "
                      "section stitching and loop cleanup are unchanged. Earcut exports removed for QJSEngine.",
        "assets": {name: hashlib.sha256((destination / name).read_bytes()).hexdigest()
                   for name in ("section-loops.js", "earcut.js", "section-algorithms.LICENSE")},
    }
    (destination / "section-provenance.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(provenance, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
