from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image, ImageDraw
from kindle_to_md.ocr import (
    ocr_image, _resolve_engine, _detect_vlm_backend,
    _is_apple_silicon, _is_ollama_available, _strip_code_fences,
)


def test_ocr_extracts_text_from_image(tmp_path):
    """OCR should extract readable text from a simple image."""
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


def test_resolve_engine_passthrough():
    """Explicit engines should pass through unchanged."""
    assert _resolve_engine("tesseract") == "tesseract"
    assert _resolve_engine("mlx") == "mlx"
    assert _resolve_engine("ollama") == "ollama"


@patch("kindle_to_md.ocr._is_apple_silicon", return_value=True)
@patch("kindle_to_md.ocr._is_ollama_available", return_value=False)
def test_detect_vlm_prefers_mlx_on_apple_silicon(mock_ollama, mock_apple):
    """VLM auto-detect should prefer MLX on Apple Silicon."""
    # Only works if mlx_vlm is importable (skip otherwise)
    try:
        import mlx_vlm  # noqa: F401
        assert _detect_vlm_backend() == "mlx"
    except ImportError:
        pass


@patch("kindle_to_md.ocr._is_apple_silicon", return_value=False)
@patch("kindle_to_md.ocr._is_ollama_available", return_value=True)
def test_detect_vlm_falls_back_to_ollama(mock_ollama, mock_apple):
    """VLM auto-detect should use ollama when not on Apple Silicon."""
    assert _detect_vlm_backend() == "ollama"


@patch("kindle_to_md.ocr._is_apple_silicon", return_value=False)
@patch("kindle_to_md.ocr._is_ollama_available", return_value=False)
def test_detect_vlm_raises_when_nothing_available(mock_ollama, mock_apple):
    """VLM auto-detect should raise when no backend is available."""
    import pytest
    with pytest.raises(RuntimeError, match="No VLM backend available"):
        _detect_vlm_backend()


def test_strip_code_fences():
    """Should strip markdown code fences from VLM output."""
    assert _strip_code_fences("```markdown\n# Hello\n```") == "# Hello"
    assert _strip_code_fences("```\nfoo\n```") == "foo"
    assert _strip_code_fences("no fences here") == "no fences here"
