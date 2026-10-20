# Tabela Gara de Nord Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aplicație PWA publică care arată tabela de sosiri/plecări din Gara de Nord (extrasă prin OCR clasic din poza CFR), cu urmărire de trenuri + notificări push și istoric căutabil.

**Architecture:** Un singur proces FastAPI pe serverul Azure. Un poller sincronizat pe faza sursei descarcă poza, OCR (OpenCV + Tesseract) o transformă în rânduri, `store` le compară cu starea anterioară și scrie evenimente în SQLite, `notifier` trimite Web Push. PWA statică servită de același proces.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, OpenCV (headless), pytesseract + Tesseract (`ron`,`eng`), SQLite (WAL), pywebpush, pytest, HTML/CSS/JS simplu (service worker + manifest), nginx, systemd.

**Spec:** `docs/superpowers/specs/2026-10-20-tabela-gara-de-nord-design.md`

## Global Constraints

- Sursa: `https://cfr.ro/gari/camereweb/index.php?statie=BucurestiNord`; poza e `data:image/jpg;base64,...` în HTML, schimbată o dată pe minut la secunda ~:10–:13.
- OCR fără AI (Tesseract + OpenCV; nu modele ML/LLM). Poza nu se redistribuie; se păstrează doar ultima, pentru depanare.
- Poller: maxim 1 cerere la 2 s și ~10 cereri/min; backoff 5 s → 5 min la eroare; User-Agent identificabil; hash identic = fără OCR.
- Fus orar al datelor: `Europe/Bucharest`. Limba interfeței: română.
- Fără conturi, fără date personale; abonarea push e anonimă.
- Ore `HH:MM`; întârziere `+N` minute (absentă = 0); `board` ∈ `arrival|departure`.
- Design: dark implicit + light după sistem; cifre tabulare mono (JetBrains Mono), text Inter; contrast AA; respectă `prefers-reduced-motion`; loc pentru siglă în antet și icon PWA (placeholder până la siglă).
- Atribuire și drepturi (cerință utilizator): în subsolul fiecărei pagini apare `© 2026 Andy217Ace` și mențiunea „Date preluate de la CFR (cfr.ro) — proiect independent, neafiliat CFR. Tabela oficială: cfr.ro". `Andy217Ace` apare și în: `LICENSE` (MIT, `Copyright (c) 2026 Andy217Ace`), `README.md`, `<meta name="author">`, `manifest.webmanifest` (`description`), User-Agent-ul pollerului și headerul fiecărui fișier sursă (`# © 2026 Andy217Ace`, în JS/CSS `/* © 2026 Andy217Ace */`). Sursa „CFR" este citată în UI lângă ora „actualizat acum".
- Git (cerință utilizator): lucru pe branch-uri `feat/*`, commit-uri mici, PR către `main` și merge după CI/teste verzi; push și merge le face controllerul. Deploy imediat ce există părți funcționale (după Task 10, apoi după Task 11), nu doar la final.
- Fără secrete în repo (chei VAPID și credențiale server doar în variabile de mediu / fișier în afara repo-ului).
- Etapa 1 fără domeniu/HTTPS: push și instalare se testează ulterior; logica push se verifică cu endpoint simulat.

## Review Focus

1. Poza are 0 rânduri/sub prag sau e corupt → ciclul `ok=0`, nicio modificare, nicio notificare (Task 6, 4).
2. Același număr de tren apare de două ori în aceeași zi (ex. sosire și plecare, sau două ore) → nu se contopesc (Task 6).
3. Tren după miezul nopții (ora 00:05 citită la 23:58) → atribuit zilei corecte (Task 6).
4. OCR citește greșit o cifră într-un singur ciclu → nu trimite notificare (debounce 2 citiri) (Task 8).
5. Utilizator urmărește un tren care iese de pe panou și revine → fără notificări duplicate (Task 8).

---

## File Structure

```
requirements.txt, requirements-dev.txt, pytest.ini, .gitignore, README.md
app/__init__.py
app/config.py          # setări din env (DB_PATH, VAPID_*, URL sursă)
app/models.py          # Row, Event (dataclasses)
app/normalize.py       # validare/corecție câmpuri
app/fetcher.py         # pagină → bytes JPEG
app/ocr/__init__.py
app/ocr/preprocess.py  # mască culoare, decupări
app/ocr/reader.py      # imagine → list[Row]
app/poller.py          # PhaseTracker + bucla de polling
app/store.py           # SQLite: schema, ingest, diff, istoric, follows
app/notifier.py        # Web Push cu debounce
app/api.py             # rute FastAPI
app/main.py            # app factory, lifespan (pornește poller), static
web/index.html, web/app.js, web/style.css, web/history.js, web/sw.js,
web/manifest.webmanifest, web/icons/ (placeholder)
tests/fixtures/board_1.jpg, page_1.html, board_1.json
tests/test_*.py
deploy/tabela.service, deploy/nginx.conf, deploy/install.sh
```

---

### Task 1: Scaffold, modele și fixture de aur

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`, `pytest.ini`, `.gitignore`, `README.md`, `app/__init__.py`, `app/config.py`, `app/models.py`, `tests/test_models.py`, `tests/fixtures/board_1.json`
- Existente deja: `tests/fixtures/board_1.jpg`, `tests/fixtures/page_1.html` (poza reală și pagina reală din 2026-10-20)

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Row`: `board: str`, `train_type: str`, `train_no: int`, `station: str`, `operator: str`, `sched_time: str` (`HH:MM`), `delay_min: int = 0`, `platform: int | None = None`, `flagged: bool = False` (prefix `*` pe panou), `confidence: float = 1.0`; proprietatea `key -> tuple[str,int,str]` = `(board, train_no, sched_time)`.
  - `@dataclass(frozen=True) class Event`: `kind: str` (`delay|platform|appeared|gone`), `row: Row`, `old: str | None`, `new: str | None`.
  - `app/config.py`: `Settings` cu `db_path`, `source_url`, `vapid_private_key`, `vapid_public_key`, `vapid_subject`, citite din env cu valori implicite; `get_settings() -> Settings`.

- [ ] **Step 1: Test** `tests/test_models.py::test_row_key_and_defaults` — `Row("arrival","IR",1636,"BRASOV","CFR Calatori","20:04").key == ("arrival",1636,"20:04")`, `delay_min == 0`, `platform is None`.
- [ ] **Step 2: Rulează** `pytest tests/test_models.py -v` → FAIL (modul lipsă).
- [ ] **Step 3:** Creează scheletul (requirements: `fastapi`, `uvicorn[standard]`, `opencv-python-headless`, `numpy`, `pytesseract`, `pywebpush`, `httpx`; dev: `pytest`, `pytest-asyncio`), `pytest.ini` (`asyncio_mode = auto`, `testpaths = tests`), `.gitignore` (venv, `*.db`, `.env`, `__pycache__`), `models.py`, `config.py`.
- [ ] **Step 4:** Scrie `tests/fixtures/board_1.json` = lista de rânduri așteptate (golden) din poza `board_1.jpg`, citită de mână; ordine panou, `delay_min` 0 unde nu e coloană, `platform` null unde nu e coloană, `flagged` true unde apare `*`:
  - sosiri: IR 1636 BRASOV CFR Calatori 20:04 +10 lin 13 `*`; RE 11038 BRASOV Regio Calatori 20:11 lin 5 `*`; RM 7944 AEROPORT H COANDA CFR Calatori 20:17 +5; RE 5026 PLOIESTI SUD CFR Calatori 20:19 +10; RE 10156 ROSIORI NORD Transferoviar 20:20 +10; IR 1734 CLUJ NAPOCA CFR Calatori 20:34 +20; IR 1662 IASI CFR Calatori 20:40 +25; IR 16086 CONSTANTA CFR Calatori 20:51; IR 16016 CRAIOVA CFR Calatori 20:54 +10; RM 7946 AEROPORT H COANDA CFR Calatori 20:57; IR 16572 BRASOV InterRegional 20:58; IR 11538 BRASOV Astra Trans Ca 21:04.
  - plecări: RE 5003 BUZAU CFR Calatori 20:17 lin 4 `*`; R 3031 BRASOV CFR Calatori 20:23 lin 3; RE 10159 ROSIORI NORD Transferoviar 20:30; RE 10117 AEROPORT H COANDA Transferoviar 20:30 lin 10; RE 10079 PLOIESTI SUD Transferoviar 20:32 lin 7; IR 1589 CONSTANTA CFR Calatori 20:33 lin 13; RE 11039 BRASOV Regio Calatori 20:40 lin 5; RE 9217 PITESTI CFR Calatori 21:06; RE 10119 AEROPORT H COANDA Transferoviar 21:10; IRN 78 BUDAPESTA KELETI CFR Calatori 21:19; IRN 1641 SATU MARE CFR Calatori 21:20; RE 10121 AEROPORT H COANDA Transferoviar 21:50.
  - Verifică valorile deschizând imaginea (nu le ghici); sosirile și plecările au aceeași „întârziere/linie" doar acolo unde există coloana.
- [ ] **Step 5:** `pytest tests/test_models.py -v` → PASS. Commit `feat: scaffold, models, golden fixture`.

### Task 2: normalize

**Files:** Create `app/normalize.py`, `tests/test_normalize.py`

**Interfaces:**
- Consumes: `Row`.
- Produces:
  - `parse_time(s: str) -> str | None` — `"20:04"`, `"20.04"`, `"2004"` → `"20:04"`; invalid (`"25:99"`, `""`) → `None`.
  - `parse_delay(s: str) -> int` — `"+10"` → 10, `""` → 0, `"+1O"` → 10 (O→0), zgomot → 0.
  - `parse_platform(s: str) -> int | None` — 1–30, altfel `None`.
  - `normalize_type(s: str) -> str | None` — doar din `{IR, IRN, R, RE, RM, IC, EC, ...}` cu corecții (`"lR"`→`IR`); necunoscut → `None`.
  - `strip_flag(s: str) -> tuple[str, bool]` — `"*IR"` → `("IR", True)`.
  - `clean_station(s: str) -> str` — majuscule, fără diacritice, spații comprimate, fără zgomot la capete.

- [ ] **Step 1:** Teste cu exemplele de mai sus, plus `parse_delay("+130") == 130` și `parse_time("24:00") is None`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementează cu regex. **Step 4:** PASS. **Step 5:** Commit.

### Task 3: fetcher

**Files:** Create `app/fetcher.py`, `tests/test_fetcher.py`

**Interfaces:**
- Produces:
  - `extract_image(html: str) -> bytes` — decodează primul `data:image/<tip>;base64,...`; `ValueError` dacă lipsește sau nu e JPEG/PNG valid.
  - `image_hash(data: bytes) -> str` — sha1 hex.
  - `async fetch_board_image(client: httpx.AsyncClient, url: str) -> bytes` — GET cu header `User-Agent: tabela-gara-de-nord/1.0 (+https://github.com/Andy217ACE/tabela-gara-de-nord)`, timeout 15 s; ridică `FetchError` la status ≥ 400 sau conexiune închisă.
  - `class FetchError(Exception)`.

- [ ] **Step 1:** Teste: `extract_image(open("tests/fixtures/page_1.html").read())` începe cu `b"\xff\xd8"` și are > 10_000 bytes; HTML fără imagine → `ValueError`; `fetch_board_image` cu `httpx.MockTransport` returnând 500 → `FetchError`, returnând pagina fixture → bytes JPEG.
- [ ] **Step 2–5:** FAIL → implementează → PASS → commit.

### Task 4: OCR (preprocess + reader)

**Files:** Create `app/ocr/__init__.py`, `app/ocr/preprocess.py`, `app/ocr/reader.py`, `tests/test_ocr.py`

**Interfaces:**
- Consumes: `Row`, funcțiile din `normalize`.
- Produces:
  - `preprocess.text_mask(img_bgr: np.ndarray) -> np.ndarray` — imagine binară (text negru pe alb) păstrând doar pixelii deschiși (alb/galben), eliminând roșu (watermark) și albastru (fundal); mărită ×3.
  - `preprocess.split_boards(img_bgr) -> tuple[np.ndarray, np.ndarray]` — (sosiri, plecări), jumătăți calibrate.
  - `preprocess.row_bands(board_mask: np.ndarray) -> list[tuple[int,int]]` — intervale `(y0,y1)` de rânduri prin proiecție orizontală.
  - `reader.COLUMNS` — fracțiuni de lățime per coloană (`type, no, station, operator, time, delay, platform`), calibrate pe fixture.
  - `reader.read_board(image_bytes: bytes) -> list[Row]` — Tesseract per celulă (whitelist cifre pe `no/time/delay/platform`, litere pe `type`, `ron+eng` pe `station/operator`), normalizează, setează `confidence` (medie conf Tesseract); rânduri fără tip sau oră validă sunt eliminate. Dacă imaginea nu decodează → `ValueError`.

- [ ] **Step 1:** Teste pe `board_1.jpg` vs `board_1.json`:
  - `test_row_count` — 12 sosiri + 12 plecări.
  - `test_numeric_fields_exact` — `train_no`, `sched_time`, `delay_min`, `platform` identice pe cel puțin 95 % din rânduri și pe toate cele 24 pentru `sched_time`.
  - `test_text_fields_close` — `station` cu `difflib.SequenceMatcher` ≥ 0.85 pe ≥ 90 % din rânduri.
  - `test_watermark_ignored` — `text_mask` nu conține pixeli în zona watermark-ului când se aplică pe o poză fără text (imagine sintetică roșu pe albastru → mască goală).
  - `test_garbage_image` — `read_board(b"not an image")` ridică `ValueError`; o imagine albastră uniformă → `[]`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementează; calibrează `split_boards`/`COLUMNS` iterând pe fixture până trec pragurile. Dacă numerele/orele nu ating pragul cu Tesseract, adaugă în același task potrivire de șabloane pe cifre (fonturi fixe) doar pentru câmpurile numerice.
- [ ] **Step 4:** PASS. **Step 5:** Commit `feat: OCR`.

### Task 5: Poller sincronizat pe fază

**Files:** Create `app/poller.py`, `tests/test_poller.py`

**Interfaces:**
- Produces:
  - `class PhaseTracker`: `observe_change(ts: float) -> None` (ts = timp wall-clock când s-a văzut hash nou); `phase: float | None` (secunda din minut, mediană ultimelor ≤5 observații); `next_poll_delay(now: float, last_change: float | None) -> float` — secunde de așteptat până la următoarea cerere:
    - fără fază: 10 s (sondare rară);
    - în afara ferestrei `[faza − 1, faza + 20]` din minutul curent: așteaptă până la `faza − 1` din minutul următor;
    - în fereastră, înainte de schimbare: 2.5 s;
    - minim 2 s între cereri, backoff pe erori gestionat de apelant.
    - dacă nu s-a văzut schimbare > 300 s: 30 s.
  - `class Backoff`: `fail() -> float` (5, 10, 20 … max 300 s), `ok() -> None`.
  - `async def run_poller(settings, on_rows: Callable[[list[Row], float], Awaitable[None]], client: httpx.AsyncClient, stop: asyncio.Event) -> None` — buclă: fetch → hash; dacă nou → `read_board` → `on_rows(rows, ts)`; la `FetchError` aplică `Backoff`. Salvează ultima poză în `data/last.jpg`.

- [ ] **Step 1:** Teste: faza mediană din ts-uri `[13.2, 12.9, 13.4]` ≈ 13.2; `next_poll_delay` la `now=40` cu faza 13 → așteaptă până la ~72 − 40 = 32 s; `now=12.5` → ≤ 2.5; `now=14, last_change=13.2` (schimbare deja văzută în acest minut) → așteaptă până la faza − 1 din minutul următor; `Backoff` 5,10,20,…,300,300 și reset după `ok()`; `run_poller` cu client simulat și ceas injectat → nu face > 1 cerere la 2 s și apelează `on_rows` doar când hash-ul s-a schimbat.
- [ ] **Step 2–5:** FAIL → implementează → PASS → commit.

### Task 6: store (ingest, diff, evenimente)

**Files:** Create `app/store.py`, `tests/test_store.py`

**Interfaces:**
- Consumes: `Row`, `Event`.
- Produces `class Store` (`Store(path: str)`, `:memory:` acceptat; WAL; `migrate()` creează tabelele din spec: `runs`, `services`, `events`, `subscriptions`, `follows`):
  - `ingest(rows: list[Row], ts: datetime, image_hash: str = "") -> list[Event]` — tranzacțional; dacă `len(rows) < MIN_ROWS` (=4) sau lipsesc ambele panouri → înregistrează `runs.ok=0`, returnează `[]`, nu modifică `services`. Altfel upsert pe cheia `(board, service_date, train_no, sched_time)`, generează `delay`, `platform`, `appeared`; `gone` pentru servicii `listed` care nu mai apar în **două** ingest-uri consecutive ok (`miss_count`), `status='gone'`.
  - `service_date(sched_time: str, now: datetime) -> date` — dacă `sched_time` e cu > 12 h înaintea/după `now` (tren la 00:05 văzut la 23:58) → ziua următoare/anterioară corespunzătoare; fus `Europe/Bucharest`.
  - `current_board() -> dict` — `{"updated_at", "arrivals": [...], "departures": [...]}` doar `status='listed'`, ordonate după oră.
  - `last_ok_age(now) -> float | None`.

- [ ] **Step 1:** Teste: secvență 1 citire → toate `appeared`; a 2-a cu `delay_min` schimbat → un eveniment `delay` cu `old`/`new`; ingest cu 1 rând → `ok=0` și `services` neschimbat (Review Focus 1); același `train_no` în `arrival` și `departure` și același număr la două ore diferite → servicii separate (RF 2); `service_date("00:05", datetime(2026,10,20,23,58))` → `2026-10-21` (RF 3); tren dispărut o singură citire → încă `listed`, după două → `gone` + eveniment `gone`.
- [ ] **Step 2–5:** FAIL → implementează → PASS → commit.

### Task 7: istoric

**Files:** Modify `app/store.py`; Create `tests/test_history.py`

**Interfaces:**
- Produces în `Store`:
  - `history(date: date, train: int | None = None, station: str | None = None, board: str | None = None, time_from: str | None = None, time_to: str | None = None) -> list[dict]` — pe serviciu: `board, train_type, train_no, station, operator, sched_time, max_delay, final_delay, platform, status, first_seen, last_seen`; ordonat după `sched_time`; `station` căutare substring fără diacritice, case-insensitive.
  - `train_events(train_no: int, date: date) -> list[dict]` — evenimentele în ordine cronologică, cu serviciul.

- [ ] **Step 1:** Teste: după ingest-uri cu întârzieri 5 → 10 → 7, `history(...)` dă `max_delay=10`, `final_delay=7`; filtre `train`, `station="brasov"`, interval orar; zi fără date → `[]`; `train_events` returnează 3 evenimente `delay` în ordine.
- [ ] **Step 2–5:** FAIL → implementează → PASS → commit.

### Task 8: notifier + follows

**Files:** Create `app/notifier.py`; Modify `app/store.py` (`subscribe`, `unsubscribe`, `follow`, `unfollow`, `followers(train_no, date)`); Create `tests/test_notifier.py`

**Interfaces:**
- Produces în `Store`: `subscribe(endpoint: str, p256dh: str, auth: str) -> int`, `unsubscribe(endpoint: str) -> None`, `follow(endpoint: str, train_no: int, date: date) -> None`, `unfollow(...) -> None`, `followers(train_no: int, date: date) -> list[Subscription]`, `list_follows(endpoint: str) -> list[dict]`.
- `app/notifier.py`:
  - `class Notifier(store, send: Callable[[Subscription, dict], Awaitable[None]], confirm: int = 2)`.
  - `async def handle(events: list[Event], today: date) -> None` — o schimbare (cheie `(service, kind, new)`) se trimite doar după ce a fost văzută în `confirm` ingest-uri consecutive; dedup: aceeași valoare nu se retrimite; mesaj în română (`"IR 1636: întârziere +10 min"`, `"IR 1636: linia 13"`, `"IR 1636: a ieșit de pe panou"`); endpoint-uri cu 404/410 se șterg.
  - `make_webpush_sender(settings) -> send` — folosește `pywebpush` cu cheile VAPID.

- [ ] **Step 1:** Teste cu `send` simulat: o schimbare văzută într-un singur ingest → 0 notificări (RF 4); văzută în 2 → 1; aceeași valoare după → 0; tren `gone`, reapare, `gone` din nou → câte o notificare per tranziție confirmată, fără dubluri (RF 5); numai abonații care urmăresc trenul primesc; send ridică `Gone` → abonarea ștearsă.
- [ ] **Step 2–5:** FAIL → implementează → PASS → commit.

### Task 9: API și aplicația

**Files:** Create `app/api.py`, `app/main.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: `Store`, `Notifier`, `run_poller`.
- Produces:
  - `create_app(settings: Settings | None = None, start_poller: bool = True) -> FastAPI` — lifespan pornește poller-ul (cu `on_rows` = `store.ingest` + `notifier.handle`) și îl oprește curat; montează `web/` ca static la `/`.
  - Rute: `GET /api/board`, `GET /api/history`, `GET /api/train/{no}`, `POST /api/push/subscribe`, `POST /api/push/unsubscribe`, `POST /api/follow`, `DELETE /api/follow`, `GET /api/follows?endpoint=`, `GET /api/push/key` (cheia VAPID publică), `GET /api/health` (`{"ok": bool, "age_s": float|None}`; `ok=false` dacă ultima citire ok > 180 s).
  - Validări: `date` ISO, `train` int, `endpoint` URL https, mărime body ≤ 4 KB; erori 422 cu mesaj în română.

- [ ] **Step 1:** Teste cu `TestClient(create_app(start_poller=False))` și `Store(":memory:")` populat: `/api/board` returnează sosiri/plecări; `/api/history?date=...&station=brasov`; `/api/history?date=nu-e-data` → 422; follow/unfollow roundtrip; `/api/health` → `ok=false` fără date.
- [ ] **Step 2–5:** FAIL → implementează → PASS → commit.

### Task 10: Frontend — tabela live (design)

**Files:** Create `web/index.html`, `web/style.css`, `web/app.js`, `web/icons/` (placeholder SVG), `tests/test_web_static.py`

**Interfaces:**
- Consumes: `GET /api/board`.
- Produces: pagină cu antet (loc siglă + titlu „Gara de Nord"), tab-uri Sosiri/Plecări (desktop: alăturate), carduri per tren: ora mare mono, stație, operator, insigne tip/linie/întârziere (verde/chihlimbar/roșu + text), buton „urmărește"; indicator „live" cu puls și „actualizat acum X s"; reîmprospătare la 10 s; animație flash la schimbare de întârziere (dezactivată la `prefers-reduced-motion`); stare „date vechi" dacă `age_s > 180`.

- [ ] **Step 1:** Test `tests/test_web_static.py`: `GET /` (cu `TestClient`) conține `<title>`, `manifest`, și `GET /style.css` definește variabilele de culoare pentru `prefers-color-scheme: dark` și `light`.
- [ ] **Step 2–3:** FAIL → implementează UI (mobil-first, bară jos Tabelă · Istoric · Urmărite; teme prin variabile CSS; fonturi Inter + JetBrains Mono din Google Fonts cu fallback sistem).
- [ ] **Step 4:** PASS + verificare vizuală cu Playwright (screenshot mobil 390 px și desktop 1280 px; nicio suprapunere/scroll orizontal). **Step 5:** Commit.

### Task 11: Frontend — istoric, urmărite, PWA

**Files:** Create `web/history.js`, `web/sw.js`, `web/manifest.webmanifest`; Modify `web/index.html`, `web/app.js`

**Interfaces:**
- Consumes: `/api/history`, `/api/train/{no}`, `/api/follow*`, `/api/push/*`.
- Produces: ecran Istoric (zi, număr tren, stație, interval orar; listă cu oră, întârziere max/finală, linie; detalii eveniment per tren), ecran Urmărite (listă + activare notificări), `sw.js` (cache shell + ultima tabelă offline marcată veche; handler `push` și `notificationclick`), `manifest.webmanifest` (nume, culori, icon placeholder).

- [ ] **Step 1:** Test `tests/test_web_static.py`: `manifest.webmanifest` e JSON valid cu `name`, `start_url`, `display=standalone`, ≥ 1 icon; `sw.js` servit cu `Content-Type` JavaScript.
- [ ] **Step 2–4:** FAIL → implementează → PASS; Playwright: deschide Istoric, alege o zi cu date de test, filtrează, verifică lista; activarea push se ascunde elegant când `Notification`/`PushManager` lipsesc sau pagina nu e HTTPS (mesaj „Notificările necesită conexiune sigură (HTTPS)").
- [ ] **Step 5:** Commit.

### Task 12: Deploy pe serverul Azure (se execută imediat după Task 10, redeploy după Task 11)

**Files:** Create `deploy/tabela.service`, `deploy/nginx.conf`, `deploy/install.sh`; Modify `README.md`

- [ ] **Step 0:** Adaugă `LICENSE` (MIT, Copyright (c) 2026 Andy217Ace) și secțiunea de atribuire CFR în `README.md` (dacă nu există deja).
- [ ] **Step 1:** Backup înainte de orice: listă a ce există (`ls /opt`, `systemctl list-units --type=service`), nu se atinge nimic existent.
- [ ] **Step 2:** `deploy/install.sh` idempotent: `apt install tesseract-ocr tesseract-ocr-ron python3-venv nginx`, utilizator de serviciu, `/opt/tabela`, venv, `pip install -r requirements.txt`, generare chei VAPID în `/etc/tabela.env` (cu permisiuni 600, în afara repo-ului), `systemd` unit, nginx (proxy pe `127.0.0.1:8000`, rate limit `limit_req` 10 r/s pe `/api/`), `ufw allow 80,443`.
- [ ] **Step 3:** Deploy din repo (clone/pull pe server), pornire serviciu.
- [ ] **Step 4:** Verificare: `curl http://20.215.34.94/api/health` → `ok:true` în ≤ 2 min; `/api/board` are ≥ 4 rânduri per panou; log-ul arată cereri spre CFR la ritmul fazei (nu > 10/min); pagina se încarcă în browser.
- [ ] **Step 5:** Commit + `README` cu instrucțiuni (rulare locală, deploy, activarea HTTPS ulterioară prin certbot + sslip.io sau domeniu).

---

## Self-review

- **Acoperire spec:** sursă/fetcher (T3), OCR (T4), poller sincronizat (T5), model de date + evenimente (T6), istoric (T7), push + follow + debounce (T8), API (T9), PWA + design + istoric UI (T10–11), deploy + rate limit (T12), fără domeniu (T12/README).
- **Consistență tipuri:** `Row.key` folosit în T6; `Event` folosit în T6/T8; `Settings` din T1 folosit în T5/T8/T9; `Store` extins incremental în T6→T7→T8.
- **Proporție:** planul are valori fixate (praguri, ferestre, texte) și semnături; corpurile funcțiilor sunt la latitudinea implementatorului.
