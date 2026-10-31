# Capturi și confidențialitate

Acest document explică ce este o **captură** în aplicația Tabela Gara de Nord, unde se păstrează,
cât timp, cine o poate vedea, ce date personale stochează aplicația și ce nu stochează. Fiecare
afirmație pornește de la cod sau de la fișierele de configurare; acolo unde nu am putut verifica
ceva, este marcat **„nesigur”** cu fișierul de verificat.

Pe scurt:

- Captura este imaginea tablei CFR, primită de la sursa publică, plus rezultatul OCR asupra ei.
- Imaginile **reale** ale tablei sunt private: se văd doar din administrare, nu se publică și nu se
  pun în repo. Aplicația păstrează imaginile 7 zile implicit; rândurile cu date rămân.
- Date personale: abonările la notificări (adresa serviciului push al browserului, plus două chei
  criptografice) și urmăririle de trenuri, legate de ele. Adresa IP apare doar în jurnalul de audit al administrării.
- Constatare: un fișier de test urmărit în git (`tests/fixtures/page_1.html`) conține o imagine JPEG
  încorporată. Vezi secțiunea 9 și verificați înainte de orice publicare.

## Cuprins

1. [Terminologie](#1-terminologie)
2. [Ce este o captură](#2-ce-este-o-captură)
3. [Unde se stochează](#3-unde-se-stochează)
4. [Cum se scrie o captură](#4-cum-se-scrie-o-captură)
5. [Retenția: cât timp rămân imaginile](#5-retenția)
6. [Rândurile după retenție](#6-rândurile-după-retenție)
7. [Vederea de administrare](#7-vederea-de-administrare)
8. [Regula proiectului: capturile sunt private](#8-regula-proiectului)
9. [Ce este urmărit în git și ce este ignorat](#9-ce-este-urmărit-în-git-și-ce-este-ignorat)
10. [Pentru contributori: imaginile private locale](#10-pentru-contributori)
11. [Pe server: directorul de imagini al antrenării umbră](#11-pe-server)
12. [Datele personale stocate](#12-datele-personale-stocate)
13. [Ce nu se stochează](#13-ce-nu-se-stochează)
14. [Lista de verificare și lucruri nesigure](#14-lista-de-verificare)

---

## 1. Terminologie

| Termen | Ce înseamnă în cod |
|---|---|
| **Imagine** (sau cadru) | Octeții JPEG/PNG ai tablei, așa cum au fost descărcați de la sursă. |
| **Captură** | Un rând din tabela `captures` (`app/observations.py`): o imagine nouă, cu oră, hash, dimensiuni, durata OCR, eroare, versiunea de procesare și calea fișierului (dacă mai există). |
| **Observație** | Un rând din `observations`: o linie OCR (12 pe panou) a unei capturi, cu textul brut și valorile normalizate. |
| **Serviciu** și **călătorie** | Un tren pe o zi de serviciu și pe un panou (`services`). Nu sunt captură și nu sunt observație. |
| **Cadru respins** | Imagine salvată în `REJECTED_DIR` pentru că un panou a fost respins sau OCR-ul a eșuat (`app/rejected.py`). |
| **Imagine de adevăr** | Cadru real folosit pentru a măsura OCR-ul (setul scris de mână din `tests/fixtures/ocr_truth/`). |

Captura este deci **imaginea + metadatele + observațiile**. Ultimele două rămân în baza de date
indiferent de imagine (vezi 6).

## 2. Ce este o captură

Pentru fiecare imagine nouă a tablei, `observations.record_capture` scrie:

- un rând în `captures`, cu: `captured_at` (UTC), `last_seen_at`, `image_hash` (SHA-1, **unic**),
  `path` (cale relativă, sau `NULL` dacă imaginea nu e pe disc), `width`, `height`, `bytes`, `ok`,
  `n_rows`, `processing_version`, `duration_ms`, `error` (max. 500 caractere), `expires_at`;
- câte un rând în `observations` pentru fiecare linie OCR, cu `raw_text`, `fields_json` (fiecare
  câmp cu textul brut, valoarea normalizată, încrederea și caseta), `train_no`, `sched_time`,
  `delay_min`, `platform`, `station`/`station_raw`, `operator`/`operator_raw`, `validation_state`.

Dacă aceeași imagine (același hash) apare din nou, **nu** se creează o captură nouă: se actualizează
doar `last_seen_at` (`record_capture`, prima ramură).

Observațiile nu conțin octeții imaginii. Conțin textul citit din tablă și interpretarea lui. Imaginea
este singurul loc unde apar pixelii tablei.

## 3. Unde se stochează

| Ce | Cale implicită | Variabilă | Cine scrie | Expiră? |
|---|---|---|---|---|
| Imaginea capturii | `/var/lib/tabela/captures/AAAA/LL/ZZ/HHMMSS-<hash8>.jpg` (UTC) pe server; `data/captures/...` altfel | `CAPTURE_DIR` | `observations.record_capture` | Da, după `CAPTURE_RETENTION_DAYS` (vezi 5) |
| Rândul capturii și observațiile | `tabela.db` (tabelele `captures`, `observations`, `trains`) | `DB_PATH` | `record_capture`, `refresh_trains` | Nu (nu există cod de ștergere pentru `observations`; vezi 6) |
| Ultima imagine descărcată | `data/last.jpg` (implicit în `config.py`); `/var/lib/tabela/last.jpg` (în `.env.example`) | `LAST_IMAGE_PATH` | `poller._save_image` | Nu; un singur fișier, suprascris la fiecare imagine nouă |
| Cadre respinse | `/var/lib/tabela/rejected` | `REJECTED_DIR` (`""` = dezactivat) | `rejected.save_rejected` | Da, cele mai vechi 40 de perechi (după număr, nu după vârstă) |
| Starea alertelor Telegram | `data/telegram_sent.json` | `TELEGRAM_STATE_PATH` | `telegram.SentLog` | Da, păstrează doar azi și ieri (`KEEP_DAYS = 2`) |
| Directorul de antrenare umbră | `/var/lib/tabela/shadow` (`export.json`, `run/`, `model-*.npz`, `report-*.json`, `truth-img/`) | argument `--workdir` | `scripts/nightly_shadow_train.py` | `run/` se șterge la fiecare rulare; restul rămâne |

Două reguli de locație, din `.gitignore`:

- `data/*` este ignorat, cu excepția `data/operators.txt` și `data/stations_seed.txt`. Deci `data/captures/`,
  `data/last.jpg` și `data/telegram_sent.json` nu ajung în git.
- `.env` și `*.db` sunt ignorate. Baza de date și fișierul de mediu nu se publică din repo.

Documentația de instalare (`README.md`, secțiunea „Capturi și retenție”) spune același lucru:
`CAPTURE_DIR` implicit este `/var/lib/tabela/captures` pe server și `data/captures` local.

## 4. Cum se scrie o captură

Ordinea (`captures.make_on_capture` și `observations.record_capture`):

1. `poller.run_poller` primește imaginea nouă, o trimite la OCR și apoi la `on_rows`.
2. După `on_rows`, apelează `on_capture` (dacă e configurat). Excepțiile lui sunt prinse și înregistrate; **nu** opresc poller-ul.
3. `on_capture` ia `corrections.correct_frame` (regulile manuale se aplică și pe capturile noi), apoi
   `admin_settings.effective` (retenția activă, din bază sau din mediu), apoi `record_capture`.
4. Dacă `CAPTURE_ENABLED` e 0/false/no/off, `on_capture` nu înregistrează **nimic** (nici rând, nici imagine;
   `make_on_capture`).
   Altfel, `record_capture` **nu** scrie imaginea dacă:
   - retenția e 0 (`retention_days > 0` este condiția), sau
   - spațiul liber pe disc, după scrierea imaginii, ar scădea sub pragul minim (`_disk_ok`).
   În acest caz rândul și observațiile se scriu oricum (doar `path` rămâne `NULL`).
5. Imaginea se scrie într-un fișier `.tmp` și apoi se mută cu `os.replace`. Dacă scrierea în baza
   de date eșuează, fișierul e șters (`_remove_file`), ca să nu rămână o imagine fără rând.

Pragul de spațiu liber:

| Sursă | Valoare implicită | Interval acceptat |
|---|---|---|
| `CAPTURE_MIN_FREE_MB` (mediu) | 2048 MB (`MIN_FREE_MB_DEFAULT`) | ≥ 0 |
| Setarea `capture_min_free_mb` (pagina Setări) | 2048 MB | 256 – 102400 MB (`admin_settings.SPECS`) |

Valoarea din pagina Setări, dacă există, are prioritate față de mediu (`admin_settings.effective`).
Motivul, din `observations.py`: „baza de date și tabela LIVE împart discul; un disc plin ar opri tabela”.
Dacă `disk_usage` eșuează, codul presupune că e spațiu (`return True`) și lasă scrierea să reușească
sau să eșueze curat.

## 5. Retenția

### 5.1 Valorile

| Setare | Mediu | Pagina Setări | Implicit | Efect |
|---|---|---|---|---|
| Zile de păstrare | `CAPTURE_RETENTION_DAYS` | `capture_retention_days` (1–30) | 7 | După câte zile se șterg imaginile |
| Limita 0 | `CAPTURE_RETENTION_DAYS=0` | nu se poate (minimul din pagină e 1) | — | Nu se mai scrie nicio imagine; imaginile existente se șterg la următoarea rulare |

Din mediu, `capture_settings()` acceptă 0–3650 zile (`max(0, min(days, 3650))`); valoarea
nevalidă devine 7. Valoarea din pagina Setări are prioritate; dacă rândul din tabela `settings` e
invalid, se folosește mediul (`admin_settings.effective`).

### 5.2 Când rulează

`captures.retention_loop` (pornit din `api.py`):

- prima rulare la **60 s** după pornire (`RETENTION_FIRST_DELAY_S`);
- apoi la fiecare **24 de ore** (`RETENTION_INTERVAL_S`);
- orice excepție se înregistrează în jurnal și bucla continuă.

### 5.3 Ce șterge `run_retention`

Condiția de selecție este:

```text
SELECT id, path FROM captures WHERE path IS NOT NULL AND captured_at < (acum − zile)
```

Pentru fiecare captură selectată:

- calea se validează cu `safe_path` (relativă, fără `..`, fără `\`, fără două puncte în primul
  segment, rezolvată în interiorul `CAPTURE_DIR`); dacă nu trece, fișierul **nu** este atins și
  referința din baza de date se șterge;
- fișierul se șterge; directoarele goale de zi, lună și an se elimină (`_prune_dirs`), fără să
  depășească `CAPTURE_DIR`;
- dacă fișierul lipsește deja, se numără ca „lipsă”;
- dacă ștergerea eșuează cu `OSError`, referința rămâne și se reîncearcă la rularea următoare;
- în toate cazurile `path` devine `NULL`, cu excepția cazului de eroare.

Rândurile din `captures` și `observations` **nu** se șterg.

**Nesigur, de notat**: coloana `expires_at` se scrie la înregistrare (`captured_at + zile`), dar
`run_retention` **nu o citește**; selecția se face după `captured_at`. Dacă schimbați retenția,
`expires_at` al capturilor vechi rămâne cel vechi. Verificare: `grep -n expires_at app/` (apare în
`observations.py`, `captures.py` pentru afișare și în schema tabelei).

### 5.4 Ce NU are retenție

| Ce | De ce nu e șters | Sursa |
|---|---|---|
| Rândurile `captures` | Doar `path` devine `NULL` | `run_retention` |
| Rândurile `observations` | Nu există nicio instrucțiune `DELETE FROM observations` în `app/` | `grep` pe `app/` |
| `LAST_IMAGE_PATH` | Este un singur fișier, suprascris de fiecare imagine nouă | `poller._save_image` |
| Cadrele respinse | Retenția lor este după număr (40), nu după vârstă | `rejected.REJECTED_KEEP` |
| Versiunile vechi de imagine din `shadow/run/` | Directorul se șterge la fiecare rulare de noapte | `nightly_shadow_train.run` |

**Poller-ul nu are cod de retenție.** `app/poller.py` doar apelează `on_capture` și salvează
cadrele respinse. Retenția este în `app/captures.py` (`run_retention`, `retention_loop`).

Creșterea bazei de date: README spune că observațiile cresc cu circa 30–40 MB pe zi și că
„compactarea câmpurilor `fields_json` vechi e planificată”. Nu am găsit în cod nicio compactare.
**Nesigur**: cifra de 30–40 MB/zi nu e verificabilă din repo; sursa ar fi măsurătorile de pe server.

### 5.5 De ce 7 zile

În cod nu este scris un motiv pentru valoarea 7. Documentația spune doar că este implicit.
**Nesigur**: fundamentarea (depanare, măsurare, setul de adevăr) nu este documentată.

## 6. Rândurile după retenție

După ce imaginea a fost ștearsă:

- capturile rămân în `captures` cu `path = NULL`. În lista administrării apar cu `has_image: false`
  (`captures.list_captures` → `_cap`);
- detaliul capturii și observațiile rămân accesibile din administrare;
- `GET /api/admin/captures/{id}/image` răspunde **404** cu mesajul „Imaginea nu mai este disponibilă
  (retenție expirată)” (`admin.capture_image`);
- overlay-ul (`/overlay.png`) are același 404, pentru că se desenează pe imaginea de pe disc
  (`admin.capture_overlay`). Overlay-ul **nu** se salvează: se generează la cerere;
- statisticile (`captures.capture_stats`) numără doar imaginile încă existente (`path IS NOT NULL`).

Observațiile rămân, deci și numărul de servicii, cataloagul `trains` și istoricul nu depind de imagini.
Asta înseamnă și că **datele OCR** (text brut, numere, ore, peroane) sunt păstrate pe termen nelimitat,
chiar dacă imaginea a dispărut. Acestea sunt date despre tablă, nu despre persoane.

## 7. Vederea de administrare

### 7.1 Rutele

Toate sunt sub `/api/admin` și trec prin `require_admin` (`app/admin.py`, `guarded = APIRouter(dependencies=[...])`):

| Rută | Ce întoarce |
|---|---|
| `GET /api/admin/captures?limit=&before=` | Lista (cel mult 200, implicit 50), cele mai noi întâi, cu contorul de linii pe panou |
| `GET /api/admin/captures/{cid}` | Detaliul: metadatele, toate observațiile, textul brut, `fields_json`, versiunea de linie |
| `GET /api/admin/captures/{cid}/image` | Imaginea originală, neschimbată (`Cache-Control: no-store`) |
| `GET /api/admin/captures/{cid}/overlay.png` | Imaginea cu dreptunghiuri pe celule, colorate după încredere (verde ≥ 80, galben ≥ 50, roșu sub 50) |
| `GET /api/admin/stats` | Spațiul liber pe disc, ultimele încercări de captură, durate, erori din 24 h, rânduri din 24 h, mărimea bazei, numărul de imagini |
| `GET /api/admin/settings` (citire) și `POST /api/admin/settings` (scriere, cu verificare CSRF) | Retenția și pragul de spațiu (valori fără secrete) |

Imaginile se servesc **doar** din administrare. În `app/api.py` nu există nicio rută de imagine (verificat
cu `grep -n "image" app/api.py`, rezultatele sunt doar referințe la `last_image_path`).

### 7.2 Autentificare

- Cheia este `ADMIN_TOKEN` din mediu (`/etc/tabela.env`, cu `chmod 600` conform `.env.example`).
  Nu este în baza de date.
- După login, cookie-ul de sesiune este `HttpOnly`, `Secure`, `SameSite=Strict`, cu durata de 12 ore
  (`admin.py`, docstring-ul de la început).
- Mod strict opțional: `ADMIN_TOKEN_STRICT=1` cere o cheie de cel puțin 24 de caractere
  (`STRICT_TOKEN_LEN`). Implicit oprit.
- Limitarea încercărilor eșuate se ține **în memorie**, pe IP și global (`_failures`, `_global_failures`);
  se resetează la repornire.

### 7.3 Jurnalul de audit

Tabela `correction_audit` (`corrections.py`) păstrează: `ts`, `actor`, `ip`, `action`,
`correction_id`, `batch`, `detail`. Acțiunile sunt: `create`, `apply`, `restore`, `delete`, `setting`.
**Adresa IP a administratorului este stocată aici**, pe termen nelimitat (nu există cod de ștergere
pentru această tabelă). Este singura adresă IP păstrată în baza de date.

## 8. Regula proiectului

Regula: **capturile reale ale tablei CFR sunt private**. Nu se urcă în repo, nu se publică și nu se redistribuie.
Sursele:

- `README.md` (secțiunea „Capturi și retenție”): „Capturile brute CFR sunt **private**: se văd doar din
  administrare și nu se redistribuie.”
- `app/captures.py` (docstring): „Raw CFR images are private (admin only) and never redistributed.”
- `tests/ocr_truth_images.py` (docstring): „Nicio captură reală nu e în git (repo public)”.
- `CHANGELOG.md`, Beta 1.43: „Nicio captură reală a tabelei nu mai e urmărită în git”. Istoricul git
  nu a fost rescris (aceeași notă).
- `.gitignore`: „capturi reale (repo public): imaginile setului de adevăr sunt locale”.

Regula se aplică și la date derivate: observațiile sunt textul tablei, nu imaginea, și nu conțin date
personale. Nu sunt însă descrise în documentație ca date de publicat în lot.

## 9. Ce este urmărit în git și ce este ignorat

### 9.1 Ignorat (`.gitignore`)

| Regulă | Ce acoperă |
|---|---|
| `tests/fixtures/ocr_truth/private/` | Imaginile setului de adevăr privat |
| `tests/fixtures/ocr_truth/**/*.jpg` | Orice JPEG din setul de adevăr |
| `tests/fixtures/**/*.jpg` | Orice JPEG din `tests/fixtures` |
| `data/*` (cu excepțiile `operators.txt`, `stations_seed.txt`) | `data/captures/`, `data/last.jpg`, `data/telegram_sent.json`, baze locale |
| `*.db`, `.env` | Baze de date și fișiere de mediu |
| `!tests/fixtures/*.db` | **Excepție**: bazele de test din `tests/fixtures/` sunt urmărite |

### 9.2 Urmărit și conținut relevant

Fișierele urmărite în `tests/fixtures/` (verificate cu `git ls-files`):

| Fișier | Ce conține | Observație |
|---|---|---|
| `board_1.json`, `board_2.json` | Rânduri de trenuri așteptate (text și numere) | Date despre tablă |
| `live_v2.db` | Bază SQLite de test: tabelele `runs`, `services`, `events`, `subscriptions`, `follows` | Am numărat rândurile: 2, 4, 5, 0, 0. Fără tabele `captures`/`observations`, fără abonări |
| `ocr_truth/truth.json` | 59 de cadre, 1416 linii etichetate | Date despre tablă; cheile de cadru conțin data și ora capturii (UTC) |
| `ocr_truth/holdout/holdout.json`, `README.md` | Setul de verificare (21 de cadre) | Idem |
| `ocr_truth/baseline-1.31.json`, `NOTE-2026-10-27.md` | Măsurători și note | Idem |
| **`page_1.html`** | **Pagina CFR salvată, care conține o imagine JPEG încorporată (base64)** | Vezi 9.3 |

### 9.3 Constatare: imagine încorporată în `tests/fixtures/page_1.html`

- Fișierul este urmărit în git și nu este acoperit de `.gitignore` (regula acoperă doar `*.jpg`).
- Conține un șir `data:image/jpg;base64,...` de circa 143 500 de caractere, care se decodează într-un
  JPEG valid de circa 107 700 octeți. Mecanismul este același ca în pagina CFR reală
  (`app/fetcher.py` extrage imaginea tablei din astfel de șir).
- Nu am descris conținutul imaginii și nu am salvat-o nicăieri.
- Fișierul este folosit de `tests/test_fetcher.py`, care îl citește ca text.
- **Nesigur**: dacă imaginea este o captură reală a tablei, ceea ce pare probabil după mecanism și
  dimensiune. Verificare umană necesară. Dacă da, regula din secțiunea 8 este încălcată, iar fișierul
  trebuie scos din git (decizia și eventuala rescriere a istoricului aparțin mantenitorului).
  Pentru test, imaginea ar putea fi înlocuită cu un JPEG generic, fără să schimbe logica testului.

## 10. Pentru contributori

### 10.1 Imaginile private locale

Repo-ul nu conține niciun JPEG. Pentru a rula testele care citesc cadre reale sau măsurarea OCR,
contributorul trebuie să aibă copiile locale, obținute din afara repo-ului (repo-ul nu descrie
procedura de obținere; **nesigur**: sursa și permisiunea trebuie stabilite de mantenitor).

Două locuri:

- `tests/fixtures/` pentru cadrele publice (`ocr12/`, `ocr13/`, `glare/`, `ocr14_delay100/`, `board_1.jpg`, …);
- `OCR_TRUTH_DIR` (implicit `tests/fixtures/ocr_truth/private/`) pentru cheile `ocr_truth/...` din `truth.json`
  și `holdout/...`.

### 10.2 Cum se comportă codul când imaginea lipsește

`tests/ocr_truth_images.py`:

- `frame_path(cheie)`: cheile `ocr_truth/<cale>` se caută în `PRIVATE/<cale>.jpg`; restul în `FIX/<cheie>.jpg`;
- `capture(cale)`: dacă fișierul lipsește, testul **sare** (`pytest.skip`) cu un motiv care spune unde
  să fie fișierul și sugerează `OCR_TRUTH_DIR` dacă directorul privat e cel implicit;
- `read_frame(cheie)`: `capture` + citirea octeților.

Scripturile au aceeași logică, dar fără sărituri, ci cu raportare:

- `scripts/ocr_eval.py` (`_image`): `IMG_DIR` explicit sau, pentru `ocr_truth/...`, `OCR_TRUTH_DIR`;
- `scripts/ocr_digit_clf.py` (`_truth_image`): caută mai întâi în `TRUTH_IMG_DIRS` (setat de noaptea
  umbră la `WORKDIR/truth-img`), apoi lângă `truth.json` (`tests/fixtures/`), apoi în `ocr_truth/private/`.
  Un cadru negăsit este numărat în raport (`frames_missing`), nu oprește rularea.

### 10.3 Ce nu trebuie să ajungă în repo

- Imagini ale tablei sub orice nume (inclusiv în `tests/fixtures/*.html` încorporate, vezi 9.3).
- Glife extrase din cadre reale, ca fișiere (rezultatele `ocr_digit_clf extract` stau în `OUT_DIR`, care
  trebuie să fie în afara repo-ului; `nightly_shadow_train` refuză un `WORKDIR` din repo).
- Capturi exportate din baza de date (fișiere `export.json` cu căi), sau baza `tabela.db` / copiile ei.

## 11. Pe server

### 11.1 Directorul de antrenare umbră

`deploy/tabela-shadow-train.service` rulează `scripts/nightly_shadow_train.py` ca utilizatorul `tabela`:

- `ReadWritePaths=/var/lib/tabela` (singurul loc scriibil), `ReadOnlyPaths=/opt/tabela`,
  `ProtectSystem=strict`, `ProtectHome=true`, `PrivateTmp=true`, `NoNewPrivileges=true`;
- baza de date se deschide în mod `ro` (`export_db`), cu `file:...?mode=ro`; scriptul nu scrie în ea;
- `_check_workdir` refuză un director de lucru în repo;
- `TIME_LIMIT_S = 2 h` (alarmă `SIGALRM` și limită în service).

Ce scrie în `/var/lib/tabela/shadow`:

| Fișier | Conținut | Imagini? |
|---|---|---|
| `export.json` | Căi de capturi și observații (`fields_json`) | Nu, dar conține numele fișierelor de imagine |
| `run/` | Glife (matrici 32×32), etichete, cache (`run/cache/*.pkl`) | Fără imagini întregi, dar fragmente de cadre reale; se șterge la fiecare rulare |
| `model-AAAA-LL-ZZ.npz` | Greutățile MLP-ului | Nu |
| `report-AAAA-LL-ZZ.json` | Numere, decizia, limitele, calea setului de adevăr | Nu |
| `truth-img/<cadru>.jpg` | Imaginile setului scris de mână (copiate manual pe server) | **Da**, private |

Imaginile de antrenare se citesc din `IMG_ROOT/captures/<cale>` (implicit `/var/lib/tabela/captures`).
Setul scris de mână este `tests/fixtures/ocr_truth/truth.json` din repo, sau `WORKDIR/truth.json`.
Cadrele fără imagine în `truth-img/` sunt sărite și numărate în raport (`set_adevar_cadre`), iar
rularea continuă (CHANGELOG, Beta 1.43).

### 11.2 Programarea

`deploy/tabela-shadow-train.timer`: `OnCalendar=*-*-* 03:30:00`, `Persistent=true` (o rulare ratată
se face la pornirea următoare). Ora este cea a sistemului.

### 11.3 Ce se întâmplă cu fișierele vechi

- `truth-img/` nu este șters de script; îl administrează omul.
- `model-*.npz` și `report-*.json` se acumulează (câte unul pe zi). **Nesigur**: nu am găsit cod de curățare.

## 12. Datele personale stocate

Aplicația nu are tabel de utilizatori și nu are conturi (verificat: lista `CREATE TABLE` din `app/`).
Datele personale sau identificatoare sunt cele de mai jos.

| Dată | Unde | Ce conține | Cât timp | Cine o vede | Sursă |
|---|---|---|---|---|---|
| Abonare push | `subscriptions` | `endpoint` (adresa serviciului de notificări al browserului), `p256dh`, `auth` (chei criptografice), `created_at` | Până la dezabonare sau la răspuns 404/410 de la serviciu | Doar în baza de date și în codul serverului | `store.subscribe`, `store.unsubscribe`, `notifier.one` |
| Urmărire tren | `follows` | `subscription_id`, `train_no`, `service_date` | Urmăririle mai vechi de ieri se șterg leneș, când aceeași abonare adaugă o urmărire nouă (`store.follow`) | Idem | `store.follow`, `store.followers` |
| Adresa de push în browser | `localStorage` al vizitatorului (`web/follows.js`) | Același endpoint de push, păstrat pe dispozitiv | Până la ștergerea datelor browserului | Doar pe dispozitivul utilizatorului | `web/follows.js` (comentariul din fișier: „the only thing kept on the device is the push subscription endpoint”) |
| Chat Telegram al administratorului | **Nu** în baza de date; în variabila de mediu `TELEGRAM_CHAT_ID` | Identificatorul chatului | Cât timp e setat mediul | Serverul și administratorul | `telegram.config_from_env` |
| Starea alertelor Telegram | `data/telegram_sent.json` | Chei de eveniment și data serviciului (fără numele vizitatorului) | Azi și ieri | Serverul | `telegram.SentLog` |
| Adresa IP a administratorului | `correction_audit.ip` | IP-ul clientului, la acțiuni de corecție și setări | Nelimitat | Administrare | `corrections.audit`, `admin._ip` |
| Limitarea exporturilor | În memorie | IP-ul, cu o fereastră de timp | Până la repornire | Nimeni | `export.LIMITER` |
| Limitarea încercărilor de login | În memorie | IP-ul și contorul | Până la repornire | Nimeni | `admin._failures` |

Observații:

- **Endpoint-ul de push** identifică un browser sau un dispozitiv. Îl tratez ca dată personală, pentru
  că este cheia de livrare a notificărilor către acel dispozitiv. Serverul acceptă doar adrese ale
  serviciilor push cunoscute (`app/endpoints.py`: FCM, Mozilla, Apple, Windows notify), prin HTTPS, fără
  utilizator și fără port neobișnuit.
- Endpoint-ul ajunge în cerere ca parametru în query string (`/api/follows?endpoint=...`). Configurația nginx
  dezactivează jurnalul de acces pentru această locație (`deploy/nginx-tabela.conf`, cu comentariul „never
  write it to the access log”).
- **Jurnalele nginx pentru alte locații** pot conține adrese IP ale vizitatorilor. Configurația globală
  de acces nu este în repo (`nginx.conf` de pe server). **Nesigur**: de verificat pe server.
- `correction_audit` păstrează IP-ul administratorului. Scopul este auditul, nu statistica.
- Numărul de urmăriri active per abonare este limitat la `MAX_FOLLOWS = 20` (`app/store.py`; docstring-ul lui `follow` spune că doar urmăririle de azi sau de mâine intră în limită).

## 13. Ce nu se stochează

Verificat în cod:

- **Nu se stochează nume, e-mailuri, numere de telefon sau conturi** ale vizitatorilor (nu există tabele pentru ele).
- **Nu se stochează IP-ul vizitatorilor publici** în baza de date. IP-urile apar doar în memorie (limitări)
  și în auditul administrării (vezi 12).
- **Nu se stochează cheia de administrare** în baza de date sau în browser (`CHANGELOG`, Beta 1.40: „Cheia nu se salvează în browser”).
- **Nu se stochează tokenul Telegram**: `telegram.TelegramConfig` are `token` cu `repr=False`, iar
  documentația modulului spune că tokenul nu apare în log și nu este returnat.
- **Nu se stochează octeții imaginii în observații**: observațiile conțin text.
- **Overlay-ul nu se salvează**: se generează la cerere (`captures.overlay_png`).
- **Nu se scriu endpoint-urile de push în jurnalul aplicației**: mesajele din `notifier.py` spun „push
  subscription gone; removing” și „push failed: <tip>: <mesaj>”. **Nesigur**: mesajele excepțiilor librăriei
  de push ar putea include URL-ul; de verificat pe jurnalele reale.
- **Serverul nu trimite date către terți** decât sursei CFR, serviciilor push, Telegram (când e activat) și
  Open-Meteo pentru meteo (`app/weather.py`, date de model, fără date personale). Verificat în `app/`; fișierele
  din `web/` nu le-am verificat pentru resurse externe. **Nesigur** pentru front-end.

## 14. Lista de verificare

Lucruri de verificat de un om, în ordinea priorității:

1. **`tests/fixtures/page_1.html`**: dacă imaginea încorporată este o captură reală (secțiunea 9.3).
   Dacă da, decizia de a o scoate din git și de a rescrie istoricul aparține mantenitorului.
2. **Jurnalele nginx de pe server** (configurația globală de acces, secțiunea 12).
3. **Mesajele excepțiilor de push în jurnal** (secțiunea 13).
4. **`expires_at`** față de retenție (secțiunea 5.3).
5. **Cifra de 30–40 MB/zi** pentru observații (secțiunea 5.4), din măsurători reale.
6. **Motivul valorii de 7 zile** (secțiunea 5.5), dacă există în alt document.
7. **Curățarea modelelor și rapoartelor vechi** din `shadow/` (secțiunea 11.3).
8. **Procedura de obținere a imaginilor private** pentru contributori (secțiunea 10.1), dacă trebuie documentată.
