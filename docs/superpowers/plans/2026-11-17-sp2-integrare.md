# SP2 (Claritate vizuală) — lista de integrare pentru controller

Singura modificare din afara fișierelor permise: `app/api.py` nu a fost atinsă, dar `detail=train_list`
cere o linie în ruta existentă. Funcția `stats_overview.overview()` primește acum `detail=None`
(opțional, compatibil înapoi); `stats_overview.parse_detail(query_params)` validează cererea
și ridică `ValueError` cu mesaj în română.

## 1. `app/stats_api.py`, funcția `stats_overview_v2` (nu `app/api.py`: ruta e în `stats_api.py`)

Înainte de `d = await run_in_threadpool(overview_v2.overview, ...)`:

```python
    try:
        detail = overview_v2.parse_detail(q)
    except ValueError as e:
        raise _bad(str(e))
```

și apelul devine:

```python
    d = await run_in_threadpool(overview_v2.overview, _store(request), p, filters, today, detail)
```

Cu `detail` setat, răspunsul e `{"params", "detail", "train_list": {"rows", "total", "limit": 200,
"truncated"}}`; `format=csv` rămâne pentru răspunsul normal (cu `detail` + `format=csv`, adăugați
un 400 dacă doriți; interfața nu face asta). Fără `detail`, comportamentul e neschimbat.

Notă: `app/stats_api.py` nu era pe lista interzisă, dar nici pe cea permisă; nu l-am modificat ca să
respect regula de conflict. Testul `test_train_list_end_to_end_when_the_api_is_wired` din
`tests/test_stats_v3_sp2_browser.py` e sărit până la această modificare și devine activ după ea.

## 2. Cache-ul client

`web/sw.js`: `stat_sp2.js` NU se pune în `SHELL` (se încarcă la runtime, la primul click pe un grafic).
Dacă vreți versiune în URL, `statistici.js` îl cere ca `stat_sp2.js?v=1`.

## 3. Buget precache

Vezi raportul: măsurarea `test_icon_weights_and_precache_budget` la finalul sub-proiectului.

## 4. Contrast ridicat în meniul de temă (opțional, `web/app.js`)

`theme-init.js` expune acum `TabelaTheme.getContrast()` și `TabelaTheme.setContrast(bool)` (cheia
`tabela.contrast` în `localStorage`, `<html data-contrast="high">`). Butonul de temă din navbar e în
`web/app.js` (fișier în afara listei permise), așa că opțiunea apare deocamdată ca „Contrast ridicat”
în bara de filtre de la Statistici. Pentru a o pune și în navbar, `app.js` poate apela
`window.TabelaTheme.setContrast(!window.TabelaTheme.getContrast())` dintr-un buton propriu.
Stilurile de contrast sunt în `web/stat_sp2.css` (lazy), deci acționează pe pagina Statistici;
dacă se dorește global, regula `html:root[data-contrast="high"]` se mută în `style.css`.

## 5. Fișiere noi, încărcate la runtime (nu în `SHELL`)

`web/stat_sp2.js`, `web/stat_sp2.css` (cerute de `statistici.js` înaintea primei afișări).
`tests/i18n_allowlist.txt`: cele 3 intrări `web/statistici.js:NNNN` au fost mutate la liniile noi
(testul scanează după număr de linie; orice modificare a `statistici.js` din alt flux le mută din nou).
