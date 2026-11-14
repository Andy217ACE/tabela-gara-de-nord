# Captures and privacy

This document explains what a **capture** is in the Tabela Gara de Nord application, where it is kept,
for how long, who can see it, what personal data the application stores and what it does not store. Every
statement starts from the code or from the configuration files; where I could not verify
something, it is marked **"uncertain"** with the file to check.

In short:

- A capture is the image of the CFR board, received from the public source, plus the OCR result on it.
- The **real** images of the board are private: they are seen only from the administration, they are not published and they are not
  put in the repo. The application keeps the images for 7 days by default; the data rows stay.
- Personal data: notification subscriptions (the address of the browser's push service, plus two cryptographic
  keys) and train follows, linked to them. The IP address appears only in the administration audit log.
- Finding: a test file tracked in git (`tests/fixtures/page_1.html`) contains an embedded JPEG
  image. See section 9 and check before any publication.

## Contents

1. [Terminology](#1-terminology)
2. [What a capture is](#2-what-a-capture-is)
3. [Where it is stored](#3-where-it-is-stored)
4. [How a capture is written](#4-how-a-capture-is-written)
5. [Retention: how long the images stay](#5-retention)
6. [Rows after retention](#6-rows-after-retention)
7. [The administration view](#7-the-administration-view)
8. [The project rule: captures are private](#8-the-project-rule)
9. [What is tracked in git and what is ignored](#9-what-is-tracked-in-git-and-what-is-ignored)
10. [For contributors: local private images](#10-for-contributors)
11. [On the server: the image directory of the shadow training](#11-on-the-server)
12. [Personal data stored](#12-personal-data-stored)
13. [What is not stored](#13-what-is-not-stored)
14. [Checklist and uncertain items](#14-checklist)

---

## 1. Terminology

| Term | What it means in the code |
|---|---|
| **Image** (or frame) | The JPEG/PNG bytes of the board, as downloaded from the source. |
| **Capture** | A row of the `captures` table (`app/observations.py`): a new image, with time, hash, dimensions, OCR duration, error, processing version and the file path (if it still exists). |
| **Observation** | A row of `observations`: an OCR line (12 per panel) of a capture, with the raw text and the normalized values. |
| **Service** and **journey** | A train on one service date and on one panel (`services`). They are neither a capture nor an observation. |
| **Rejected frame** | An image saved in `REJECTED_DIR` because a panel was rejected or the OCR failed (`app/rejected.py`). |
| **Ground-truth image** | A real frame used to measure the OCR (the hand-written set in `tests/fixtures/ocr_truth/`). |

So a capture is **the image + the metadata + the observations**. The last two stay in the database
regardless of the image (see 6).

## 2. What a capture is

For each new image of the board, `observations.record_capture` writes:

- a row in `captures`, with: `captured_at` (UTC), `last_seen_at`, `image_hash` (SHA-1, **unique**),
  `path` (relative path, or `NULL` if the image is not on disk), `width`, `height`, `bytes`, `ok`,
  `n_rows`, `processing_version`, `duration_ms`, `error` (max. 500 characters), `expires_at`;
- one row in `observations` for each OCR line, with `raw_text`, `fields_json` (each
  field with the raw text, the normalized value, the confidence and the box), `train_no`, `sched_time`,
  `delay_min`, `platform`, `station`/`station_raw`, `operator`/`operator_raw`, `validation_state`.

If the same image (the same hash) appears again, a new capture is **not** created: only
`last_seen_at` is updated (`record_capture`, the first branch).

The observations do not contain the image bytes. They contain the text read from the board and its interpretation. The image
is the only place where the pixels of the board appear.

## 3. Where it is stored

| What | Default path | Variable | Who writes | Expires? |
|---|---|---|---|---|
| The capture image | `/var/lib/tabela/captures/AAAA/LL/ZZ/HHMMSS-<hash8>.jpg` (UTC) on the server; `data/captures/...` otherwise | `CAPTURE_DIR` | `observations.record_capture` | Yes, after `CAPTURE_RETENTION_DAYS` (see 5) |
| The capture row and the observations | `tabela.db` (the tables `captures`, `observations`, `trains`) | `DB_PATH` | `record_capture`, `refresh_trains` | No (there is no deletion code for `observations`; see 6) |
| The last downloaded image | `data/last.jpg` (the default in `config.py`); `/var/lib/tabela/last.jpg` (in `.env.example`) | `LAST_IMAGE_PATH` | `poller._save_image` | No; a single file, overwritten on every new image |
| Rejected frames | `/var/lib/tabela/rejected` | `REJECTED_DIR` (`""` = disabled) | `rejected.save_rejected` | Yes, the oldest 40 pairs (by count, not by age) |
| The Telegram alert state | `data/telegram_sent.json` | `TELEGRAM_STATE_PATH` | `telegram.SentLog` | Yes, it keeps only today and yesterday (`KEEP_DAYS = 2`) |
| The shadow training directory | `/var/lib/tabela/shadow` (`export.json`, `run/`, `model-*.npz`, `report-*.json`, `truth-img/`) | the `--workdir` argument | `scripts/nightly_shadow_train.py` | `run/` is deleted on every run; the rest stays |

Two location rules, from `.gitignore`:

- `data/*` is ignored, except for `data/operators.txt` and `data/stations_seed.txt`. So `data/captures/`,
  `data/last.jpg` and `data/telegram_sent.json` do not reach git.
- `.env` and `*.db` are ignored. The database and the environment file are not published from the repo.

The installation documentation (`README.md`, the "Capturi și retenție" section) says the same:
`CAPTURE_DIR` defaults to `/var/lib/tabela/captures` on the server and `data/captures` locally.

## 4. How a capture is written

The order (`captures.make_on_capture` and `observations.record_capture`):

1. `poller.run_poller` receives the new image, sends it to OCR and then to `on_rows`.
2. After `on_rows`, it calls `on_capture` (if configured). Its exceptions are caught and logged; they do **not** stop the poller.
3. `on_capture` takes `corrections.correct_frame` (the manual rules also apply to new captures), then
   `admin_settings.effective` (the active retention, from the database or from the environment), then `record_capture`.
4. If `CAPTURE_ENABLED` is 0/false/no/off, `on_capture` records **nothing** (neither a row nor an image;
   `make_on_capture`).
   Otherwise, `record_capture` does **not** write the image if:
   - the retention is 0 (`retention_days > 0` is the condition), or
   - the free disk space, after writing the image, would drop below the minimum threshold (`_disk_ok`).
   In this case the row and the observations are written anyway (only `path` stays `NULL`).
5. The image is written to a `.tmp` file and then moved with `os.replace`. If writing to the
   database fails, the file is deleted (`_remove_file`), so that no image is left without a row.

The free-space threshold:

| Source | Default value | Accepted range |
|---|---|---|
| `CAPTURE_MIN_FREE_MB` (environment) | 2048 MB (`MIN_FREE_MB_DEFAULT`) | ≥ 0 |
| The `capture_min_free_mb` setting (Settings page) | 2048 MB | 256 – 102400 MB (`admin_settings.SPECS`) |

The value from the Settings page, if present, has priority over the environment (`admin_settings.effective`).
The reason, from `observations.py`: "the database and the LIVE board share the disk; a full disk would stop the board".
If `disk_usage` fails, the code assumes there is space (`return True`) and lets the write succeed
or fail cleanly.

## 5. Retention

### 5.1 The values

| Setting | Environment | Settings page | Default | Effect |
|---|---|---|---|---|
| Days to keep | `CAPTURE_RETENTION_DAYS` | `capture_retention_days` (1–30) | 7 | After how many days the images are deleted |
| The 0 limit | `CAPTURE_RETENTION_DAYS=0` | not possible (the minimum on the page is 1) | — | No image is written any more; the existing images are deleted on the next run |

From the environment, `capture_settings()` accepts 0–3650 days (`max(0, min(days, 3650))`); an invalid
value becomes 7. The value from the Settings page has priority; if the row in the `settings` table is
invalid, the environment is used (`admin_settings.effective`).

### 5.2 When it runs

`captures.retention_loop` (started from `api.py`):

- the first run **60 s** after startup (`RETENTION_FIRST_DELAY_S`);
- then every **24 hours** (`RETENTION_INTERVAL_S`);
- any exception is logged and the loop continues.

### 5.3 What `run_retention` deletes

The selection condition is:

```text
SELECT id, path FROM captures WHERE path IS NOT NULL AND captured_at < (acum − zile)
```

For each capture selected:

- the path is validated with `safe_path` (relative, no `..`, no `\`, no two dots in the first
  segment, resolved inside `CAPTURE_DIR`); if it does not pass, the file is **not** touched and
  the reference in the database is cleared;
- the file is deleted; the empty day, month and year directories are removed (`_prune_dirs`), without
  going beyond `CAPTURE_DIR`;
- if the file is already missing, it is counted as "missing";
- if deletion fails with `OSError`, the reference stays and is retried on the next run;
- in all cases `path` becomes `NULL`, except in the error case.

The rows in `captures` and `observations` are **not** deleted.

**Uncertain, to note**: the `expires_at` column is written at recording time (`captured_at + days`), but
`run_retention` **does not read it**; the selection is done by `captured_at`. If you change the retention,
the `expires_at` of old captures stays the old one. Check: `grep -n expires_at app/` (it appears in
`observations.py`, `captures.py` for display and in the table schema).

### 5.4 What has NO retention

| What | Why it is not deleted | Source |
|---|---|---|
| The `captures` rows | Only `path` becomes `NULL` | `run_retention` |
| The `observations` rows | There is no `DELETE FROM observations` statement in `app/` | `grep` on `app/` |
| `LAST_IMAGE_PATH` | It is a single file, overwritten by every new image | `poller._save_image` |
| Rejected frames | Their retention is by count (40), not by age | `rejected.REJECTED_KEEP` |
| Old image versions in `shadow/run/` | The directory is deleted on every nightly run | `nightly_shadow_train.run` |

**The poller has no retention code.** `app/poller.py` only calls `on_capture` and saves the rejected
frames. The retention is in `app/captures.py` (`run_retention`, `retention_loop`).

Database growth: the README says the observations grow by about 30–40 MB per day and that
"compaction of the old `fields_json` fields is planned". I found no compaction in the code.
**Uncertain**: the 30–40 MB/day figure cannot be verified from the repo; the source would be measurements on the server.

### 5.5 Why 7 days

No reason for the value 7 is written in the code. The documentation says only that it is the default.
**Uncertain**: the rationale (debugging, measurement, the ground-truth set) is not documented.

## 6. Rows after retention

After the image has been deleted:

- the captures stay in `captures` with `path = NULL`. In the administration list they appear with `has_image: false`
  (`captures.list_captures` → `_cap`);
- the capture detail and the observations stay accessible from the administration;
- `GET /api/admin/captures/{id}/image` answers **404** with the message "Imaginea nu mai este disponibilă
  (retenție expirată)" (`admin.capture_image`);
- the overlay (`/overlay.png`) has the same 404, because it is drawn on the image on disk
  (`admin.capture_overlay`). The overlay is **not** saved: it is generated on request;
- the statistics (`captures.capture_stats`) count only the images that still exist (`path IS NOT NULL`).

The observations stay, so the number of services, the `trains` catalog and the history do not depend on images.
This also means that the **OCR data** (raw text, numbers, times, platforms) is kept indefinitely,
even if the image is gone. This is data about the board, not about people.

## 7. The administration view

### 7.1 The routes

All are under `/api/admin` and go through `require_admin` (`app/admin.py`, `guarded = APIRouter(dependencies=[...])`):

| Route | What it returns |
|---|---|
| `GET /api/admin/captures?limit=&before=` | The list (at most 200, default 50), newest first, with the line counter per panel |
| `GET /api/admin/captures/{cid}` | The detail: the metadata, all the observations, the raw text, `fields_json`, the line version |
| `GET /api/admin/captures/{cid}/image` | The original image, unchanged (`Cache-Control: no-store`) |
| `GET /api/admin/captures/{cid}/overlay.png` | The image with rectangles on the cells, colored by confidence (green ≥ 80, yellow ≥ 50, red below 50) |
| `GET /api/admin/stats` | Free disk space, the latest capture attempts, durations, errors from the last 24 h, rows from the last 24 h, the database size, the number of images |
| `GET /api/admin/settings` (read) and `POST /api/admin/settings` (write, with CSRF check) | The retention and the space threshold (values without secrets) |

The images are served **only** from the administration. In `app/api.py` there is no image route (verified
with `grep -n "image" app/api.py`; the results are only references to `last_image_path`).

### 7.2 Authentication

- The key is `ADMIN_TOKEN` from the environment (`/etc/tabela.env`, with `chmod 600` according to `.env.example`).
  It is not in the database.
- After login, the session cookie is `HttpOnly`, `Secure`, `SameSite=Strict`, with a duration of 12 hours
  (`admin.py`, the docstring at the top).
- Optional strict mode: `ADMIN_TOKEN_STRICT=1` requires a key of at least 24 characters
  (`STRICT_TOKEN_LEN`). Off by default.
- The limiting of failed attempts is kept **in memory**, per IP and globally (`_failures`, `_global_failures`);
  it resets on restart.

### 7.3 The audit log

The `correction_audit` table (`corrections.py`) keeps: `ts`, `actor`, `ip`, `action`,
`correction_id`, `batch`, `detail`. The actions are: `create`, `apply`, `restore`, `delete`, `setting`.
**The administrator's IP address is stored here**, indefinitely (there is no deletion code
for this table). It is the only IP address kept in the database.

## 8. The project rule

The rule: **real captures of the CFR board are private**. They are not uploaded to the repo, not published and not redistributed.
The sources:

- `README.md` (the "Capturi și retenție" section): "Raw CFR captures are **private**: they are seen only from
  the administration and are not redistributed." (the original is in Romanian: "Capturile brute CFR sunt **private**: se văd doar din administrare și nu se redistribuie.")
- `app/captures.py` (docstring): "Raw CFR images are private (admin only) and never redistributed."
- `tests/ocr_truth_images.py` (docstring): "Nicio captură reală nu e în git (repo public)" (no real capture is in git; public repo).
- `CHANGELOG.md`, Beta 1.43: "Nicio captură reală a tabelei nu mai e urmărită în git" (no real board capture is tracked in git any more). The git history
  was not rewritten (the same note).
- `.gitignore`: "capturi reale (repo public): imaginile setului de adevăr sunt locale" (real captures, public repo: the ground-truth images are local).

The rule also applies to derived data: the observations are the text of the board, not the image, and contain no personal
data. They are not, however, described in the documentation as data to be published in bulk.

## 9. What is tracked in git and what is ignored

### 9.1 Ignored (`.gitignore`)

| Rule | What it covers |
|---|---|
| `tests/fixtures/ocr_truth/private/` | The images of the private ground-truth set |
| `tests/fixtures/ocr_truth/**/*.jpg` | Any JPEG in the ground-truth set |
| `tests/fixtures/**/*.jpg` | Any JPEG in `tests/fixtures` |
| `data/*` (with the exceptions `operators.txt`, `stations_seed.txt`) | `data/captures/`, `data/last.jpg`, `data/telegram_sent.json`, local databases |
| `*.db`, `.env` | Databases and environment files |
| `!tests/fixtures/*.db` | **Exception**: the test databases in `tests/fixtures/` are tracked |

### 9.2 Tracked and relevant content

The files tracked in `tests/fixtures/` (verified with `git ls-files`):

| File | What it contains | Remark |
|---|---|---|
| `board_1.json`, `board_2.json` | Expected train rows (text and numbers) | Data about the board |
| `live_v2.db` | A test SQLite database: the tables `runs`, `services`, `events`, `subscriptions`, `follows` | I counted the rows: 2, 4, 5, 0, 0. No `captures`/`observations` tables, no subscriptions |
| `ocr_truth/truth.json` | 59 frames, 1416 labeled lines | Data about the board; the frame keys contain the date and time of the capture (UTC) |
| `ocr_truth/holdout/holdout.json`, `README.md` | The verification set (21 frames) | Same |
| `ocr_truth/baseline-1.31.json`, `NOTE-2026-10-27.md` | Measurements and notes | Same |
| **`page_1.html`** | **The saved CFR page, which contains an embedded JPEG image (base64)** | See 9.3 |

### 9.3 Finding: an image embedded in `tests/fixtures/page_1.html`

- The file is tracked in git and is not covered by `.gitignore` (the rule covers only `*.jpg`).
- It contains a `data:image/jpg;base64,...` string of about 143,500 characters, which decodes into a
  valid JPEG of about 107,700 bytes. The mechanism is the same as in the real CFR page
  (`app/fetcher.py` extracts the board image from such a string).
- I did not describe the content of the image and did not save it anywhere.
- The file is used by `tests/test_fetcher.py`, which reads it as text.
- **Uncertain**: whether the image is a real capture of the board, which seems likely from the mechanism and
  size. Human verification is needed. If so, the rule in section 8 is violated, and the file
  must be removed from git (the decision and any rewriting of the history belong to the maintainer).
  For the test, the image could be replaced with a generic JPEG, without changing the test logic.

## 10. For contributors

### 10.1 Local private images

The repo contains no JPEG. To run the tests that read real frames or the OCR measurement,
the contributor must have local copies, obtained from outside the repo (the repo does not describe
the procedure for obtaining them; **uncertain**: the source and permission must be set by the maintainer).

Two places:

- `tests/fixtures/` for the public frames (`ocr12/`, `ocr13/`, `glare/`, `ocr14_delay100/`, `board_1.jpg`, …);
- `OCR_TRUTH_DIR` (default `tests/fixtures/ocr_truth/private/`) for the `ocr_truth/...` keys in `truth.json`
  and `holdout/...`.

### 10.2 How the code behaves when the image is missing

`tests/ocr_truth_images.py`:

- `frame_path(key)`: the `ocr_truth/<path>` keys are looked up in `PRIVATE/<path>.jpg`; the rest in `FIX/<key>.jpg`;
- `capture(path)`: if the file is missing, the test **skips** (`pytest.skip`) with a reason that says where
  the file should be and suggests `OCR_TRUTH_DIR` if the private directory is the default one;
- `read_frame(key)`: `capture` + reading the bytes.

The scripts have the same logic, but without skips, with reporting instead:

- `scripts/ocr_eval.py` (`_image`): an explicit `IMG_DIR` or, for `ocr_truth/...`, `OCR_TRUTH_DIR`;
- `scripts/ocr_digit_clf.py` (`_truth_image`): looks first in `TRUTH_IMG_DIRS` (set by the nightly
  shadow run to `WORKDIR/truth-img`), then next to `truth.json` (`tests/fixtures/`), then in `ocr_truth/private/`.
  A frame not found is counted in the report (`frames_missing`), and does not stop the run.

### 10.3 What must not reach the repo

- Images of the board under any name (including in embedded `tests/fixtures/*.html`, see 9.3).
- Glyphs extracted from real frames, as files (the results of `ocr_digit_clf extract` stay in `OUT_DIR`, which
  must be outside the repo; `nightly_shadow_train` refuses a `WORKDIR` inside the repo).
- Captures exported from the database (`export.json` files with paths), or the `tabela.db` database / its copies.

## 11. On the server

### 11.1 The shadow training directory

`deploy/tabela-shadow-train.service` runs `scripts/nightly_shadow_train.py` as the `tabela` user:

- `ReadWritePaths=/var/lib/tabela` (the only writable place), `ReadOnlyPaths=/opt/tabela`,
  `ProtectSystem=strict`, `ProtectHome=true`, `PrivateTmp=true`, `NoNewPrivileges=true`;
- the database is opened in `ro` mode (`export_db`), with `file:...?mode=ro`; the script does not write to it;
- `_check_workdir` refuses a working directory in the repo;
- `TIME_LIMIT_S = 2 h` (`SIGALRM` alarm and a limit in the service).

What it writes in `/var/lib/tabela/shadow`:

| File | Content | Images? |
|---|---|---|
| `export.json` | Capture paths and observations (`fields_json`) | No, but it contains the image file names |
| `run/` | Glyphs (32×32 matrices), labels, cache (`run/cache/*.pkl`) | No whole images, but fragments of real frames; deleted on every run |
| `model-AAAA-LL-ZZ.npz` | The MLP weights | No |
| `report-AAAA-LL-ZZ.json` | Numbers, the decision, the limits, the ground-truth set path | No |
| `truth-img/<frame>.jpg` | The images of the hand-written set (copied manually to the server) | **Yes**, private |

The training images are read from `IMG_ROOT/captures/<path>` (default `/var/lib/tabela/captures`).
The hand-written set is `tests/fixtures/ocr_truth/truth.json` from the repo, or `WORKDIR/truth.json`.
Frames without an image in `truth-img/` are skipped and counted in the report (`set_adevar_cadre`), and
the run continues (CHANGELOG, Beta 1.43).

### 11.2 Scheduling

`deploy/tabela-shadow-train.timer`: `OnCalendar=*-*-* 03:30:00`, `Persistent=true` (a missed run
is made at the next startup). The time is the system's.

### 11.3 What happens to old files

- `truth-img/` is not deleted by the script; a person manages it.
- `model-*.npz` and `report-*.json` accumulate (one per day). **Uncertain**: I found no cleanup code.

## 12. Personal data stored

The application has no users table and no accounts (verified: the `CREATE TABLE` list in `app/`).
The personal or identifying data is the following.

| Data | Where | What it contains | For how long | Who sees it | Source |
|---|---|---|---|---|---|
| Push subscription | `subscriptions` | `endpoint` (the address of the browser's notification service), `p256dh`, `auth` (cryptographic keys), `created_at` | Until unsubscribe or a 404/410 answer from the service | Only in the database and in the server code | `store.subscribe`, `store.unsubscribe`, `notifier.one` |
| Train follow | `follows` | `subscription_id`, `train_no`, `service_date` | Follows older than yesterday are deleted lazily, when the same subscription adds a new follow (`store.follow`) | Same | `store.follow`, `store.followers` |
| The push address in the browser | the visitor's `localStorage` (`web/follows.js`) | The same push endpoint, kept on the device | Until the browser data is cleared | Only on the user's device | `web/follows.js` (the comment in the file: "the only thing kept on the device is the push subscription endpoint") |
| The administrator's Telegram chat | **Not** in the database; in the environment variable `TELEGRAM_CHAT_ID` | The chat identifier | As long as the environment is set | The server and the administrator | `telegram.config_from_env` |
| The Telegram alert state | `data/telegram_sent.json` | Event keys and the service date (without the visitor's name) | Today and yesterday | The server | `telegram.SentLog` |
| The administrator's IP address | `correction_audit.ip` | The client IP, on correction and settings actions | Unlimited | Administration | `corrections.audit`, `admin._ip` |
| Export rate limiting | In memory | The IP, with a time window | Until restart | Nobody | `export.LIMITER` |
| Login attempt limiting | In memory | The IP and the counter | Until restart | Nobody | `admin._failures` |

Remarks:

- **The push endpoint** identifies a browser or a device. I treat it as personal data, because
  it is the delivery key for notifications to that device. The server accepts only addresses of
  known push services (`app/endpoints.py`: FCM, Mozilla, Apple, Windows notify), over HTTPS, with no
  user and no unusual port.
- The endpoint arrives in the request as a query string parameter (`/api/follows?endpoint=...`). The nginx configuration
  disables the access log for this location (`deploy/nginx-tabela.conf`, with the comment "never
  write it to the access log").
- **The nginx logs for other locations** may contain visitors' IP addresses. The global access
  configuration is not in the repo (the `nginx.conf` on the server). **Uncertain**: to verify on the server.
- `correction_audit` keeps the administrator's IP. The purpose is auditing, not statistics.
- The number of active follows per subscription is limited to `MAX_FOLLOWS = 20` (`app/store.py`; the docstring of `follow` says that only today's or tomorrow's follows count toward the limit).

## 13. What is not stored

Verified in the code:

- **No names, emails, phone numbers or accounts** of the visitors are stored (there are no tables for them).
- **The IP of public visitors is not stored** in the database. IPs appear only in memory (limiting)
  and in the administration audit (see 12).
- **The administration key is not stored** in the database or in the browser (`CHANGELOG`, Beta 1.40: "Cheia nu se salvează în browser", the key is not saved in the browser).
- **The Telegram token is not stored**: `telegram.TelegramConfig` has `token` with `repr=False`, and
  the module documentation says the token does not appear in the log and is not returned.
- **The image bytes are not stored in the observations**: the observations contain text.
- **The overlay is not saved**: it is generated on request (`captures.overlay_png`).
- **Push endpoints are not written to the application log**: the messages in `notifier.py` say "push
  subscription gone; removing" and "push failed: <type>: <message>". **Uncertain**: the exception messages of the push
  library might include the URL; to verify on the real logs.
- **The server sends no data to third parties** other than the CFR source, the push services, Telegram (when enabled) and
  Open-Meteo for the weather (`app/weather.py`, model data, no personal data). Verified in `app/`; I did not check
  the files in `web/` for external resources. **Uncertain** for the front end.

## 14. Checklist

Things for a person to verify, in order of priority:

1. **`tests/fixtures/page_1.html`**: whether the embedded image is a real capture (section 9.3).
   If so, the decision to remove it from git and rewrite the history belongs to the maintainer.
2. **The nginx logs on the server** (the global access configuration, section 12).
3. **The push exception messages in the log** (section 13).
4. **`expires_at`** versus the retention (section 5.3).
5. **The 30–40 MB/day figure** for observations (section 5.4), from real measurements.
6. **The reason for the 7-day value** (section 5.5), if it exists in another document.
7. **Cleaning up old models and reports** from `shadow/` (section 11.3).
8. **The procedure for obtaining the private images** for contributors (section 10.1), if it needs to be documented.
