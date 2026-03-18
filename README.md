# kindle-to-md

Extract Kindle ebooks to clean Markdown via browser automation and OCR.

## Features

- **Browser automation** via Playwright (Chromium) — navigates Kindle Cloud Reader
- **Two OCR backends** — Tesseract (CPU, fast) and Qwen2.5-VL (Apple Silicon via MLX, structured markdown)
- **Session persistence** — log in once, extract many books
- **Resume support** — interrupt and continue later
- **Per-book projects** — each book gets its own folder with screenshots and output

## Requirements

- Python 3.11+
- An Amazon Kindle Cloud Reader account
- Tesseract OCR (for default mode): `brew install tesseract` / `apt install tesseract-ocr`

## Installation

### Basic (Tesseract OCR)

```bash
pip install -e .
playwright install chromium
```

### Apple Silicon (Qwen2.5-VL via MLX)

```bash
pip install -e ".[mlx]"
playwright install chromium
```

## Quick Start

### 1. Login to Amazon

```bash
kindle-to-md --login --region co.uk
```

### 2. Extract a book

```bash
kindle-to-md B0G6MF376S --headed
```

### 3. Re-process with better OCR (Apple Silicon)

```bash
kindle-to-md B0G6MF376S --reprocess --ocr mlx
```

## Usage

```
kindle-to-md [ASIN] [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `ASIN` | — | Amazon book ID or full Kindle URL |
| `-o, --output` | `projects/{ASIN}/book.md` | Output file path |
| `--region` | `co.uk` | Amazon region (co.uk, com, de, etc.) |
| `--ocr` | `tesseract` | OCR engine: `tesseract`, `vlm`, `mlx`, `ollama` |
| `--login` | — | Open browser for Amazon login, then exit |
| `--reprocess` | — | Re-run OCR on cached screenshots |
| `--resume` | — | Resume interrupted extraction |
| `--headed` | — | Show browser window |
| `--reauth` | — | Force fresh login |
| `--delay` | `1.0` | Seconds between page turns |
| `-v, --verbose` | — | Debug logging |

### Project Structure

Each book creates a project folder:

```
projects/
  B0G6MF376S/
    images/       # page screenshots (cached for re-processing)
    book.md       # extracted markdown output
```

## OCR Backends

| Backend | Flag | Speed | Quality | Platform |
|---------|------|-------|---------|----------|
| Tesseract | `--ocr tesseract` | ~0.6s/page | Plain text | Any |
| VLM (auto) | `--ocr vlm` | ~11s/page | Structured markdown | Any (see below) |
| MLX | `--ocr mlx` | ~11s/page | Structured markdown | Apple Silicon only |
| Ollama | `--ocr ollama` | ~15s/page | Structured markdown | Any |

### Tesseract (default)

Fast, works everywhere, plain text output. Good for books with simple formatting.

### VLM — Vision Language Model (recommended)

`--ocr vlm` auto-detects the best available VLM backend:
- **Apple Silicon** → MLX (fastest, runs on M-series GPU)
- **Any platform** → Ollama (requires ollama to be running)

Both use Qwen2.5-VL to produce structured Markdown with proper headings, bold text, code formatting, and tables.

### Setup: MLX (Apple Silicon)

```bash
pip install -e ".[mlx]"
```

### Setup: Ollama (any platform)

1. Install ollama: https://ollama.com
2. Pull the model: `ollama pull qwen2.5-vl`
3. Start the server: `ollama serve`

You can configure the ollama endpoint via `OLLAMA_HOST` (default: `http://localhost:11434`) and model via `OLLAMA_MODEL` (default: `qwen2.5-vl`).

## Post-Processing

The raw OCR output may need format-specific cleanup depending on your book. See `examples/` for post-processing scripts you can adapt:

- `examples/postprocess_quiz.py` — normalises quiz/exam books (questions, answers, answer keys)

## How It Works

1. Opens Kindle Cloud Reader in a Playwright-controlled Chromium browser
2. Navigates to page 1, switches to single-column layout
3. Screenshots each page, advances with arrow keys
4. Detects end-of-book via content change detection
5. Runs OCR on each screenshot (Tesseract or Qwen2.5-VL)
6. Outputs clean Markdown with page markers for resume support

## License

MIT
