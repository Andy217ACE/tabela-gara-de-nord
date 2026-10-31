# Val 4b — Backup, restaurare și export (DRAFT)

> **DRAFT — aprobarea utilizatorului este obligatorie înainte de orice cod.**
> Sub-plan 4b din `docs/superpowers/plans/2026-10-27-backlog-wave.md`, Partea 4. Versiune provizorie: Beta 1.34. Depinde de 4a (pagina Sistem).

**Scop:** Există copii de siguranță ale bazei verificate automat, o restaurare controlată și un export CSV al istoricului, fără date private.

## Ce intră
- Copie online a bazei SQLite (consistentă cu WAL), cu verificare de integritate și păstrarea ultimelor 5 copii. `app/dbbackup.py` există deja pe `main`; de verificat ce acoperă.
- Script de restaurare `scripts/restore_db.py`: rulează doar cu serviciul oprit și face întâi copie de siguranță a stării curente.
- Export CSV al istoricului, filtrat pe interval și tren, cu antet fix și limită de rânduri.

## Ce NU intră
- Restaurarea din interfața web.
- Export JSON și export de capturi sau imagini (redistribuirea imaginilor CFR e exclusă).
- Copii în afara serverului (cloud). Este decizie separată, cu costuri și implicații asupra datelor.

## Decizii deschise pentru utilizator
1. **Backup-ul se poate descărca din admin?** Recomandare: nu. Fișierul conține corecțiile și datele de administrare; rămâne pe server, în `/var/lib/tabela/backups`, și se descarcă manual prin SSH.
2. **Câte copii păstrăm?** Recomandare: 5 locale. Copiile în afara serverului rămân decizie separată.
3. **Ce conține exportul CSV?** Recomandare: data, ora, trenul, stația, întârzierea și peronul. Fără corecții (`+corr`) și fără note de admin.
4. **Interval maxim la export.** Recomandare: 366 zile și maximum 50.000 de rânduri.
5. **Cine poate exporta?** Recomandare: public (datele sunt deja afișate public), cu limită de cereri.
6. **Restaurarea: cine o face?** Recomandare: doar administratorul pe server, cu confirmare dublă.

## Riscuri
- Restaurarea unei copii vechi pierde date noi. Mitigare: copie de siguranță a stării curente înainte.
- Copie coruptă restaurată din greșeală. Mitigare: `verify_backup` înainte de orice atingere a bazei live.
- Export mare blochează serverul cu un singur worker. Mitigare: limită de rânduri și paginare.
- Date private ajung în CSV. Mitigare: test care verifică coloanele.

## Criterii de acceptare
- `verify_backup` respinge un fișier trunchiat sau corupt și nu atinge baza live (test).
- Copia se face online, în timp ce poller-ul scrie, și rezultatul trece `PRAGMA integrity_check` (test).
- Restaurarea unei copii cu schemă mai veche declanșează migrarea, nu eroare (test pe copie locală).
- Restaurarea este refuzată dacă serviciul rulează.
- După al 6-lea backup, rămân exact 5 copii.
- CSV: antet fix; nu conține coloane de corecții sau note; interval mai mare de 366 zile → 422.

## Interfețe
- `GET /api/export/history.csv?from=&to=&train=` (public, cu limită de cereri, zona `tabela_stats`).
- Python: `app/backup_api.py` cu `make_backup(store_path, dest_dir, keep=5) -> Path` și `verify_backup(path) -> bool`; `scripts/restore_db.py` cu `restore(path, db_path) -> None`; `app/export_api.py`.
- Tabele DB: fără tabele noi. Copiile păstrează `user_version`. Dacă se adaugă un jurnal de backup, schemă nouă, versiune de stabilit (pe `main`, `SCHEMA_VERSION` este acum 9).
