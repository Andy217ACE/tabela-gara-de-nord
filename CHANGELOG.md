# Istoric versiuni — Tabela Gara de Nord

Schema versiunilor: `Beta 1.NN`, unde NN crește cu 1 la fiecare deploy pe
tabelacfr.ddns.net. Cele mai noi versiuni sunt sus.

© 2026 Andy217Ace · Date preluate de la CFR (cfr.ro) — proiect independent, neafiliat CFR

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
