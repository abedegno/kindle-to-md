"""Integration test using a fake Kindle reader page."""
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from kindle_to_md.extractor import extract_page_content


def test_extract_from_fake_reader(tmp_path):
    """Full extraction pipeline against a fake reader page."""
    fixture_path = Path(__file__).parent / "fixtures" / "fake_reader.html"
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
            time.sleep(0.3)

        browser.close()

    # Verify extraction
    assert len(pages) == 4
    assert pages[0].chapter_heading is not None
    assert "Chapter 1" in pages[0].chapter_heading
    assert pages[0].has_meaningful_text()
    assert pages[2].chapter_heading is not None
    assert "Chapter 2" in pages[2].chapter_heading
