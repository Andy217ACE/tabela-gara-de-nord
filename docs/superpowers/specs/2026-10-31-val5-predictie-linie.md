# Val 5b — Predicția liniei la final (Beta 1.38)

> **DRAFT: aprobarea utilizatorului este obligatorie înainte de cod.** Decizia 1 (ce prezice exact) trebuie luată prima, pentru că schimbă tot restul.

Sursă: `docs/superpowers/plans/2026-10-27-backlog-wave.md`, Partea 5b; `docs/superpowers/specs/2026-10-21-roadmap-v2-direction.md`, etapa H.

**Scop:** afișăm o estimare etichetată ca atare, cu interval și N, a întârzierii finale a unui tren, construită doar din istoricul observat și validată pe date din trecut.

## Ce intră (presupunând decizia 1: întârziere finală)
- `app/predict.py` cu `predict_final` și `Prediction(delay_min, low, high, n, basis)`; endpoint `GET /api/trains/{no}/prediction`.
- Ierarhie de bază, cu prima variantă care are n ≥ 10 sau n ≥ 30 pe stație:
  (a) mediana aceluiași tren, în aceeași zi a săptămânii;
  (b) mediana aceluiași tren;
  (c) mediana pe stație, oră și zi a săptămânii (n ≥ 30).
- Etichetă „Estimare”, N, interval P25–P75, afișat separat de „Întârziere citită”.
- Pagină de metodologie cu backtestul: eroarea absolută medie (MAE) și procentul de valori reale în interval.

## Ce NU intră
- Model opac (ML, rețele, boosting) sau meteo ca variabilă.
- Predicție de peron (vezi decizia 2).
- Estimarea în statistici, istoric sau alerte. Nu se scrie în `services` și nu intră în `stats.counted`.
- Înlocuirea valorii citite pe panoul LIVE. Ultima întârziere citită rămâne sursa principală.

## Decizii deschise pentru utilizator
1. **Ce prezice 5b.** Documentele nu se potrivesc: planul (interfața cu `delay_min`) și titlul cer întârziere finală, iar roadmap-ul (etapa H, „Linie estimată”) folosește „linie” pentru peron. Recomandare: întârziere finală. Peronul ar fi un spec separat.
2. **Peron, da sau nu.** Recomandare: nu acum. În primele 4 zile, majoritatea celor 161 de schimbări de peron erau confuzii OCR (5↔6: 57, 3↔8: 28), deci semnalul e dominat de eroarea de citire.
3. **Definiția „comparabil”.** Recomandare: același număr de tren, aceeași stație, același bord, aceeași zi a săptămânii pentru nivelul (a). Alternativa, fără ziua săptămânii, dă mai multe date dar mai puțină precizie.
4. **Prag de publicare.** Recomandare: 5b nu se publică înainte de 30 de zile de date de calitate (~20.11.2026, din planul de backlog), chiar dacă unele trenuri au n ≥ 10 mai devreme.
5. **Criteriul de a publica.** Recomandare: 5b se livrează doar dacă bate linia de bază „ultima întârziere citită” pe MAE, în backtest. Dacă nu o bate, nu se livrează și afișăm doar ce e citit.
6. **Interval.** Recomandare: P25–P75. P10–P90 acoperă mai bine, dar e prea larg ca să ajute.

## Date disponibile acum vs. după acumulare
- **Acum:** ținta e `last_delay_clean` din `service_quality` (NULL = necunoscut, nu 0). Analiza din 24.10 arată 1.157 de călătorii publice în 4 zile, 1.133 încheiate, 408 trenuri distincte, dintre care 346 apar în 3 zile și niciunul în 5 sau mai multe. Nivelul (a) nu are sens acum.
- **Nivelul (b), tren:** pentru trenurile zilnice, n ≥ 10 vine în jur de 4 noiembrie 2026 (~14 zile de colectare, cu ~3 din 4 zile). Trenurile rare vin mai târziu sau nu vin deloc.
- **Nivelul (c), stație:** cu ~30 de zile, ~20.11.2026, pentru ca fiecare zi a săptămânii să aibă cel puțin 4 ocurențe.
- **Backtest:** `tests/fixtures/live_v2.db` nu ajunge. Are 4 servicii dintr-o singură zi (20.10.2026). Backtestul cere o copie read-only a bazei de producție, aprobată de utilizator. Nu m-am conectat la server pentru acest spec.

## Riscuri
- **Corelație ca explicație:** o estimare nu explică de ce întârzie trenul. Text fix, etichetă „Estimare”, N și interval.
- **Estimarea pare promisiune:** utilizatorul o poate lua ca fapt. Mitigare: interval vizibil, fără cifră punctuală.
- **Scurgere din viitor:** backtestul trebuie să folosească doar date cunoscute înainte de momentul predicției.
- **Plecările:** la plecări, întârzierea citită e cea anunțată înainte de plecare, nu ora reală. Asta trebuie scris pe pagină.
- **Schimbarea orarului și ora de vară:** datele din jurul schimbărilor nu sunt comparabile direct (25.10.2026 e deja în date).
- **Trenuri cu puține zile:** n ≥ 10 poate veni din aceeași săptămână repetată. De aceea există nivelul (b) și pragul de 30 de zile.
- **Confirmare:** folosim doar călătorii cu rezultat confirmat (`confirmed_only` din `stats.Params`).

## Criterii de acceptare
1. `predict_final` întoarce `None` când n < 10 (test).
2. Apelul de predicție nu scrie în nicio tabelă și nu schimbă numărătoarea din `stats` (test: înainte și după apel).
3. Backtestul e temporal: niciun test nu folosește date ulterioare punctului de predicție (test cu o zi „viitoare” injectată).
4. Backtestul raportează MAE și procentul de valori reale în interval, cu N pe grup.
5. MAE-ul estimării < MAE-ul liniei de bază „ultima întârziere citită”, pe același set. Altfel 5b nu se livrează (criteriu de oprire).
6. UI: eticheta „Estimare” și N sunt vizibile și separate de „Întârziere citită”.
7. Nicio cifră sub pragul de eșantion.

## Metoda
- Mediane pe grupe, în ierarhia (a) → (b) → (c). Nu există model opac.
- Interval: P25–P75 al aceluiași eșantion.
- Backtest: pentru fiecare zi t din setul de test, se „antrenează” pe datele până la t−1 și se prezice pentru călătoriile din t. Linii de bază: „ultima întârziere citită” și „mediana trenului”.
- Se publică MAE, mediana erorii, procentul în interval și N pe grupă, pe pagina de metodologie. Cifrele se actualizează la fiecare versiune.
