# © 2026 Andy217Ace
"""Watchdog for the `tabela` service: checks `/api/health`, restarts the service after
THRESHOLD consecutive failed checks, at most once per RESTART_COOLDOWN_S.

The systemd timer (deploy/tabela-watchdog.timer) starts one short process per minute, so
the failure count and the last restart are kept in a small JSON state file between runs:
`python -m app.watchdog --state FILE --url URL --service tabela`. Only the `tabela`
service is restarted; nginx is left alone (a network fault must not be masked).
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

THRESHOLD = 3  # consecutive failed checks before a restart
RESTART_COOLDOWN_S = 600  # at most one restart per this many seconds
CHECK_TIMEOUT_S = 20.0  # generous: OCR on a busy server can make /api/health slow


class Watchdog:
    """`tick()` runs one check and returns: "ok", "fail", "restart" (on_fail was called)
    or "throttled" (the third failure fell inside the cooldown: nothing done)."""

    def __init__(self, check: Callable[[], bool], on_fail: Callable[[], object],
                 interval_s: float, *, clock: Callable[[], float] = time.time,
                 state: dict | None = None):
        self.check = check
        self.on_fail = on_fail
        self.interval_s = interval_s
        self.clock = clock
        self._failures = 0
        self._last_restart: float | None = None
        if isinstance(state, dict):
            f, lr = state.get("failures"), state.get("last_restart")
            if isinstance(f, int) and not isinstance(f, bool) and f >= 0:
                self._failures = f
            if isinstance(lr, (int, float)) and not isinstance(lr, bool):
                self._last_restart = float(lr)

    def state(self) -> dict:
        return {"failures": self._failures, "last_restart": self._last_restart}

    def tick(self) -> str:
        try:
            ok = bool(self.check())
        except Exception:  # an unreachable or erroring service counts as a failed check
            log.warning("watchdog: check raised", exc_info=True)
            ok = False
        if ok:
            self._failures = 0
            return "ok"
        self._failures += 1
        if self._failures < THRESHOLD:
            return "fail"
        self._failures = 0  # one decision per THRESHOLD failures, restart or not
        now = self.clock()
        if self._last_restart is not None and now - self._last_restart < RESTART_COOLDOWN_S:
            log.error("watchdog: %d failed checks, restart skipped (cooldown)", THRESHOLD)
            return "throttled"
        self._last_restart = now
        log.error("watchdog: %d failed checks, restarting the service", THRESHOLD)
        self.on_fail()
        return "restart"


def health_ok(url: str, timeout_s: float = CHECK_TIMEOUT_S) -> bool:
    """True when `url` answers HTTP 200 with a JSON object (any health content)."""
    import httpx
    r = httpx.get(url, timeout=timeout_s, headers={"Accept": "application/json"})
    return r.status_code == 200 and isinstance(r.json(), dict)


def restart_service(name: str) -> None:
    subprocess.run(["systemctl", "restart", name], check=False, timeout=60)


def _load_state(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None  # missing or corrupt: start clean


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="One watchdog check (run by the systemd timer).")
    p.add_argument("--state", required=True, help="JSON state file between runs")
    p.add_argument("--url", default="http://127.0.0.1:8000/api/health")
    p.add_argument("--service", default="tabela")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    state_path = Path(args.state)
    dog = Watchdog(check=lambda: health_ok(args.url),
                   on_fail=lambda: restart_service(args.service),
                   interval_s=60, state=_load_state(state_path))
    result = dog.tick()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(dog.state()), encoding="utf-8")
    log.info("watchdog: %s", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
