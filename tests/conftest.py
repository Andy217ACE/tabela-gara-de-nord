# © 2026 Andy217Ace
import os
from pathlib import Path

# Local dev convenience: point pytesseract at the Windows install when present.
_WIN_TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
if "TESSERACT_CMD" not in os.environ and _WIN_TESSERACT.exists():
    os.environ["TESSERACT_CMD"] = str(_WIN_TESSERACT)
