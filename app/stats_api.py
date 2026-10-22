# © 2026 Andy217Ace
"""Public read-only endpoints: journeys (final result), catalog stats, statistics,
rankings. JSON by default, `format=csv` for exports. Delays are those READ on the
București Nord board; arrivals and departures are never mixed."""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from app import journeys, stations, stats
from app import stats_overview as overview_v2

router = APIRouter()
MAX_QUERY = 40
JOURNEYS_MAX = 5000
RANK_MAX = 50
STATES = set(journeys.STATES)


def _bad(msg: str) -> HTTPException:
    return HTTPException(status_code=422, detail=msg)


def _int(raw: str | None, name: str, lo: int, hi: int) -> int | None:
    if raw is None or raw == "":
        return None
    if not (raw.isascii() and raw.isdigit() and lo <= int(raw) <= hi):
        raise _bad(f"Parametru „{name}” invalid ({lo}–{hi}).")
    return int(raw)


def _date(raw: str | None, name: str) -> date | None:
    if not raw:
        return None
    try:
        if len(raw) != 10:
            raise ValueError
        return date.fromisoformat(raw)
    except ValueError:
        raise _bad(f"Data „{name}” invalidă (AAAA-LL-ZZ).") from None


def params(request: Request) -> stats.Params:
    q = request.query_params
    board = q.get("board") or None
    if board is not None and board not in stats.BOARDS:
        raise _bad("Panou invalid (arrival sau departure).")
    d0, d1 = _date(q.get("from"), "de la"), _date(q.get("to"), "până la")
    if d0 and d1 and d0 > d1:
        raise _bad("Data „de la” este după data „până la”.")
    conf = q.get("doar_confirmate") or "0"
    if conf not in ("0", "1"):
        raise _bad("Parametru „doar_confirmate” invalid (0 sau 1).")
    return stats.Params(on_time=_int(q.get("prag"), "prag", 0, 60),
                        min_sample=_int(q.get("min"), "min", 1, 1000),
                        board=board, date_from=d0, date_to=d1, confirmed_only=conf == "1")


def _fmt(request: Request) -> str:
    f = request.query_params.get("format") or "json"
    if f not in ("json", "csv"):
        raise _bad("Format invalid (json sau csv).")
    return f


def _csv(body: str, name: str) -> Response:
    return Response(body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _store(request: Request):
    return request.app.state.store


@router.get("/api/journeys")
async def journeys_list(request: Request):
    p = params(request)
    fmt = _fmt(request)
    q = request.query_params
    where, args = [], []
    train = _int(q.get("train"), "train", 1, 999999)
    if train is not None:
        where.append("s.train_no = ?")
        args.append(train)
    station = (q.get("station") or "").strip()
    if len(station) > MAX_QUERY:
        raise _bad("Numele stației este prea lung.")
    if station:
        where.append(f"{journeys.STATION_SQL} = ?")
        args.append(stations.canonical(station) or station.upper())
    state = q.get("state") or None
    if state is not None and state not in STATES:
        raise _bad("Stare invalidă.")
    limit = _int(q.get("limit"), "limit", 1, JOURNEYS_MAX) or 500

    def run():
        js = stats.load(_store(request), p, where, args)
        if state:
            js = [j for j in js if j["result"]["state"] == state]
        return js

    js = await run_in_threadpool(run)
    truncated = len(js) > limit
    items = [stats.journey_public(j) for j in js[:limit]]
    if fmt == "csv":
        return _csv(stats.journeys_csv(items), "calatorii.csv")
    return {"params": p.echo(), "n": len(items), "total": len(js), "truncated": truncated,
            "journeys": items}


@router.get("/api/journeys/{jid}")
async def journey(request: Request, jid: str):
    if not (jid.isascii() and jid.isdigit() and len(jid) <= 12):
        raise _bad("Identificator de călătorie invalid.")
    d = await run_in_threadpool(journeys.detail, _store(request), int(jid))
    if d is None:
        raise HTTPException(status_code=404, detail="Călătoria nu există.")
    return d


@router.get("/api/trains/stats")
async def trains_stats(request: Request):
    p = params(request)
    fmt = _fmt(request)
    query = (request.query_params.get("query") or "").strip()
    if len(query) > MAX_QUERY:
        raise _bad("Căutarea este prea lungă.")
    d = await run_in_threadpool(stats.catalog, _store(request), p, query or None)
    if fmt == "csv":
        return _csv(stats.entries_csv(d["trains"]), "trenuri.csv")
    return d


@router.get("/api/trains/{no}/journeys")
async def train_journeys(request: Request, no: str):
    if not (no.isascii() and no.isdigit() and len(no) <= 6 and 0 < int(no) < 1_000_000):
        raise _bad("Număr de tren invalid.")
    p = params(request)
    fmt = _fmt(request)
    d = await run_in_threadpool(stats.train_profile, _store(request), int(no), p)
    if d is None:
        raise HTTPException(status_code=404, detail="Trenul nu a fost observat.")
    if fmt == "csv":
        return _csv(stats.journeys_csv(d["journeys"]), f"tren-{int(no)}.csv")
    return d


@router.get("/api/stats")
async def stats_overview(request: Request):
    p = params(request)
    if _fmt(request) == "csv":
        raise _bad("Pentru export CSV folosiți /api/journeys?format=csv sau /api/trains/stats?format=csv.")
    return await run_in_threadpool(stats.overview, _store(request), p)


@router.get("/api/stats/overview")
async def stats_overview_v2(request: Request):
    """Everything the #statistici page shows, in one cached read-only computation:
    `perioada` (1|7|30|all), `board`, `operator`, `tip`, `doar_confirmate`, `prag`, `min`;
    `format=csv&set=<name>` exports one data set."""
    q = request.query_params
    perioada = q.get("perioada") or "all"
    if perioada not in overview_v2.PERIODS:
        raise _bad("Perioadă invalidă (1, 7, 30 sau all).")
    filters = {"perioada": perioada}
    for name in ("operator", "tip"):
        v = (q.get(name) or "").strip()
        if len(v) > MAX_QUERY:
            raise _bad(f"Parametru „{name}” prea lung.")
        filters[name] = v or None
    p = params(request)
    today = datetime.now(journeys.TZ).date()
    if perioada != "all":
        p.date_from, p.date_to = overview_v2.period_range(perioada, today)
    fmt = _fmt(request)
    set_name = q.get("set") or ""
    if fmt == "csv" and set_name not in overview_v2.SETS:
        raise _bad("Set invalid pentru export CSV (" + ", ".join(overview_v2.SETS) + ").")
    d = await run_in_threadpool(overview_v2.overview, _store(request), p, filters, today)
    if fmt == "csv":
        return _csv(overview_v2.to_csv(d, set_name), f"statistici-{set_name}.csv")
    return d


@router.get("/api/stats/rankings")
async def stats_rankings(request: Request):
    p = params(request)
    fmt = _fmt(request)
    limit = _int(request.query_params.get("limit"), "limit", 1, RANK_MAX) or 10

    def run():
        d = stats.rankings(_store(request), p, limit)
        st = stations.rank_stations(stats.load(_store(request), p), p, limit)
        st.pop("_ranked")
        d["stations"] = st
        return d

    d = await run_in_threadpool(run)
    if fmt == "csv":
        rows = []
        for name in ("most_delayed", "most_punctual"):
            for i, e in enumerate(d[name], 1):
                rows.append([name, i, e["train_no"], e["board"], e["station"]]
                            + [e["stats"][c] for c in stats.STAT_COLS])
            for i, e in enumerate(d["stations"][name], 1):
                rows.append(["stations_" + name, i, "", e["board"], e["station"]]
                            + [e["stats"][c] for c in stats.STAT_COLS])
        return _csv(stats.to_csv(["list", "rank", "train_no", "board", "station"]
                                 + stats.STAT_COLS, rows), "clasamente.csv")
    return d


def _station_name(name: str) -> str:
    if len(name) > MAX_QUERY:
        raise _bad("Numele stației este prea lung.")
    canon = stations.canonical(name)
    if not canon:
        raise _bad("Nume de stație invalid.")
    return canon


@router.get("/api/stations")
async def stations_list(request: Request):
    q = request.query_params
    query = (q.get("query") or "").strip()
    if len(query) > MAX_QUERY:
        raise _bad("Căutarea este prea lungă.")
    limit = _int(q.get("limit"), "limit", 1, stations.LIST_MAX) or 100
    fmt = _fmt(request)
    items = await run_in_threadpool(stations.list_stations, _store(request), query or None, limit)
    if fmt == "csv":
        cols = ["name", "journeys", "arrivals", "departures", "trains", "delay_known",
                "first_date", "last_date", "uncertain_only"]
        return _csv(stats.to_csv(cols, [[i[c] for c in cols] for i in items]), "statii.csv")
    return {"n": len(items), "stations": items}


@router.get("/api/stations/{name}")
async def station_detail(request: Request, name: str):
    canon = _station_name(name)
    p = params(request)
    fmt = _fmt(request)
    d = await run_in_threadpool(stations.detail, _store(request), canon, p)
    if d is None:
        raise HTTPException(status_code=404, detail="Stația nu a fost observată pe tabelă.")
    if fmt == "csv":
        entries = [e for b in d["boards"].values() for e in b["trains"]]
        return _csv(stats.entries_csv(entries), f"statie-{_slug(canon)}.csv")
    return d


@router.get("/api/stations/{name}/journeys")
async def station_journeys(request: Request, name: str):
    canon = _station_name(name)
    p = params(request)
    fmt = _fmt(request)
    q = request.query_params
    limit = _int(q.get("limit"), "limit", 1, stations.JOURNEYS_PAGE_MAX) or 100
    before = _int(q.get("before"), "before", 1, 10**12)
    d = await run_in_threadpool(stations.journeys_page, _store(request), canon, p, limit, before)
    if d is None:
        raise HTTPException(status_code=404, detail="Stația nu a fost observată pe tabelă.")
    if fmt == "csv":
        return _csv(stats.journeys_csv(d["journeys"]), f"statie-{_slug(canon)}-calatorii.csv")
    return d


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-") or "statie"
