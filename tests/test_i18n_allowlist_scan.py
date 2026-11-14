# © 2026 Andy217Ace
"""Scan web/ JS and HTML for Romanian literals that are not in tests/i18n_allowlist.txt.

Comment text (JS // and /* */, HTML <!-- -->) is ignored; string literals and markup text are scanned.
HTML lines carrying data-i18n* are the pre-JS fallback of a dictionary key and are exempt.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
ALLOWLIST = Path(__file__).resolve().parent / "i18n_allowlist.txt"
PATTERN = re.compile("[ăîâșțĂÎÂȘȚşţŞŢ]|Încarc|Trenuri|Plecări|Sosiri")


def _blank(s):
    """Replace comment text by spaces, keeping newlines so line numbers survive."""
    return re.sub(r"[^\n]", " ", s)


def strip_js_comments(text):
    out = []
    i, n = 0, len(text)
    quote = None
    while i < n:
        c = text[i]
        if quote:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == quote or (c == "\n" and quote != "`"):
                quote = None
            i += 1
            continue
        if c in "'\"`":
            quote = c
            out.append(c)
            i += 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(_blank(text[i:j]))
            i = j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(_blank(text[i:j]))
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def strip_html_comments(text):
    return re.sub(r"<!--.*?-->", lambda m: _blank(m.group(0)), text, flags=re.S)


def strip_comments(text, suffix):
    if suffix == ".html":
        text = strip_html_comments(text)
        # inline <script>/<style> comments are rare; JS-style comments inside them are blanked too
        return re.sub(
            r"(<script\b[^>]*>)(.*?)(</script>)",
            lambda m: m.group(1) + strip_js_comments(m.group(2)) + m.group(3),
            text, flags=re.S)
    return strip_js_comments(text)


def _allowed():
    allowed = set()
    for raw in ALLOWLIST.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        path, lineno, _reason = line.split(":", 2)
        allowed.add((path, int(lineno)))
    return allowed


def test_comment_rule_ignores_comments_but_not_strings():
    word = "Încărcare"
    assert not PATTERN.search(strip_comments(f"var a = 1; // {word}\n", ".js"))
    assert not PATTERN.search(strip_comments(f"/* {word}\n {word} */ var a;\n", ".js"))
    assert not PATTERN.search(strip_comments(f"<p>x</p><!-- {word} -->\n", ".html"))
    assert PATTERN.search(strip_comments(f'var a = "{word}";\n', ".js"))
    assert PATTERN.search(strip_comments(f"var a = 'http://x' + '{word}';\n", ".js"))
    assert PATTERN.search(strip_comments(f"<p>{word}</p>\n", ".html"))
    assert strip_comments("a\n/* x\ny */\nb\n", ".js").count("\n") == 4


def test_no_romanian_literals_outside_allowlist():
    allowed = _allowed()
    hits = []
    files = sorted(list(WEB.rglob("*.js")) + list(WEB.rglob("*.html")))
    assert files, "no web files scanned"
    for f in files:
        rel = f.relative_to(ROOT).as_posix()
        raw = f.read_text(encoding="utf-8")
        lines = raw.splitlines()
        for n, text in enumerate(strip_comments(raw, f.suffix).splitlines(), 1):
            if f.suffix == ".html" and "data-i18n" in text:
                continue  # static fallback of a dictionary key (data-i18n / data-i18n-attr)
            if PATTERN.search(text) and (rel, n) not in allowed:
                hits.append(f"{rel}:{n}: {lines[n-1].strip()[:110]}")
    assert not hits, f"{len(hits)} Romanian literal lines:\n" + "\n".join(hits)
