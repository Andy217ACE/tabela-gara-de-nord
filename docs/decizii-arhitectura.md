# Decizii de arhitectură

© 2026 Andy217Ace

Lista de mai jos strânge alegerile deliberate ale proiectului, cu motivul fiecăreia. Ce pare lipsă la prima vedere (Postgres, Redis, Docker, chei API, backup în cloud) este de fapt o decizie, luată pentru un singur server de acasă și o singură persoană care îl operează. Fiecare punct are forma: **decizia**, **motivul**, **când o revedem**.

## 1. Un singur SQLite (WAL), nu Postgres

- **Decizia.** Toată starea este într-un fișier SQLite (`app/store.py`), în mod WAL, cu `synchronous=NORMAL` și `busy_timeout` 5000 ms.
- **Motivul.** Există un singur proces de scriere (poller-ul din procesul aplicației). Volumul este mic, iar citirile sunt interogări simple. SQLite nu are server de administrat, copia de siguranță este o copie de fișier verificată (`app/dbbackup.py`), iar restaurarea este un singur fișier.
- **Revedem când:** apar mai multe procese de scriere sau baza depășește ce poate fi copiat într-un interval de întreținere.

## 2. Fără Redis

- **Decizia.** Nu există cache sau coadă externă. Cache-urile sunt în proces (de exemplu 60 s pentru statistici, 300 s pentru estimări).
- **Motivul.** Un singur worker uvicorn, poller-ul rulează în proces, iar datele sunt mici. Un Redis ar adăuga un serviciu de supravegheat fără să rezolve o problemă reală.
- **Revedem când:** se trece la mai mulți workeri (ar trebui oricum mutat poller-ul într-un proces separat).

## 3. Fără Docker, Kubernetes sau blue-green

- **Decizia.** Deploy-ul este `deploy/update.sh`: `git fetch`, `pip install`, copie de siguranță înainte de o migrare, repornire, așteptarea `/api/health`, **rollback automat** dacă serviciul nu devine sănătos.
- **Motivul.** Un singur server de acasă. Rollback-ul automat și copia de dinaintea migrării acoperă riscul real (o versiune proastă), fără o platformă de orchestrare. Instalarea este idempotentă (`deploy/install.sh`) și testată static și prin simulare (`tests/test_update_sh.py`).
- **Revedem când:** apare un al doilea server sau cerința de deploy fără nicio întrerupere.

## 4. OCR într-un fir din proces, nu într-o coadă de workeri

- **Decizia.** Citirea imaginii rulează în `asyncio.to_thread`; nu blochează bucla de evenimente. `OMP_THREAD_LIMIT=1` în unitatea systemd împiedică OpenMP să ocupe toate nucleele.
- **Motivul.** O imagine pe minut, un singur consumator. O coadă (Celery, RQ) ar adăuga un broker și o a doua cale de eșec pentru o încărcare de câteva secunde pe minut. Poller-ul are buget de timp propriu și nu cade din cauza unei citiri eșuate.
- **Revedem când:** cadența sau numărul de surse crește peste ce poate face un fir.

## 5. Fără chei API publice și fără cote; limitarea cererilor în loc

- **Decizia.** API-ul public este read-only și fără cont. Protecția este limitarea cererilor în nginx (`tabela_api` 10 cereri/s, burst 20; `tabela_stats` 60/min; `tabela_admin_login` 5/min) și fail2ban pentru scanere.
- **Motivul.** Datele sunt publice prin natura lor (tabela unei gări). Chei și cote ar cere conturi, stocarea lor și suport, fără beneficiu pentru un proiect cu un singur operator.
- **Revedem când:** apar consumatori externi care cer garanții de disponibilitate.

## 6. Administrare cu un singur token, sesiune cu cookie semnat HMAC și expirare

- **Decizia.** `ADMIN_TOKEN` din `/etc/tabela.env` deschide o sesiune: cookie `HttpOnly`, `Secure`, `SameSite=Strict`, semnat HMAC, cu expirare (12 h); cookie-ul nu conține tokenul. Mutațiile cer și token CSRF. Încercările greșite sunt limitate pe IP și global. Schimbarea tokenului invalidează toate sesiunile.
- **Rotația.** Se face de mână, după pașii din `docs/admin-rotatie-cheie.md`. **Nu există rotație automată**: este alegerea proprietarului (un singur administrator, token lung și aleatoriu, accesibil doar pe server).
- **Revedem când:** apar mai mulți administratori (planul de conturi, `docs/superpowers`, este doar plan).

## 7. Fără actualizări și reporniri automate ale sistemului de operare

- **Decizia.** Actualizările Ubuntu se aplică de mână, la un moment ales, nu automat.
- **Motivul.** O repornire automată într-un moment nepotrivit întrerupe citirea tablei și pierde cadre. Alegerea momentului îi aparține proprietarului. Riscul acceptat: corecțiile de securitate ale sistemului ajung cu întârziere.
- **Atenuări.** Firewall (`ufw`), fail2ban, utilizator fără privilegii, întărire systemd, `pip-audit` și Dependabot pentru dependențele aplicației.

## 8. Copia de siguranță în afara serverului este amânată

- **Decizia.** Nu există încă o copie off-site. Există copii locale verificate (înainte de fiecare migrare, la restaurări și la operațiile destructive din `#admin`) și monitorizare (watchdog, temporizator NVMe, verificări externe de uptime).
- **Motivul.** Decizia proprietarului, amânată. Datele sunt reconstruibile doar în parte (istoricul observat nu se poate reciti din altă sursă).
- **Risc cunoscut:** pierderea discului și a copiilor locale odată ar însemna pierderea istoricului. Este o lacună asumată, nu o omisiune; o revedem la prima ocazie.
