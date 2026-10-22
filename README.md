<p align="center"><img src="web/icons/logo.png" alt="Sigla Tabela Gara de Nord" width="96" height="96"></p>

# Tabela Gara de Nord

Aplicație web (PWA) care citește prin OCR clasic (OpenCV + Tesseract, fără AI) tabela de sosiri/plecări din Gara de Nord București, urmărește trenurile, trimite notificări push la întârzieri sau schimbări de linie și păstrează un istoric căutabil.

Live: https://tabelacfr.ddns.net

## Ce face

- **Tabelă (Carduri)** — sosiri și plecări cu ora programată, întârzierea citită, linia,
  operatorul; implicit pe telefon. Valorile lipsă apar ca „—”, nu ca 0.
- **Panou** — afișaj de gară (implicit de la 1024 px): Sosiri / Plecări / Toate, ceas,
  starea datelor (ACTUALIZAT / DATE VECHI / INDISPONIBIL), căutare, filtre (întârziere,
  operator, linie, Favorite (local)), sortare, coloane configurabile, ecran complet,
  detaliu pe tren cu link către Istoric și buton „Urmărește (notificări)”. Culorile
  întârzierii vin din `/api/config`; datele vechi trec pe gri.
- **Istoric** — ce a afișat tabela într-o zi (filtre: zi, tren, stație, interval, panou),
  cu detaliul evenimentelor și graficul întârzierii observate. Link direct:
  `#istoric?train=1636&date=2026-10-21`.
- **Urmărite** — notificări Web Push la schimbări de întârziere/linie sau la dispariția
  trenului de pe tabelă (necesită HTTPS; pe iPhone, aplicația adăugată pe ecranul principal).
- **PWA** — instalabilă, funcționează offline cu ultima tabelă (marcată „date vechi”) și o
  pagină offline cu sigla.
- **Temă** — buton în antet (și în Panou, inclusiv în ecran complet): Auto → Luminoasă →
  Întunecată; alegerea se păstrează în browser.
- **Nume canonice** — operatorul și stația citite prin OCR sunt aduse la forma cunoscută;
  o potrivire nesigură e subliniată punctat, cu titlul „citire nesigură”.

### Sigla

Originalul e în `docs/brand/logo-source.png`. Toate variantele (antet, favicon 16/32/48,
iconițe PWA 192/512 + maskable, apple-touch-icon, imaginea `og:image` 1200×630) se
regenerează cu `python scripts/make_icons.py`. La 16–32 px se folosește un decupaj
simplificat din aceeași grafică (fața trenului), pentru lizibilitate în taburi.

## Rulare (dezvoltare)

    python -m venv .venv
    .venv\Scripts\pip install -r requirements-dev.txt
    .venv\Scripts\python -m pytest

## Cerințe pentru deploy

- Tesseract 5 cu limbile `eng` și `ron` instalat pe server; dacă nu e în `PATH`,
  setați `TESSERACT_CMD` cu calea către executabil.
- Fișierul `app/ocr/digit_templates.npz` (șabloanele de cifre ale fontului tabelei)
  trebuie livrat împreună cu codul, lângă `app/ocr/digits.py`. Fără el aplicația
  pornește, dar scrie un avertisment în log și precizia pe numere/ore scade
  (rămâne doar Tesseract). Se regenerează cu
  `python -m app.ocr.digits tests/fixtures/board_1.jpg tests/fixtures/board_1.json`
  (implicit doar panoul de sosiri, ca plecările să rămână verificare independentă).

## OCR și canonicalizare

- Apelul OCR trece prin interfața `OcrEngine` (`app/ocr/engine.py`); implementarea
  folosită e `TesseractEngine` (timeout 10 s, `OcrError` la eșec). Preprocesarea și
  interpretarea rândurilor nu depind de motor: `read_board(imagine, engine=...)`.
- Operatorul și stația citite sunt aduse la forma canonică (`app/canonical.py`, potrivire
  `difflib`, prag implicit 0,82): ex. „Transferovlar” → „Transferoviar”, „CFR Calatorl” →
  „CFR Calatori”. Operatorii cunoscuți sunt în `data/operators.txt`, stațiile în
  `data/stations_seed.txt` plus cele învățate din istoric (stații văzute la cel puțin
  2 servicii). Listele conțin doar nume văzute efectiv pe tabelă — se completează manual.
- Sub prag se păstrează textul citit și rândul e marcat `uncertain` (expus în `/api/board`
  și `/api/history`). Textul brut se păstrează mereu în `operator_raw`/`station_raw`
  (schema bazei de date v3); identitatea serviciului (panou, dată, tren, oră) nu se schimbă.

## Capturi și retenție

- Schema v5 (migrare automată, fără ștergeri; din v1/v2/v3/v4): `captures` (o imagine
  nouă a tabelei: oră UTC, hash, cale relativă, dimensiuni, durata OCR, eroare,
  `processing_version`), `observations` (o linie OCR: textul brut complet, pe fiecare
  câmp text brut / valoare normalizată / încredere / dreptunghi, stare de validare
  `ok | uncertain | rejected_low_conf | incomplete`, legătura cu călătoria) și `trains`
  (catalogul numerelor de tren: `journeys` = călătorii/servicii, `observations` = citiri
  OCR utilizabile — două numere distincte; istoricul de dinainte de v5 are 0 observații).
- Fiecare imagine nouă se salvează **nemodificată** în `CAPTURE_DIR/AAAA/LL/ZZ/HHMMSS-<hash8>.jpg`
  (UTC); aceeași imagine (același hash) nu creează o captură nouă. Liniile incomplete sau
  cu încredere mică se păstrează și ele, marcate. O eroare la înregistrare nu oprește
  niciodată tabela (doar se scrie în jurnal).
- Variabile: `CAPTURE_ENABLED` (implicit 1), `CAPTURE_DIR` (implicit
  `/var/lib/tabela/captures` pe server, `data/captures` local), `CAPTURE_RETENTION_DAYS`
  (implicit 7). O dată pe zi se șterg doar **fișierele** imagine mai vechi decât retenția
  (rândurile rămân, `path` devine NULL); nu se atinge nimic în afara `CAPTURE_DIR`.
  `CAPTURE_RETENTION_DAYS=0` nu mai scrie deloc imagini. Sub `CAPTURE_MIN_FREE_MB`
  (implicit 2048) spațiu liber pe disc nu se mai scriu imagini (doar metadatele), ca baza
  de date și tabela LIVE să nu rămână fără spațiu; `GET /api/admin/stats` arată spațiul liber.
  Observațiile rămân în baza de date (~30–40 MB/zi) — de urmărit; compactarea câmpurilor
  `fields_json` vechi e planificată (fără ștergerea rândurilor).
- Catalogul `trains` se actualizează la fiecare citire a tabelei (și la fiecare captură).
- Capturile brute CFR sunt **private**: se văd doar din administrare și nu se redistribuie.
- Catalog public (fără imagini): `GET /api/trains?query=&limit=` și `GET /api/trains/{nr}`.
- Dezvoltare: `python scripts/dev_seed.py dev.db --capture-dir data/captures` adaugă și o captură.

## Administrare

- Pagina „Capturi OCR” e la `/#ocr` (nu apare în meniu): listă capturi, imagine cu
  dreptunghiurile OCR (verde ≥ 80, galben 50–79, roșu < 50), text brut vs normalizat pe
  câmp, „Copiază JSON”, plus starea sistemului (`GET /api/admin/stats`).
- Se activează cu `ADMIN_TOKEN` în `/etc/tabela.env` (minim 12 caractere; recomandat un șir aleator lung; fără el toate
  `/api/admin/*` răspund 503 „Administrare dezactivată”). Generare:
  `python -c "import secrets;print(secrets.token_urlsafe(32))"`.
- Autentificare: `Authorization: Bearer <token>` sau formularul din pagină (cookie
  HttpOnly, Secure, SameSite=Strict, 12 h; cookie-ul nu conține tokenul). 5 încercări
  greșite/minut/IP → 429 (și 30/minut în total, pentru toți); nginx limitează în plus `POST /api/admin/login` la 5/min
  (zona `tabela_admin_login` din `deploy/tabela-limits.conf`). Răspunsurile admin au
  `Cache-Control: private, no-store` și nu trec prin cache-ul service worker-ului.
  Schimbarea `ADMIN_TOKEN` invalidează toate sesiunile.

## Călătorii, statistici, stații

- **Călătorie** = o apariție a unui tren pe un panou (sosiri sau plecări din București Nord) într-o
  *zi de serviciu* (ziua orei programate; 00:05 citit la 23:58 aparține zilei următoare).
  **Tren** = număr de tren. **Observație** = o linie citită dintr-o captură OCR. Se raportează separat.
- **Întârzierea** folosită este ultima valoare CITITĂ pe tabela din București Nord, doar cu dovada
  citirii (`services.delay_read_at`, schema v6). Datele de dinainte de v6 au dovada doar din
  observații (v5); restul rămân „întârziere necunoscută” (nu 0). Un salt de peste 30 min într-un
  singur cadru se aplică doar după a doua citire identică (misread de tip „15” → „945”).
- **Rezultat final** (`app/journeys.py`): `confirmed` doar cu dispariție observată după ora estimată
  (programat + întârziere) și întârziere citită cu cel mult `FINAL_READ_MAX_GAP_MIN` înainte;
  altfel `unconfirmed` (cu motiv) sau `unknown`; `in_progress` cât e pe tabelă.
- **Statistici** (`app/stats.py`): N, medie, mediană, p90, max, % la timp (≤ prag), > 30 min; sub
  eșantionul minim procentele și p90 nu se afișează. Sosiri și plecări mereu separat.
- **API** (JSON, `format=csv` pentru export): `/api/journeys`, `/api/journeys/{id}`,
  `/api/trains/stats`, `/api/trains/{nr}/journeys`, `/api/stats`, `/api/stats/rankings`,
  `/api/stations`, `/api/stations/{nume}`, `/api/stations/{nume}/journeys`. Parametri: `prag`,
  `min`, `board`, `from`, `to` (AAAA-LL-ZZ), `doar_confirmate=1`.
- **Env** (opționale): `ON_TIME_MAX_MIN` (implicit 5), `STATS_MIN_SAMPLE` (5),
  `FINAL_READ_MAX_GAP_MIN` (15).
- Pe paginile de stație întârzierea este cea de la București Nord, nu de la stația respectivă.

## Deploy (server Ubuntu 24.04)

Live: https://tabelacfr.ddns.net (nginx + certificat Let's Encrypt, reînnoit de `certbot.timer`).

Fișiere în `deploy/`: `install.sh` (instalare idempotentă), `update.sh` (actualizare),
`tabela.service` (unit systemd), `nginx-tabela.conf` (site-ul nginx, cu liniile certbot),
`tabela-limits.conf` (zona `limit_req`, 10 cereri/s pe IP, burst 20, pe `/api/`).

Prima instalare (pe server, cu sudo):

    git clone --branch feat/app https://github.com/Andy217Ace/tabela-gara-de-nord.git /tmp/tabela
    sudo bash /tmp/tabela/deploy/install.sh feat/app   # branch obligatoriu la prima instalare

Scriptul instalează `tesseract-ocr`, `tesseract-ocr-ron`, `python3-venv`, `git`; creează
utilizatorul de sistem `tabela` (fără login), codul în `/opt/tabela/app`, venv în
`/opt/tabela/venv`, datele în `/var/lib/tabela`, fișierul de configurare `/etc/tabela.env`
(root, `chmod 600`), pornește serviciul `tabela` (un singur worker uvicorn pe
`127.0.0.1:8000` — poller-ul rulează în proces) și configurează nginx (cu `nginx -t` înainte
de reload; copia anterioară a site-ului ajunge în `/root/backup-<data>/tabela.site.bak` și
e restaurată automat dacă testul eșuează). `ufw` nu se activează: firewall-ul e NSG-ul Azure.

**La fiecare deploy crește versiunea și completează istoricul:** în `VERSION` se trece
`Beta 1.NN` cu NN mărit cu 1 (ex. `Beta 1.01` → `Beta 1.02`), iar în `CHANGELOG.md` se
adaugă sus o secțiune `## Beta 1.NN — AAAA-LL-ZZ` cu `### Adăugat` / `### Reparat` (în
română). Versiunea apare în footer (link spre ecranul „Versiuni”, `#versiuni`), în
`/api/health` (câmpul `version`) și în `/api/changelog`; `update.sh` o afișează la final.

Actualizare (după `git push` pe branch):

    sudo bash /opt/tabela/app/deploy/update.sh

face, în ordine:

1. notează commit-ul curent (PREV) și refuză clar un HEAD detașat (dați branch-ul explicit);
2. `git fetch` + checkout pe branch, apoi `pip install -r requirements.txt` — dacă pip eșuează,
   pune înapoi codul vechi și **nu** repornește serviciul;
3. completează `/etc/tabela.env` cu setările noi lipsă (ex. `LAST_IMAGE_PATH`, `CAPTURE_DIR`)
   și creează `CAPTURE_DIR` (proprietar `tabela`); `ADMIN_TOKEN` se pune manual (secret);
4. dacă noul cod are o versiune de schemă mai mare decât baza de date (`PRAGMA user_version`),
   face întâi un backup online SQLite (`sqlite3 .backup`) în `/var/lib/tabela/backups/`
   (se păstrează ultimele 5);
5. repornește și așteaptă `/api/health` (max. 3 minute); dacă nu devine sănătos, face
   **rollback** automat la PREV pe branch-ul inițial (checkout, pip install, restart,
   așteaptă) și iese cu cod 1.

Poarta de sănătate implicită (`HEALTH_MODE=strict`) cere `"ok":true`, adică aplicația a citit
tabela CFR recent. Dacă CFR însuși nu răspunde, poarta nu poate trece (scriptul avertizează
înainte); pentru o redistribuire de urgență: `sudo HEALTH_MODE=up bash .../update.sh <branch>`
(ajunge HTTP 200 de la `/api/health`). Scriptul rulează dintr-o copie temporară a lui însuși
(checkout-ul îl înlocuiește). Simularea lui (git temporar, comenzi false) e în
`tests/test_update_sh.py`.

**Restaurarea bazei de date** dintr-un backup (baza e în modul WAL — nu copiați fișierul peste
o bază deschisă și nu lăsați fișierele `-wal`/`-shm` vechi lângă ea):

    sudo systemctl stop tabela && \
    sudo rm -f /var/lib/tabela/tabela.db-wal /var/lib/tabela/tabela.db-shm && \
    sudo install -o tabela -g tabela -m 640 <backup.db> /var/lib/tabela/tabela.db && \
    sudo systemctl start tabela

După un rollback de cod de la o versiune care a migrat schema, codul vechi ignoră coloanele
noi; restaurarea de mai sus e necesară doar dacă vreți și datele de dinainte de migrare.

`install.sh` fără argument rămâne pe branch-ul deja scos în `/opt/tabela/app` (ca
`update.sh`); la prima instalare branch-ul e obligatoriu. Schimbările din
`deploy/nginx-tabela.conf`, `tabela-limits.conf` sau pachetele apt se aplică rulând din nou
`install.sh <branch>` (idempotent; nu regenerează cheile VAPID, iar dacă lipsește doar cheia
publică o derivă din cea privată).

### Primul deploy al valului 1 (schema v3) — procedură

Serverul are încă `update.sh`/`install.sh` vechi: **nu le rulați** (cel vechi nu face backup și
poate fi stricat de propriul `git checkout`). Pași (cu sudo, `B` = branch-ul de livrat):

1. Verificări: `curl -s http://127.0.0.1:8000/api/health` (ok=true), `df -h /var/lib/tabela /opt`,
   `git -C /opt/tabela/app status --porcelain` (gol); notați `git -C /opt/tabela/app rev-parse HEAD`.
2. Backup manual online + verificare:

       sudo install -d -m 700 /root/tabela-predeploy
       sudo /opt/tabela/venv/bin/python -c 'import sqlite3; s=sqlite3.connect("file:/var/lib/tabela/tabela.db?mode=ro", uri=True); d=sqlite3.connect("/root/tabela-predeploy/tabela.db"); s.backup(d); print(d.execute("PRAGMA integrity_check").fetchone()[0], d.execute("PRAGMA user_version").fetchone()[0], d.execute("SELECT COUNT(*) FROM services").fetchone()[0])'

   (trebuie să afișeze `ok 2 <număr servicii>`).
3. Scriptul NOU, rulat din `/tmp`:

       sudo git -C /opt/tabela/app fetch origin "$B"
       sudo git -C /opt/tabela/app show "origin/$B:deploy/update.sh" > /tmp/update-new.sh
       sudo bash /tmp/update-new.sh "$B"

4. Verificare: `PRAGMA user_version` = 3 și aceleași numere de servicii/evenimente (cu
   `mode=ro` ca mai sus), `/api/health` ok, `/api/board` are `uncertain` și `delay_read`.
5. `sudo bash /opt/tabela/app/deploy/install.sh "$B"` (explicit: pachetul sqlite3 și
   `limit_req_log_level`).
6. Rollback (dacă e nevoie): doar cod — `git -C /opt/tabela/app checkout -B <branch-vechi>
   <SHA notat>`, `/opt/tabela/venv/bin/pip install -r /opt/tabela/app/requirements.txt`,
   `systemctl restart tabela`; baza de date — restaurarea de mai sus cu
   `/root/tabela-predeploy/tabela.db`.

Trecerea pe `main` după merge-ul PR-ului: `sudo bash /opt/tabela/app/deploy/update.sh main`
(de atunci `update.sh` fără argument rămâne pe `main`).

- Log-uri: `journalctl -u tabela -f` (aplicația), `/var/log/nginx/access.log` (cererile;
  `/api/follows` nu se loghează, pentru că endpoint-ul push e în query string).
  Atenție: o cerere respinsă de `limit_req` (429) poate scrie totuși linia cererii (cu query
  string-ul) în `/var/log/nginx/error.log`. De aceea `tabela-limits.conf` setează
  `limit_req_log_level warn`, sub nivelul implicit `error` al `error_log` — nu coborâți
  nivelul `error_log` la `warn`/`info` fără să țineți cont de asta.
- Configurare UI: `GET /api/config` (pragurile de culoare `DELAY_THRESHOLDS="5,15,30"` din env,
  `refresh_s`, `stale_after_s`) — sursa unică pentru intervalul de reîmprospătare și culori.
- Date: `/var/lib/tabela/tabela.db` (SQLite, istoric + abonări) și
  `/var/lib/tabela/last.jpg` (ultima imagine a tabelei, utilă la depanarea OCR).
- Variabile în `/etc/tabela.env`: `DB_PATH`, `LAST_IMAGE_PATH`, `POLLER_ENABLED`,
  `VAPID_SUBJECT`, `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY`, `CAPTURE_DIR`, `ADMIN_TOKEN`
  (opțional `TESSERACT_CMD`, `CAPTURE_RETENTION_DAYS`, `WEATHER_*`); model fără valori
  reale în `.env.example`.
- Chei VAPID: generate o singură dată de `install.sh` (dacă lipsesc din `/etc/tabela.env`);
  nu se regenerează niciodată, altfel toate abonările push existente devin invalide.
  Cheia privată nu iese din `/etc/tabela.env`; subiectul VAPID e URL-ul site-ului.
- Politețe față de CFR: aplicația cere imaginea tabelei sincronizat cu momentul în care se
  schimbă (de obicei 1–4 cereri/minut, plafon fix de 10/minut, backoff la erori) și se
  identifică prin User-Agent. Nu rulați mai multe instanțe/workeri pe aceeași sursă.

## Meteo

Lângă ceas (în antetul vizualizării Carduri și în bara de titlu a Panoului) apare un widget
mic cu vremea din București: pictogramă, temperatură, „se simte", vânt; la apăsare/hover un
popover cu detalii (precipitații, ora observației, sursa).

- Serverul (nu browserul — CSP rămâne `connect-src 'self'`) cere blocul `current` de la
  Open-Meteo (`temperature_2m, precipitation, weather_code, wind_speed_10m,
  wind_direction_10m, apparent_temperature`) la fiecare 15 minute, într-o sarcină proprie,
  independentă de poller-ul CFR: o eroare meteo nu afectează tabela și nici `ok` din
  `/api/health` (care primește doar `weather_age_s`). Backoff la erori (5 → 30 min), niciodată
  mai mult de o cerere la 5 minute, nici după repornire.
- Etichetare onestă: valorile `current` sunt **date de model** pentru celula de grilă a
  coordonatelor, nu măsurătorile unei stații meteo. Se salvează cu `kind = model_current` și
  se afișează „Condiții curente (model Open-Meteo)". Valoare lipsă = `NULL`/„—", niciodată 0
  (0,0 mm precipitații e o valoare reală). Peste 45 de minute datele apar gri, „date vechi".
- Stocare: tabelul `weather_observations` (schema v4, migrare aditivă), un rând per oră de
  observație (UTC, `observed_at` unic), istoric permanent (~96 rânduri/zi) pentru analiza
  „Meteo și trenuri" din Etapa G. API: `GET /api/weather`; `GET /api/config` → `weather`.
- Variabile (opționale) în `/etc/tabela.env`: `WEATHER_ENABLED` (implicit `1`; `0` oprește
  serviciul și ascunde widgetul), `WEATHER_INTERVAL_S` (implicit `900`, minim `300`),
  `WEATHER_LAT` / `WEATHER_LON` (implicit `44.4323` / `26.1063`), `WEATHER_URL` (implicit
  `https://api.open-meteo.com/v1/forecast`).
- Licență și atribuire: datele meteo sunt de la [Open-Meteo.com](https://open-meteo.com/),
  sub licența **CC BY 4.0** (API-ul gratuit este pentru uz necomercial); atribuirea apare în
  popover, în subsolul paginii și în creditul Panoului (vizibil și în ecran complet).

## Atribuire

Date preluate de la CFR (cfr.ro) — proiect independent, neafiliat CFR. Tabela oficială: https://cfr.ro. © 2026 Andy217Ace.
Meteo: Open-Meteo.com (CC BY 4.0), valori de model.

Licență: MIT (vezi `LICENSE`).
