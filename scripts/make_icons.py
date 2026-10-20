# © 2026 Andy217Ace
"""Dev-time helper: build every logo/icon asset from the original artwork.

    python scripts/make_icons.py [docs/brand/logo-source.png]

Source: docs/brand/logo-source.png (1254x1254 RGBA render: rounded blue tile with the
Gara de Nord facade, a departure board and a train front). The render has a soft,
almost opaque light "shadow" slab under the tile plus a few stray semi-transparent
pixels. Cleaning:

  * stray pixels with alpha < 16 are dropped;
  * the tile outline is vertically symmetric, so the bottom half of the outline is the
    mirror of the (clean) top half: alpha below the middle is clipped by that mirrored
    outline, which removes the slab and keeps the anti-aliased rounded corners;
  * the result is centred on a square canvas with the same transparent margin all round.

Outputs (committed; nothing runs at runtime, Pillow only):

  web/icons/logo.png               512, transparent (header @2x, loading, footer, panel)
  web/icons/icon-192.png, -512     purpose "any", transparent margin
  web/icons/icon-maskable-512.png  solid tile blue, logo inside the 80 % safe zone
  web/icons/apple-touch-icon.png   180, opaque (iOS shows transparency as black)
  web/icons/favicon-32.png, -16    simplified crop (train front) of the same artwork:
                                   the full board is unreadable at 16-32 px
  web/favicon.ico                  16/32 from the simplified crop, 48 from the full logo
  web/icons/og-image.png           1200x630 social card
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
ICONS = WEB / "icons"
SRC = ROOT / "docs" / "brand" / "logo-source.png"

TILE_TOP, TILE_BOTTOM = 87, 1168   # tile outline rows in the 1254x1254 source
MARGIN = 0.04                      # transparent margin on each side of logo.png
OG_BG_TOP = (14, 34, 70)           # og-image gradient: logo navy -> app background
OG_BG_BOTTOM = (10, 13, 18)        # = --bg / theme-color #0a0d12
FONT_DIRS = [Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/dejavu")]


def clean(src: Path) -> Image.Image:
    im = Image.open(src).convert("RGBA")
    if im.size != (1254, 1254):
        raise SystemExit(f"unexpected source size {im.size}; adjust TILE_TOP/TILE_BOTTOM")
    a = np.array(im)
    alpha = a[..., 3].astype(np.int32)
    alpha[alpha < 16] = 0
    mid = (TILE_TOP + TILE_BOTTOM) // 2
    outline = alpha.copy()
    for y in range(mid + 1, alpha.shape[0]):
        m = TILE_TOP + TILE_BOTTOM - y  # mirrored row in the clean top half
        outline[y] = alpha[m] if TILE_TOP <= m <= mid else 0
    alpha = np.minimum(alpha, outline)
    a[..., 3] = alpha.astype(np.uint8)
    out = Image.fromarray(a, "RGBA")
    return out.crop(out.getbbox())


def square(logo: Image.Image, margin: float = MARGIN) -> Image.Image:
    w, h = logo.size
    side = round(max(w, h) / (1 - 2 * margin))
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.alpha_composite(logo, ((side - w) // 2, (side - h) // 2))
    return canvas


def tile_blue(logo: Image.Image) -> tuple[int, int, int]:
    """Median colour of a ring just inside the tile edge (its own background blue)."""
    a = np.array(logo).astype(np.int32)
    inside = a[..., 3] > 250
    shrunk = np.array(Image.fromarray((inside * 255).astype(np.uint8))
                      .filter(ImageFilter.MinFilter(25))) > 0
    ring = inside & ~shrunk
    px = a[ring][:, :3]
    blue = px[(px[:, 2] - px[:, 0]) > 40]  # skip the grey facade wings
    return tuple(int(v) for v in np.median(blue, axis=0))


def resized(img: Image.Image, size: int) -> Image.Image:
    return img.resize((size, size), Image.LANCZOS)


def on_background(logo_sq: Image.Image, size: int, fraction: float, bg) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), bg + (255,))
    inner = round(size * fraction)
    canvas.alpha_composite(resized(logo_sq, inner), ((size - inner) // 2, (size - inner) // 2))
    return canvas


def small_mark(logo: Image.Image, bg) -> Image.Image:
    """Train front + rails from the bottom of the same artwork, on a rounded blue tile."""
    w, h = logo.size
    cx = w // 2
    # train front + rails sit in the lower quarter of the tile (source px ~ 490-760 x 890-1140)
    box = (cx - 140, h - 281, cx + 140, h - 1)  # below the board, above the tile edge
    crop = logo.crop(box)
    side = crop.size[0]
    tile = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    mask = Image.new("L", (side, side), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, side - 1, side - 1), radius=side // 5, fill=255)
    base = Image.new("RGBA", (side, side), bg + (255,))
    base.alpha_composite(crop, (0, 0))
    tile.paste(base, (0, 0), mask)
    return tile


def font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    names = ["segoeuib.ttf", "DejaVuSans-Bold.ttf"] if bold else ["segoeui.ttf", "DejaVuSans.ttf"]
    for d in FONT_DIRS:
        for n in names:
            if (d / n).exists():
                return ImageFont.truetype(str(d / n), size)
    raise SystemExit("no TrueType font found for og-image")


def og_image(logo_sq: Image.Image) -> Image.Image:
    W, H = 1200, 630
    top, bot = np.array(OG_BG_TOP), np.array(OG_BG_BOTTOM)
    grad = (top[None, :] + (bot - top)[None, :] * np.linspace(0, 1, H)[:, None]).astype(np.uint8)
    img = Image.fromarray(np.repeat(grad[:, None, :], W, axis=1), "RGB").convert("RGBA")
    size = 470
    img.alpha_composite(resized(logo_sq, size), (60, (H - size) // 2))
    d = ImageDraw.Draw(img)
    x = 580
    d.text((x, 205), "Tabela Gara de Nord", font=font(True, 58), fill=(233, 238, 245))
    d.text((x, 290), "Sosiri și plecări live", font=font(False, 44), fill=(255, 181, 71))
    d.text((x, 380), "București Nord · date preluate de la CFR", font=font(False, 26),
           fill=(163, 174, 192))
    d.text((x, 418), "Proiect independent, neafiliat CFR", font=font(False, 26),
           fill=(163, 174, 192))
    return img.convert("RGB")


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else SRC
    logo = clean(src)
    logo_sq = square(logo)
    bg = tile_blue(logo)
    print("tile blue:", "#%02x%02x%02x" % bg)
    mark = small_mark(logo, bg)
    outputs = {
        ICONS / "logo.png": resized(logo_sq, 512),
        ICONS / "icon-192.png": resized(logo_sq, 192),
        ICONS / "icon-512.png": resized(logo_sq, 512),
        # maskable: launchers crop to a circle of 80 % diameter; keep the artwork inside
        ICONS / "icon-maskable-512.png": on_background(logo_sq, 512, 0.72, bg),
        ICONS / "apple-touch-icon.png": on_background(logo_sq, 180, 1.1, bg).convert("RGB"),
        ICONS / "favicon-32.png": resized(mark, 32),
        ICONS / "favicon-16.png": resized(mark, 16),
        ICONS / "og-image.png": og_image(logo_sq),
    }
    for path, img in outputs.items():
        img.save(path, optimize=True)
        print("wrote", path.relative_to(ROOT), img.size)
    # .ico: write explicit frames (simplified mark at 16/32, full logo at 48)
    frames = [resized(mark, 16), resized(mark, 32), resized(logo_sq, 48)]
    frames[2].save(WEB / "favicon.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48)],
                   append_images=frames[:2])
    print("wrote web/favicon.ico (16, 32, 48)")


if __name__ == "__main__":
    main()
