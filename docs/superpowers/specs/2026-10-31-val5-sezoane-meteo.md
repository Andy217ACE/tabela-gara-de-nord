# Val 5a — Meteo pe sezoane (Beta 1.37)

> **DRAFT: aprobarea utilizatorului este obligatorie înainte de cod.** Deciziile de mai jos trebuie confirmate, mai ales 1, 2 și 4.

Sursă: `docs/superpowers/plans/2026-10-27-backlog-wave.md`, Partea 5a; `docs/superpowers/specs/2026-10-21-roadmap-v2-direction.md`, etapa G.

**Scop:** arătăm pe sezoane cum se asociază întârzierea citită a călătoriilor cu condițiile meteo observate, fără cauzalitate și fără cifre sub pragul de date.

## Ce intră
- Grupare pe sezon, cu bordurile sosiri și plecări separate (nu se amestecă).
- Pentru fiecare sezon eligibil: mediana întârzierii citite și procentul la timp, pe grupe de precipitații (cu / fără) și de temperatură (benzile din `app/stats_overview.py`), cu N afișat.
- Sezoanele sub prag apar ca „date insuficiente (N=…)”, fără grafic.
- Text fix „corelație, nu cauzalitate”, grafic, „Cum se citește” și export CSV, ca la celelalte seturi.

## Ce NU intră
- Regresie sau model de predicție a întârzierii din vreme.
- Corecție pentru ora din zi, trafic sau orar. Doar afișare stratificată pe bord.
- Meteo măsurat la stații. Sursa e modelul Open-Meteo (`kind=model_current`); eticheta rămâne.
- Import de istoric meteo (vezi decizia 4) și orice schimbare de schemă.

## Decizii deschise pentru utilizator
1. **Ce înseamnă sezon.** Recomandare: sezoane meteorologice calendaristice (dec–feb, mar–mai, iun–aug, sep–nov), ca în roadmap („mar–mai etc.”). Alternativa, anotimpurile astronomice, aduce limite mobile fără câștig practic.
2. **Prag minim N.** Recomandare: ≥ 30 de zile eligibile per sezon, unde o zi e eligibilă dacă are cel puțin 50 % din observațiile meteo așteptate (~48 din 96). Așa fiecare zi a săptămânii apare de cel puțin 4 ori. Blocul existent folosește 7 zile (`WEATHER_MIN_DAYS`); pentru comparația pe sezoane propun 30.
3. **Indicatorul principal.** Recomandare: mediana și % la timp, nu media, pentru că media e mutată de un singur caz extrem (cum s-a văzut la Beta 1.17).
4. **Import istoric din arhiva Open-Meteo.** Recomandare: nu acum. Ar da sezoane complete imediat, dar amestecă două surse (model curent și reanaliză) și cere verificarea termenilor de utilizare (CC BY 4.0, uz necomercial gratuit, de verificat).
5. **Schimbarea orarului CFR.** Recomandare: excludem ±7 zile în jurul schimbării de orar din comparația dintre sezoane, pentru că baza de întârziere se schimbă odată cu orarul. Data exactă trebuie confirmată de utilizator.
6. **Prag pentru comparație între grupe.** Recomandare: ≥ 30 de călătorii per grupă pentru a compara sezoanele. Pragul de 5 rămâne doar pentru procente pe o singură grupă.

## Date disponibile acum vs. după acumulare
- **Acum (31.10.2026):** colectare meteo din ~21.10 (290 de observații în primele 4 zile, conform analizei din 24.10). Există un singur sezon, toamna, parțial (~10 zile). Se poate scrie acum `weather_by_season` și testa pe date sintetice, dar nu se poate afișa niciun sezon eligibil.
- **~20.11.2026:** toamna atinge 30 de zile eligibile.
- **Primul rezultat curat:** cel mai devreme în ianuarie 2027 se pot compara toamna 2026 și iarna 2026/27, dar schimbarea de orar din decembrie amestecă comparația (decizia 5). Recomand să publicăm prima concluzie după vara 2027 (sfârșitul lui august), când există cel puțin două sezoane eligibile fără schimbare de orar între ele. De confirmat.

## Riscuri
- **Corelație prezentată ca cauzalitate:** „iarna întârzie mai mult” poate fi orarul, traficul, lucrările sau ora din zi. Mitigare: text fix, verbe de asociere („se asociază”), fără concluzii dintr-un singur sezon.
- **Confuzie cu sezonul:** iarna are și alt orar și alte condiții de trafic.
- **Valoare lipsă tratată ca 0:** o zi fără meteo nu e zi cu vreme bună. Trebuie să rămână „lipsă”.
- **Fus orar:** meteo e în UTC (`Z`), observațiile sunt locale. Schimbarea orei din 25.10.2026 e deja în date; potrivirea ±30 min trebuie testată în acea noapte.
- **Model, nu stație:** vremea e valoarea modelului pentru celula din jurul Bucureștiului, aceeași pentru toate stațiile.
- **Independență:** întârzierile dintr-o zi sunt corelate; 30 de zile nu înseamnă 30 de observații independente.

## Criterii de acceptare
1. Un sezon cu mai puțin de 30 de zile eligibile → `enough=False`; UI afișează „date insuficiente (N=…)” și nu randează grafic (test).
2. Zilele cu sub 50 % din observațiile meteo nu intră în nicio grupă; zilele fără meteo nu devin 0 (test).
3. Atribuirea sezonului e corectă pe limite (1 dec, 28 feb, 31 mai, 31 aug, 30 nov), în ora României (test).
4. Potrivirea ±30 min funcționează în noaptea schimbării orei (test cu marcaje UTC și locale).
5. Fiecare cifră afișată are N; procentele lipsesc sub prag.
6. „Corelație, nu cauzalitate” apare lângă grafic; textele nu conțin formulări cauzale (test de conținut).
7. Exportul CSV al setului `weather` conține aceleași N ca pagina.
8. Fără migrație nouă de schemă (test).

**Metoda:** descriptivă, fără model. Mediană și % la timp pe grupe, cu N. Compararea între sezoane doar când există cel puțin două sezoane eligibile. Intervalele de încredere nu intră în prima versiune; pot fi adăugate ulterior, ca decizie separată.
