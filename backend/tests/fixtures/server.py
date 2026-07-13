"""
server.py — local stdlib HTTP server backing crawler/detector tests.

No real internet, no new dependency: serves static fixture HTML straight
off disk (from fixtures/detector_pages/ and fixtures/crawler_site/) plus a
/slow endpoint that sleeps past a caller-tunable delay, used to exercise
crawler.py's real Playwright navigation-timeout handling, and (Phase 4.6)
/blocked_403 /blocked_429 /blocked_503 /challenge_page routes used to
exercise crawler.py's bot-blocking detection. One server backs both
detector and crawler tests — one piece of test infra, not two.
"""
import http.server
import socket
import threading
import time
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent
SLOW_DELAY_S = 3.0

# Phase 4.6: synthetic routes for bot-blocking tests. Inline (not fixture
# files) since the content itself is test-only, same pattern as /slow.
_BLOCKED_STATUS_ROUTES = {
    "/blocked_403": 403,
    "/blocked_429": 429,
    "/blocked_503": 503,
}
_CHALLENGE_PAGE_HTML = (
    b"<!DOCTYPE html><html lang=\"en\"><head><title>Just a moment...</title>"
    b"</head><body>Checking your browser before accessing this site."
    b' <a href="/crawler_site/page_a.html">link</a></body></html>'
)


class _FixtureHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass  # keep pytest output focused on assertions, not access logs

    def do_GET(self):
        if self.path == "/slow":
            time.sleep(SLOW_DELAY_S)
            self._respond(b"<!DOCTYPE html><html lang=\"en\"><body>slow</body></html>")
            return

        if self.path in _BLOCKED_STATUS_ROUTES:
            status = _BLOCKED_STATUS_ROUTES[self.path]
            self._respond(f"blocked (status {status})".encode(), status=status)
            return

        if self.path == "/challenge_page":
            self._respond(_CHALLENGE_PAGE_HTML)
            return

        rel_path = self.path.split("?")[0].lstrip("/")
        candidate = (FIXTURES_DIR / rel_path).resolve()
        try:
            candidate.relative_to(FIXTURES_DIR.resolve())
        except ValueError:
            self.send_error(404)
            return

        if not candidate.is_file():
            self.send_error(404)
            return

        self._respond(candidate.read_bytes())

    def _respond(self, body: bytes, status: int = 200) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            # Expected for /slow: the client (Playwright, on a short
            # navigation timeout) gives up and closes the socket before the
            # handler finishes sleeping past the delay. Not a real failure.
            pass


class TestHTTPServer:
    """Session-scoped local server. Binds 127.0.0.1:0 (OS-assigned free
    port) so parallel test runs never collide on a fixed port."""

    def __init__(self) -> None:
        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
        self.port = self._httpd.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


def find_unused_port() -> int:
    """Binds an ephemeral port and immediately releases it, for
    connection-refused tests — nothing ever listens on the returned port,
    so a real Playwright connection-refused error is guaranteed."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
