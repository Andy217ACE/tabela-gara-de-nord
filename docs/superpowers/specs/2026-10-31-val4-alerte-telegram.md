# Val 4d — Alerte Telegram (DRAFT)

> **DRAFT — aprobarea utilizatorului este obligatorie înainte de orice cod.**
> Sub-plan 4d din `docs/superpowers/plans/2026-10-27-backlog-wave.md`, Partea 4. Versiune provizorie: Beta 1.36. Depinde de 4c (setări).

**Scop:** Alertele existente ajung și pe Telegram, ca opțiune, fără să se schimbe regulile de alertă și fără ca Telegram să poată opri panoul.

## Ce intră
- Canal Telegram adăugat pe același `Notifier`, cu aceeași semnătură `send(sub, data)`.
- Destinatar fix, configurat în mediu (token și ID de chat), opțional și implicit oprit.
- Text scurt în română, cu ora citirii, pe aceeași regulă de confirmare (alertă confirmată în cel puțin `confirm` citiri).

## Ce NU intră
- Comenzi interactive pentru bot.
- Abonare multi-utilizator și cod de legare a chatului (după prima versiune).
- Alerte pe grupuri publice.
- Alerte pentru predicții sau estimări (acestea sunt etichetate separat, în 5b).

## Decizii deschise pentru utilizator
1. **Cine primește alertele?** Recomandare: doar administratorul, printr-un singur chat configurat în mediu.
2. **Cum se leagă chatul?** Recomandare: ID fix în mediu, fără pagină nouă de abonare.
3. **Ce tipuri de alertă?** Recomandare: aceleași ca la Web Push (întârziere peste prag, anulare, dispariție confirmată). Nu „date vechi”.
4. **Doar trenurile urmărite sau toate?** Recomandare: doar cele urmărite, ca la Web Push, ca să evităm zgomotul.
5. **Ce facem când Telegram e indisponibil?** Recomandare: nu retrimitem. Eroarea se loghează cel mult o dată la 10 minute. Retrimiterea ar putea livra alerte vechi.

## Riscuri
- Token scurs. Mitigare: doar în mediu, niciodată în repo, log sau CHANGELOG.
- Limită de cereri (429) sau timeout de la Telegram blochează poller-ul. Mitigare: trimiterea nu blochează ciclul de citire.
- Alertă dublată după repornire, dacă deduplicarea e doar în memorie. De verificat în `app/notifier.py` înainte de implementare.

## Criterii de acceptare
- Fără token, canalul este dezactivat, aplicația pornește și nu apare nicio excepție (test).
- Cu un `send` care aruncă eroare sau întârzie, `handle()` nu este blocat (test).
- Același eveniment nu se trimite de două ori pe același canal (test).
- Eroarea de rețea se loghează cel mult o dată la 10 minute.
- Mesajul este în română, conține ora citirii și nu conține tokenul.
- Livrarea reală se testează doar cu acordul utilizatorului și cu propriul token.

## Interfețe
- Variabile noi în `app/config.py`, opționale, implicit oprite: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
- Python: `app/telegram.py::make_telegram_sender(settings) -> Callable[[Subscription, dict], Awaitable[None]]`; punct de extensie în `app/notifier.py`, fără schimbarea semnăturii `Notifier`.
- Endpoint: niciunul în prima versiune. Dacă se cere abonare din interfață, rută nouă, de stabilit.
- Tabele DB: fără tabele noi în prima versiune. Dacă deduplicarea sau abonările se persistă, schemă nouă, versiune de stabilit (pe `main`, `SCHEMA_VERSION` este acum 9).
