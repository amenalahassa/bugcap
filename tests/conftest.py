"""Shared pytest fixtures: BUGCAP_HOME isolation, throwaway git repos, a fake `gh`."""
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Optional

import pytest


@pytest.fixture
def bugcap_home(tmp_path, monkeypatch):
    """Point bugcap's data/config at a temp dir and clear XDG/platform env leakage."""
    home = tmp_path / "bugcap_home"
    monkeypatch.setenv("BUGCAP_HOME", str(home))
    # Don't pick up a .bugcap.toml from wherever pytest was started.
    monkeypatch.chdir(tmp_path)
    for var in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_SESSION_TYPE", "LOCALAPPDATA", "APPDATA"):
        monkeypatch.delenv(var, raising=False)
    return home


@pytest.fixture
def git_repo(tmp_path):
    """Factory for a temp git repo, optionally with an `origin` remote."""
    def _make(name: str = "proj", origin: Optional[str] = None) -> Path:
        root = tmp_path / name
        root.mkdir()
        env = {"GIT_CONFIG_NOSYSTEM": "1", "HOME": str(tmp_path)}
        subprocess.run(["git", "init", "-q"], cwd=root, check=True, env={**_base_env(), **env})
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True, env=_base_env())
        subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True, env=_base_env())
        if origin:
            subprocess.run(["git", "remote", "add", "origin", origin], cwd=root, check=True, env=_base_env())
        return root
    return _make


def _base_env() -> dict:
    import os
    return dict(os.environ)


@dataclass
class _Call:
    argv: list
    stdin: Optional[str]


@dataclass
class FakeGh:
    """Records `gh` invocations and returns scripted results.

    `responses` maps a predicate over argv to a CompletedProcess-like result.
    `which` controls whether `gh` (and other binaries) appear on PATH.
    """
    calls: list = field(default_factory=list)
    _handlers: list = field(default_factory=list)
    present: set = field(default_factory=lambda: {"gh"})

    def add(self, match: Callable[[list], bool], returncode: int = 0, stdout: str = "", stderr: str = ""):
        self._handlers.append((match, returncode, stdout, stderr))
        return self

    def on(self, *tokens: str, returncode: int = 0, stdout: str = "", stderr: str = ""):
        """Match when every token appears as (a substring of) some argv element.

        This matches both standalone flags (e.g. "--repo") and tokens embedded in a
        single element (e.g. "contents" inside the `gh api repos/o/r/contents/...` path).
        """
        toks = list(tokens)
        return self.add(
            lambda argv: all(any(t in elem for elem in argv) for t in toks),
            returncode,
            stdout,
            stderr,
        )

    def run(self, argv, *args, **kwargs):
        stdin = kwargs.get("input")
        self.calls.append(_Call(list(argv), stdin))
        for match, rc, out, err in self._handlers:
            if match(argv):
                return subprocess.CompletedProcess(argv, rc, out, err)
        return subprocess.CompletedProcess(argv, 0, "", "")

    @property
    def argvs(self) -> list:
        return [c.argv for c in self.calls]


@pytest.fixture
def fake_gh(monkeypatch):
    """Install a FakeGh over subprocess.run and shutil.which for the ghcli module."""
    fake = FakeGh()

    def fake_which(name):
        return f"/usr/bin/{name}" if name in fake.present else None

    # Patch where ghcli looks them up.
    import bugcap.ghcli as ghcli  # noqa: F401  (import may create the module lazily)
    monkeypatch.setattr("bugcap.ghcli.subprocess.run", fake.run)
    monkeypatch.setattr("bugcap.ghcli.shutil.which", fake_which)
    return fake


@dataclass
class HttpFixture:
    base: str
    requests: list = field(default_factory=list)  # [(path, headers dict)]

    def url(self, path: str) -> str:
        return self.base + path


@pytest.fixture
def http_server():
    """Local HTTP server for URL-ingestion tests; records request headers."""
    from fixtures.make_images import png_bytes

    fixture = HttpFixture(base="")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, ctype, body, extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            fixture.requests.append((self.path, {k.lower(): v for k, v in self.headers.items()}))
            try:
                if self.path == "/ok.png":
                    self._send(200, "image/png", png_bytes())
                elif self.path == "/page.html":
                    self._send(200, "text/html", b"<html><body>nope</body></html>")
                elif self.path == "/big.png":
                    self._send(200, "image/png", png_bytes() + b"\0" * (2 * 1024 * 1024))
                elif self.path == "/slow":
                    time.sleep(3)
                    self._send(200, "image/png", png_bytes())
                elif self.path == "/redirect-loop":
                    self._send(302, "text/plain", b"", {"Location": "/redirect-loop"})
                elif self.path == "/redirect-file":
                    self._send(302, "text/plain", b"", {"Location": "file:///etc/passwd"})
                elif self.path == "/redirect-ok":
                    self._send(302, "text/plain", b"", {"Location": "/ok.png"})
                else:
                    self._send(404, "text/plain", b"missing")
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    fixture.base = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield fixture
    server.shutdown()
    server.server_close()


# Make `src/` importable without an install when tests run from a checkout.
_src = Path(__file__).resolve().parent.parent / "src"
if _src.is_dir() and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))


@pytest.fixture
def sample_images(tmp_path):
    """Directory holding sample.png/.jpg/.gif/.webp and not-image.txt."""
    from fixtures.make_images import write_all

    directory = tmp_path / "samples"
    write_all(directory)
    return directory


@pytest.fixture
def dashboard(bugcap_home):
    """A running in-process dashboard on a free port; `call(method, path, ...)` returns
    (status, headers, body-bytes)."""
    import http.client
    import json as _json

    from bugcap.dashboard.server import make_server

    server = make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    class Client:
        pass

    client = Client()
    client.server, client.token, client.port = server, server.token, server.port

    def call(method, path, body=None, headers=None, token=True, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
        hdrs = {"Host": host or f"127.0.0.1:{server.port}"}
        if token and method != "GET":
            hdrs["X-Bugcap-Token"] = server.token
        hdrs.update(headers or {})
        data = None
        if body is not None:
            data = _json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        raw = resp.read()
        out = (resp.status, {k.lower(): v for k, v in resp.getheaders()}, raw)
        conn.close()
        return out

    def jcall(*a, **k):
        status, headers, raw = call(*a, **k)
        return status, _json.loads(raw) if raw else None

    client.call, client.json = call, jcall
    yield client
    server.shutdown()
    server.server_close()


@pytest.fixture(autouse=True)
def _no_real_github(monkeypatch):
    """Tests never reach GitHub: online verification reports "unavailable" unless a test
    installs its own fake."""
    import bugcap.ghcli as ghcli

    if not hasattr(ghcli, "verify_repo_real"):
        ghcli.verify_repo_real = ghcli.verify_repo  # for tests of the real function

    def unavailable(*args, **kwargs):
        raise ghcli.GhUnavailable("offline in tests")

    monkeypatch.setattr(ghcli, "verify_repo", unavailable)
