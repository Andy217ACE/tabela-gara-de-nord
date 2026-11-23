# Contribuții / Contributing

## Română
- Teste: `pip install -r requirements-dev.txt -c requirements.lock`, apoi `python -m pytest -q` (testele de browser cer `python -m playwright install chromium`; fără el se omit). Verificare de release: `python scripts/check_release.py`.
- Release: `VERSION` (`Beta 1.NN`), secțiune nouă sus în `CHANGELOG.md` (română + `### English`) și `CHARTS_V` din `web/ui2.js` = `1.NN`. Fiecare deploy crește NN cu 1.
- Frontend: CSP strict (fără stiluri/scripturi inline, fără `innerHTML`); tot textul prin i18n, cu aceleași chei în `web/i18n/ro.json` și `en.json`.
- Flux: branch din `main`, PR cu CI verde, completează lista din șablonul de PR.
- Dependențe: `requirements.txt` are versiuni fixe, iar `requirements.lock` e generat din el cu `uv pip compile requirements.txt --python-version 3.14 --python-platform x86_64-unknown-linux-gnu -o requirements.lock` (comanda e în antetul fișierului). Dependabot (pip) poate actualiza doar `requirements.txt`: workflow-ul `.github/workflows/lock.yml` regenerează automat lock-ul pe PR-urile Dependabot și îl împinge pe ramura PR-ului (apoi relansează CI). Lock-ul nu se editează de mână. `opencv-python-headless` și `numpy` nu se actualizează automat la minor/major (`.github/dependabot.yml`): ele schimbă rezultatul OCR și se actualizează manual, cu re-măsurare (`docs/ocr.md`).
- fail2ban: filtrele din `deploy/fail2ban/` sunt validate în CI (job-ul `fail2ban`) cu `fail2ban-regex` pe `tests/fixtures/fail2ban/`; o regulă nouă cere linii noi în `should_match*.log` și în `should_not_match.log`.

## English
- Tests: `pip install -r requirements-dev.txt -c requirements.lock`, then `python -m pytest -q` (browser tests need `python -m playwright install chromium`, otherwise they skip). Release check: `python scripts/check_release.py`.
- Releases: `VERSION` (`Beta 1.NN`), a new top section in `CHANGELOG.md` (Romanian + `### English`) and `CHARTS_V` in `web/ui2.js` = `1.NN`. Every deploy bumps NN by 1.
- Frontend: strict CSP (no inline styles/scripts, no `innerHTML`); all text through i18n, identical keys in `web/i18n/ro.json` and `en.json`.
- Flow: branch from `main`, PR with green CI, fill in the PR template checklist.
- Dependencies: `requirements.txt` has pinned versions and `requirements.lock` is generated from it with `uv pip compile requirements.txt --python-version 3.14 --python-platform x86_64-unknown-linux-gnu -o requirements.lock` (the command is in the file header). Dependabot (pip) can only update `requirements.txt`: the `.github/workflows/lock.yml` workflow regenerates the lock on Dependabot PRs and pushes it to the PR branch (then re-runs CI). Never edit the lock by hand. `opencv-python-headless` and `numpy` are not auto-updated for minor/major (`.github/dependabot.yml`): they change the OCR result and are updated by hand, with a re-measurement (`docs/ocr.md`).
- fail2ban: the filters in `deploy/fail2ban/` are validated in CI (the `fail2ban` job) with `fail2ban-regex` against `tests/fixtures/fail2ban/`; a new rule needs new lines in `should_match*.log` and in `should_not_match.log`.
