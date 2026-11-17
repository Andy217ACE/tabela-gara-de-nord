# Alternativa OCR — specificație

Data: 2026-11-17 · Ramură: `feat/ocr-alt-spec` · Doar specificație; implementarea vine într-un plan și un branch separat.

Convenție: „(verificat)” = confirmat în cod; „(presupunere)” = neverificat în cod, de confirmat.

## Scop

Modelul antrenat în umbră (`scripts/nightly_shadow_train.py`, MLP numpy peste glifele de cifre, 128 unități ascunse, 30 de epoci; rulat zilnic 10–14.11, ~18 min, ~4,8 GB RAM; 99,76% față de motor 99,62% pe scris de mână) devine o **alternativă de rezervă**: se încearcă numai când cititorul actual nu scoate nimic dintr-un cadru. Scopul e să recupereze cadre care azi se pierd (panou respins, rânduri `unread`), nu să „îmbunătățească” cadrele deja citite.

Stare actuală (verificat): nicio linie din `app/` nu importă clasificatorul; decizia raportului e fixă „nu promovez” (`decide()`); producția folosește Tesseract + șabloane (`digit_templates.npz`) cu buget `FRAME_BUDGET_S = 8 s` per cadru (`reader.py`). Clasificatorul citește doar coloanele cu cifre (`no`, `time`, `delay`, `platform`); tipul, stația și operatorul rămân la Tesseract (verificat în `docs/ocr.md` 19.2).

## Ce NU face

- **Nu înlocuiește cititorul.** Pe un cadru citit de cititorul actual, alternativa nu rulează și nu poate schimba nicio valoare.
- Nu suprascrie o valoare deja citită; completează doar celule rămase `unread` (aceeași regulă ca `_merge` la recitire: „doar coloanele necitite primesc valoare nouă”, verificat).
- Nu schimbă schema bazei de date, `PROCESSING_VERSION` de bază, `digit_templates.npz`, pragurile `store._judge` sau pragurile testelor existente.
- Nu rulează în procesul web la prima versiune dacă măsurătoarea de RAM (vezi Riscuri) nu o permite; nu se antrenează pe serverul live în timpul zilei.
- Nu inventează: dacă nici alternativa nu e sigură, linia rămâne `unread`.

## Criterii de declanșare exacte

Un cadru „eșuează” când, după toată recitirea cititorului actual (buget inclus), apare **oricare** din:

1. **Cadru fără rânduri:** `read_board` întoarce 0 rânduri (poller: „no rows read”, `error="no rows read"`), sau ambele panouri au 0 rânduri complete.
2. **Panou cu rânduri necitite peste prag:** un panou are ≥ 3 linii `unread` (text prezent, tren necitit) dar ≤ `MAX_RETRY_LINES` (4). Peste 4 cadrul e considerat stricat (JPEG trunchiat/glitch) și alternativa **nu** rulează, ca să nu inventeze rânduri (verificat: logica `MAX_RETRY_LINES` din `reader.py`). Pragul de 3 este o propunere de calibrat (presupunere).
3. **Cadru ce ar fi respins de `_judge`** din motive de volum: sub `MIN_ROWS` = 4 rânduri sigure sau un panou sub `MIN_BOARD_ROWS` = 2 (verificat în `store.py`).

Condiții suplimentare, toate obligatorii:
- cadrul are imagine decodabilă de cel puțin 200×60 px (limita `read_board_debug`);
- `OcrError` (timeout Tesseract, binar lipsă) **nu** declanșează alternativa: e o defecțiune a mediului, nu a cadrului (presupunere de confirmat);
- alternativa are propriul buget, `OCR_ALT_BUDGET_S` (propus 4 s) și se oprește la depășire; cadrul rămâne cum l-a lăsat cititorul actual;
- cel mult un cadru alternativ în zbor; peste limită se sare (nu se pune în coadă).

## Cum se marchează în observații

Fără schimbare de schemă: se adaugă sufixul `+ocr:alt` la `processing_version`-ul liniei, prin `line_version()` din `app/observations.py` (coloană `TEXT`, deja variabilă: `+retry:…`, `+corr:…`, verificat). Se marchează **doar liniile** completate de alternativă, nu tot cadrul.

- Parserul `parse_line_version` ignoră etichete necunoscute (verificat: ramurile necunoscute nu fac nimic), deci marcajul nu strică citirile existente; un test nou fixează comportamentul.
- Regula de interogare: `processing_version LIKE '%+ocr:alt%'`.
- Rândurile alternativei intră în statistici ca orice observație; filtrul de evaluare poate să le excludă prin marcaj.
- Fără marcaj nou pe `captures`; în `app/ocr/stats.py` se adaugă (în memorie) un contor „cadre recuperate de alternativă” pentru `/api/health` (presupunere de acceptat).

## Date de evaluare și criterii de promovare

Date:
- `tests/fixtures/ocr_truth/truth.json` (59 cadre, 1416 linii, adevăr scris de mână) și `holdout/holdout.json` (21 cadre, 504 linii, etichetat orbește); verificat în `docs/ocr.md` 20.
- **Seturi de eșec** (nou): cadrele din `REJECTED_DIR` (ultimele 40) și cadrele cu ≥ 1 linie `unread`, selectate din serverul real; etichetate de mână pentru ≥ 50 de cadre înainte de promovare. Silver-ul (acordul cititorului cu el însuși) nu e dovadă independentă (limită scrisă în `LIMITS`).
- Instrument: extensie a `scripts/ocr_eval.py` cu `--alt`, `OMP_THREAD_LIMIT=1`, același `NPROC` ca azi.

Criterii de promovare (toate, măsurate pe seturile de mai sus):
1. **Cadre recuperate:** ≥ 60% din cadrele-eșec din setul de eșec devin cadre acceptate de `_judge` cu alternativa (față de 0% fără ea).
2. **Fără citiri false noi:** pe `truth.json` + `holdout.json`, numărul de valori **greșite** nu crește pentru niciun câmp față de pragurile `MAX_WRONG` din `tests/test_ocr14.py`; pe liniile completate de alternativă, rata de greșite ≤ 0,5% din valorile etichetate, cu minim 300 de valori verificate.
3. **Zero interferență:** pe cadrele citite deja de cititorul actual, diferența de ieșire cu alternativa activată = 0 (test de regresie).
4. **Precizie pe câmp:** clasificatorul nu scade sub motor pe `no`, `platform`, `delay` (diferență semnificativă = 0,5 puncte, `SIGNIFICANT` din script).
5. **Buget:** p95 al timpului alternativei ≤ `OCR_ALT_BUDGET_S`; RAM de vârf măsurat sub limita din Riscuri.
Mod: întâi 7 zile în umbră în producție (rulează, scrie marcajul într-un jurnal, nu publică); promovare doar dacă criteriile 1–5 trec pe cadrele reale ale celor 7 zile.

## Riscuri

- **RAM/CPU:** antrenarea a măsurat ~4,8 GB (verificat doar din istoricul sesiunilor, nu din cod). **Inferența** e mult mai ieftină (MLP mic, doar greutăți din `model-*.npz`), dar nemăsurată (presupunere); se măsoară înainte de integrare. Antrenarea rămâne offline, în `tabela-shadow-train.service` (`Nice=19`, `IOSchedulingClass=idle`, timeout 2 h), nu în procesul web.
- **Tesseract concurent:** regula `OMP_THREAD_LIMIT=1` este doar procedură de rulare; `deploy/tabela.service` și `app/` nu o setează (verificat în `docs/ocr.md` 8.3). Alternativa rulează după cititorul actual, în același fir de cadru, ca să nu dubleze Tesseract; orice apel nou la Tesseract din alternativă (re-citire de celule) folosește același `OMP_THREAD_LIMIT=1`. O rulare paralelă a blocat OCR-ul live 16 min (din plan, `2026-10-27-backlog-wave.md`).
- **Model învechit:** greutățile vin din etichete silver (nu verificate de om) și din cadre vechi; fișierul modelului se versionează (data + amprenta motorului) și alternativa se dezactivează dacă amprenta nu se potrivește.
- **Bucla de feedback:** dacă observațiile `+ocr:alt` revin în antrenare, modelul învață din propria ieșire; se exclud din etichetele silver.
- **Încărcare pe cadru:** fiecare cadru-eșec adaugă secunde peste cele 8 ale bugetului; la rafale de eșecuri poate întârzia următorul cadru (cadrele vin o dată pe minut).

## Decizii de confirmat

1. Pragul de declanșare pe linii necitite: 3 per panou (propus) sau altul?
2. `OcrError` (timeout/binar lipsă) exclus din declanșare: de acord?
3. Mod de rulare: inline în poller după cititor, sau job separat care reia cadrele salvate (mai sigur pe RAM, dar întârziat)?
4. Cine etichetează ≥ 50 de cadre-eșec pentru setul de evaluare?
5. Durata fazei în umbră: 7 zile (propus).
6. Contor nou în `/api/health` pentru cadrele recuperate: acceptat?
