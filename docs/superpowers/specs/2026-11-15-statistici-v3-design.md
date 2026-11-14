# Statistici v3 — design (patru sub-proiecte)

Data: 2026-11-15 · Ramură: `feat/stats-v3` · Cale: arhitecturală, descompusă în 4 sub-proiecte. Fiecare sub-proiect primește propriul plan la implementare.

## Scop

Pagina de Statistici (`#statistici`) să răspundă rapid la „cum merg trenurile acum”, cu mai multă claritate, comparații și export, fără să devină mai grea de încărcat sau mai greu de folosit pe telefon. Cele 20 de sugestii ale utilizatorului sunt grupate în patru sub-proiecte, în ordinea de livrare de mai jos.

## Ce există deja (de păstrat)

- Filtre: perioadă (`all`, `30`, `7`, `1`), tablou (ambele, sosiri, plecări), operator, tip tren, cu parametrii în adresă (`readParams`, `syncHash`).
- Secțiuni de grafice (`statistici.js`, `stats.js`, `stat_*.js`, `charts3.js`), cu tooltip SVG (`tip`), link de grafic (`data-key`, `grafic=`) și traducere completă ro/en cu `Intl`.
- Endpoint `/api/stats/overview` (`app/stats_overview.py`), cache 60 s, conexiune SQLite read-only.
- Constrângeri: CSP fără inline script și fără `innerHTML` cu text din date; textele noi trec prin dicționar (`ro.json` și `en.json`, chei identice); layout verificat la 360 px fără derulare orizontală; bugetul de precache nu crește fără ruling.

## Sub-proiectul 1 — Sumar, filtre și navigare (doar front-end)

1. **Sumar rapid sus:** patru carduri: procent la timp, întârziere medie (minute), număr de trenuri analizate, ruta cu cea mai mare problemă. Datele vin din `/api/stats/overview`. Dacă lipsește un câmp, cardul arată „—”.
2. **Filtre sticky:** bara de filtre rămâne lipită de sus la derulare (`position: sticky`), fără să acopere conținutul pe mobil.
3. **Buton „Resetează filtrele”:** vizibil când cel puțin un filtru e activ; golește filtrele și actualizează adresa.
4. **Link-uri directe către secțiuni:** `#statistici?sect=probleme` (și restul secțiunilor) derulează la secțiune și o evidențiază; adresa se actualizează la navigare.
5. **Filtre salvate:** până la 5 presetări cu nume, în `localStorage` (cheia `tabela.statsPresets`), încărcate dintr-un meniu, cu ștergere individuală. Nu se sincronizează între dispozitive.
6. **Mobil:** sub 600 px, filtrele se strâng într-un panou „Filtre (n)”, iar cardurile de probleme au o singură coloană.

**Erori:** dacă `localStorage` nu e disponibil, presetările se dezactivează cu un mesaj. Sumarul afișează „—” pentru câmpurile lipsă.
**Teste:** browser pentru sticky (poziția după derulare), reset, link direct, presetare salvată și reîncărcată, layout la 360 px (`scrollWidth <= 360`). Static pentru cheile de dicționar noi.

## Sub-proiectul 2 — Claritate vizuală (front-end)

1. **Cod de culori unic:** o singură scală verde (bine), galben (mediu), roșu (rău), definită o dată ca token CSS și aplicată în toate secțiunile și în sumar. Pragurile sunt constante într-un singur loc.
2. **Tooltips pe metrici:** „Încredere”, „Gravitate”, „N” și „mediană vs medie” au explicație scurtă în dicționar, afișată la hover și la focus de la tastatură.
3. **Grafice interactive:** click pe un bar sau punct deschide lista trenurilor din spatele lui. Cere un parametru nou la endpoint, `detail=train_list`, limitat la 200 de rânduri.
4. **Mod contrast ridicat:** opțiune în meniul de temă (`theme-init.js`), care mărește contrastul textelor și al scalei de culori. Persistă în `localStorage` ca tema.
5. **Mod simplu sau expert:** comutator care ascunde N, încredere și mediana-față-de-medie în modul simplu. Implicit simplu, reținut în `localStorage`.
6. **Texte scurte la Probleme:** fiecare explicație are o versiune de o frază și un buton „Citește mai mult” care arată restul.

**Erori:** un grafic fără date afișează starea goală existentă. Lista de la click se trunchiază cu un mesaj când depășește 200.
**Teste:** browser pentru click pe grafic (lista se deschide și conține trenuri), comutatorul simplu/expert (câmpurile dispar), contrast (clasa e aplicată), tooltip accesibil. Static: o singură definiție a scalei de culori.

## Sub-proiectul 3 — Conținut nou (cere calcule noi pe server)

1. **„Ce s-a schimbat săptămâna asta”:** top 3 rute sau operatori care s-au îmbunătățit și top 3 care s-au înrăutățit, față de săptămâna anterioară, după procentul la timp. Endpoint nou `/api/stats/changes`, cache 60 s, read-only.
2. **Alerte pe prag:** o rută sau un operator cu întârziere mediană peste 15 min în ultimele 7 zile apare într-un banner în sumar. Pragul e constantă în cod, nu se configurează din interfață.
3. **Comparație între perioade:** două coloane, ultimele 7 zile și cele 7 zile dinaintea lor, pentru aceleași metrici din sumar. Endpoint `/api/stats/overview?compare=prev7`.
4. **„Cele mai fiabile trenuri”:** secțiune oglindă a „Probleme”, cu trenurile cel mai des la timp. Cere minim 10 călătorii, ca să nu apară trenuri cu o singură călătorie.
5. **Heatmap zile × ore:** întârzierea medie pe zi a săptămânii și oră. Endpoint `/api/stats/heatmap` (zile 0–6, ore 0–23), cu scala comună.

**Erori:** dacă baza are mai puțin de 7 zile de date, comparația și schimbările afișează „date insuficiente” (cheie de dicționar), nu valori false.
**Teste:** endpoint (forma răspunsului, pragul de 10 călătorii, lipsa datelor), browser pentru banner și heatmap.

## Sub-proiectul 4 — Export și performanță

1. **Export pe fiecare grafic și tabel:** CSV (separator virgulă, UTF-8 cu BOM pentru Excel) și PNG (SVG serializat, desenat pe canvas, fără librării externe).
2. **PDF:** nu se generează pe server și nu se adaugă librărie. Butonul „Tipărește” deschide vizualizarea pentru print (`@media print`), iar utilizatorul salvează ca PDF din browser.
3. **Încărcare progresivă:** la deschidere se încarcă sumarul și „Probleme”. Restul secțiunilor se încarcă la prima vizită (`IntersectionObserver` sau click pe tab).
4. **Indicator de actualizare:** „Date actualizate acum X minute” lângă filtre, reîmprospătat la 60 s cât pagina e deschisă.

**Erori:** export fără date afișează starea goală. Dacă PNG eșuează, se oferă CSV cu un mesaj.
**Teste:** browser pentru descărcarea CSV (conținut și BOM); secțiunile întârziate nu cer endpoint-ul înainte de vizită; static: nicio librărie nouă.

## Ordinea de livrare

1. Sub-proiectul 1 (fără dependențe).
2. Sub-proiectul 2 (folosește scala de culori și dicționarul din 1).
3. Sub-proiectul 4 (independent, poate merge în paralel cu 2).
4. Sub-proiectul 3 (ultimul: cere endpoint-uri noi și date suficiente).

Fiecare sub-proiect are plan propriu, review de sarcină și review final, apoi release propriu (Beta 1.57 până la 1.60) cu deploy, backup și verificare live.

## Riscuri

- **Precache:** fișierele JS noi se memorează la runtime, nu în precache, ca în Beta 1.55.
- **Cost pe server:** endpoint-urile noi fac agregări pe SQLite read-only. Se cache-uiesc 60 s, ca `/api/stats/overview`.
- **Date insuficiente:** pe o bază nouă, comparațiile și heatmap-ul nu au sens. Afișăm starea, nu zero.

## Decizii de confirmat la aprobare

- Limita de 200 de rânduri la click pe grafic.
- Pragul de 15 min pentru alerte și de 10 călătorii pentru „Cele mai fiabile”.
- Export PDF doar prin print, fără generare pe server.
