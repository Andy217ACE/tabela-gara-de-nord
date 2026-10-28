# © 2026 Andy217Ace
"""Versioning: VERSION file, CHANGELOG.md, /api/health version, /api/changelog, footer."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import version as v
from app.api import create_app
from app.config import Settings

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


@pytest.fixture
def client(tmp_path):
    s = Settings(db_path=str(tmp_path / "t.db"), source_url="http://x", vapid_private_key="",
                 vapid_public_key="", vapid_subject="mailto:a@b.c", tesseract_cmd="tesseract",
                 poller_enabled=False, last_image_path=None)
    with TestClient(create_app(s, start_poller=False)) as c:
        yield c


def test_version_file_follows_scheme():
    assert v.VERSION_RE.match(v.__version__), v.__version__
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == v.__version__


def test_changelog_newest_first_and_current_version_documented():
    entries = v.changelog()
    assert entries and entries[0]["version"] == v.__version__
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", entries[0]["date"])
    items = [i for g in entries[0]["groups"] for i in g["items"]]
    assert len(items) >= 5
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "© 2026 Andy217Ace" in text


def test_beta_101_lists_the_wave():
    e = {x["version"]: x for x in v.changelog()}["Beta 1.01"]
    blob = " ".join(i for g in e["groups"] for i in g["items"]).lower()
    for word in ("panou live", "istoric", "push", "pwa", "temă", "sigla", "meteo", "ceas",
                 "capturi ocr", "observații", "v4", "v5"):
        assert word in blob, word


def test_beta_102_lists_the_hotfix():
    e = {x["version"]: x for x in v.changelog()}["Beta 1.02"]
    blob = " ".join(i for g in e["groups"] for i in g["items"]).lower()
    for word in ("două ori", "a doua citire", "citiri parțiale", "date vechi", "rejected_dir",
                 "ocr"):
        assert word in blob, word


def test_health_and_changelog_endpoints(client):
    h = client.get("/api/health").json()
    assert h["version"] == v.__version__
    r = client.get("/api/changelog")
    assert r.status_code == 200
    assert r.json()["version"] == v.__version__
    assert r.json()["entries"][0]["version"] == v.__version__


def test_footer_links_to_versions_screen():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    footer = re.search(r'<footer class="footer">(.*?)</footer>', html, re.S).group(1)
    assert re.search(r'<a class="footer-version" id="app-version" href="#versiuni"', footer)
    assert 'id="view-versiuni"' in html and '<script src="versions.js" defer>' in html
    js = (WEB / "versions.js").read_text(encoding="utf-8")
    assert js.startswith("// © 2026 Andy217Ace")
    for bad in ("innerHTML", ".style.", "cssText", "insertAdjacentHTML"):
        assert bad not in js
    assert '"#versiuni": "versiuni"' in (WEB / "app.js").read_text(encoding="utf-8")
    assert '"/versions.js"' in (WEB / "sw.js").read_text(encoding="utf-8")


def test_deploy_docs_require_version_bump():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    upd = (ROOT / "deploy" / "update.sh").read_text(encoding="utf-8")
    assert "CHANGELOG.md" in readme and "VERSION" in readme
    assert "CHANGELOG.md" in upd and "VERSION" in upd


def test_beta_103_lists_the_layout_fix():
    e = {x["version"]: x for x in v.changelog()}["Beta 1.03"]
    blob = " ".join(i for g in e["groups"] for i in g["items"]).lower()
    for word in ("panou", "lățimea coloanelor", "ecran complet", "carduri", "tooltip"):
        assert word in blob, word


# Old gaps in the published numbering that CHANGELOG.md does not explain yet.
# Empty: Beta 1.07 now has its "nu a fost publicată separat" note in CHANGELOG.md.
KNOWN_UNDOCUMENTED_GAPS: set[int] = set()

_PUB_HEAD = re.compile(r"^## Beta 1\.(\d+) — \d{4}-\d{2}-\d{2}\s*$", re.M)
_NOT_SEPARATE = re.compile(r"Beta 1\.(\d+) nu a fost publicată separat")


def _gap_report(text: str) -> tuple[list[int], set[int], set[int]]:
    """(published minors in file order, missing minors between them, documented ones)."""
    pub = [int(m) for m in _PUB_HEAD.findall(text)]
    missing: set[int] = set()
    for a, b in zip(pub, pub[1:]):
        missing.update(range(b + 1, a))
    documented = {int(m) for m in _NOT_SEPARATE.findall(text)}
    return pub, missing, documented


def _check_gaps(text: str) -> list[str]:
    pub, missing, documented = _gap_report(text)
    errs = []
    if any(a <= b for a, b in zip(pub, pub[1:])):
        errs.append(f"versions not strictly descending: {pub}")
    errs += [f"Beta 1.{n:02d} missing and not explained" for n in sorted(missing - documented - KNOWN_UNDOCUMENTED_GAPS)]
    return errs


def test_changelog_explains_gap_1_22():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "Beta 1.22 nu a fost publicată separat" in text
    pub, missing, documented = _gap_report(text)
    assert 22 in missing and 22 in documented
    assert _check_gaps(text) == []
    # the allowlist cannot go stale: each entry must still be a real, undocumented gap
    for n in KNOWN_UNDOCUMENTED_GAPS:
        assert n in missing and n not in documented, f"Beta 1.{n:02d} allowlist entry is stale"


def test_gap_check_catches_new_gap_and_disorder():
    base = "## Beta 1.05 — 2026-01-01\n## Beta 1.04 — 2026-01-01\n"
    assert _check_gaps(base) == []
    assert _check_gaps("## Beta 1.05 — 2026-01-01\n## Beta 1.03 — 2026-01-01\n") == ["Beta 1.04 missing and not explained"]
    assert _check_gaps("## Beta 1.05 — 2026-01-01\n## Beta 1.03 — 2026-01-01\nBeta 1.04 nu a fost publicată separat\n") == []
    assert _check_gaps("## Beta 1.04 — 2026-01-01\n## Beta 1.05 — 2026-01-01\n")
