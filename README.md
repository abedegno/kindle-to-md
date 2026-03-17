# kindle-to-md

Extract Kindle ebooks to Markdown via browser automation.

## Prerequisites

- Python 3.11+
- Tesseract OCR: `brew install tesseract`
- Lightpanda (optional): downloaded automatically, or use `--backend chromium`

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium
```

## Usage

```bash
# First run — will open a browser for Amazon login
kindle-to-md B0G6MF376S

# Specify output and region
kindle-to-md B0G6MF376S -o my-book.md --region com

# Use Chromium instead of Lightpanda
kindle-to-md B0G6MF376S --backend chromium

# Resume interrupted extraction
kindle-to-md B0G6MF376S --resume

# Force re-login
kindle-to-md B0G6MF376S --reauth
```

## How it works

1. Opens a browser for you to log into Amazon (first time only — session is saved)
2. Navigates to the Kindle Cloud Reader for your book
3. Pages through the book, extracting text from the DOM
4. Falls back to OCR (Tesseract) for canvas-rendered or image-based pages
5. Outputs a single Markdown file
