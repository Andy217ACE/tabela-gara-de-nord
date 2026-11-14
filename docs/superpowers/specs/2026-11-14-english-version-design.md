# Versiunea în engleză — design

Data: 2026-11-14 · Ramură: `feat/english-version` · Cale: arhitecturală

## Scop

Un vizitator care nu citește română poate folosi Tabela în engleză, iar documentația de pe GitHub există și în engleză.

## Ce intră

1. **Interfața aplicației** (`web/`) în română și engleză, cu comutator RO/EN. Română rămâne implicită.
2. **Documentație pe GitHub:** `README` și toate fișierele din `docs/` în engleză, în paralel cu cele românești.
3. **CHANGELOG:** fiecare versiune nouă are secțiune în română și în engleză. Istoricul rămâne doar în română.

## Ce nu intră

- Nu traducem istoricul din CHANGELOG (versiunile până la Beta 1.53).
- Nu schimbăm API-urile și nu traducem datele (numele stațiilor, trenurilor, operatorilor vin din CFR în română și rămân așa).
- Nu adăugăm alte limbi.

## Decizii

- **Limba se alege** în această ordine: parametrul `?lang=en|ro` din adresă, apoi valoarea salvată în `localStorage` (cheia `tabela-lang`), apoi română. Comutatorul scrie valoarea salvată și actualizează adresa fără reîncărcare.
- **Atributul `lang`** al paginii (`<html lang>`) se actualizează la schimbare.
- **Documentația:** `README.md` devine în engleză (pagina principală de pe GitHub), iar versiunea română devine `README.ro.md`. Fiecare pagină are un link către cealaltă. În `docs/` fișierele rămân în română, iar traducerile sunt în `docs/en/`, cu același nume de fișier.
- **Formatări** (ore, date, numere, zile) trec prin `Intl` cu locale-ul ales, nu cu valori fixe pentru română.

## Arhitectura interfeței

- `web/i18n/ro.js` și `web/i18n/en.js`: dicționare cu chei stabile (ex. `board.arrivals`). Fiecare fișier exportă un singur obiect.
- `web/i18n/i18n.js`: funcția `t(cheie, parametri)`, aplicarea limbii, comutatorul, actualizarea `lang` și a titlului paginii.
- În HTML: atribut `data-i18n="cheie"` (sau `data-i18n-attr="placeholder:cheie"`). În JS: `t("cheie")` în locul textului literal.
- Șirurile dinamice cu variabile folosesc `{nume}` în dicționar: `t("delay.minutes", {n: 12})`.
- Un singur punct de comutare: la schimbare se reaplică textele din pagină și se re-randează panourile deja afișate.

## Service worker și versiuni

- `web/i18n/*.js` intră în lista precache. Bugetul de precache (~650 KB) trebuie verificat; dacă depășește, dicționarele se încarcă la cerere.
- Se incrementează versiunea SW (lista de precache se schimbă).
- Se incrementează `CHARTS_V`, fiindcă etichetele graficelor se schimbă.
- La release: `VERSION` Beta 1.54 și secțiunea CHANGELOG (ro + en).

## Testare

- **Paritate chei:** test care verifică că `ro.js` și `en.js` au exact aceleași chei și că niciun `{parametru}` nu lipsește dintr-o limbă.
- **Acoperire:** test care caută șiruri românești literale rămase în `web/*.js` și în HTML (listă de excepții explicită).
- **Browser:** test cu Playwright (ca `tests/test_nav_browser.py`): comutatorul schimbă textele, adresa și `lang`; alegerea rămâne după reîncărcare.
- **Documentație:** fiecare fișier din `docs/` are pereche în `docs/en/` (test de existență).
- Suita existentă rămâne verde.

## Riscuri

- **Volumul:** ~10.000 de linii cu text, dintre care multe în JS. Se împarte pe fișiere, pe agenți, pe modele (Haiku pentru traduceri mecanice și extragere de chei, Sonnet pentru migrarea fișierelor JS, cu revizie de Fable pentru ambiguități).
- **Regresii vizuale:** textele engleze sunt mai lungi; butoanele și meniul pot ieși din spațiu. Se verifică la 360 px.
- **Traduceri:** termenii tehnici (OCR, precache, shadow) rămân în engleză în toate locurile, cu un glosar în `docs/en/glosar.md`.

## Ordinea de lucru (propusă, detaliată în plan)

1. Infrastructura i18n (`web/i18n/`, comutator, teste de paritate). Fără text migrat încă.
2. Migrarea paginilor, una câte una: panou principal, istoric, urmărite, statistici, admin.
3. Documentația: README, apoi `docs/`.
4. CHANGELOG bilingv pentru versiunea nouă.
5. Release Beta 1.54: teste, PR, merge, deploy cu verificare live în ambele limbi.
