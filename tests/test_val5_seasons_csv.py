# © 2026 Andy217Ace
"""Val 5a: exportul CSV al sezoanelor are aceleași N ca payload-ul; sezonul sub prag apare
ca rând „date insuficiente”, fără cifre."""
from datetime import date, timedelta

from app import seasons as se
from app import stats
from tests.test_seasons import day_obs, jn

P = stats.Params(on_time=5, min_sample=5)


def _payload(n_days):
    rows, js = [], []
    for i in range(n_days):
        d = date(2026, 9, 1) + timedelta(days=i)
        rows += day_obs(d, 48)
        js.append(jn("arrival", d.isoformat(), "12:00", 3 + (i % 4)))
    return se.build(js, rows, P, ["arrival"], ())


def test_csv_same_n_as_payload():
    out = _payload(30)
    text = se.to_csv(out)
    assert text.startswith("﻿")
    lines = text.lstrip("﻿").strip().split("\r\n")
    assert lines[0].startswith("board,season,season_days,dimension,key,label,n")
    groups = out["boards"]["arrival"]["seasons"][0]["groups"]
    want = {(dim, g["key"]): g["n"] for dim, gs in groups.items() for g in gs}
    got = {}
    for ln in lines[1:]:
        c = ln.split(",")
        got[(c[3], c[4])] = int(c[6])
    assert got == want and want


def test_csv_insufficient_season_has_no_figures():
    text = se.to_csv(_payload(10))
    lines = text.lstrip("﻿").strip().split("\r\n")
    assert len(lines) == 2
    c = lines[1].split(",")
    assert c[2] == "10" and c[3] == "insufficient" and c[6] == "" and c[7] == ""


def test_csv_rows_never_mix_boards():
    out = _payload(30)
    assert {ln.split(",")[0] for ln in se.to_csv(out).strip().split("\r\n")[1:]} == {"arrival"}
