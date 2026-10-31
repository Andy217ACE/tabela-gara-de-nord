# Val 4a — Stare sistem și watchdog (DRAFT)

> **DRAFT — aprobarea utilizatorului este obligatorie înainte de orice cod.**
> Sub-plan 4a din `docs/superpowers/plans/2026-10-27-backlog-wave.md`, Partea 4. Versiune provizorie: Beta 1.33 (se ia următoarea liberă după `git fetch`).

**Scop:** Pagina „Sistem” arată clar dacă panoul e viu, când a fost ultima citire reușită și ce spațiu are serverul, iar un watchdog repornește serviciul când nu mai răspunde.

## Ce intră
- Pagina `#sistem`: versiune, ultima citire reușită, stare LIVE / date vechi / necunoscut, rata de rânduri necitite în ultima oră (cu N), spațiu liber pe disc, mărimea bazei.
- Secțiune detaliată în admin (aceleași date, plus ultima eroare scurtă).
- Watchdog: un timer systemd verifică `/api/health`; după 3 eșecuri consecutive repornește serviciul `tabela`.

## Ce NU intră
- Alerte către utilizator (sunt în 4d).
- Monitorizare externă sau grafice de performanță.
- Repornirea serverului sau a nginx.

## Decizii deschise pentru utilizator
1. **Cine vede pagina Sistem?** Recomandare: public, cu câmpuri minime (versiune, ultima citire, stare LIVE/vechi); detaliile doar în admin.
2. **Când e considerat blocat panoul?** Recomandare: fără citire reușită de 10 minute (se afișează „date vechi”).
3. **Ce repornește watchdog-ul?** Recomandare: doar serviciul `tabela`. Nginx rămâne manual, ca să nu mascheze o problemă de rețea.
4. **Pragul watchdog-ului.** Recomandare: 3 verificări eșuate la rând, la 1 minut.
5. **Limita de repornire.** Recomandare: cel mult o repornire la 10 minute, ca să nu intre în buclă.

## Riscuri
- Repornirea în mijlocul unui ciclu OCR poate pierde o citire. Se acceptă și se loghează.
- Fals pozitiv dacă serverul e lent (Tesseract poate dura). Mitigare: timeout generos pe verificare.
- Indicatorul de OCR poate părea „sănătos” cu puține date. Mitigare: afișăm N și „date insuficiente” sub un prag.

## Criterii de acceptare
- `/api/system` nu conține căi de fișiere, tokenuri sau variabile de mediu (test automat). Eroarea afișată este un cod scurt, fără traceback.
- Când ultima citire e mai veche decât pragul, pagina afișează „Date vechi”, nu „LIVE”.
- Valoarea lipsă se afișează „necunoscut”, nu 0.
- Watchdog: 3 eșecuri consecutive produc exact o acțiune de repornire; un răspuns valid resetează contorul; maximum o repornire la 10 minute (test cu ceas fals).
- Pagina `#sistem` respectă footerul exact și CSP, și e testată în Playwright la 390 px, fără scroll orizontal.
- `deploy/update.sh` instalează timerul fără să modifice celelalte unit-uri.

## Interfețe
- `GET /api/system` (public): `version`, `schema`, `uptime_s`, `poller{last_ok_age_s,last_error}`, `ocr{unread_rate_1h,n}`, `disk{free_gb}`, `db{size_mb,wal_mb}`.
- `GET /api/admin/system` (sub `require_admin`): același set, plus detalii.
- Python: `app/system_status.py::collect_status(store, settings, now) -> dict`; `app/watchdog.py::Watchdog(check, on_fail, interval_s)`.
- Fișiere noi: `deploy/tabela-watchdog.service`, `deploy/tabela-watchdog.timer`.
- Tabele DB: fără tabele noi în această variantă. Schema rămâne neschimbată.
