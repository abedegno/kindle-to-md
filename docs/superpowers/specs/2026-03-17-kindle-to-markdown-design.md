# kindle-to-markdown Design Spec

## Purpose

A reusable Python CLI tool that extracts Kindle ebook content to Markdown by driving the Kindle Cloud Reader through a headless browser. For personal format-shifting — reading purchased ebooks in a preferred format.

## Architecture

Three components connected in a pipeline:

```
CLI  -->  Browser Driver  -->  Extractor  -->  Markdown Output
                                  |
                                  v
                              OCR Fallback
```

### 1. Browser Driver (`browser.py`)

Abstraction over browser backends, connected via Playwright's CDP support.

**Backends:**
- **Lightpanda** (primary) — launched as a subprocess exposing a CDP WebSocket endpoint. Playwright connects via `browser_type.connect_over_cdp()`. Lightpanda is headless-only, so it requires pre-authenticated cookies (see Session Persistence below).
- **Chromium** (fallback) — standard Playwright Chromium launch. Supports headed mode for manual login.

**Two-phase auth strategy:**

Since Lightpanda has no headed mode, authentication uses a two-phase approach:
1. **Login phase** — always uses Chromium in headed mode. User logs in manually. Cookies and localStorage are saved to `~/.kindle-to-md/sessions/`.
2. **Extraction phase** — loads saved session into whichever backend is selected (Lightpanda or Chromium). If the session is expired, falls back to login phase automatically.

A `--reauth` flag forces a fresh login regardless of saved session state.

**Lightpanda subprocess management:**
- On launch, start the Lightpanda binary and wait up to 10 seconds for the CDP WebSocket URL to appear on stdout. If startup times out, raise a clear error suggesting `--backend chromium`.
- If the process crashes mid-extraction, catch the connection error and surface a clear message suggesting `--backend chromium`.

**Interface:**
- `login(region: str) -> None` — launches Chromium headed, waits for auth, saves session.
- `launch(backend: str, region: str) -> Page` — loads saved session, starts the browser, returns a Playwright Page object.
- `shutdown()` — cleanly closes the browser and any subprocesses.

The rest of the codebase works with the Playwright `Page` API regardless of backend, making the browser swappable with a single flag.

### 2. Extractor (`extractor.py`)

Drives the Kindle Cloud Reader to page through a book and extract content.

**Auth flow:**
1. Browser driver loads saved session cookies
2. Navigate to `https://read.amazon.{region}/?asin={ASIN}`
3. If redirected to login (session expired), trigger the login phase automatically
4. Poll for the reader UI to appear (detect a known reader DOM element)
5. Timeout after 5 minutes if auth never completes

**Page navigation:**
1. Wait for the reader to fully load the current page
2. Extract content (see below)
3. Send `ArrowRight` keypress to advance
4. Wait for content to change (compare against previous page)
5. Configurable delay between page turns (`--delay`, default 1.0s) to avoid anti-automation detection
6. Detect end-of-book: 3 consecutive page turns with no content change, each after a 2s settle wait. Blank/sparse pages mid-book (dedications, part dividers) won't trigger this because a forward navigation still produces different (even if minimal) content.

**Progress reporting:**
- Print current page number and any detected chapter headings to stderr
- If the reader UI exposes a total page count or location indicator, display estimated progress percentage

**Content extraction per page (priority order):**
1. **Canvas detection** — if the reader viewport is dominated by a `<canvas>` element, skip DOM extraction and go directly to OCR.
2. **DOM text** — query text nodes within the reader content container. If meaningful text is found (20+ characters), use it. Pages with less text (epigraphs, dedications) are still captured — the threshold only controls whether OCR is also attempted.
3. **Images** — extract `<img>` elements. Handle `src`, `data:` URIs, and `blob:` URLs (convert blob URLs via canvas-to-PNG extraction in the page context — extract eagerly before navigating forward, as blob URLs are origin-scoped and may be revoked). Save to `images/` with sequential filenames (`img-001.png`, `img-002.png`, etc.).
4. **OCR fallback** — if no DOM text and no images are found (or canvas detected), screenshot the reader viewport and run Tesseract OCR on it.

**Chapter detection:**
- Look for heading-like elements (large font, bold, `<h1>`-`<h6>` tags) in the DOM
- When detected, insert a Markdown heading (`#`, `##`, etc.) in the output

### 3. OCR Module (`ocr.py`)

Handles the screenshot-to-text fallback path.

- Takes a Playwright `Page` and a CSS selector for the reader viewport
- Screenshots the element
- Runs Tesseract via `pytesseract`
- Returns extracted text
- Strips common OCR artefacts (stray characters, broken whitespace)

### 4. Markdown Assembler (`markdown.py`)

Combines extracted pages into a single Markdown document.

- Accumulates content page by page
- Inserts chapter headings where detected
- Embeds images as `![](images/filename.png)`
- Handles deduplication of page overlaps using suffix/prefix matching: compare the last N lines of the previous page with the first N lines of the current page, removing overlapping text
- Writes output incrementally — each page is appended to a working file as it's extracted, so partial progress is preserved if extraction fails mid-book
- A `--resume` flag reads existing partial output, counts extracted pages/sections, and skips that many page-forward operations before resuming extraction

### 5. CLI (`cli.py`)

Entry point using Click.

```
Usage: kindle-to-md [OPTIONS] ASIN

Options:
  -o, --output PATH       Output file path (default: {ASIN}.md)
  -b, --backend TEXT       Browser backend: lightpanda | chromium (default: lightpanda)
  --region TEXT            Amazon region: co.uk | com | de | etc. (default: co.uk)
  --timeout INTEGER        Auth timeout in seconds (default: 300)
  --delay FLOAT            Delay between page turns in seconds (default: 1.0)
  --reauth                 Force fresh login, ignoring saved session
  --resume                 Resume extraction from existing partial output
```

## Tech Stack

- Python 3.11+
- Playwright (CDP connection)
- pytesseract + Tesseract system binary (OCR fallback)
- Click (CLI)
- Pillow (image handling for screenshots)

## Project Structure

```
kindle/
├── kindle_to_md/
│   ├── __init__.py
│   ├── cli.py
│   ├── browser.py
│   ├── extractor.py
│   ├── ocr.py
│   └── markdown.py
├── pyproject.toml
└── docs/
    └── superpowers/
        └── specs/
            └── 2026-03-17-kindle-to-markdown-design.md
```

## Key Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Lightpanda can't render Cloud Reader | `--backend chromium` flag for instant fallback |
| Cloud Reader uses canvas rendering | OCR fallback via Tesseract |
| Amazon changes reader DOM structure | Selectors are isolated in extractor.py — single place to update |
| Auth complexity (CAPTCHA/2FA) | Manual login in headed mode; script waits |
| Page overlap/duplication | Content dedup by comparing consecutive pages |
| End-of-book detection | Content-change detection with a stability check |

## Out of Scope

- Automated Amazon login
- DRM decryption
- Batch processing of multiple books (can be added later)
- Table of contents generation from metadata
