# Securitate în #admin (fail2ban + cereri) — plan de implementare

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Pașii folosesc `- [ ]`.

**Goal:** cardul „Securitate” din #admin arată IP-urile banate de fail2ban, istoricul ban-urilor
și numărul de cereri / cereri-probă pe 24 h și 7 zile, fără privilegii pentru aplicație.

**Architecture:** exportator root (`scripts/security_snapshot.py`, doar stdlib), rulat de
`tabela-security-snapshot.timer` la 2 min → JSON atomic `/var/lib/tabela/security/snapshot.json`
(dir root:tabela 750, fișier 640) → `GET /api/admin/security` (protejat ca restul, sanitizează,
cache 10 s, `available:false` + `reason` dacă lipsește/invalid/vechi > 600 s) → `web/admin.js`
(DOM doar cu `textContent`).

**Tech Stack:** Python 3 stdlib (sqlite3, gzip, re), FastAPI, JS vanilla, pytest + Playwright.

**Spec:** cererea coordonatorului (design decis, punctele 1–4), rezumată aici.

## Global Constraints
- Aplicația nu rulează `fail2ban-client`, nu citește socket-ul, log-urile nginx sau DB-ul fail2ban.
- Exportator: fără rețea (PrivateNetwork), fără DNS/geoIP; max 500 IP-uri, istoric 200, timp limitat.
- Clasificarea probelor = filtrul `nginx-tabela-probes` (4xx, exclude `/.well-known/`); `_probe`
  citit din filtrul live, cu copie integrată identică (test de egalitate cu `deploy/fail2ban/`).
- Valoare lipsă → „—” (nu 0); ore în Europe/Bucharest cu fus afișat; 390 px fără scroll orizontal.
- Nu se ating VERSION, CHANGELOG.md, tabela.service, config fail2ban/nginx, footer, sw.js
  (admin.js/admin.css nu sunt precache-uite → fără bump SW).
- Fără buton de unban.

## Review Focus
- Cale probată cu `<script>`/`<img onerror>` → afișată ca text (test de browser).
- Director de ieșire înlocuit cu symlink/dir al altui user → exportatorul refuză (test).
- fail2ban sau access.log lipsă → snapshot `available` parțial, nu crash (test).
- Linii de log corupte / binare / foarte lungi → numărate ca `parse_errors`, ignorate (test).
- Snapshot vechi (> 10 min) sau JSON invalid → `available:false` cu vârsta (test endpoint).

---

### Task 1: exportatorul (`scripts/security_snapshot.py`)
**Files:** Create `scripts/security_snapshot.py`, `deploy/fail2ban/nginx-tabela-probes.local`
(copie de referință), `tests/test_security_snapshot.py`.
**Interfaces (produce):** `is_probe(request: str, status: int, probe=None) -> bool`;
`parse_access_line(line) -> dict|None` (ip, ts, method, path, status);
`parse_f2b_log_line(line, tz) -> dict|None` (ts, event ban|unban|restore, jail, ip);
`read_f2b_db(path, now) -> dict` (jails, banned, bans); `build_snapshot(...) -> dict`;
`write_atomic(dir, name, data, gid)`; CLI `main(argv)` cu `--out`.
- [ ] Teste roșii: probe (`/.env`, `/.git/config`, `/wp-login.php`, `/x/phpinfo`, `http://h/.env`)
  numărate doar cu 4xx; NU: `/`, `/api/board`, `/sw.js`, `/.well-known/acme-challenge/x`,
  `/.env` cu 200; parser combined; log fail2ban; DB sqlite cu schema reală (bips/bans/jails);
  agregare 24h/7z + top căi; limită 500; write_atomic refuză symlink.
- [ ] Implementare, teste verzi, commit.

### Task 2: unit + timer + update.sh/install.sh
**Files:** Create `deploy/tabela-security-snapshot.{service,timer}`; Modify `deploy/update.sh`,
`deploy/install.sh`; Test `tests/test_update_sh.py`, `tests/test_deploy_static.py`.
- [ ] Teste: update.sh instalează unit-urile, creează dir-ul root:tabela 750, `enable --now`
  timer; eșecul nu oprește deploy-ul (avertisment); unit-ul are hardening (PrivateNetwork,
  ReadWritePaths=/var/lib/tabela/security, NoNewPrivileges, ProtectSystem=strict).
- [ ] Implementare, commit.

### Task 3: endpoint `GET /api/admin/security`
**Files:** Create `app/security_status.py` (`read_snapshot(path, now_ts) -> dict`, sanitizare);
Modify `app/admin.py`; Test `tests/test_admin_security.py`.
- [ ] Teste: 401 fără sesiune; lipsă → available false reason missing; vechi → stale + age_s;
  invalid → invalid; valid → câmpuri sanitizate (căi tăiate la 200, liste limitate);
  nu apare în API-urile publice.
- [ ] Implementare, commit.

### Task 4: UI în #admin
**Files:** Modify `web/admin.js`, `web/admin.css`; Test `tests/test_admin_security_browser.py`.
- [ ] Test de browser: login → card `#admin-security` cu rezumat, 3 tabele, „Actualizat acum”,
  ore cu „ora României”, sortare la click, fereastră 24h/7z, cale ostilă ca text, 390 px fără
  scroll orizontal, temă luminoasă/întunecată, fără erori de consolă/CSP; snapshot lipsă → mesaj.
- [ ] Implementare, commit.

### Task 5: validare pe server, review, PR
- [ ] Rulare exportator ca root în `/tmp/tabela-sec-test` (timp, dimensiune, nr. IP-uri).
- [ ] Teste noi + atinse; review cu subagent; PR (fără merge/deploy).
