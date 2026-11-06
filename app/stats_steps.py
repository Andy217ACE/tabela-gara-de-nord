# © 2026 Andy217Ace
"""Statistici — „Întârzieri în trepte” and „Număr de modificări”: deterministic, no AI.

Input: the public journeys of /api/stats/overview and their delay events (`old` is always
NULL, `new` = the minutes READ on the București Nord board; chronological per service).
Output: `steps[board]` = {`steps`: …, `changes`: …}.

Rules (documented choices):
- the series of a journey starts from an implicit 0: the first reading 0 -> 5 is a step of 5;
- values a revert shows to be a misread „+” (journeys.misread_values) are dropped, as are
  non-numeric readings and a repeat of the previous value;
- OCR noise: a bounce A -> B -> A (the value goes away and comes back to exactly the previous
  one, i.e. B lived one observation) is removed and only COUNTED (`bounces`); real recoveries
  almost never land on the exact previous value, so this keeps them;
- steps up (from -> to, to > from) and decreases (reveniri/scăderi) are reported apart, so
  the matrix is only about growth;
- a „modification” = a value of the cleaned series (the first one included);
- arrivals and departures are never mixed; below the minimum sample no percentages.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime

from app import journeys, stats

TOP_PAIRS = 12
TOP_SIZES = 8
TOP_TRAINS = 10
TOP_MIN_CHANGES = 2       # a train with one modification is not a „many changes” case
HIST_KEYS = ("0", "1", "2", "3", "4+")


def _median(vals):
    return stats._r(stats.percentile(sorted(vals), 0.5)) if vals else None


def _pct(k, n, p):
    return round(100.0 * k / n, 1) if n and n >= p.min_sample else None


def _ts(raw):
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def clean_points(evs) -> tuple[list[tuple[int, datetime | None]], int]:
    """Cleaned [(value, time)] of one journey's delay events and the number of bounces removed."""
    evs = evs or []
    bad = journeys.misread_values(evs)
    out: list[tuple[int, datetime | None]] = []
    bounces = 0
    for e in evs:
        v = journeys._int(e.get("new"))
        if v is None or v in bad:
            continue
        if out and out[-1][0] == v:
            continue
        if len(out) >= 2 and out[-2][0] == v:   # A, B, A: B was noise
            out.pop()
            bounces += 1
            continue
        out.append((v, _ts(e.get("ts"))))
    if out and out[0][0] == 0:                  # a first „0” is the baseline, not a change
        out.pop(0)
    return out, bounces


def clean_series(evs) -> tuple[list[int], int]:
    pts, bounces = clean_points(evs)
    return [v for v, _t in pts], bounces


def _board(js, p, events) -> dict:
    pairs, sizes, downs = Counter(), Counter(), []
    gaps, hist, per = [], Counter(), []
    first_ann, first_fin, first_complete, first_added = 0, 0, 0, []
    steps_j = bounces = 0
    for j in js:
        pts, b = clean_points(events.get(j["id"]))
        bounces += b
        vals = [v for v, _t in pts]
        k = len(vals)
        hist[HIST_KEYS[min(k, 4)]] += 1
        per.append((k, j, vals))
        if k:
            steps_j += 1
        prev = 0
        for v in vals:
            if v > prev:
                pairs[(prev, v)] += 1
                sizes[v - prev] += 1
            elif v < prev:
                downs.append(prev - v)
            prev = v
        for (_a, ta), (_b, tb) in zip(pts, pts[1:]):
            if ta and tb and ta.tzinfo is not None and tb.tzinfo is not None:
                gaps.append((tb - ta).total_seconds() / 60.0)
        pos = [v for v in vals if v > 0]
        if pos and vals[-1] > 0:
            fin, first = vals[-1], pos[0]
            first_ann += min(first, fin)
            first_fin += fin
            if first >= fin:
                first_complete += 1
            else:
                first_added.append(fin - first)
    nsteps = sum(pairs.values())
    nfirst = first_complete + len(first_added)
    top = sorted((x for x in per if x[0] >= TOP_MIN_CHANGES),
                 key=lambda x: (-x[0], -(x[2][-1] if x[2] else 0), x[1]["train_no"],
                                x[1]["service_date"]))[:TOP_TRAINS]
    n = len(per)
    total = sum(k for k, _j, _v in per)
    return {
        "steps": {
            "n_journeys": steps_j, "n_steps": nsteps, "ups": nsteps, "downs": len(downs),
            "down_median": _median(downs),
            "matrix": [{"from": a, "to": b, "n": c} for (a, b), c in
                       sorted(pairs.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_PAIRS]],
            "distinct_pairs": len(pairs),
            "median_size": _median([s for s, c in sizes.items() for _ in range(c)]),
            "sizes": [{"size": s, "n": c} for s, c in
                      sorted(sizes.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_SIZES]],
            "median_gap_min": _median(gaps), "gap_n": len(gaps),
            "first_share": {"n": nfirst, "complete": first_complete, "later": len(first_added),
                            "announced_min": first_ann, "final_min": first_fin,
                            "announced_pct": _pct(first_ann, first_fin, p) if nfirst >= p.min_sample else None,
                            "added_median": _median(first_added)},
            "bounces": bounces, "sufficient": nsteps >= p.min_sample,
        },
        "changes": {
            "n": n, "mean": round(total / n, 2) if n else None,
            "max": max((k for k, _j, _v in per), default=None), "bounces": bounces,
            "hist": [{"key": k, "n": hist[k], "pct": _pct(hist[k], n, p)} for k in HIST_KEYS],
            "top": [{"train_no": j["train_no"], "train_type": j["train_type"],
                     "station": j["station"], "date": j["service_date"],
                     "sched_time": j["sched_time"], "changes": k, "final": vals[-1],
                     "values": vals, "href": f"#tren?nr={j['train_no']}"}
                    for k, j, vals in top],
            "sufficient": n >= p.min_sample,
        },
    }


def build(js, boards, p, events: dict) -> dict:
    return {b: _board([j for j in js if j["board"] == b], p, events or {}) for b in boards}
