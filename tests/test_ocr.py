from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from kindle_to_md.ocr import ocr_image


def test_ocr_extracts_text_from_image(tmp_path):
    """OCR should extract readable text from a simple image."""
    # Create a test image with text
    img = Image.new("RGB", (400, 100), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((10, 30), "Hello World Test", fill="black")
    img_path = tmp_path / "test.png"
    img.save(img_path)

    result = ocr_image(img_path)
    assert "Hello" in result
    assert "World" in result


def test_ocr_returns_empty_for_blank_image(tmp_path):
    """OCR should return empty string for a blank image."""
    img = Image.new("RGB", (400, 100), color="white")
    img_path = tmp_path / "blank.png"
    img.save(img_path)

    result = ocr_image(img_path)
    assert result.strip() == ""
