# © 2026 Andy217Ace
"""Beta 1.69 finisaj: polish.css + print.css are linked/precached, motion is reduced-motion safe,
no inline styles."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"


def read(n):
    return (WEB / n).read_text(encoding="utf-8")


def test_linked_and_precached():
    html, sw = read("index.html"), read("sw.js")
    assert '<link rel="stylesheet" href="polish.css">' in html
    assert re.search(r'<link rel="stylesheet" href="print\.css" media="print">', html)
    assert html.index("polish.css") > html.index("ui2.css") > html.index('href="style.css"')
    assert '"/polish.css"' in sw and '"/print.css"' in sw


def test_transitions_only_when_motion_allowed():
    css = read("polish.css")
    assert "@media (prefers-reduced-motion: no-preference)" in css
    head = css.split("@media (prefers-reduced-motion: no-preference)")[0]
    assert "transition" not in head and "animation" not in head


def test_no_inline_styles_or_raw_colors_in_polish():
    css = read("polish.css")
    assert "!important" not in css and not re.search(r"#[0-9a-fA-F]{3,6}\b", css)
    assert "style=" not in read("index.html").split("polish.css")[1][:200]


def test_print_hides_chrome():
    css = read("print.css")
    assert css.strip().split("*/", 1)[1].lstrip().startswith("@media print")
    for sel in ("nav", ".bottom-nav", "button:not(", ".filters", "footer"):
        assert sel in css
    # data inside buttons / live regions must print (train numbers, headings, column labels, counts)
    for keep in (".h-train", ".oc-name", ".st-sort", ".st-jbtn", ".ss-acc-btn"):
        assert keep in css
    assert "[aria-live]" not in css and '[role="button"]' not in css
