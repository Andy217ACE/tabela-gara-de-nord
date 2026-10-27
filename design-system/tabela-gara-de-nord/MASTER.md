# Tabela Gara de Nord — sistem de design (MASTER)

> Sursa de adevăr pentru aspectul aplicației (Beta 1.20, „UI2"). Paginile pot avea
> suprascrieri în `design-system/tabela-gara-de-nord/pages/<pagina>.md`; dacă lipsesc, se aplică
> doar acest fișier. Implementarea: `web/style.css` (tokeni + shell + carduri + pagini),
> `web/panel.css` (Panoul LIVE), `web/weather.css`, `web/stats.css`, `web/statistici.css`, `web/ocr.css`.

## 1. Direcție

Produs public de informare feroviară. **LIVE (Tabelă: Panou / Carduri) e prioritar și dominant.**
Estetică de afișaj de gară modern, foarte lizibil: fundal slate întunecat + temă luminoasă la
paritate, ambră de panou de gară pentru ore, linie și selecție. Stil: *flat* (fără gradiente,
fără glassmorphism pe tabel; umbre doar pe straturi suprapuse), densitate mare pe desktop,
ținte tactile de 44 px pe mobil.

Recomandări din `ui-ux-pro-max` folosite: stil Flat Design (risc a11y mic, cost de performanță
mic), perechea tipografică „Dashboard Data" (Fira Code + Fira Sans), paleta slate pentru
panouri de stare/IoT (fundal `#0F172A`), regulile UX pentru stări de încărcare (schelet stabil,
`aria-busy`), insigne live (un singur `role=status` cu text complet), animații 150–300 ms.
Respins din generator: tipografia Lexend Mega/Public Sans (neubrutalist — nu se potrivește),
GSAP/scroll reveal (fără biblioteci; mișcare minimă pe un afișaj live).

## 2. Principii de date (vizibile în UI)

| Regulă | Cum arată |
|---|---|
| citit ≠ estimat | ora estimată (programată + întârzierea citită) apare doar când întârzierea a fost citită; programata rămâne tăiată dedesubt |
| lipsă ≠ 0 | întârziere necitită = „necitit" gri (iconiță ceas), niciodată „la timp"; linie neanunțată = „—" gri |
| verde doar din citire | `ok`/„la timp" numai cu `delay_read === true` (testat în `test_brand_theme.py`) |
| N afișat | statisticile arată N și eșantionul minim; sub prag — „—" + notă |
| date vechi marcate | `.pnl[data-fresh=stale|offline]` → toate nivelurile devin gri + chip „DATE VECHI"; un singur panou vechi e marcat separat |

## 3. Tokeni — trei straturi

1. **Primitive** (`--ref-*`, în `html {}` din `style.css`): singurul loc cu valori hex/rgba.
   Slate 0…925, ambră 400/800/950, galben, portocaliu, verde, roșu, albastru, violet, teal, lime,
   culorile de grafic (validate CVD) și câteva transparențe (scrim, umbre, bara de navigare).
2. **Semantice** (în `:root` = întunecat; redefinite în `@media (prefers-color-scheme: light)
   :root:not([data-theme="dark"])` și în `:root[data-theme="light"]` — cele două blocuri luminoase
   sunt identice): `--bg --surface --surface-2 --surface-hover --border --border-strong
   --field-border --text --text-2 --text-3 --accent --accent-ink --time --focus --ok(-bg)
   --warn(-bg) --bad(-bg) --info --unknown --board-* --lvl-* --t-* --c-* --shadow
   --shadow-overlay --scrim --nav-bg`.
3. **Componente**: `--btn-*`, `--card-*`, `--chip-bg`, `--field-bg` (în `html {}`) și tokenii
   Panoului `--p-*` din `.pnl {}` (`panel.css`), care sunt **doar referințe** la semantice.

Componentele nu conțin culori brute (verificat cu
`node ~/.claude/skills/design-system/scripts/validate-tokens.cjs -d web`: hex doar în stratul
primitiv și în `theme-init.js` pentru `<meta name="theme-color">`).

### Valori semantice principale

| Token | Întunecat | Luminos | Rol |
|---|---|---|---|
| `--bg` | slate-900 `#0F172A` | slate-100 `#F1F5F9` | fundal pagină |
| `--surface` | `#151F33` | `#FFFFFF` | carduri, panouri |
| `--surface-2` | `#1E293B` | `#EEF2F7` | câmpuri, chips, segment activ |
| `--board-bg` | `#0B1222` | `#F8FAFC` | afișajul Panou |
| `--text` / `-2` / `-3` | `#F1F5F9` / `#CBD5E1` / `#94A3B8` | `#0F172A` / `#475569` / `#5B6779` | text |
| `--accent` = `--time` | ambră `#FFB547` | ambră închisă `#92400E` | ore, linie, titlu panou, selecție |
| `--ok` | `#4ADE80` | `#166534` | la timp (citit) |
| `--warn` / `--lvl-low` | `#FDE047` | `#8A5300` / `#7A5D00` | întârziere mică |
| `--lvl-mid` | `#FB923C` | `#AD3F0A` | întârziere medie |
| `--bad` / `--lvl-high` | `#F87171` | `#B91C1C` | întârziere mare |
| `--unknown` | `#94A3B8` | `#5B6779` | necitit / necunoscut / vechi |
| `--info` | `#60A5FA` | `#1D4ED8` | modificat recent, în desfășurare |
| `--field-border` | `#5B6779` | `#7A889E` | contur de câmp (≥ 3:1, WCAG 1.4.11) |

Toate perechile text/fundal ≥ 4.5:1 (mari ≥ 3:1) — verificat automat (§9).

### Scale (independente de temă)

- **Tipografie**: `--font` Fira Sans (text), `--mono` Fira Code (ore, numere de tren, cifre,
  titlul și ceasul Panoului). Auto-găzduite în `web/fonts/` (woff2, subset latin + latin-ext cu
  ă â î ș ț, `font-display: swap`, licențe `OFL-FiraSans.txt`, `OFL-FiraCode.txt`). Fira Code e
  variabil (300–700). Mărimi: `--fs-xs` 12 · `--fs-sm` 13 · `--fs-md` 14 · `--fs-base` 16 ·
  `--fs-lg` 18 · `--fs-xl` 20 · `--fs-2xl` 24 · `--fs-3xl` 28 px. **Nimic sub 12 px.**
  Etichete: MAJUSCULE, `--fs-xs`, 600, `--tracking-label` 0.08em. Cifre: `tabular-nums`.
- **Spațiere** (bază 4): `--space-1…8` = 4, 8, 12, 16, 20, 24, 32 px. `--gutter` 16 → 24 (≥ 600 px).
- **Raze**: `--radius-sm` 6 (insigne, rânduri panou) · `-md` 10 (butoane, câmpuri) · `-lg` 12
  (carduri = `--radius`) · `-xl` 16 (panou, foi de detaliu) · `-pill`.
- **Mișcare**: `--dur-fast` 150 ms (hover/culori) · `--dur` 200 ms (comutatoare, segmente) ·
  `--dur-slow` 300 ms (foaie de detaliu) · `--ease` cubic-bezier(0.2, 0.7, 0.2, 1). Doar
  `transform`, `opacity`, culori/umbre. `prefers-reduced-motion: reduce` anulează tot.
- **Ținte**: `--tap` 44 px (navigație, câmpuri, butoane pe mobil), `--control-h` 40 px (desktop).

## 4. Componente

| Componentă | Specificație |
|---|---|
| Antet | siglă (logo-ul existent, 40–44 px) + „Gara de Nord / Sosiri și plecări"; ceas Fira Code + vreme; indicator „actualizat" (punct verde pulsând doar live; ambră pătrat la vechi); comutator temă 44×44. Sub 430 px: „Sursa: CFR" și detaliile vremii se ascund (sunt în footer / popover) ca totul să încapă pe 2 rânduri |
| Vreme (widget) | buton compact 44 px: pictogramă după `weather_code` (zi = `--accent`, noapte = `--info`), temperatură Fira Code, „se simte” ≥ 430 px. Popover (320 px, pe telefon cât lățimea − 32 px, sub buton, derulabil): titlu „Condiții curente (model Open-Meteo)”, temperatură mare, plăcuți `--surface-2` (umiditate, presiune, vânt + rafale, precipitații cu defalcare doar când > 0), grafic SVG 24 h (linie `--accent`, aria `--accent` 14 %, minim `--info`, maxim `--accent`, „acum” = linie punctată + punct `--text`), atribuire Open-Meteo CC BY 4.0. Lipsă = „—” (niciodată 0); > 45 min = „date vechi”: chenar punctat, serie gri, „observat” în loc de „acum”. Fără animații (doar scheletul de încărcare, oprit la `prefers-reduced-motion`) |
| Navigare | bară lipicioasă; element activ = text ambră + fundal `--surface-2` + linie ambră de 2 px jos; ≥ 44 px; derulare orizontală în interiorul barei |
| Buton | `--btn-bg`, contur `--btn-border`, hover `--btn-hover` + contur `--field-border`; primar = ambră cu `--accent-ink`; dezactivat = opacitate 0.55 + `cursor: progress/not-allowed` |
| Segment (Sosiri/Plecări/Toate, Panou/Carduri) | container cu contur, opțiunea activă plină (ambră pentru panou, `--surface-2` pentru mod) |
| Câmp | `--field-bg`, contur `--field-border`, 44 px pe mobil / 40 desktop, etichetă vizibilă deasupra |
| Card tren | bară laterală de 4 px după stare (galben/roșu/gri necitit; fără bară la timp), ora mare Fira Code ambră, stația 18 px 600, tip tren ca insignă conturată colorată pe tip, insignă de întârziere cu **iconiță + text**, plăcuța liniei (pătrat cu colțuri 10 px, chenar și cifre ambră; necunoscută = „—" gri fără chenar) |
| Rând Panou | tabel cu lățimi fixe; bara de 4 px `--lvl`; ora ambră 600; stația MAJUSCULE; insignă de întârziere colorată pe nivel (fundal 16 % / 14 % din culoare) + coloana „Stare" în text; linia = plăcuță ambră |
| Insignă stare | `la timp` (✓) · `+N min` (ceas / triunghi) · `necitit` (ceas, gri, italic) · rezultat călătorie (confirmat/neconfirmat/necunoscut/în desfășurare) |
| Chip-uri Panou | stare date: ACTUALIZAT (verde) / DATE VECHI (ambră) / necunoscut (gri) + captură, sistem, sursă, număr |
| Foaie de detaliu | `--surface`, raza xl, `--shadow-overlay`, fundal `--scrim`, intrare 300 ms (fade + 8 px) |
| Toast | `--surface-2`, raza lg, intrare 200 ms |
| Footer | „© 2026 Andy217Ace · Date preluate de la CFR (cfr.ro) — proiect independent, neafiliat CFR" + Meteo + „Beta 1.NN" (link Versiuni) — text neschimbat (testat) |

## 5. Stări de ecran

- **Încărcare**: schelet static cu puls de opacitate (1.4 s), aceleași dimensiuni ca rândul/cardul
  real (fără salt de layout); `aria-busy` pe listă; sigla mică în „Se încarcă tabela…".
- **Gol**: chenar punctat + text explicativ pe `--surface`.
- **Eroare**: `.notice-error` (roșu pe `--bad-bg`), `role="alert"`.
- **Date vechi / offline**: chip ambră + bandou; rândurile Panoului devin gri (`--unknown`),
  cardurile panoului vechi au opacitate 0.6 și eticheta „date vechi".
- **Necunoscut**: întotdeauna gri + text („necitit", „—", „linie neanunțată"), niciodată verde.

## 6. Layout

- Mobil întâi; puncte de rupere: 430 (antet compact), 600 (gutter 24), 760 (tabele reale în
  Istoric/Panou), 1024 (Sosiri + Plecări alăturate la Carduri, antet pe un rând), 1200, 1600
  („Toate" alăturate în Panou).
- Zero scroll orizontal al paginii (tabelele late derulează în containerul lor).
- Panou pe telefon: legenda coboară sub tabele, acțiunile devin un rând de butoane-iconiță de
  44 px (textul rămâne numele accesibil), tema din panou apare doar în ecran complet.

## 7. Accesibilitate

Contrast ≥ 4.5:1 / 3:1 (automat), focus vizibil (`--focus`, 2 px), skip-link, stări cu text
(nu doar culoare), `forced-colors` (contururi CanvasText), `prefers-reduced-motion`, ținte ≥ 44 px
pe mobil (excepție: stea/clopoțel în rândul Panoului pe telefon = 40 px, cu alternativa din
detaliu), iconițe SVG inline cu `aria-hidden` lângă text.

## 8. Constrângeri tehnice

CSP strict (`style-src 'self'`, `font-src 'self' …`): fără `<style>`, `style=`, scripturi inline;
DOM doar cu `createElement`/`textContent`. Fonturile sunt locale (fără cereri externe).
PWA: `sw.js` precache-uiește shell-ul + cele două fonturi critice (Fira Sans 400, Fira Code);
celelalte greutăți se încarcă la cerere. Bugetul de precache: ≤ 650 KB necomprimat (testat; 560 KB până la Beta 1.25).

## 9. Verificare

- `python scripts/contrast_audit.py <url> [--api-from https://tabelacfr.ddns.net]` — toate
  ecranele, ambele teme; ieșire ≠ 0 la orice text sub prag.
- `tests/test_contrast_browser.py` — același audit în suita de teste (1280 și 390 px, dark+light).
- `node …/validate-tokens.cjs -d web` — culori brute doar în stratul primitiv.
- Capturi Playwright 390×844 și 1440×900, dark + light, pentru fiecare ecran.

## 10. Checklist de livrare (din `ui-ux-pro-max/references/pro-rules.md`)

- [x] fără emoji ca iconițe (SVG inline, o singură familie, contur 1.8–2.4)
- [x] tokeni semantici peste tot (fără hex în componente)
- [x] hover/press cu tranziții 150–300 ms, fără salt de layout
- [x] contrast verificat separat pe dark și light
- [x] focus vizibil, ordine de focus = ordine vizuală
- [x] ținte ≥ 44 px pe mobil (excepția de mai sus documentată)
- [x] safe-area (antet, footer) respectate
- [x] testat la 390 și 1440, reduced-motion respectat

## 11. UI v2 — paginile din afara Tabelei (Beta 1.26)

Se aplică la Istoric, Urmărite, Trenuri, Tren, Statistici, Clasamente, Stații, Stație, Versiuni.
**Nu** se aplică Tabelei (Carduri / Panou / Ecran complet, `panel.*`, antetul cu vremea) și nici
paginii Capturi OCR (`.view-ocr` e exclusă explicit în `ui2.css`). Implementare: `web/ui2.css` +
`web/ui2.js` (`App.ui2`), fără bibliotecă (SVG + CSS proprii; CSP `script-src 'self'`, fără `.style`).

| Element | Regulă |
|---|---|
| Fundal | luminiță radială ambră + albastră pe `body[data-route]` ≠ tabela (`--page-glow`) |
| Antet de pagină | chip cu pictograma meniului (48 px, ambră), titlu `clamp(1.75rem…2.5rem)` 700 |
| Carduri | `--card-grad` + `--card-edge` (reflex de 1 px) + `--elev-1`, raza `--radius-xl`; hover (liste): −2 px + contur |
| Bandă de cifre | `ui-hero` → `ui-stat`: etichetă MAJUSCULE, cifră Fira Code 600 care numără (900 ms, o dată, doar dacă e pe ecran), subtitlu cu N, bară `ui-meter` |
| Donut / pie | doar pentru **părți dintr-un întreg cu puține categorii** (≤ 6 + „Altele”); inel 15/100, spațiu 0,8 %, centru = total sau felia activă, legendă cu cifre + %, un model per felie (linii, puncte, hașură), o singură oprire de tab și săgeți în legendă; sub N minim fără procente; 0 nu se desenează dar se listează |
| Culori categoriale | `--cat-1…6` (`--ref-cat-d/l-*`), validate cu `validate_palette.js` (CVD ΔE ≥ 9, contrast ≥ 3:1) pe suprafața cardului; stări: `--ok` / `--lvl-mid` / `--bad` doar cu text; sosiri/plecări = `--c-arr` / `--c-dep` |
| Rămân bare / linii / pătrate | clasamente și comparații (bare orizontale), serii în timp (linii), ora × ziua (hartă de căldură), distribuția pe intervale ordonate (coloane) |
| Mișcare | tranziție de pagină 320 ms, ridicare eșalonată (≤ 12 elemente, 45 ms), reveal la derulare o singură dată (doar `transform`), desenare bare / linii / donut; **tot dispare** cu `prefers-reduced-motion`; nimic nu e ascuns la repaus (nicio opacitate 0 persistentă) |
| Încărcare / gol / eroare | `ui-skel` (shimmer prin `transform`), `.empty` cu chenar punctat și pictogramă, `.notice-error` |
| Versiuni | axă a timpului, ultima versiune evidențiată, insigne Nou / Reparat / Tehnic, primele 3 deschise |

Verificare: `tests/test_ui2_static.py`, `tests/test_ui2_browser.py` (360 / 768 / 1280 px, ambele teme),
`tests/test_contrast_browser.py` (așteaptă finalul animațiilor înainte de audit).

## 12. UI v3 — grafice interactive (Beta 1.28)

Strat lazy (`web/charts3.js` + `charts3.css`, `App.charts3`), doar pe Statistici, Tren, Clasamente, Stație.

| Element | Regulă |
|---|---|
| Tooltip | un singur card plutitor (`.c3-tip`, `aria-hidden`) pentru toate graficele; mouse = imediat, atingere = apasă și trage (cardul urcă deasupra degetului, niciodată peste valoarea atinsă), tastatură = Tab pe grafic (o singură oprire), săgeți, Home / End, Esc; rămâne în viewport; textul e citit dintr-o regiune `aria-live=polite` (doar la tastatură), titlul nativ SVG dispare |
| Ghidaj | linia punctată verticală (linii) sau banda (coloane) + punct mărit; banda „N” de dedesubt urmărește aceeași categorie |
| Legendă | hover = evidențiază seria, estompează celelalte; click / Enter = arată / ascunde (ultima nu se ascunde); `aria-pressed` |
| Linii | curbă monotonă (fără depășiri), umplere în degrade (≥ 3 puncte consecutive), etichete max / min, linii de referință cu etichetă în margine (prag „la timp”, media perioadei), cerc gol = eșantion mic, gol = necitit (niciodată 0) |
| Bare | degrade 100 → 58 %, capăt rotunjit 4 px, etichetă „max” pe cea mai înaltă coloană fără valoare proprie |
| Indicator circular | arc 270°, doar lângă cifră (`ui-stat.has-gauge`), `aria-label` cu valoarea |
| Calendar | un pătrat pe zi, scară ca la harta oră × zi (`ss-q0…4`), de la 7 zile; tabel „Vezi datele” |
| Minigrafic în tabel | 84 × 24, una și aceeași scară pe tot tabelul (percentila 90, minim 5 min), gol unde nu s-a citit, „—” sub 2 zile |
| Ecran complet | `<dialog>` modal, focus blocat (Tab / Shift+Tab), Esc, click pe fundal, focus înapoi pe buton, tabelul alături |
| Chips | `nav.c3-toc` lipit sub meniu, scroll-spy cu `IntersectionObserver`, `aria-current="location"` |
| Mișcare | doar transform / opacitate / contur; filtrul schimbat = alunecare (WAAPI); grafice în afara ecranului stau pe pauză; fără bucle continue (shimmer 3 treceri); `prefers-reduced-motion` oprește totul |

Verificare: `tests/test_ui3_static.py`, `tests/test_ui3_browser.py`, `tests/test_trend.py`.
