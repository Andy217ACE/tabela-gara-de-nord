# Tabela Gara de Nord — Plan master (v1 rămas + v2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Produs public: panou LIVE în stil de gară (sosiri + plecări) peste care se construiesc istoric, catalog, statistici, alerte, meteo și predicții.

**Specs:** `docs/superpowers/specs/2026-10-20-tabela-gara-de-nord-design.md` (v1) și `docs/superpowers/specs/2026-10-21-roadmap-v2-direction.md` (direcția v2, cu principiile obligatorii).
**Planul v1 (istoric):** `docs/superpowers/plans/2026-10-20-tabela-gara-de-nord.md` — Task 1–10 și deploy-ul inițial sunt FĂCUTE (vezi starea mai jos). Task 11 din v1 este reluat aici ca A1.

## Global Constraints (valabile în toate etapele)
- Atribuire peste tot: `© 2026 Andy217Ace · Date preluate de la CFR (cfr.ro) — proiect independent, neafiliat CFR`; antet `© 2026 Andy217Ace` în fișiere sursă; `LICENSE` MIT.
- Tesseract = motor OCR principal, în spatele interfeței `OcrEngine`; fără ML/LLM în OCR.
- Date citite ≠ calculate/estimate; valoare lipsă ≠ 0; date vechi marcate vizibil; nimic inventat.
- Călătorie ≠ număr de tren ≠ observație; orice statistică afișează numărul de călătorii folosit (N) și respectă un eșantion minim configurabil.
- Corelație ≠ cauzalitate (meteo); predicțiile se evaluează temporal fără scurgeri din viitor.
- Migrații versionate (`PRAGMA user_version`), fără ștergeri de date istorice; backup înainte de orice migrare pe server.
- CSP: fără `<style>`, `style=`, scripturi inline; DOM construit cu `textContent`.
- Secrete doar în env (`/etc/tabela.env`), `.env.example` fără valori reale; endpointuri administrative cu autentificare.
- Git: branch-uri `feat/*`, PR către `main`; deploy după fiecare etapă funcțională; migrare server pe `main` după merge.
- Fus orar `Europe/Bucharest` pentru afișare, UTC pentru meteo.

## Starea curentă
| Parte | Stare |
|---|---|
| v1 Task 1–10 (OCR, poller sincronizat, store, istoric, notifier, API, UI LIVE) | gata, în `feat/app` (PR #1 deschis) |
| Deploy v1 pe tabelacfr.ddns.net | live (health ok, 12+12 rânduri); raportul final al agentului de deploy încă în așteptare |
| Merge PR #1 în `main` | blocat de classifier — îl face utilizatorul |
| Minori amânați | vezi `.superpowers/sdd/.../progress.md` (jitter claim, OcrError export, banner offline la visibilitychange, skeleton pe eșec, sr-only pentru `*`, dev_seed fără tests.conftest, sync store calls în notifier, `/api/history` fără limită) |

---

## Etapa A — Stabilizare + LIVE-Panou (următoarea)

### Task A1: Istoric, Urmărite și PWA (ex Task 11 din v1)
**Files:** `web/history.js`, `web/follows.js`, `web/sw.js`, `web/manifest.webmanifest`, `web/index.html`, `web/app.js`, `web/style.css`, `tests/test_web_static.py`
**Interfaces:** Consumes `/api/history`, `/api/train/{no}`, `/api/follow*`, `/api/push/{key,subscribe,unsubscribe}`, `/api/follows`. Produces `window.TabelaApp.onFollow(train, button)` real.
- [ ] Ecran Istoric (zi, nr. tren, stație, interval; listă cu oră programată, întârziere max/finală, linie; detaliu evenimente per tren) cu stare goală și N afișat.
- [ ] Ecran Urmărite (listă + activare/dezactivare notificări); mesaj „Notificările necesită HTTPS" când lipsesc `Notification`/`PushManager`.
- [ ] `sw.js`: cache shell + ultima tabelă offline marcată veche; handlere `push` și `notificationclick`; `manifest.webmanifest` + link în `index.html`; icon placeholder (se înlocuiește cu sigla).
- [ ] Teste statice (manifest JSON valid, sw servit ca JS, CSP-compat) + Playwright pe domeniul live după deploy; redeploy.

### Task A2: Interfața `OcrEngine` + canonicalizare operator/stație
**Files:** `app/ocr/engine.py` (nou), `app/ocr/reader.py`, `app/canonical.py` (nou), `data/operators.txt`, `tests/test_canonical.py`, `tests/test_ocr.py`
**Interfaces:** `class OcrEngine(Protocol): read_cells(image: np.ndarray, spec: CellSpec) -> list[CellResult]` (text, conf, bbox); `TesseractEngine` implementarea curentă; `canonical_operator(text) -> tuple[str, float]`, `canonical_station(text, known: set[str]) -> tuple[str, float]` (potrivire fuzzy `difflib`, prag configurabil; sub prag păstrează textul brut și marchează `uncertain`).
- [ ] Extrage apelurile Tesseract în `TesseractEngine`; `read_board(image_bytes, engine=None)`; testele OCR existente rămân verzi (24/24 numerice).
- [ ] Listă de operatori cunoscuți (CFR Calatori, Transferoviar, Regio Calatori, InterRegional, Astra Trans Carpatic, Softrans, Unicredit… doar cei văzuți efectiv în date) + stații învățate din istoric; test pe zgomot tip „“Mransferoviar" → Transferoviar.
- [ ] `Row` păstrează `operator_raw` și `station_raw` (migrare store: coloane noi `*_raw`).

### Task A3: Mod „Panou" (afișaj de gară)
**Files:** `web/index.html`, `web/panel.css`, `web/panel.js`, `tests/test_web_static.py`
- [ ] Vizualizare tabel cu coloane configurabile (oră programată, tren, origine/destinație, operator, întârziere, linie, mesaj, ultima modificare), font mono, estetică de afișaj; implicită ≥1024 px, comutator Panou/Carduri; Sosiri/Plecări/Toate; căutare + filtre (nr., localitate, întârziere, linie), sortare, ecran complet, titlu „SOSIRI — GARA DE NORD BUCUREȘTI" cu data/ora, starea sursei/OCR, număr trenuri, buton reîmprospătare.
- [ ] Praguri de culoare din setări (`/api/config` read-only), legendă; gri pentru necunoscut/vechi, niciodată verde „la timp" fără dată de întârziere citită.
- [ ] Verificare Playwright (390×844, 1280×800, ecran complet) fără scroll orizontal/CSP errors.

### Task A4: Minori de calitate amânați din v1
- [ ] Fix-uri grupate: banner offline la `visibilitychange`, skeleton pe eșec, sr-only pentru `*`, `trainKey` cu `service_date` (API trimite `service_date`), `dev_seed` fără `tests.conftest`, `ORDER BY`/claim global la jitter, guard `status='listed'` la low-confidence, `/api/history` cu limită, notifier cu `to_thread` pe apelurile Store, export `OcrError` din `app.ocr`.

## Etapa B — Observații + migrații
- Tabele `observations` (raw text, bbox, scor/câmp, referință imagine, versiune procesare, stare validare) și `trains` (catalog), migrație v3; `captures` cu retenție configurabilă (implicit 7 zile; doar referințe în DB, datele structurate permanente); modul debug „Capturi OCR" (imagine + dreptunghiuri).

## Etapa C — Călătorii și rezultat final
- Reguli de închidere a călătoriei: `final_confirmed` doar când există dovadă (ultima întârziere citită + dispariție după ora estimată, niciodată presupus); `data de serviciu`, asocierea sosire↔plecare doar cu reguli explicite; grafic evoluție întârziere/călătorie.

## Etapa D — Catalog, profil tren, Statistici, Clasamente
- Pagina „Toate trenurile" (N călătorii, % la timp, medie/mediană/max, >30 min, calitatea datelor), profil tren, clasamente cu eșantion minim, punctualitate configurabilă, distribuții; export CSV/JSON.

## Etapa E — Alerte și monitorizare
- Motor de reguli (cooldown, id eveniment, jurnal), Telegram opțional, pagina Stare sistem (durate OCR, erori, vechime date, dimensiune DB/imagini), watchdog.

## Etapa F — Export, backup/restaurare, Setări, administrare
- Backup programat + verificare integritate + restaurare documentată; pagina Setări; autentificare pentru funcții administrative; `.env.example`; retenție imagini.

## Etapa G — Meteo și anotimpuri
- Verificare sursă (Open-Meteo: condiții de utilizare, istoric, limite) → serviciu `weather` separat; observație vs prognoză; UTC; intervale T-0 / T-1..3h / T-6h / zi; pagina „Meteo și trenuri"; analiză descriptivă pe anotimpuri/luni, apoi modele cu avertisment de corelație.

## Etapa H — Predicția liniei
- Frecvențe istorice → model de bază → evaluare temporală → afișare „Linie estimată — neconfirmată" cu N exemple.

---
Fiecare etapă: spec scurt (dacă nu e deja în roadmap) → plan detaliat pe task-uri → implementare pe subagenți cu review → deploy pe server → raport.
