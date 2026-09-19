"""Tiny web relay for LoopHole. Standard library only -- no new dependency.

It streams a run log (runs/<case>.jsonl, or a fixture) to the browser over
Server-Sent Events, so the room can watch attempts, candidates and the
confirmed bypass in a browser instead of a terminal. It is a *viewer*: it never
calls the model and never writes the log -- the loop still produces the log.
That keeps the web layer safe to leave running and keyless.

Run:
    .venv/bin/python web/server.py
    # then open http://127.0.0.1:8000
    # stream a different log:  http://127.0.0.1:8000/?log=runs/path_traversal.jsonl
"""

import http.server
import os
import time
import urllib.parse

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(ROOT)
DEFAULT_LOG = "demo/fixtures/path_traversal.jsonl"


def _safe_log_path(rel: str):
    """Resolve `rel` under the repo, refuse anything that escapes it or isn't a
    .jsonl file. (Fitting, given what this project is about.)"""
    candidate = os.path.realpath(os.path.join(REPO, rel))
    repo_root = os.path.realpath(REPO) + os.sep
    if not candidate.startswith(repo_root):
        return None
    if not candidate.endswith(".jsonl") or not os.path.isfile(candidate):
        return None
    return candidate


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # quiet

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            self._serve_file(os.path.join(ROOT, "index.html"), "text/html")
        elif parsed.path == "/events":
            self._stream_events(parsed)
        else:
            self.send_error(404)

    def _serve_file(self, path, content_type):
        with open(path, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream_events(self, parsed):
        qs = urllib.parse.parse_qs(parsed.query)
        rel = qs.get("log", [DEFAULT_LOG])[0]
        speed = qs.get("speed", ["1"])[0]
        try:
            delay = max(0.0, 0.6 / float(speed))
        except ValueError:
            delay = 0.6

        path = _safe_log_path(rel)
        if path is None:
            self.send_error(404, "log not found")
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    self.wfile.write(f"data: {line}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    time.sleep(delay)
            self.wfile.write(b"event: end\ndata: {}\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # browser closed the tab


def main(port: int = 8000):
    # Bind to localhost only -- do not expose this on a network.
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"LoopHole web relay on http://127.0.0.1:{port}  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", "8000"))
    main(port)
