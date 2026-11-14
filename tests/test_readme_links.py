from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_readme_links_both_languages():
    en = (ROOT / "README.md").read_text(encoding="utf-8")
    ro_path = ROOT / "README.ro.md"
    assert ro_path.exists()
    ro = ro_path.read_text(encoding="utf-8")
    assert "](README.ro.md)" in en
    assert "](docs/en/" in en
    assert "](README.md)" in ro
