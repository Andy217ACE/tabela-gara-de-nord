# Statistici v3 — sub-proiectul 1 (sumar, filtre, navigare) — plan de implementare

> **For agentic workers:** execute task-by-task; steps use checkbox (`- [ ]`) syntax.

**Goal:** pagina de Statistici are sumar rapid sus, filtre sticky cu buton de reset, link-uri directe către secțiuni, presetări salvate și panou de filtre pentru mobil.

**Spec:** `docs/superpowers/specs/2026-11-15-statistici-v3-design.md` (secțiunea „Sub-proiectul 1”).

**Architecture:** totul e front-end în `web/statistici.js` (funcția `ensure()` construiește formularul de filtre; `load()`/`render()` construiesc corpul), stiluri în `web/statistici.css`, texte în `web/i18n/ro.json` și `en.json` (chei identice). Niciun endpoint nou. Parametrul de secțiune `sect` nu intră în `FIELDS`, ca să nu fie tratat ca filtru.

**Tech Stack:** JavaScript vanilla (CSP: fără inline, fără `innerHTML` cu date), Playwright pentru teste de browser (`tests/test_i18n_browser.py` și `tests/test_statistici_browser.py` există deja ca model), pytest.

## Global Constraints

- Limbi: ro (implicit) și en; orice text nou are cheie în ambele fișiere, cu aceiași `{parametri}`.
- Layout la 360 px: `document.documentElement.scrollWidth <= 360`, fără derulare orizontală.
- `localStorage` în try/catch; nimic nu aruncă excepție nerezolvată.
- Bugetul de precache nu crește (statistici.js nu e în precache; nu adăuga fișiere noi în SHELL).
- Testele existente rămân verzi.

## Review Focus

1. **Filtru activ fără valoare vizibilă:** „Resetează” apare doar când un filtru diferă de implicit; reset golește și adresa.
2. **Presetare salvată cu un câmp care nu mai există** (ex. operator șters): se aplică doar câmpurile valide, fără eroare.
3. **`sect=` necunoscut sau lipsă:** pagina se deschide normal, fără derulare și fără eroare.
4. **`localStorage` blocat:** presetările se dezactivează cu mesaj; filtrele merg.
5. **Sumar cu date lipsă** (un câmp `null`): afișează „—”, nu `NaN`.

## File Structure

- Modify: `web/statistici.js` — sumar (`renderSummary`), reset (în `ensure()`), sect (în `show()`), presetări (funcții noi `presets*`), panou mobil (în `ensure()`).
- Modify: `web/statistici.css` — sticky, sumar, panou mobil, evidențiere secțiune.
- Modify: `web/i18n/ro.json`, `web/i18n/en.json` — chei `stats.sum.*`, `stats.reset`, `stats.preset.*`, `stats.mobile.*`.
- Create: `tests/test_stats_v3_sp1_browser.py` — testele de browser ale sub-proiectului.
- Create: `tests/test_stats_v3_sp1_static.py` — testul static pentru chei și pentru lipsa `innerHTML` în fișierele noi.

---

### Task 1: Sumar rapid

**Files:** Modify `web/statistici.js`, `web/statistici.css`, `web/i18n/ro.json`, `web/i18n/en.json`; Test `tests/test_stats_v3_sp1_browser.py`.

**Interfaces:** Consumes: răspunsul existent `/api/stats/overview` (câmpurile de sumar le citește din `v.data`; numele exact le stabilești din `app/stats_overview.py` și din `render()`). Produces: funcția `renderSummary(data)` care construiește cele patru carduri în `v.ui.body` înaintea secțiunilor.

- [ ] **Step 1: Test eșuat.** În `tests/test_stats_v3_sp1_browser.py`, `test_summary_cards_show_four_metrics`: deschide `#statistici` cu date de test (folosește fixture-ul `stats_url` din `tests/test_i18n_browser.py` sau echivalentul din `tests/test_statistici_browser.py`), așteaptă `.ss-summary .ss-card` și verifică patru carduri cu titluri din dicționar și o valoare care nu e `NaN`.
- [ ] **Step 2: Rulează** `pytest tests/test_stats_v3_sp1_browser.py -q` → FAIL.
- [ ] **Step 3: Implementează** `renderSummary(data)`: patru carduri (`% la timp`, `întârziere medie`, `trenuri analizate`, `ruta cu cele mai multe probleme`), fiecare cu titlu `t("stats.sum.<cheie>")` și valoare formatată cu `num()`/`pct()`/`minutes()`; valoarea `null` → „—”. Apelat din `render()` înainte de secțiuni.
- [ ] **Step 4: Rulează** → PASS; adaugă cheile `stats.sum.*` în ambele dicționare.
- [ ] **Step 5: Commit** `git commit -m "stats v3 sp1: sumar rapid"`.

---

### Task 2: Filtre sticky și buton de reset

**Files:** Modify `web/statistici.js` (`ensure()`), `web/statistici.css`, dicționare; Test `tests/test_stats_v3_sp1_browser.py`.

**Interfaces:** Consumes: `v.ui.form`, funcția `read()` din `ensure()`, `syncHash`, `load`.

- [ ] **Step 1: Teste eșuate:** `test_filters_stay_sticky_after_scroll` (după derulare, `.ss-filters` are `getBoundingClientRect().top` ≤ 1); `test_reset_clears_filters_and_hash` (setează perioada `7`, butonul `.ss-reset` apare; click → perioada revine la `all`, adresa nu mai conține `perioada=`, butonul dispare).
- [ ] **Step 2: Rulează** → FAIL.
- [ ] **Step 3: Implementează:** în CSS `.ss-filters { position: sticky; top: 0; z-index: 5; }`; buton `button.ss-reset` (text `stats.reset`) în formular, `hidden` când `read()` e egal cu valorile implicite; click: setează câmpurile la implicit, apelează același flux ca `change` (`v.p = read(); syncHash(v.p); load();`).
- [ ] **Step 4: Rulează** → PASS.
- [ ] **Step 5: Commit** `git commit -m "stats v3 sp1: filtre sticky și reset"`.

---

### Task 3: Link-uri directe către secțiuni

**Files:** Modify `web/statistici.js` (`show()`, `query`/`syncHash` nu se schimbă pentru filtre), `web/statistici.css`; Test `tests/test_stats_v3_sp1_browser.py`.

**Interfaces:** Consumes: id-urile secțiunilor deja randate (verifică în `render()`); `location.hash`. Produces: parametrul `sect` în hash, citit de `show()` și scris când utilizatorul navighează către o secțiune.

- [ ] **Step 1: Teste eșuate:** `test_deep_link_scrolls_and_highlights_section` (deschide `#statistici?sect=probleme`, secțiunea există și are clasa `ss-target` după încărcare, `window.scrollY` > 0); `test_unknown_section_is_ignored` (`?sect=nu-exista` → pagina se deschide, fără `ss-target`, fără eroare de consolă).
- [ ] **Step 2: Rulează** → FAIL.
- [ ] **Step 3: Implementează:** după `render()` în `show()`, citește `sect` din `location.hash`; dacă există o secțiune cu id-ul corespunzător, `scrollIntoView({block:"start"})` și adaugă `ss-target` (scoasă după 2 s). La click pe un link de secțiune din sumar sau din meniul de secțiuni, actualizează hash-ul cu `sect=` fără a șterge filtrele. `sect` nu intră în `FIELDS`.
- [ ] **Step 4: Rulează** → PASS.
- [ ] **Step 5: Commit** `git commit -m "stats v3 sp1: link-uri directe către secțiuni"`.

---

### Task 4: Presetări salvate

**Files:** Modify `web/statistici.js` (funcții noi `presetsLoad`, `presetsSave`, `presetsApply`, buton și meniu în `ensure()`), dicționare; Test `tests/test_stats_v3_sp1_browser.py`.

**Interfaces:** Consumes: `read()`, `setForm(p)`, `query`. Produces: cheia `tabela.statsPresets` în `localStorage`, valoare JSON: listă de `{name: string, filters: object}`, maximum 5 intrări.

- [ ] **Step 1: Teste eșuate:** `test_preset_saves_and_restores_filters` (setează operator și perioada `7`, salvează „Test”, reîncarcă pagina → presetarea există în meniu; apply → filtrele revin); `test_preset_with_missing_field_applies_valid_fields_only` (salvează în `localStorage` o presetare cu un câmp `operator` inexistent → apply nu aruncă, perioada se aplică); `test_presets_disabled_without_storage` (`localStorage` aruncă → meniul afișează mesajul `stats.preset.unavailable`, filtrele merg).
- [ ] **Step 2: Rulează** → FAIL.
- [ ] **Step 3: Implementează:** buton „Presetări” lângă reset; meniu cu lista de presetări (apply la click, buton de ștergere pe fiecare); „Salvează filtrele” cere un nume (`window.prompt` NU — folosește un câmp inline cu `input` și buton), max 5. Toate accesele la `localStorage` în try/catch.
- [ ] **Step 4: Rulează** → PASS.
- [ ] **Step 5: Commit** `git commit -m "stats v3 sp1: presetări de filtre salvate"`.

---

### Task 5: Panou de filtre pentru mobil

**Files:** Modify `web/statistici.js` (`ensure()`), `web/statistici.css`, dicționare; Test `tests/test_stats_v3_sp1_browser.py`.

**Interfaces:** Consumes: `v.ui.form`, `window.matchMedia("(max-width: 599px)")`.

- [ ] **Step 1: Teste eșuate:** `test_mobile_filters_collapse_into_panel` (la 360 px, câmpurile sunt ascunse, butonul `.ss-filters-toggle` arată „Filtre (n)” cu n = numărul de filtre active; click → câmpurile apar); `test_no_horizontal_scroll_at_360` (`scrollWidth <= 360`, cu și fără panou deschis).
- [ ] **Step 2: Rulează** → FAIL.
- [ ] **Step 3: Implementează:** sub 600 px, câmpurile formularului primesc `hidden` până la click pe `.ss-filters-toggle`; numărul din buton se recalculează la fiecare `change`. Peste 600 px, comportamentul rămâne cel de până acum.
- [ ] **Step 4: Rulează** → PASS.
- [ ] **Step 5: Commit** `git commit -m "stats v3 sp1: panou de filtre pe mobil"`.

---

### Task 6: Versiune, changelog, verificare

**Files:** Modify `VERSION` (Beta 1.57), `CHANGELOG.md` (secțiune nouă cu cel puțin 5 puncte în română și `### English`), `web/ui2.js` (`CHARTS_V` = `1.57`).

- [ ] **Step 1:** rulează `pytest tests/test_version.py tests/test_ui3_static.py tests/test_stats_v3_sp1_browser.py tests/test_stats_v3_sp1_static.py tests/test_i18n_parity.py tests/test_statistici_browser.py -q` → PASS.
- [ ] **Step 2:** scrie secțiunea din CHANGELOG (Adăugat: sumar, sticky și reset, link-uri către secțiuni, presetări, panou mobil; plus `### English`).
- [ ] **Step 3: Commit** `git commit -m "Beta 1.57: Statistici v3 sp1 (sumar, filtre, navigare)"`.
