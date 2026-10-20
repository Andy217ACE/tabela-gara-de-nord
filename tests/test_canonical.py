# © 2026 Andy217Ace
import pytest

from app import canonical
from app.canonical import (
    DEFAULT_THRESHOLD,
    canonical_operator,
    canonical_station,
    known_operators,
    seed_stations,
)

OPERATORS = {"CFR Calatori", "Regio Calatori", "Transferoviar", "InterRegional",
             "Astra Trans Ca"}


def test_default_threshold():
    assert DEFAULT_THRESHOLD == 0.82


def test_operator_list_only_seen_operators():
    assert set(known_operators()) == OPERATORS


@pytest.mark.parametrize("noisy, expected", [
    ("“Mransferoviar", "Transferoviar"),
    ("Transferovlar", "Transferoviar"),
    ("Transfernviar", "Transferoviar"),
    ("Transferbviar", "Transferoviar"),
    ("CFR Calatorl", "CFR Calatori"),
    ("CFR Catatori", "CFR Calatori"),
    ("CFR Calaitori", "CFR Calatori"),
    ("CFR CAlaitori", "CFR Calatori"),
    ("GFR Calatori", "CFR Calatori"),
    ("(SFR Calatari", "CFR Calatori"),
    ("interRegional", "InterRegional"),
    ("mterRegional", "InterRegional"),
    ("Regio Calatori", "Regio Calatori"),
    ("Astra Trans Ca", "Astra Trans Ca"),
])
def test_operator_noise_maps_to_canonical(noisy, expected):
    text, score = canonical_operator(noisy)
    assert text == expected
    assert score >= DEFAULT_THRESHOLD


def test_exact_operator_scores_one():
    assert canonical_operator("Transferoviar") == ("Transferoviar", 1.0)


def test_distinct_operators_not_merged():
    assert canonical_operator("Regio Calatori")[0] == "Regio Calatori"
    assert canonical_operator("CFR Calatori")[0] == "CFR Calatori"
    assert canonical_operator("Regio Calatorl")[0] == "Regio Calatori"


@pytest.mark.parametrize("unknown", ["Softrans", "Unknown Rail SA", "xq"])
def test_unknown_operator_stays_raw_with_low_score(unknown):
    text, score = canonical_operator(unknown)
    assert text == unknown
    assert score < DEFAULT_THRESHOLD


def test_operator_raw_text_is_cleaned_when_unknown():
    assert canonical_operator("  Softrans  .")[0] == "Softrans"


def test_empty_operator():
    assert canonical_operator("") == ("", 0.0)
    assert canonical_operator(None) == ("", 0.0)


def test_operator_custom_known_and_threshold():
    assert canonical_operator("Softrans", known=["Softrans SRL"])[0] == "Softrans"  # ratio 0.8
    assert canonical_operator("Softrans", known=["Softrans SRL"],
                              threshold=0.7)[0] == "Softrans SRL"


SEED = {"BRASOV", "PLOIESTI SUD", "IASI", "AEROPORT H COANDA"}


def test_station_noise_maps_to_known():
    assert canonical_station("BRASOY", SEED) == ("BRASOV", pytest.approx(5 / 6))
    assert canonical_station("brașov", SEED) == ("BRASOV", 1.0)
    assert canonical_station("AEROPORT H COANDA.", SEED)[0] == "AEROPORT H COANDA"


def test_station_unknown_stays_raw():
    text, score = canonical_station("Suceava", SEED)
    assert text == "SUCEAVA"
    assert score < DEFAULT_THRESHOLD


def test_close_but_distinct_stations_not_merged():
    text, score = canonical_station("PLOIESTI VEST", SEED)
    assert text == "PLOIESTI VEST" and score < DEFAULT_THRESHOLD


def test_station_preferred_seed_beats_learned_noise():
    learned = {"BRASOY"}  # a misread that slipped into the history
    assert canonical_station("BRASOY", SEED | learned, preferred=SEED)[0] == "BRASOV"
    # a learned legitimate station still matches itself
    assert canonical_station("SUCEAVA", SEED | {"SUCEAVA"}, preferred=SEED) == ("SUCEAVA", 1.0)


def test_empty_station():
    assert canonical_station("", SEED) == ("", 0.0)


def test_seed_stations_file():
    seed = seed_stations()
    assert {"BRASOV", "AEROPORT H COANDA", "BUDAPESTA KELETI", "VATRA DORNEI BAI"} <= seed
    assert all(s == s.upper().strip() for s in seed)


def test_data_files_have_header_and_no_blank_entries():
    for name in ("operators.txt", "stations_seed.txt"):
        lines = (canonical.DATA_DIR / name).read_text(encoding="utf-8").splitlines()
        assert lines[0].startswith("# © 2026 Andy217Ace")
