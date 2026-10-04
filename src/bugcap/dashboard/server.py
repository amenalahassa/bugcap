"""Local dashboard server: standard-library HTTP, loopback only by default.

Protections: Host and Origin checks (DNS rebinding / cross-site), a per-process token on every
write (CSRF), media served by row id with containment checks, a static allowlist, and a CSP
that forbids external origins."""
from __future__ import annotations

import hmac
import json
import re
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import parse_qs, urlparse

from ..errors import ServiceError
from ..store import Store
from . import api
from .media import serve_media

LOOPBACK = ("127.0.0.1", "localhost")
STATIC_ALLOWLIST = {"app.js": "text/javascript", "app.css": "text/css"}
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "media-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
)
MAX_BODY = 1024 * 1024
MUTATING = ("POST", "PUT", "PATCH", "DELETE")
_REPORT = re.compile(r"^/api/reports/(\d+)$")
_REPORT_ACTION = re.compile(r"^/api/reports/(\d+)/(status|tags|notes)$")
_MEDIA = re.compile(r"^/media/(\d+)$")
_FRAME = re.compile(r"^/media/(\d+)/frames/(\d+)$")


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, token: str, exposed: bool = False):
        super().__init__(address, Handler)
        self.token = token
        self.exposed = exposed

    @property
    def port(self) -> int:
        return self.server_address[1]


class Handler(BaseHTTPRequestHandler):
    server: DashboardServer
    server_version = "bugcap"

    def log_message(self, fmt, *args):  # keep the terminal quiet; no tokens in logs
        pass

    # --- response helpers ------------------------------------------------------

    def send_security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("Referrer-Policy", "no-referrer")

    def send_json(self, status: int, payload) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_security_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, exc: ServiceError) -> None:
        self.send_json(api.http_status(exc), exc.as_dict())

    # --- access rules ----------------------------------------------------------

    def _allowed_origins(self) -> set:
        port = self.server.port
        return {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    def _check_access(self) -> bool:
        host = self.headers.get("Host", "")
        if not self.server.exposed and host not in {f"127.0.0.1:{self.server.port}", f"localhost:{self.server.port}"}:
            self.send_json(400, {"code": "bad_host", "message": "unexpected Host header"})
            return False
        origin = self.headers.get("Origin")
        if origin is not None:
            allowed = self._allowed_origins() | ({f"http://{host}"} if self.server.exposed else set())
            if origin not in allowed:
                self.send_json(403, {"code": "bad_origin", "message": "cross-origin request refused"})
                return False
        if self.command in MUTATING:
            sent = self.headers.get("X-Bugcap-Token", "")
            if not hmac.compare_digest(sent.encode(), self.server.token.encode()):
                self._error(ServiceError("bad_token", "missing or wrong X-Bugcap-Token"))
                return False
        return True

    # --- routing ---------------------------------------------------------------

    def _dispatch(self) -> None:
        if not self._check_access():
            return
        parsed = urlparse(self.path)
        path, query = parsed.path, parse_qs(parsed.query)
        try:
            self._route(path, query)
        except ServiceError as exc:
            self._error(exc)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:  # never leak internals
            self.send_json(500, {"code": "internal", "message": "internal error"})

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _dispatch

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if not 0 < length <= MAX_BODY:
            raise ServiceError("bad_query", "a JSON body is required")
        try:
            data = json.loads(self.rfile.read(length))
        except ValueError:
            raise ServiceError("bad_query", "body is not valid JSON")
        if not isinstance(data, dict):
            raise ServiceError("bad_query", "body must be a JSON object")
        return data

    def _route(self, path: str, query: dict) -> None:
        method = self.command
        if method == "GET":
            if path == "/":
                return self._static("index.html", "text/html; charset=utf-8")
            if path.startswith("/static/") and path[len("/static/"):] in STATIC_ALLOWLIST:
                name = path[len("/static/"):]
                return self._static(name, STATIC_ALLOWLIST[name] + "; charset=utf-8")
            if path == "/api/session":
                return self.send_json(200, {"token": self.server.token})
            if path == "/api/reports":
                with Store() as store:
                    return self.send_json(200, api.list_reports(store, query))
            match = _REPORT.match(path)
            if match:
                with Store() as store:
                    return self.send_json(200, api.get_report(store, int(match.group(1))))
            match = _MEDIA.match(path)
            if match:
                return self._media(int(match.group(1)), None)
            match = _FRAME.match(path)
            if match:
                return self._media(int(match.group(1)), int(match.group(2)))
        else:
            match = _REPORT_ACTION.match(path)
            handlers = {("POST", "status"): api.set_status, ("POST", "tags"): api.set_tags,
                        ("PUT", "notes"): api.set_notes}
            if match and (method, match.group(2)) in handlers:
                body = self._body()
                with Store() as store:
                    return self.send_json(200, handlers[(method, match.group(2))](store, int(match.group(1)), body))
        self.send_json(404, {"code": "not_found", "message": "no such route"})

    def _static(self, name: str, content_type: str) -> None:
        data = (resources.files("bugcap.dashboard") / "static" / name).read_bytes()
        self.send_response(200)
        self.send_security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _media(self, media_id: int, frame_no) -> None:
        with Store() as store:
            media = store.get_media(media_id)
        if media is None:
            return self.send_json(404, {"code": "not_found", "message": "media not found"})
        if frame_no is None:
            if media.kind == "frames" or not media.path:
                return self.send_json(404, {"code": "not_found", "message": "media not found"})
            return serve_media(self, media.path, media.mime, self.headers.get("Range"))
        frame = next((f for f in media.frames if f.frame_no == frame_no), None)
        if frame is None:
            return self.send_json(404, {"code": "not_found", "message": "frame not found"})
        serve_media(self, frame.path, media.mime, self.headers.get("Range"))


def make_server(host: str = "127.0.0.1", port: int = 8765, token: str | None = None,
                explicit_host: bool = False) -> DashboardServer:
    """Bind the server (not yet serving). Non-loopback hosts need `explicit_host=True`."""
    if host not in LOOPBACK and not explicit_host:
        raise ValueError(f"refusing to bind {host}: the dashboard is local-only unless --host is given")
    return DashboardServer((host, port), token or secrets.token_urlsafe(32), exposed=host not in LOOPBACK)


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False,
          explicit_host: bool = False) -> None:
    server = make_server(host, port, explicit_host=explicit_host)
    shown = "127.0.0.1" if host in LOOPBACK else host
    url = f"http://{shown}:{server.port}/"
    print(f"bugcap dashboard: {url}  (Ctrl+C to stop)", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("", file=sys.stderr)
    finally:
        server.server_close()
