import http.server
import threading
import pytest
from kindle_to_md.browser import BrowserDriver


class _HelloHandler(http.server.BaseHTTPRequestHandler):
    """Minimal HTTP handler that serves a static hello page."""

    def do_GET(self):
        body = b"<h1>hello</h1>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence request logging in test output
        pass


@pytest.fixture(scope="module")
def hello_server():
    """Start a local HTTP server on a free port and yield its base URL."""
    server = http.server.HTTPServer(("127.0.0.1", 0), _HelloHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}/"
    server.shutdown()


def test_lightpanda_launch_creates_page(tmp_path, hello_server):
    """Lightpanda backend should launch and return a connectable CDP endpoint."""
    driver = BrowserDriver(backend="lightpanda", session_dir=tmp_path / "sessions")
    try:
        page = driver.launch()
        assert page is not None
        page.goto(hello_server)
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
