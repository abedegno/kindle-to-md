"""Browser driver abstraction — Chromium via Playwright."""

import json
import logging
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

log = logging.getLogger("kindle-to-md")


class BrowserDriver:
    def __init__(
        self,
        session_dir: Path | None = None,
        region: str = "co.uk",
        headed: bool = False,
    ):
        self.session_dir = session_dir or Path.home() / ".kindle-to-md" / "sessions"
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.region = region
        self.headed = headed

        self._playwright = None
        self._browser = None
        self._context = None

    def launch(self) -> Page:
        """Start the browser and return a Playwright Page with saved session loaded."""
        log.info(f"Launching Chromium (headed={self.headed})")
        self._playwright = sync_playwright().start()
        return self._launch_chromium(headed=self.headed)

    def login(self, timeout: int = 300) -> None:
        """Launch Chromium in headed mode for manual Amazon login, then save session."""
        self._playwright = sync_playwright().start()
        page = self._launch_chromium(headed=True)

        # Navigate to the Kindle Cloud Reader — this will redirect to Amazon signin
        login_url = f"https://read.amazon.{self.region}/"
        log.info(f"Navigating to {login_url} (will redirect to login)")
        page.goto(login_url, wait_until="commit")

        # Wait for signin redirect
        log.info("Waiting for signin redirect...")
        try:
            page.wait_for_url(lambda url: "/ap/" in url or "signin" in url, timeout=15000)
            log.info(f"On signin page: {page.url}")
        except Exception:
            log.info(f"No signin redirect, current URL: {page.url}")

        print(
            f"Please log in to Amazon in the browser window.\n"
            f"Once you reach the Kindle library, the browser will close automatically.\n"
            f"Waiting up to {timeout}s...",
            file=sys.stderr,
        )

        # Wait until the browser is on read.amazon (login complete)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                current_url = page.evaluate("window.location.href")
            except Exception:
                current_url = page.url
            log.debug(f"Browser URL: {current_url}")
            if f"read.amazon.{self.region}" in current_url and "/ap/" not in current_url:
                time.sleep(3)
                break
            time.sleep(2)
        else:
            self.shutdown()
            raise TimeoutError("Login timed out. Please try again.")

        print("Login successful. Saving session...", file=sys.stderr)
        self._save_session()
        self.shutdown()

    def _launch_chromium(self, headed: bool = False) -> Page:
        """Launch Chromium via Playwright."""
        log.info(f"Starting Chromium (headless={not headed})")
        self._browser = self._playwright.chromium.launch(headless=not headed)
        # Narrow + tall viewport: forces single-column and reduces page overflow
        context_opts = {
            "viewport": {"width": 600, "height": 1800},
        }
        session_file = self._session_file()
        if session_file.exists():
            log.info(f"Loading session from {session_file}")
            state = json.loads(session_file.read_text())
            log.info(f"Session has {len(state.get('cookies', []))} cookies, "
                      f"{len(state.get('origins', []))} localStorage origins")
            context_opts["storage_state"] = str(session_file)
        else:
            log.info("No session file found, starting fresh context")
        self._context = self._browser.new_context(**context_opts)
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
        """Close browser."""
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
