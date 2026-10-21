# © 2026 Andy217Ace
"""Station pages (Etapa D2): journeys coming FROM a station (arrivals board) or going
TO it (departures board), exactly as the București Nord board displays them.

The delay is the one read on the București Nord board, NOT at the station itself.
Names are the canonical ones stored by the OCR canonicalisation (upper case, no
diacritics); journeys passing through a station but shown with another origin /
destination are never attributed to it.
"""
from __future__ import annotations

from collections import defaultdict

from app import stats
from app.normalize import clean_station

NOTE = ("Întârzierea este cea afișată pe tabela din București Nord (la sosirea sau "
        "plecarea din Gara de Nord), nu la stația {name}. Trenurile sunt atribuite stației "
        "doar când tabela o afișează ca origine (sosiri) sau destinație (plecări).")
LIST_MAX = 500
JOURNEYS_PAGE_MAX = 500


def canonical(name: str) -> str:
    return clean_station(name or "")


def list_stations(store, query: str | None = None, limit: int = 100) -> list[dict]:
    where, args = "", []
    if query:
        q = canonical(query) or query.strip().upper()
        esc = q.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        where = " WHERE station LIKE ? ESCAPE '!'"
        args.append(f"%{esc}%")
    sql = ("SELECT station, COUNT(*) AS journeys,"
           " SUM(board='arrival') AS arrivals, SUM(board='departure') AS departures,"
           " COUNT(DISTINCT train_no) AS trains,"
           " SUM(delay_read_at IS NOT NULL AND status='gone') AS delay_known,"
           " SUM(uncertain=0) AS certain,"
           " MIN(service_date) AS first_date, MAX(service_date) AS last_date"
           f" FROM services{where} GROUP BY station"
           " ORDER BY journeys DESC, station LIMIT ?")
    with store._lock:
        rows = store._conn.execute(sql, args + [int(limit)]).fetchall()
    return [{"name": r["station"], "journeys": r["journeys"], "arrivals": r["arrivals"],
             "departures": r["departures"], "trains": r["trains"],
             "delay_known": r["delay_known"], "first_date": r["first_date"],
             "last_date": r["last_date"],
             # every journey had a name that did not match a known station: maybe a misread
             "uncertain_only": r["certain"] == 0} for r in rows if r["station"]]


def station_entries(js: list[dict], p: stats.Params) -> list[dict]:
    """One ranking entry per (station, board)."""
    groups: dict = defaultdict(list)
    for j in js:
        groups[(j["station"], j["board"])].append(j)
    out = []
    for (name, board), g in groups.items():
        out.append({"station": name, "board": board, "journeys": len(g),
                    "trains": len({j["train_no"] for j in g}),
                    "quality": stats.quality(g),
                    "stats": stats.summarize(stats.delays(g, p), p.on_time, p.min_sample)})
    out.sort(key=lambda e: (e["station"], e["board"]))
    return out


def rank_stations(js: list[dict], p: stats.Params, limit: int = 10) -> dict:
    entries = station_entries(js, p)
    ranked = [e for e in entries if e["stats"]["n"] >= p.min_sample]
    below = sum(1 for e in entries if 0 < e["stats"]["n"] < p.min_sample)
    delayed = sorted(ranked, key=lambda e: (-e["stats"]["mean"], -e["stats"]["median"],
                                            e["station"], e["board"]))
    punctual = sorted(ranked, key=lambda e: (-e["stats"]["on_time_pct"], e["stats"]["mean"],
                                             e["station"], e["board"]))
    return {"eligible": len(ranked), "below_min": below,
            "most_delayed": delayed[:limit], "most_punctual": punctual[:limit],
            "_ranked": delayed}


def detail(store, name: str, p: stats.Params) -> dict | None:
    name = canonical(name)
    if not name:
        return None
    js = stats.load(store, p, ["s.station = ?"], [name])
    if not js:
        return None
    every = stats.load(store, p)
    ranking = rank_stations(every, p, limit=0)["_ranked"]
    boards = {}
    for b in stats.BOARDS:
        if p.board and p.board != b:
            continue
        bj = [j for j in js if j["board"] == b]
        pos = next((i for i, e in enumerate(r for r in ranking if r["board"] == b)
                    if e["station"] == name), None)
        boards[b] = {
            "journeys": len(bj),
            "stats": stats.summarize(stats.delays(bj, p), p.on_time, p.min_sample),
            "quality": stats.quality(bj),
            "distribution": stats.distribution(stats.delays(bj, p)),
            "trains": stats.train_entries(bj, p),
            # 1 = most delayed among stations with at least min_sample journeys
            "rank": {"position": None if pos is None else pos + 1,
                     "of": sum(1 for r in ranking if r["board"] == b)},
        }
    stamps = sorted(j["first_seen"] for j in js) + sorted(j["last_seen"] for j in js)
    dates = sorted(j["service_date"] for j in js)
    return {
        "params": p.echo(),
        "name": name,
        "note": NOTE.format(name=name),
        "journeys": len(js),
        "trains": len({j["train_no"] for j in js}),
        "uncertain_names": sum(1 for j in js if j["uncertain"]),
        "first_seen": min(stamps), "last_seen": max(stamps),
        "period": {"first": dates[0], "last": dates[-1], "days": len(set(dates))},
        "quality": stats.quality(js),
        "boards": boards,
        "by_time": stats.by_time(js, p),
    }


def journeys_page(store, name: str, p: stats.Params, limit: int = 100,
                  before: int | None = None) -> dict | None:
    """Journeys of a station, newest first, paginated by id (`before`)."""
    name = canonical(name)
    if not name:
        return None
    where, args = ["s.station = ?"], [name]
    if before is not None:
        where.append("s.id < ?")
        args.append(before)
    js = stats.load(store, p, where, args)
    if not js and before is None:
        return None
    js.sort(key=lambda j: j["id"], reverse=True)
    page = js[:limit]
    return {"params": p.echo(), "name": name, "n": len(page),
            "next_before": page[-1]["id"] if len(js) > limit else None,
            "journeys": [stats.journey_public(j) for j in page]}
