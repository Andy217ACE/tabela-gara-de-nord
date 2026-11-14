# Glossary (Romanian to English)

Fixed term decisions for the English documentation in `docs/en/` and for the English interface (`web/i18n/en.json`). Every translated document uses these terms. Technical terms that are already English in the Romanian text stay in English.

## Rules

- Code blocks, commands, file paths, JSON keys, API paths, environment variables and table structure are never translated.
- Station names, train numbers/categories and operator names are CFR data and are not translated (for example "Gara de Nord", "București Nord", "InterRegio").
- Code identifiers that contain Romanian words (for example `label_ro`, `condition_ro`, `wind_direction_ro`, `LABEL_RO`) are kept as they are; the prose around them is translated.
- Quoted interface strings that exist in the Romanian UI are given in English as they appear in the English UI, with the Romanian original in parentheses on first mention when it matters.
- The copyright line `© 2026 Andy217Ace` is kept unchanged.

## Product and interface

| Romanian | English | Note |
|---|---|---|
| Tabela Gara de Nord | Tabela Gara de Nord | product name, not translated |
| tabela (panoul de afișaj) | the board | the station display board; "arrivals board" / "departures board" for the two halves |
| Sosiri / Plecări | Arrivals / Departures | |
| Istoric | History | page and menu entry |
| Urmărite | Followed trains | page; the menu label is short "Followed" |
| Urmărit (tren) | followed | verb: to follow a train |
| Statistici | Statistics | |
| Clasamente | Rankings | |
| Stații | Stations | |
| Trenuri | Trains | |
| Sistem | System | |
| Setări | Settings | |
| Istoric versiuni | Version history | |
| Meteo | Weather | |
| peron | platform | |
| Perturbații / probleme | Problems | |
| Cuprins | Contents | |
| bara de sus / meniul pe telefon | top bar / phone menu | |
| temă luminoasă / întunecată | light / dark theme | |
| mod offline | offline mode | |
| datele de pe pagină | page data | |

## Data and statistics

| Romanian | English | Note |
|---|---|---|
| călătorie (un tren pe o zi de serviciu) | journey | one train on one service date |
| zi de serviciu | service date | |
| ora programată | scheduled time | |
| întârziere | delay | |
| la timp | on time | |
| rezultat confirmat | confirmed result | |
| rezultat provizoriu / neconfirmat | provisional / unconfirmed result | |
| eșantion minim | minimum sample | |
| acoperire (a datelor) | coverage | |
| calitatea datelor | data quality | |
| corecție | correction | |
| validare | validation | |
| sezoane | seasons | meteorological seasons |
| corelație, nu cauzalitate | correlation, not causation | |
| grupă | group | |
| mediană / medie | median / mean | |
| observație | observation | |
| captură | capture | a captured image of the board; "screenshot" only for browser screenshots |
| setul de adevăr (OCR) | ground-truth set | |
| retenție | retention | |
| jurnal | log | "audit log" for `jurnalul de audit` |
| operator | operator | |
| sondare / ciclu de sondare | polling / polling cycle | |

## Technical terms kept in English

| Romanian text | English | Note |
|---|---|---|
| OCR | OCR | |
| precache | precache | service-worker pre-cache; verb "precache" |
| shadow (antrenare umbră) | shadow | "shadow training", "shadow directory"; never "umbra" |
| poller | poller | |
| watchdog | watchdog | |
| rollback | rollback | |
| backoff | backoff | |
| service worker | service worker | |
| PWA, CSP, TLS, DNS | unchanged | |
| rate limit | rate limit | |
| deploy | deploy | noun and verb |
| release | release | |
| staging | staging | |
| flaky (teste instabile) | flaky | "flaky tests" |
| fixture | fixture | |
| endpoint, token, cookie, cache | unchanged | |
| placeholder | placeholder | |
| widget | widget | |
| popover | popover | |
| fallback | fallback | |
| timeout | timeout | |

## Recurring phrasings

| Romanian | English |
|---|---|
| Ce nu am putut verifica / Ce nu am verificat | What I could not verify |
| Cum a fost verificat documentul | How this document was verified |
| Verificări și nesiguranțe | Checks and uncertainties |
| de verificat | to verify |
| Afirmațiile vin din cod | The statements come from the code |
| Ce nu se afirmă | What is not claimed |
| date vechi | stale data |
| în curs de adunare | still being collected |
| date insuficiente | insufficient data |
| Pentru contributori | For contributors |
| Lista de verificare | Checklist |
| Legături | Links |
| pas cu pas | step by step |
