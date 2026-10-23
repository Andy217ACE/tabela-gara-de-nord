# Statistici v2 — design (2026-10-22)

© 2026 Andy217Ace

Cerere: „refă pagina de statistici, mai explicativă, date mai interesante, grafice mai bune
și mai relevante”. Utilizatorul a delegat deciziile de design (fără aprobări intermediare).

## Scop și criterii de reușită

- Pagina `#statistici` răspunde la întrebări concrete („Cât de des ajung trenurile la timp?”,
  „La ce oră întârzie cel mai mult?”, „Ce linii se folosesc?”), nu doar afișează cifre.
- Sus: un rezumat în cuvinte generat din date, cu perioada și calitatea datelor.
- Fiecare grafic: titlu-întrebare, frază „Cum se citește”, legendă (≥ 2 serii), N, avertisment
  de eșantion, tabel accesibil („Vezi datele”) și export CSV.
- Regulile produsului: citit ≠ estimat; lipsă ≠ 0; N lângă orice cifră; sub
  `STATS_MIN_SAMPLE` fără procente; punctual = ≤ `ON_TIME_MAX_MIN`; fantome și perioada
  low_quality excluse; corelație ≠ cauzalitate; trenuri ≠ călătorii ≠ observații.
- O singură cerere pe încărcare: `GET /api/stats/overview` (zona nginx `tabela_stats`).
- Statisticile nu blochează lock-ul store-ului OCR: conexiune SQLite read-only separată +
  cache TTL 60 s.

## Arhitectură

- `app/stats_overview.py` (nou):
  - `fetch(store, p, extra)` — rânduri de călătorii (JOURNEY_SQL) + meteo + numărători de
    excluderi și observații, pe o conexiune `file:…?mode=ro` (fallback: conexiunea store-ului
    sub lock, doar pentru `:memory:` în teste).
  - `build(rows, weather, extra, p, today)` — funcție pură, produce tot JSON-ul.
  - `overview(store, p)` — cache TTL (`STATS_CACHE_TTL_S`, implicit 60, max 32 chei), calcul
    serializat (un singur calcul simultan → fără „stampede”).
  - `to_csv(data, set)` — export pe set.
- `app/stats_api.py`: `GET /api/stats/overview` cu `perioada` (`1`|`7`|`30`|`all`, implicit
  `all`), `board`, `operator`, `tip`, `doar_confirmate`, `prag`, `min`, `from`/`to`,
  `format=csv&set=…`. `/api/stats` rămâne (compatibilitate).
- `web/statistici.js` + `web/statistici.css` (noi) înlocuiesc vizualizarea `statistici` din
  `stats.js` (care rămâne pentru #trenuri/#tren/#clasamente/#statii/#statie).

## Conținut (ordinea paginii)

1. Filtre (un rând, sus): Perioadă (Azi / 7 zile / 30 zile / Tot istoricul — butoane
   segmentate), Panou (Ambele / Sosiri / Plecări), Operator, Tip tren, „Doar rezultate
   confirmate”. Selecția în URL (`#statistici?perioada=7&board=arrival`).
2. „Pe scurt”: propoziții generate pe server (`insights`), linie de acoperire (perioadă,
   zile de istoric, călătorii, trenuri, observații, excluse) și banner „date insuficiente
   încă — X zile de istoric” sub 7 zile.
3. Carduri pe panou: % la timp (cifra principală, sau „—” sub eșantion cu cifre brute),
   mediană, medie, p90, N.
4. Grafice:
   - Distribuția întârzierilor (0 / 1–5 / 6–15 / 16–30 / 31–60 / > 60), coloane grupate.
   - Întârzierea pe ora programată: linie mediană + medie în tooltip, puncte goale sub eșantion,
     bandă separată cu N pe oră (fără axă dublă).
   - Hartă de căldură oră × zi a săptămânii (medie), small multiples pe panou, celule sub
     eșantion gri; legendă cu 5 clase.
   - Evoluția pe zile: % la timp pe zi (linie, goluri sub eșantion) + bandă N.
   - Operatori și tipuri de tren: bare orizontale „% la timp” cu N; sub eșantion rând gri
     cu cifre brute.
   - Rute (stații de origine/destinație): cele mai întârziate / cele mai punctuale (N ≥ min).
   - Aglomerația pe ore: trenuri programate pe oră (medie pe zi), sosiri vs plecări.
   - Liniile (peroanele): câte călătorii pe fiecare linie, sosiri/plecări; „linie necitită”
     separat (nu 0).
   - Meteo și întârzieri: doar cu ≥ 7 zile cu meteo asociat și ≥ 2 grupe cu N ≥ min;
     altfel „în curs de adunare” cu numărătorile; avertisment corelație ≠ cauzalitate.
   - Calitatea datelor: rezultate (confirmat / neconfirmat / necunoscut / în desfășurare),
     citirea OCR (ok / nesigur / respins / incomplet), excluse (fantome, calitate redusă).
5. Glosar și export (JSON complet + CSV pe set).

## Design vizual

- Culori de serie (validate cu `validate_palette.js`, ambele teme): sosiri = albastru
  (`#1f5fb8` / `#4a96e6`), plecări = chihlimbar (`#965200` / `#c97d12`); harta de căldură =
  rampă secvențială dintr-o singură nuanță (violet `--t-irn` amestecat cu suprafața).
- Tokenuri noi în `style.css` (`--c-arr`, `--c-dep`, `--c-seq`), toate temele.
- Bare ≤ 24 px, capăt rotunjit; linii 2 px; markeri r ≥ 4 cu inel de suprafață; grilă
  hairline solidă; text în tokenuri de text, niciodată în culoarea seriei; etichete directe
  selective.
- SVG construit în JS (createElementNS + clase), lățimea = lățimea containerului, re-randare
  la redimensionare; fără style=, fără scripturi inline (CSP).
- `prefers-reduced-motion`: fără tranziții.

## Rulings (decizii delegate)

- R1: Mediana (nu media) pe grafice pe ore — robustă la câteva întârzieri foarte mari; media
  rămâne în tabel/tooltip.
- R2: Meteo afișat doar după 7 zile cu date asociate (evită „corelații” din 2 zile în care
  temperatura urmează ora din zi).
- R3: Perioada implicită = tot istoricul (istoricul e scurt).
- R4: Tooltipuri native (`<title>`) + tabel „Vezi datele” pentru tastatură/cititoare de ecran,
  în loc de tooltip custom.
- R5: Aglomerația și liniile numără toate călătoriile publice (nu doar cele cu întârziere
  citită); întârzierile doar pe cele încheiate cu întârziere citită.
