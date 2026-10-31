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

## Setările din pagina Setări

Retenția capturilor (1–30 de zile, implicit 7) și pragul de spațiu liber (MB) se schimbă din pagina Setări. Valorile din mediu (`CAPTURE_RETENTION_DAYS`, `CAPTURE_MIN_FREE_MB`) rămân valorile implicite până se salvează o valoare din interfață.
