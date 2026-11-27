# Rotația cheii de administrare (ADMIN_TOKEN)

Cheia stă doar în `/etc/tabela.env` (root, chmod 600). Nu o pune în repo, în CHANGELOG, în log sau în interfață.

## Pașii

1. Generează o cheie nouă, de cel puțin 24 de caractere, pe serverul tău:
   `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`
2. Editează `/etc/tabela.env` și setează `ADMIN_TOKEN=<cheia nouă>`.
3. Pentru modul strict, adaugă `ADMIN_TOKEN_STRICT=1` în același fișier (implicit este oprit).
4. Repornește serviciul: `sudo systemctl restart tabela`.
5. Verifică: autentificarea cu cheia veche trebuie refuzată, cea nouă acceptată.

## Efecte

- Toate sesiunile active se invalidează la rotație (cookie-ul este semnat cu cheia veche). Singurul efect pentru tine este reautentificarea.
- Cu `ADMIN_TOKEN_STRICT=1` și o cheie sub 24 de caractere, serviciul nu pornește și afișează un mesaj fără cheie. Corectează `/etc/tabela.env` și repornește.

## Recuperare dacă ai uitat cheia

Te conectezi prin SSH, editezi `/etc/tabela.env` (setezi o cheie nouă sau scoți `ADMIN_TOKEN_STRICT`) și repornești serviciul. Nu există altă cale de recuperare din interfață.

## Autentificare în doi pași (2FA, opțională)

Oprită implicit. Fără `ADMIN_TOTP_SECRET`, autentificarea rămâne doar cu cheia.

**Pornire**
1. Pe server: `python3 scripts/admin_totp_setup.py` (în `/opt/tabela`, cu venv-ul aplicației). Scriptul afișează un secret base32 și un URI `otpauth://`; nu scrie nimic nicăieri.
2. Adaugă secretul în aplicația de autentificare (TOTP, 6 cifre, 30 s, SHA1): introducere manuală, sau un cod QR generat local din URI.
3. Adaugă în `/etc/tabela.env`: `ADMIN_TOTP_SECRET=<secretul>` și repornește: `sudo systemctl restart tabela`.
4. Verifică într-o fereastră nouă, **fără să închizi sesiunea SSH**: `#admin` cere cheia și codul de 6 cifre.

**Efecte**
- Fiecare cod e acceptat o singură dată (±30 s toleranță de ceas). Dacă primești „Cheie sau cod greșit.”, așteaptă codul următor.
- `Authorization: Bearer` e acceptat doar de pe server (`127.0.0.1`), ca la `curl` de mai sus; din afară este refuzat.
- Un secret invalid (nu e base32 sau are sub 16 caractere) dezactivează administrarea (503) până îl corectezi.
- Toate formularele de autentificare (`#admin`, `#ocr`, `#ocr2`, `#infofer`) arată câmpul de cod.

**Oprire / recuperare** (telefon pierdut, ceas desincronizat): prin SSH, șterge linia `ADMIN_TOTP_SECRET` din `/etc/tabela.env` și `sudo systemctl restart tabela`. Pentru un telefon nou, generează un secret nou cu scriptul.

## Setările din pagina Setări

Retenția capturilor (1–30 de zile, implicit 7) și pragul de spațiu liber (MB) se schimbă din pagina Setări. Valorile din mediu (`CAPTURE_RETENTION_DAYS`, `CAPTURE_MIN_FREE_MB`) rămân valorile implicite până se salvează o valoare din interfață.
