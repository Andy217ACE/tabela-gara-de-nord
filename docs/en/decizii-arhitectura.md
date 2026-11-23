# Architecture decisions

© 2026 Andy217Ace

The list below gathers the project's deliberate choices, with the reason for each. What looks missing at first sight (Postgres, Redis, Docker, API keys, cloud backup) is in fact a decision, made for a single home server operated by a single person. Each item has the form: **the decision**, **the reason**, **when we revisit it**.

## 1. One SQLite (WAL) database, not Postgres

- **The decision.** All state is in one SQLite file (`app/store.py`), in WAL mode, with `synchronous=NORMAL` and `busy_timeout` 5000 ms.
- **The reason.** There is a single writing process (the poller inside the application process). The volume is small and the reads are simple queries. SQLite has no server to administer, the backup is a verified file copy (`app/dbbackup.py`), and a restore is one file.
- **Revisit when:** several writing processes appear or the database outgrows what can be copied in a maintenance window.

## 2. No Redis

- **The decision.** There is no external cache or queue. The caches are in process (for example 60 s for statistics, 300 s for estimates).
- **The reason.** One uvicorn worker, the poller runs in the process, and the data is small. A Redis would add a service to watch without solving a real problem.
- **Revisit when:** moving to several workers (the poller would have to move to a separate process anyway).

## 3. No Docker, Kubernetes or blue-green

- **The decision.** Deploying is `deploy/update.sh`: `git fetch`, `pip install`, a backup before a migration, restart, waiting for `/api/health`, **automatic rollback** if the service does not become healthy.
- **The reason.** One home server. The automatic rollback and the pre-migration backup cover the real risk (a bad version) without an orchestration platform. The install is idempotent (`deploy/install.sh`) and tested statically and by simulation (`tests/test_update_sh.py`).
- **Revisit when:** a second server appears or zero-downtime deploys become a requirement.

## 4. OCR in a thread of the process, not in a worker queue

- **The decision.** Reading the image runs in `asyncio.to_thread`; it does not block the event loop. `OMP_THREAD_LIMIT=1` in the systemd unit stops OpenMP from occupying every core.
- **The reason.** One image per minute, one consumer. A queue (Celery, RQ) would add a broker and a second failure path for a load of a few seconds a minute. The poller has its own time budget and does not fall over because of a failed reading.
- **Revisit when:** the cadence or the number of sources grows beyond what one thread can do.

## 5. No public API keys or quotas; rate limiting instead

- **The decision.** The public API is read-only and needs no account. Protection is request limiting in nginx (`tabela_api` 10 requests/s, burst 20; `tabela_stats` 60/min; `tabela_admin_login` 5/min) and fail2ban for scanners.
- **The reason.** The data is public by nature (a station board). Keys and quotas would need accounts, their storage and support, with no benefit for a project with a single operator.
- **Revisit when:** external consumers appear who need availability guarantees.

## 6. Administration with one token, an HMAC-signed session cookie and expiry

- **The decision.** `ADMIN_TOKEN` in `/etc/tabela.env` opens a session: an `HttpOnly`, `Secure`, `SameSite=Strict` cookie, HMAC-signed, with an expiry (12 h); the cookie does not contain the token. Mutations also need a CSRF token. Wrong attempts are limited per IP and globally. Changing the token invalidates every session.
- **Rotation.** It is done by hand, following `docs/en/admin-rotatie-cheie.md`. **There is no automatic rotation**: it is the owner's choice (a single administrator, a long random token, reachable only on the server).
- **Revisit when:** several administrators appear (the accounts plan, `docs/superpowers`, is only a plan).

## 7. No automatic operating-system updates or reboots

- **The decision.** Ubuntu updates are applied by hand, at a chosen time, not automatically.
- **The reason.** An automatic reboot at a bad moment interrupts the board reading and loses frames. Choosing the moment belongs to the owner. Accepted risk: system security fixes arrive with a delay.
- **Mitigations.** Firewall (`ufw`), fail2ban, an unprivileged user, systemd hardening, `pip-audit` and Dependabot for the application's dependencies.

## 8. Off-site backup is deferred

- **The decision.** There is no off-site copy yet. There are verified local copies (before every migration, at restores and at the destructive operations of `#admin`) and monitoring (watchdog, NVMe timer, external uptime checks).
- **The reason.** The owner's decision, deferred. The data is only partly reconstructible (the observed history cannot be re-read from another source).
- **Known risk:** losing the disk and the local copies together would mean losing the history. It is an accepted gap, not an omission; we revisit it at the first opportunity.
