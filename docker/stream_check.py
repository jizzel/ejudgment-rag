"""Proxy streaming check (standard library only; used by scripts/check_proxy_stream.sh).

    python stream_check.py serve            the stand-in for the UI behind Caddy
    python stream_check.py check BASE_URL   the client: asserts how Caddy passes the stream on

The stand-in answers ``POST /api/chat`` like the real answer stream: server-sent events
spread over time (a first event at once, more 2 s apart). With ``?silent=1`` it sends one event
and then nothing at all, as the real stream does while the model drafts, and only watches its
socket: it logs "upstream closed" when the proxy closes the connection (a reader who left must
cancel the answer even then). ``GET /`` is a page large enough to be compressed. No models,
database or Ollama are involved. STAND_IN_DEAF=1 makes it never notice a close (to prove the
check fails then).
"""

import http.client
import http.server
import os
import select
import sys
import time
from urllib.parse import urlsplit

PAGE = ("<!doctype html><title>stand-in</title>" + "<p>filler for compression</p>" * 150).encode()
FIRST_EVENT_WITHIN = 1.0  # seconds
GAP = 2.0  # seconds between events


class StandIn(http.server.BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # quiet
        pass

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(PAGE)))
        self.end_headers()
        self.wfile.write(PAGE)

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("content-length") or 0))
        if self.path.split("?")[0] != "/api/chat":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("content-type", "text/event-stream; charset=utf-8")
        # ?bare=1 leaves out the hints the UI sends, so the proxy is checked on its own.
        if "bare=1" not in self.path:
            self.send_header("cache-control", "no-cache, no-transform")
            self.send_header("x-accel-buffering", "no")
        self.end_headers()  # HTTP/1.0: the body ends when the connection closes
        if "silent=1" in self.path:
            self._silent()
            return
        try:
            for n in range(1, 4):
                event = f'event: stage\ndata: {{"type": "stage", "n": {n}}}\n\n'
                self.wfile.write(event.encode())
                self.wfile.flush()
                time.sleep(GAP)
            self.wfile.write(b'event: answer\ndata: {"type": "answer"}\n\n')
            print("stream complete", flush=True)
        except (BrokenPipeError, ConnectionResetError):
            print("client disconnected", flush=True)

    def _silent(self) -> None:
        """One event, then silence: only the proxy closing the connection ends it."""
        self.wfile.write(b'event: stage\ndata: {"type": "stage", "stage": "drafting"}\n\n')
        self.wfile.flush()
        started = time.monotonic()
        deaf = os.environ.get("STAND_IN_DEAF") == "1"
        while time.monotonic() - started < 30:
            readable, _, _ = select.select([self.connection], [], [], 0.1)
            if not readable or deaf:
                continue
            try:
                closed = self.connection.recv(1) == b""
            except OSError:
                closed = True
            if closed:
                print(f"upstream closed after {time.monotonic() - started:.1f} s", flush=True)
                return
        print("upstream still open after 30 s", flush=True)


def serve() -> None:
    http.server.ThreadingHTTPServer(("0.0.0.0", 3000), StandIn).serve_forever()


def _connect(base: str) -> http.client.HTTPConnection:
    parts = urlsplit(base)
    return http.client.HTTPConnection(parts.hostname or "127.0.0.1", parts.port or 80, timeout=6)


def check(base: str) -> None:
    failures: list[str] = []
    # 1. The stream: not compressed, and each event arrives when it is sent; both with the
    # UI's no-transform hints and without them (the proxy must not depend on them).
    for path in ("/api/chat", "/api/chat?bare=1"):
        failures += _check_stream(base, path)
    _check_page(base, failures)
    if failures:
        print("FAIL:\n  " + "\n  ".join(failures))
        sys.exit(1)
    print("ok: events stream unbuffered and uncompressed; pages compressed; headers set")


def _check_stream(base: str, path: str) -> list[str]:
    failures: list[str] = []
    conn = _connect(base)
    started = time.monotonic()
    conn.request(
        "POST",
        path,
        body=b'{"question": "q"}',
        headers={"content-type": "application/json", "accept-encoding": "gzip, zstd"},
    )
    response = conn.getresponse()
    if response.status != 200:
        failures.append(f"stream status {response.status}")
    if response.getheader("content-encoding"):
        failures.append(f"stream is compressed ({response.getheader('content-encoding')})")
    if response.getheader("x-content-type-options") != "nosniff":
        failures.append("stream lacks the security headers")
    arrivals: list[float] = []
    try:
        while len(arrivals) < 2:
            line = response.fp.readline()
            if not line:
                break
            if line.startswith(b"event:"):
                arrivals.append(time.monotonic() - started)
    except TimeoutError:
        pass  # nothing arrived in time: reported below
    conn.close()
    print(f"{path}: events arrived at", ", ".join(f"{t:.2f} s" for t in arrivals) or "never")
    if not arrivals or arrivals[0] > FIRST_EVENT_WITHIN:
        first = arrivals[:1] or "never"
        failures.append(f"{path}: first event held back ({first}; limit {FIRST_EVENT_WITHIN} s)")
    elif len(arrivals) < 2 or arrivals[1] - arrivals[0] < GAP * 0.75:
        failures.append(f"{path}: events not spread over time: {arrivals}")
    return failures


def _check_page(base: str, failures: list[str]) -> None:
    """Pages are still compressed, with the security headers."""
    conn = _connect(base)
    conn.request("GET", "/", headers={"accept-encoding": "gzip"})
    page = conn.getresponse()
    page.read()
    conn.close()
    if page.getheader("content-encoding") != "gzip":
        encoding = page.getheader("content-encoding")
        failures.append(f"pages are not compressed (content-encoding={encoding})")
    if page.getheader("x-content-type-options") != "nosniff":
        failures.append("pages lack the security headers")


def cancel(base: str) -> None:
    """Open a stream that then goes silent, read its first event, and go away (as Cancel does
    while the model drafts and nothing is being sent)."""
    conn = _connect(base)
    try:
        conn.request(
            "POST", "/api/chat?silent=1", body=b"{}", headers={"content-type": "application/json"}
        )
        response = conn.getresponse()
    except (http.client.HTTPException, OSError) as exc:
        sys.exit(f"FAIL: cancel step: no response ({exc!r})")
    if response.status != 200:
        sys.exit(f"FAIL: cancel step: the stream answered {response.status}, not 200")
    try:
        while True:
            line = response.fp.readline()
            if not line:  # the end of the stream: readline() would return b"" forever
                sys.exit("FAIL: cancel step: the stream ended before its first event")
            if line.startswith(b"event:"):
                break
    except TimeoutError:
        sys.exit("FAIL: cancel step: no event arrived in time")
    conn.sock.close()  # type: ignore[union-attr]
    conn.close()
    print("closed the stream after the first event")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if command == "serve":
        serve()
    elif command == "check":
        check(sys.argv[2])
    elif command == "cancel":
        cancel(sys.argv[2])
    else:
        sys.exit(f"unknown command {command}")
