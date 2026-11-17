# Program de livrare Tabela CFR — 17.11.2026

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** livrarea în ordine a Statistici v3 (sp1–sp4), Val 4, Val 5 și a alternativei OCR, fiecare ca release Beta cu deploy verificat pe tabelacfr.ddns.net, fără ca două fluxuri să atingă același fișier.

**Architecture:** un controller (sesiunea principală) deține fișierele partajate și toate release-urile (VERSION, CHANGELOG.md, web/sw.js, CHARTS_V în web/ui2.js, app/api.py, app/config.py, app/store.py, deploy/*) și face deploy-urile serial. Fiecare flux de lucru are worktree și branch propriu, pornit de la `origin/main`, și lucrează doar în fișierele din coloana lui.

**Tech Stack:** Python (Flask-style API, SQLite), JS vanilla, Tesseract/OpenCV, nginx, systemd, bash (deploy/update.sh).

**Spec:** `docs/superpowers/specs/2026-11-15-statistici-v3-design.md`, `docs/superpowers/specs/2026-10-31-val4-*.md`, `docs/superpowers/specs/2026-10-31-val5-*.md`, `docs/superpowers/specs/2026-11-05-val5-peron-design.md`, `docs/superpowers/specs/2026-11-14-english-version-design.md`.

## Global Constraints

- Versiune: `Beta 1.NN` în `VERSION`; doar controllerul o crește, la release.
- Nicio librărie JS nouă; CSP fără inline script și fără `innerHTML` cu text din date.
- Textele noi trec prin dicționarul `ro.json` și `en.json`, cu chei identice.
- Layout verificat la 360 px fără derulare orizontală (`scrollWidth <= 360`).
- Precache: fișierele noi JS se încarcă la runtime, nu în precache (ca în Beta 1.55); bugetul din `tests/test_brand_theme.py` nu crește fără decizie.
- Nicio schimbare de schemă DB în fluxuri paralele. Schema v9 e curentă; orice schemă nouă se face serial de controller, cu backup.
- Atribuire commit: ultima linie `Co-Authored-By: Claude Haiku 5.5 <noreply@anthropic.com>`.
- Serverul de producție: fluxurile NU modifică nimic pe server și nu rulează Tesseract acolo.

## Review Focus

1. Pagina de statistici pe o bază nouă, cu mai puțin de 7 zile de date: comparația și heatmap-ul afișează „date insuficiente”, nu zero. (Sp3, teste de endpoint.)
2. Filtru salvat în `localStorage` care referă un operator dispărut: presetarea trece peste câmpul lipsă și nu aruncă eroare. (Sp1, test browser.)
3. Export CSV cu caractere românești și cu nume de stații care conțin virgulă: fișierul rămâne valid în Excel (BOM, ghilimele). (Sp4.)
4. Click pe bar cu peste 200 de trenuri: lista se trunchiază cu mesaj, nu se încarcă tot. (Sp2.)
5. Restart de serviciu în timpul unui shadow-train sau al unui deploy: aplicația pornește și nu pierde date. (Val 4 watchdog, deploy.)

## Structura fluxurilor și a fișierelor

| Flux | Worktree / branch | Fișiere pe care le poate modifica | Depinde de |
|---|---|---|---|
| R (release 1.57) | `feat/stats-v3` (repo principal) | toate fișierele sp1 deja comise | — |
| S4 (export, încărcare progresivă) | `tg-wt\s4` / `feat/stats-v3-sp4` | `web/stat_export.js` (nou), `web/statistici.js` (doar încărcarea progresivă), `web/statistici.css` (doar export), `web/ro.json`/`en.json` (chei noi) | sp1 îmbinat |
| V4 (Val 4: alerte, watchdog, backup/restore, setări/export/auth) | `tg-wt\v4` / `feat/val4` | `app/alerts.py`, `app/watchdog.py`, `app/backup_restore.py`, `app/settings.py` (noi), teste noi, `deploy/` DOAR pentru unit-uri noi | — |
| O (alternativă OCR, DOAR spec) | `tg-wt\ocr-alt` / `feat/ocr-alt-spec` | `docs/superpowers/specs/2026-11-17-ocr-alternativa.md` | — |

**Interzise tuturor fluxurilor** (le atinge doar controllerul, serial, la release): `VERSION`, `CHANGELOG.md`, `web/sw.js`, `web/ui2.js`, `app/api.py`, `app/config.py`, `app/store.py`, `deploy/update.sh`, `tests/test_brand_theme.py`, `tests/test_version.py`.

Dacă o sarcină cere un fișier din altă coloană sau unul interzis, agentul se oprește cu status `NEEDS_CONTEXT` și scrie de ce, nu îl modifică.

## Ordinea de livrare

1. **R — release 1.57** (Statistici v3 sp1). Suita completă sub lacăt, PR, repetiție pe server, backup, `update.sh`, verificare live, curățenie git.
2. **În paralel cu R:** S4 (pe branch-ul de la sp1, după ce R e îmbinat, se rebazează pe `main`), V4 (pe `main`), O (doar document).
3. **După R:** sp2 (Claritate vizuală) — folosește scala de culori și dicționarul din sp1. Release 1.58.
4. **După S4 îmbinat:** sp3 (Conținut nou), ultimul, cere endpoint-uri noi. Release 1.59 sau 1.60.
5. **După V4 îmbinat:** Val 5 (sezoane/meteo și predicție linie din specificațiile `2026-10-31-val5-*` și `2026-11-05-val5-peron-design.md`). Atinge `api.py` și `store.py` → serial, controller.

## Tasks

### Task 1: Release 1.57 (controller)

**Files:**
- Modify (controller): `VERSION`, `CHANGELOG.md`, `web/sw.js`, `web/ui2.js` (CHARTS_V, dacă lista precache se schimbă)

**Interfaces:**
- Consumes: branch `feat/stats-v3` cu commit-urile sp1 (`36844ec` … `e9e1a02`).
- Produces: PR spre `main`, tag `beta-1.57`, release GitHub, serviciu live pe 1.57.

- [ ] **Step 1: Suita focalizată sp1**
  Run: `OMP_THREAD_LIMIT=1 .venv\Scripts\python.exe -m pytest tests/test_stat_presets* tests/test_ui3_browser.py -k "stats or stat" -q`
  Expected: 0 eșecuri (sau eșecuri notate explicit, cu motiv).

- [ ] **Step 2: Suita completă sub lacăt**
  Ia lacătul `.superpowers\suite.lock` (mkdir atomic), rulează `pytest -q`, eliberează lacătul (rmdir).
  Expected: toate testele trec; testul pixel instabil `test_ui3_browser.py::…[360-780-light-carduri]` se rulează izolat de 3 ori dacă pică.

- [ ] **Step 3: Bump versiune și changelog**
  `VERSION` → `Beta 1.57` (deja setat); verifică `CHANGELOG.md` (secțiunea 1.57 e deja sus); `web/sw.js` la v43 (deja); `CHARTS_V` neschimbat dacă nu s-au schimbat grafice.
  Run: `pytest tests/test_version.py -q`. Expected: PASS.

- [ ] **Step 4: PR și îmbinare**
  `git push -u origin feat/stats-v3`; `gh pr create --base main --title "Beta 1.57: Statistici v3 sp1" --body ...` (cu footer-ul de atribuire); `gh pr merge --squash` după ce `main` e rebazat fără conflicte. Repo fără CI: verificarea e suita de la pasul 2.

- [ ] **Step 5: Repetiție pe server ca user `tabela`**
  Rulează `scratchpad\rehearse\run_rehearsal.py feat/stats-v3`. Expected: PASS (pornire, /api/health, schema neschimbată).

- [ ] **Step 6: Backup și deploy**
  Pe server, ca root: backup `.backup` + `PRAGMA integrity_check`; `git show origin/main:deploy/update.sh > /root/update-157.sh`; `bash -n`; `umask 022 && bash /root/update-157.sh main`. Expected: serviciu activ, NRestarts 0.

- [ ] **Step 7: Verificare live și curățenie**
  `curl https://tabelacfr.ddns.net/api/health` → `"version":"Beta 1.57"`; `/#statistici` se încarcă; sumarul afișează 4 carduri; șterge scriptul de pe server; tag `beta-1.57` și release GitHub.

### Task 2: Statistici v3 sp4 (export, încărcare progresivă, indicator)

**Files:**
- Create: `web/stat_export.js`, `tests/test_stat_export_browser.py`
- Modify: `web/statistici.js` (încărcare progresivă), `web/statistici.css` (export), `web/ro.json`, `web/en.json`

**Interfaces:**
- Consumes: `/api/stats/overview` (sumar și Probleme la deschidere; restul la prima vizită).
- Produces: `exportCsv(table: TableModel) -> Blob` (UTF-8 cu BOM, separator virgulă, ghilimele pentru câmpurile cu virgulă); `exportPng(svgEl) -> Promise<Blob>` (canvas, fără librării).

- [ ] **Step 1:** test browser — descărcarea CSV are BOM `﻿` și câmpurile cu virgulă sunt între ghilimele.
- [ ] **Step 2:** test browser — secțiunile întârziate nu cer endpoint-ul înainte de prima vizită.
- [ ] **Step 3:** implementează `exportCsv`, butoanele CSV/PNG pe fiecare grafic și tabel; PNG eșuat → mesaj cu oferta CSV.
- [ ] **Step 4:** `IntersectionObserver` pentru secțiuni; indicator „Date actualizate acum X minute” reîmprospătat la 60 s.
- [ ] **Step 5:** `pytest tests/test_stat_export_browser.py -q` — PASS; test static: nicio librărie nouă.
- [ ] **Step 6:** commit pe `feat/stats-v3-sp4`; NU modifică VERSION/CHANGELOG/sw.js/CHARTS_V.

### Task 3: Val 4 (alerte, watchdog, backup/restore, setări/export/auth)

**Files:**
- Create: `app/alerts.py`, `app/watchdog.py`, `app/backup_restore.py`, `app/settings.py`, teste corespunzătoare în `tests/`
- Modify (doar pentru unit-uri noi): `deploy/tabela-watchdog.service` (nou), `deploy/tabela-watchdog.timer` (nou)

**Interfaces:** conform specificațiilor `2026-10-31-val4-*.md`; orice punct de integrare în `api.py` / `config.py` / `store.py` se predă controllerului ca listă de modificări, nu se aplică direct.

- [ ] **Step 1:** citește cele patru specificații; scrie un plan de sarcini în `docs/superpowers/plans/2026-11-17-val4.md` (sub-sarcinile pe fiecare componentă).
- [ ] **Step 2:** implementează componentă cu componentă, TDD, fiecare în propriul commit.
- [ ] **Step 3:** la final, lista de integrare pentru controller în `docs/superpowers/plans/2026-11-17-val4-integrare.md`.

### Task 4: Alternativa OCR (doar specificație)

**Files:**
- Create: `docs/superpowers/specs/2026-11-17-ocr-alternativa.md`

- [ ] **Step 1:** specificație: modelul antrenat în umbră devine alternativă, folosită doar când cititorul actual eșuează pe un cadru (fără rânduri sau rânduri necitite). Include: criterii de declanșare, cum se marchează în observații (`+ocr:alt`), ce date de evaluare se folosesc, criterii de promovare, ce NU se face (nu înlocuiește cititorul).
- [ ] **Step 2:** nu se implementează în acest program până la aprobarea specificației de utilizator — dar utilizatorul a cerut fără confirmări, deci după scriere se trece la implementare într-un branch separat, într-un plan nou.

## Riscuri și reguli de coordonare

- **Conflicte de merge:** fluxurile S4 și R ating `statistici.js` și `statistici.css`. S4 se rebazează pe `main` după ce R e îmbinat; nu înainte.
- **Dicționare:** `ro.json`/`en.json` au chei comune; fiecare flux își adaugă cheile în blocuri separate și rebază cu atenție.
- **Schemă DB:** V4 poate cere tabele noi (alerte, setări). Schema v10 se face serial de controller, cu backup și migrare testată pe copie.
- **Server:** niciun agent nu se conectează la server; repetițiile și deploy-urile le face controllerul.
