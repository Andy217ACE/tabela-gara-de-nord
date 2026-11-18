# Alternativa OCR: lista de integrare (pentru controller)

Ramură: `feat/ocr-alt` (din origin/main d2acead, Beta 1.60). Modulul nou `app/ocr/alt_reader.py` e complet și **oprit implicit**
(`OCR_ALT` neprecizat = no-op). Nimic de mai jos nu e aplicat în `poller.py`, `observations.py`, `stats.py`, `api.py`, `deploy/*`.

## 1. `app/poller.py`, `run_poller`: punctul de apelare (după cititor, înainte de `on_rows`)

Import (sus, lângă `from app.ocr.reader import ...`):

```python
from app.ocr import alt_reader
```

În blocul `try:` al citirii, imediat după `rows, debug = rows` (ramura `if on_capture is not None:`), adaugă:

```python
                if on_capture is not None:
                    rows, debug = rows
                    if debug and alt_reader.enabled():
                        alt = await asyncio.to_thread(alt_reader.apply, data, debug)
                        if alt.get("recovered") and not alt.get("shadow"):
                            rows = [e["row"] for e in debug if e["row"] is not None]
                        alt_reader_stats(alt)   # vezi punctul 3 (opțional)
```

Motive: (a) `read_board_debug` întoarce `rows = [e["row"] for e in entries if e["row"] is not None]` în aceeași ordine, deci
reconstrucția e identică cu a cititorului; (b) alternativa rulează în firul de cadru (`to_thread`), după cititor, deci nu
dublează Tesseract (nu apelează deloc Tesseract); (c) `OcrError`/`ValueError` ies prin `except` înainte de acest cod, deci
nu declanșează alternativa (decizia 2 din spec, confirmată); (d) `apply` nu aruncă niciodată (la eroare lasă `debug` neatins);
(e) cu `on_capture is None` (`read_board`, fără debug) alternativa nu rulează: ea are nevoie de liniile de debug. În producție
`on_capture` e mereu setat.

## 2. `app/observations.py`, `line_version`: marcajul `+ocr:alt`

După blocul `retry`, înainte de `delay`:

```python
    if entry.get("alt"):  # linia a fost completată de alternativa OCR (app/ocr/alt_reader.py)
        v += "+ocr:alt"
```

`parse_line_version` ignoră deja etichetele necunoscute (testat în `tests/test_ocr_alt_reader.py::test_alt_mark_does_not_break_the_version_parser`).
`PROCESSING_VERSION` nu se schimbă. Interogare: `processing_version LIKE '%+ocr:alt%'`.
Marcajul e pe linie (nu pe cadru): doar liniile cu `entry["alt"]`; fiecare are și `fields.<col>.check == "alt"` și `row.uncertain = True`,
`row.confidence <= 0.65` (sub `store.CONFIRM_CONFIDENCE` = 0.7: un serviciu nou din ea cere a doua citire consecutivă).

## 3. Contor în `/api/health` (opțional, decizia 6 din spec)

`app/ocr/stats.py`: contor în memorie, ex.

```python
_alt = {"frames": 0, "tried": 0, "recovered": 0}
def record_alt(info: dict) -> None:
    with _lock:
        _alt["frames"] += bool(info.get("tried"))
        _alt["tried"] += info.get("tried", 0)
        _alt["recovered"] += info.get("recovered", 0)
```

și expus în `snapshot()`; `alt_reader_stats` din punctul 1 = `stats.record_alt`. Dacă controllerul nu vrea contorul, se șterge linia
din poller; nimic altceva nu depinde de ea.

## 4. Configurare (env; `deploy/tabela.service` / fișierul de mediu, nu `app/config.py`)

| variabilă | implicit | rol |
|---|---|---|
| `OCR_ALT` | oprit | `1` pornește alternativa |
| `OCR_ALT_SHADOW` | oprit | `1`: rulează și scrie în jurnalul `app.ocr.alt_shadow` ce ar completa, fără să schimbe nimic (faza de 7 zile) |
| `OCR_ALT_MODEL` | gol (= oprit) | calea `model-AAAA-LL-ZZ.npz` (ex. `/var/lib/tabela/shadow/model-...npz`); lipsă/stricat/amprentă diferită = alternativa oprită, cu avertisment |
| `OCR_ALT_BUDGET_S` | 4 | buget propriu pe cadru |
| `OCR_ALT_MIN_UNREAD` | 1 | linii necitite pe panou de la care se declanșează (vezi ruling R1) |
| `OCR_ALT_MAX_UNREAD` | 4 | peste, panoul e stricat la sursă și nu se atinge (= `MAX_RETRY_LINES`) |

Calea de rulare recomandată: `OCR_ALT=1 OCR_ALT_SHADOW=1` 7 zile, apoi evaluarea de mai jos pe jurnal, apoi decizie. Nu se rulează
antrenarea în procesul web (neschimbat).

## 5. Antrenare și bucla de feedback (nu s-au atins `scripts/nightly_shadow_train.py` / `ocr_digit_clf.py`)

- `nightly_shadow_train.py`: la `np.savez_compressed(model, **P)` adaugă `engine_fp=engine_fingerprint()`. `AltModel.load` verifică
  amprenta dacă există (nu se potrivește: model învechit, alternativa se oprește). **Atenție:** amprenta din script include și
  fișierul scriptului; cea din `alt_reader.engine_fingerprint()` hașează doar `app/ocr/*` fără `alt_reader.py`. Ca să se potrivească,
  scriptul trebuie să hașeze același set (fără el însuși), sau câmpul se omite până atunci (fără câmp = fără verificare).
- Silver fără ieșirea alternativei: `export_db` trebuie să includă `processing_version` din `observations`, iar `ocr_digit_clf.label`
  să sară liniile cu `+ocr:alt`. Fără asta, modelul s-ar antrena din propria ieșire.

## 6. Verificare după integrare

```
set OMP_THREAD_LIMIT=1
python -m pytest tests/test_ocr_alt_reader.py tests/test_ocr_alt_real.py tests/test_ocr_alt_eval.py -q
python scripts/ocr_alt_eval.py baseline base.pkl            # citește 79 de cadre (NPROC=2)
python scripts/ocr_alt_eval.py eval base.pkl model-AAAA-LL-ZZ.npz --json rez.json
```

Capturile reale nu sunt în git: `OCR_TRUTH_DIR` (ca `tests/ocr_truth_images.py`) și `tests/fixtures/**/*.jpg` copiate local.

## Ruling-uri

- **R1. Prag de declanșare = 1 linie necitită per panou (nu 3 ca în spec).** Motiv: auditul (4 zile) arată 17 din 20 cadre cu o singură linie
  necitită; la 3 alternativa n-ar atinge 85% din ele. În setul de adevar, toate cele 8 linii necitite sunt singure pe panou. Cost dacă
  greșesc: o încercare în plus pe cadre cu o linie necitită (p95 0,08 s pe cadru cu o linie necitită, măsurat), fără risc de valori false mai mare decât
  la 3, fiindcă regulile de siguranță sunt pe celulă, nu pe numărul de linii. Reglabil prin `OCR_ALT_MIN_UNREAD`.
- **R2. Peste 4 linii necitite pe panou alternativa nu rulează** (contrazicere în spec: criteriul 1 „cadru fără rânduri” vs. criteriul 2 „>4 = stricat”).
  Motiv: auditul: cadrele fără rânduri sunt corupte la sursă (13 din 14), a le „repara” înseamnă a inventa; trebuie marcate, nu reparate. Cost: un
  cadru fără rânduri din cauza unei defecțiuni nesursă nu e recuperat; se deschide prin `OCR_ALT_MAX_UNREAD`.
- **R3. Doar `no` și `time` ale liniilor cu tip citit.** MLP-ul e antrenat pe cifre, `+`, `:`; tipul, stația, operatorul rămân ale cititorului.
  O linie fără tip rămâne necitită. Cost: pierdem cadrele de tip C3 din audit (tip lipsă); în setul de adevar 0 din 8 linii necitite n-au tip.
- **R4. Prag pe glifă 0,99 (spec: nespecificat).** Din evaluare: la 0,5 / 0,8 / 0,9 / 0,95 / 0,99: 19 / 12 / 6 / 3 / 0 valori greșite din
  3632 / 3609 / 3576 / 3542 / 3394 citite. Doar 0,99 dă 0 greșite; acoperirea scade de la 3542 la 3394 (−4%). Cost dacă greșesc: mai puține
  recuperări sau o citire falsă la nivelul de 0,08%.
- **R5. Ora trebuie să încapă în ordinea cronologică a panoului; numărul nu poate fi al altei linii.** Motiv: aceleași reguli ca `order.py` /
  `reader._duplicate`; taie citiri false fără a inventa nimic. Cost: o recuperare corectă dar „ciudată” e respinsă.
- **R6. Glife lipite (`fused`) => abstinență.** Segmentarea nu știe câte cifre sunt; cinci din cele opt linii necitite din adevăr au primele glife ale numărului lipite
  între ele (segmentare: `fused`), iar MLP-ul a dat 150157 în loc de 10157 și 15581 în loc de 1581 când i s-a permis. Cost: rămân necitite.
- **R7. Marcajul `+ocr:alt` pe linie, `entry["alt"]` pe intrarea de debug, `uncertain=True`, încredere ≤ 0,65.** Un rând al alternativei nu poate
  crea singur un serviciu nou (are nevoie de a doua citire).
- **R8. Mod umbră propriu (`OCR_ALT_SHADOW`)** în loc de un job separat: aceeași cale, zero risc pentru date; răspunde deciziei 3 din spec
  („inline după cititor”): alternativa nu rulează Tesseract și costă milisecunde, deci inline e sigur pe RAM/CPU.
