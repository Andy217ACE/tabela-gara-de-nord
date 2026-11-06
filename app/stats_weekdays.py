# © 2026 Andy217Ace
"""Statistici — „Comparație pe zilele săptămânii” (luni–duminică), separat sosiri / plecări.

Prag de încredere: MIN_APPEARANCES (N=4). O zi a săptămânii are cifre afișate doar dacă a apărut
în cel puțin N date calendaristice DISTINCTE și COMPLETE; altfel e „date insuficiente” (numărul
brut de servicii rămâne vizibil, procentele și mediana sunt ascunse). Ziua curentă nu e completă:
datele ei nu intră în nicio cifră și nu se numără ca apariție (se semnalează `partial_today`).
Cât timp nicio zi a săptămânii nu atinge pragul, statusul e „collecting” (mesaj + numărul de
săptămâni acumulate = cea mai mare apariție a unei zile; nu se desenează nimic).
Reguli moștenite: întârzierea necunoscută nu e 0, percentajele cer min_sample, panourile nu se
amestecă. Funcție pură: nu citește baza de date.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from app import stats

MIN_APPEARANCES = 4
MESSAGE = "Comparația va deveni valabilă după ~4 săptămâni de date"


def build(js: list[dict], boards: list[str], p: stats.Params, today: date) -> dict:
    today_s = today.isoformat()
    out_boards, weeks = {}, 0
    today_wd = today.weekday()
    for b in boards:
        rows = [j for j in js if j["board"] == b]
        days = defaultdict(set)                       # weekday -> complete service dates
        groups = defaultdict(lambda: {"journeys": 0, "delays": []})
        partial = False
        for j in rows:
            sd = j["service_date"]
            if sd >= today_s:                         # ziua curentă (sau viitor): incompletă
                partial = partial or sd == today_s
                continue
            w = date.fromisoformat(sd).weekday()
            days[w].add(sd)
            groups[w]["journeys"] += 1
            if stats.counted(j, p):
                groups[w]["delays"].append(j["result"]["observed_delay"])
        cells = []
        for w in range(7):
            n_app = len(days[w])
            g = groups[w]
            reliable = n_app >= MIN_APPEARANCES
            s = stats.summarize(g["delays"], p.on_time, p.min_sample)
            weeks = max(weeks, n_app)
            cells.append({
                "d": w, "label": stats.WEEKDAYS[w], "appearances": n_app,
                "reliable": reliable, "journeys": g["journeys"], "n": s["n"],
                "per_day": round(g["journeys"] / n_app, 1) if reliable else None,
                "on_time_pct": s["on_time_pct"] if reliable else None,
                "median": s["median"] if reliable else None,
                "over_30_pct": s["over_30_pct"] if reliable else None,
                "partial_today": partial and w == today_wd,
            })
        out_boards[b] = cells
    ok = any(c["reliable"] for cells in out_boards.values() for c in cells)
    return {"min_appearances": MIN_APPEARANCES, "status": "ok" if ok else "collecting",
            "weeks": weeks, "message": None if ok else MESSAGE,
            "today_weekday": today_wd, "boards": out_boards}
