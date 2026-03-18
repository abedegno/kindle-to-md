"""OCR engines for extracting text from Kindle page screenshots."""

import base64
import json
import logging
import os
import platform
import re
import urllib.request
import urllib.error
from pathlib import Path

import pytesseract
from PIL import Image

log = logging.getLogger("kindle-to-md")

# Shared VLM prompt
VLM_PROMPT = (
    "Convert this page to clean markdown. Preserve all headings, bold text, "
    "lists, tables, and formatting. Output ONLY the markdown content, "
    "no wrapping code fences."
)

# Global MLX model cache
_mlx_model = None
_mlx_processor = None

# Valid engine choices
ENGINES = ("tesseract", "vlm", "mlx", "ollama")


def ocr_image(image_path: Path, engine: str = "tesseract") -> str:
    """Run OCR on an image file and return text."""
    engine = _resolve_engine(engine)
    if engine == "mlx":
        return _ocr_mlx(str(image_path))
    if engine == "ollama":
        return _ocr_ollama_file(str(image_path))
    img = Image.open(image_path)
    raw = pytesseract.image_to_string(img.convert("L"))
    return _clean_ocr_text(raw)


def ocr_screenshot(screenshot_bytes: bytes, engine: str = "tesseract") -> str:
    """Run OCR on screenshot bytes and return text."""
    engine = _resolve_engine(engine)
    if engine == "mlx":
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(screenshot_bytes)
            f.flush()
            return _ocr_mlx(f.name)
    if engine == "ollama":
        return _ocr_ollama_bytes(screenshot_bytes)
    import io
    img = Image.open(io.BytesIO(screenshot_bytes)).convert("L")
    raw = pytesseract.image_to_string(img)
    return _clean_ocr_text(raw)


# ---------------------------------------------------------------------------
# Engine resolution
# ---------------------------------------------------------------------------

def _resolve_engine(engine: str) -> str:
    """Resolve 'vlm' to a concrete backend, or validate explicit choice."""
    if engine != "vlm":
        return engine
    return _detect_vlm_backend()


def _detect_vlm_backend() -> str:
    """Auto-detect the best available VLM backend.

    Tries MLX first (Apple Silicon), then ollama.
    """
    if _is_apple_silicon():
        try:
            import mlx_vlm  # noqa: F401
            log.info("Auto-detected VLM backend: mlx")
            return "mlx"
        except ImportError:
            pass

    if _is_ollama_available():
        log.info("Auto-detected VLM backend: ollama")
        return "ollama"

    raise RuntimeError(
        "No VLM backend available.\n"
        "  Apple Silicon: pip install -e '.[mlx]'\n"
        "  Any platform:  Install ollama (https://ollama.com) and run:\n"
        "                 ollama pull qwen2.5-vl"
    )


def _is_apple_silicon() -> bool:
    """Check if running on Apple Silicon."""
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def _is_ollama_available() -> bool:
    """Check if ollama is running and has a VLM model."""
    try:
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        req = urllib.request.Request(f"{host}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read())
            models = [m.get("name", "") for m in data.get("models", [])]
            return any("qwen2.5-vl" in m for m in models)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Ollama backend
# ---------------------------------------------------------------------------

def _ocr_ollama_bytes(screenshot_bytes: bytes) -> str:
    """Run OCR via ollama API with image bytes."""
    img_b64 = base64.b64encode(screenshot_bytes).decode("ascii")
    return _ollama_generate(img_b64)


def _ocr_ollama_file(img_path: str) -> str:
    """Run OCR via ollama API with image file path."""
    img_bytes = Path(img_path).read_bytes()
    return _ocr_ollama_bytes(img_bytes)


def _ollama_generate(img_b64: str) -> str:
    """Call ollama /api/generate with a base64 image."""
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    model = os.environ.get("OLLAMA_MODEL", "qwen2.5-vl")

    payload = json.dumps({
        "model": model,
        "prompt": VLM_PROMPT,
        "images": [img_b64],
        "stream": False,
        "options": {"num_predict": 4000},
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{host}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Cannot connect to ollama at {host}. "
            "Is it running? Start with: ollama serve"
        ) from e

    text = result.get("response", "")
    return _strip_code_fences(text)


# ---------------------------------------------------------------------------
# MLX backend (Apple Silicon)
# ---------------------------------------------------------------------------

def _load_qwen_model():
    """Load Qwen2.5-VL model and processor (cached globally)."""
    global _mlx_model, _mlx_processor
    if _mlx_model is not None:
        return _mlx_model, _mlx_processor

    log.info("Loading Qwen2.5-VL model via mlx-vlm...")

    from transformers import AutoTokenizer, AutoImageProcessor, processing_utils
    from transformers.models.qwen2_5_vl.processing_qwen2_5_vl import Qwen2_5_VLProcessor
    from mlx_vlm.utils import load_tokenizer, load_model, StoppingCriteria
    from huggingface_hub import snapshot_download

    # Patch video processor validation (not needed for image-only use)
    orig_check = processing_utils.ProcessorMixin.check_argument_for_proper_class

    def lenient_check(self, attr, arg):
        if "video" in attr.lower():
            return
        return orig_check(self, attr, arg)

    processing_utils.ProcessorMixin.check_argument_for_proper_class = lenient_check

    model_id = "mlx-community/Qwen2.5-VL-7B-Instruct-4bit"
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    image_processor = AutoImageProcessor.from_pretrained(model_id, use_fast=False)

    class DummyVP:
        pass

    processor = Qwen2_5_VLProcessor(
        image_processor=image_processor,
        tokenizer=tokenizer,
        video_processor=DummyVP(),
    )

    model_path = Path(snapshot_download(model_id))
    detokenizer_class = load_tokenizer(model_path, return_tokenizer=False)
    processor.detokenizer = detokenizer_class(processor.tokenizer)
    eos_ids = getattr(processor.tokenizer, "eos_token_ids", None) or [
        processor.tokenizer.eos_token_id
    ]
    processor.tokenizer.stopping_criteria = StoppingCriteria(
        eos_ids, processor.tokenizer
    )

    _mlx_model = load_model(model_path)
    _mlx_processor = processor
    log.info("Qwen2.5-VL model loaded.")
    return _mlx_model, _mlx_processor


def _ocr_mlx(img_path: str) -> str:
    """Run OCR via Qwen2.5-VL on MLX. Takes a file path."""
    from mlx_vlm import generate

    model, processor = _load_qwen_model()

    prompt = (
        "<|im_start|>system\nYou are a document OCR assistant. "
        "Output clean markdown only, no commentary.<|im_end|>\n"
        "<|im_start|>user\n<|vision_start|><|image_pad|><|vision_end|>"
        f"{VLM_PROMPT}<|im_end|>\n"
        "<|im_start|>assistant\n"
    )

    result = generate(
        model, processor, prompt, image=img_path, max_tokens=4000, verbose=False
    )

    return _strip_code_fences(result.text)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences that VLMs sometimes wrap output in."""
    for prefix in ("```markdown\n", "```\n"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    for suffix in ("\n```", "```"):
        if text.endswith(suffix):
            text = text[:-len(suffix)]
    return text.strip()


def _clean_ocr_text(text: str) -> str:
    """Strip common OCR artefacts from Tesseract output."""
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if len(stripped) <= 1 and not stripped.isalnum():
            continue
        cleaned.append(line)
    result = "\n".join(cleaned)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()
