# Pagina admin #ocr2: alternativa OCR la vedere — 23.11.2026

## De ce
Alternativa OCR (Beta 1.62) rulează în mod umbră din 23.11 (`OCR_ALT=1`, `OCR_ALT_SHADOW=1`).
Pe ~30.11 utilizatorul decide dacă o pornește de-adevăratelea. Azi rezultatele umbrei ajung doar
în jurnalul serviciului (`app.ocr.alt_shadow`) și în contoare în memorie (`/api/health` → `ocr.alt`,
resetate la repornire). Decizia are nevoie de dovezi: ce ar fi completat alternativa și dacă e corect.

## Ce construim (varianta B, aleasă)
O pagină `#ocr2`, doar pentru admin, cu:
1. **Stare:** alternativa pornită/oprită, umbră da/nu, modelul (cale, încărcat da/nu), contoarele de la
   pornire (`frames`, `tried`, `recovered`).
2. **Totaluri persistente** (supraviețuiesc repornirii): evenimente înregistrate, rânduri propuse,
   verificate, corecte, greșite, neclare, **precizie = corecte / (corecte + greșite)** cu N afișat.
3. **Lista evenimentelor** (cele mai noi primele, 50 pe pagină, filtru „doar neverificate”): pentru fiecare
   rând propus — data/ora, panoul (Sosiri/Plecări), rândul, ce citise cititorul principal pe celelalte
   câmpuri (tip, stație, operator), coloanele completate de alternativă cu valoarea și încrederea,
   **decupajul celulei din captură** pentru fiecare coloană completată, butoanele **Corect / Greșit /
   Neclar** (și verdictul curent, modificabil).

## Non-scopuri
- Nu schimbă ce face alternativa și nici ce se afișează public.
- Fără schimbare de schemă DB (rămâne v9). Fără librării noi (JS vanilla, CSP neschimbat).
- Fără rută publică; nimic din aceste date în API-ul public.

## Contract

### Înregistrare (backend, `app/ocr/alt_journal.py`, nou)
- Directorul: `<dirname(DB_PATH)>/ocr_alt/` (pe server `/var/lib/tabela/ocr_alt/`), creat la nevoie (umask 027).
  Override: variabila `OCR_ALT_JOURNAL_DIR` (pentru teste).
- `events.jsonl` — o linie per rând propus (în umbră **și** când alternativa e activă): 
  `{"id": "<AAAALLZZTHHMMSS>-<board>-<row_index>", "ts": ISO UTC, "shadow": bool, "board": "arrival|departure",
  "row_index": int, "cols": ["no","time"], "values": {"no": "1581", "time": "18:44"}, "prob": 0.9931,
  "context": {"type": "IR", "station": "CONSTANTA", "operator": "CFR Calatori", "platform": ..., "delay": ...}}`
  (context = valorile normalizate ale cititorului principal pentru celelalte câmpuri, `null` dacă lipsesc).
- `crops/<id>_<col>.png` — decupajul celulei (imaginea celulei pe care a citit-o modelul, scalată ×3 pentru
  lizibilitate, PNG). Scris o singură dată, la înregistrare.
- `verdicts.json` — `{"<id>": {"verdict": "correct|wrong|unclear", "at": ISO UTC}}`, scris atomic (tmp + rename).
- Retenție: păstrează ultimele 30 de zile **și** maxim 5000 de evenimente; la depășire se rescrie
  `events.jsonl` și se șterg crop-urile și verdictele evenimentelor scoase. Rulată la cel mult o dată pe oră.
- Nu aruncă niciodată în poller: orice eroare se loghează (warning) și poller-ul merge mai departe.
- Cârlig: în `alt_reader.apply`, după `recover`, pentru fiecare linie din `info["lines"]` (pe copia `work`),
  în ambele moduri. Imaginea celulei se obține la fel ca în `recover` (`_panels(image_bytes)[board].cells(row_index)[col]`)
  — de preferat ca `recover` să păstreze referințele celulelor folosite, ca să nu decodeze imaginea de două ori.

### API (admin, `app/ocr_alt_api.py`, nou; router cu `Depends(admin.require_admin)`)
- `GET /api/admin/ocr-alt?limit=50&before=<id>&only=unverified|all` →
  `{"state": {"enabled", "shadow", "model_path", "model_loaded", "since_start": {"frames","tried","recovered"}},
    "totals": {"events", "verified", "correct", "wrong", "unclear", "precision": float|null, "n_precision": int},
    "events": [ {…eveniment…, "verdict": null|"correct"|"wrong"|"unclear", "crops": {"no": "/api/admin/ocr-alt/crop/<id>/no", …}} ],
    "next": "<id>"|null}`
- `GET /api/admin/ocr-alt/crop/{id}/{col}` → `image/png`, `Cache-Control: private, max-age=86400`;
  404 dacă lipsește; `id`/`col` validate strict (regex), fără path traversal.
- `POST /api/admin/ocr-alt/{id}/verdict` cu `{"verdict": "correct|wrong|unclear|null"}` (`null` = șterge),
  `Depends(admin.require_csrf)`; 404 la id necunoscut, 422 la valoare invalidă.
- Fără sesiune admin: 401 (ca restul `/api/admin/*`).

### Pagina (frontend)
- `#ocr2`, doar admin, nu apare în meniu (ca `#ocr`); fără sesiune → același comportament ca `#ocr`.
- `web/ocr2.js` + `web/ocr2.css`, încărcate la cerere (ca `ocr.js`), **nu** în precache.
- Texte prin `ro.json`/`en.json` (chei `ocr2.*`, identice în ambele). Fără `innerHTML` cu date; CSP neschimbat.
- La 360 px fără derulare orizontală. Temă luminoasă/întunecată din tokenii existenți.
- Butoanele de verdict: actualizare optimistă, revenire + mesaj la eroare. Precizia se recalculează după fiecare verdict.
- Link „Alternativa OCR →” din `#ocr` spre `#ocr2` (o linie).

## Release
Beta 1.63: `VERSION`, `CHANGELOG.md` (RO + English, min. 5 puncte), fără bump `CHARTS_V`/SW dacă precache nu se schimbă
(îl face controllerul).
