# Istoric versiuni — Tabela Gara de Nord

Schema versiunilor: `Beta 1.NN`, unde NN crește cu 1 la fiecare deploy pe
tabelacfr.ddns.net. Cele mai noi versiuni sunt sus.

© 2026 Andy217Ace · Date preluate de la CFR (cfr.ro) — proiect independent, neafiliat CFR

## Beta 1.01 — 2026-10-21

### Adăugat
- Panou LIVE cu sosiri și plecări citite de pe tabela CFR, actualizat sincron cu sursa; mod „Panou” (afișaj de gară, ecran complet) și mod „Carduri”.
- Istoric pe zile: filtre după tren, stație, interval orar și panou; detaliu cu evenimentele fiecărui tren și numărul de schimbări observate.
- Urmărirea trenurilor cu notificări push (întârziere, linie, dispariție de pe tabelă); lista „Urmărite” arată „necitit” când întârzierea nu s-a putut citi.
- Aplicație instalabilă (PWA): funcționare offline cu ultima tabelă marcată ca veche, pagină offline.
- Temă luminoasă / întunecată / automată, fără clipire la încărcare.
- Sigla Gara de Nord peste tot: antet, favicon, iconițe PWA, imagine de previzualizare, footer.
- Ceas cu secunde (HH:MM:SS, ora României, cifre tabulare) în antet și în Panou; widget meteo (Open-Meteo, valori de model, nu de stație) lângă ambele ceasuri, cu marcaj „date vechi”; `/api/weather`.
- Capturi OCR: fiecare imagine a tabelei e păstrată 7 zile, cu observațiile pe fiecare rând (text brut, încredere, stare de validare) și o pagină de administrare `#ocr` protejată prin cheie (cu limitare a încercărilor).
- Catalog de trenuri public: `/api/trains`, `/api/trains/{nr}`.
- Versiunea aplicației în footer și pagina „Versiuni” (`#versiuni`, `/api/changelog`); câmpul `version` în `/api/health`.

### Bază de date
- Migrare schema v4: tabelul `weather_observations`.
- Migrare schema v5: tabelele `captures`, `observations`, `trains` (catalogul se reconstruiește din istoricul existent). Migrările sunt aditive, fiecare pas atomic; datele istorice nu se șterg.

### Reparat
- O întârziere care nu s-a putut citi nu mai apare ca 0 / „la timp” și nu declanșează notificări.
- OCR: stații distincte nu mai sunt contopite; operatorii și stațiile sunt canonicalizate, cele corectate sunt marcate nesigure.
- Footerul de atribuire apărea de două ori pe desktop în modul Panou; acum e afișat o singură dată (creditul din Panou apare doar în ecran complet).
- Deploy: backup al bazei de date, verificare de sănătate și revenire automată la versiunea anterioară dacă verificarea eșuează.
