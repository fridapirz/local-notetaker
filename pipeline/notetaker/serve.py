"""notetaker serve: the meetings page on http://127.0.0.1:<port>/, so action items can be ticked.

Started by the menu bar app. Binds to loopback only. Two guards keep other web pages out:
- the Host header must be 127.0.0.1/localhost on this port (blocks DNS rebinding reads of the notes);
- POST needs a JSON body and an X-Notetaker header, which a cross-site page can't send without a CORS
  preflight that this server never approves (blocks CSRF ticks).
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlparse

FOLDER = re.compile(r"^\d{4}-\d{2}-\d{2} \d{4}( – .+)?$")
LOCK = threading.Lock()  # one writer at a time for notes.md / index.html


def make_handler(notes_dir: Path, port: int, rebuild: Callable[[], Path]) -> type[BaseHTTPRequestHandler]:
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    root = notes_dir.resolve()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quiet; the app doesn't read it
            pass

        def send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, code: int, obj: dict) -> None:
            self.send(code, json.dumps(obj).encode(), "application/json")

        def host_ok(self) -> bool:
            if self.headers.get("Host") in allowed_hosts:
                return True
            self.send_json(403, {"error": "forbidden host"})
            return False

        def do_GET(self):
            if not self.host_ok():
                return
            path = unquote(urlparse(self.path).path)
            if path in ("/", "/index.html"):
                with LOCK:
                    page = rebuild().read_bytes()  # always fresh: new meetings and ticks show on reload
            else:
                target = (root / path.lstrip("/")).resolve()
                if root not in target.parents or target.suffix != ".html" or not target.is_file():
                    self.send(404, b"Not found", "text/plain")
                    return
                if target.name == "notes.html" and (target.parent / "notes.md").is_file():
                    from .html import render
                    with LOCK:
                        page = render(target.parent).read_bytes()  # fresh sidebar and ticks
                else:
                    page = target.read_bytes()
            self.send(200, page, "text/html; charset=utf-8")

        def do_POST(self):
            if not self.host_ok():
                return
            if (urlparse(self.path).path != "/api/done" or self.headers.get("X-Notetaker") != "1"
                    or not self.headers.get("Content-Type", "").startswith("application/json")):
                self.send_json(403, {"error": "forbidden"})
                return
            try:
                req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                folder, item, done = str(req["folder"]), str(req["id"]), bool(req["done"])
            except (ValueError, KeyError, TypeError):
                self.send_json(400, {"error": "bad request"})
                return
            session = root / folder
            if not FOLDER.match(folder) or not (session / "notes.md").is_file():
                self.send_json(404, {"error": "meeting not found"})
                return
            from .actions import set_done
            from .html import render
            with LOCK:
                result = set_done(session, item, done)
                if result:
                    render(session)
                    rebuild()
            if not result:
                self.send_json(404, {"error": "item not found; reload the page"})
                return
            self.send_json(200, result)

    return Handler


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def exit_with_app(server: ThreadingHTTPServer, app_pid: int | None) -> None:
    """Stop when the app is gone, even if it was killed (`uv run` sits between us, so watch the app's pid)."""
    parent = os.getppid()
    while True:
        time.sleep(3)
        if (app_pid and not alive(app_pid)) or (not app_pid and os.getppid() != parent):
            server.shutdown()
            return


def bind(notes_dir: Path, port: int, rebuild: Callable[[], Path]) -> ThreadingHTTPServer:
    """A server from the previous app run may still be shutting down: retry for a few seconds."""
    for attempt in range(8):
        try:
            return ThreadingHTTPServer(("127.0.0.1", port), make_handler(notes_dir, port, rebuild))
        except OSError:
            if attempt == 7:
                raise
            time.sleep(2)
    raise RuntimeError("unreachable")


def serve(notes_dir: Path, port: int, rebuild: Callable[[], Path], app_pid: int | None = None) -> None:
    server = bind(notes_dir, port, rebuild)
    threading.Thread(target=exit_with_app, args=(server, app_pid), daemon=True).start()
    print(f"Serving {notes_dir} on http://127.0.0.1:{port}/", flush=True)
    server.serve_forever()
