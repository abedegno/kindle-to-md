"""OCR engines for extracting text from Kindle page screenshots."""

import logging
import re
from pathlib import Path

import pytesseract
from PIL import Image

log = logging.getLogger("kindle-to-md")

# Global MLX model cache
_mlx_model = None
_mlx_processor = None


def ocr_image(image_path: Path, engine: str = "tesseract") -> str:
    """Run OCR on an image file and return text."""
    if engine == "mlx":
        return _ocr_mlx(str(image_path))
    img = Image.open(image_path)
    raw = pytesseract.image_to_string(img.convert("L"))
    return _clean_ocr_text(raw)


def ocr_screenshot(screenshot_bytes: bytes, engine: str = "tesseract") -> str:
    """Run OCR on screenshot bytes and return text."""
    if engine == "mlx":
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(screenshot_bytes)
            f.flush()
            return _ocr_mlx(f.name)
    import io
    img = Image.open(io.BytesIO(screenshot_bytes)).convert("L")
    raw = pytesseract.image_to_string(img)
    return _clean_ocr_text(raw)


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
        "Convert this page to clean markdown. Preserve all headings, bold text, "
        "lists, tables, and formatting. Output ONLY the markdown content, "
        "no wrapping code fences.<|im_end|>\n"
        "<|im_start|>assistant\n"
    )

    result = generate(
        model, processor, prompt, image=img_path, max_tokens=4000, verbose=False
    )

    text = result.text
    for prefix in ("```markdown\n", "```\n"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    for suffix in ("\n```", "```"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
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
