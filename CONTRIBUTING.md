# Contribuții / Contributing

## Română
- Teste: `pip install -r requirements-dev.txt -c requirements.lock`, apoi `python -m pytest -q` (testele de browser cer `python -m playwright install chromium`; fără el se omit). Verificare de release: `python scripts/check_release.py`.
- Release: `VERSION` (`Beta 1.NN`), secțiune nouă sus în `CHANGELOG.md` (română + `### English`) și `CHARTS_V` din `web/ui2.js` = `1.NN`. Fiecare deploy crește NN cu 1.
- Frontend: CSP strict (fără stiluri/scripturi inline, fără `innerHTML`); tot textul prin i18n, cu aceleași chei în `web/i18n/ro.json` și `en.json`.
- Flux: branch din `main`, PR cu CI verde, completează lista din șablonul de PR.

## English
- Tests: `pip install -r requirements-dev.txt -c requirements.lock`, then `python -m pytest -q` (browser tests need `python -m playwright install chromium`, otherwise they skip). Release check: `python scripts/check_release.py`.
- Releases: `VERSION` (`Beta 1.NN`), a new top section in `CHANGELOG.md` (Romanian + `### English`) and `CHARTS_V` in `web/ui2.js` = `1.NN`. Every deploy bumps NN by 1.
- Frontend: strict CSP (no inline styles/scripts, no `innerHTML`); all text through i18n, identical keys in `web/i18n/ro.json` and `en.json`.
- Flow: branch from `main`, PR with green CI, fill in the PR template checklist.
