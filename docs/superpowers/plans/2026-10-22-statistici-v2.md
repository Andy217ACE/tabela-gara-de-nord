# Statistici v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (execuție inline, decizie delegată). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Pagina `#statistici` refăcută: rezumat în cuvinte + grafice explicative dintr-un singur endpoint agregat, cu cache și conexiune read-only.

**Architecture:** `app/stats_overview.py` (fetch read-only → `build` pur → cache TTL) expus ca `GET /api/stats/overview`; UI nou în `web/statistici.js`/`web/statistici.css` (SVG în JS, clase CSS), vechea vizualizare scoasă din `stats.js`.

**Tech Stack:** Python 3.12, FastAPI, SQLite (WAL, `mode=ro`), JS vanilla ES5, SVG, pytest + Playwright.

**Spec:** `docs/superpowers/specs/2026-10-22-statistici-v2-design.md`

## Global Constraints

- `ON_TIME_MAX_MIN`=5, `STATS_MIN_SAMPLE`=5, `STATS_CACHE_TTL_S`=60; fantome + low_quality excluse (`quality.public_services_where`).
- Lipsă = `null`/„—”, niciodată 0; N lângă orice cifră; sub eșantion fără procente (`sufficient=false`).
- CSP: fără `innerHTML`, `.style.`, `style=`, scripturi inline; doar tokenuri de temă în CSS (fără hex în `statistici.css`).
- 390 px și 1280 px fără scroll orizontal, ambele teme; un singur footer.
- Nu se ating `app/ocr`, `app/quality.py`, `scripts/purge_ghosts.py`.

## Review Focus

- Bază goală (0 călătorii) → JSON valid, toate seriile goale, insights = mesaj „date insuficiente” (test `test_build_empty`).
- Filtru operator/tip care nu mai există → listă goală, nu 500 (test `test_api_unknown_operator`).
- `perioada` invalidă → 422 (test `test_api_bad_period`).
- Meteo lipsă (tabelă goală) → `weather.status == "collecting"` cu `matched=0` (test `test_weather_collecting`).
- Conexiunea read-only indisponibilă → fallback pe store, nu eroare (test `test_ro_fallback_memory`).

---

### Task 1: Agregări pure + fetch + cache (`app/stats_overview.py`)

**Files:** Create `app/stats_overview.py`, `tests/test_stats_overview.py`

**Interfaces:**
- Produces: `period_range(perioada: str, today: date) -> tuple[date|None, date|None]`; `build(rows: list[dict], weather: list[dict], extra: dict, p: stats.Params, today: date, filters: dict) -> dict`; `overview(store, p, filters: dict, today: date|None=None) -> dict`; `to_csv(data: dict, set_name: str) -> str`; `SETS` (tuple de nume).
- Chei JSON: `params, options, coverage, history, boards, insights, distribution, hourly, heatmap, daily, operators, types, routes, traffic, platforms, weather, quality, generated_at`.

- [ ] Test: `test_build_empty`, `test_board_summary_and_distribution`, `test_hourly_and_heatmap_mark_small_samples`, `test_operators_types_routes_min_sample`, `test_traffic_and_platforms_count_all_public_journeys`, `test_missing_platform_is_not_zero`, `test_insights_text`, `test_weather_collecting`, `test_weather_ok_groups`, `test_ghost_and_low_quality_excluded`, `test_period_range`, `test_cache_ttl`, `test_ro_fallback_memory`, `test_csv_sets`.
- [ ] Run → FAIL (modul inexistent).
- [ ] Implement.
- [ ] Run → PASS; commit.

### Task 2: Endpoint `GET /api/stats/overview` (`app/stats_api.py`)

**Files:** Modify `app/stats_api.py`; Test `tests/test_stats_overview.py`

- [ ] Test: `test_api_overview_json`, `test_api_filters_echo`, `test_api_bad_period`, `test_api_unknown_operator`, `test_api_csv_set`, `test_api_csv_bad_set`.
- [ ] Implement params `perioada|board|operator|tip|doar_confirmate|prag|min|from|to|format|set`; run → PASS; commit.

### Task 3: UI nou (`web/statistici.js`, `web/statistici.css`, tokenuri în `style.css`, `index.html`, `sw.js`)

**Files:** Create `web/statistici.js`, `web/statistici.css`, `tests/test_statistici_static.py`; Modify `web/stats.js` (scoate vizualizarea statistici, expune helperi), `web/style.css` (`--c-arr`, `--c-dep`, `--c-seq` în 3 blocuri de temă), `web/index.html`, `web/sw.js`, `tests/test_stats_static.py`.

- [ ] Test static: servit, CSP-safe, folosește `/api/stats/overview`, `App.views.statistici`, „Cum se citește”, „Vezi datele”, „date insuficiente încă”, „corelație”, `prefers-reduced-motion`; fără hex în CSS; în SHELL-ul SW.
- [ ] Implement; run → PASS; commit.

### Task 4: Test browser (`tests/test_statistici_browser.py`)

- [ ] 390×844 și 1280×800 × light/dark: rezumat vizibil, ≥ 8 grafice SVG, filtrele schimbă URL-ul, fără erori console/CSP, fără scroll orizontal, nimic în afara viewportului, un footer; caz bază goală → mesaj „date insuficiente”.
- [ ] Run → PASS; commit.

### Task 5: Release + deploy

- [ ] VERSION/CHANGELOG (versiunea liberă după `git fetch`), `sw.js` VERSION bump; suita completă verde.
- [ ] Review cu subagent; corecturi.
- [ ] Rebase pe `origin/feat/app`, push, backup server, `deploy/update.sh feat/app`, verificare live Playwright + capturi; raport.
