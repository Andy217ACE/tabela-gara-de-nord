# © 2026 Andy217Ace
import os
from pathlib import Path

# Local dev convenience: point pytesseract at the Windows install when present.
_WIN_TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
if "TESSERACT_CMD" not in os.environ and _WIN_TESSERACT.exists():
    os.environ["TESSERACT_CMD"] = str(_WIN_TESSERACT)


import pytest  # noqa: E402


@pytest.fixture
def legacy_rules(monkeypatch):
    """Store rules as before the data-quality validation (Beta 1.02): a delay/platform
    change applies on its first reading, GONE after 2 misses, every return is a new
    'appeared'. For tests of other layers (notifier, history) written against those."""
    from app import quality, store
    for name in ("DELAY_CONFIRM", "DELAY_BIG_CONFIRM", "PLATFORM_CONFIRM",
                 "PLATFORM_CONFUSED_CONFIRM"):
        monkeypatch.setattr(quality, name, 1)
    monkeypatch.setattr(store, "GONE_AFTER_MISSES", 2)
    monkeypatch.setattr(store, "REAPPEAR_QUIET_MIN", -1)
    monkeypatch.setattr(quality, "GHOST_MIN_LIFE_S", -1)  # short test services are not ghosts


@pytest.fixture(autouse=True)
def _fresh_ocr_stats():
    """The in-memory OCR frame statistics are process-wide: every test starts empty."""
    from app.ocr import stats
    stats.reset()
    yield
    stats.reset()


EMPTY_OCR = {"expected_rows": 12, "last": None,
             "window": {"frames": 0, "full_frames": 0, "frames_retried": 0,
                        "lines_retried": 0, "lines_recovered": 0, "duration_ms_max": None,
                        "duration_ms_p50": None, "retry_ms_max": None}}
