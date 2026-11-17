# Val 4 — modificări de integrare pentru controller

Nicio schimbare de schemă. Fișiere interzise fluxului, deci aplicate doar de controller.

## 1. `app/api.py`, ruta `/api/export/history.csv` (Review Focus 3): lipsește BOM-ul UTF-8
Fără BOM, Excel deschide diacriticele greșit. În răspunsul existent:
```python
return Response(content=text.encode("utf-8"), media_type="text/csv; charset=utf-8", ...)
```
se schimbă în:
```python
return Response(content=("﻿" + text).encode("utf-8"), media_type="text/csv; charset=utf-8", ...)
```
Verifică `tests/test_export.py` / `tests/test_api.py` dacă compară începutul corpului (antetul). Ghilimelele pentru stații cu virgulă sunt deja corecte (modulul `csv`).

## 2. Opțional: folosirea fațadelor
Nu e necesar; `api.py` / `admin.py` pot rămâne pe `app.telegram`, `app.restore`, `app.admin_settings`. Fațadele `app.alerts`, `app.backup_restore`, `app.settings` sunt noi, neinclude nicăieri.

## 3. Nimic pentru deploy
`deploy/tabela-watchdog.{service,timer,sudoers}` și instalarea lor în `deploy/update.sh` există deja.
