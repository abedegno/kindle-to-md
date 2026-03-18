"""Kindle Cloud Reader page extraction and navigation."""

import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Page

from kindle_to_md.ocr import ocr_screenshot

log = logging.getLogger("kindle-to-md")

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
    log.info(f"Navigating to {url}")
    page.goto(url, timeout=60000)

    current_url = page.evaluate("window.location.href")
    log.info(f"Landed on: {current_url}")
    log.info(f"Page title: {page.title()}")

    # Check if we got redirected to login
    if "/ap/" in current_url or "signin" in current_url:
        log.warning("Redirected to login page — session may be expired")
        raise RuntimeError(
            "Redirected to Amazon login. Session expired — run with --reauth"
        )

    # The ASIN URL may land on the library page — we need to open the book
    print("Waiting for Kindle reader to load...", file=sys.stderr)
    log.info("Waiting for page to settle...")
    time.sleep(3)

    # Check if we're on the library page and need to click to open the book
    current_url = page.evaluate("window.location.href")
    log.info(f"Current URL after settle: {current_url}")

    if "kindle-library" in current_url or "library" in current_url:
        log.info("On library page — attempting to open book...")
        print("On library page, opening book...", file=sys.stderr)

        # Try clicking the book cover/link with the ASIN
        opened = False
        # Try various selectors for opening a book from the library
        book_selectors = [
            f'[data-asin="{asin}"]',
            f'a[href*="{asin}"]',
            f'img[src*="{asin}"]',
            '[id*="library-item"]',
        ]
        for sel in book_selectors:
            try:
                el = page.query_selector(sel)
                if el:
                    log.info(f"Found book element with selector: {sel}")
                    el.click()
                    opened = True
                    break
            except Exception as e:
                log.debug(f"Selector {sel} failed: {e}")

        if not opened:
            # Try clicking the first book in the library
            log.info("Trying to click first book in library...")
            try:
                page.click('.book-image, .library-book, [class*="book"], [class*="cover"]', timeout=5000)
                opened = True
            except Exception:
                log.warning("Could not find a book to click in library")

        if opened:
            log.info("Clicked book, waiting for reader to load...")
            time.sleep(5)
            current_url = page.evaluate("window.location.href")
            log.info(f"URL after clicking book: {current_url}")

    # Now wait for the actual reader content frame/element
    log.info("Waiting for reader content...")

    # The Kindle reader uses an iframe — look for it
    reader_loaded = False
    for attempt in range(30):  # 30 attempts, 2s each = 60s
        # Check for iframe-based reader
        frames = page.frames
        log.debug(f"Found {len(frames)} frames")
        for frame in frames:
            frame_url = ""
            try:
                frame_url = frame.url
            except Exception:
                pass
            if "KindleReader" in frame_url or "read.amazon" in frame_url:
                log.info(f"Found reader frame: {frame_url}")

            # Check for content in any frame
            try:
                text = frame.evaluate("""() => {
                    const el = document.querySelector('#kindle-reader-content, #kr-renderer, .kp-notebook-container, #a-page');
                    return el ? el.innerText.substring(0, 200) : '';
                }""")
                if text and len(text.strip()) > 20:
                    log.info(f"Found reader content in frame: {text[:100]}")
                    reader_loaded = True
                    break
            except Exception:
                pass

        if reader_loaded:
            break

        # Also check main page
        try:
            text = page.evaluate("""() => {
                const el = document.querySelector('#kindle-reader-content, #kr-renderer, .kp-notebook-container, #a-page');
                return el ? el.innerText.substring(0, 200) : '';
            }""")
            if text and len(text.strip()) > 20:
                log.info(f"Found reader content on main page: {text[:100]}")
                reader_loaded = True
                break
        except Exception:
            pass

        time.sleep(2)

    if not reader_loaded:
        # Check for the Kryptonite canvas-based reader (#kr-renderer)
        has_kr = page.evaluate("() => !!document.querySelector('#kr-renderer')")
        if has_kr:
            log.info("Detected Kryptonite canvas-based reader (#kr-renderer)")
            reader_loaded = True
        else:
            body = page.evaluate("() => document.body ? document.body.innerText.substring(0, 1000) : 'no body'")
            log.error(f"Reader content not found. Page body: {body[:500]}")
            log.error(f"Final URL: {page.evaluate('window.location.href')}")
            for i, f in enumerate(page.frames):
                try:
                    log.error(f"Frame {i}: {f.url}")
                except Exception:
                    pass
            raise RuntimeError(
                "Kindle reader content did not load. Try opening the book manually with --headed"
            )

    print("Reader loaded. Starting extraction...", file=sys.stderr)
    log.info("Reader content found, starting extraction")

    # Dismiss cookie consent popup if present
    _dismiss_cookie_popup(page)

    # Switch to single-column (continuous scroll or 1-page) layout
    _set_single_column(page)
    time.sleep(2)

    # Navigate to the beginning of the book (reader remembers last position)
    if resume_from == 0:
        _go_to_start(page)
        time.sleep(2)

    # Detect page count from the reader footer (e.g., "Page 2 of 452")
    page_info = page.evaluate("""() => {
        const footer = document.querySelector('.footer-label-color-default, [class*="footer"]');
        return footer ? footer.innerText : '';
    }""")
    log.info(f"Reader page info: {page_info}")
    total_book_pages = 0
    if "of" in page_info:
        try:
            total_book_pages = int(page_info.split("of")[1].strip().split()[0])
            log.info(f"Total book pages: {total_book_pages}")
            print(f"Book has {total_book_pages} pages", file=sys.stderr)
        except (ValueError, IndexError):
            pass
    time.sleep(2)  # Let the reader fully render

    # Skip pages if resuming
    if resume_from > 0:
        print(f"Resuming: skipping {resume_from} pages...", file=sys.stderr)
        for _ in range(resume_from):
            _next_page(page)
            time.sleep(0.3)
        time.sleep(1)

    prev_text = ""
    unchanged_count = 0
    screenshot_num = resume_from  # Sequential counter for screenshot filenames
    total_pages = 0

    while True:
        # Get the reader's own page number from the footer
        reader_page = _get_reader_page_num(page)
        log.debug(f"Reader page: {reader_page}, total: {total_book_pages}")

        # Screenshot the reader area for OCR — use sequential numbering
        screenshot_num += 1
        content, screenshot_bytes = _extract_via_screenshot(page, screenshot_num, images_dir)
        log.debug(f"Extracted {len(content.text)} chars from screenshot {screenshot_num} (reader page {reader_page})")

        # Format and append via markdown module
        formatted = format_page(content, prev_text)
        append_page(output_path, formatted)
        total_pages += 1
        prev_text = content.text.strip()

        # Progress
        pct = f" ({reader_page}/{total_book_pages})" if total_book_pages > 0 else ""
        print(f"\rPage {screenshot_num}{pct}", end="", file=sys.stderr)

        # Navigate forward
        _next_page(page)

        # Wait for content to actually change (page number or canvas pixels)
        changed = _wait_for_content_change(page, reader_page, hash(screenshot_bytes), timeout=5.0)
        if not changed:
            unchanged_count += 1
            if unchanged_count >= END_OF_BOOK_UNCHANGED_COUNT:
                print(f"\nEnd of book detected at reader page {reader_page}.", file=sys.stderr)
                break
        else:
            unchanged_count = 0

    print(f"\nExtraction complete. {total_pages} pages extracted.", file=sys.stderr)


def _wait_for_content_change(page: Page, old_page: int, old_screenshot_hash: int, timeout: float = 5.0) -> bool:
    """Wait until either the page number or the canvas content changes.

    Handles both page advances (number changes) and long pages that span
    multiple screens (same page number, different content).

    Returns True if something changed, False if nothing changed (end of book).
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        # Check page number first (fast)
        current = _get_reader_page_num(page)
        if current != old_page and current > 0:
            time.sleep(0.5)  # Let canvas finish rendering
            return True

        # Page number same — check if canvas content changed (for long pages)
        renderer = page.query_selector("#kr-renderer")
        if renderer:
            screenshot = renderer.screenshot()
            if hash(screenshot) != old_screenshot_hash:
                time.sleep(0.3)  # Brief settle
                return True

        time.sleep(0.3)
    log.debug(f"No content change from page {old_page} within {timeout}s")
    return False


def _next_page(page: Page) -> None:
    """Advance to the next page using the RIGHT arrow key.

    Matches the approach used by kindleOCRer — press Right arrow key
    which the Kindle reader intercepts for page navigation.
    """
    page.keyboard.press("ArrowRight")


def _go_to_start(page: Page) -> None:
    """Navigate to page 1 using the Reader Menu > Go to Page dialog."""
    try:
        current = _get_reader_page_num(page)
        log.info(f"Navigating to page 1 from page {current}")
        print(f"Navigating to page 1 from page {current}...", file=sys.stderr)

        # Open Reader Menu (three dots button)
        menu_btn = page.query_selector('ion-button[aria-label="Reader menu"]')
        if not menu_btn:
            log.warning("Reader menu button not found")
            return
        menu_btn.click()
        time.sleep(1)

        # Click "Go to Page"
        go_to = page.query_selector('[data-testid="pop_over_menu_go_to_page"]')
        if not go_to:
            log.warning("Go to Page menu item not found")
            page.keyboard.press("Escape")
            return
        go_to.click()
        time.sleep(1)

        # The input is inside ion-input with a native input inside.
        # Click on it to focus, clear it, type "1"
        native_input = page.query_selector('[item-i-d="go-to-modal-number-input"] input.native-input')
        if native_input:
            native_input.click()
            time.sleep(0.2)
            native_input.fill("1")
            log.info("Filled native input with 1")
        else:
            # Fallback: set via JS
            page.evaluate("""() => {
                const ionInput = document.querySelector('[item-i-d="go-to-modal-number-input"]');
                if (ionInput) {
                    const native = ionInput.querySelector('input.native-input');
                    if (native) {
                        native.focus();
                        native.value = '1';
                        native.dispatchEvent(new Event('input', { bubbles: true }));
                        native.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }
            }""")
            log.info("Set page input to 1 via JS fallback")
        time.sleep(0.5)

        # Click the Go button
        go_btn = page.query_selector('[item-i-d="go-to-modal-go-button"]')
        if go_btn:
            go_btn.click()
            log.info("Clicked Go button")
        else:
            page.keyboard.press("Enter")

        time.sleep(3)
        final = _get_reader_page_num(page)
        log.info(f"Now on page {final}")
        print(f"At page {final}", file=sys.stderr)
    except Exception as e:
        log.warning(f"Failed to navigate to start: {e}")


def _set_single_column(page: Page) -> None:
    """Switch the Kindle reader to single-column layout via Reader Settings."""
    try:
        # Open Reader Settings panel
        settings_btn = page.query_selector('ion-button[aria-label="Reader settings"]')
        if not settings_btn:
            log.warning("Reader settings button not found")
            return

        settings_btn.click()
        time.sleep(1)

        # Click "Single Column" option
        single_col = page.query_selector('#columns-1, .column-item--1')
        if single_col:
            log.info("Switching to single-column layout")
            single_col.click()
            time.sleep(1)
        else:
            log.warning("Single column option not found in settings")

        # Close settings panel
        close_btn = page.query_selector('.side-menu-close-button')
        if close_btn:
            close_btn.click()
        else:
            page.keyboard.press("Escape")
        time.sleep(1)
    except Exception as e:
        log.warning(f"Failed to set single column: {e}")


def _dismiss_cookie_popup(page: Page) -> None:
    """Dismiss any cookie consent popup that may obscure the reader.

    Amazon's Kindle reader cookie banner renders in a way that's not easily
    selectable via DOM queries. The X (close) button is in the bottom-right
    area of the viewport. We click it directly by coordinates.
    """
    try:
        # First try standard selectors
        for sel in ['#sp-cc-accept', '[data-action="sp-cc-accept"]']:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    log.info(f"Dismissing cookie popup via: {sel}")
                    btn.click()
                    time.sleep(1)
                    return
            except Exception:
                continue

        # Click the X button area (bottom-right of viewport)
        # The banner's close button is typically near viewport_width - 32, viewport_height - 168
        viewport = page.viewport_size
        if viewport:
            x = viewport["width"] - 32
            y = viewport["height"] - 168
            log.info(f"Clicking cookie dismiss at ({x}, {y})")
            page.mouse.click(x, y)
            time.sleep(1)
    except Exception as e:
        log.debug(f"Cookie popup dismissal failed: {e}")


def _get_reader_page_num(page: Page) -> int:
    """Extract the current page number from the Kindle reader footer."""
    try:
        info = page.evaluate("""() => {
            const el = document.querySelector('.footer-label-color-default, [class*="footer-label"]');
            return el ? el.innerText : '';
        }""")
        if "Page" in info and "of" in info:
            # "Page 2 of 452 ● 0% ..."
            return int(info.split("Page")[1].split("of")[0].strip())
    except Exception:
        pass
    return 0


def _extract_via_screenshot(page: Page, page_number: int, images_dir: Path) -> tuple[PageContent, bytes]:
    """Extract content from the current page via screenshot + OCR.

    Screenshots the #kr-renderer element directly to avoid capturing
    the reader header, footer, and sidebar chrome.

    Returns (PageContent, raw_screenshot_bytes) so callers can use the
    screenshot hash for change detection.
    """
    images_dir.mkdir(parents=True, exist_ok=True)

    # Target the renderer element to exclude UI chrome (header, footer, sidebar)
    renderer = page.query_selector("#kr-renderer")
    if renderer:
        screenshot = renderer.screenshot()
        log.debug("Screenshot taken of #kr-renderer element")
    else:
        # Fallback: hide header/footer via CSS, then screenshot
        page.evaluate("""() => {
            const header = document.querySelector('#reader-header');
            const footer = document.querySelector('.footer-label-color-default');
            const menu = document.querySelector('ion-menu');
            if (header) header.style.display = 'none';
            if (footer) footer.style.display = 'none';
            if (menu) menu.style.display = 'none';
        }""")
        screenshot = page.screenshot()
        # Restore
        page.evaluate("""() => {
            const header = document.querySelector('#reader-header');
            const footer = document.querySelector('.footer-label-color-default');
            const menu = document.querySelector('ion-menu');
            if (header) header.style.display = '';
            if (footer) footer.style.display = '';
            if (menu) menu.style.display = '';
        }""")
        log.debug("Screenshot taken of full page (renderer not found)")

    text = ocr_screenshot(screenshot)

    # Save the screenshot
    img_path = images_dir / f"page-{page_number:04d}.png"
    img_path.write_bytes(screenshot)

    return PageContent(
        text=text,
        images=[f"images/page-{page_number:04d}.png"],
        chapter_heading=None,  # Don't detect chapters from UI chrome
        page_number=page_number,
    ), screenshot
