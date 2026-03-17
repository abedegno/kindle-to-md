# kindle-to-markdown Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reusable Python CLI tool that extracts Kindle ebook content to Markdown via headless browser automation of the Kindle Cloud Reader.

**Architecture:** Three-layer pipeline — Browser Driver (Lightpanda/Chromium via Playwright CDP) → Extractor (page navigation + content extraction) → Markdown Assembler. Two-phase auth: Chromium headed for login with session persistence, any backend for extraction. OCR fallback for canvas-rendered content.

**Tech Stack:** Python 3.11+, Playwright (CDP), pytesseract + Tesseract, Click, Pillow

**Spec:** `docs/superpowers/specs/2026-03-17-kindle-to-markdown-design.md`

---

## Chunk 1: Project Scaffolding & Browser Driver

### Task 1: Project setup

**Files:**
- Create: `pyproject.toml`
- Create: `kindle_to_md/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68.0", "setuptools-scm"]
build-backend = "setuptools.build_meta"

[project]
name = "kindle-to-md"
version = "0.1.0"
description = "Extract Kindle ebooks to Markdown via browser automation"
requires-python = ">=3.11"
dependencies = [
    "playwright>=1.40",
    "click>=8.1",
    "pytesseract>=0.3.10",
    "Pillow>=10.0",
]

[project.scripts]
kindle-to-md = "kindle_to_md.cli:main"
```

- [ ] **Step 2: Create package init**

```python
"""kindle-to-md: Extract Kindle ebooks to Markdown."""
```

- [ ] **Step 3: Install the project in dev mode**

Run: `cd /Users/jonw/kindle && python3 -m venv .venv && source .venv/bin/activate && pip install -e .`
Expected: Successful installation

- [ ] **Step 4: Install Playwright browsers**

Run: `source .venv/bin/activate && playwright install chromium`
Expected: Chromium downloaded

- [ ] **Step 5: Install Lightpanda binary**

Run: `curl -L -o /Users/jonw/kindle/lightpanda https://github.com/lightpanda-io/browser/releases/download/nightly/lightpanda-aarch64-macos && chmod a+x /Users/jonw/kindle/lightpanda`
Expected: Binary downloaded and made executable

- [ ] **Step 6: Verify Lightpanda runs**

Run: `./lightpanda serve --host 127.0.0.1 --port 9222 &; sleep 2; curl -s http://127.0.0.1:9222/json/version; kill %1`
Expected: JSON response with browser info

- [ ] **Step 7: Commit**

```bash
git init
echo -e ".venv/\n__pycache__/\n*.egg-info/\nlightpanda\nimages/" > .gitignore
git add pyproject.toml kindle_to_md/__init__.py tests/__init__.py .gitignore docs/
git commit -m "chore: initial project scaffolding"
```

---

### Task 2: Browser Driver

**Files:**
- Create: `kindle_to_md/browser.py`
- Create: `tests/test_browser.py`

- [ ] **Step 1: Write the failing test for Lightpanda launcher**

```python
# tests/test_browser.py
import pytest
from kindle_to_md.browser import BrowserDriver


def test_lightpanda_launch_creates_page(tmp_path):
    """Lightpanda backend should launch and return a connectable CDP endpoint."""
    driver = BrowserDriver(backend="lightpanda", session_dir=tmp_path / "sessions")
    try:
        page = driver.launch()
        assert page is not None
        page.goto("data:text/html,<h1>hello</h1>")
        assert "hello" in page.content()
    finally:
        driver.shutdown()


def test_chromium_launch_creates_page(tmp_path):
    """Chromium backend should launch and return a Playwright page."""
    driver = BrowserDriver(backend="chromium", session_dir=tmp_path / "sessions")
    try:
        page = driver.launch()
        assert page is not None
        page.goto("data:text/html,<h1>hello</h1>")
        assert "hello" in page.content()
    finally:
        driver.shutdown()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_browser.py -v`
Expected: FAIL — `ImportError: cannot import name 'BrowserDriver'`

- [ ] **Step 3: Implement BrowserDriver**

```python
# kindle_to_md/browser.py
"""Browser driver abstraction — Lightpanda or Chromium via Playwright CDP."""

import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


class BrowserDriver:
    def __init__(
        self,
        backend: str = "lightpanda",
        session_dir: Path | None = None,
        region: str = "co.uk",
        lightpanda_bin: str = "./lightpanda",
    ):
        self.backend = backend
        self.session_dir = session_dir or Path.home() / ".kindle-to-md" / "sessions"
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.region = region
        self.lightpanda_bin = lightpanda_bin

        self._playwright = None
        self._browser = None
        self._context = None
        self._lightpanda_proc = None

    def launch(self) -> Page:
        """Start the browser and return a Playwright Page with saved session loaded."""
        self._playwright = sync_playwright().start()

        if self.backend == "lightpanda":
            return self._launch_lightpanda()
        elif self.backend == "chromium":
            return self._launch_chromium(headed=False)
        else:
            raise ValueError(f"Unknown backend: {self.backend}")

    def login(self, timeout: int = 300) -> None:
        """Launch Chromium in headed mode for manual Amazon login, then save session."""
        self._playwright = sync_playwright().start()
        page = self._launch_chromium(headed=True)

        login_url = f"https://www.amazon.{self.region}/ap/signin"
        page.goto(login_url)

        print(
            f"Please log in to Amazon in the browser window.\n"
            f"Waiting up to {timeout}s for authentication...",
            file=sys.stderr,
        )

        # Wait until we land on a non-signin page
        try:
            page.wait_for_url(
                lambda url: "/ap/signin" not in url and "/ap/mfa" not in url,
                timeout=timeout * 1000,
            )
        except Exception:
            self.shutdown()
            raise TimeoutError("Login timed out. Please try again.")

        print("Login successful. Saving session...", file=sys.stderr)
        self._save_session()
        self.shutdown()

    def _launch_lightpanda(self) -> Page:
        """Start Lightpanda subprocess and connect via CDP."""
        self._lightpanda_proc = subprocess.Popen(
            [
                self.lightpanda_bin,
                "serve",
                "--host", "127.0.0.1",
                "--port", "9222",
                "--timeout", "300",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for CDP endpoint to be ready
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                import urllib.request
                resp = urllib.request.urlopen("http://127.0.0.1:9222/json/version")
                info = json.loads(resp.read())
                ws_url = info.get("webSocketDebuggerUrl", "ws://127.0.0.1:9222")
                break
            except Exception:
                time.sleep(0.5)
        else:
            self.shutdown()
            raise ConnectionError(
                "Lightpanda failed to start within 10s. "
                "Try --backend chromium instead."
            )

        self._browser = self._playwright.chromium.connect_over_cdp(ws_url)
        self._context = self._browser.contexts[0] if self._browser.contexts else self._browser.new_context()
        self._load_session()
        return self._context.new_page()

    def _launch_chromium(self, headed: bool = False) -> Page:
        """Launch Chromium via Playwright."""
        self._browser = self._playwright.chromium.launch(headless=not headed)
        session_file = self._session_file()
        if session_file.exists():
            self._context = self._browser.new_context(storage_state=str(session_file))
        else:
            self._context = self._browser.new_context()
        return self._context.new_page()

    def _session_file(self) -> Path:
        return self.session_dir / f"amazon_{self.region}.json"

    def _save_session(self) -> None:
        """Save cookies and storage state to disk."""
        if self._context:
            state = self._context.storage_state()
            self._session_file().write_text(json.dumps(state, indent=2))

    def _load_session(self) -> None:
        """Load saved session cookies into the browser context."""
        session_file = self._session_file()
        if session_file.exists():
            state = json.loads(session_file.read_text())
            if state.get("cookies"):
                self._context.add_cookies(state["cookies"])

    def shutdown(self) -> None:
        """Close browser and any subprocesses."""
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
        if self._lightpanda_proc:
            self._lightpanda_proc.terminate()
            self._lightpanda_proc.wait(timeout=5)
            self._lightpanda_proc = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_browser.py -v`
Expected: Both tests PASS

- [ ] **Step 5: Commit**

```bash
git add kindle_to_md/browser.py tests/test_browser.py
git commit -m "feat: browser driver with Lightpanda and Chromium backends"
```

---

### Task 3: Session persistence

**Files:**
- Modify: `kindle_to_md/browser.py`
- Create: `tests/test_session.py`

- [ ] **Step 1: Write failing tests for session save/load**

```python
# tests/test_session.py
import json
import pytest
from kindle_to_md.browser import BrowserDriver


def test_save_and_load_session(tmp_path):
    """Saved session cookies should be restored on next launch via storage_state."""
    session_dir = tmp_path / "sessions"

    # First driver: launch, add a cookie, save
    driver1 = BrowserDriver(backend="chromium", session_dir=session_dir)
    try:
        page = driver1.launch()
        page.goto("data:text/html,<h1>test</h1>")
        driver1._context.add_cookies([{
            "name": "test_cookie",
            "value": "abc123",
            "domain": "example.com",
            "path": "/",
        }])
        driver1._save_session()
    finally:
        driver1.shutdown()

    # Verify session file exists and contains the cookie
    session_file = session_dir / "amazon_co.uk.json"
    assert session_file.exists()
    state = json.loads(session_file.read_text())
    assert any(c["name"] == "test_cookie" for c in state["cookies"])

    # Second driver: should load the saved session (cookies + localStorage)
    # via Playwright's storage_state parameter
    driver2 = BrowserDriver(backend="chromium", session_dir=session_dir)
    try:
        page = driver2.launch()
        cookies = driver2._context.cookies()
        assert any(c["name"] == "test_cookie" and c["value"] == "abc123" for c in cookies)
    finally:
        driver2.shutdown()


def test_no_session_file_works(tmp_path):
    """Launch should work fine when no session file exists."""
    driver = BrowserDriver(backend="chromium", session_dir=tmp_path / "sessions")
    try:
        page = driver.launch()
        assert page is not None
    finally:
        driver.shutdown()
```

- [ ] **Step 2: Run tests to verify they pass** (implementation already in browser.py)

Run: `source .venv/bin/activate && python -m pytest tests/test_session.py -v`
Expected: PASS — session persistence is already implemented in Task 2

- [ ] **Step 3: Commit**

```bash
git add tests/test_session.py
git commit -m "test: session persistence verification"
```

---

## Chunk 2: Content Extraction

### Task 4: OCR module

**Files:**
- Create: `kindle_to_md/ocr.py`
- Create: `tests/test_ocr.py`

- [ ] **Step 1: Verify Tesseract is installed**

Run: `which tesseract || brew install tesseract`
Expected: Tesseract binary path

- [ ] **Step 2: Write failing test for OCR**

```python
# tests/test_ocr.py
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_ocr.py -v`
Expected: FAIL — `ImportError: cannot import name 'ocr_image'`

- [ ] **Step 4: Implement OCR module**

```python
# kindle_to_md/ocr.py
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_ocr.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add kindle_to_md/ocr.py tests/test_ocr.py
git commit -m "feat: OCR module with Tesseract for image/canvas fallback"
```

---

### Task 5: Extractor — page content extraction

**Files:**
- Create: `kindle_to_md/extractor.py`
- Create: `tests/test_extractor.py`

- [ ] **Step 1: Write failing tests for content extraction helpers**

```python
# tests/test_extractor.py
import pytest
from kindle_to_md.extractor import PageContent, extract_page_content


def test_page_content_dataclass():
    """PageContent should hold text, images, and chapter info."""
    pc = PageContent(text="Hello", images=[], chapter_heading=None, page_number=1)
    assert pc.text == "Hello"
    assert pc.page_number == 1


def test_has_meaningful_text():
    """PageContent with 20+ chars should be considered meaningful."""
    pc = PageContent(text="This is meaningful text content", images=[], chapter_heading=None, page_number=1)
    assert pc.has_meaningful_text()

    sparse = PageContent(text="Short", images=[], chapter_heading=None, page_number=1)
    assert not sparse.has_meaningful_text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_extractor.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement extractor data model and page extraction**

```python
# kindle_to_md/extractor.py
"""Kindle Cloud Reader page extraction and navigation."""

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Page

from kindle_to_md.ocr import ocr_screenshot

MEANINGFUL_TEXT_THRESHOLD = 20
END_OF_BOOK_UNCHANGED_COUNT = 3
PAGE_SETTLE_DELAY = 2.0


@dataclass
class PageContent:
    text: str
    images: list[str]
    chapter_heading: str | None
    page_number: int

    def has_meaningful_text(self) -> bool:
        return len(self.text.strip()) >= MEANINGFUL_TEXT_THRESHOLD


def extract_page_content(page: Page, page_number: int, images_dir: Path) -> PageContent:
    """Extract content from the current Kindle Cloud Reader page."""
    # Check for canvas-based rendering
    has_canvas = page.evaluate("""() => {
        const reader = document.querySelector('#kindle-reader-content, #kr-renderer, .kp-notebook-container');
        if (!reader) return false;
        const canvas = reader.querySelector('canvas');
        return canvas !== null && canvas.width > 100;
    }""")

    if has_canvas:
        screenshot = page.screenshot()
        text = ocr_screenshot(screenshot)
        return PageContent(
            text=text,
            images=[],
            chapter_heading=_detect_chapter(page),
            page_number=page_number,
        )

    # Try DOM text extraction
    text = page.evaluate("""() => {
        const selectors = [
            '#kindle-reader-content',
            '#kr-renderer',
            '.kp-notebook-container',
            '#a-page',
            '[class*="reader"]',
            '[id*="reader"]',
        ];
        for (const sel of selectors) {
            const el = document.querySelector(sel);
            if (el && el.innerText && el.innerText.trim().length > 0) {
                return el.innerText.trim();
            }
        }
        return document.body ? document.body.innerText.trim() : '';
    }""")

    # Extract images
    images = _extract_images(page, page_number, images_dir)

    # If not enough DOM text and no images, fall back to OCR
    content = PageContent(
        text=text,
        images=images,
        chapter_heading=_detect_chapter(page),
        page_number=page_number,
    )

    if not content.has_meaningful_text() and not images:
        screenshot = page.screenshot()
        ocr_text = ocr_screenshot(screenshot)
        if len(ocr_text.strip()) > len(text.strip()):
            content.text = ocr_text

    return content


def _detect_chapter(page: Page) -> str | None:
    """Look for heading-like elements indicating a chapter break."""
    heading = page.evaluate("""() => {
        const headings = document.querySelectorAll('h1, h2, h3, h4, h5, h6, [class*="chapter"], [class*="title"]');
        for (const h of headings) {
            const text = h.innerText?.trim();
            if (text && text.length > 2 && text.length < 200) {
                return text;
            }
        }
        return null;
    }""")
    return heading


def _extract_images(page: Page, page_number: int, images_dir: Path) -> list[str]:
    """Extract images from the current page, handling src, data:, and blob: URLs."""
    images_dir.mkdir(parents=True, exist_ok=True)

    image_data_list = page.evaluate("""() => {
        const imgs = document.querySelectorAll('#kindle-reader-content img, #kr-renderer img, [class*="reader"] img');
        const results = [];
        for (const img of imgs) {
            if (img.naturalWidth < 10 || img.naturalHeight < 10) continue;
            const src = img.src || '';
            if (src.startsWith('data:')) {
                results.push({type: 'data', data: src});
            } else if (src.startsWith('blob:')) {
                // Convert blob to data URL via canvas
                try {
                    const canvas = document.createElement('canvas');
                    canvas.width = img.naturalWidth;
                    canvas.height = img.naturalHeight;
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(img, 0, 0);
                    results.push({type: 'data', data: canvas.toDataURL('image/png')});
                } catch(e) {
                    results.push({type: 'error', data: e.message});
                }
            } else if (src) {
                results.push({type: 'url', data: src});
            }
        }
        return results;
    }""")

    saved_paths = []
    img_counter = len(list(images_dir.glob("*.png")))

    for item in image_data_list:
        if item["type"] == "data":
            import base64
            # Strip data URI prefix
            data = item["data"]
            if "," in data:
                data = data.split(",", 1)[1]
            img_bytes = base64.b64decode(data)
            img_counter += 1
            filename = f"img-{img_counter:03d}.png"
            filepath = images_dir / filename
            filepath.write_bytes(img_bytes)
            saved_paths.append(f"images/{filename}")
        elif item["type"] == "url":
            # Download via the browser
            try:
                response = page.request.get(item["data"])
                if response.ok:
                    img_counter += 1
                    filename = f"img-{img_counter:03d}.png"
                    filepath = images_dir / filename
                    filepath.write_bytes(response.body())
                    saved_paths.append(f"images/{filename}")
            except Exception:
                pass

    return saved_paths


def extract_book(
    page: Page,
    asin: str,
    region: str,
    output_path: Path,
    images_dir: Path,
    delay: float = 1.0,
    resume_from: int = 0,
) -> None:
    """Navigate through the entire book, extracting each page to markdown.

    Uses markdown.format_page for formatting and markdown.append_page for
    incremental output. Extractor only handles extraction and navigation.
    """
    from kindle_to_md.markdown import format_page, append_page

    url = f"https://read.amazon.{region}/?asin={asin}"
    page.goto(url, timeout=60000)

    # Wait for reader to load
    print(f"Waiting for Kindle reader to load...", file=sys.stderr)
    try:
        page.wait_for_selector(
            "#kindle-reader-content, #kr-renderer, .kp-notebook-container, [id*='reader']",
            timeout=60000,
        )
    except Exception:
        raise RuntimeError(
            "Kindle reader did not load. Session may be expired — try with --reauth"
        )

    print("Reader loaded. Starting extraction...", file=sys.stderr)
    time.sleep(2)  # Let the reader fully render

    # Skip pages if resuming
    if resume_from > 0:
        print(f"Resuming: skipping {resume_from} pages...", file=sys.stderr)
        for _ in range(resume_from):
            page.keyboard.press("ArrowRight")
            time.sleep(0.3)
        time.sleep(1)

    prev_text = ""
    unchanged_count = 0
    page_number = resume_from
    total_pages = 0

    while True:
        page_number += 1
        content = extract_page_content(page, page_number, images_dir)
        current_text = content.text.strip()

        # End-of-book detection: if content unchanged, wait and re-check
        if current_text == prev_text:
            time.sleep(PAGE_SETTLE_DELAY)
            content = extract_page_content(page, page_number, images_dir)
            current_text = content.text.strip()

        if current_text == prev_text:
            unchanged_count += 1
            if unchanged_count >= END_OF_BOOK_UNCHANGED_COUNT:
                print(f"\nEnd of book detected at page {page_number}.", file=sys.stderr)
                break
        else:
            unchanged_count = 0

        # Format and append via markdown module
        formatted = format_page(content, prev_text)
        append_page(output_path, formatted)
        total_pages += 1
        prev_text = current_text

        # Progress
        chapter_info = f" — {content.chapter_heading}" if content.chapter_heading else ""
        print(f"\rPage {page_number}{chapter_info}", end="", file=sys.stderr)

        # Navigate forward
        page.keyboard.press("ArrowRight")
        time.sleep(delay)

    print(f"\nExtraction complete. {total_pages} pages extracted.", file=sys.stderr)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_extractor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add kindle_to_md/extractor.py tests/test_extractor.py
git commit -m "feat: extractor with DOM text, image, and OCR extraction"
```

---

### Task 6: Markdown assembler

**Files:**
- Create: `kindle_to_md/markdown.py`
- Create: `tests/test_markdown.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_markdown.py
from pathlib import Path
from kindle_to_md.markdown import remove_overlap, format_page, append_page, count_existing_pages
from kindle_to_md.extractor import PageContent


def test_remove_overlap_detects_matching_suffix_prefix():
    prev = "Line 1\nLine 2\nLine 3\nLine 4"
    curr = "Line 3\nLine 4\nLine 5\nLine 6"
    result = remove_overlap(prev, curr)
    assert "Line 3" not in result
    assert "Line 4" not in result
    assert "Line 5" in result
    assert "Line 6" in result


def test_remove_overlap_no_overlap():
    prev = "AAA\nBBB"
    curr = "CCC\nDDD"
    result = remove_overlap(prev, curr)
    assert result == "CCC\nDDD"


def test_format_page_with_chapter():
    pc = PageContent(
        text="Some content here.",
        images=["images/img-001.png"],
        chapter_heading="Chapter 1",
        page_number=1,
    )
    result = format_page(pc, prev_text="")
    assert "## Chapter 1" in result
    assert "Some content here." in result
    assert "![](images/img-001.png)" in result
    assert "<!-- page:1 -->" in result


def test_format_page_no_chapter():
    pc = PageContent(
        text="Just text.",
        images=[],
        chapter_heading=None,
        page_number=2,
    )
    result = format_page(pc, prev_text="")
    assert "Just text." in result
    assert "##" not in result
    assert "<!-- page:2 -->" in result


def test_append_and_count_pages(tmp_path):
    """append_page writes to file, count_existing_pages reads page markers."""
    output = tmp_path / "test.md"
    pc1 = PageContent(text="Page one content.", images=[], chapter_heading=None, page_number=1)
    pc2 = PageContent(text="Page two content.", images=[], chapter_heading=None, page_number=2)

    append_page(output, format_page(pc1, prev_text=""))
    append_page(output, format_page(pc2, prev_text="Page one content."))

    assert count_existing_pages(str(output)) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_markdown.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement markdown module**

```python
# kindle_to_md/markdown.py
"""Markdown formatting and assembly for extracted Kindle content."""

from pathlib import Path

from kindle_to_md.extractor import PageContent

# Page marker used for resume counting
PAGE_MARKER = "<!-- page:{page_number} -->"


def remove_overlap(prev_text: str, current_text: str) -> str:
    """Remove overlapping text between consecutive pages."""
    prev_lines = prev_text.strip().split("\n")
    curr_lines = current_text.strip().split("\n")

    if not prev_lines or not curr_lines:
        return current_text

    max_check = min(10, len(prev_lines), len(curr_lines))
    best_overlap = 0

    for overlap_size in range(1, max_check + 1):
        prev_suffix = [l.strip() for l in prev_lines[-overlap_size:]]
        curr_prefix = [l.strip() for l in curr_lines[:overlap_size]]
        if prev_suffix == curr_prefix:
            best_overlap = overlap_size

    if best_overlap > 0:
        return "\n".join(curr_lines[best_overlap:])
    return current_text


def format_page(content: PageContent, prev_text: str) -> str:
    """Format a single page's content as Markdown with dedup against previous page."""
    parts = []

    if content.chapter_heading:
        parts.append(f"\n## {content.chapter_heading}\n")

    text = content.text.strip()
    if prev_text:
        text = remove_overlap(prev_text, text)

    if text:
        parts.append(text)

    for img_path in content.images:
        parts.append(f"\n![]({img_path})\n")

    # Add page marker for resume support
    parts.append(PAGE_MARKER.format(page_number=content.page_number))

    return "\n\n".join(parts)


def append_page(output_path: Path, formatted_text: str) -> None:
    """Append a formatted page to the output file."""
    with open(output_path, "a", encoding="utf-8") as f:
        f.write(formatted_text)
        f.write("\n\n")


def count_existing_pages(output_path: str) -> int:
    """Count pages in an existing partial output file for resume support.

    Uses page markers (<!-- page:N -->) for accurate counting.
    """
    p = Path(output_path)
    if not p.exists():
        return 0
    content = p.read_text(encoding="utf-8")
    import re
    markers = re.findall(r"<!-- page:(\d+) -->", content)
    if markers:
        return int(markers[-1])  # Return the last page number
    return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_markdown.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add kindle_to_md/markdown.py tests/test_markdown.py
git commit -m "feat: markdown formatting with overlap dedup and resume counting"
```

---

## Chunk 3: CLI & Integration

### Task 7: CLI entry point

**Files:**
- Create: `kindle_to_md/cli.py`

- [ ] **Step 1: Implement CLI**

```python
# kindle_to_md/cli.py
"""CLI entry point for kindle-to-md."""

import sys
from pathlib import Path

import click

from kindle_to_md.browser import BrowserDriver
from kindle_to_md.extractor import extract_book
from kindle_to_md.markdown import count_existing_pages


@click.command()
@click.argument("asin")
@click.option("-o", "--output", default=None, help="Output file path (default: {ASIN}.md)")
@click.option("-b", "--backend", default="lightpanda", type=click.Choice(["lightpanda", "chromium"]), help="Browser backend")
@click.option("--region", default="co.uk", help="Amazon region (co.uk, com, de, etc.)")
@click.option("--timeout", default=300, help="Auth timeout in seconds")
@click.option("--delay", default=1.0, help="Delay between page turns in seconds")
@click.option("--reauth", is_flag=True, help="Force fresh login")
@click.option("--resume", is_flag=True, help="Resume from existing partial output")
def main(asin: str, output: str, backend: str, region: str, timeout: int, delay: float, reauth: bool, resume: bool):
    """Extract a Kindle ebook to Markdown.

    ASIN is the Amazon book identifier (e.g., B0G6MF376S).
    You can also pass a full Kindle URL — the ASIN will be extracted.
    """
    # Extract ASIN from URL if needed
    if "asin=" in asin:
        asin = asin.split("asin=")[1].split("&")[0]
    elif "/" in asin:
        # Try to find ASIN-like pattern
        parts = asin.split("/")
        for part in parts:
            if part.startswith("B0") and len(part) == 10:
                asin = part
                break

    output_path = Path(output) if output else Path(f"{asin}.md")
    images_dir = output_path.parent / "images"

    driver = BrowserDriver(
        backend=backend,
        region=region,
    )

    try:
        # Handle auth
        session_file = driver._session_file()
        if reauth or not session_file.exists():
            print("Login required. Opening browser...", file=sys.stderr)
            driver.login(timeout=timeout)
            # Re-create driver for extraction
            driver = BrowserDriver(backend=backend, region=region)

        # Determine resume point
        resume_from = 0
        if resume and output_path.exists():
            resume_from = count_existing_pages(str(output_path))
            print(f"Resuming from page {resume_from}...", file=sys.stderr)
        elif not resume and output_path.exists():
            # Start fresh
            output_path.unlink()

        # Launch extraction browser
        page = driver.launch()

        extract_book(
            page=page,
            asin=asin,
            region=region,
            output_path=output_path,
            images_dir=images_dir,
            delay=delay,
            resume_from=resume_from,
        )

        print(f"\nOutput saved to {output_path}", file=sys.stderr)

    except KeyboardInterrupt:
        print("\n\nInterrupted. Partial output saved.", file=sys.stderr)
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        if backend == "lightpanda":
            print("Tip: try --backend chromium if Lightpanda isn't working.", file=sys.stderr)
        sys.exit(1)
    finally:
        driver.shutdown()
```

- [ ] **Step 2: Verify CLI help works**

Run: `source .venv/bin/activate && kindle-to-md --help`
Expected: Help text showing usage, options, and ASIN argument

- [ ] **Step 3: Commit**

```bash
git add kindle_to_md/cli.py
git commit -m "feat: CLI entry point with all options"
```

---

### Task 8: Integration test — end to end with a test HTML page

**Files:**
- Create: `tests/test_integration.py`
- Create: `tests/fixtures/fake_reader.html`

- [ ] **Step 1: Create a fake Kindle reader HTML page for testing**

```html
<!-- tests/fixtures/fake_reader.html -->
<!DOCTYPE html>
<html>
<head><title>Fake Kindle Reader</title></head>
<body>
  <div id="kindle-reader-content">
    <div class="page" id="page-1">
      <h2>Chapter 1: The Beginning</h2>
      <p>This is the first page of our test book. It contains enough text to be considered meaningful by the extractor threshold.</p>
    </div>
  </div>
  <script>
    let currentPage = 1;
    const pages = [
      {heading: 'Chapter 1: The Beginning', text: 'This is the first page of our test book. It contains enough text to be considered meaningful by the extractor threshold.'},
      {heading: null, text: 'This is the second page with more content. The story continues with interesting developments and plot twists.'},
      {heading: 'Chapter 2: The Middle', text: 'Chapter two begins here. New adventures await our protagonist in this exciting chapter.'},
      {heading: null, text: 'The final page of our test book. Everything wraps up nicely with a satisfying conclusion.'},
    ];

    document.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowRight' && currentPage < pages.length) {
        currentPage++;
        const page = pages[currentPage - 1];
        const container = document.getElementById('kindle-reader-content');
        container.innerHTML = `<div class="page" id="page-${currentPage}">
          ${page.heading ? `<h2>${page.heading}</h2>` : ''}
          <p>${page.text}</p>
        </div>`;
      }
    });
  </script>
</body>
</html>
```

- [ ] **Step 2: Write integration test**

```python
# tests/test_integration.py
"""Integration test using a fake Kindle reader page."""
from pathlib import Path
from playwright.sync_api import sync_playwright


def test_extract_from_fake_reader(tmp_path):
    """Full extraction pipeline against a fake reader page."""
    from kindle_to_md.extractor import extract_page_content, PageContent

    fixture_path = Path(__file__).parent / "fixtures" / "fake_reader.html"
    output = tmp_path / "test_book.md"
    images_dir = tmp_path / "images"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        page.goto(f"file://{fixture_path}")
        page.wait_for_selector("#kindle-reader-content")

        pages = []
        for i in range(4):
            content = extract_page_content(page, i + 1, images_dir)
            pages.append(content)
            page.keyboard.press("ArrowRight")
            import time
            time.sleep(0.3)

        browser.close()

    # Verify extraction
    assert len(pages) == 4
    assert pages[0].chapter_heading is not None
    assert "Chapter 1" in pages[0].chapter_heading
    assert pages[0].has_meaningful_text()
    assert pages[2].chapter_heading is not None
    assert "Chapter 2" in pages[2].chapter_heading
```

- [ ] **Step 3: Run integration test**

Run: `source .venv/bin/activate && python -m pytest tests/test_integration.py -v`
Expected: PASS

- [ ] **Step 4: Run full test suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/fake_reader.html tests/test_integration.py
git commit -m "test: integration test with fake Kindle reader page"
```

---

### Task 9: Manual smoke test with Lightpanda

- [ ] **Step 1: Start Lightpanda and verify CDP connection from Python**

Run:
```bash
source .venv/bin/activate
python3 -c "
from playwright.sync_api import sync_playwright
import subprocess, time

proc = subprocess.Popen(['./lightpanda', 'serve', '--host', '127.0.0.1', '--port', '9222', '--timeout', '300'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(3)

try:
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp('ws://127.0.0.1:9222')
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = ctx.new_page()
    page.goto('data:text/html,<h1>Lightpanda works</h1>')
    print('Content:', page.content()[:200])
    print('SUCCESS: Lightpanda CDP connection works')
    browser.close()
    pw.stop()
except Exception as e:
    print(f'FAILED: {e}')
    print('Lightpanda may not support this — try --backend chromium')
finally:
    proc.terminate()
"
```

Expected: Either SUCCESS (Lightpanda works) or FAILED (need Chromium fallback)

- [ ] **Step 2: If Lightpanda works, try loading the Kindle Cloud Reader**

Run: `source .venv/bin/activate && kindle-to-md B0G6MF376S --backend lightpanda --reauth`

If this fails, note the error and try:
Run: `source .venv/bin/activate && kindle-to-md B0G6MF376S --backend chromium --reauth`

- [ ] **Step 3: Commit any fixes needed**

```bash
git add -u
git commit -m "fix: adjustments from smoke testing"
```

---

### Task 10: Final commit — README

- [ ] **Step 1: Create README**

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with usage instructions"
```
