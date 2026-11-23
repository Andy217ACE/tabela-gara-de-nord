<p align="center"><img src="web/icons/logo.png" alt="Tabela Gara de Nord logo" width="96" height="96"></p>

**English** · [Română](README.ro.md)

# Tabela Gara de Nord

A web application (PWA) that uses classic OCR (OpenCV + Tesseract, no AI) to read the arrivals/departures board at Gara de Nord in Bucharest, tracks trains, sends push notifications on delays or platform changes, and keeps a searchable history.

Live: https://tabelacfr.ddns.net

Status: **Beta** — versions and notes in [Releases](https://github.com/Andy217ACE/tabela-gara-de-nord/releases)
and in `CHANGELOG.md`. The data is read by OCR from the CFR webcam image and may contain errors;
values that could not be read appear as "—", not as 0.

## Detailed documentation

The pages below describe each subsystem in detail, with Mermaid diagrams (rendered directly on GitHub).
The README below stays a summary; the pages are the complete source. The English pages are in
[docs/en/](docs/en/); the Romanian originals are in `docs/`.

| Page | What it covers |
|---|---|
| [Architecture](docs/en/arhitectura.md) | Processes, the modules in `app/`, systemd units, nginx, the data path on the server |
| [Data and database schema](docs/en/date-si-schema.md) | Every table and column, migrations v0–v9, ingest, service identity, retention, archives and restore |
| [API](docs/en/api.md) | All public and admin routes: parameters, responses, errors, cache, limits, the security model |
| [Interface](docs/en/interfata.md) | Pages and routes (#…), navigation, theme, service worker, CSP, charts, accessibility |
| [OCR](docs/en/ocr.md) | The reading pipeline step by step, the real constants, delay rules, measurement, open problems |
| [Captures and privacy](docs/en/capturi-si-confidentialitate.md) | What a capture is, retention, what git ignores, the privacy rule, personal data |
| [Statistics, journeys, quality](docs/en/statistici-calatorii-calitate.md) | Catalog, journeys, stations, formulas and thresholds, prediction, consensus, data quality |
| [Weather](docs/en/meteo.md) | The Open-Meteo source, storage, frequency, failures |
| [Administration and operations](docs/en/administrare-operare.md) | The #admin page, corrections, merges, purge, backup and restore, Telegram, push, watchdog, runbooks |
| [Deploy and configuration](docs/en/deploy-si-configurare.md) | Environment variables, install.sh, update.sh, systemd, nginx, certificates, the release process, rollback |
| [Testing](docs/en/testare.md) | How to run the suite, the test layers, tests that depend on captures, how to add a test |
| [Admin key rotation](docs/en/admin-rotatie-cheie.md) | Steps for changing `ADMIN_TOKEN` |
| [Glossary](docs/en/glosar.md) | Romanian terms used in the code and data, with English equivalents |

## What it does

- **Board (Cards)** — arrivals and departures with the scheduled time, the delay as read, the platform,
  the operator; the default on phones. Missing values appear as "—", not as 0.
- **Panel** — station-style display (default from 1024 px): Arrivals / Departures / All, clock,
  data status (UP TO DATE / STALE DATA / UNAVAILABLE), search, filters (delay,
  operator, platform, Favorites (local)), sorting, configurable columns, full screen,
  per-train detail with a link to History and a "Follow (notifications)" button. Delay colors
  come from `/api/config`; stale data turns grey.
- **History** — what the board showed on a given day (filters: day, train, station, time range, panel),
  with the event details and the chart of the observed delay. Direct link:
  `#istoric?train=1636&date=2026-10-21`.
- **Statistics** — punctuality, delays, rankings and heat maps over a period, with the number of
  journeys (N) and the minimum sample shown; CSV export. History can be viewed across all days.
- **Followed** — Web Push notifications on delay/platform changes or when the train
  disappears from the board (requires HTTPS; on iPhone, the app added to the home screen).
- **PWA** — installable, works offline with the last board (marked "stale data") and an
  offline page with the logo.
- **Theme** — button in the header (and in the Panel, including full screen): Auto → Light →
  Dark; the choice is kept in the browser.
- **Canonical names** — the operator and station read by OCR are brought to the known form;
  an uncertain match is underlined with dots, with the title "uncertain reading".

### Page graphics (Beta 1.26)

The pages outside the Board (History, Followed, Trains, Train, Statistics, Rankings, Stations,
Station, Versions) use a shared visual layer: `web/ui2.css` + `web/ui2.js` (donut/pie, counting
numbers, proportion bars, mini charts, loading skeletons, transitions). **No external
libraries**: the charts are SVG + CSS drawn by our own code, to respect the security policy
(`script-src 'self'`, no inline styles), to follow the light/dark themes, to have an accessible
alternative (legend, table, CSV) and not to grow the precache with a library.
If one is added in the future, it goes under `web/vendor/<name>-<version>/` with its license file,
is loaded on demand (only on the pages that use it) and does **not** go into `SHELL` in `sw.js`.
The Board (Cards / Panel / Full screen) does not use this layer.

**Beta 1.28 (UI v3):** the interactive chart layers (a shared tooltip for bars / lines / columns / heat maps,
a legend with hover and toggling, full screen with the table alongside, "Copy link", section chips, calendar,
data sliding when a filter changes) are in `web/charts3.js` + `web/charts3.css`, **loaded on demand**
(`App.ui2.charts()`) only on Statistics, Train, Rankings and Station, so outside the `SHELL` in `sw.js`.
Again without a library: a tooltip or chart library would require inline styles / canvas (CSP, themes, accessibility
on every value) and would be heavier than the ~18 KB gzip of our own code.

### The logo

The original is in `docs/brand/logo-source.png`. All variants (header, favicon 16/32/48,
PWA icons 192/512 + maskable, apple-touch-icon, the 1200×630 `og:image`) are
regenerated with `python scripts/make_icons.py`. At 16–32 px a simplified crop of the
same artwork is used (the train's face), for legibility in tabs.

## Running (development)

    python -m venv .venv
    .venv\Scripts\pip install -r requirements-dev.txt
    .venv\Scripts\python -m pytest

## Deploy requirements

- Tesseract 5 with the `eng` and `ron` languages installed on the server; if it is not in `PATH`,
  set `TESSERACT_CMD` to the path of the executable.
- The file `app/ocr/digit_templates.npz` (the digit templates of the board's font)
  must be shipped together with the code, next to `app/ocr/digits.py`. Without it the application
  starts, but writes a warning to the log and the accuracy on numbers/times drops
  (only Tesseract remains). It is regenerated with
  `python -m app.ocr.digits tests/fixtures/board_1.jpg tests/fixtures/board_1.json`
  (by default only the arrivals panel, so that departures stay an independent check).

## OCR and canonicalization

- The OCR call goes through the `OcrEngine` interface (`app/ocr/engine.py`); the implementation
  in use is `TesseractEngine` (10 s timeout, `OcrError` on failure). Preprocessing and
  row interpretation do not depend on the engine: `read_board(image, engine=...)`.
- The operator and station read are brought to the canonical form (`app/canonical.py`, `difflib`
  matching, default threshold 0.82): e.g. "Transferovlar" → "Transferoviar", "CFR Calatorl" →
  "CFR Călători" (the official name; board forms such as "CFR Calatori" are aliases, and a softer score 0.65-0.82 is accepted with a margin of at least 0.10 over the runner-up operator). The known operators are in `data/operators.txt` (`Official name | alias`), the stations in
  `data/stations_seed.txt` plus those learned from history (stations seen on at least
  2 distinct trains, on at least 2 distinct service days). The lists contain only names actually seen on the board — they are completed by hand.
- Below the threshold the text as read is kept and the row is marked `uncertain` (exposed in `/api/board`
  and `/api/history`). The raw text is always kept in `operator_raw`/`station_raw`
  (database schema v3); the service identity (panel, date, train, time) does not change.

## 12 rows per panel (4 × 3) and re-reading unread rows

- The CFR board has 4 blue groups of 3 rows on each panel. The text bands
  found by projection are checked per group (`preprocess.structured_bands`): a
  group with a number of rows other than 3 gets its fixed grid (derived from the image, not
  from the text), so a weak or empty row does not disappear and does not stick to its neighbor.
- A row with text but without a readable type/number/time is automatically re-read only on the
  type, number and time columns, with alternative preprocessing (`preprocess.VARIANTS`: without the
  vertical reflection lines, lower/higher threshold, ×4, adaptive threshold, wider crop), until it
  succeeds or the frame budget runs out (`OCR_FRAME_BUDGET_S`, default 8 s, re-reads
  included). A panel with more than 4 unread rows is considered a broken frame and is not
  re-read (trains are not invented).
- Rows stay `necitit` (unread) (not 0, not a guessed train); a row without text is `rând gol` (empty row).
  The processing version of each observation (e.g. `ocr-tess-grid-5`) has suffixes:
  `+empty`, `+unread`, `+retry:<variant>:<attempts>`.
- `/api/health` → `ocr`: rows per panel from the last frame, re-reads, duration, and
  over the last 60 frames how many had 12/12. The "OCR captures" page shows "S 12 · P 11"
  and the re-reads for each capture.

## Captures and retention

- Schema v5 (automatic migration, no deletions; from v1/v2/v3/v4): `captures` (a new
  image of the board: UTC time, hash, relative path, dimensions, OCR duration, error,
  `processing_version`), `observations` (one OCR line: the full raw text, per
  field raw text / normalized value / confidence / rectangle, validation state
  `ok | uncertain | rejected_low_conf | incomplete`, the link to the journey) and `trains`
  (the catalog of train numbers: `journeys` = journeys/services, `observations` = usable OCR
  readings — two distinct numbers; history from before v5 has 0 observations).
- Every new image is saved **unmodified** to `CAPTURE_DIR/YYYY/MM/DD/HHMMSS-<hash8>.jpg`
  (UTC); the same image (same hash) does not create a new capture. Incomplete or
  low-confidence lines are kept too, marked. An error while recording never
  stops the board (it is only written to the log).
- Variables: `CAPTURE_ENABLED` (default 1), `CAPTURE_DIR` (default
  `/var/lib/tabela/captures` on the server, `data/captures` locally), `CAPTURE_RETENTION_DAYS`
  (default 7). Once a day only the image **files** older than the retention are deleted
  (the rows stay, `path` becomes NULL); nothing outside `CAPTURE_DIR` is touched.
  `CAPTURE_RETENTION_DAYS=0` stops writing images altogether. Below `CAPTURE_MIN_FREE_MB`
  (default 2048) of free disk space no more images are written (only the metadata), so that the database
  and the LIVE board do not run out of space; `GET /api/admin/stats` shows the free space.
  Observations stay in the database (~30–40 MB/day) — to be watched; compacting the old
  `fields_json` fields is planned (without deleting rows).
- The `trains` catalog is updated on every board read (and on every capture).
- The raw CFR captures are **private**: they are visible only from administration and are not redistributed.
- Public catalog (no images): `GET /api/trains?query=&limit=` and `GET /api/trains/{nr}`.
- Development: `python scripts/dev_seed.py dev.db --capture-dir data/captures` also adds a capture.

## Administration

- The "OCR captures" page is at `/#ocr` (it does not appear in the menu): list of captures, image with
  the OCR rectangles (green ≥ 80, yellow 50–79, red < 50), raw vs normalized text per
  field, "Copy JSON", plus the system state (`GET /api/admin/stats`).
- It is enabled with `ADMIN_TOKEN` in `/etc/tabela.env` (at least 12 characters; a long random string is recommended; without it all
  `/api/admin/*` answer 503 "Administration disabled"). Generation:
  `python -c "import secrets;print(secrets.token_urlsafe(32))"`.
- Authentication: `Authorization: Bearer <token>` or the form on the page (cookie
  HttpOnly, Secure, SameSite=Strict, 12 h; the cookie does not contain the token). 5 wrong
  attempts/minute/IP → 429 (and 30/minute in total, for everyone); nginx additionally limits `POST /api/admin/login` to 5/min
  (zone `tabela_admin_login` in `deploy/tabela-limits.conf`). Admin responses have
  `Cache-Control: private, no-store` and do not go through the service worker's cache.
  Changing `ADMIN_TOKEN` invalidates all sessions.

## Journeys, statistics, stations

- **Journey** = one appearance of a train on a panel (arrivals or departures at București Nord) on one
  *service day* (the day of the scheduled time; 00:05 read at 23:58 belongs to the next day).
  **Train** = a train number. **Observation** = one line read from an OCR capture. They are reported separately.
- The **delay** used is the last value READ on the board at București Nord, only with proof
  of the reading (`services.delay_read_at`, schema v6). Data from before v6 has proof only from
  observations (v5); the rest stay "unknown delay" (not 0). A jump of over 30 min in a
  single frame is applied only after the second identical reading (a misread of the "15" → "945" kind).
- **Final result** (`app/journeys.py`): `confirmed` only with a disappearance observed after the estimated time
  (scheduled + delay) and a delay read at most `FINAL_READ_MAX_GAP_MIN` before;
  otherwise `unconfirmed` (with a reason) or `unknown`; `in_progress` while it is on the board.
- **Statistics** (`app/stats.py`): N, mean, median, p90, max, % on time (≤ threshold), > 30 min; below
  the minimum sample the percentages and p90 are not shown. Arrivals and departures always separate.
- **API** (JSON, `format=csv` for export): `/api/journeys`, `/api/journeys/{id}`,
  `/api/trains/stats`, `/api/trains/{nr}/journeys`, `/api/stats`, `/api/stats/rankings`,
  `/api/stations`, `/api/stations/{name}`, `/api/stations/{name}/journeys`. Parameters: `prag`,
  `min`, `board`, `from`, `to` (YYYY-MM-DD), `doar_confirmate=1`. And: `/api/stats/overview` (everything the
  Statistics page shows), `/api/stats/seasons` (comparison by season and weather), `/api/export/history.csv`
  (CSV export of the history over a range) and `/api/system` (system state; details only for admin).
  The full list, with parameters, responses and errors: [docs/en/api.md](docs/en/api.md).
- **History across all days**: `/api/history?all=1` = all trains, all days;
  `train=N` restricts to one train (optional `date`,
  `station`, `from`/`to` HH:MM, `board`, `limit` 1–200, `cursor` from the previous response,
  `min`, `prag`, `doar_confirmate`). Journeys, newest first, without ghosts; the low-quality
  period appears marked (`low_quality`) and does not enter the summary. `total`, `period` and
  `summary` (per panel, only delays read) describe the whole result, not just the page (without
  a train, `summary`/`quality` are computed at most once every 60 s, `total`/`period` always
  live). The History page starts with no day chosen = all days. Without
  `all=1`, `/api/history` stays on a single day (`date`, default today).
- **Env** (optional): `ON_TIME_MAX_MIN` (default 5), `STATS_MIN_SAMPLE` (5),
  `FINAL_READ_MAX_GAP_MIN` (15).
- On the station pages the delay is the one at București Nord, not at the station in question.

## Data quality (schema v7)

What is read from the board stays in the database exactly as it was read. The quality verdicts
live in separate tables (`app/quality.py`, each rule is tested on real cases):

- **Validation at read time:** a delay change is applied at the second consecutive
  identical reading. A large jump (at least 60 minutes, at over 100 minutes) is applied at the
  third. A value that looks like the "+" sign read as a digit (25 → 425) is applied only at the fifth.
  For the platform 2 readings are needed; for confused digits (5/6, 1/4/11/14, 3/8), 3.
  A train is considered gone (GONE) after 3 missing readings. If it comes back within 10 minutes,
  no new appearance is recorded.
- **Ghosts** (`service_quality.ghost`): a service seen for less than 2 minutes, or a
  one-character variant of another, longer-lived service (with at most one observation).
  A minority variant of a row that OCR reads alternately is also a ghost:
  the real train must have at least double its observations. The readings of such a row
  go to the majority service. Renaming a service is done by vote: at least 3 readings
  and 70% of the last 10.
  Ghosts do not appear in the Panel, History, catalog, statistics or station pages.
- **The low-quality period** (`quality_periods`, 21.10.2026 00:00–11:31) is excluded
  by default from the statistics. To include it: `STATS_INCLUDE_LOW_QUALITY=1`.
- **Retroactive correction** (idempotent; run with the service stopped):

      sudo systemctl stop tabela
      sudo -u tabela env DB_PATH=/var/lib/tabela/tabela.db /opt/tabela/venv/bin/python -m app.quality --dry-run
      sudo -u tabela env DB_PATH=/var/lib/tabela/tabela.db /opt/tabela/venv/bin/python -m app.quality
      sudo systemctl start tabela

  The `python` commands are run from `/opt/tabela/app`.
- **Removing ghosts** (optional, the administrator's decision): `scripts/purge_ghosts.py`.
  By default it does only a dry run, which prints the number of rows and 20 examples. With
  `--apply --backup-dir DIR` it first makes a full copy of the database, then reversibly archives
  the rows in `purged_rows`. With `--restore` it puts them back.

## Deploy (Ubuntu 24.04 server)

Live: https://tabelacfr.ddns.net (nginx + Let's Encrypt certificate, renewed by `certbot.timer`).

Files in `deploy/`: `install.sh` (idempotent install), `update.sh` (update),
`tabela.service` (systemd unit), `nginx-tabela.conf` (the nginx site, with the certbot lines),
`tabela-limits.conf` (the `limit_req` zone, 10 requests/s per IP, burst 20, on `/api/`).

First install (on the server, with sudo):

    git clone --branch feat/app https://github.com/Andy217Ace/tabela-gara-de-nord.git /tmp/tabela
    sudo bash /tmp/tabela/deploy/install.sh feat/app   # branch obligatoriu la prima instalare

The script installs `tesseract-ocr`, `tesseract-ocr-ron`, `python3-venv`, `git`, `curl`, `sqlite3`; creates the
system user `tabela` (no login), the code in `/opt/tabela/app`, the venv in
`/opt/tabela/venv`, the data in `/var/lib/tabela`, the configuration file `/etc/tabela.env`
(root, `chmod 600`), starts the `tabela` service (a single uvicorn worker on
`127.0.0.1:8000` — the poller runs in-process) and configures nginx (with `nginx -t` before
the reload; the previous copy of the site ends up in `/root/backup-<date>/tabela.site.bak` and
is restored automatically if the test fails). `ufw` is not enabled by the script. The production server is now the home server, not an Azure machine,
  and its effective firewall is not described in the repo: to be checked on the server (see
  [docs/en/deploy-si-configurare.md](docs/en/deploy-si-configurare.md), section 7).

**On every deploy, bump the version and fill in the history:** in `VERSION` put
`Beta 1.NN` with NN increased by 1 (e.g. `Beta 1.01` → `Beta 1.02`), and in `CHANGELOG.md`
add at the top a section `## Beta 1.NN — YYYY-MM-DD` with `### Adăugat` / `### Reparat` (in
Romanian, with an English twin as an `### English` sub-heading). The version appears in the footer (a link to the "Versions" screen, `#versiuni`), in
`/api/health` (the `version` field) and in `/api/changelog`; `update.sh` prints it at the end.

Update (after `git push` on the branch):

    sudo bash /opt/tabela/app/deploy/update.sh

it does, in order:

1. notes the current commit (PREV) and clearly refuses a detached HEAD (give the branch explicitly);
2. `git fetch` + checkout on the branch, then `pip install -r requirements.txt` — if pip fails,
   it puts the old code back and does **not** restart the service;
3. completes `/etc/tabela.env` with the missing new settings (e.g. `LAST_IMAGE_PATH`, `CAPTURE_DIR`)
   and creates `CAPTURE_DIR` (owner `tabela`); `ADMIN_TOKEN` is set manually (secret);
4. if the new code has a higher schema version than the database (`PRAGMA user_version`),
   it first makes an online SQLite backup (`sqlite3 .backup`) in `/var/lib/tabela/backups/`
   (the last 5 are kept);
5. restarts and waits for `/api/health` (max. 3 minutes); if it does not become healthy, it does an
   automatic **rollback** to PREV on the original branch (checkout, pip install, restart,
   wait) and exits with code 1.

The default health gate (`HEALTH_MODE=strict`) requires `"ok":true`, i.e. the application has read
the CFR board recently. If CFR itself does not respond, the gate cannot pass (the script warns
beforehand); for an emergency redeploy: `sudo HEALTH_MODE=up bash .../update.sh <branch>`
(an HTTP 200 from `/api/health` is enough). The script runs from a temporary copy of itself
(the checkout replaces it). Its simulation (temporary git, fake commands) is in
`tests/test_update_sh.py`.

**Restoring the database** from a backup (the database is in WAL mode — do not copy the file over
an open database and do not leave old `-wal`/`-shm` files next to it):

    sudo systemctl stop tabela && \
    sudo rm -f /var/lib/tabela/tabela.db-wal /var/lib/tabela/tabela.db-shm && \
    sudo install -o tabela -g tabela -m 640 <backup.db> /var/lib/tabela/tabela.db && \
    sudo systemctl start tabela

After a code rollback from a version that migrated the schema, the old code ignores the new
columns; the restore above is needed only if you also want the data from before the migration.

`install.sh` without an argument stays on the branch already checked out in `/opt/tabela/app` (like
`update.sh`); on the first install the branch is mandatory. Changes to
`deploy/nginx-tabela.conf`, `tabela-limits.conf` or the apt packages are applied by running
`install.sh <branch>` again (idempotent; it does not regenerate the VAPID keys, and if only the
public key is missing it derives it from the private one).

### The first deploy of wave 1 (schema v3) — procedure

The server still has the old `update.sh`/`install.sh`: **do not run them** (the old one does not make a backup and
can be broken by its own `git checkout`). Steps (with sudo, `B` = the branch to deliver):

1. Checks: `curl -s http://127.0.0.1:8000/api/health` (ok=true), `df -h /var/lib/tabela /opt`,
   `git -C /opt/tabela/app status --porcelain` (empty); note `git -C /opt/tabela/app rev-parse HEAD`.
2. Manual online backup + verification:

       sudo install -d -m 700 /root/tabela-predeploy
       sudo /opt/tabela/venv/bin/python -c 'import sqlite3; s=sqlite3.connect("file:/var/lib/tabela/tabela.db?mode=ro", uri=True); d=sqlite3.connect("/root/tabela-predeploy/tabela.db"); s.backup(d); print(d.execute("PRAGMA integrity_check").fetchone()[0], d.execute("PRAGMA user_version").fetchone()[0], d.execute("SELECT COUNT(*) FROM services").fetchone()[0])'

   (it must print `ok 2 <number of services>`).
3. The NEW script, run from `/tmp`:

       sudo git -C /opt/tabela/app fetch origin "$B"
       sudo git -C /opt/tabela/app show "origin/$B:deploy/update.sh" > /tmp/update-new.sh
       sudo bash /tmp/update-new.sh "$B"

4. Verification: `PRAGMA user_version` = 3 and the same numbers of services/events (with
   `mode=ro` as above), `/api/health` ok, `/api/board` has `uncertain` and `delay_read`.
5. `sudo bash /opt/tabela/app/deploy/install.sh "$B"` (explicitly: the sqlite3 package and
   `limit_req_log_level`).
6. Rollback (if needed): code only — `git -C /opt/tabela/app checkout -B <old-branch>
   <noted SHA>`, `/opt/tabela/venv/bin/pip install -r /opt/tabela/app/requirements.txt`,
   `systemctl restart tabela`; database — the restore above with
   `/root/tabela-predeploy/tabela.db`.

Switching to `main` after the PR is merged: `sudo bash /opt/tabela/app/deploy/update.sh main`
(from then on `update.sh` without an argument stays on `main`).

- Logs: `journalctl -u tabela -f` (the application), `/var/log/nginx/access.log` (requests;
  `/api/follows` is not logged, because the push endpoint is in the query string).
  Note: a request rejected by `limit_req` (429) may still write the request line (with the query
  string) to `/var/log/nginx/error.log`. That is why `tabela-limits.conf` sets
  `limit_req_log_level warn`, below the default `error` level of `error_log` — do not lower the
  `error_log` level to `warn`/`info` without taking this into account.
- UI configuration: `GET /api/config` (the color thresholds `DELAY_THRESHOLDS="5,15,30"` from env,
  `refresh_s`, `stale_after_s`) — the single source for the refresh interval and colors.
- Data: `/var/lib/tabela/tabela.db` (SQLite, history + subscriptions) and
  `/var/lib/tabela/last.jpg` (the last image of the board, useful when debugging OCR).
- Variables in `/etc/tabela.env`: `DB_PATH`, `LAST_IMAGE_PATH`, `POLLER_ENABLED`,
  `VAPID_SUBJECT`, `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY`, `CAPTURE_DIR`, `ADMIN_TOKEN`
  (optionally `TESSERACT_CMD`, `CAPTURE_RETENTION_DAYS`, `WEATHER_*`, `TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_CHAT_ID`, `TELEGRAM_STATE_PATH`); a template without real values
  in `.env.example`.
- VAPID keys: generated once by `install.sh` (if missing from `/etc/tabela.env`);
  never regenerated, otherwise all existing push subscriptions become invalid.
  The private key does not leave `/etc/tabela.env`; the VAPID subject is the site's URL.
- Politeness toward CFR: the application requests the board image synchronized with the moment it
  changes (usually 1–4 requests/minute, a fixed cap of 10/minute, backoff on errors) and
  identifies itself through the User-Agent. Do not run several instances/workers against the same source.

## Weather

Next to the clock (in the header of the Cards view and in the title bar of the Panel) a small
widget with the weather in Bucharest appears: an icon by `weather_code` (day/night variant by `is_day`),
temperature and "feels like"; on press/hover a popover with details: humidity, pressure (hPa),
wind (speed + direction in words, e.g. "SW", + gusts), precipitation (the total; rain / showers
/ snow only when > 0; 0.0 mm is a real value), an SVG chart of the temperature over the
next 24 h with minimum, maximum and the "now" marker, the observation time and the source.

- The server (not the browser — CSP stays `connect-src 'self'`) makes **a single request** to
  Open-Meteo: `current=temperature_2m,relative_humidity_2m,apparent_temperature,is_day,
  precipitation,rain,showers,snowfall,weather_code,surface_pressure,wind_speed_10m,
  wind_direction_10m,wind_gusts_10m` + `hourly=temperature_2m`, with `timezone=UTC` (the same as
  the storage) and `forecast_days=2`, every 15 minutes, in its own task,
  independent of the CFR poller: a weather error does not affect the board nor the `ok` in
  `/api/health` (which receives only `weather_age_s`). Backoff on errors (5 → 30 min), never
  more than one request every 5 minutes, not even after a restart.
- Honest labeling: the `current` values are **model data** for the grid cell of the
  coordinates, not the measurements of a weather station. They are saved with `kind = model_current` and
  displayed as "Current conditions (Open-Meteo model)". Missing value = `NULL`/"—", never 0
  (0.0 mm precipitation is a real value). After 45 minutes the data appears grey, "stale data".
- Storage: the `weather_observations` table (schema v4; **schema v8** adds, additively and nullable,
  `relative_humidity_pct, is_day, rain_mm, showers_mm, snowfall_cm, surface_pressure_hpa,
  wind_gusts_kmh, hourly_json`; old rows stay untouched, with `NULL` in the new columns),
  one row per observation (every 15 minutes, UTC, unique `observed_at`), permanent history (~96 rows/day)
  for the "Weather and trains" analysis. The hourly series (25 points from the observation hour, compact
  JSON) is kept only on the newest observation: it is a forecast, not history. API:
  `GET /api/weather` (the new fields + `hourly`); `GET /api/config` → `weather`.
- Variables (optional) in `/etc/tabela.env`: `WEATHER_ENABLED` (default `1`; `0` stops
  the service and hides the widget), `WEATHER_INTERVAL_S` (default `900`, minimum `300`),
  `WEATHER_LAT` / `WEATHER_LON` (default `44.4323` / `26.1063`), `WEATHER_URL` (default
  `https://api.open-meteo.com/v1/forecast`).
- License and attribution: the weather data is from [Open-Meteo.com](https://open-meteo.com/),
  under the **CC BY 4.0** license (the free API is for non-commercial use); the attribution appears in the
  popover, in the page footer and in the Panel's credit (also visible in full screen).

## Attribution

Data taken from CFR (cfr.ro) — an independent project, not affiliated with CFR. The official board: https://cfr.ro. © 2026 Andy217Ace.
Weather: Open-Meteo.com (CC BY 4.0), model values.

License: MIT (see `LICENSE`).
