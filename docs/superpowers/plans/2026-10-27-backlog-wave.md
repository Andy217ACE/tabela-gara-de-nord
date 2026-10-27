# Backlog după Beta 1.28 — Plan de implementare

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recomandat) sau superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Închide backlogul rămas după Beta 1.28 (UI hygiene, calitatea OCR, perechi ambigue, Val 4, Val 5, curățenie, teste cross-browser), în versiuni mici, fiecare cu deploy propriu.

**Architecture:** Un plan-umbrelă cu 7 părți independente; fiecare parte produce o versiune `Beta 1.NN` livrabilă singură (cod → teste → PR → deploy cu backup). Părțile 1–3 sunt complet detaliate (cod existent, cauza se măsoară întâi). Părțile 4–5 (Val 4/5) sunt subsisteme noi: fiecare începe cu un spec scurt aprobat de utilizator, apoi taskuri; aici sunt fixate doar interfețele și ordinea.

**Tech Stack:** Python 3.12, FastAPI, SQLite (WAL), OpenCV + Tesseract (`OcrEngine`), JS vanilla + SVG, pytest + Playwright, deploy `deploy/update.sh` (rollback automat).

**Spec:** `docs/superpowers/specs/2026-10-21-roadmap-v2-direction.md` (direcția produsului). Corecția manuală din admin (Beta 1.29, schema v9) este în lucru într-un agent separat (`tg-wt\adm`, `feat/admin-corrections`) și NU face parte din acest plan; punctele 1.30+ se rebazează pe `main` după ce 1.29 e îmbinată.

## Global Constraints

- Date citite ≠ estimate; valoare lipsă ≠ 0; N afișat la statistici; corelație ≠ cauzalitate; nicio dată inventată.
- Footer exact, peste tot: `© 2026 Andy217Ace · Date preluate de la CFR (cfr.ro) — proiect independent, neafiliat CFR` (`tests/test_web_static.py::test_footer_unchanged`).
- Logo `C:\Users\Irina Profir\projects\tg-assets\logo-source.png` rămâne peste tot.
- Fără AI în OCR: Tesseract + OpenCV + template matching; `OcrEngine` (`app/ocr/engine.py`) rămâne înlocuibil.
- La FIECARE deploy: `VERSION` crește (`Beta 1.NN`, următoarea liberă după `git fetch`), secțiune nouă sus în `CHANGELOG.md` (română), backup DB înainte, `deploy/update.sh main` (rollback automat), verificări live după (`/api/health` cu `"version"` nou, `ok:true`).
- Schema DB: `app/store.py::SCHEMA_VERSION` (acum 8; 1.29 ia 9 → orice schemă nouă din acest plan ia 10+). Datele brute nu se modifică; corecțiile sunt reversibile (lot + arhivă).
- Tesseract pe server doar cu `OMP_THREAD_LIMIT=1` (o rulare paralelă a blocat OCR-ul live 16 min).
- Panoul Tabela (Carduri/Panou/Ecran complet) rămâne pixel-identic, în afara părților care îl vizează explicit.
- `Settings`/env: orice variabilă nouă se adaugă în `app/config.py`, cu valoare implicită sigură (funcția oprită = comportament actual).
- Merge și deploy: doar după CI/teste verzi; utilizatorul a dat acord permanent pentru merge/deploy fără confirmări repetate.
- Un singur worker uvicorn (poller în proces) — nimic nou nu cere mai multe procese.

## Review Focus

- Platformă citită greșit ≠ platformă lipsă: o cifră greșită (ex. 8→3) se publică, o valoare `None` e onestă → testele numără `wrong` separat de `unread` (`app/ocr/truth.py`).
- Același număr de tren citit diferit în cadre diferite (1584/1581): rezultatul nu trebuie să comaseze trenuri diferite.
- Pereche ambiguă reală (două trenuri distincte, ex. 5011 și 5014, în aceeași zi): comasarea nu trebuie să le unească.
- Restart al serviciului în mijlocul unui ciclu de alertă: fără alertă dublă, fără alertă pierdută.
- Telegram indisponibil / token greșit: poller-ul și Web Push nu se opresc, eroarea e logată o singură dată pe interval.
- Backup/restore: restaurarea unei copii cu schema mai veche decât codul → migrare, nu eroare; copia coruptă e respinsă înainte de a atinge baza live.
- Cheie admin nouă: sesiunile vechi (cookie semnat cu cheia veche) devin invalide; fără blocarea utilizatorului în afara adminului.

## Ordine și dependențe

| Parte | Versiune | Depinde de |
|---|---|---|
| 1 UI hygiene (CSP, stări goale, ținte tactile) | Beta 1.30 | Beta 1.29 îmbinată |
| 2 OCR: peron tăiat + încrederea numărului Plecări r9/r11 | Beta 1.31 | — |
| 3 Perechi ambigue + golul 1.22 | Beta 1.32 | 1.29 (corecții) |
| 4a Stare sistem + watchdog | Beta 1.33 | — |
| 4b Backup/restore + export | Beta 1.34 | 4a (pagina Sistem) |
| 4c Auth admin cu cheie puternică + setări | Beta 1.35 | 4a |
| 4d Alerte Telegram | Beta 1.36 | 4c (setări) |
| 5a Meteo pe sezoane | Beta 1.37 | ≥ 4 săptămâni de date meteo |
| 5b Predicția liniei la final | Beta 1.38 | 5a, ≥ 30 de zile de date de calitate |
| 6 Curățenie (fără versiune) | — | oricând, după câteva zile |
| 7 Teste cross-browser / push pe telefon real | — | după 1.30 |

Versiunile sunt provizorii: se ia mereu „următoarea liberă” după `git fetch`.

---

## Partea 1 — UI hygiene (Beta 1.30)

### Task 1.1: CSP fără Google Fonts

**Files:**
- Modify: `app/api.py:61-64` (lista `CSP`: `style-src 'self'`, `font-src 'self'`)
- Modify: `tests/test_api.py:254` (inversează aserțiunea)
- Modify: `tests/test_web_static.py:68-72` (lista de gazde permise fără `fonts.googleapis.com`/`fonts.gstatic.com`)
- Test: `tests/test_web_static.py`

**Interfaces:**
- Consumes: `app.api.CSP: str`, fonturile locale `web/fonts/*.woff2` deja încărcate din `web/style.css`.
- Produces: nimic nou.

- [ ] **Step 1: Teste care eșuează.** În `tests/test_api.py` înlocuiește aserțiunea de la linia 254 cu `assert "fonts.googleapis.com" not in csp and "fonts.gstatic.com" not in csp`. În `tests/test_web_static.py` adaugă `test_no_external_font_hosts`: parcurge `web/*.html`, `web/*.css`, `web/*.js` și aserează că niciun fișier nu conține `fonts.googleapis.com` sau `fonts.gstatic.com`; scoate cele două gazde din tuple-ul de la linia 71.
- [ ] **Step 2: Rulează** `pytest tests/test_api.py tests/test_web_static.py -q` — Expected: FAIL (CSP încă le permite).
- [ ] **Step 3: Scoate cele două gazde din `CSP` în `app/api.py`.** Dacă `test_no_external_font_hosts` găsește o referință rămasă, o elimini din fișierul web respectiv.
- [ ] **Step 4: Verificare în browser real** (Playwright, fișier nou `tests/test_csp_browser.py::test_no_csp_violations_on_main_pages`): deschide `#`, `#statistici`, `#trenuri`, `#statii` și aserează zero mesaje de consolă cu „Content Security Policy” și că `document.fonts.check("16px 'Fira Sans'")` este `True`.
- [ ] **Step 5: Rulează** `pytest tests/test_api.py tests/test_web_static.py tests/test_csp_browser.py -q` — Expected: PASS.
- [ ] **Step 6: Commit** `fix(csp): fonturile sunt locale, scoate Google Fonts din CSP`.

### Task 1.2: Stări goale la Trenuri și Stații

**Files:**
- Modify: `web/app.js` (randarea paginilor `#trenuri` și `#statii`; găsești locul cu `grep -n "trenuri\|statii" web/app.js web/stats.js`)
- Modify: `web/stats.css` sau `web/style.css` (clasa `.empty` deja existentă)
- Test: `tests/test_empty_states_browser.py` (nou)

**Interfaces:**
- Consumes: `/api/trains/stats`, `/api/stations` (listă goală posibilă).
- Produces: nimic.

- [ ] **Step 1: Test care eșuează.** `test_empty_trains_and_stations_show_message`: în Playwright, interceptează `/api/trains/stats` și `/api/stations*` cu răspuns gol (`[]` / structura goală reală a endpointului) și aserează că pagina arată textul „Nu există încă date pentru …” (formulare exactă fixată în test) și NU un tabel gol, nici `NaN`/`undefined`. Al doilea test: același lucru cu eroare 500 → mesaj „Nu am putut încărca …” + buton „Reîncearcă”.
- [ ] **Step 2: Rulează** testul — Expected: FAIL.
- [ ] **Step 3: Implementează** starea goală și starea de eroare în randarea celor două pagini, reutilizând clasa `.empty` și textul în română; fără stil inline (CSP).
- [ ] **Step 4: Rulează** `pytest tests/test_empty_states_browser.py -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(ui): stări goale/eroare la Trenuri și Stații`.

### Task 1.3: Stea și clopoțel — ținte tactile ≥ 44 px pe telefon

**Files:**
- Modify: `web/style.css` (butoanele de urmărire; clasa se găsește cu `grep -n "follow" web/style.css web/follows.js`)
- Test: `tests/test_touch_targets_browser.py` (nou)

**Interfaces:** nimic nou.

- [ ] **Step 1: Test care eșuează.** `test_follow_buttons_min_44px_on_phone`: viewport 390×844, aserează că `getBoundingClientRect()` pentru steaua și clopoțelul de pe o carte de tren are lățime și înălțime ≥ 44, și că două ținte vecine nu se suprapun.
- [ ] **Step 2: Rulează** — Expected: FAIL (acum 40 px).
- [ ] **Step 3: Mărește zona de atingere** (min-width/min-height 44 px sau padding), fără a schimba aspectul pe desktop și fără a muta layout-ul cărții (`tests/test_layout_browser.py` rămâne verde).
- [ ] **Step 4: Rulează** `pytest tests/test_touch_targets_browser.py tests/test_layout_browser.py -q` — Expected: PASS.
- [ ] **Step 5: Versiune.** `VERSION` → `Beta 1.30`; secțiune nouă în `CHANGELOG.md`; bump cache `web/sw.js`; `pytest -q` complet verde; commit `chore(release): Beta 1.30`; PR spre `main`.
- [ ] **Step 6: Deploy** cu backup; verificare: `curl https://tabelacfr.ddns.net/api/health` → `"version":"Beta 1.30"`, antet CSP fără `fonts.g*`.

---

## Partea 2 — OCR: peron tăiat și încrederea numărului (Beta 1.31)

Cauza nu e dovedită: ipoteza din cod este perspectiva (cifra peronului stă mai sus decât linia, banda îi taie vârful; `GROW_UP`/`PLATFORM_UP` în `app/ocr/reader.py:154-160`). Planul măsoară întâi.

### Task 2.1: Set de adevăr pentru peron tăiat și Plecări r9/r11

**Files:**
- Modify: `tests/fixtures/ocr_truth/truth.json` (+ imaginile noi în același director)
- Create: `tests/test_ocr_platform_cut.py`

**Interfaces:**
- Consumes: formatul `truth.json` din `app/ocr/truth.py` (docstring: cadre → `arrival`/`departure` → 12 linii cu `no,time,type,delay,platform,station,operator`; `"?"` = nescorat).
- Produces: cadre etichetate manual cu ochiul (nu consens al bazei), minim 15 cu peron tăiat și 10 cu rândurile 9/11 de la Plecări.

- [ ] **Step 1: Selectează cadrele.** Din `/var/lib/tabela/captures` (read-only; copiază local doar cele alese) și din `rejected`: cadre unde peronul e `None`/necitit deși trenul îl are pe tabelă, și cadre unde numărul la Plecări r9/r11 diferă între citiri consecutive. Notează lista în `tests/fixtures/ocr_truth/NOTE-2026-10-27.md`.
- [ ] **Step 2: Etichetează** fiecare rând vizual și adaugă-l în `truth.json` (câmp necitibil → `"?"`).
- [ ] **Step 3: Test de bază.** `tests/test_ocr_platform_cut.py::test_baseline_recorded`: rulează `app.ocr.truth` pe cadrele noi și scrie în `tests/fixtures/ocr_truth/baseline-1.31.json` numărul `ok/unread/wrong` pe `platform` și `no` (Plecări). Rulează cu `OMP_THREAD_LIMIT=1`.
- [ ] **Step 4: Rulează** `python scripts/ocr_eval.py predict out.json && python scripts/ocr_eval.py score out.json` și notează baza în `task-OCR15-report.md`.
- [ ] **Step 5: Commit** `test(ocr): set adevăr peron tăiat + Plecări r9/r11`.

### Task 2.2: Peron tăiat — citire robustă

**Files:**
- Modify: `app/ocr/reader.py` (`grow_up` linia 163, `PLATFORM_UP`/`GROW_UP`, citirea peronului; `parse_platform` din `app/normalize.py`)
- Test: `tests/test_ocr_platform_cut.py`

**Interfaces:**
- Consumes: `grow_up(mask, band, x0, x1, up) -> np.ndarray`, `DigitMatcher.read(cell, allowed) -> tuple[str, float, bool]`.
- Produces: peronul citit pe cadrele din 2.1 cu `wrong == 0` și `unread` strict sub baza din `baseline-1.31.json`.

- [ ] **Step 1: Test care eșuează.** `test_platform_cut_frames`: pentru fiecare cadru din setul nou, aserează `wrong == 0` pe `platform` și `unread <= <valoarea măsurată în 2.1 minus îmbunătățirea țintă>` (valoarea numerică se fixează în test din baza măsurată; nu mai laxă decât baza). `test_platform_blank_stays_none`: celula goală reală rămâne `None`, nu o cifră inventată.
- [ ] **Step 2: Rulează** — Expected: FAIL (peste prag).
- [ ] **Step 3: Diagnostic.** Pentru 3 cadre cu peron tăiat, salvează celula la `PLATFORM_UP` curent și mărit; stabilește dacă cifra e tăiată sus (crește `PLATFORM_UP` sau crește pe verticală adaptiv după înclinarea panoului) sau fragmentată pe orizontală; notează concluzia în raport înainte de cod.
- [ ] **Step 4: Implementează** corecția rezultată din diagnostic în `reader.py`, în limita: o cifră citită doar dacă `glyph_trusted(score, margin)` (`app/ocr/digits.py:256`); altfel `None`.
- [ ] **Step 5: Rulează** `pytest tests/test_ocr_platform_cut.py tests/test_ocr14.py tests/test_ocr13.py tests/test_ocr12.py tests/test_glare.py -q` — Expected: PASS, fără regresii pe `ocr_truth` (scorul pe cadrele vechi nu scade).
- [ ] **Step 6: Commit** `fix(ocr): peron tăiat de bandă`.

### Task 2.3: Încrederea numărului la Plecări, rândurile 9 și 11

**Files:**
- Modify: `app/ocr/reader.py` (citirea numărului: `_numeric` linia 300, `_confirmed` linia 342)
- Modify: `app/poller.py` (vot pe număr între cadre doar dacă diagnosticul o cere)
- Test: `tests/test_ocr_platform_cut.py`

**Interfaces:**
- Consumes: setul din 2.1 (Plecări r9/r11).
- Produces: numărul fie corect, fie `None` (marcat necitit, ca la întârziere); niciodată o cifră în plus/minus stabilă greșită.

- [ ] **Step 1: Test care eșuează.** `test_departure_rows_9_11_number_never_wrong`: pe cadrele r9/r11 etichetate, `wrong == 0` pe `no`; `unread` sub bază.
- [ ] **Step 2: Rulează** — Expected: FAIL.
- [ ] **Step 3: Diagnostic** (ipoteză de verificat, nu certitudine: perspectiva/înclinarea panoului la rândurile de jos). Măsoară dacă `x0/x1` ale celulei „no” se decalează pe aceste rânduri (`_Panel.boxes`); notează în raport.
- [ ] **Step 4: Implementează** corecția din diagnostic. Dacă numărul rămâne nesigur → `None`, nu ghicit.
- [ ] **Step 5: Rulează** suita OCR din Task 2.2 Step 5 + `pytest tests/test_poller.py tests/test_robust_ingest.py -q` — Expected: PASS.
- [ ] **Step 6: Versiune.** `Beta 1.31`, CHANGELOG, `PROCESSING_VERSION` în `app/observations.py:42` → `ocr-tess-grid-5`; `pytest -q` complet; PR; deploy cu backup; verificare live: `/api/health` → `ocr.window` fără rânduri `unread` noi, 30 min de observare.

---

## Partea 3 — Perechi ambigue și golul 1.22 (Beta 1.32)

Perechi cunoscute: 5011/5014, 11081/41081, 8093/93, 5019/19, 10055/55, 503/5031, 5014/5011, 800/8001, 16593/1658, 10101/10261. Corecția manuală (1.29) e instrumentul pentru decizii individuale; aici apar cele sistematice.

### Task 3.1: Raport read-only al perechilor ambigue

**Files:**
- Create: `scripts/ambiguous_pairs.py`
- Test: `tests/test_ambiguous_pairs.py`

**Interfaces:**
- Produces: `find_pairs(conn: sqlite3.Connection, days: int = 30) -> list[Pair]` cu `Pair(no_a:int, no_b:int, station:str|None, same_day_overlap:bool, reads_a:int, reads_b:int, kind:str)`, `kind ∈ {"prefix_dup","one_digit","coexist"}`; `main(argv) -> int` tipărește tabel, fără scriere (`mode=ro`).

- [ ] **Step 1: Teste care eșuează** pe o bază sintetică (în `tmp_path`): (a) 8093 și 93 cu aceeași oră/stație/zi, niciodată simultan pe tabelă → `prefix_dup`; (b) 5011 și 5014 prezente simultan în aceeași citire → `coexist` (trenuri distincte, NU se comasează); (c) 1584 și 1581 cu un singur caracter diferit → `one_digit`.
- [ ] **Step 2: Rulează** — Expected: FAIL (modul inexistent).
- [ ] **Step 3: Implementează** `find_pairs` (SQL read-only peste `services`/`observations`) și `main`.
- [ ] **Step 4: Rulează** `pytest tests/test_ambiguous_pairs.py -q` — Expected: PASS.
- [ ] **Step 5: Rulează raportul pe o copie a bazei live** (copie din `/var/lib/tabela/backups`, nu pe baza live) și salvează ieșirea în `task-PAIRS-report.md`.
- [ ] **Step 6: Commit** `feat(scripts): raport perechi ambigue`.

### Task 3.2: Decizia pe perechi — niciodată auto-comasare pe `coexist`

**Files:**
- Modify: `app/canonical.py` sau `app/quality.py` (locul unde se decide redenumirea prin vot; confirmă cu `grep -n "rename\|minority_dup" app/quality.py app/store.py`)
- Modify: `scripts/merge_number_dups.py` (nu comasează `coexist`)
- Test: `tests/test_merge_number_dups.py`, `tests/test_ambiguous_pairs.py`

**Interfaces:**
- Consumes: `find_pairs` din 3.1.
- Produces: `merge_number_dups.py` exclude perechile `coexist`; cele rămase pentru decizie umană sunt listate (nu comasate) în ieșirea dry-run.

- [ ] **Step 1: Test care eșuează.** `test_coexisting_pair_is_never_merged`: bază sintetică cu 5011 și 5014 coexistente → după `--apply` ambele servicii există neschimbate; `test_prefix_dup_is_merged_and_restorable`: 8093/93 se comasează și `--restore` readuce starea exactă.
- [ ] **Step 2: Rulează** — Expected: FAIL pe primul.
- [ ] **Step 3: Implementează** excluderea. Pentru 1584/1581 și 7911/7914 decizia rămâne la corecția manuală din admin (1.29), nu aici.
- [ ] **Step 4: Rulează** `pytest tests/test_merge_number_dups.py tests/test_ambiguous_pairs.py tests/test_quality.py -q` — Expected: PASS.
- [ ] **Step 5: Aplicare pe live** (după deploy): `systemctl stop tabela` → `python scripts/merge_number_dups.py --db /var/lib/tabela/tabela.db --apply --backup-dir <dir>` doar după ce utilizatorul a văzut dry-run-ul — comasarea modifică date; se păstrează `--restore`. → `python -m app.quality` → `systemctl start tabela`.

### Task 3.3: Golul 1.22 documentat

**Files:**
- Verify: `CHANGELOG.md:76` (rândul „Beta 1.22 nu a fost publicată separat…” există deja)
- Test: `tests/test_version.py`

- [ ] **Step 1: Test.** `test_changelog_explains_gap_1_22`: aserează că `CHANGELOG.md` conține „Beta 1.22 nu a fost publicată separat” și că versiunile publicate nu au alte goluri nedocumentate (ordinea strict descrescătoare).
- [ ] **Step 2: Rulează** — Expected: PASS (documentat deja); dacă pica, adaugă nota.
- [ ] **Step 3: Versiune.** `Beta 1.32`, CHANGELOG, PR, deploy cu backup, verificare live.

---

## Partea 4 — Val 4 (4 sub-planuri; fiecare cu spec propriu înainte de cod)

Regulă comună: pentru fiecare sub-plan, primul task e un spec de 1 pagină în `docs/superpowers/specs/2026-10-NN-<nume>.md` (skill `superpowers:brainstorming`), aprobat de utilizator; taskurile de mai jos sunt scheletul care se detaliază după spec. Fără cod înainte de spec.

### 4a — Stare sistem + watchdog (Beta 1.33)

**Files (nou):** `app/system_status.py`, `web/sistem.js`, `web/sistem.css`; modifică `app/api.py` (rută), `app/admin.py` (secțiune admin), `web/index.html`, `web/sw.js` (precache cu buget, `SW` curent ~650 KB — verifică limita din `tests/test_web_static.py`).

**Interfaces:**
- Produces: `collect_status(store, settings, now: datetime) -> dict` cu cheile `version`, `schema`, `uptime_s`, `poller{last_ok_age_s,last_error}`, `ocr{unread_rate_1h}`, `disk{free_gb}`, `db{size_mb,wal_mb}`; `GET /api/system` (public, doar câmpuri sigure, fără căi/tokenuri) și `GET /api/admin/system` (detaliat, sub `require_admin`).
- Produces: watchdog: `app/watchdog.py::Watchdog(check: Callable[[], Awaitable[bool]], on_fail: Callable[[str], Awaitable[None]], interval_s: float)`; `deploy/tabela-watchdog.timer` + `.service` (verifică `/api/health`, repornește serviciul după 3 eșecuri consecutive).

- [ ] **Task 4a.1:** Spec + aprobare.
- [ ] **Task 4a.2:** Test + implementare `collect_status` (test: câmpurile din `/api/system` nu conțin `/var/lib`, `token`, `AZPW`).
- [ ] **Task 4a.3:** Test + implementare watchdog (test cu ceas fals: 3 eșecuri → `on_fail` o singură dată; revenire → resetare; fără buclă de restart mai des de 1/10 min).
- [ ] **Task 4a.4:** UI `#sistem` + test Playwright; unit systemd + test în `tests/test_update_sh.py`-stil pentru instalare.
- [ ] **Task 4a.5:** Versiune `Beta 1.33`, CHANGELOG, PR, deploy.

### 4b — Backup/restore + export (Beta 1.34)

**Files (nou):** `app/backup_api.py`, `app/export_api.py`, `scripts/restore_db.py`; reutilizează `app/dbbackup.py` (din 1.29, backup online SQLite cu verificare de integritate).

**Interfaces:**
- Produces: `make_backup(store_path: str, dest_dir: str, keep: int = 5) -> Path`; `verify_backup(path: Path) -> bool` (`PRAGMA integrity_check` + `user_version ≤ SCHEMA_VERSION`); `restore(path: Path, db_path: str) -> None` (doar cu serviciul oprit, copie de siguranță a bazei curente înainte); `GET /api/export/history.csv?from=&to=&train=` (CSV cu antet, cu limită de rânduri și rate-limit zona `tabela_stats`).

- [ ] **Task 4b.1:** Spec + aprobare (ce se exportă, ce se restaurează, cine are voie).
- [ ] **Task 4b.2:** Teste: copie coruptă respinsă (`verify_backup` → False); schemă mai veche → migrare la restaurare; CSV nu conține câmpuri private (`+corr`, note de admin).
- [ ] **Task 4b.3:** Implementare + buton în admin cu confirmare dublă la restaurare; restaurarea nu se face din UI web (doar script, serviciul oprit).
- [ ] **Task 4b.4:** Test de restaurare pe copie locală; versiune `Beta 1.34`, deploy.

### 4c — Auth admin cu cheie puternică + setări (Beta 1.35)

**Files:** modifică `app/admin.py` (`admin_token()` linia 54, `make_session`/`check_session` liniile 103-117, `login` linia 181), `app/config.py`, `deploy/update.sh` (nu înlocuiește secretul), `tests/test_admin.py`.

**Interfaces:**
- Produces: `admin_token()` cere ≥ 24 caractere dacă `ADMIN_TOKEN_STRICT=1` (implicit 0 la început → apoi 1 după ce utilizatorul schimbă cheia); schimbarea cheii în `/etc/tabela.env` invalidează sesiunile (cookie semnat cu cheia veche); `GET/POST /api/admin/settings` pentru retenția capturilor (acum 7 zile) și praguri, cu validare de interval și jurnal de audit (tabelul de audit din 1.29).

- [ ] **Task 4c.1:** Spec + aprobare (inclusiv ce se mută din env în setări).
- [ ] **Task 4c.2:** Teste: cheie scurtă respinsă la pornire sub `STRICT`; sesiune veche invalidă după rotație; setări în afara intervalului → 422; fără ocolirea CSRF.
- [ ] **Task 4c.3:** Implementare + rotație documentată (`docs/` pas cu pas: generezi cheia, o pui în `/etc/tabela.env`, `systemctl restart tabela`). Cheia nu apare în repo, log sau CHANGELOG.
- [ ] **Task 4c.4:** Versiune `Beta 1.35`, deploy; utilizatorul alege cheia nouă (nu o generez eu în conversație).

### 4d — Alerte Telegram (Beta 1.36)

**Files (nou):** `app/telegram.py`, `tests/test_telegram.py`; modifică `app/notifier.py` (punct de extensie), `app/config.py` (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, opționale, implicit oprit), `app/endpoints.py`/`app/api.py` (rute de abonare).

**Interfaces:**
- Consumes: `Notifier.__init__(store, send, ...)` (`app/notifier.py:91`) — canalul Telegram are aceeași semnătură `send(sub, data) -> Awaitable[None]`; `message(ev: Event) -> str|None` (linia 73) pentru text.
- Produces: `make_telegram_sender(settings) -> Callable[[Subscription, dict], Awaitable[None]]`; erorile de rețea sunt prinse și logate cel mult o dată pe 10 minute; dedup și debounce-ul din `Notifier` rămân neschimbate (alertă confirmată în ≥ `confirm` citiri).

- [ ] **Task 4d.1:** Spec + aprobare (cine se abonează, cum se leagă un chat, ce alerte).
- [ ] **Task 4d.2:** Teste cu `send` fals: token lipsă → canal dezactivat fără excepție; 429/timeout de la Telegram nu blochează `handle()`; același eveniment nu iese de două ori pe același canal.
- [ ] **Task 4d.3:** Implementare; testul de livrare reală se face doar la cererea utilizatorului (token propriu, niciodată în repo).
- [ ] **Task 4d.4:** Versiune `Beta 1.36`, deploy.

---

## Partea 5 — Val 5 (după acumulare de date; spec obligatoriu)

### 5a — Meteo pe sezoane (Beta 1.37)

**Files:** `app/stats_overview.py` (blocul meteo existent „după 7 zile”), `app/weather.py`, `web/statistici.js`/`charts3.js`.

**Interfaces:**
- Produces: `weather_by_season(conn, now) -> dict` cu `n` pe fiecare sezon și `enough: bool`; când `n < 30` zile pe sezon, UI arată „date insuficiente (N=…)”, nu un grafic; afișaj „corelație ≠ cauzalitate”.

- [ ] **Task 5a.1:** Spec: ce înseamnă sezon (calendaristic?), ce metrici (întârziere medie vs temperatură/precipitații), prag minim de N.
- [ ] **Task 5a.2:** Teste: sezon cu N sub prag → `enough=False`; zile fără meteo = lipsă, nu 0; intervale `ro` UTC/local consecvente (formatele UTC diferite meteo/observații — risc cunoscut).
- [ ] **Task 5a.3:** Implementare + grafic + `Cum se citește` + export CSV ca la celelalte grafice; versiune, deploy.

### 5b — Predicția liniei la final (Beta 1.38)

**Files (nou):** `app/predict.py`, `tests/test_predict.py`; endpoint `GET /api/trains/{no}/prediction`.

**Interfaces:**
- Produces: `predict_final(history: list[JourneyPoint], now) -> Prediction | None` unde `Prediction(delay_min:int, low:int, high:int, n:int, basis:str)`; întoarce `None` dacă `n < 10` călătorii comparabile. Se etichetează explicit „estimare”, separat de datele citite (regula date citite ≠ estimate), cu interval, nu valoare punctuală.

- [ ] **Task 5b.1:** Spec: metoda (mediană pe ore/zi a săptămânii, nu model opac), validare pe istoric (backtest cu eroare măsurată publică).
- [ ] **Task 5b.2:** Teste: sub 10 călătorii → `None`; estimarea nu intră niciodată în statistici/istoric; backtest pe `tests/fixtures/live_v2.db` cu eroare raportată.
- [ ] **Task 5b.3:** UI cu eticheta „estimare” și N; versiune, deploy.

---

## Partea 6 — Curățenie (operațională, fără versiune)

Fiecare acțiune: inspectează ținta, apoi șterge. Nimic din `/var/lib/tabela/tabela.db` sau `backups/`.

- [ ] **6.1** `/var/lib/tabela/captures.old` — după ≥ 3 zile de la montarea discului nou și cu `captures/` verificat ca funcțional (`ls`, `df`); `sudo rm -rf` doar pe acest director, după `du -sh` afișat utilizatorului.
- [ ] **6.2** Worktree-uri locale: `git worktree list`; pentru `ocr15`, `ui2`, `ui3`, `wx` verifică `git branch --merged main` și `git status` curat, apoi `git worktree remove <cale>` și `git branch -d <branch>`; `adm` doar după merge-ul 1.29.
- [ ] **6.3** Fișierele goale `C:\Windows\System32\git` și `\python` — decide utilizatorul (nu sunt în repo).
- [ ] **6.4** `git fetch --prune`; confirmă că nu mai există branch-uri remote în afară de `main`.

---

## Partea 7 — Teste cross-browser și push pe telefon real

**Files:** `tests/conftest.py` (fixture Playwright parametrizat), teste existente `*_browser.py`.

- [ ] **Task 7.1:** Parametrizează fixture-ul de browser pe `chromium`, `firefox`, `webkit` (Playwright suportă toate trei; `playwright install firefox webkit`). Test: `tests/test_cross_browser_smoke.py::test_main_pages_render_all_engines` — fiecare pagină principală se încarcă, zero erori de consolă, `document.fonts.check` pozitiv, tabela are 12 rânduri/panou pe fixture.
- [ ] **Task 7.2:** Rulează `pytest tests/test_cross_browser_smoke.py -q` — Expected: PASS pe cele trei motoare; defectele găsite devin taskuri separate, nu sunt ascunse în test.
- [ ] **Task 7.3:** Push pe telefon real (nu se poate automatiza): listă de verificare în `docs/test-push-telefon.md` — instalare PWA, abonare la un tren, primire a alertei de test, comportament după repornirea serviciului; utilizatorul confirmă rezultatul, nu îl presupun eu.
- [ ] **Task 7.4:** Notează în CHANGELOG-ul versiunii următoare ce motoare au fost verificate; fără afirmații despre motoare neverificate.

---

## Auto-revizuire

- **Acoperire:** punctele 1–7 din backlog au o parte fiecare; punctul 1 (numere stabil greșite) e livrat de Beta 1.29 și doar referit; golul 1.22 e deja documentat (Task 3.3 doar îl fixează cu un test).
- **Neclarități declarate:** cauza „peron tăiat” și a numerelor r9/r11 nu e dovedită → taskuri de măsurare înaintea codului; Val 4/5 cer spec aprobat (nu am inventat detalii de produs).
- **Consistență tipuri:** `find_pairs`/`Pair` (3.1) sunt folosite în 3.2; `make_backup`/`verify_backup`/`restore` (4b) se bazează pe `app/dbbackup.py` din 1.29; `Notifier.send` din 4d are semnătura din `app/notifier.py:91`.
- **Riscuri de coliziune:** versiunile `Beta 1.NN` sunt provizorii (agenți paraleli au mai consumat numere); `SCHEMA_VERSION` următoare liberă după 1.29 (v9).
