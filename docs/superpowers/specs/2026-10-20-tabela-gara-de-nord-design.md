# Tabela Gara de Nord — design

Data: 2026-10-20 · Stare: ciornă pentru aprobare

## Scop
O aplicație publică, instalabilă (PWA) pe web și pe telefon, care arată online tabela de
sosiri și plecări din Gara de Nord București, extrasă prin **OCR clasic (fără AI)** din
poza webcam publicată de CFR, cu:
1. tabelă live (sosiri / plecări);
2. urmărirea unui tren cu notificări push la schimbări (întârziere, linie, apariție/dispariție);
3. istoric căutabil în baza de date: ce trenuri au circulat într-o anumită zi, la ce oră,
   ce întârzieri au avut.

Public țintă: oricine. Fără domeniu în prima etapă.

## Sursa de date
`https://cfr.ro/gari/camereweb/index.php?statie=BucurestiNord`

- Pagina conține o singură poză JPEG (~1100×350), încorporată ca `data:image/jpg;base64,...`
  în HTML; pagina se reîncarcă singură la 60 s.
- Stânga = SOSIRI, dreapta = PLECĂRI. Fiecare arată următoarele ~10–12 trenuri.
- Coloane fixe: tip (IR, RE, R, RM, IRN…, uneori prefix `*`), număr, sosește de la /
  pleacă la, operator, oră, întârziere (`+10`), linie.
- Text alb/galben pe albastru; peste poză e un watermark roșu „www.cfr.ro".
- Poza este doar intrare pentru OCR; nu o publicăm și nu o stocăm (în afară de ultima, pentru
  depanare).

Notă: sursa e un serviciu CFR neoficial pentru acest scop. Interogăm cel mult 1×/minut,
cu User-Agent identificabil, și nu redistribuim imaginea.

## Arhitectură
Un singur server (Azure Ubuntu 24.04), un proces backend, SQLite.

```
CFR webcam page ──(1/min)──► poller ──► OCR ──► diff ──► SQLite ──► API ──► PWA
                                                   └──► Web Push (abonați care urmăresc trenul)
```

Unități (fiecare testabilă separat):

| Unitate | Rol | Depinde de |
|---|---|---|
| `fetcher` | descarcă pagina, extrage JPEG-ul din base64, sare peste dacă hash-ul e identic | HTTP |
| `ocr` | imagine → listă de rânduri structurate (sosiri + plecări) | OpenCV, Tesseract |
| `normalize` | validează/corectează câmpurile (regex pe tip/număr/oră/întârziere, listă de stații văzute) | — |
| `store` | upsert în SQLite, produce evenimente de schimbare | SQLite |
| `notifier` | evenimente → Web Push către abonații trenului | pywebpush |
| `api` | REST: tabela curentă, istoric, abonări | store |
| `web` | PWA: tabelă, căutare istoric, urmărire, instalare | api |

Stack: Python 3.12, FastAPI, Tesseract (`ron`+`eng`), OpenCV, SQLite (WAL), pywebpush.
Frontend: HTML/JS simplu, service worker + manifest (fără framework).
Rulare: systemd (backend) + nginx (reverse proxy, TLS ulterior).

## OCR (fără AI)
1. Decupare în două jumătăți (sosiri / plecări) cu coordonate calibrate, apoi decupare în
   benzi de rânduri.
2. Mască de culoare în HSV: păstrează pixelii deschiși (alb/galben), elimină roșul
   watermark-ului și albastrul fundalului → text negru pe alb, mărit ×3.
3. Pe fiecare rând, decupare pe coloane fixe; Tesseract pe fiecare celulă cu whitelist
   specific (cifre pentru oră/număr/întârziere/linie, litere mari pentru tip; text liber
   pentru stație/operator).
4. Normalizare: oră `HH:MM`, întârziere `+N` (absentă = la timp), linie întreagă sau
   absentă, tip din lista cunoscută.
5. Rânduri cu încredere mică sunt marcate și nu declanșează notificări.
6. Dacă preciziunea pe câmpurile numerice nu e suficientă, trecem la potrivire de
   șabloane pe glifele fontului panoului (font fix) — extensie, nu parte din prima etapă.

Calibrarea se face pe poze reale salvate ca fixturi de test (golden files cu rezultatul
așteptat scris de mână).

## Model de date (SQLite)
- `runs(id, ts, image_hash, ok, n_rows)` — fiecare ciclu de citire.
- `services(id, board, service_date, train_type, train_no, station, operator,
  sched_time, first_seen, last_seen, last_delay, last_platform, status)`
  — un rând per tren/zi/panou (`board` = `arrival|departure`); cheia naturală:
  `(board, service_date, train_no, sched_time)`.
  `status`: `listed | gone`.
- `events(id, service_id, ts, kind, old, new)` — `kind`: `delay`, `platform`,
  `appeared`, `gone`.
- `subscriptions(id, endpoint, p256dh, auth, created_at)` — Web Push.
- `follows(subscription_id, train_no, service_date)` — ce tren urmărește cine.

Istoricul se construiește din `services` + `events`: pentru o zi, ce trenuri au apărut,
la ce oră, cu ce întârziere finală și maximă, pe ce linie. Păstrat nelimitat (volum mic).
Data serviciului se deduce din ora Europe/Bucharest; trenurile după miezul nopții se
atribuie zilei corecte prin ora programată.

## API
- `GET /api/board` — tabela curentă (ambele panouri) + `updated_at`.
- `GET /api/history?date=YYYY-MM-DD&train=&station=&board=&from=HH:MM&to=HH:MM`
- `GET /api/train/{no}?date=` — istoric complet al unui tren într-o zi (evenimente).
- `POST /api/push/subscribe`, `POST /api/push/unsubscribe`
- `POST /api/follow`, `DELETE /api/follow`
- `GET /api/health` — vârsta ultimei citiri reușite.

## Frontend (PWA)
- Ecran principal: tab-uri Sosiri / Plecări, actualizare automată, indicator „actualizat
  acum X s"; buton „urmărește" pe fiecare tren.
- Ecran Istoric: alegere zi, filtre (număr tren, stație, interval orar), listă cu
  oră programată, întârziere maximă/finală, linie.
- Ecran Urmărite + setări notificări.
- Instalabil (manifest + service worker, offline: ultima tabelă din cache, marcată ca veche).
- Limba: română.

## Notificări push
- Tip: Web Push cu chei VAPID. Declanșatori pentru trenurile urmărite: întârziere
  modificată, linie atribuită/schimbată, tren dispărut de pe panou.
- Debounce: o notificare per schimbare confirmată în 2 citiri consecutive (evită OCR instabil).
- **Etapa 1 fără domeniu:** codul push este implementat, dar nu poate fi testat de la un
  telefon fără HTTPS. Testarea se face când există adresă HTTPS (vezi mai jos); până atunci,
  logica e acoperită de teste automate cu un push-endpoint simulat.

## Acces fără domeniu
- Etapa 1: aplicația servită pe `http://20.215.34.94` pentru tabelă și istoric (funcționează
  în browser fără PWA/push).
- Instalare ca aplicație și push cer HTTPS. Când vrem să le activăm: `20-215-34-94.sslip.io`
  sau o etichetă DNS Azure + Let's Encrypt (nginx); apoi domeniu propriu. Nicio schimbare de
  cod, doar configurare nginx.

## Public, deci
- Rate limit pe API (nginx) și pe abonări push.
- Fără conturi, fără date personale: abonarea push e anonimă (endpoint-ul browserului).
- Poller unic server-side: numărul de utilizatori nu crește încărcarea pe CFR.

## Gestionarea erorilor
- Pagina CFR indisponibilă sau poza veche/identică: păstrăm ultima stare, `updated_at` nu
  avansează, UI arată „date vechi de X min".
- OCR dă prea puține rânduri (< prag) sau rânduri invalide: ciclul se marchează `ok=0`,
  nu modifică `services` și nu trimite notificări.
- Log structurat per ciclu; `/api/health` pentru monitorizare.

## Testare
- Teste unitare `normalize` (regex, corecții).
- Teste OCR pe fixturi reale (poze salvate + JSON așteptat), cu prag de acuratețe pe câmp.
- Teste `store`/diff: secvențe de citiri → evenimentele corecte.
- Teste API cu SQLite în memorie; test `notifier` cu endpoint push simulat.
- Smoke test pe server după deploy.

## În afara etapei 1 (YAGNI)
Alte gări, conturi de utilizator, e-mail/SMS, potrivire de șabloane pe glife (doar dacă
Tesseract nu ajunge), statistici agregate/grafice, domeniu propriu.

## Deploy
Backup înainte de orice modificare pe server, instalare dependențe (tesseract-ocr, ron),
serviciu systemd, nginx, firewall (80/443). Credențialele serverului nu intră în repo.
