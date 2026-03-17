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
