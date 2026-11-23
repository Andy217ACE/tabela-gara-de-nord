# © 2026 Andy217Ace
"""Sanity check of deploy/fail2ban filters: the failregex lines translated to Python re,
applied to tests/fixtures/fail2ban. The authoritative check is `fail2ban-regex` in CI
(.github/workflows/ci.yml, job fail2ban); this one runs anywhere, without fail2ban."""
import configparser
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
F2B = ROOT / "deploy" / "fail2ban"
FIX = ROOT / "tests" / "fixtures" / "fail2ban"


def _failregex(name):
    """Compiled failregex list of a filter, `%(_probe)s` expanded (the slow filter takes it
    from the probes one via [INCLUDES] before=). <HOST> is any non-space token here."""
    cp = configparser.RawConfigParser()
    cp.read(F2B / "nginx-tabela-probes.local", encoding="utf-8")
    probe = cp["Definition"]["_probe"]
    cp.read(F2B / f"{name}.local", encoding="utf-8")
    raw = cp["Definition"]["failregex"].strip().splitlines()
    return [re.compile(r.strip().replace("%(_probe)s", probe).replace("<HOST>", r"(?P<host>\S+)")) for r in raw]


def _lines(name):
    # fail2ban removes the date, leaving "[]"
    return [re.sub(r"\[[^\]]*\]", "[]", l, count=1)
            for l in (FIX / name).read_text(encoding="latin-1").splitlines() if l.strip()]


def _hits(filt, fixture):
    rx = _failregex(filt)
    return [l for l in _lines(fixture) if any(r.search(l) for r in rx)]


def test_slow_matches_every_should_match_line():
    assert _hits("nginx-tabela-slow", "should_match.log") == _lines("should_match.log")


def test_probes_matches_every_probe_line():
    assert _hits("nginx-tabela-probes", "should_match_probes.log") == _lines("should_match_probes.log")
    assert _hits("nginx-tabela-slow", "should_match_probes.log") == _lines("should_match_probes.log")


def test_normal_traffic_matches_nothing():
    assert _lines("should_not_match.log")
    for filt in ("nginx-tabela-probes", "nginx-tabela-slow"):
        assert _hits(filt, "should_not_match.log") == []
