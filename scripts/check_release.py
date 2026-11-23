# © 2026 Andy217Ace
"""Release consistency: VERSION == newest CHANGELOG section, which has Romanian bullets and an
'### English' subsection with bullets, and CHARTS_V in web/ui2.js == the version number.
Run in CI: python scripts/check_release.py  (exit 1 and a list of problems on failure)."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def problems(version: str, changelog: str, ui2: str) -> list[str]:
    errs = []
    m = re.fullmatch(r"Beta 1\.(\d{2,})", version.strip())
    if not m:
        return [f"VERSION '{version.strip()}' is not 'Beta 1.NN'"]
    num = m.group(1)
    heads = list(re.finditer(r"^## (Beta 1\.\d+)\b.*$", changelog, re.M))
    if not heads or heads[0].group(1) != version.strip():
        found = heads[0].group(1) if heads else "none"
        return [f"top CHANGELOG section is '{found}', VERSION is '{version.strip()}'"]
    end = heads[1].start() if len(heads) > 1 else len(changelog)
    body = changelog[heads[0].end():end]
    ro, sep, en = body.partition("### English")
    if not sep:
        errs.append("top CHANGELOG section has no '### English' subsection")
    elif not re.search(r"^- ", en, re.M):
        errs.append("'### English' subsection has no bullets")
    if not re.search(r"^- ", ro, re.M):
        errs.append("top CHANGELOG section has no Romanian bullets before '### English'")
    cv = re.search(r'CHARTS_V = "([^"]*)"', ui2)
    if not cv or cv.group(1) != f"1.{num}":
        errs.append(f"CHARTS_V in web/ui2.js is {cv.group(1) if cv else 'missing'}, expected 1.{num}")
    return errs


def main() -> int:
    errs = problems((ROOT / "VERSION").read_text(encoding="utf-8"),
                    (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"),
                    (ROOT / "web" / "ui2.js").read_text(encoding="utf-8"))
    for e in errs:
        print("release check:", e, file=sys.stderr)
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
