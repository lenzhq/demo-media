"""Local preview server with Firebase-parity 404s.

``python -m http.server`` shows its own white error page on misses; Firebase
Hosting serves our branded ``404.html``. This thin wrapper closes that gap so
local demos look like production. Usage: ``make serve`` (or
``python scripts/serve.py [port] [dir]``).
"""

from __future__ import annotations

import contextlib
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class NotFoundAwareHandler(SimpleHTTPRequestHandler):
    def send_error(self, code: int, message=None, explain=None):  # noqa: N802
        if code == 404:
            page = Path(self.directory) / "404.html"
            if page.is_file():
                body = page.read_bytes()
                self.send_response(404)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                with contextlib.suppress(BrokenPipeError):
                    self.wfile.write(body)
                return
        super().send_error(code, message, explain)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    directory = sys.argv[2] if len(sys.argv) > 2 else "dist"
    handler = partial(NotFoundAwareHandler, directory=directory)
    print(f"Serving {directory}/ at http://localhost:{port} (branded 404s)")
    ThreadingHTTPServer(("", port), handler).serve_forever()


if __name__ == "__main__":
    main()
