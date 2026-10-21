# © 2026 Andy217Ace
"""Real-browser layout checks (Beta 1.03): long station/operator names must not change the
column widths of the Panou tables from one update to the next, and in full screen the
„Sosiri" and „Plecări" tables must line up (same row tops and heights). Also: no horizontal
scroll at 390 px and the cards keep long names clamped with the full value in `title`.
Skipped when Playwright (dev only) or its Chromium is unavailable."""
import json
import urllib.request

import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_footer_browser import base_url, browser  # noqa: E402,F401  (shared fixtures)

LONG_STATION = "Chișinău Triaj Internațional – Nord"
LONG_OP = "Transferoviar Călători Internațional Grup Feroviar SRL"
TOL = 1.0

MEASURE = """() => {
  const out = {};
  for (const b of ['arrivals', 'departures']) {
    const sec = document.querySelector('.pnl-board[data-board="' + b + '"]');
    const vis = sec && getComputedStyle(sec).display !== 'none';
    out[b] = !vis ? null : {
      sec: sec.getBoundingClientRect().toJSON(),
      head: sec.querySelector('thead').getBoundingClientRect().toJSON(),
      th: [...sec.querySelectorAll('thead th')].map(e => e.getBoundingClientRect().width),
      rows: [...sec.querySelectorAll('tbody tr')].map(e => {
        const r = e.getBoundingClientRect(); return [r.top, r.height]; }),
      text: sec.querySelector('tbody').textContent
    };
  }
  out.fs = !!document.fullscreenElement;
  out.isFs = document.querySelector('.pnl').classList.contains('is-fs');
  out.hscroll = document.documentElement.scrollWidth > document.documentElement.clientWidth;
  return out;
}"""


@pytest.fixture(scope="module")
def boards(base_url):  # noqa: F811
    real = json.loads(urllib.request.urlopen(base_url + "/api/board", timeout=10).read())
    assert real["arrivals"] and real["departures"]

    def make(long):
        b = json.loads(json.dumps(real))
        if long:
            for k, parity in (("arrivals", 0), ("departures", 1)):
                for i, t in enumerate(b[k]):
                    if i % 2 == parity:
                        t["station"], t["operator"] = LONG_STATION, LONG_OP
        return json.dumps(b)
    return {"short": make(False), "long": make(True)}


def _open(browser, base_url, boards, w, h, theme, view, board="all"):  # noqa: F811
    state = {"set": "short"}
    ctx = browser.new_context(viewport={"width": w, "height": h}, service_workers="block")
    ctx.add_init_script(f"localStorage.setItem('tabela.theme', '{theme}');"
                        f"localStorage.setItem('tabela.view', '{view}');"
                        f"localStorage.setItem('tabela.panel.board', '{board}');")

    def route(r):
        url = r.request.url
        if url.startswith(base_url + "/api/board"):
            r.fulfill(status=200, content_type="application/json", body=boards[state["set"]])
        elif url.startswith(base_url):
            r.continue_()
        else:
            r.abort()
    ctx.route("**/*", route)
    page = ctx.new_page()
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(base_url + "/")
    page.wait_for_function("document.documentElement.dataset.view === '%s'" % view)
    page.wait_for_selector(".pnl-row" if view == "panou" else ".train .t-station")
    page.wait_for_timeout(200)
    return ctx, page, state, errors


def _load(page, state, which):
    """Switch the mocked /api/board payload and wait until the panel re-rendered it."""
    state["set"] = which
    page.click(".pnl-btn:has-text('Reîmprospătează')")
    want = LONG_STATION.upper() if which == "long" else None
    for _ in range(50):  # poll from Python: page-side string predicates need eval (CSP)
        m = page.evaluate(MEASURE)
        txt = (m["arrivals"] or m["departures"])["text"].upper()
        if (want in txt) if want else (LONG_STATION.upper() not in txt):
            page.wait_for_timeout(100)
            return page.evaluate(MEASURE)
        page.wait_for_timeout(100)
    raise AssertionError("board did not re-render with the %s set" % which)


def _fullscreen(page):
    page.click(".pnl-btn:has-text('Ecran complet')")
    for _ in range(30):
        if page.evaluate(MEASURE)["isFs"]:
            break
        page.wait_for_timeout(100)
    page.wait_for_timeout(300)
    m = page.evaluate(MEASURE)
    assert m["isFs"]
    return m


def _close(a, b):
    return abs(a - b) <= TOL


@pytest.mark.parametrize("w,h", [(1280, 800), (1920, 1080)])
@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("fs", [False, True])
def test_panel_column_widths_do_not_depend_on_data(browser, base_url, boards, w, h, theme, fs):  # noqa: F811
    ctx, page, state, errors = _open(browser, base_url, boards, w, h, theme, "panou")
    try:
        if fs:
            _fullscreen(page)
        short = _load(page, state, "short")
        long_ = _load(page, state, "long")
        # the full value stays available in the tooltip
        title = page.get_attribute(".pnl-board[data-board='arrivals'] tbody tr:first-child .c-station",
                                   "title")
        assert title and LONG_STATION in title
        again = _load(page, state, "short")
        for b in ("arrivals", "departures"):
            for x, y, z in zip(short[b]["th"], long_[b]["th"], again[b]["th"]):
                assert _close(x, y) and _close(x, z), (b, short[b]["th"], long_[b]["th"])
            heights = {round(r[1], 1) for r in long_[b]["rows"]}
            assert max(heights) - min(heights) <= TOL, (b, heights)  # same height for every row
            assert _close(short[b]["rows"][0][1], long_[b]["rows"][0][1])
        # both panels: identical columns and identical row height
        for x, y in zip(long_["arrivals"]["th"], long_["departures"]["th"]):
            assert _close(x, y)
        assert _close(long_["arrivals"]["rows"][0][1], long_["departures"]["rows"][0][1])
        assert not long_["hscroll"]
        assert not page.is_visible(".pnl-filters-sum")  # filters are always open on desktop
        assert not [e for e in errors if "Content Security Policy" in e]
    finally:
        ctx.close()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_fullscreen_side_by_side_panels_are_aligned(browser, base_url, boards, theme):  # noqa: F811
    ctx, page, state, _ = _open(browser, base_url, boards, 1920, 1080, theme, "panou")
    try:
        m = _fullscreen(page)
        assert m["fs"], "Fullscreen API should be active (real full screen)"
        m = _load(page, state, "long")
        a, d = m["arrivals"], m["departures"]
        assert _close(a["sec"]["top"], d["sec"]["top"])
        assert _close(a["sec"]["width"], d["sec"]["width"])
        assert _close(a["head"]["top"], d["head"]["top"])
        assert _close(a["head"]["height"], d["head"]["height"])
        assert a["sec"]["right"] <= d["sec"]["left"]  # side by side
        n = min(len(a["rows"]), len(d["rows"]))
        assert n >= 5
        for (ta, ha), (td, hd) in zip(a["rows"][:n], d["rows"][:n]):
            assert _close(ta, td) and _close(ha, hd), (a["rows"][:n], d["rows"][:n])
    finally:
        ctx.close()


@pytest.mark.parametrize("view", ["panou", "carduri"])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_no_horizontal_scroll_on_phone_with_long_names(browser, base_url, boards, view, theme):  # noqa: F811
    ctx, page, state, _ = _open(browser, base_url, boards, 390, 844, theme, view)
    try:
        state["set"] = "long"
        page.reload()
        page.wait_for_selector(".pnl-row" if view == "panou" else ".train .t-station")
        page.wait_for_timeout(300)
        assert not page.evaluate("document.documentElement.scrollWidth > "
                                 "document.documentElement.clientWidth")
        if view == "panou":  # the collapsible filters summary is only for phones
            assert page.is_visible(".pnl-filters-sum")
        if view == "carduri":
            info = page.evaluate("""() => [...document.querySelectorAll('.train')]
              .filter(li => li.getBoundingClientRect().height > 0).map(li => {
                const s = li.querySelector('.t-station'), r = li.getBoundingClientRect();
                const lh = parseFloat(getComputedStyle(s).lineHeight);
                return { title: s.title, lines: Math.round(s.getBoundingClientRect().height / lh),
                         right: r.right, vw: document.documentElement.clientWidth }; })""")
            assert info
            assert any(LONG_STATION in i["title"] for i in info)
            assert all(i["lines"] <= 2 and i["right"] <= i["vw"] + TOL for i in info), info
    finally:
        ctx.close()


@pytest.mark.parametrize("w,h", [(1100, 800), (1280, 800), (1920, 1080)])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_desktop_cards_columns_equal_with_long_names(browser, base_url, boards, w, h, theme):  # noqa: F811
    ctx, page, state, _ = _open(browser, base_url, boards, w, h, theme, "carduri")
    try:
        state["set"] = "long"
        page.reload()
        page.wait_for_selector(".train .t-station")
        page.wait_for_timeout(300)
        r = page.evaluate("""() => ['arrivals', 'departures'].map(b =>
          document.querySelector('.board[data-board="' + b + '"]').getBoundingClientRect().toJSON())""")
        assert _close(r[0]["width"], r[1]["width"]) and _close(r[0]["top"], r[1]["top"])
        # side by side: every card has the same height, so the rows of both columns line up
        cards = page.evaluate("""() => ['arrivals', 'departures'].map(b =>
          [...document.querySelectorAll('.board[data-board="' + b + '"] .train')]
            .map(e => { const q = e.getBoundingClientRect(); return [q.top, q.height]; }))""")
        n = min(len(cards[0]), len(cards[1]))
        assert n >= 5
        for (ta, ha), (td, hd) in zip(cards[0][:n], cards[1][:n]):
            assert _close(ta, td) and _close(ha, hd), cards
        op = page.evaluate("""() => { const o = [...document.querySelectorAll('.t-op')]
          .find(e => e.textContent.length > 30); const cs = getComputedStyle(o);
          return { title: o.title, ov: cs.textOverflow, ws: cs.whiteSpace }; }""")
        assert "Transferoviar" in op["title"] and op["ov"] == "ellipsis" and op["ws"] == "nowrap"
        assert not page.evaluate("document.documentElement.scrollWidth > "
                                 "document.documentElement.clientWidth")
    finally:
        ctx.close()
