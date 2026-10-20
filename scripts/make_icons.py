# © 2026 Andy217Ace
"""Dev-time helper: build every app icon from the logo artwork.

    python scripts/make_icons.py "path/to/Gara de Nord Train Board.png"

The source is the 1254x1254 logo render (rounded blue tile with a white reflection
under it). The tile is cut out with a fitted rounded-rectangle mask (plus the station
wings that stick out on the sides), then written to web/icons/ and web/:

    icon-32.png, icon-192.png, icon-512.png   purpose "any", transparent corners
    icon-maskable-512.png                      full-bleed blue, logo inside the safe zone
    apple-touch-icon.png (180)                 opaque (iOS shows transparency as black)
    ../favicon.ico (16, 32, 48)                for clients that ask /favicon.ico

Pillow only (already a dependency); the PNGs are committed, nothing runs at runtime.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

WEB = Path(__file__).resolve().parent.parent / "web"
ICONS = WEB / "icons"
BG = (10, 52, 110, 255)  # deep blue of the tile, for opaque/maskable variants

# Geometry of the source render (1254x1254): tile and side wings, crop square.
TILE = (97, 87, 1161, 1166)
TILE_RADIUS = 215
WINGS = (77, 280, 1177, 760)
CROP = (77, 77, 1177, 1177)


def cut_logo(src: Path) -> Image.Image:
    im = Image.open(src).convert("RGBA")
    if im.size != (1254, 1254):
        raise SystemExit(f"unexpected source size {im.size}; adjust TILE/WINGS/CROP")
    mask = Image.new("L", im.size, 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle(TILE, radius=TILE_RADIUS, fill=255)
    d.rectangle(WINGS, fill=255)
    im.putalpha(ImageChops.multiply(im.getchannel("A"), mask))
    return im.crop(CROP)


def scaled(logo: Image.Image, size: int) -> Image.Image:
    return logo.resize((size, size), Image.LANCZOS)


def on_background(logo: Image.Image, size: int, fraction: float) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), BG)
    inner = round(size * fraction)
    canvas.alpha_composite(scaled(logo, inner), ((size - inner) // 2, (size - inner) // 2))
    return canvas


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    logo = cut_logo(Path(sys.argv[1]))
    outputs = {
        ICONS / "icon-32.png": scaled(logo, 32),
        ICONS / "icon-192.png": scaled(logo, 192),
        ICONS / "icon-512.png": scaled(logo, 512),
        # maskable: launchers crop to a circle of 80 % diameter; keep the tile inside it
        ICONS / "icon-maskable-512.png": on_background(logo, 512, 0.74),
        ICONS / "apple-touch-icon.png": on_background(logo, 180, 1.0).convert("RGB"),
    }
    for path, img in outputs.items():
        img.save(path, optimize=True)
        print("wrote", path)
    scaled(logo, 256).save(WEB / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    print("wrote", WEB / "favicon.ico")


if __name__ == "__main__":
    main()
