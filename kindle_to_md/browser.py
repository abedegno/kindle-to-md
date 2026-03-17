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
