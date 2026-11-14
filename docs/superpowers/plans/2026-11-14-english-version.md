# Versiunea în engleză — plan de implementare

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Interfața Tabelei și documentația de pe GitHub există în română și în engleză, cu comutator RO/EN; română rămâne implicită.

**Architecture:** Dicționare JSON (`web/i18n/ro.json`, `web/i18n/en.json`) cu chei stabile, încărcate de un modul `web/i18n/i18n.js` care expune `window.I18N`. Textele din HTML au `data-i18n`, iar cele din JS trec prin `I18N.t(cheie, parametri)`. Documentația e tradusă în `docs/en/` și `README.md`; română rămâne în `README.ro.md` și `docs/`.

**Tech Stack:** JavaScript vanilla (fără framework), Python 3 + pytest (teste de paritate și de existență), Playwright (teste de browser, ca `tests/test_nav_browser.py`), `Intl` pentru date și numere.

**Spec:** `docs/superpowers/specs/2026-11-14-english-version-design.md`

**Abatere față de spec:** dicționarele sunt JSON, nu module `.js` cu export. Motivul: testul de paritate (`tests/test_i18n_parity.py`) citește direct JSON-ul din Python, fără să parseze JavaScript. Limba se încarcă cu `fetch`, iar dicționarele intră în precache-ul service worker-ului.

## Global Constraints

- Limbi: doar `ro` (implicită) și `en`; orice alt cod de limbă cade pe `ro`.
- Parametrul de adresă: `?lang=en` sau `?lang=ro`; cheia de stocare: `tabela-lang`.
- Ordinea de alegere: adresă → `localStorage` → `ro`.
- Niciun text literal românesc rămas în `web/*.js` sau `web/*.html` după migrare, în afară de listele din `tests/i18n_allowlist.txt`.
- Nume de stații, trenuri și operatori rămân în română (vin din CFR).
- Termeni tehnici rămân în engleză în ambele limbi (OCR, precache, shadow); glosarul e în `docs/en/glosar.md`.
- Test-urile existente rămân verzi; `tests/test_version.py` trebuie să găsească în continuare exact o intrare nouă sus, cu cel puțin 5 puncte.
- Bugetul de precache (~650 KB) nu se depășește.
- Lățimea minimă de verificare: 360 px, fără derulare orizontală.

## Review Focus

1. **Cheie lipsă în engleză** — în locul textului apare cheia brută (`board.arrivals`). Se așteaptă: text românesc, nu cheia.
2. **`?lang=` cu valoare necunoscută** (ex. `?lang=fr`, `?lang=`, `?lang=<script>`) — se așteaptă: română, fără eroare JS, fără text injectat.
3. **`localStorage` indisponibil** (mod privat, blocat) — comutatorul trebuie să funcționeze pentru sesiunea curentă, fără excepție nerezolvată.
4. **Plural și numere în engleză** — „1 minute” vs „2 minutes”, „1 train”, separatorul zecimal din `Intl`.
5. **Offline cu dicționarele din cache** — pagina și `offline.html` trebuie să afișeze engleza când limba salvată e `en`, fără rețea.

## File Structure

- Create: `web/i18n/i18n.js` — modul de limbă (`t`, `setLang`, `applyDom`, alegerea limbii).
- Create: `web/i18n/ro.json`, `web/i18n/en.json` — dicționare cu aceleași chei.
- Create: `tests/test_i18n_parity.py` — chei identice, parametri identici, valori nevide.
- Create: `tests/test_i18n_allowlist_scan.py` — caută șiruri românești literale în `web/`.
- Create: `tests/i18n_allowlist.txt` — excepții explicite (fișier:linie:motiv).
- Create: `tests/test_i18n_browser.py` — comutator, adresă, `lang`, persistare, fallback.
- Modify: `web/index.html`, `web/app.js`, `web/theme-init.js`, `web/ui2.js`, `web/panel.js`, `web/weather.js`, `web/history.js`, `web/follows.js`, `web/peron_est.js`, `web/statistici.js`, `web/stats.js`, `web/stat_*.js`, `web/charts3.js`, `web/admin.js`, `web/ocr.js`, `web/sistem.js`, `web/setari.js`, `web/sezoane.js`, `web/versions.js`, `web/offline.html` — migrare text.
- Modify: `web/sw.js` — precache pentru `web/i18n/*`, versiune nouă, `CHARTS_V`.
- Modify: `README.md` (devine engleză), create `README.ro.md` (copia românească).
- Create: `docs/en/*.md` — traducerea fiecărui fișier din `docs/*.md`; `docs/en/glosar.md`.
- Modify: `CHANGELOG.md`, `VERSION` (Beta 1.54).

## Interfaces (contract comun)

- `window.I18N.t(key: string, params?: object) -> string` — întoarce textul din limba activă; dacă lipsește, din română; dacă lipsește și acolo, cheia.
- `window.I18N.lang() -> "ro" | "en"`.
- `window.I18N.setLang(code: string) -> void` — validează, salvează în `localStorage`, reaplică DOM-ul, emite eventul `i18n:change` pe `document`.
- `window.I18N.applyDom(root?: Element) -> void` — completează `data-i18n` și `data-i18n-attr="attr:cheie"`.
- `window.I18N.ready: Promise<void>` — rezolvată după încărcarea dicționarelor; codul care randează trebuie să aștepte.
- Eveniment `i18n:change` pe `document`, cu `detail.lang`. Panourile care randează dinamic se re-randează la acest eveniment.

---

### Task 1: Modul de limbă și încărcare dicționare

**Files:**
- Create: `web/i18n/i18n.js`
- Create: `web/i18n/ro.json`, `web/i18n/en.json` (conțin doar `{}` plus cheile de test `"test.hello": "Bună"` / `"test.hello": "Hello"`)
- Test: `tests/test_i18n_browser.py` (primul test)

**Interfaces:**
- Produces: contractul de mai sus, în întregime.

- [ ] **Step 1: Test eșuat** — `test_default_is_romanian_and_t_falls_back`: deschide pagina de test, verifică `I18N.lang() == "ro"` și `I18N.t("cheie.inexistenta") == "cheie.inexistenta"` pentru cheia care nu există în niciun dicționar.
- [ ] **Step 2: Rulează** `pytest tests/test_i18n_browser.py -v` → FAIL (`I18N` nedefinit).
- [ ] **Step 3: Implementare** `web/i18n/i18n.js`: încarcă `ro.json` întotdeauna, `en.json` doar dacă limba e `en`; `t` caută în limba activă, apoi în `ro`, apoi întoarce cheia.
- [ ] **Step 4: Rulează** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "i18n: modul de limbă și încărcare dicționare"`.

**Model:** Sonnet (cod nou cu contract clar, un singur fișier).

---

### Task 2: Alegerea limbii (adresă, stocare, fallback)

**Files:**
- Modify: `web/i18n/i18n.js`
- Test: `tests/test_i18n_browser.py`

**Interfaces:**
- Consumes: contractul din Task 1.
- Produces: `setLang`, persistare sub cheia `tabela-lang`, citirea parametrului `lang`.

- [ ] **Step 1: Teste eșuate** (în `tests/test_i18n_browser.py`):
  - `?lang=en` → `I18N.lang() == "en"`.
  - `?lang=fr` → `"ro"`; `?lang=` → `"ro"`; `?lang=<script>alert(1)</script>` → `"ro"`, fără dialog JS.
  - `setLang("en")` salvează `localStorage["tabela-lang"] == "en"`; reîncărcarea păstrează `en`.
  - Cu `localStorage` înlocuit cu o funcție care aruncă: `setLang("en")` nu aruncă și schimbă limba pentru sesiune.
- [ ] **Step 2: Rulează** → FAIL.
- [ ] **Step 3: Implementare** în `i18n.js`: lista valorilor acceptate `["ro","en"]`; toate accesele la `localStorage` în `try/catch`.
- [ ] **Step 4: Rulează** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "i18n: alegerea limbii din adresă și stocare, cu fallback"`.

**Model:** Sonnet.

---

### Task 3: Teste de paritate și scanare de text literal

**Files:**
- Create: `tests/test_i18n_parity.py`, `tests/test_i18n_allowlist_scan.py`, `tests/i18n_allowlist.txt`

**Interfaces:**
- Consumes: `web/i18n/ro.json`, `web/i18n/en.json`.

- [ ] **Step 1: Test de paritate** — `test_same_keys_and_params`: aceleași chei în ambele fișiere; pentru fiecare cheie, același set de `{parametri}`; valori nevide.
- [ ] **Step 2: Test de scanare** — `test_no_romanian_literals_outside_allowlist`: caută în `web/**/*.js` și `web/**/*.html` șiruri cu diacritice românești (`ăîâșț` și variantele mari) sau cuvinte-cheie (`Încarc`, `Nu `, `Trenuri`, `Plecări`, `Sosiri`) care nu sunt în `tests/i18n_allowlist.txt`. Format allowlist: `fișier:linie:motiv`.
- [ ] **Step 3: Rulează** → paritatea trece (dicționare de test), scanarea FAIL cu lista de fișiere existente (asta e intenția: se goleşte pe măsură ce se migrează).
- [ ] **Step 4: Adaugă** în allowlist numai liniile care sunt date CFR (nume de stații, trenuri), cu motivul.
- [ ] **Step 5: Commit** — `git commit -m "i18n: teste de paritate și de text literal"`.

**Model:** Sonnet (regex și format, cu revizie atentă a allowlist-ului).

---

### Task 4: Comutatorul RO/EN în bara de navigare

**Files:**
- Modify: `web/index.html`, `web/app.js`, `web/theme-init.js`
- Test: `tests/test_i18n_browser.py`

**Interfaces:**
- Consumes: `I18N.setLang`, `I18N.ready`, `I18N.applyDom`.

- [ ] **Step 1: Test eșuat** — `test_toggle_switches_language_and_url`: butonul `data-lang-toggle` există în `.navbar` la 360 px; click → `I18N.lang() == "en"`, `?lang=en` în adresă, `document.documentElement.lang == "en"`.
- [ ] **Step 2: Rulează** → FAIL.
- [ ] **Step 3: Implementare**: buton în navbar, `applyDom()` pe `document` după `ready`. `theme-init.js` setează `lang` înainte de randare (fără clipire).
- [ ] **Step 4: Rulează** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "i18n: comutator RO/EN în navbar"`.

**Model:** Sonnet.

---

### Task 5: Migrare panou principal (index, app, ui2, panel, weather)

**Files:**
- Modify: `web/index.html`, `web/app.js`, `web/ui2.js`, `web/panel.js`, `web/weather.js`
- Modify: `web/i18n/ro.json`, `web/i18n/en.json`
- Test: `tests/test_i18n_browser.py`

**Interfaces:**
- Consumes: `I18N.t`, eventul `i18n:change`.

- [ ] **Step 1: Test eșuat** — `test_board_in_english`: în `en`, titlul panoului „Arrivals” / „Departures”, starea „delayed” și textul pentru întârziere în minute apar în engleză; cu `?lang=ro` apar în română.
- [ ] **Step 2: Rulează** → FAIL.
- [ ] **Step 3: Implementare**: extrage cheile (`board.*`, `weather.*`, `app.*`) în ambele dicționare; panoul se re-randează la `i18n:change`.
- [ ] **Step 4: Rulează** → PASS; scanarea (Task 3) scade pentru aceste fișiere.
- [ ] **Step 5: Verifică la 360 px** — screenshot cu Playwright în `en`, fără derulare orizontală (`document.documentElement.scrollWidth <= 360`).
- [ ] **Step 6: Commit** — `git commit -m "i18n: panou principal, meteo și aplicația"`.

**Model:** Sonnet. Revizie pentru plural (Review Focus 4) de Fable 5.2 doar dacă Sonnet raportează o ambiguitate.

---

### Task 6: Migrare istoric, urmărite, peron

**Files:**
- Modify: `web/history.js`, `web/follows.js`, `web/peron_est.js`
- Modify: `web/i18n/ro.json`, `web/i18n/en.json`
- Test: `tests/test_i18n_browser.py`

**Interfaces:**
- Consumes: `I18N.t`, eventul `i18n:change`.

- [ ] **Step 1: Test eșuat** — `test_history_and_follows_in_english`: în `en`, titlul „History” și butonul „Load more” apar; pentru „1 train” și „2 trains” pluralul e corect (Review Focus 4).
- [ ] **Step 2: Rulează** → FAIL.
- [ ] **Step 3: Implementare**: pluralul prin cheile `*.one` / `*.other` alese cu `Intl.PluralRules(lang)`.
- [ ] **Step 4: Rulează** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "i18n: istoric, urmărite și peron"`.

**Model:** Sonnet.

---

### Task 7: Migrare statistici și grafice

**Files:**
- Modify: `web/statistici.js`, `web/stats.js`, `web/stat_quality_daily.js`, `web/stat_steps.js`, `web/stat_platform.js`, `web/stat_dwell.js`, `web/stat_weekdays.js`, `web/charts3.js`, `web/statistici.css` (doar dacă un text iese din spațiu)
- Modify: dicționare
- Test: `tests/test_i18n_browser.py`

**Interfaces:**
- Consumes: `I18N.t`, `Intl.NumberFormat(lang)` pentru zecimale, `Intl.DateTimeFormat(lang)` pentru date.

- [ ] **Step 1: Test eșuat** — `test_stats_labels_and_decimal_separator`: în `en`, titlurile graficelor sunt în engleză; zecimalele folosesc punct (`12.5`), iar în `ro` virgulă (`12,5`).
- [ ] **Step 2: Rulează** → FAIL.
- [ ] **Step 3: Implementare**: toate formatările numerice și de dată trec prin `Intl`; etichetele graficelor se citesc din dicționar.
- [ ] **Step 4: Rulează** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "i18n: statistici, grafice și formatări"`.

**Model:** Sonnet. Fișierul `statistici.js` are 1.731 de linii: se împarte pe secțiuni, cu un commit intermediar la jumătate.

---

### Task 8: Migrare administrare, OCR, sistem, setări

**Files:**
- Modify: `web/admin.js`, `web/ocr.js`, `web/sistem.js`, `web/setari.js`, `web/sezoane.js`, `web/versions.js`
- Modify: dicționare
- Test: `tests/test_i18n_browser.py`

**Interfaces:**
- Consumes: `I18N.t`.

- [ ] **Step 1: Test eșuat** — `test_admin_in_english_with_romanian_fallback`: în `en`, titlurile admin apar în engleză; un mesaj de eroare din API (text românesc) rămâne în română, fără cheie brută.
- [ ] **Step 2: Rulează** → FAIL.
- [ ] **Step 3: Implementare** cu cheile `admin.*`, `ocr.*`, `sistem.*`.
- [ ] **Step 4: Rulează** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "i18n: administrare, OCR, sistem și setări"`.

**Model:** Haiku pentru extragerea cheilor din textele evidente, Sonnet pentru fișierele cu logică de randare (`admin.js`, `ocr.js`). Revizia de Sonnet pe ambele.

---

### Task 9: Service worker, offline și versiuni de cache

**Files:**
- Modify: `web/sw.js`, `web/offline.html`, `web/manifest.webmanifest` (doar `lang` dacă e nevoie)
- Test: `tests/test_i18n_browser.py`, `tests/test_ui3_static.py` (existent)

**Interfaces:**
- Consumes: lista de precache din `sw.js`.

- [ ] **Step 1: Test eșuat** — `test_offline_page_in_english_from_cache`: cu `lang=en` salvat și rețea oprită, `offline.html` afișează textul în engleză (Review Focus 5).
- [ ] **Step 2: Rulează** → FAIL.
- [ ] **Step 3: Implementare**: `web/i18n/ro.json`, `web/i18n/en.json`, `web/i18n/i18n.js` în precache; versiunea cache-ului crește (v18 → următoarea liberă); `CHARTS_V` crește; verifică bugetul de precache.
- [ ] **Step 4: Rulează** `pytest tests/test_ui3_static.py tests/test_i18n_browser.py -v` → PASS.
- [ ] **Step 5: Commit** — `git commit -m "i18n: service worker, offline și versiuni de cache"`.

**Model:** Sonnet.

---

### Task 10: Glosar și traducere documentație

**Files:**
- Create: `docs/en/glosar.md` (termeni fixați: OCR, precache, shadow, Istoric → History, Urmărite → Followed trains, Statistici → Statistics, etc.)
- Create: `docs/en/<nume>.md` pentru fiecare fișier din `docs/*.md` (12 fișiere, ~6.000 de linii)
- Create: `tests/test_docs_en_parity.py`

**Interfaces:**
- Consumes: glosarul (fixat înainte de restul traducerilor).

- [ ] **Step 1: Test eșuat** — `test_every_romanian_doc_has_english_twin`: pentru fiecare `docs/*.md`, există `docs/en/*.md` cu același nume.
- [ ] **Step 2: Rulează** → FAIL.
- [ ] **Step 3: Glosar** (Sonnet, o singură sesiune cu decizii fixate; Fable 5.2 doar pentru termeni ambigui).
- [ ] **Step 4: Traducere** pe fișiere, în paralel: fișierele mici (`meteo.md`, `admin-rotatie-cheie.md`, `brand/`) → Haiku; cele tehnice (`api.md`, `ocr.md`, `date-si-schema.md`, `administrare-operare.md`, `statistici-calatorii-calitate.md`, `deploy-si-configurare.md`, `arhitectura.md`, `testare.md`, `interfata.md`, `capturi-si-confidentialitate.md`) → Sonnet, cu glosarul în context.
- [ ] **Step 5: Rulează** → PASS.
- [ ] **Step 6: Commit** — pe fiecare lot, `git commit -m "docs: traducere în engleză — <lot>"`.

**Model:** Haiku (fișiere scurte), Sonnet (fișiere tehnice). Nicio sarcină pe Fable.

---

### Task 11: README bilingv și linkuri

**Files:**
- Create: `README.ro.md` (copia românească actuală, neschimbată)
- Modify: `README.md` (engleză)

**Interfaces:**
- Consumes: `docs/en/` (linkurile trimit acolo; `docs/` rămâne română).

- [ ] **Step 1: Test eșuat** — `test_readme_links_both_languages`: `README.md` conține link către `README.ro.md` și `docs/en/`; `README.ro.md` conține link către `README.md`.
- [ ] **Step 2: Rulează** → FAIL.
- [ ] **Step 3: Implementare**: `git mv` nu e necesar; copiere cu `README.ro.md` și traducerea în `README.md`, cu aceleași secțiuni.
- [ ] **Step 4: Rulează** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "docs: README în engleză și README.ro.md"`.

**Model:** Sonnet.

---

### Task 12: CHANGELOG bilingv, versiune 1.54, verificare finală

**Files:**
- Modify: `CHANGELOG.md`, `VERSION`

**Interfaces:**
- Consumes: `tests/test_version.py` (exact o intrare nouă sus, ≥5 puncte).

- [ ] **Step 1: Verifică** `pytest tests/test_version.py -v` → PASS după modificare.
- [ ] **Step 2: CHANGELOG**: secțiunea „Beta 1.54” în română, urmată de „Beta 1.54 (English)”, fără ca testul să numere două versiuni.
- [ ] **Step 3: Suita completă** în fundal: `pytest -q` → toate verzi. Oprește și raportează orice test roșu, cu ieșirea.
- [ ] **Step 4: Commit** — `git commit -m "Beta 1.54: versiune în engleză (interfață și documentație)"`.

**Model:** Sonnet. Orchestratorul (eu) verifică diff-ul final.

---

## Execution order and parallelism

- Task 1 → 2 → 3 → 4 (secvențial: fiecare depinde de contractul precedent).
- Tasks 5, 6, 7, 8 pot rula în paralel după Task 4, pe fișiere diferite. Dicționarele sunt fișiere comune: fiecare agent adaugă la final, iar orchestratorul rezolvă conflictele de merge.
- Task 9 după 5–8.
- Task 10 (glosar) înainte de restul traducerilor; fișierele din `docs/en/` în paralel.
- Task 11 după Task 10. Task 12 ultimul.

## Modele per sarcină (rezumat)

| Sarcină | Model | Motiv |
|---|---|---|
| 1–4, 9 | Sonnet | cod nou cu contract clar, o singură responsabilitate |
| 5–8 | Sonnet (Haiku pentru extragere în 8) | migrare mecanică cu logică de randare |
| 10 | Haiku (scurte), Sonnet (tehnice) | traducere; glosarul fixat înainte |
| 11–12 | Sonnet | README și versiune, cu verificare de orchestrator |
| Escaladare | Fable 5.2 | doar dacă o sarcină eșuează de două ori sau apare o ambiguitate de arhitectură |

## Self-review

- **Acoperirea specificației:** interfață (Tasks 1–9), documentație (Tasks 10–11), CHANGELOG (Task 12), service worker și versiuni (Task 9), testare (Tasks 1–3, 9–10). Toate secțiunile specificației sunt acoperite.
- **Consistența tipurilor:** `I18N.t`, `I18N.lang`, `I18N.setLang`, `I18N.applyDom`, `I18N.ready`, eveniment `i18n:change` — același nume în toate sarcinile.
- **Review Focus:** fiecare din cele 5 linii are test în sarcina care deține codul (1 → Task 1 și 3; 2 → Task 2; 3 → Task 2; 4 → Task 6; 5 → Task 9).
- **Abaterea JSON:** declarată în antet.

---

## Execution Handoff

Planul e salvat în `docs/superpowers/plans/2026-11-14-english-version.md`. Te rog să-l citești. Recomand **Subagent-driven**: sarcinile sunt multe (12), iar 5–8 pot rula în paralel, pe fișiere diferite. Fiecare sarcină primește modelul potrivit, iar un reviewer verifică fiecare înainte de următoarea. Native ar fi mai ieftin, dar fără review independent până la capăt.

Planul captează ce vrei? Dacă da, confirmă metoda (subagent-driven sau native) și pornesc.
