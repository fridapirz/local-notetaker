"""notetaker serve: the meetings page on http://127.0.0.1:<port>/, so action items can be ticked.

Started by the menu bar app. Binds to loopback only. Two guards keep other web pages out:
- the Host header must be 127.0.0.1/localhost on this port (blocks DNS rebinding reads of the notes);
- POST (/api/done, /api/order) needs a JSON body and an X-Notetaker header, which a cross-site page can't send without a CORS
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
            from .html import CSP
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
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
            from .html import index_page, meeting_page
            path = unquote(urlparse(self.path).path)
            if path in ("/", "/index.html"):
                with LOCK:
                    page = index_page(root).encode()  # always fresh: new meetings and ticks show on reload
            else:
                target = (root / path.lstrip("/")).resolve()
                if root not in target.parents or target.suffix != ".html" or not target.is_file():
                    self.send(404, b"Not found", "text/plain")
                    return
                if target.name == "notes.html" and (target.parent / "notes.md").is_file():
                    with LOCK:
                        page = meeting_page(target.parent).encode()  # fresh sidebar and ticks
                else:
                    page = target.read_bytes()
            self.send(200, page, "text/html; charset=utf-8")

        def do_POST(self):
            if not self.host_ok():
                return
            path = urlparse(self.path).path
            if (path not in ("/api/done", "/api/order") or self.headers.get("X-Notetaker") != "1"
                    or not self.headers.get("Content-Type", "").startswith("application/json")):
                self.send_json(403, {"error": "forbidden"})
                return
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length > 512_000:
                self.send_json(413, {"error": "too large"})
                return
            if path == "/api/order":
                self.post_order(length)
                return
            try:
                req = json.loads(self.rfile.read(length))
                folder, item, done = str(req["folder"]), str(req["id"]), bool(req["done"])
            except (ValueError, KeyError, TypeError):
                self.send_json(400, {"error": "bad request"})
                return
            session = (root / folder).resolve()
            if not FOLDER.match(folder) or session.parent != root or not (session / "notes.md").is_file():
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

        def post_order(self, length: int) -> None:
            """New priority for some items: {"keys": ["<folder>/<id>", ...]} in their new order."""
            try:
                keys = json.loads(self.rfile.read(length))["keys"]
                if not isinstance(keys, list) or not all(isinstance(k, str) and len(k) < 400 for k in keys):
                    raise TypeError
            except (ValueError, KeyError, TypeError):
                self.send_json(400, {"error": "bad request"})
                return
            from .actions import reorder
            from .html import render, site
            with LOCK:
                ctx = site(root)
                reorder(root, ctx["items"], keys)  # unknown keys are ignored
                folders = {k.rsplit("/", 1)[0] for k in keys}
                fresh = site(root)
                for m in fresh["meetings"]:  # keep the file versions of the touched meetings in order too
                    if Path(m["folder"]).name in folders and m["notes"]:
                        render(Path(m["folder"]), fresh)
                rebuild()
            self.send_json(200, {"ok": True})

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
