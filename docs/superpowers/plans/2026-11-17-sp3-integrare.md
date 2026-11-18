# SP3 (Conținut nou) — lista de integrare pentru controller

Tot codul de calcul e în module noi (`app/stats_compare.py`, `app/stats_changes.py`, `app/stats_heatmap.py`),
read-only, cu cache 60 s prin `stats_overview._fresh/_put` (același TTL, `STATS_CACHE_TTL_S`). Singura
modificare din afara fișierelor permise este în `app/stats_api.py` (fișier interzis mie): patru rute, mai jos.
Până se leagă, `web/stat_sp3.js` ascunde secțiunile (404 la `reliable`/`heatmap` elimină secțiunea, erorile
la `changes`/`compare` lasă sumarul neschimbat) și `tests/test_stats_v3_sp3_api.py` se sare.

## 1. `app/stats_api.py`, importuri

Lângă `from app import stats_overview as overview_v2` (numele exact din fișier):

```python
from app import stats_changes, stats_compare, stats_heatmap
```

## 2. `app/stats_api.py`, helper comun (după `_store`)

```python
def _sp3_args(request: Request):
    """(params, filters, today) for the sp3 routes: `perioada`, `board`, `operator`, `tip`,
    `doar_confirmate`, `prag`, `min` — the same reading as /api/stats/overview."""
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
        if p.date_from or p.date_to:
            raise _bad("„perioada” și „from”/„to” nu se folosesc împreună.")
        p.date_from, p.date_to = overview_v2.period_range(perioada, today)
    return p, filters, today
```

(`changes` și `compare` folosesc mereu ultimele 7 zile față de cele 7 dinaintea lor, deci ignoră
`perioada`; `heatmap` și `reliable` o respectă.)

## 3. `app/stats_api.py`, rute noi (după `stats_overview_v2`)

```python
@router.get("/api/stats/changes")
async def stats_changes_route(request: Request):
    """„Ce s-a schimbat săptămâna asta” + alertele pe prag (mediană > 15 min, ultimele 7 zile)."""
    p, filters, today = _sp3_args(request)
    return await run_in_threadpool(stats_changes.changes, _store(request), p, filters, today)


@router.get("/api/stats/heatmap")
async def stats_heatmap_route(request: Request):
    """Întârzierea medie pe zi a săptămânii (0-6) și oră (0-23), cu scală comună."""
    p, filters, today = _sp3_args(request)
    return await run_in_threadpool(stats_heatmap.heatmap, _store(request), p, filters, today)


@router.get("/api/stats/reliable")
async def stats_reliable_route(request: Request):
    """„Cele mai fiabile trenuri”: minim 10 călătorii cu întârziere citită."""
    p, filters, today = _sp3_args(request)
    return await run_in_threadpool(stats_changes.reliable, _store(request), p, filters, today)
```

Rută adăugată față de specificație: `/api/stats/reliable` (specificația cere secțiunea, nu numește
endpoint-ul; `stats_overview.build` e în afara listei mele, deci nu am putut-o pune în sumar).

## 4. `app/stats_api.py`, `stats_overview_v2`: `compare=prev7`

După blocul `try: detail = overview_v2.parse_detail(q) ...` și înainte de
`d = await run_in_threadpool(overview_v2.overview, ...)`:

```python
    compare = (q.get("compare") or "").strip()
    if compare:
        if compare != "prev7":
            raise _bad("Parametrul „compare” poate fi doar prev7.")
        if detail or fmt == "csv":
            raise _bad("„compare” nu se combină cu „detail” sau cu exportul CSV.")
        return await run_in_threadpool(stats_compare.compare, _store(request), p, filters, today)
```

Răspunsul cu `compare=prev7` este payload-ul comparației (`status`, `now`, `before`, `delta`, `window`,
`history`), nu sumarul complet: interfața îl cere separat, cu filtrele paginii fără `perioada`.

## 5. Forma răspunsurilor (pentru teste de contract)

- `changes`: `{params, window{now,before}, history{days,needed_days,sufficient}, generated_at, cache_ttl_s,
  alert_threshold_min: 15, alerts[{kind,board,key,median,n,threshold}], status: "ok"|"insufficient",
  improved[], worsened[] (cel mult 3 rute + 3 operatori, fiecare {kind,board,key,now_pct,before_pct,delta,n_now,n_before}),
  message_key: "stats.sp3.insufficient" (doar la insufficient)}`.
- `compare`: `{..., compare: "prev7", status, now{n,on_time,on_time_pct,mean,median,sufficient,journeys,trains},
  before{...}, delta{on_time_pct,mean,median,journeys,trains}}`; `now/before/delta = null` la `insufficient`.
- `heatmap`: `{status, days:[0..6], hours:[0..23], boards{board:[168 celule {d,h,journeys,n,mean,median,sufficient}]},
  scale{min:0,max,unit:"min"}}`; `boards = {}` și `scale = null` la `insufficient`; `max = null` fără nicio celulă cu eșantion suficient.
- `reliable`: `{status: "ok"|"empty", min_journeys: 10, eligible, items[{train_no,train,board,operator,route,n,journeys,on_time_pct,mean,median}] (cel mult 10), message_key (la empty)}`.
- Sub 7 zile de date (zile distincte cu servicii publice) `changes`, `compare` și `heatmap` răspund `insufficient`
  cu cheia de dicționar, niciodată valori zero. Alertele rămân (sunt cifre ale ultimelor 7 zile, cu N și eșantion minim).

## 6. Fișiere noi, încărcate la runtime (nu în `SHELL`)

`web/stat_sp3.js`, `web/stat_sp3.css`, cerute de `statistici.js` înaintea primei afișări (`layer("statSp3", "stat_sp3")`,
URL `stat_sp3.js?v=1`). `web/sw.js` nu se atinge. Precache neschimbat (SHELL intact; `statistici.js` are +0 linii:
cele două modificări sunt pe linii existente, deci `tests/i18n_allowlist.txt` nu s-a mișcat).

## 7. Teste

`tests/test_stats_v3_sp3_{changes,alerts,compare,reliable,heatmap}.py` (funcțiile din module, fără rută),
`tests/test_stats_v3_sp3_static.py`, `tests/test_stats_v3_sp3_browser.py` (browserul interceptează cele 4 rute și
răspunde cu modulele reale pe baza de test), `tests/test_stats_v3_sp3_api.py` (se activează după legarea rutelor).
