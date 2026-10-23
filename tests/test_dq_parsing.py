# © 2026 Andy217Ace
"""Type rescue, station/operator variants and the argmin crash — real cases from the
live database (data-quality-report.md)."""
import numpy as np
import pytest

from app import canonical
from app.normalize import resolve_type
from app.ocr import digits


@pytest.mark.parametrize("raw,no,want", [
    ("I", 531, "IC"), ("I", 536, "IC"), ("I", 581, "IC"),      # IC in every other reading
    ("RN", 7929, "RM"), ("RN", 7931, "RM"), ("RND", 7935, "RM"), ("RNE", 7939, "RM"),
    ("RIM", 7923, "RM"), ("RR", 7925, "RM"),                     # airport shuttle RM
    ("I", 1632, None), ("I", 11753, None),                       # IR / ambiguous: not guessed
    ("RR", 10165, None), ("RR", 16089, None), ("RN", 1658, None),
    ("IR", 1580, "IR"), ("", 531, None),
])
def test_resolve_type(raw, no, want):
    assert resolve_type(raw, no) == want


@pytest.mark.parametrize("raw,want", [
    ("AD JUD", "ADJUD"), ("ARAD E", "ARAD"), ("RUSE I", "RUSE"),
    ("TIMISOA.RA NORD", "TIMISOARA NORD"), ("BRASOY", "BRASOV"), ("PLOIESTISUD", "PLOIESTI SUD"),
    ("CHISINAU -KIEV", "CHISINAU-KIEV"), ("BUCUREST! OBOR", "BUCURESTI OBOR"),
    ("FETEST", "FETESTI"), ("GALATI", "GALATI"), ("SUCEAVA NORD", "SUCEAVA NORD"),
])
def test_station_variants(raw, want):
    assert canonical.canonical_station(raw, (), preferred=canonical.seed_stations())[0] == want


def test_station_distinct_names_not_merged():
    seed = canonical.seed_stations()
    assert canonical.canonical_station("VATRA DORNEI", (), preferred=seed)[0] == "VATRA DORNEI"
    assert canonical.canonical_station("SUCEAVA", (), preferred=seed)[0] == "SUCEAVA"
    assert canonical.canonical_station("LASI", (), preferred=seed)[0] == "LASI"  # not guessed


@pytest.mark.parametrize("raw,want", [
    ("CFR Calaitori", "CFR Calatori"), ("CFR CAleitori", "CFR Calatori"),
    ("interRegional", "InterRegional"), ("Transfernviar", "Transferoviar"),
    ("Sofirans Calat", "Softrans Calat"), ("Softrans!Calat", "Softrans Calat"),
    ("Ferotrafic", "Ferotrafic"),
])
def test_operator_variants(raw, want):
    assert canonical.canonical_operator(raw)[0] == want


def test_merged_operator_not_canonicalised():
    assert canonical.canonical_operator("CFR CFR Calatori Calatori")[1] < 0.82


def test_near_name():
    assert canonical.near_name("AD JUD", "ADJUD")
    assert canonical.near_name("RUSE I", "RUSE")
    assert canonical.near_name("LASI", "IASI")
    assert not canonical.near_name("SUCEAVA", "SUCEAVA NORD")
    assert not canonical.near_name("ARAD", "ADJUD")


def test_split_touching_degenerate_component_no_argmin_crash():
    # ValueError "attempt to get argmin of an empty sequence" (2 captures, 21.10):
    # a component wider than one glyph but only a few pixels wide
    line = np.ones((1, 2), np.float32)  # w=2, line_h=1: the old code raised here
    parts = digits._split_touching(line, 0, 2, 1)
    assert parts and all(b > a for a, b in parts)


def test_near_name_word_order():
    # "KIEV - CHISINAU" next to CHISINAU-KIEV (report 2): not learned as a new station
    assert canonical.near_name("KIEV - CHISINAU", "CHISINAU-KIEV")
    assert not canonical.near_name("SUCEAVA NORD", "SUCEAVA")
