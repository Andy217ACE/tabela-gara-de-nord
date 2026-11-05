# © 2026 Andy217Ace
# Val 5b (peron) — Predicția peronului, design

Data: 2026-11-05. Referință: `docs/superpowers/specs/2026-10-31-val5-predictie-linie.md` (DRAFT, decizia 2 „peron, da sau nu”). Utilizatorul a decis: DA, peron, ca spec separat. Model de structură, teste și poartă: `app/predict.py` (întârziere, Beta 1.38).

## Decizii (alese autonom, documentate aici)

1. **Ce prezicem.** Peronul (linia de plecare/sosire) pe care va apărea un serviciu, identificat prin tren, stație, bord și dată. Output: un peron, ca estimare etichetată „Estimare”, cu N (numărul de citiri din grup) și procentul (share-ul peronului câștigător). Niciodată ca „citit”.
2. **Sursa.** Doar observații cu `validation_state = 'ok'` și `platform IS NOT NULL` (peron citit, nu „necitit”, nu NULL), legate de un serviciu (`observations.service_id`) din servicii publice (`quality.public_services_where`: fără ghosturi, fără perioada de calitate redusă). Adevărul de referință pentru un serviciu = peronul modal din observațiile lui valide; dacă există egalitate, serviciul e exclus din backtest.
3. **Unitatea de numărare.** O citire = un serviciu cu peronul lui modal (nu fiecare cadru OCR), ca un serviciu cu 40 de cadre să nu conteze de 40 de ori.
4. **Ierarhie.**
   - (a) tren + stație + bord, doar istoricul din ultimele 60 de zile strict anterioare zilei predicției; prag n ≥ 5 și peron dominant ≥ 60%.
   - (b) stație + bord + oră programată (bucket de 1h) + zi a săptămânii, tot istoricul anterior; prag n ≥ 20 și peron dominant ≥ 60%.
   - Se folosește primul nivel care trece ambii pragi. Nimic: fără predicție.
5. **Prag de încredere.** Peronul dominant are ≥ 60% din citirile grupului (`share >= 0.60`, inclusiv). Sub prag la ambele niveluri: fără predicție.
6. **Linia de bază.** Ultimul peron citit pentru același tren, la aceeași stație și același bord, dintr-o zi anterioară. Fără istoric: linia de bază lipsește (cazul e exclus din comparația de bază, dar rămâne în N).
7. **Zgomot OCR (5↔6, 3↔8).** Nu se aplică nicio corecție ad-hoc. Confuziile sunt tratate ca zgomot. Backtestul raportează câte predicții greșite sunt exact aceste confuzii, și cota lor printre greșelile liniei de bază, ca să se vadă dacă predicția le amplifică.
8. **Backtest temporal.** Zilele se parcurg în ordine. Predicțiile pentru ziua t folosesc doar servicii din zile strict anterioare lui t; după ce toate predicțiile zilei t sunt făcute, ziua devine istoric. Fără scurgere din viitor.
9. **Poarta de publicare (ca la întârziere, cu criteriile cerute de utilizator).** Publicat doar dacă, pe backtest:
   - N predicții evaluate ≥ 100;
   - acuratețea predicției pe cazurile cu predicție ≥ 80%;
   - acuratețea predicției ≥ acuratețea liniei de bază + 5 puncte, pe același set (cazuri cu predicție și linie de bază).
   Interpretarea „≥ 80% dintre cazurile cu predicție corecte” = acuratețea pe cazurile cu predicție, de aceeași formă cu pragul de 80%.
10. **Publicare.** Nu se adaugă rută publică și nu se schimbă interfața în această etapă. Dacă poarta nu trece: rămâne doar cod intern (funcții și script de backtest). Dacă trece, un endpoint ar veni într-o etapă separată, în spatele unui flag implicit oprit; în acest branch nu se adaugă endpoint.
11. **Schema bazei rămâne v9. Nicio scriere în DB.** Modulul citește cu conexiune `mode=ro`; scriptul refuză calea de producție `/var/lib/tabela/tabela.db`.

## Interfețe

`app/peron_predict.py` (funcții pure, fără scriere):

- `Case(service_id, service_date: str, train_no: int, station: str, board: str, sched_time: str, platform: int)`: serviciu cu peron adevărat (modal).
- `Prediction(platform: int, n: int, share: float, basis: str)`, basis ∈ {"a", "b"}.
- `Pool`: istoric incremental. `add(case)`; `predict(case) -> Prediction | None`; `baseline(case) -> int | None`.
- `Evaluation(service_id, service_date, truth, prediction, baseline)`.
- `load_cases(conn) -> list[Case]`: doar SELECT.
- `walk_forward(cases) -> list[Evaluation]`.
- `report(evals, cases) -> dict`: `n_cases`, `n_pred`, `n_nopred`, `acc_pred`, `n_common`, `acc_pred_common`, `acc_base_common`, `by_level`, `wrong_pairs_56_38`, `wrong_pairs_share`, `good_days`.
- `gate(rep) -> Gate(published: bool, reason: str)`.

`scripts/backtest_peron.py --db COPIE.db`: refuză calea de producție, deschide cu `mode=ro`, afișează N, acuratețea predicției, linia de bază, cazuri fără predicție, confuziile 5↔6 / 3↔8, decizia porții.

## Testare

`tests/test_peron_predict.py` (TDD, pas cu pas, vezi planul):
- ierarhie: nivel (a) cu n=5 și 60%; sub 5 nu; nivel (b) cu n=20; sub 20 nu; fereastra de 60 de zile la nivelul (a);
- praguri: 60% inclusiv, 59% exclus; egalitate exclusă;
- zgomot OCR: 10 citiri de 5 și 3 de 6 → prezice 5 (nu se amplifică);
- backtest: fără scurgere din viitor (adăugarea unei zile viitoare nu schimbă predicțiile zilelor anterioare); predicțiile folosesc doar zile anterioare;
- linia de bază: ultimul peron citit din zi anterioară;
- poartă: sub 100 de predicții, sub 80%, diferență sub 5 puncte, și trecere completă;
- nicio scriere: `load_cases` și predicțiile nu schimbă `total_changes` și conținutul tabelelor;
- script: refuză `/var/lib/tabela/tabela.db`.

## Risc

- **Date puține.** Pe baza live (câteva zile de date la 2026-11-05), nivelul (b) poate avea rar n ≥ 20. Asta e un rezultat, nu un bug: poarta ar trebui să respingă. Se raportează numărul de cazuri fără predicție.
- **OCR.** Peronul citit greșit din ziua adevărului strică și adevărul, și predicția. Măsurat, nu corectat.
- **Peroane schimbate.** Peroanele se pot schimba în timp; fereastra de 60 de zile la nivelul (a) limitează asta, nivelul (b) nu are fereastră (se acceptă, se raportează).
- **Estimare ca promisiune.** Pe pagină (când și dacă se afișează) trebuie „Estimare”, N și procentul; în acest branch nu se afișează nimic public.
- **Ora de vară / schimbarea orarului.** Nu se corectează; zilele sunt tratate ca zile normale.

## Rezultat backtest (2026-11-05, copia bazei live, read-only)

- Servicii cu peron adevărat: 2157, în 7 zile.
- Predicții evaluate: 133 (toate la nivelul a); fără predicție: 2024.
- Acuratețe predicție: 48,9 %. Linia de bază pe aceleași 133 de cazuri: 34,6 %.
- Greșeli 5↔6 / 3↔8: 1 din greșelile predicției (1,5 %); 1,1 % din greșelile liniei de bază.
- Decizie poartă: NU TRECE (acuratețe 48,9 % sub pragul de 80 %). Rămâne cod intern; nicio rută publică, nicio schimbare de interfață.
