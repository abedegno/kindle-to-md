"""OCR fallback for canvas-rendered or image-based Kindle pages."""

import re
from pathlib import Path

import pytesseract
from PIL import Image


def ocr_image(image_path: Path) -> str:
    """Run Tesseract OCR on an image and return cleaned text."""
    img = Image.open(image_path)
    raw = pytesseract.image_to_string(img)
    return _clean_ocr_text(raw)


def ocr_screenshot(screenshot_bytes: bytes) -> str:
    """Run Tesseract OCR on screenshot bytes and return cleaned text."""
    import io
    img = Image.open(io.BytesIO(screenshot_bytes))
    raw = pytesseract.image_to_string(img)
    return _clean_ocr_text(raw)


def _clean_ocr_text(text: str) -> str:
    """Strip common OCR artefacts."""
    # Remove stray single characters on their own lines
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if len(stripped) <= 1 and not stripped.isalnum():
            continue
        cleaned.append(line)
    result = "\n".join(cleaned)
    # Collapse excessive whitespace
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()
