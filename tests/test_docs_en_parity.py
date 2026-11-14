"""Every Romanian doc in docs/*.md must have an English twin in docs/en/."""
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"


def test_every_romanian_doc_has_english_twin():
    missing = [p.name for p in sorted(DOCS.glob("*.md")) if not (DOCS / "en" / p.name).is_file()]
    assert not missing, f"missing English twins in docs/en/: {missing}"


def test_english_docs_have_no_orphans():
    # glosar.md is the only English-only extra allowed.
    ro = {p.name for p in DOCS.glob("*.md")}
    extra = [p.name for p in (DOCS / "en").glob("*.md") if p.name not in ro and p.name != "glosar.md"]
    assert not extra, f"English docs without a Romanian twin: {extra}"
