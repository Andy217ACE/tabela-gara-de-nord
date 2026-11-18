# Val 5 — lista de integrare (controller)

Schema DB: rămâne v9, fără migrare. Nimic de aplicat în `store.py` / `config.py`.

## app/api.py
1. Export CSV sezoane, în `stats_seasons` (ruta `/api/stats/seasons`, ~linia 564): adaugă parametrul `format`:
```python
    @app.get("/api/stats/seasons", include_in_schema=False)
    async def stats_seasons(request: Request, format: str = "json"):
        ...  # p = ca acum
        d = await run_in_threadpool(seasons.overview, store_of(request), p)
        if format == "csv":
            return Response(seasons.to_csv(d), media_type="text/csv; charset=utf-8",
                            headers={"Content-Disposition": 'attachment; filename="sezoane.csv"'})
        return d
```
2. Ruta estimării întârzierii finale (doar după ce poarta `predict.gate` trece pe baza reală; până atunci întoarce `published:false` cu motiv, fără cifre). Import `line_prediction`:
```python
    @app.get("/api/trains/{no}/prediction", include_in_schema=False)
    async def train_prediction(request: Request, no: int):
        from datetime import datetime
        def run():
            with stats_overview._reader(store_of(request)) as c:
                return line_prediction.compute(c, no, datetime.now(TZ).date())
        return await run_in_threadpool(run)
```
(cache 5 min ca la `/api/predict/peron` e recomandat: poarta rulează backtestul pe toată baza.)

## web/statistici.js (sau ui2.js, la alegerea controllerului)
Montare lazy: la deschiderea secțiunii „Sezoane”: încarcă `val5_seasons.js` + `val5.css`, apoi `window.Val5.mountSeasons(host, queryString)`. Pentru fișa trenului: `fetch('/api/trains/'+no+'/prediction')` apoi `window.Val5.renderPrediction(host, json)`.
Nu se adaugă în SHELL din `sw.js`; `sezoane.js`, `val5_seasons.js`, `val5.css` se încarcă la runtime (adaugă `val5_seasons.js` în lista LAZY din `tests/test_sw_precache_lazy.py` dacă se vrea acoperire).

## app/api.py, includere router
Nimic pentru peron: `peron_api.router` e deja inclus.
