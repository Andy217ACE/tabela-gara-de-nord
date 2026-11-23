# © 2026 Andy217Ace
"""Station display names (data/stations.txt): keys stay ASCII upper case, the UI shows Romanian."""
import re
from pathlib import Path

from app import canonical, history_all, stations, stats
from tests.test_stations import client, store  # noqa: F401  (fixtures)

WEB = Path(__file__).resolve().parent.parent / "web"
# Every distinct clean station on the live board (copy of the live DB, 2026-11-23): 8,955 of
# 8,966 journeys (99.88%); the other 11 values are one-off misreads, left as read on purpose.
LIVE = ["BRASOV", "AEROPORT H COANDA", "CONSTANTA", "ROSIORI NORD", "PITESTI", "PLOIESTI SUD",
        "CRAIOVA", "TARGOVISTE", "BUZAU", "CLUJ NAPOCA", "GALATI", "ADJUD", "IASI",
        "BUDAPESTA KELETI", "URZICENI", "ARAD", "SUCEAVA", "FETESTI", "SLOBOZIA VECHE", "TITU",
        "VATRA DORNEI BAI", "TIMISOARA NORD", "VIENA", "SUCEAVA NORD", "SIBIU", "SATU MARE",
        "RUSE", "BUCURESTI OBOR", "BACAU", "TARGU JIU", "DEVA", "TEIUS", "TARGU MURES",
        "KIEV - CHISINAU", "CHISINAU-KIEV"]


def test_mapping_loads_and_covers_live_and_seed():
    names = canonical.station_names()
    assert names["TIMISOARA NORD"] == "Timișoara Nord" and names["GALATI"] == "Galați"
    assert names["AEROPORT H COANDA"] == "Aeroport Henri Coandă" and names["BRASOV"] == "Brașov"
    assert set(LIVE) <= set(names) and canonical.seed_stations() <= set(names)
    for key, name in names.items():   # a display name is the key with diacritics/casing only
        assert key == canonical.clean_station(key)
        assert canonical.station_key(name) == key


def test_key_resolution_and_search():
    assert stations.canonical("Cluj-Napoca") == "CLUJ NAPOCA"
    assert stations.display_name("CLUJ NAPOCA") == "Cluj Napoca"  # forma CFR, fără cratimă
    assert stations.canonical("Brașov") == stations.canonical("BRASOV") == "BRASOV"
    assert stations.canonical("NEWHERE") == "NEWHERE"   # unknown: kept as read
    assert canonical.stations_matching("henri coandă") == ["AEROPORT H COANDA"]
    assert canonical.stations_matching("Târgu") == ["TARGU JIU", "TARGU MURES"]
    assert canonical.stations_matching("") == []


def test_list_search_with_and_without_diacritics(store):  # noqa: F811
    for q in ("galați", "GALATI", "Gala"):
        assert {i["name"] for i in stations.list_stations(store, q)} >= {"GALATI"}
    items = {i["name"]: i for i in stations.list_stations(store)}
    assert items["GALATI"]["display_name"] == "Galați"
    assert items["GALATZ"]["display_name"] == "GALATZ"   # misread: never a wrong station
    assert history_all.page(store, None, stats.Params(), station="Galați")["total"] == 7


def test_api_payloads(client):  # noqa: F811
    names = client.get("/api/station-names").json()
    assert names["BRASOV"] == "Brașov"
    j = client.get("/api/stations?query=bra%C8%99ov").json()
    assert [(s["name"], s["display_name"]) for s in j["stations"]][0] == ("BRASOV", "Brașov")
    d = client.get("/api/stations/Gala%C8%9Bi").json()
    assert d["name"] == "GALATI" and d["display_name"] == "Galați"
    csv = client.get("/api/stations?format=csv").text.lstrip("﻿")
    assert csv.startswith("name,journeys,")   # export columns unchanged


def test_frontend_renders_stations_through_one_helper():
    i18n = (WEB / "i18n" / "i18n.js").read_text(encoding="utf-8")
    assert '"/api/station-names"' in i18n and "station: station" in i18n
    for f in ("history.js", "follows.js"):   # titleCase (also S.titleCase) delegates to it
        assert "window.I18N.station(" in (WEB / f).read_text(encoding="utf-8")
    app = (WEB / "app.js").read_text(encoding="utf-8")
    assert "window.I18N.station(t.station)" in app and "t.station.toLowerCase()" not in app
    for f in ("panel.js", "stat_steps.js", "val5_seasons.js"):
        assert "I18N.station(" in (WEB / f).read_text(encoding="utf-8")
    # proper casing comes from the data ("Curtea de Argeș"): no CSS capitalize on names
    css = (WEB / "style.css").read_text(encoding="utf-8")
    for sel in (".t-station", ".h-station"):
        block = re.search(re.escape(sel) + r" \{([^}]*)\}", css).group(1)
        assert "capitalize" not in block
