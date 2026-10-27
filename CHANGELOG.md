# Istoric versiuni — Tabela Gara de Nord

Schema versiunilor: `Beta 1.NN`, unde NN crește cu 1 la fiecare deploy pe
tabelacfr.ddns.net. Cele mai noi versiuni sunt sus.

© 2026 Andy217Ace · Date preluate de la CFR (cfr.ro) — proiect independent, neafiliat CFR

## Beta 1.30 — 2026-10-27

Igienă de interfață. **Tabela** (Carduri, Panou, Ecran complet) rămâne neschimbată pixel cu pixel în afara celor două butoane de mai jos; datele și API-ul nu se schimbă.

### Nou
- **Stări goale la Trenuri și Stații:** când nu există încă nicio dată, pagina spune „Nu există încă date pentru trenuri.” / „… pentru stații.”, în loc de antet și tabel goale. O căutare fără rezultate păstrează mesajul „Niciun tren / Nicio stație nu se potrivește căutării.”.
- **Stare de eroare cu „Reîncearcă”:** dacă serverul nu răspunde, pagina spune „Nu am putut încărca trenurile / stațiile.” cu motivul și un buton „Reîncearcă” care cere din nou datele.

### Schimbat
- **Stea și clopoțel pe telefon:** zona de atingere ajunge la cel puțin 44 × 44 px (pe Carduri butonul „urmărește”, pe Panou steaua și clopoțelul). Mărirea este compensată cu margini negative, deci rândurile și cardurile nu se mută. Pe ecrane late nimic nu se schimbă.

### Reparat
- **CSP fără Google Fonts:** fonturile sunt deja auto-găzduite (`web/fonts`), dar antetul `Content-Security-Policy` încă permitea `fonts.googleapis.com` și `fonts.gstatic.com`. Gazdele sunt scoase (`style-src 'self'`, `font-src 'self'`); un test verifică să nu mai apară în fișierele web, iar un test în browser real verifică lipsa încălcărilor CSP și încărcarea Fira Sans.

### Tehnic
- Service worker `v30` și `CHARTS_V` 1.30 (reîncarcă fișierele noi). Teste noi: `test_csp_browser`, `test_empty_states_browser`, `test_touch_targets_browser`; bugetul de precache din `test_brand_theme` a crescut de la 650 KB la 652 KB.

## Beta 1.29 — 2026-10-27

**Corecție manuală din administrare** (pagina interioară „Capturi OCR”, `#ocr`). Pentru numerele pe care OCR le citește mereu la fel de greșit (de exemplu IR 1584 în loc de IR 1581, sau 7911 în loc de 7914). **Tabela** și paginile publice rămân neschimbate pixel cu pixel; nimic din corecții nu apare în API-ul public.

### Nou
- **Corectează un rând direct din captură:** alegi captura, apeși „Corectează” pe rând, alegi câmpul (nr. tren, tip, stație, operator, oră, linie, întârziere), valoarea citită greșit (precompletată din rând), valoarea corectă și o notă obligatorie.
- **Regulă îngustă:** (panou, câmp, valoare citită greșit) și, opțional, doar o stație, o oră programată sau un interval de zile. Regula se potrivește exact pe valoarea greșită, nu „aproximativ”.
- **Pe cadrele noi:** corecția se aplică la citire, iar observația primește marcajul `+corr:<id>` (textul brut OCR rămâne neatins; rândul apare marcat „corectat #id” în detaliul capturii).
- **Retroactiv, reversibil:** „Previzualizează retroactiv” (dry-run: câte servicii, observații și evenimente s-ar schimba, cu exemple și conflicte) și abia apoi „Aplică”; aplicarea cere previzualizarea exactă și se face într-o singură tranzacție, cu arhivă pe lot, la fel ca `scripts/merge_number_dups.py --restore`. „Restaurează lotul” pune valorile vechi la loc (rândurile modificate între timp rămân cum sunt). Conflictele (există deja serviciul cu numărul corect) sunt doar listate, nu se modifică.
- **Valoare lipsă ≠ 0:** „necitit” se poate corecta doar la linie și întârziere; o întârziere 0 citită nu se confundă cu una necitită.
- **Siguranță:** validarea intrării pe server, token CSRF (plus verificarea Origin) pentru apelurile cu cookie, ștergere moale (regula rămâne în evidență), jurnal de audit (cine/ce/când/IP) afișat în pagină. Cheia de administrare rămâne obligatorie.

### Tehnic
- Schema DB **v9**: tabelele `corrections`, `correction_batches`, `correction_archive`, `correction_audit` (aditive). Înainte de migrare se verifică/face o copie a bazei (modulul `dbbackup`; folosește copia recentă făcută de `update.sh`).
- Cod nou: modulele `corrections` și `corrections_api` din `app` (rute sub `/api/admin/`: corrections, csrf), UI în `web/ocr.js` și `web/ocr.css` (încărcate la cerere, nu intră în service worker). Teste: `test_corrections` și `test_corrections_browser` din `tests`; capturi în `docs/superpowers/screenshots`.

## Beta 1.28 — 2026-10-27

Runda a doua a redesign-ului (după Beta 1.26): graficele din **Statistici**, **Tren**, **Stație** și **Clasamente** devin interactive și mai clare. **Tabela** (Carduri, Panou, Ecran complet), vremea, Capturile OCR și datele nu se schimbă (Beta 1.27 este rezervată lucrărilor de OCR, care nu ating pagina web).

### Nou
- **Tooltip pentru toate graficele** (bare, coloane, linii, hărți de căldură): același card plutitor pentru toate; cu mouse-ul apare imediat (înlocuiește tooltip-ul nativ, lent), pe telefon apeși și tragi degetul ca să treci de la o valoare la alta (cardul stă deasupra degetului, niciodată peste valoarea atinsă), cu tastatura intri în grafic cu Tab, mergi cu săgețile, Esc îl închide. Rămâne în ecran, iar textul fiecărei valori este citit de cititorul de ecran. La liniile de timp apare și o linie de ghidaj cu punctele evidențiate; banda „N” de dedesubt urmărește aceeași oră sau zi.
- **Legenda este interactivă:** treci peste „Sosiri” sau „Plecări” și cealaltă serie se estompează; apeși ca să ascunzi sau să arăți o serie (ultima serie vizibilă nu se poate ascunde).
- **Grafice mai clare, la fel de oneste:** linii netede cu umplere în degrade, bare cu degrade, etichete pentru cea mai mare și cea mai mică valoare, linii de referință cu etichetă (pragul „la timp ≤ 5 min” pe ore; media perioadei, pe panou, la evoluția pe zile), procentul scris direct pe feliile donut-urilor care au loc, un **indicator circular** de punctualitate în cifrele mari, iar în **Statistici** un **calendar** nou: câte un pătrat pe zi, colorat după întârzierea medie (apare de la 7 zile cu date). Valorile lipsă rămân „—”, nu 0; sub 5 călătorii arătăm doar cifre brute.
- **La schimbarea unui filtru** barele, punctele și liniile alunecă de la valorile vechi la cele noi, în loc să se redeseneze brusc.
- **Ultimele 14 zile, în tabele:** minigrafic cu întârzierea medie pe zi în Trenuri, Clasamente (trenuri, stații și podium) și în trenurile unei stații; aceeași scară pentru tot tabelul, goluri unde întârzierea nu a fost citită. Câmpul nou `trend` din API este doar adăugat (`/api/trains/stats`, `/api/stats/rankings`, `/api/trains/{nr}/journeys`, `/api/stations/{nume}`), fără schimbări pentru ce exista.
- **Ecran complet pentru fiecare grafic** (fereastră cu focus blocat și Esc, tabelul cu datele alături) și **„Copiază linkul către grafic”**: linkul păstrează filtrele și te duce direct la grafic.
- **Chips de secțiuni, lipite sub meniu, în Statistici:** Probleme, Cifre, Distribuție, Zile, Ore, Hartă etc., cu urmărirea secțiunii pe care o citești.
- **Alte rafinări:** schimbarea paginii se face ca o tranziție de pagină (View Transitions, unde browserul o are; altfel animația de până acum), carduri mici care se ridică la hover, schelete de încărcare în forma graficelor (trei treceri, apoi stau), stare goală cu acțiune („Șterge filtrele”), apariția la derulare fără recalcularea paginii. Totul se oprește cu prefers-reduced-motion; se animă doar transform, opacitate și contur; nimic nu rulează continuu.

### Reparat
- Donut-urile aveau două elemente cu același `id` (descrierea și modelul cu puncte); modelele au acum id-uri proprii.

### Tehnic
- Cod nou încărcat **la cerere**, doar pe Statistici, Tren, Clasamente și Stație: `web/charts3.js` + `web/charts3.css` (~58 KB necomprimat, ~18 KB gzip). Nu intră în service worker (precache-ul rămâne sub 650 KB; v28 doar pentru schimbările din `ui2.js`, `ui2.css`, `app.js`, `statistici.js` și `stats.js`). Fără bibliotecă nouă: SVG propriu, fără stiluri inline (CSP).
- API: `trend` (ultimele 14 zile, medie pe zi, `null` = necitit) în intrările de tren și de stație; teste în `tests/test_trend.py`. Teste noi: `tests/test_ui3_static.py`, `tests/test_ui3_browser.py` (tooltip, atingere, tastatură, legendă, ecran complet, link, chips, calendar, mișcare redusă, Tabela identică pixel cu pixel cu și fără stratul vizual).

## Beta 1.27 — 2026-10-27

Beta 1.26 (aspectul nou) e în versiunea dinaintea acesteia; aceasta schimbă doar citirea imaginii (OCR), nu interfața.

### Reparat
- **Reflexia ceasului din sticlă peste tabelă** (observată pe 27.10, ~07:30–07:50; capturile 8465–8467) acoperă două locuri fixe: „+” și prima cifră a întârzierii de pe **primul rând de Sosiri** (399 din 407 celule respinse pentru reflexie din istoric sunt pe rândul 0, zilnic, din 23.10) și **cele două puncte din ora programată de pe al doilea rând** („7:37” devenea „7▪37”). Sub pată pixelii nu mai există, deci nu se citește nimic de acolo; se completează doar ce lasă dovezile fără echivoc.
- **Întârziere cu „+” acoperit:** dacă celula e respinsă pentru reflexie / „+” ascuns, iar cifra unităților (0 sau 5) se vede clar și o confirmă ambele cititoare (șabloane și Tesseract), întârzierea rămâne cea pe care trenul a avut-o în cadrele dinainte, dacă ultimele 3 citiri reale ale lui sunt aceeași valoare, care se termină în acea cifră. Cifra zecilor de sub pată nu se citește niciodată („+15” dădea 45, 75, 465, 85). Cel mult 30 de cadre la rând. Valoarea apare ca citită, marcată `+delay:glare_inferred` în versiunea de procesare și `uncertain` pe observație. Pe sosiri nu există întârzieri negative (0 din 101 532 citiri), deci „+” ascuns este un plus. Un tren fără istoric rămâne „necitit”.
- **Ora programată cu punctele acoperite:** rândul avea tip și număr, dar fără oră rămânea necitit și trenul lipsea de pe tabelă (9202 Pitești 07:37, 11/12 rânduri). Acum se completează doar când o singură oră este compatibilă cu glifele de încredere, cu ordinea cronologică a rândurilor vecine și, dacă trenul a arătat aceeași oră în ultimele cadre, cu ea. O cifră ascunsă (nu doar punctele) cere ambii vecini sau istoricul. Altfel rămâne necitit. Rândul e `uncertain`, cu încredere 0,65 (sub pragul unui serviciu nou) și `+time:glare_filled` în versiune.

### Tehnic
- `app/ocr/glare.py` (nou): candidați de oră din glife (glif fără încredere = joker, cel mult unul), `fits`/`pick_time` (vecinii și istoricul), `delay_tail`. `app/ocr/reader.py`: `DelayVotes._infer` (citiri reale ținute per tren, serie limitată), memorie de ore curate per tren (`time_hint`), `_fill_times` înainte de recitirea întârzierilor. `app/observations.py`: sufixul `+time:glare_filled`.
- Fără pre-procesare anti-reflexie: pixelii reflexiei au aceeași luminozitate ca textul (min(R,G,B) 200–240), nu se pot separa, iar sub ei nu e nimic de recuperat. Vot pe caractere pentru numărul trenului: nu s-a livrat; cadrele cu număr diferit de al serviciului sunt 9 din 69 030, iar numerele greșite stabile (IR 1584 în loc de 1581) sunt la fel în toate cadrele, deci votul nu le poate corecta.
- Schema DB neschimbată (v8). Teste noi: `tests/test_glare.py`, cadre reale în `tests/fixtures/glare/`.

## Beta 1.26 — 2026-10-27

Beta 1.25 (vremea din antet) e în versiunea dinaintea acesteia. Această versiune schimbă aspectul tuturor paginilor în afară de **Tabelă** (Carduri, Panou și Ecran complet rămân exact cum erau) și de Capturi OCR.

### Nou
- **Statistici: felii (donut) acolo unde datele sunt părți dintr-un întreg.** Pe fiecare panou: câte călătorii au fost la timp, întârziate până la 30 min și peste 30 min (în centru, procentul la timp). O cifră nouă, „Cum se împart călătoriile?”: sosiri față de plecări, apoi pe tip de tren (IR, IRN, RE, R, RM, IC) și pe operator (primii cinci și „Altele”). Calitatea datelor (rezultat și citiri OCR) are tot felii.
- Fiecare donut are legendă cu cifre și procente, N afișat, centrul care arată felia peste care treci cu mouse-ul sau pe care ajungi cu tastatura, un model pe fiecare felie (linii, puncte, hașură) ca să nu conteze doar culoarea, „Vezi datele” (tabel) și export CSV. Sub 5 călătorii se arată doar cifrele brute, fără procente. Clasamentele, seriile în timp (ore, zile) și hărțile de căldură rămân bare, linii și pătrate.
- **Prima privire în fiecare pagină:** bandă de cifre mari care numără până la valoare (la timp pe panou, călătorii, zile cu date; la Trenuri, Stații, Stație, Tren, Clasamente, Istoric, Urmărite, Versiuni), cu bare subțiri de proporție.
- **Clasamente:** podium cu primele trei trenuri (cele mai punctuale și cele mai întârziate); tabelele au bare de proporție la „% la timp”. **Stații:** sosiri față de plecări ca donut și ca bară în fiecare rând. **Tren / Stație:** donut de întârzieri și linia întârzierii pe călătorii. **Statistici → trenuri care întârzie zi de zi:** minigrafic pe zile.
- **Versiuni:** axă a timpului, versiunea curentă evidențiată, insigne pentru Nou / Reparat / Tehnic; versiunile mai vechi de a patra se deschid la cerere.
- **Mișcare:** tranziție la schimbarea paginii, apariția cardurilor la derulare (o singură dată), graficele se desenează (bare, linii, donut), schelete de încărcare în locul textului „Se încarcă…”, stări goale cu pictogramă. Se oprește complet cu prefers-reduced-motion; se animă doar transform, opacitate și contur.
- Design: fundal cu lumină discretă, carduri cu adâncime, titluri mai mari, pictograma paginii în antet; temă luminoasă și întunecată, mobil de la 360 px, fără scroll orizontal.

### Tehnic
- Fără bibliotecă nouă: grafice SVG + CSS proprii (CSP: `script-src 'self'`, fără stiluri inline), temabile și accesibile; `web/ui2.js` (donut, count-up, meter, sparkline, schelete, tranziții) și `web/ui2.css`. Culorile categoriale noi (`--ref-cat-*`) sunt validate cu verificatorul de palete (CVD, contrast) pe ambele suprafețe.
- Service worker v27; bugetul de precache crește la 650 KB necomprimat (~+72 KB, ~20 KB gzip).
- Teste noi: `tests/test_ui2_static.py`, `tests/test_ui2_browser.py` (pagini la 360/768/1280, ambele teme, donut, mișcare redusă, Tabela neatinsă). Backend și schema DB neschimbate (v8, din Beta 1.25).

## Beta 1.25 — 2026-10-27

### Nou
- **Widgetul de vreme, regândit.** În antet (lângă ceas) rămâne compact: pictogramă după codul meteo, cu variantă de zi sau de noapte (după `is_day` de la model), temperatura și „se simte". La apăsare (sau hover pe desktop) se deschide un panou cu: umiditate, presiune (hPa), vânt (viteză, direcție în cuvinte, de exemplu „SV”, și rafale), precipitații (totalul; ploaie / averse / zăpadă doar când sunt mai mari decât 0; 0,0 mm este o valoare reală) și un grafic mic al temperaturii din următoarele 24 de ore, cu minim, maxim și marcajul „acum”.
- Stare „date vechi” peste 45 de minute: chenar punctat, seria desenată în gri, „observat” în loc de „acum”. Valorile lipsă apar „—”, niciodată 0.
- Pe telefon (360 px) panoul se deschide sub buton, pe toată lățimea, fără derulare orizontală; se poate închide cu Esc.

### Tehnic
- O singură cerere către Open-Meteo, făcută de server: `current` cu temperatură, umiditate, temperatură resimțită, zi/noapte, precipitații (total, ploaie, averse, zăpadă), cod meteo, presiune, vânt, direcție și rafale, plus `hourly=temperature_2m`, cu `timezone=UTC` și `forecast_days=2`. Aceleași reguli ca înainte: browserul nu apelează Open-Meteo (CSP `connect-src 'self'`), cel mult o cerere la 5 minute, backoff 5 → 30 min, sarcină proprie supravegheată, atribuire CC BY 4.0, „model Open-Meteo”, nu stație meteo.
- **Schema DB v8** (aditivă, un singur `ALTER TABLE ... ADD COLUMN` pe pas, atomic cu versiunea): `weather_observations` primește coloanele nullable `relative_humidity_pct`, `is_day`, `rain_mm`, `showers_mm`, `snowfall_cm`, `surface_pressure_hpa`, `wind_gusts_kmh`, `hourly_json`. Rândurile vechi rămân neatinse (valorile noi sunt `NULL`, nu 0); statisticile „Meteo și trenuri” citesc aceleași coloane ca până acum. Seria orară (25 de puncte) se păstrează doar pe cea mai nouă observație, ca baza de date să nu crească. `deploy/update.sh` face singur backup înainte de repornire, pentru că versiunea schemei crește.
- `GET /api/weather`: câmpuri noi `relative_humidity_pct`, `surface_pressure_hpa`, `wind_gusts_kmh`, `rain_mm`, `showers_mm`, `snowfall_cm`, `hourly` (`start_utc`, `step_s`, `temperature_c`, `min_c`, `max_c`); `is_day` vine acum din model (rândurile vechi: calculat din poziția soarelui, ca până acum).
- Service worker `v26`. Teste noi: parsare (câmpuri lipsă / null / unități), migrarea v7 → v8, forma API, și un test în browser real (`tests/test_weather_browser.py`: conținut, fără depășire la 360 px, contrast, tastatură, stare veche, fără apeluri externe).

## Beta 1.24 — 2026-10-26

Beta 1.22 nu a fost publicată separat: conținutul ei (calitatea datelor, runda 3) este în această versiune, peste Beta 1.23 (dreptunghiurile celulelor pe panou înclinat).

### Reparat
- **Numere de tren cu cifre în plus sau în minus** (RE 9209 apărea și ca 92011, RM 7938 ca 79311, RE 10157 ca 157, R 5019 ca 19): cauza era rostul dintre modulele tabelei, care taie ultima cifră (un „9” devenea „11”) și strălucirile care ascund prima cifră. Cifra tăiată se lipește la loc, iar două citiri ale aceluiași rând (aceeași stație și aceeași oră, numere apropiate) sunt tratate ca **un singur tren**, nu ca două; dacă tabela arată cu adevărat două trenuri în același cadru, rămân două.
- **Stații scrise diferit:** „KIEV -CHISINAU” și „KIEV - CHISINAU” sunt aceeași stație; „VATRA DORNEI BA” se completează la „VATRA DORNEI BAI”.
- **Ore programate citite greșit** (01:10 și 01:49, 03:38 și 08:58): orele de pe un panou cresc mereu; o oră care iese din ordine primește încredere scăzută și, doar dacă o singură cifră confundabilă (5/6, 3/8, 0/8…) o pune la loc fără îndoială, este corectată și marcată incertă. Același tren, în aceeași stație și zi, cu ore apropiate ca scriere, este un singur tren.
- **Întârzieri care nu sunt multiplu de 5** („+46”, „+26”, „+6”): tabela numără din 5 în 5 minute, deci o astfel de valoare e o cifră citită greșit și devine „necitită” (lipsă, niciodată 0 și niciodată o presupunere).
- **Întârziere recuperată când „+” e acoperit de săgeata de peron:** dacă în cel puțin 8 din ultimele 12 cadre se vede aceeași valoare (multiplu de 5, nu mai mică decât ultima citire), aceea este întârzierea. Reduce trenurile „neconfirmate” din coada de la peron.
- **Ora repetată din noaptea de 25.10 (trecerea la ora de iarnă):** pentru trenurile programate între 03:00 și 03:59 ora estimată și dispariția erau comparate cu o oră de diferență (apăreau „dispărut înainte de ora estimată” false). Comparațiile se fac acum în UTC.

### Tehnic
- `app/ocr/digits.py` (lipirea cifrei tăiate, rost până la ~4 px), `app/ocr/reader.py` (confirmare Tesseract când lipsește prima cifră, validare pas de 5 min, `DelayVotes` pe textul văzut), `app/ocr/order.py` (ordinea orelor), `app/store.py` (`_near_dup`, vot de redenumire spre mai puține cifre doar la 90%), `app/canonical.py` + `data/stations_seed.txt`, `app/journeys.py` (UTC).
- Teste noi: `tests/test_q122.py`. Schema DB neschimbată (v7). Datele deja salvate nu se modifică; curățarea retroactivă se face separat.
- Rămas: coloana peron citită tăiat/acoperită de reflexii (cadrul 7028) nu poate fi citită; numerele greșite stabile (IR 1584/1574 în loc de 1581/1571) cer vot pe caractere.
## Beta 1.23 — 2026-10-26

### Reparat
- **Capturi OCR, overlay:** dreptunghiurile celulelor „tip tren” și „număr tren” de pe Plecări (mai ales grupul 4, rândurile 9–11) erau prea sus și tăiau partea de jos a cifrelor și a literelor, iar „oră”/„operator” erau prea jos.
- Cauza: camera vede panoul înclinat (textul coboară spre stânga și urcă spre dreapta, ~3 px pe Plecări), iar banda de rând era comună pentru toate coloanele.
- Acum fiecare celulă își urmărește propria cerneală dincolo de bandă (limitat la 35% din înălțime și la jumătatea spațiului până la rândul vecin) și are 1 px margine.
- Tăiere jos la tip/nr: de la 22–42% din celule la sub 1%.
- **Citirea nu a fost afectată în mod măsurabil:** imaginile trimise la Tesseract rămân neschimbate (șabloanele de cifre sunt calibrate pe ele); acuratețea pe setul de adevăr e identică (384 rânduri).

### Tehnic
- `preprocess.extend_span`, `_Panel.cell_span`, `_Panel.boxes`; test `tests/test_band_boxes.py` cu captură reală (`tests/fixtures/band_group4.jpg`). Schema DB neschimbată (v7).

## Beta 1.21 — 2026-10-24

### Reparat
- Pagina **Versiuni** afișa marcajele de evidențiere ca text brut (două steluțe înainte și după); acum fragmentele marcate apar îngroșat, ca în notele de pe GitHub.
- Se aplică tuturor versiunilor din listă, inclusiv notelor vechi (Beta 1.09–1.20).
- Textul notelor e pus în pagină tot ca text (fără HTML venit din date), deci politica de securitate a paginii rămâne la fel de strictă.

### Tehnic
- Doar `web/versions.js`; footerul și „Versiunea curentă” nu se schimbă.
- Service worker v25. Schema DB neschimbată (v7).

## Beta 1.20 — 2026-10-24

### Nou
- **Primul release** (până acum doar pre-release-uri): grafica întregii aplicații, regândită ca un afișaj de gară modern.
- **Aspect nou, pe toate ecranele:** fundal slate (albastru-gri închis) și o temă luminoasă la fel de lucrată; ambra panoului de gară pentru ore, linie și selecție; verde, galben, portocaliu și roșu doar pentru stări citite, mereu cu iconiță și text; gri pentru necitit, necunoscut și date vechi (niciodată „la timp” fără o întârziere citită).
- **Fonturi noi, găzduite pe site:** Fira Code pentru ore, numere de tren și cifre, Fira Sans pentru text, cu diacritice românești. Nu mai există nicio cerere către Google Fonts.
- **LIVE mai ușor de citit:** linia apare ca o plăcuță de peron (chenar și cifre ambră); la trenurile întârziate ora estimată rămâne mare, iar starea o spun bara colorată și eticheta „+N min”; filtrele Panoului încap pe un rând pe desktop.
- **Pe telefon:** antetul ocupă două rânduri (ceasul, vremea și „actualizat” pe același rând), meniul are linia ambră sub pagina curentă, butoanele Panoului sunt iconițe de 44 px pe un singur rând, iar legenda culorilor coboară sub tabel, ca trenurile să apară mai sus.
- Butoane, câmpuri, carduri, insigne și foi de detaliu au aceeași formă și aceleași stări pe toate paginile (Istoric, Urmărite, Trenuri, Tren, Stații, Stație, Statistici, Clasamente, Versiuni, Capturi OCR).

### Reparat
- Contrast insuficient în tema luminoasă a Panoului („la timp” 4,48:1 și „+30 min” 3,9:1): toate textele au acum cel puțin 4,5:1, verificat automat pe toate ecranele, în ambele teme.
- Textul nu mai coboară sub 12 px (etichetele de 11 px au fost mărite), iar câmpurile au contur vizibil (3:1).
- Butonul de temă nu mai apare de două ori pe Tabelă (în Panou rămâne doar în ecran complet).

### Tehnic
- Sistem de design în trei straturi (primitive → semantice → componente), descris în `design-system/tabela-gara-de-nord/MASTER.md`; culorile brute există doar în stratul primitiv.
- Audit automat de contrast: `scripts/contrast_audit.py` și `tests/test_contrast_browser.py` (1280 și 390 px, dark + light).
- Fonturi woff2 în `web/fonts/` (subset latin + latin-ext, `font-display: swap`, licență OFL inclusă); cele două critice sunt preîncărcate și în cache-ul offline. Service worker v24. Schema DB neschimbată (v7). Logica, API-ul și datele nu s-au schimbat.

## Beta 1.19 — 2026-10-24

### Nou
- **Statisticile încep cu „Probleme”.** Pe baza primelor 4 zile (1157 de călătorii, 103 708 citiri ale tabelei), pagina Statistici arată întâi ce iese în evidență, clasat după gravitate × câte călătorii afectează × încrederea în cifre. Fiecare problemă are N, cifrele brute, „de ce contează” și link spre tren, stație sau zi. Calculul e determinist, din date (fără AI).
- Ce apare acum în date: sosirile sunt la timp doar în 48,5 % din cazuri (37 % fără navetele de Aeroport), plecările în 92,5 %; trenurile din Pitești (2 din 30 la timp, mediana 32,5 min) și Târgoviște (1 din 21); 59 de trenuri întârziate în fiecare zi în care au fost văzute; trenurile de noapte (IRN) — niciunul la timp la sosire (N = 25); ferestrele 06–09 și 15–18 la sosiri; prima întârziere anunțată crește la 43 % dintre sosiri.
- **„Ce merge bine”** pe scurt, apoi **„Problemele în detaliu”**: trenuri întârziate zi de zi (cu întârzierea fiecărei zile), ferestre de 3 ore și episoade de o zi (de ex. 22.10, 06–09), sosiri și plecări față în față, întârzieri foarte mari, direcții, creșterea întârzierii după primul anunț, tendința pe zile.
- **Indicator de acoperire:** zile parțiale (ziua în curs, ore excluse), pauze în citirea tabelei, rezultate neconfirmate/necunoscute și ce nu se poate concluziona încă (tendințe sub 7 zile, vremea, schimbările de linie, „cel mai bun operator”).

### Reparat
- **Statistici înșelătoare pe medie:** un singur tren cu 390 min (IR 16534, 23.10) făcea din 23:00 „ora cu cea mai mare întârziere” (mediana orei: 5 min) și din Cluj-Napoca „ruta cea mai întârziată”. Orele și rutele se clasează acum după mediană; o direcție trebuie să aibă cel puțin 2 trenuri diferite.
- Propoziția „cel mai punctual operator” (12 călătorii = 4 trenuri × 3 zile) a fost scoasă: operatorii au rute diferite (corelație, nu cauzalitate).
- Harta oră × zi a săptămânii avertizează că, sub 7 zile de istoric, fiecare zi a săptămânii e o singură dată.

### Tehnic
- `app/stats_problems.py` (nou, funcții pure, testat cu date sintetice, inclusiv sub eșantionul minim); secțiunea `problems` în `/api/stats/overview`, calculată pe aceeași conexiune read-only și același cache TTL.
- Analiza datelor: `docs/superpowers/analysis/2026-10-24-date-4-zile.md`.
- Service worker v23. Schema DB neschimbată (v7).

## Beta 1.18 — 2026-10-24

### Reparat
- **Panoul LIVE arăta uneori 13 trenuri, deși tabela fizică are mereu 12 rânduri.** Un tren care dispare de pe tabelă e trecut „plecat” abia după 3 citiri în care lipsește (ca o citire greșită de un cadru să nu-l scoată și să-l readucă). În acest interval rămânea și pe LIVE, lângă trenul nou intrat.
- Acum, după un cadru complet al panoului (toate cele 12 rânduri citite), LIVE arată doar trenurile din acel cadru. Trenul aflat în așteptare rămâne în baza de date și în istoric și devine „plecat” după aceleași reguli ca înainte; dacă reapare la următoarea citire, revine pe LIVE.
- Dacă ultimul cadru al unui panou nu a fost complet, dacă panoul a fost respins sau dacă datele lui sunt vechi, nu se ascunde nimic (comportamentul de până acum).

### Tehnic
- Service worker v22. Schema DB neschimbată (v7).
- Regulile pentru „plecat”, evenimentele, notificările, istoricul și statisticile nu s-au schimbat; se schimbă doar ce arată `/api/board`.
- După o repornire a serviciului nu se ascunde nimic până la primul cadru complet citit.

## Beta 1.17 — 2026-10-23

### Reparat
- **Întârzierile de peste 100 de minute acoperite de reflexie rămâneau necitite.** Caz real: IRN 401 KIEV - CHIȘINĂU, la Sosiri, cu „+100” pe tabelă (confirmat vizual). Pata albă acoperă vârful cifrei din mijloc, așa că pe un singur cadru cele două citiri alternau între 100, 160 și 180, iar valoarea era refuzată (corect: un singur cadru nu e sigur).
- Acum se votează între cadre: dacă „+” și „1”-ul de început sunt citite sigur, ultima cifră e clară și Tesseract vede și el trei cifre care încep cu „1”, valoarea candidată din fiecare cadru intră într-un vot pe ultimele 7 cadre ale aceluiași tren. Se acceptă doar o valoare văzută de cel puțin 4 ori și în majoritate. Pe cadrele reale: 100 citit în 5 din 12 cadre, celelalte rămân necitite; 160/180 nu sunt acceptate niciodată.
- Erorile de tip „+65 → +465” / „+20 → +240” (pata lipită de „+”) rămân refuzate: acolo tabela are două cifre și votul nu are niciun candidat.

### Calitate măsurată
- Setul de adevăr (384 de rânduri): nicio întârziere greșită, nicio valoare de 100+ falsă. Pe eșantionul de 683 de cadre reale (21–22.10), nicio valoare de 100+ nouă.

### Tehnic
- Service worker v21. Întârzierea acceptată prin vot e marcată `+delay-retry:vote:<n>` în versiunea observației.

## Beta 1.16 — 2026-10-23

### Reparat
- **Numărul trenului fără ultimul „1” (3021 → 302, 5011 → 501, 1661 → 166) sau cu „4” în loc de „1” (9101 → 9104, 1571 → 1574).** Cauza, găsită pe capturi: o îmbinare verticală între două module ale tabelei trece exact prin ultima cifră a numărului și rupe „1”-ul subțire în steag și picior. Segmentarea lipește acum la loc steagul de piciorul lui și o cifră tăiată în două (7909 nu mai devine 79091); o cifră de care șabloanele nu sunt sigure e păstrată doar dacă Tesseract o citește la fel, pe aceeași poziție.
- **Ora cu „1” citit „4” (1:10 → 1:40, 3:10 → 3:40):** linia luminoasă a îmbinării nu mai e luată drept cifră.
- **Peronul cu vârful cifrei tăiat (8 → 3, 6 → 5, 9 necitit):** în dreapta tabelei cifra peronului stă mai sus decât rândul (perspectivă); celula peronului se extinde acum în sus, fără cerneala rândului de deasupra. La oră, aceeași extindere se folosește doar când citirea normală e nesigură.
- **Peronul trebuie să fie între 1 și 14** (liniile din Gara de Nord); orice alt număr e o citire greșită și rămâne necitit.
- O recitire (altă binarizare) care pierde o cifră văzută la prima trecere nu mai e folosită.

### Calitate măsurată
- Set de adevăr nou: 16 capturi reale, 384 de rânduri, fiecare câmp verificat vizual pe imagine (`tests/fixtures/ocr_truth/truth.json`), cu scriptul `scripts/ocr_eval.py` (metrici pe câmp: corect / necitit / greșit) și teste care pică dacă OCR-ul citește mai prost decât acum.
- Greșeli pe setul de adevăr, Beta 1.15 → 1.16: nr. tren 19 → 4, oră 6 → 2, peron 5 greșite + 3 necitite → 1 greșit, tip 0 → 0, întârziere 0 → 0 (8 necitite rămase, sub reflexie), stație 2 → 2, operator 1 → 1.

### Tehnic
- Service worker v20. Observațiile noi au versiunea de procesare `ocr-tess-grid-4`. Observațiile vechi nu s-au modificat.

## Beta 1.15 — 2026-10-23

### Reparat
- **Întârzieri citite aiurea (ex. 465 sau 945 de minute).** Cauza, găsită pe capturile reale: o reflexie (o pată albă) pe tabelă acoperă prima cifră a întârzierii în primele rânduri de la Sosiri. Pata lipea semnul „+” de cifră, iar OCR-ul citea o cifră în plus („+65” devenea „+465”, „+20” devenea „+240”) sau alterna cifra ascunsă (60/80, 5/35/95).
- Coloana de întârziere se citește acum după regulile tabelei: întâi trebuie găsit semnul „+” (formă de cruce); numărul de cifre (1–3) vine din separarea glifelor; o cifră nesigură e acceptată doar dacă ambele metode de citire o văd la fel, și niciodată dintr-o zonă lipită de reflexie; o întârziere de 3 cifre (100+ minute) cere ca ambele citiri să fie sigure și de acord.
- Ce nu trece aceste reguli rămâne **necitit**: întârzierea lipsește pentru acel cadru, nu devine 0 și nu e ghicită. Celulele necitite sunt recitite automat cu alte preprocesări, în limita celor 8 secunde pe cadru.
- Istoric și grafice: o întârziere de 100+ minute din observații apare doar dacă a fost confirmată; revenirea dintr-o citire greșită („410 → 10”) nu mai face din 410 maximul citit.

### Nou
- Service worker v19. Observațiile au versiunea de procesare `ocr-tess-grid-3`, cu marcajul `+delay:<motiv>` (ex. `glare`) când întârzierea a rămas necitită și `+delay-retry:<variantă>` când a fost recitită.

## Beta 1.14 — 2026-10-23

### Nou
- **Statistici refăcute** (`#statistici`): pagina explică ce arată. Sus, „Pe scurt” — un rezumat în cuvinte generat din date (cât la sută au fost la timp la sosiri și la plecări, ora cu cea mai mare întârziere medie, ruta cea mai întârziată, cel mai punctual operator, ora cea mai aglomerată, linia folosită cel mai des, cât din întârzieri au fost citite), cu perioada, numărul de călătorii, trenuri și observații și ce s-a exclus (fantome, perioada de calitate redusă). Cât timp istoricul are sub 7 zile, un mesaj clar: „Date insuficiente încă — X zile de istoric”.
- Câte un card pe panou (Sosiri, Plecări) cu procentul la timp ca cifră principală, mediană, medie, p90, peste 30 min, maxim și N.
- Grafice noi, fiecare cu întrebarea la care răspunde, „Cum se citește”, legendă, N, avertisment de eșantion mic, tabel „Vezi datele” și export CSV: distribuția întârzierilor (0 / 1–5 / 6–15 / 16–30 / 31–60 / > 60 min), evoluția pe zile, mediana pe ora programată (cu banda N pe oră; orele cu sub 5 călătorii apar ca cercuri goale), harta oră × zi a săptămânii (celulele cu eșantion mic în gri), operatori și tipuri de tren (% la timp), rutele cele mai întârziate / cele mai punctuale, aglomerația pe ore (sosiri vs plecări), liniile (peroanele) folosite — „linie necitită” separat, nu ca linia 0 —, meteo și întârzieri (apare după 7 zile cu date; până atunci „în curs de adunare”; corelație, nu cauzalitate) și calitatea datelor (rezultate confirmate / neconfirmate / necunoscute, citiri OCR complete / nesigure / respinse / incomplete). Glosar la final.
- Filtre: perioadă (tot istoricul / 30 de zile / 7 zile / azi), panou, operator, tip de tren, doar rezultate confirmate — selecția rămâne în adresă (ex. `#statistici?perioada=7&board=arrival`), deci poate fi trimisă ca link.
- API: `GET /api/stats/overview` (aceiași parametri; `format=csv&set=…` exportă un set: distribution, hourly, heatmap, daily, operators, types, routes, traffic, platforms, weather).

### Tehnic
- Statisticile se calculează pe o conexiune SQLite separată, doar pentru citire — nu mai așteaptă și nu mai blochează citirea OCR a tabelei —, cu rezultat păstrat 60 s (`STATS_CACHE_TTL_S`) și un singur calcul simultan; pagina face o singură cerere.
- Culori de serie noi în ambele teme (sosiri albastru, plecări chihlimbar, o singură nuanță pentru harta de căldură), verificate pentru daltonism și contrast. Service worker v18.

## Beta 1.13 — 2026-10-22

### Schimbat
- **Istoric: implicit toate zilele.** Pagina Istoric nu mai pornește pe ziua de azi. Dacă nu alegi o zi, vezi tot istoricul, din toate zilele: cele mai noi primele, grupat pe zi, câte 200 pe pagină, cu butonul „Încarcă mai multe”. Câmpul „Ziua” rămâne gol, nu se completează singur cu data de azi.
- Orice filtru fără zi (număr de tren, stație, interval orar, sosiri/plecări) caută în toate zilele. Sus apar numărul total de călătorii și perioada (prima zi – ultima zi, câte zile).
- Dacă alegi o zi, lista arată doar ziua aceea. Butonul „Toate zilele” golește ziua și revine la tot istoricul.
- Filtrele se văd în adresa paginii (`#istoric`, `#istoric?date=…`, `#istoric?station=…&board=…`), deci o căutare se poate trimite cuiva.
- Rezumatul (N, medie, mediană, maxim, procente doar peste eșantionul minim) folosește doar întârzierile citite. O întârziere necitită nu este 0. Călătoriile din perioada de calitate redusă apar în listă, marcate, dar nu intră în rezumat.

### API
- `/api/history?all=1` merge acum și fără `train`: toate trenurile din toate zilele, cu `limit` (1–200) și `cursor`. Filtre opționale: `train`, `date`, `station`, `from`/`to`, `board`. `total` și `period` sunt calculate mereu la zi. Rezumatul pe toate trenurile se recalculează cel mult o dată la 60 de secunde, ca să nu țină baza de date ocupată. `/api/history` fără `all=1` rămâne neschimbat: o singură zi.

## Beta 1.12 — 2026-10-22

### Reparat
- **12 rânduri pe panou.** Tabela CFR are pe fiecare panou 4 grupuri a câte 3 rânduri. Când un rând avea text greu de citit (un „1” subțire lângă o linie de reflexie, un „*” mic, „13:38” citit „43:38”, ora „4:41” citită „4:4”), rândul se pierdea și panoul arăta 11 trenuri în loc de 12. Asta se întâmpla la aproximativ 1 cadru din 15. Acum un asemenea rând este recitit automat, doar pe coloanele tip, număr și oră, cu alte preprocesări (fără liniile de reflexie, prag mai mic sau mai mare, imagine mărită, prag adaptiv, decupaj mai larg). Recitirea are o limită de 8 secunde pe cadru.
- O recitire nu schimbă nicio valoare citită deja corect. Nu se acceptă numărul unui tren de pe alt rând, iar un cadru stricat (imagine trunchiată, cu peste 4 rânduri ilizibile pe un panou) nu se recitește: nu se inventează trenuri.
- Rândurile sunt verificate pe structura 4 × 3, derivată din imagine. Un rând slab sau gol își păstrează locul și nu se mai lipește de vecin. Un rând fără text e „rând gol”, unul cu text ilizibil e „rând necitit” (niciodată 0 sau tren ghicit).

### Nou
- `/api/health` → `ocr`: rândurile citite pe fiecare panou în ultimul cadru, câte rânduri au fost recitite și recuperate, durata OCR și câte cadre din ultimele 60 au avut 12/12.
- Capturi OCR (admin): fiecare captură arată „S 12 · P 11” și recitirile. Fiecare rând arată „rând gol” / „rând necitit” / „recitit (variantă)”. Versiunea de procesare a observațiilor este `ocr-tess-grid-2`.

## Beta 1.11 — 2026-10-22

### Reparat
- Istoric pe toate zilele, pe telefoane (390 px și mai înguste): rezultatul „necunoscut” împreună cu marcajul „calitate redusă” nu mai împinge pagina lateral (problema a apărut live la trenuri văzute și pe 21.10, în perioada beta).
- Marcajul „calitate redusă” trece pe rândul următor, sub rezultat, în loc să iasă din card.
- La fel pentru orice rezultat lung din cardurile Istoricului pe toate zilele: rândul „Rezultat” se poate împărți pe două rânduri.
- Istoricul pe o singură zi și tabelul de pe desktop rămân neschimbate.
- Teste noi în browser: niciun element din Istoric nu iese din ecran la 360, 390 și 1280 px, în temă luminoasă și întunecată.

## Beta 1.10 — 2026-10-22

Calitatea datelor, partea 2. Raportul de reanaliză din 22.10 a găsit trei probleme care apar
mai ales noaptea: dubluri noi, redenumiri care oscilează și treceri repetate dispărut/apărut.

### Reparat
- **Același rând citit alternativ ca două trenuri.** Exemplu: R 5011 / R 5014 BUZĂU 04:47, ore
  întregi. Citirea merge acum la serviciul cu cele mai multe citiri, deci cel minoritar nu mai
  „apare” și „dispare” la fiecare minut. Când iese de pe tabelă, e marcat ca fantomă dacă trenul
  real are cel puțin dublul citirilor lui. Două trenuri reale citite în același cadru nu sunt
  comasate niciodată.
- **Redenumirea trenului se face prin vot**, nu după „3 citiri la rând”: un număr nou trebuie să
  aibă cel puțin 3 citiri și 70% din ultimele 10. S-a oprit oscilația 7917→7914→791→7914→7911.
  Un tren nu mai e redenumit într-un număr trunchiat (1571 nu devine 157).
- **Linia:** 2/5 e acum tratată ca pereche de cifre confundabile (3 citiri pentru o schimbare).
- **Stații învățate:** un nume care repetă cuvintele unei stații cunoscute în altă ordine
  („KIEV - CHISINAU” față de CHISINAU-KIEV) nu mai e învățat ca stație nouă. Lista stațiilor
  învățate se recalculează din oră în oră (înainte, o dată pe zi).

### Bază de date
- Corecția retroactivă (`python -m app.quality`) marchează și perechile dispărut→apărut sub
  3 minute (`flap`) și fantomele „minoritare”. Rămâne idempotentă și nu modifică datele brute.
- `scripts/purge_ghosts.py` (implicit doar simulare; aplicarea o decide administratorul):
  - observațiile unei fantome trec la trenul ei real (comasare);
  - șterge întârzierile imposibile (de ex. 10→410→10), perechile dispărut→apărut sub 3 minute
    și rândurile de catalog fără nicio călătorie;
  - corectează întârzierea finală citită greșit (de ex. 945→15);
  - arhivează tot, cu posibilitate de restaurare;
  - nu folosește niciodată legături în lanț (RM 7919 09:50 e un tren real);
  - recalculează lista chiar în momentul aplicării.

## Beta 1.09 — 2026-10-22

### Adăugat
- **Istoric — tot istoricul unui tren:** când completezi „Nr. tren”, căutarea arată călătoriile trenului din **toate zilele** observate, cele mai noi primele, grupate pe zile. Pentru fiecare: data de serviciu, panoul (sosire/plecare), ora programată, stația, întârzierea finală (sau ultima citită) și maximul citit, rezultatul (confirmat / neconfirmat / necunoscut / în desfășurare), linia, plus link spre detaliu (grafic) și spre profilul trenului.
- Selectorul de zi devine „Toate zilele” (implicit când e completat un număr de tren) sau „O zi anume”. Se combină cu filtrele de stație, oră și panou. Fără număr de tren, Istoricul rămâne pe o singură zi, ca până acum.
- Antet: numărul de călătorii și perioada (prima–ultima zi) și un rezumat separat pe sosiri și plecări: N, medie, mediană și maxim, calculate doar din întârzierile citite. Sub eșantionul minim (implicit 5) nu se afișează procente.
- Paginare: câte 200 de călătorii, cu butonul „Încarcă mai multe”.
- API: `/api/history?train=N&all=1` (opțional `date`, `station`, `from`, `to`, `board`, `limit` ≤ 200, `cursor`).

### Reguli de date
- Întârzierea necunoscută rămâne „necitit”/necunoscută, nu 0, și nu intră în medie. Trenurile-fantomă nu apar. Evenimentele suspecte nu contează ca citiri. Călătoriile din perioada de calitate redusă (versiunea beta inițială) apar marcate, dar nu intră în rezumat (ca în statistici).

## Beta 1.08 — 2026-10-22

### Reparat
- **Meniul de sus se vede pe orice ecran.** Pe telefon, cu „Site pentru desktop” activat, pagina e așezată la ~980 px lățime (sub pragul vechi de 1024 px), iar meniul ajungea o bară fixă JOS, afișată micșorată — minusculă sau ieșită din ecran, niciodată sus. Acum meniul (Tabelă, Istoric, Urmărite, Trenuri, Statistici, Clasamente, Stații) e o bară proprie sub antet, lipită sus la derulare, la orice lățime: telefon, telefon culcat, tabletă, desktop, „Site pentru desktop” pe Chrome Android și Safari iOS.
- Când elementele nu încap, bara se derulează orizontal în interiorul ei (pagina nu se mai mișcă lateral); secțiunea curentă e adusă automat în vedere. Ținte de atingere de cel puțin 44 px; pe ecrane tactile, ceva mai mari; în „Site pentru desktop” (pagina micșorată), mult mai mari, ca să rămână lizibile.
- Bara de jos de pe telefon a fost înlocuită de bara de sus (un singur meniu, nu două).
- **Stații** are acum intrare în meniu; paginile unei stații o evidențiază (înainte evidențiau „Trenuri”).
- Istoric: filtrele nu mai împing pagina lateral pe tablete și pe telefoane culcate (760–1023 px).

## Beta 1.06 — 2026-10-22

Calitatea datelor (analiza din 21.10 pe baza live). Datele citite rămân în baza de date
așa cum au fost citite; corecțiile sunt marcaje și câmpuri separate, iar nimic nu se șterge.

### Reparat
- **Întârzieri imposibile:** semnul „+” citit ca cifră („+25” citit 425, „+10” citit 410, „+20” citit 240, „+45” citit 435) nu mai ajunge pe tabelă. O asemenea valoare se aplică doar dacă rămâne aceeași 5 citiri la rând, cum ar face o întârziere reală de 150 după 15.
- Orice schimbare de întârziere se aplică abia la a doua citire identică consecutivă. Un salt mare (de cel puțin 60 de minute, la peste 100 de minute) se aplică la a treia. Oscilațiile de tip 15→45→15 nu mai produc evenimente sau notificări.
- **Linia (peronul):** o schimbare se aplică la a doua citire identică. Pentru cifrele pe care OCR-ul le confundă (5/6; 1/4/11/14; 3/8) e nevoie de a treia citire, iar o linie ștearsă trebuie citită goală de două ori. Prima linie afișată apare imediat.
- **Apariții/dispariții:** un tren e scos de pe tabelă după 3 citiri lipsă (înainte, 2). Dacă revine în cel mult 10 minute, nu mai apare o „apariție” nouă. Dacă a ieșit cu adevărat după ce revenise, urmăritorii primesc din nou notificarea.
- **Trenuri-fantomă:** sunt citiri greșite ale unui număr sau ale unei ore (de ex. R 5011 citit 5014, 50141, 501…) sau trenuri văzute mai puțin de 2 minute. Sunt marcate (nu șterse) și nu mai apar în Panou, Istoric, catalogul de trenuri, statistici, clasamente și paginile de stații. Ieșirea lor de pe tabelă nu mai trimite notificări.
- **Tip tren:** „I” citit pe un număr de 3 cifre devine IC (531, 536, 553, 571, 581). „RN”/„RND”/„RNE”/„RIM”/„RR” pe numerele navetei Aeroport 79xx devin RM. Asteriscul („*”) se tratează separat de tip. Alte tipuri ilizibile rămân necitite: nu se ghicesc.
- **Stații:** lista de stații cunoscute are acum 45 de nume reale. Variantele OCR se recunosc: „AD JUD” → ADJUD, „ARAD E” → ARAD, „RUSE I” → RUSE, „TIMISOA.RA NORD” → TIMISOARA NORD, „PLOIESTISUD” → PLOIESTI SUD. Un nume la 1–2 caractere de o stație cunoscută (sau care conține „!”, „.”) nu mai e învățat ca stație nouă.
- **Operatori:** au fost adăugați Softrans Calat și Ferotrafic. Variantele citite greșit („CFR Calaitori”, „Transfernviar”, „Sofirans Calat”) se afișează cu numele corect; textul citit rămâne păstrat.
- **Capturi:** eroarea „argmin of an empty sequence” (2 cadre pierdute pe 21.10) e reparată. La o celulă degenerată se folosește citirea Tesseract, iar evenimentul apare în jurnal.

### Bază de date
- **Schema v7** (după v6): tabelele `service_quality` (fantomă, perioadă de calitate redusă, întârziere maximă/finală confirmată, stație/operator canonic), `event_quality` (evenimente suspecte și motivul), `quality_periods`, `dq_meta`. Migrarea e aditivă și atomică, fără modificarea datelor existente.
- **Corecție retroactivă:** `python -m app.quality --db … [--dry-run]` e idempotentă și nu modifică nimic din datele brute. Recalculează marcajele: fantome, evenimente de întârziere suspecte, `max_delay_clean`/`last_delay_clean` doar din valori confirmate (lipsă = necunoscut, niciodată 0) și numele canonice.
- **Perioada 21.10.2026 00:00–11:31** (versiunea veche, înainte de capturi) e marcată „calitate redusă (beta)” și e exclusă implicit din statisticile publice. O poți include cu `STATS_INCLUDE_LOW_QUALITY=1`.
- `scripts/purge_ghosts.py`: implicit doar afișează ce ar elimina (dry run). Cu `--apply` face întâi o copie completă a bazei, apoi arhivează reversibil rândurile în `purged_rows`. Cu `--restore` le pune la loc. Nu se rulează automat.

## Beta 1.05 — 2026-10-21

### Adăugat
- **Pagini pe stații** (`#statie?nume=…`): click pe numele unei stații oriunde apare (Panou, Carduri, Istoric, profil tren, Trenuri, Clasamente) deschide istoricul trenurilor care vin dinspre stație (sosiri) și pleacă înspre ea (plecări), separat: N călătorii și trenuri, perioada, medie / mediană / p90 / maxim, % la timp, peste 30 min, distribuția, medii pe oră / zi / lună, tabelul trenurilor, ultimele călătorii (paginate, cu rezultatul și graficul fiecăreia), export CSV/JSON.
- Avertisment explicit pe fiecare pagină de stație: întârzierea este cea afișată pe tabela din București Nord, nu la stația respectivă; trenurile sunt atribuite stației doar când tabela o afișează ca origine sau destinație.
- **Lista stațiilor** (`#statii`) cu căutare (și cu diacritice: „Galați” găsește GALATI), marcaj „nume nesigur”, export.
- **Clasamentul stațiilor** în Clasamente (cele mai întârziate / punctuale, pe panou, doar cu eșantion minim, N afișat) și poziția fiecărei stații în clasament pe pagina ei.
- API public: `/api/stations?query=`, `/api/stations/{nume}`, `/api/stations/{nume}/journeys` (paginat, `before=`), JSON și `format=csv`; numele stațiilor sunt cele canonice (fără diacritice).

## Beta 1.04 — 2026-10-21

### Adăugat
- **Rezultatul final al fiecărei călătorii** (în detaliul din Istoric): „confirmat” doar cu dovadă — întârzierea citită cu cel mult 15 min înainte ca trenul să dispară de pe tabelă, iar dispariția observată după ora estimată (programat + întârziere). Altfel „neconfirmat” (cu motivul) sau „necunoscut”; niciodată presupus.
- **Data de serviciu** afișată explicit (ziua orei programate; un tren de 00:05 citit la 23:58 aparține zilei următoare) și graficul evoluției întârzierii din citirile reale, cu momentul dispariției.
- **Trenuri**: catalog cu un rând pe număr de tren și panou — N călătorii, câte au întârzierea citită, % la timp (prag configurabil), medie, mediană, p90, maxim, peste 30 min, calitatea datelor; căutare, sortare, export CSV/JSON.
- **Profil tren** (`#tren?nr=`): statistici separate pe sosiri și plecări, distribuția întârzierilor, lista călătoriilor cu rezultatul fiecăreia.
- **Statistici**: perioada, călătorii / trenuri / observații, calitatea datelor, distribuții și medii pe oră, zi a săptămânii și lună, cu filtre (panou, perioadă, prag, eșantion minim, doar confirmate).
- **Clasamente**: cele mai întârziate și cele mai punctuale trenuri, doar cu eșantion minim (implicit 5 călătorii), cu N afișat și avertisment când nu există suficiente date.
- API public: `/api/journeys`, `/api/journeys/{id}`, `/api/trains/stats`, `/api/trains/{nr}/journeys`, `/api/stats`, `/api/stats/rankings` (JSON și `format=csv`); `/api/stations*` pregătit pentru paginile pe stații.

### Reguli de date
- Întârzierea folosită este ultima valoare CITITĂ pe tabela din București Nord, doar cu dovada citirii (schema DB v6, `delay_read_at`). Pentru călătoriile de dinainte, dovada vine doar din observațiile OCR păstrate; restul au întârzierea „necunoscută” (nu 0) și nu intră în statistici.
- Sub eșantionul minim se afișează doar cifrele brute, fără procente și fără p90.
- Un salt al întârzierii de peste 30 min într-un singur cadru (ex. „15” citit „945”) se aplică doar după a doua citire identică.

## Beta 1.03 — 2026-10-21

### Reparat
- Modul „Panou”: lățimea coloanelor nu mai depinde de date — numele lungi de stație sau operator (ex. „Chișinău Triaj Internațional – Nord”) nu mai lățesc zona de text și coloanele nu mai sar de la o actualizare la alta (tabel cu lățimi fixe).
- Textul lung (stație, operator, stare) se afișează pe cel mult 2 rânduri, apoi „…”; valoarea completă rămâne în tooltip (title), în detaliul trenului și pentru cititoarele de ecran.
- Toate rândurile au aceeași înălțime, în ambele panouri.
- Ecran complet pe desktop: coloanele „Sosiri” și „Plecări” au aceeași lățime, antetele și rândurile sunt aliniate sus și pe orizontală; fontul se adaptează când cele două panouri stau alăturate.
- Modul „Carduri”: pe desktop, cele două coloane au aceeași lățime și cardurile aceeași înălțime (rândurile rămân aliniate); operatorul lung e trunchiat cu „…”, numele complet e în tooltip. Pe telefon, stația are cel mult 2 rânduri și nu apare scroll orizontal.
- Butonul „Caută, filtrează, sortează” nu mai apare pe desktop (era vizibil deși filtrele sunt deja deschise).

## Beta 1.02 — 2026-10-21

### Reparat
- Un tren nu mai apare de două ori pe tabelă când OCR-ul citește greșit un singur caracter din număr sau din oră (ex. „1234” citit „1284”, „06:52” citit „05:52”): rândul se asociază trenului deja afișat, pe același panou, aceeași stație și aceeași zi; trenurile care diferă prin două sau mai multe cifre sau prin stație rămân separate.
- Dacă tocmai prima citire a unui tren a fost cea greșită, trenul își primește numărul (sau ora) corect după 3 citiri consecutive care îl confirmă — urmăririle și notificările merg pe numărul real.
- Un tren nou citit cu încredere scăzută intră pe tabelă abia la a doua citire consecutivă; `/api/board` comasează orice dublură rămasă (două trenuri citite în același cadru rămân separate).
- Citiri parțiale („doar 2 rânduri” pe un panou): dacă un panou are brusc sub jumătate din rândurile ultimei citiri bune, cadrul e respins pentru acel panou — se păstrează ultima stare bună, trenurile nu sunt marcate dispărute, iar celălalt panou se actualizează în continuare.
- Doar panoul afectat e marcat „date vechi” (în Carduri și în Panou); `/api/board` și `/api/health` au câmpul `boards` cu vechimea fiecărui panou.
- OCR mai robust la variații de expunere și lumină (zori/amurg): prag de text adaptiv pe fiecare panou, detecția rândurilor tolerantă la separatoare și reflexii, recuperarea „:” din oră; testat pe o a doua imagine de referință și pe variante augmentate (luminozitate, gamma, contrast, blur, zgomot).

### Diagnostic
- Cadrele respinse se salvează (imagine + motiv) în `REJECTED_DIR` (implicit `/var/lib/tabela/rejected`, ultimele 40), cu avertisment în jurnal.

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
