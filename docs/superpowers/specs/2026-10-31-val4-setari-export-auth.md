# Val 4c — Autentificare admin cu cheie puternică și setări (DRAFT)

> **DRAFT — aprobarea utilizatorului este obligatorie înainte de orice cod.**
> Sub-plan 4c din `docs/superpowers/plans/2026-10-27-backlog-wave.md`, Partea 4. Versiune provizorie: Beta 1.35. Depinde de 4a.

**Scop:** Cheia de administrare devine suficient de lungă și poate fi schimbată fără să rămână sesiuni vechi active, iar retenția și pragurile se modifică dintr-o pagină Setări, nu din fișierul de mediu.

## Ce intră
- Mod strict pentru cheia de admin: minimum 24 de caractere, activat prin `ADMIN_TOKEN_STRICT=1` (implicit oprit).
- Rotația cheii invalidează sesiunile care au cookie-ul semnat cu cheia veche.
- Pagina Setări (`GET/POST /api/admin/settings`) pentru retenția capturilor și pragurile de alertă, cu validare de interval și jurnal de audit.
- Documentație pas cu pas pentru rotația cheii.

## Ce NU intră
- Conturi multiple de administrator sau de utilizator (planul de acces rămâne separat, doar plan).
- Autentificare în doi pași.
- Schimbarea cheii din interfață. Cheia rămâne în `/etc/tabela.env`.

## Decizii deschise pentru utilizator
1. **Unde stă cheia?** Recomandare: în `/etc/tabela.env`, niciodată în interfață și niciodată în repo, log sau CHANGELOG.
2. **Ce se mută din mediu în Setări?** Recomandare: doar retenția capturilor și pragurile de alertă. Porturi, tokenuri și căi rămân în mediu.
3. **Când devine modul strict obligatoriu?** Recomandare: nu automat. Îl activezi tu după ce ți-ai ales cheia.
4. **Lungimea minimă a cheii.** Recomandare: 24 de caractere.
5. **Ce se întâmplă cu sesiunile active la rotație?** Recomandare: toate se invalidează. Singurul efect pentru tine este reautentificarea.
6. **Interval pentru retenția capturilor.** Recomandare: 1–30 de zile, implicit 7.

## Riscuri
- Te blochezi afară dacă uiți cheia. Mitigare: procedură documentată de recuperare prin SSH (editezi `/etc/tabela.env` și repornești serviciul).
- O setare invalidă oprește poller-ul. Mitigare: validare la intrare și valori implicite sigure.
- Cheia scurtă rămâne activă după activarea modului strict. Mitigare: serviciul refuză pornirea și afișează un mesaj clar.

## Criterii de acceptare
- Cu `ADMIN_TOKEN_STRICT=1` și cheie sub 24 de caractere, serviciul refuză pornirea cu mesaj clar (test).
- După rotația cheii, un cookie vechi este refuzat (test).
- `POST /api/admin/settings` cu valoare în afara intervalului returnează 422 și nu modifică nimic (test).
- Cererea fără token CSRF valid este refuzată (test).
- Fiecare schimbare de setare apare în jurnalul de audit cu cine, când și ce, fără valori secrete.
- Cheia nu apare în repo, CHANGELOG sau log (test de căutare în fișiere).

## Interfețe
- `GET /api/admin/settings`, `POST /api/admin/settings` (sub `require_admin`).
- Variabilă nouă `ADMIN_TOKEN_STRICT` în `app/config.py`, cu valoare implicită 0.
- Python: `app/admin.py` (`admin_token()`, `make_session`, `check_session`), fără schimbarea formatului cookie-ului.
- Tabele DB: tabel de setări (cheie-valoare) și tabel de audit. Dacă tabelul de audit din planul 1.29 nu există pe `main`, schemă nouă, versiune de stabilit (pe `main`, `SCHEMA_VERSION` este acum 9).
