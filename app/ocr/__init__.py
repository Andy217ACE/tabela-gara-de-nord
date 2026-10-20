# © 2026 Andy217Ace
"""Classical OCR (OpenCV + Tesseract) for the Gara de Nord departures/arrivals board."""
from app.ocr.reader import OcrError, read_board

__all__ = ["OcrError", "read_board"]
