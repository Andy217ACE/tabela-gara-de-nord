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

Actualizare (după `git push` pe branch):

    sudo bash /opt/tabela/app/deploy/update.sh

face, în ordine:

1. notează commit-ul curent (PREV) și refuză clar un HEAD detașat (dați branch-ul explicit);
2. `git fetch` + checkout pe branch, apoi `pip install -r requirements.txt` — dacă pip eșuează,
   pune înapoi codul vechi și **nu** repornește serviciul;
3. completează `/etc/tabela.env` cu setările noi lipsă (ex. `LAST_IMAGE_PATH`);
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
  `VAPID_SUBJECT`, `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY` (opțional `TESSERACT_CMD`).
- Chei VAPID: generate o singură dată de `install.sh` (dacă lipsesc din `/etc/tabela.env`);
  nu se regenerează niciodată, altfel toate abonările push existente devin invalide.
  Cheia privată nu iese din `/etc/tabela.env`; subiectul VAPID e URL-ul site-ului.
- Politețe față de CFR: aplicația cere imaginea tabelei sincronizat cu momentul în care se
  schimbă (de obicei 1–4 cereri/minut, plafon fix de 10/minut, backoff la erori) și se
  identifică prin User-Agent. Nu rulați mai multe instanțe/workeri pe aceeași sursă.

## Atribuire

Date preluate de la CFR (cfr.ro) — proiect independent, neafiliat CFR. Tabela oficială: https://cfr.ro. © 2026 Andy217Ace.

Licență: MIT (vezi `LICENSE`).
