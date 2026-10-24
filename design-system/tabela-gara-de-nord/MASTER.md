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
celelalte greutăți se încarcă la cerere. Bugetul de precache: ≤ 560 KB necomprimat (testat).

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
