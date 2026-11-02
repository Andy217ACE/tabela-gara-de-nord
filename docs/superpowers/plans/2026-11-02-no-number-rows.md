# Rânduri fără număr de tren Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un rând citit fără număr de tren (`train_no` 0) nu mai creează și nu modifică servicii; rămâne în observations ca „incomplete”.

**Architecture:** `app/ocr/reader.py` (~linia 1360) construiește rândul cu `train_no=0` când celula numărului nu are cifre. `Store._diff` tratează rândul ca pe un tren real: nicio cale de potrivire (exactă, jitter, fuzzy) nu cere 0, dar rândul cu încredere >= `CONFIRM_CONFIDENCE` (0.7) devine serviciu nou. Fix-ul: filtrul `train_no` în `_diff`, pe `good` și `low`, după judecata panoului. `_judge` rămâne neschimbat: rândul fără număr e tot un rând de pe panou, deci contorul pentru „partial read” / „too few rows” rămâne corect. `observations.py` nu se schimbă: `validation_state` dă deja „incomplete” pentru `not row.train_no`, iar `record_capture` salvează rândul fără `service_id`.

**Tech Stack:** Python, SQLite (`app/store.py`), pytest. Venv din repo principal: `C:/Users/Irina Profir/projects/tabela-gara-de-nord/.venv/Scripts/python.exe`.

**Spec:** Cererea de lucru din 2026-11-02 (nu există document de spec separat).

## Global Constraints

- Fără push, merge, deploy; fără atingerea serverului sau a bazei de date.
- Fiecare schimbare de comportament are test roșu înainte de fix.

## Review Focus

1. Rând fără număr la aceeași oră și stație ca un tren real citit corect, cu încredere mare → nu creează serviciu, nu schimbă trenul (Task 1: `test_no_number_row_creates_no_service`, `test_no_number_row_does_not_change_existing_train`).
2. Rând fără număr singur în cadru → nu creează nimic, nu modifică trenul existent (Task 1: `test_no_number_row_alone_creates_nothing`).
3. Rând fără număr care ar fi potrivit fuzzy cu un tren de o cifră (0 vs 5) → nu revendică trenul (Task 1: `test_no_number_row_is_not_fuzzy_matched_to_one_digit_train`).
4. Rândurile fără număr intră în contorul panoului → panoul nu e respins din cauza lor (Task 1: `test_no_number_rows_count_for_panel_judgement`).
5. Rând fără număr în observations → „incomplete”, fără `train_no`, fără `service_id` (Task 2: `test_no_number_row_is_kept_as_incomplete`).

## Task 1: Store ignoră rândurile fără număr în diff

**Files:**
- Test: `tests/test_store_no_number.py` (nou)
- Modify: `app/store.py` (`Store._diff`, la început, după `self.last_ghost_numbers = set()`)

**Interfaces:**
- Consumes: `Store.ingest(rows: list[Row], ts: datetime, image_hash: str = "") -> list[Event]`; `Row.train_no: int`
- Produces: `_diff` nu procesează rânduri cu `train_no == 0`; nicio semnătură publică nouă.

- [ ] **Step 1: Scrie testele** (cinci teste în `tests/test_store_no_number.py`, după Review Focus 1–4; aserțiile: `ev == []`, `COUNT(services WHERE train_no=0) == 0`, `last_delay`/`last_platform` ale lui 7908 rămân 0/None, `last_seen` al lui 5 rămâne `T0`, `store.last_rejected == {}`).
- [ ] **Step 2: Rulează, verifică roșu.** `pytest tests/test_store_no_number.py -q` → așteptat: 3 picate (`creates_no_service`, `alone_creates_nothing`, `fuzzy_matched`). Două trec deja (`does_not_change_existing_train`, `count_for_panel_judgement`): sunt teste de regresie pentru guard, nu dovadă de bug.
- [ ] **Step 3: Implementează.** În `Store._diff`: `good = [r for r in good if r.train_no]` și `low = [r for r in low if r.train_no]`, cu un comentariu de o linie.
- [ ] **Step 4: Rulează, verifică verde.** `pytest tests/test_store_no_number.py -q` → așteptat: 5 trecute.
- [ ] **Step 5: Commit** (după Task 2, pentru un commit per fix cu CHANGELOG).

## Task 2: Observations păstrează rândul fără număr ca „incomplete”

**Files:**
- Test: `tests/test_observations.py` (funcția `test_no_number_row_is_kept_as_incomplete`)
- Modify: nimic în `app/observations.py` (comportamentul există; testul îl fixează)

**Interfaces:**
- Consumes: `observations.record_capture(store, image_bytes, rows, debug, ts, *, capture_dir)`
- Produces: nimic nou.

- [ ] **Step 1: Scrie testul** (rând `train_no=0`, `validation_state == "incomplete"`, `train_no IS NULL`, `service_id IS NULL`).
- [ ] **Step 2: Rulează.** Așteptat: trece și înainte de fix, pentru că observations nu s-a schimbat; de aceea e pin, nu roșu.
- [ ] **Step 3: Nicio modificare de cod.**

## Task 3: Versiune și CHANGELOG

**Files:**
- Modify: `VERSION` (`Beta 1.43` → următoarea versiune liberă), `CHANGELOG.md` (intrare nouă sus)

- [ ] **Step 1:** Verifică tag-urile `beta-*` (ultimul `beta-1.43`) și `git fetch` (deja făcut, fără versiune nouă pe remote).
- [ ] **Step 2:** Adaugă intrarea în CHANGELOG cu versiunea liberă, în stilul existent, și actualizează `VERSION`.
- [ ] **Step 3: Commit.**

```bash
git add app/store.py tests/test_store_no_number.py tests/test_observations.py docs/superpowers/plans/2026-11-02-no-number-rows.md VERSION CHANGELOG.md
git commit -m "fix: rândurile fără număr de tren nu mai creează servicii"
```
