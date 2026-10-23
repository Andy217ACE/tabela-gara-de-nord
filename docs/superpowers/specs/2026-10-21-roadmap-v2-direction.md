# Direcția produsului (v2) — sosiri, plecări, istoric, statistici, meteo

Sursa: două documente de instrucțiuni ale proprietarului (Andy217Ace), 2026-10-21. Acest fișier le traduce în
etape peste ce există deja în repo. Prioritatea absolută: **panou LIVE rapid, stabil, lizibil, corect**.

## Principii (din instrucțiuni, obligatorii)
- LIVE e pagina implicită și dominantă; fără dashboard generic în față.
- Tesseract rămâne motorul OCR principal; OCR-ul stă în spatele unei interfețe (`OcrEngine`) înlocuibile.
- Date citite ≠ date calculate/estimate; nimic inventat; valoare lipsă ≠ 0; date vechi marcate vizibil.
- O călătorie ≠ un număr de tren ≠ o observație. Statisticile arată mereu numărul de călătorii din spatele cifrelor.
- Fără ștergeri de date; migrații versionate; backup + restaurare documentate; secrete doar în env.
- Corelație ≠ cauzalitate (meteo); predicțiile se evaluează temporal, fără scurgeri din viitor.
- Atribuire: © 2026 Andy217Ace · date preluate de la CFR (cfr.ro), proiect independent.

## Ce există deja (v1, branch feat/app)
Poller sincronizat pe faza sursei; OCR (Tesseract + OpenCV + template matching pe cifre); SQLite cu `services`
(≈ călătorii) + `events`; sosiri ȘI plecări (`board`); API FastAPI; UI LIVE (carduri, dark/light, tab-uri);
notificări Web Push cu debounce; istoric (`history`, `train_events`); HTTPS pe tabelacfr.ddns.net.

## Diferențe față de instrucțiuni (decizii)
| Cerință nouă | Situația acum | Decizie |
|---|---|---|
| Panou cu aspect de afișaj de gară, coloane (oră, tren, rută, operator, întârziere, linie, mesaj) | carduri moderne | Adăugăm **mod „Panou"** (tabel pe rânduri/coloane, font mono, stil afișaj) ca vizualizare implicită pe desktop; cardurile rămân pe mobil |
| Interval implicit 60 s | phase-locked (≈1 cerere/min, latență 2–3 s) | Păstrăm (respectă „nu capturi concurente"); intervalul devine configurabil |
| Salvare text brut OCR, coordonate, scoruri pe câmp, referință imagine | doar valori normalizate + confidence rând | Tabel nou `observations` (migrație v3): raw text, bbox, scor/câmp, hash/cale imagine, versiune procesare |
| Catalog tren / călătorie / observație | doar `services` + `events` | Tabel `trains` (catalog) + `services`=călătorii + `observations` |
| Imagini păstrate cu retenție | doar ultima | Retenție configurabilă, implicit scurtă (7 zile) și **doar referințe în DB**; datele structurate se păstrează permanent. (Redistribuirea imaginilor CFR rămâne exclusă.) |
| Pagini: Toate trenurile, Istoric, Statistici, Clasamente, Alerte, Predicții, Capturi OCR, Stare sistem, Setări, Meteo | doar LIVE + placeholder-uri | Etapele B–G de mai jos |
| Alerte configurabile + Telegram opțional | push cu debounce | Motor de reguli peste `events`; Telegram opțional prin env |
| Admin protejat, export CSV/JSON, backup | — | Etapa F; autentificare pentru tot ce e administrativ |
| Meteo + analiză sezonieră | — | Etapa G (sursă de verificat înainte: Open-Meteo — observații/istoric, licență CC BY 4.0, uz necomercial gratuit) |
| Predicția liniei | — | Etapa H, doar după date suficiente |

## Etape (peste v1), în ordine
- **A. Stabilizare + LIVE-Panou** (acum): deploy v1, `OcrEngine` interface, mod Panou, operator/stație canonice (fuzzy
  pe liste cunoscute) — „zgomotul" OCR vizibil (ex. „“Mransferoviar") dispare; Istoric + Urmărite + PWA (Task 11).
- **B. Observații + migrații**: `observations`, `trains`, versiune procesare, retenție imagini, modul debug (imagine + dreptunghiuri).
- **C. Călătorii & rezultat final**: reguli de închidere a călătoriei (fără a trata dispariția de pe panou ca dovadă),
  `final_confirmed`, evoluția întârzierii pe grafic.
- **D. Catalog + profil tren + Statistici/Clasamente**: eșantion minim configurabil, mediană/percentile, N afișat.
- **E. Alerte + monitorizare**: reguli, cooldown, jurnal, Telegram opțional; pagina Stare sistem; watchdog.
- **F. Export, backup/restaurare, Setări, autentificare admin, `.env.example`**.
- **G. Meteo** (`direction` deja există ca `board`): serviciu separat, observație vs prognoză, UTC, intervale T-0/T-1..3h/T-6h/zi,
  anotimpuri (mar–mai etc.), pagina „Meteo și trenuri", analiză descriptivă apoi modele cu avertisment de corelație.
- **H. Predicția liniei**: frecvențe istorice → model de bază → evaluare temporală → afișare „Linie estimată — neconfirmată".

Fiecare etapă: spec scurt → plan → implementare pe subagenți cu review → deploy.
