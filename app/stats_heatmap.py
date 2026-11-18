# © 2026 Andy217Ace
"""Statistici v3 sp3: `/api/stats/heatmap` — mean delay by weekday (0 = Monday ... 6 = Sunday) and
hour (0-23), per board (never mixed), with ONE scale for the whole picture (min 0, max = the highest
mean among cells that reach the minimum sample, so a single late journey cannot stretch it).

Read-only, cached 60 s through `stats_compare.load`; period = the request's (`perioada`), by default
the whole history. Under HISTORY_MIN_DAYS days of data: status `insufficient` + dictionary key and no
cells. A cell without a read delay has mean None (missing is never 0).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from app import stats
from app import stats_compare as cmp

DAYS = list(range(7))
HOURS = list(range(24))


def _board(rows: list[dict], p: stats.Params) -> list[dict]:
    g: dict = defaultdict(lambda: {"journeys": 0, "delays": []})
    for j in rows:
        k = (date.fromisoformat(j["service_date"]).weekday(), int(j["sched_time"][:2]))
        g[k]["journeys"] += 1
        if stats.counted(j, p):
            g[k]["delays"].append(j["result"]["observed_delay"])
    out = []
    for d in DAYS:
        for h in HOURS:
            v = g.get((d, h)) or {"journeys": 0, "delays": []}
            s = stats.summarize(v["delays"], p.on_time, p.min_sample)
            out.append({"d": d, "h": h, "journeys": v["journeys"], "n": s["n"], "mean": s["mean"],
                        "median": s["median"], "sufficient": s["sufficient"]})
    return out


def heatmap(store, p: stats.Params, filters: dict, today: date) -> dict:
    rows, extra = cmp.load(store, p)
    hist = cmp.history(extra)
    d = cmp.envelope(p, filters, today, hist)
    d.pop("window")
    d.update(days=DAYS, hours=HOURS)
    if not hist["sufficient"]:
        d.update(status="insufficient", message_key=cmp.INSUFFICIENT_KEY, boards={}, scale=None)
        return d
    op, tip = filters.get("operator"), filters.get("tip")
    rows = [j for j in rows if (not op or j["operator"] == op) and (not tip or j["train_type"] == tip)]
    boards = [p.board] if p.board else list(stats.BOARDS)
    cells = {b: _board([j for j in rows if j["board"] == b], p) for b in boards}
    means = [c["mean"] for v in cells.values() for c in v if c["sufficient"] and c["mean"] is not None]
    d.update(status="ok", boards=cells,
             scale={"min": 0, "max": max(means) if means else None, "unit": "min"})
    return d
