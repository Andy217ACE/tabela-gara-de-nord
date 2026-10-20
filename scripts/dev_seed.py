# © 2026 Andy217Ace
"""Dev helper: fill a SQLite DB with a real board read from the test fixture.

    python scripts/dev_seed.py dev.db                # OCR tests/fixtures/board_1.jpg, ingest now
    python scripts/dev_seed.py dev.db --age 600      # pretend the reading is 10 min old (stale UI)
    python scripts/dev_seed.py dev.db --bump 7       # re-ingest with +7 min on the first arrival

Then serve it without the poller:
    DB_PATH=dev.db POLLER_ENABLED=0 uvicorn app.main:create --factory
"""
from __future__ import annotations

import argparse
import dataclasses
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import tests.conftest  # noqa: E402,F401  (points pytesseract at the Windows install)
from app.ocr.reader import read_board  # noqa: E402
from app.store import TZ, Store  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db", help="SQLite file to create/update")
    ap.add_argument("--image", default=str(ROOT / "tests" / "fixtures" / "board_1.jpg"))
    ap.add_argument("--age", type=float, default=0.0, help="reading age in seconds")
    ap.add_argument("--bump", type=int, default=0, help="extra delay minutes on the first arrival")
    args = ap.parse_args()

    rows = read_board(Path(args.image).read_bytes())
    if args.bump:
        for i, r in enumerate(rows):
            if r.board == "arrival":
                rows[i] = dataclasses.replace(r, delay_min=r.delay_min + args.bump)
                break
    store = Store(args.db)
    store.migrate()
    when = datetime.now(TZ) - timedelta(seconds=args.age)
    events = store.ingest(rows, when, "dev-seed")
    b = store.current_board()
    store.close()
    print(f"{len(rows)} rows read, {len(events)} events; board: "
          f"{len(b['arrivals'])} arrivals, {len(b['departures'])} departures")


if __name__ == "__main__":
    main()
