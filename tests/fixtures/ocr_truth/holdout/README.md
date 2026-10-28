# Hold-out orb pentru peron (21-27.10, cadre nevazute)

- Cadre: 21 capturi reale de pe server (Beta 1.31, citire read-only din /var/lib/tabela/captures), zilele 22-27.10.2026,
  fiecare la >= 60 min de orice cadru din truth.json / fixture-urile locale. Orele din numele fisierelor (UTC): 03:00-22:23,
  adica dimineata, amiaza, seara si noapte. Alegerea s-a facut doar privind imaginile (montaje), niciodata rulind cititorul.
- Etichetare: oarba, de un etichetator distinct de implementatori; toate cele 24 de randuri, toate campurile, privind imaginea
  (crop-uri marite 1.45x). `?` = necitibil (sticla), `null` = celula goala. Nu s-au consultat iesirea OCR, baza de date sau
  etichetele altor zile. Cheile: `ocr_truth/holdout/<nume>` (cale sub tests/fixtures, fara .jpg).
- Continut (celule de peron vizibile, ambele table): 168 (cifra: 1x11, 2x11, 3x17, 4x14, 5x12, 6x11, 7x23, 8x14, 9x18;
  doua cifre 10x11, 11x7, 12x6, 13x10, 14x3). Peron 0 nu exista pe tabela (apare doar in 10). 11 cadre cu sticla/reflexii.
- Initial 28.10 a fost refuzat: la verificare existau doar capturi 00:00-02:03, tabela statica (vezi holdout-report.md).
- Scor: `scoring` cu un script extern (nu e in repo); cadrele se citesc cu IMG_ROOT=tests/fixtures.
