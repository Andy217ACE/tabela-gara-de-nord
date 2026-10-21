# Istoric versiuni — Tabela Gara de Nord

Schema versiunilor: `Beta 1.NN`, unde NN crește cu 1 la fiecare deploy pe
tabelacfr.ddns.net. Cele mai noi versiuni sunt sus.

© 2026 Andy217Ace · Date preluate de la CFR (cfr.ro) — proiect independent, neafiliat CFR

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
