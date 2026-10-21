# © 2026 Andy217Ace
"""Rejected frames: the board images a panel (or the whole frame) was rejected for.

Kept for diagnosing OCR misreads (partial reads, unreadable panels). Only the
last REJECTED_KEEP frames stay; each is the image as fetched plus a small JSON
with the reasons. Never raises: a failure is logged and the poller carries on.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger(__name__)

REJECTED_KEEP = 40
DEFAULT_DIR = "/var/lib/tabela/rejected"


def _ensure_dir(path: str) -> bool:
    """Create `path` (0750) if missing; refuse a symlink or a non-directory."""
    if os.path.islink(path):
        log.warning("rejected frames: %s is a symlink; not saving", path)
        return False
    os.makedirs(path, mode=0o750, exist_ok=True)
    if not os.path.isdir(path) or os.path.islink(path):
        log.warning("rejected frames: %s is not a directory; not saving", path)
        return False
    return True


def _write(path: str, data: bytes) -> None:
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def prune(path: str, keep: int = REJECTED_KEEP) -> None:
    frames = sorted(n for n in os.listdir(path) if n.endswith(".jpg"))
    for name in frames[:max(0, len(frames) - keep)]:
        for victim in (name, name[:-4] + ".json"):
            try:
                os.remove(os.path.join(path, victim))
            except FileNotFoundError:
                pass


def save_rejected(path: str | None, data: bytes, ts: float, reasons: dict[str, str],
                  keep: int = REJECTED_KEEP) -> str | None:
    """Save one rejected frame; returns the image path (None: disabled or failed)."""
    if not path:
        return None
    try:
        if not _ensure_dir(path):
            return None
        when = datetime.fromtimestamp(ts, timezone.utc)
        stem = when.strftime("%Y%m%dT%H%M%S") + f"{int(ts * 1000) % 1000:03d}Z"
        img = os.path.join(path, stem + ".jpg")
        _write(img, data)
        meta = {"ts": when.isoformat(), "reasons": reasons}
        _write(os.path.join(path, stem + ".json"),
               json.dumps(meta, ensure_ascii=False).encode("utf-8"))
        prune(path, keep)
        log.warning("frame rejected (%s); saved %s",
                    "; ".join(f"{b}: {why}" for b, why in sorted(reasons.items())), img)
        return img
    except OSError:
        log.warning("could not save rejected frame", exc_info=True)
        return None
