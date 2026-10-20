# © 2026 Andy217Ace
import pytest

from app.normalize import (
    clean_station,
    normalize_type,
    parse_delay,
    parse_platform,
    parse_time,
    strip_flag,
)


@pytest.mark.parametrize("s,exp", [
    ("20:04", "20:04"), ("20.04", "20:04"), ("2004", "20:04"),
    ("9:05", "09:05"), ("2O:O4", "20:04"), (" 20:04 ", "20:04"),
    ("25:99", None), ("24:00", None), ("", None), ("abc", None), ("20:6", None),
])
def test_parse_time(s, exp):
    assert parse_time(s) == exp


@pytest.mark.parametrize("s,exp", [
    ("+10", 10), ("", 0), ("+1O", 10), ("+130", 130), ("+5", 5),
    ("xyz", 0), ("--", 0), ("+", 0), ("10", 10),
])
def test_parse_delay(s, exp):
    assert parse_delay(s) == exp


@pytest.mark.parametrize("s,exp", [
    ("1", 1), ("12", 12), ("30", 30), ("0", None), ("31", None),
    ("", None), ("x", None), ("l2", 12), ("O", None), ("1O", 10),
])
def test_parse_platform(s, exp):
    assert parse_platform(s) == exp


@pytest.mark.parametrize("s,exp", [
    ("IR", "IR"), ("lR", "IR"), ("ir", "IR"), ("IRN", "IRN"), ("R", "R"),
    ("RE", "RE"), ("RM", "RM"), ("IC", "IC"), ("EC", "EC"), ("EN", "EN"),
    ("D", "D"), ("1R", "IR"), ("|R", "IR"), ("XYZ", None), ("", None),
])
def test_normalize_type(s, exp):
    assert normalize_type(s) == exp


@pytest.mark.parametrize("s,exp", [
    ("*IR", ("IR", True)), ("IR", ("IR", False)), ("* IR", ("IR", True)),
    ("IR*", ("IR", True)), ("", ("", False)),
])
def test_strip_flag(s, exp):
    assert strip_flag(s) == exp


@pytest.mark.parametrize("s,exp", [
    ("Brașov", "BRASOV"), ("  Cluj   Napoca ", "CLUJ NAPOCA"),
    ("|Iași.", "IASI"), ("_Târgu-Mureș-", "TARGU-MURES"),
    ("Timișoara Nord", "TIMISOARA NORD"), ("Constanța", "CONSTANTA"),
    ("Pașcani", "PASCANI"), ("Ţ ă î â ş", "T A I A S"), ("", ""), ("...", ""),
])
def test_clean_station(s, exp):
    assert clean_station(s) == exp
