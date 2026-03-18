import pytest
from kindle_to_md.browser import BrowserDriver


def test_chromium_launch_creates_page(tmp_path):
    """Chromium backend should launch and return a Playwright page."""
    driver = BrowserDriver(session_dir=tmp_path / "sessions")
    try:
        page = driver.launch()
        assert page is not None
        page.goto("data:text/html,<h1>hello</h1>")
        assert "hello" in page.content()
    finally:
        driver.shutdown()
