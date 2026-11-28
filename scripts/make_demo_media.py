# © 2026 Andy217Ace
"""Capturi demo pentru README (docs/media/): PNG-uri + un GIF animat din capturile desktop.

Folosește DOAR pagini PUBLICE ale site-ului (tabela, istoric, statistici, trenuri, stații,
?lang=en). Nu deschide niciodată #admin, #ocr, #ocr2, #infofer, #setari sau alte pagini private
și nu trimite niciun token.

Uz:  python scripts/make_demo_media.py [--base https://tabelagn.online] [--out docs/media]
Cere Playwright (Chromium) și Pillow (ambele în mediul de dezvoltare, nu în requirements.txt).
"""
from __future__ import annotations

import argparse
import io
import json
import urllib.request
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ("/", "/istoric", "/statistici", "/trenuri", "/statii")  # + /tren/<nr>
PRIVATE = ("#admin", "#ocr", "#infofer", "#setari", "/api/admin")
PNG_MAX = 300_000
GIF_MAX = 2_500_000
GIF_W = 960


def train_no(base: str) -> int:
    with urllib.request.urlopen(base + "/api/board", timeout=20) as r:  # nosec B310 (https, fixed host)
        d = json.load(r)
    rows = [x for x in d["departures"] + d["arrivals"] if x.get("train_no") and x.get("delay_read")]
    return rows[0]["train_no"]


def shots(base: str) -> list[tuple[str, str, str, str, tuple[int, int]]]:
    """(name, path, theme, view, viewport); every path is public."""
    tren = f"/tren/{train_no(base)}"
    D, M = (1280, 800), (390, 844)
    s = [
        ("desktop-panou-light", "/", "light", "panou", D),
        ("desktop-carduri-light", "/", "light", "carduri", D),
        ("desktop-statistici-light", "/statistici", "light", "", D),
        ("desktop-istoric-light", "/istoric", "light", "", D),
        ("desktop-tren-light", tren, "light", "", D),
        ("desktop-panou-dark", "/", "dark", "panou", D),
        ("desktop-statistici-dark", "/statistici", "dark", "", D),
        ("desktop-en-dark", "/?lang=en", "dark", "carduri", D),
        ("mobil-carduri-light", "/", "light", "carduri", M),
        ("mobil-carduri-dark", "/", "dark", "carduri", M),
        ("mobil-statistici-light", "/statistici", "light", "", M),
        ("mobil-tren-dark", tren, "dark", "", M),
    ]
    for _, path, *_ in s:
        assert not any(p in path for p in PRIVATE), path
        assert path.split("?")[0] in PUBLIC or path.startswith("/tren/"), path
    return s


def quantize(png: bytes, max_bytes: int) -> tuple[Image.Image, bytes]:
    img = Image.open(io.BytesIO(png)).convert("RGB")
    while True:
        q = img.quantize(colors=128, method=Image.Quantize.MEDIANCUT)
        buf = io.BytesIO()
        q.save(buf, "PNG", optimize=True)
        if buf.tell() <= max_bytes or img.width < 400:
            return img, buf.getvalue()
        img = img.resize((int(img.width * 0.85), int(img.height * 0.85)), Image.LANCZOS)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://tabelagn.online")
    ap.add_argument("--out", default=str(ROOT / "docs" / "media"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    frames = []
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        for name, path, theme, view, vp in shots(a.base):
            mobile = vp[0] < 600
            ctx = br.new_context(viewport={"width": vp[0], "height": vp[1]}, locale="ro-RO",
                                 device_scale_factor=2 if mobile else 1, is_mobile=mobile,
                                 has_touch=mobile, color_scheme=theme, service_workers="block")
            js = f"localStorage.setItem('tabela.theme', '{theme}');"
            if view:
                js += f"localStorage.setItem('tabela.view', '{view}');"
            ctx.add_init_script(js)
            page = ctx.new_page()
            page.goto(a.base + path, wait_until="networkidle", timeout=60_000)
            page.wait_for_timeout(3000)  # count-up figures and lazy charts settle
            img, data = quantize(page.screenshot(), PNG_MAX)
            (out / f"{name}.png").write_bytes(data)
            print(f"{name}.png {img.width}x{img.height} {len(data) // 1024} KB")
            if name.startswith("desktop-"):
                frames.append(img)
            ctx.close()
        br.close()
    h = round(frames[0].height * GIF_W / frames[0].width)
    g = [f.resize((GIF_W, h), Image.LANCZOS).quantize(colors=128, method=Image.Quantize.MEDIANCUT)
         for f in frames]
    gif = out / "demo.gif"
    g[0].save(gif, save_all=True, append_images=g[1:], duration=2000, loop=0, optimize=True)
    size = gif.stat().st_size
    print(f"demo.gif {GIF_W}x{h} {len(g)} cadre {size // 1024} KB")
    assert size <= GIF_MAX, "GIF prea mare: micșorează GIF_W"


if __name__ == "__main__":
    main()
