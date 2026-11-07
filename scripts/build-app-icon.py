# -*- coding: utf-8 -*-
"""生成桌面多尺寸 ICO 和对应的网页 PNG/ICO。

用法（在 08_Qt移植版/ 下）：
    .venv-qt/Scripts/python.exe scripts/build-app-icon.py

≤32px 使用小尺寸简版（app-icon-small.svg），≥48px 使用主版（app-icon.svg）。
ICO 采用 PNG-in-ICO（Vista+ 支持），无需 Pillow。
"""
import struct
import sys
from pathlib import Path

QT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QT_ROOT))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ASSETS = QT_ROOT / "assets"
FULL_SVG = ASSETS / "app-icon.svg"
SMALL_SVG = ASSETS / "app-icon-small.svg"
OUT_ICO = ASSETS / "app-icon.ico"
UI_ASSETS = QT_ROOT / "src" / "desktop-ui" / "assets"

# (尺寸, 源 SVG)
SPECS = [
    (16, SMALL_SVG),
    (24, SMALL_SVG),
    (32, SMALL_SVG),
    (48, FULL_SVG),
    (64, FULL_SVG),
    (128, FULL_SVG),
    (256, FULL_SVG),
]


def render_png(svg_path: Path, size: int) -> bytes:
    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        raise RuntimeError(f"SVG 无效: {svg_path}")
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(0x00000000)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()

    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    if not image.save(buf, "PNG"):
        raise RuntimeError(f"PNG 编码失败: {svg_path} @ {size}px")
    buf.close()
    return bytes(data.data())


def build_ico(entries: list[tuple[int, bytes]]) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(entries))
    offset = 6 + 16 * len(entries)
    directory = b""
    payload = b""
    for size, png in entries:
        tag = size if size < 256 else 0  # 256 在目录项中记为 0
        directory += struct.pack("<BBBBHHII", tag, tag, 0, 0, 1, 32, len(png), offset)
        payload += png
        offset += len(png)
    return header + directory + payload


def main() -> int:
    for path in (FULL_SVG, SMALL_SVG):
        if not path.is_file():
            print(f"缺少源文件: {path}")
            return 1

    entries = []
    for size, svg in SPECS:
        png = render_png(svg, size)
        entries.append((size, png))
        print(f"  {size:>3}px <- {svg.name}  ({len(png):,} B)")

    ico = build_ico(entries)
    OUT_ICO.write_bytes(ico)
    UI_ASSETS.mkdir(parents=True, exist_ok=True)
    (UI_ASSETS / "app-icon.ico").write_bytes(ico)
    (UI_ASSETS / "app-icon.png").write_bytes(entries[-1][1])
    print(f"已生成 {OUT_ICO}  ({len(ico):,} B, {len(entries)} 档)")
    print(f"已同步网页图标到 {UI_ASSETS}")
    return 0


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    sys.exit(main())
