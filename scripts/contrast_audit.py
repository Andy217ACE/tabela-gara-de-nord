# © 2026 Andy217Ace
"""Automatic text-contrast audit (WCAG 2.x, 1.4.3) in a real browser.

For every visible element that has its own text, the script takes the computed text colour
and composes the effective background from the element up to <html> (background-color with
alpha, element opacity included), then computes the contrast ratio. Normal text needs
>= 4.5:1, large text (>= 24 px, or >= 18.66 px bold) >= 3:1.

    python scripts/contrast_audit.py https://tabelacfr.ddns.net            # all routes, both themes
    python scripts/contrast_audit.py http://127.0.0.1:8000 --routes "#,#istoric" --themes dark

Exit code 1 when anything fails. Requires Playwright + Chromium (dev dependency).
The same JS (AUDIT_JS) is used by tests/test_contrast_browser.py.
"""
import argparse
import json
import sys

AUDIT_JS = r"""() => {
  const parse = (c) => {
    if (!c || c === 'transparent') return [0, 0, 0, 0];
    let m = c.match(/^rgba?\(([^)]+)\)$/);
    if (m) {
      const p = m[1].split(/[\s,\/]+/).filter(Boolean).map(Number);
      return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
    }
    m = c.match(/^color\(srgb ([^)]+)\)$/);
    if (m) {
      const p = m[1].split(/[\s\/]+/).filter(Boolean).map(Number);
      return [p[0] * 255, p[1] * 255, p[2] * 255, p.length > 3 ? p[3] : 1];
    }
    return null;
  };
  const over = (top, bottom) => {           // alpha compositing, bottom opaque
    const a = top[3];
    return [0, 1, 2].map(i => top[i] * a + bottom[i] * (1 - a)).concat([1]);
  };
  const lum = (c) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
  };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const bgOf = (el) => {
    const chain = [];
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) chain.push(e);
    let bg = [255, 255, 255, 1];
    const root = parse(getComputedStyle(document.documentElement).backgroundColor);
    const body = parse(getComputedStyle(document.body).backgroundColor);
    if (root && root[3] > 0) bg = over(root, bg);
    if (body && body[3] > 0) bg = over(body, bg);
    for (let i = chain.length - 1; i >= 0; i--) {
      const e = chain[i];
      if (e === document.documentElement || e === document.body) continue;
      const c = parse(getComputedStyle(e).backgroundColor);
      if (c && c[3] > 0) bg = over(c, bg);
    }
    return bg;
  };
  const opacityOf = (el) => {
    let o = 1;
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) o *= parseFloat(getComputedStyle(e).opacity);
    return o;
  };
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') return false;
    if (el.closest('.sr-only, [hidden], [aria-hidden="true"] .sr-only')) return false;
    if (cs.clip === 'rect(0px, 0px, 0px, 0px)' || cs.clipPath === 'inset(50%)') return false;
    if (cs.position === 'absolute' && r.width <= 1 && r.height <= 1) return false;
    return true;
  };
  const out = [];
  const seen = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (!n.textContent.trim()) continue;
    const el = n.parentElement;
    if (!el || seen.has(el)) continue;
    seen.add(el);
    if (el.closest('svg, script, style, noscript, option, select, input, textarea')) continue;
    if (!visible(el)) continue;
    if (el.closest('[disabled], [aria-disabled="true"]')) continue;   // WCAG: inactive UI exempt
    const cs = getComputedStyle(el);
    let fg = parse(cs.color);
    if (!fg) continue;
    const bg = bgOf(el);
    fg = [fg[0], fg[1], fg[2], fg[3] * opacityOf(el)];
    const eff = over(fg, bg);
    const r = ratio(eff, bg);
    const size = parseFloat(cs.fontSize), weight = parseInt(cs.fontWeight, 10) || 400;
    const large = size >= 24 || (size >= 18.66 && weight >= 700);
    const need = large ? 3 : 4.5;
    if (r + 0.005 < need) {
      out.push({ text: n.textContent.trim().slice(0, 40), cls: (el.className && el.className.baseVal === undefined ? el.className : '') || el.tagName,
                 ratio: Math.round(r * 100) / 100, need, fg: cs.color, size });
    }
  }
  return out;
}"""

ROUTES = ["#", "#istoric", "#urmarite", "#trenuri", "#tren?nr=8122", "#statii", "#statistici",
          "#clasamente", "#versiuni"]


def audit(page):
    return page.evaluate(AUDIT_JS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--routes", default=",".join(ROUTES))
    ap.add_argument("--themes", default="dark,light")
    ap.add_argument("--views", default="panou,carduri", help="LIVE modes for the # route")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--api-from", default="", help="serve /api/* from another origin (local CSS, live data)")
    args = ap.parse_args()
    from playwright.sync_api import sync_playwright

    fails = 0
    with sync_playwright() as p:
        b = p.chromium.launch()
        for theme in args.themes.split(","):
            for route in args.routes.split(","):
                views = args.views.split(",") if route in ("#", "") else ["panou"]
                for view in views:
                    ctx = b.new_context(viewport={"width": args.width, "height": 900}, service_workers="block")
                    ctx.add_init_script(f"localStorage.setItem('tabela.theme','{theme}');"
                                        f"localStorage.setItem('tabela.view','{view}');")
                    if args.api_from:
                        def proxy(r, api=args.api_from.rstrip("/")):
                            u = r.request.url
                            try:
                                r.fulfill(response=r.fetch(url=api + u[u.index("/api/"):]))
                            except Exception:
                                r.abort()
                        ctx.route("**/api/**", proxy)
                    page = ctx.new_page()
                    page.goto(args.base.rstrip("/") + "/" + route, wait_until="networkidle")
                    page.wait_for_timeout(1200)
                    bad = audit(page)
                    tag = f"{theme} {route} {view if route in ('#', '') else ''}".strip()
                    print(f"{tag}: {len(bad)} failures")
                    for f in bad[:30]:
                        print("   ", json.dumps(f, ensure_ascii=False))
                    fails += len(bad)
                    ctx.close()
        b.close()
    print("TOTAL failures:", fails)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
