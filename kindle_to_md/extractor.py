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
