# © 2026 Andy217Ace
"""Dev helper: fill a SQLite DB with a real board read from the test fixture.

    python scripts/dev_seed.py dev.db                # OCR tests/fixtures/board_1.jpg, ingest now
    python scripts/dev_seed.py dev.db --age 600      # pretend the reading is 10 min old (stale UI)
    python scripts/dev_seed.py dev.db --bump 7       # re-ingest with +7 min on the first arrival
    python scripts/dev_seed.py dev.db --capture-dir data/captures   # also record an OCR capture

The real captures are not in the public repo. Without tests/fixtures/board_1.jpg (and no
--image) the rows come from the golden tests/fixtures/board_1.json instead of OCR;
--capture-dir still needs the image.

Then serve it without the poller:
    DB_PATH=dev.db POLLER_ENABLED=0 uvicorn app.main:create --factory
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Local dev convenience: point pytesseract at the Windows install when present.
_WIN_TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
if "TESSERACT_CMD" not in os.environ and _WIN_TESSERACT.exists():
    os.environ["TESSERACT_CMD"] = str(_WIN_TESSERACT)

from app.models import Row  # noqa: E402
from app.ocr.reader import read_board_debug  # noqa: E402
from app.store import TZ, Store  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
DEFAULT_IMAGE = FIXTURES / "board_1.jpg"
GOLDEN = FIXTURES / "board_1.json"


def golden_rows(path: Path = GOLDEN) -> list[Row]:
    """The expected rows of board_1.jpg (what a correct OCR reads), as Row objects."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Row(board=b, **d) for b in ("arrival", "departure") for d in data[b]]


def _has_rows(db: str) -> bool:
    """True if `db` is an existing database that already holds runs or services."""
    if not Path(db).exists():
        return False
    con = sqlite3.connect(db)
    try:
        for table in ("runs", "services"):
            try:
                if con.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
                    return True
            except sqlite3.OperationalError:
                pass  # table missing: empty/unmigrated database
        return False
    finally:
        con.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db", help="SQLite file to create/update")
    ap.add_argument("--image", default=None,
                    help=f"board photo to OCR (default {DEFAULT_IMAGE.name}; "
                         f"if it is missing, the rows of {GOLDEN.name})")
    ap.add_argument("--age", type=float, default=0.0, help="reading age in seconds")
    ap.add_argument("--bump", type=int, default=0, help="extra delay minutes on the first arrival")
    ap.add_argument("--force", action="store_true",
                    help="seed even if the database already has rows")
    ap.add_argument("--capture-dir", default=None,
                    help="also record the image + OCR observations (Capturi OCR) under this dir")
    args = ap.parse_args()

    if not args.force and _has_rows(args.db):
        sys.exit(f"{args.db} already has data; refusing to seed it (use --force to override)")

    if args.image is None and not DEFAULT_IMAGE.is_file():
        if args.capture_dir:
            sys.exit(f"--capture-dir needs a board photo: {DEFAULT_IMAGE} is missing "
                     "(real captures are not in the repo); pass --image")
        image, debug = None, None
        rows = golden_rows()
        print(f"{DEFAULT_IMAGE.name} missing: seeding the golden rows of {GOLDEN.name}")
    else:
        image = Path(args.image or DEFAULT_IMAGE).read_bytes()
        rows, debug = read_board_debug(image)
    if args.bump:
        for i, r in enumerate(rows):
            if r.board == "arrival":
                rows[i] = dataclasses.replace(r, delay_min=r.delay_min + args.bump)
                break
    store = Store(args.db)
    store.migrate()
    when = datetime.now(TZ) - timedelta(seconds=args.age)
    events = store.ingest(rows, when, "dev-seed")
    if args.capture_dir:
        from app.observations import record_capture
        cid = record_capture(store, image, rows, debug, when, capture_dir=args.capture_dir)
        print(f"capture #{cid} recorded under {args.capture_dir}")
    b = store.current_board()
    store.close()
    print(f"{len(rows)} rows read, {len(events)} events; board: "
          f"{len(b['arrivals'])} arrivals, {len(b['departures'])} departures")


if __name__ == "__main__":
    main()
