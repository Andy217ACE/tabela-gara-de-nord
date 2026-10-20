# © 2026 Andy217Ace
"""Dev-time helper: draw the PNG app icons from the geometry of web/icons/icon.svg.

    python scripts/make_icons.py

Writes web/icons/icon-192.png, icon-512.png (purpose "any", rounded corners like the SVG)
and icon-maskable-512.png (full-bleed background, glyph inside the 80 % safe zone).
Uses Pillow only (already a dependency); the output PNGs are committed, nothing runs at
runtime. Drawn at 4x and downscaled for smooth edges.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ICONS = Path(__file__).resolve().parent.parent / "web" / "icons"
BG = "#0a0d12"
FG = "#ffb547"
SS = 4  # supersampling


def draw(size: int, *, maskable: bool) -> Image.Image:
    big = size * SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    unit = big / 512
    if maskable:
        d.rectangle([0, 0, big, big], fill=BG)
        scale, off = unit * 0.72, big * 0.14  # glyph shrunk into the safe zone
    else:
        d.rounded_rectangle([0, 0, big - 1, big - 1], radius=112 * unit, fill=BG)
        scale, off = unit, 0.0

    def p(x: float, y: float) -> tuple[float, float]:
        return (off + x * scale, off + y * scale)

    w = round(26 * scale)
    # body of the board: rounded rect 136..376 x 112..360, r=40
    d.rounded_rectangle([*p(136, 112), *p(376, 360)], radius=40 * scale, outline=FG, width=w)
    for a, b in (((140, 236), (372, 236)), ((206, 170), (306, 170)),
                 ((196, 360), (154, 416)), ((316, 360), (358, 416))):
        d.line([p(*a), p(*b)], fill=FG, width=w)
        for pt in (a, b):  # round caps
            cx, cy = p(*pt)
            d.ellipse([cx - w / 2, cy - w / 2, cx + w / 2, cy + w / 2], fill=FG)
    for cx, cy in ((196, 300), (316, 300)):
        x, y = p(cx, cy)
        r = 20 * scale
        d.ellipse([x - r, y - r, x + r, y + r], fill=FG)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    for name, size, maskable in (("icon-192.png", 192, False), ("icon-512.png", 512, False),
                                 ("icon-maskable-512.png", 512, True)):
        draw(size, maskable=maskable).save(ICONS / name, optimize=True)
        print("wrote", ICONS / name)


if __name__ == "__main__":
    main()
