# © 2026 Andy217Ace
"""Val 5a: comparația meteo pe sezoane, cu prag de date. Pur (fără bază reală): datele
sintetice trec prin funcțiile din app.seasons."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app import seasons as se
from app import stats

BUC = ZoneInfo("Europe/Bucharest")
P = stats.Params(on_time=5, min_sample=5)


def jn(board, service_date, sched, delay, read_at=None):
    """Călătorie încheiată, cu întârzierea citită (forma din app.journeys.result)."""
    return {"board": board, "service_date": service_date, "sched_time": sched,
            "result": {"state": "confirmed", "delay_known": True, "observed_delay": delay,
                       "delay_read_at": read_at or f"{service_date}T{sched}:00+03:00"}}


def wx(local_iso, temp=10.0, precip=0.0):
    """Observație meteo, stocată în UTC cu sufix Z (ca în weather_observations)."""
    t = datetime.fromisoformat(local_iso).astimezone(timezone.utc)
    return {"observed_at": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "temperature_c": temp,
            "precipitation_mm": precip}


def day_obs(d, n, temp=10.0, precip=0.0):
    """n observații într-o zi locală, la pas egal, începând cu 00:00 ora României."""
    start = datetime(d.year, d.month, d.day, tzinfo=BUC)
    step = timedelta(minutes=1440 / n)
    out = []
    for i in range(n):
        t = (start + step * i).astimezone(BUC)
        out.append(wx(t.isoformat(), temp, precip))
    return out


# ---- sezoane ---------------------------------------------------------------------------

def test_season_boundaries_romania_calendar():
    def key(d):
        return se.season_of(d)[0]
    assert key(date(2026, 11, 30)) == "toamna-2026"
    assert key(date(2026, 12, 1)) == "iarna-2026"
    assert key(date(2027, 2, 28)) == "iarna-2026"  # iarna 2026/27: dec aparține iernii
    assert key(date(2027, 3, 1)) == "primavara-2027"
    assert key(date(2027, 5, 31)) == "primavara-2027"
    assert key(date(2027, 6, 1)) == "vara-2027"
    assert key(date(2027, 8, 31)) == "vara-2027"
    assert key(date(2027, 9, 1)) == "toamna-2027"
    assert se.season_of(date(2027, 1, 15))[1] == "iarnă 2026/27"
    assert se.season_of(date(2027, 9, 1))[1] == "toamnă 2027"


def test_local_day_for_observations_uses_romania_time():
    # 31.10 22:30 UTC = 01.11 00:30 ora României: ziua e 01.11
    rows = [wx("2026-11-01T00:30:00+02:00")]
    rows[0]["observed_at"] = "2026-10-31T22:30:00Z"
    assert se.weather_days(rows) == {date(2026, 11, 1): 1}


# ---- zile eligibile --------------------------------------------------------------------

def test_day_needs_half_of_the_expected_observations():
    d = date(2026, 10, 10)
    assert se.eligible_days(day_obs(d, 47), []) == {}
    assert se.eligible_days(day_obs(d, 48), []) == {d: 48}


def test_timetable_exclusion_is_plus_minus_seven_days():
    change = (date(2026, 12, 13),)
    ok = day_obs(date(2026, 12, 5), 96) + day_obs(date(2026, 12, 6), 96)
    assert se.eligible_days(ok, change) == {date(2026, 12, 5): 96}
    # 13.12 ± 7 zile = 06.12 … 20.12 (excluse); 21.12 e la 8 zile, deci eligibilă
    assert se.eligible_days(day_obs(date(2026, 12, 20), 96), change) == {}
    assert se.eligible_days(day_obs(date(2026, 12, 21), 96), change) == {date(2026, 12, 21): 96}


def test_timetable_changes_are_configuration_in_seasons_module():
    assert isinstance(se.TIMETABLE_CHANGE_DATES, tuple)
    assert se.TIMETABLE_MARGIN_DAYS == 7


# ---- potrivire ±30 min, noaptea schimbării orei ----------------------------------------

def test_match_on_dst_night_uses_read_time_to_pick_occurrence():
    # 25.10.2026, 03:10 programat; citit la 03:20 (+02, a doua apariție a orei 03:xx)
    j = jn("arrival", "2026-10-25", "03:10", 4, read_at="2026-10-25T03:20:00+02:00")
    # observație la 03:15 +02 = 01:15Z: trebuie să se potrivească
    hit = se.match([j], [wx("2026-10-25T03:15:00+02:00")], P)
    assert len(hit) == 1
    # observație la 03:10 +03 = 00:10Z (prima apariție): nu trebuie să se potrivească
    assert se.match([j], [wx("2026-10-25T03:10:00+03:00")], P) == []


def test_match_window_is_30_minutes():
    j = jn("arrival", "2026-11-03", "12:00", 2)
    assert len(se.match([j], [wx("2026-11-03T12:30:00+02:00")], P)) == 1
    assert se.match([j], [wx("2026-11-03T12:31:00+02:00")], P) == []


# ---- sezon: prag N=30, grupe, valori lipsă --------------------------------------------

def _autumn(n_days, temp=10.0, precip=0.0, per_day=48):
    rows, js = [], []
    for i in range(n_days):
        d = date(2026, 9, 1) + timedelta(days=i)
        rows += day_obs(d, per_day, temp, precip)
        js.append(jn("arrival", d.isoformat(), "12:00", 3 + (i % 4)))
    return js, rows


def test_season_below_threshold_has_no_groups():
    js, rows = _autumn(29)
    out = se.build(js, rows, P, ["arrival"], ())
    s = out["boards"]["arrival"]["seasons"][0]
    assert s["key"] == "toamna-2026" and s["days"] == 29 and s["enough"] is False
    assert "groups" not in s


def test_season_at_threshold_has_groups_and_compare_needs_two():
    js, rows = _autumn(30)
    out = se.build(js, rows, P, ["arrival"], ())
    b = out["boards"]["arrival"]
    s = b["seasons"][0]
    assert s["enough"] is True and s["days"] == 30
    assert {g["key"] for g in s["groups"]["precip"]} == {"dry"}
    assert b["compare"] is False  # un singur sezon eligibil


def test_compare_true_with_two_eligible_seasons():
    js1, rows1 = _autumn(30)
    rows2 = []
    js2 = []
    for i in range(30):
        d = date(2026, 12, 20) + timedelta(days=i)  # departe de ±7 zile din orar
        rows2 += day_obs(d, 48)
        js2.append(jn("arrival", d.isoformat(), "12:00", 2))
    out = se.build(js1 + js2, rows1 + rows2, P, ["arrival"], ())
    b = out["boards"]["arrival"]
    assert [s["key"] for s in b["seasons"]] == ["toamna-2026", "iarna-2026"]
    assert b["compare"] is True


def test_groups_comparable_only_from_30_journeys():
    js, rows = _autumn(30)
    out = se.build(js, rows, P, ["arrival"], ())
    g = out["boards"]["arrival"]["seasons"][0]["groups"]["precip"][0]
    assert g["n"] == 30 and g["comparable"] is True


def test_missing_values_stay_missing_not_zero():
    js, rows = _autumn(30)
    # ziua 1: temperatura și precipitațiile lipsesc (None); nu devin 0
    # ziua 1: temperatura și precipitațiile lipsesc (None); nu devin 0
    d0 = date(2026, 9, 1)
    gone = []
    for r in rows:
        local = datetime.fromisoformat(r["observed_at"].replace("Z", "+00:00")).astimezone(BUC)
        if local.date() == d0:
            r = dict(r, temperature_c=None, precipitation_mm=None)
        gone.append(r)
    out = se.build(js, gone, P, ["arrival"], ())
    s = out["boards"]["arrival"]["seasons"][0]
    assert sum(g["n"] for g in s["groups"]["precip"]) == 29  # None nu devine 0 (dry)
    assert sum(g["n"] for g in s["groups"]["temp"]) == 29


def test_days_under_half_of_observations_do_not_enter_groups():
    js, rows = _autumn(30)
    # a 31-a zi (eligibilă) și journey-ul ei; a 32-a zi are doar 10 observații
    extra_d = date(2026, 10, 1)
    rows += day_obs(extra_d, 10)
    js.append(jn("arrival", extra_d.isoformat(), "12:00", 50))
    out = se.build(js, rows, P, ["arrival"], ())
    s = out["boards"]["arrival"]["seasons"][0]
    assert s["days"] == 30
    assert sum(g["n"] for g in s["groups"]["precip"]) == 30  # ziua cu 10 obs nu contează


def test_wet_and_temp_groups():
    js, rows = _autumn(30, precip=1.5, temp=18.0)
    s = se.build(js, rows, P, ["arrival"], ())["boards"]["arrival"]["seasons"][0]
    assert [g["key"] for g in s["groups"]["precip"]] == ["wet"]
    assert [g["key"] for g in s["groups"]["temp"]] == ["15-25"]


def test_payload_has_note_and_no_causal_wording():
    out = se.build([], [], P, ["arrival"], ())
    assert "Corelație, nu cauzalitate" in out["note"]
    assert out["min_days"] == 30 and out["group_min"] == 30
    text = out["note"].lower()
    for bad in ("cauzează", "provoacă", "duce la", "din cauza"):
        assert bad not in text


def test_fetch_based_overview_reads_only(tmp_path):
    from app.store import Store
    s = Store(str(tmp_path / "s.db"))
    s.migrate()
    before = s._conn.total_changes
    out = se.overview(s, P, boards=None, changes=())
    assert out["boards"] == {} or isinstance(out["boards"], dict)
    assert s._conn.total_changes == before  # nicio scriere
    s.close()


def test_sezoane_js_is_csp_safe_and_has_header():
    from pathlib import Path
    js = (Path(__file__).resolve().parent.parent / "web" / "sezoane.js").read_text(encoding="utf-8")
    assert js.startswith("// © 2026 Andy217Ace")
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(",
                "new Function", ".style."):
        assert bad not in js, bad
    assert "date insuficiente (N=" in js
