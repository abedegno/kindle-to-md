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
| `--ocr` | `tesseract` | OCR engine: `tesseract` or `mlx` |
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

### Tesseract (default)

Fast (~0.6s/page), works everywhere, plain text output. Good for books with simple formatting.

### Qwen2.5-VL via MLX (Apple Silicon only)

Slower (~11s/page) but produces structured Markdown with proper headings, bold text, code formatting, and tables. Runs natively on M-series GPU via MLX.

**Note:** This backend requires an Apple Silicon Mac (M1/M2/M3/M4). For other platforms, use `--ocr tesseract`.

Requires: `pip install -e ".[mlx]"`

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
