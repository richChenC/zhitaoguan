"""Generate the project icon in deterministic raster/vector-friendly form.

The mark combines a tube-sheet hole grid, an inspection crosshair, and one
highlighted indication. The large PNG is retained as the editable source and
the ICO contains the standard Windows shell sizes.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent
SIZE = 1024


def draw_mark(size: int = SIZE) -> Image.Image:
    scale = size / SIZE
    image = Image.new("RGBA", (size, size), (9, 36, 47, 255))
    draw = ImageDraw.Draw(image)

    def p(value: float) -> int:
        return round(value * scale)

    # A quiet engineering plate: rounded shell, rim, and four-by-four tube grid.
    draw.rounded_rectangle((p(36), p(36), p(988), p(988)), radius=p(154),
                           fill=(11, 52, 64, 255), outline=(56, 196, 202, 255),
                           width=max(2, p(18)))
    draw.rounded_rectangle((p(102), p(102), p(922), p(922)), radius=p(112),
                           fill=(13, 66, 77, 255), outline=(126, 224, 214, 255),
                           width=max(2, p(8)))

    grid_origin = 264
    step = 132
    for row in range(4):
        for col in range(4):
            cx = grid_origin + col * step
            cy = grid_origin + row * step
            r = 35
            highlighted = row == 2 and col == 3
            fill = (246, 252, 247, 255) if not highlighted else (246, 164, 77, 255)
            outline = (185, 242, 233, 255) if not highlighted else (255, 232, 158, 255)
            draw.ellipse((p(cx-r), p(cy-r), p(cx+r), p(cy+r)),
                          fill=fill, outline=outline, width=max(2, p(8)))
            # Tube inner shadow gives the small icon enough depth at 16 px.
            draw.ellipse((p(cx-13), p(cy-13), p(cx+13), p(cy+13)),
                          fill=(33, 105, 111, 255))

    # Inspection crosshair over the plate.
    center = (620, 586)
    draw.line((p(center[0]-236), p(center[1]), p(center[0]+236), p(center[1])),
              fill=(93, 237, 232, 255), width=max(2, p(13)))
    draw.line((p(center[0]), p(center[1]-236), p(center[0]), p(center[1]+236)),
              fill=(93, 237, 232, 255), width=max(2, p(13)))
    draw.ellipse((p(center[0]-84), p(center[1]-84), p(center[0]+84), p(center[1]+84)),
                 outline=(93, 237, 232, 255), width=max(2, p(13)))
    draw.ellipse((p(center[0]-18), p(center[1]-18), p(center[0]+18), p(center[1]+18)),
                 fill=(255, 193, 88, 255))

    # Small directional tick: reads as an engineering annotation, not a letter.
    draw.line((p(736), p(798), p(844), p(690)), fill=(255, 193, 88, 255),
              width=max(2, p(15)))
    draw.polygon([(p(844), p(690)), (p(795), p(699)), (p(836), p(740))],
                 fill=(255, 193, 88, 255))
    return image


def main() -> None:
    image = draw_mark()
    image.save(ROOT / "app-icon-source.png", "PNG", optimize=True)
    # Pillow writes a multi-image ICO with the standard Windows shell sizes.
    image.save(
        ROOT / "app-icon.ico",
        format="ICO",
        sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)],
    )


if __name__ == "__main__":
    main()
