"""Server lifecycle for HTTP-based assignments.

Spawns a student's `uvicorn main:app` in their venv, waits for it to bind,
yields a stdlib-only HTTP Client, and tears down on context exit. Used by
both bronze and silver checks for any assignment whose contract is over HTTP.

Stdlib-only on the client side intentionally — keeps the harness env
independent of httpx (which would otherwise need to be installed everywhere
the harness runs).
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .runner import Runner


@dataclass
class Response:
    status: int
    headers: dict
    body: bytes = b""
    error: str = ""

    def json(self):
        if not self.body:
            return None
        try:
            return json.loads(self.body.decode("utf-8"))
        except Exception:
            return None


class Client:
    """Stdlib HTTP client with `get/post/patch/delete/put` helpers."""

    def __init__(self, base_url: str, timeout: float = 5.0):
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, *,
                 json_body=None, headers=None, params=None) -> Response:
        url = self.base + path
        if params:
            from urllib.parse import urlencode
            url = url + ("&" if "?" in url else "?") + urlencode(params)
        data = None
        h = {"Accept": "application/json"}
        if headers:
            h.update(headers)
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return Response(status=resp.status,
                                headers=dict(resp.headers),
                                body=resp.read())
        except urllib.error.HTTPError as e:
            return Response(status=e.code,
                            headers=dict(e.headers or {}),
                            body=e.read() or b"")
        except Exception as e:
            return Response(status=0, headers={}, error=str(e))

    def get(self, path, params=None, headers=None):
        return self._request("GET", path, params=params, headers=headers)

    def post(self, path, json_body=None, headers=None):
        return self._request("POST", path, json_body=json_body, headers=headers)

    def patch(self, path, json_body=None, headers=None):
        return self._request("PATCH", path, json_body=json_body, headers=headers)

    def put(self, path, json_body=None, headers=None):
        return self._request("PUT", path, json_body=json_body, headers=headers)

    def delete(self, path, headers=None):
        return self._request("DELETE", path, headers=headers)


@dataclass
class ServerHandle:
    proc: subprocess.Popen | None = None
    port: int = 0
    base: str = ""
    started: bool = False
    startup_log: str = ""
    error: str = ""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _purge_dbs(work: Path) -> None:
    """Wipe any sqlite db so server starts with a fresh schema."""
    for pat in ("*.db", "*.db-journal", "*.sqlite", "*.sqlite3"):
        for p in work.rglob(pat):
            if "__pycache__" in p.parts:
                continue
            try:
                p.unlink()
            except Exception:
                pass


def _start(runner: Runner, work: Path, timeout: float = 20.0) -> ServerHandle:
    sh = ServerHandle()
    if not (work / "main.py").exists():
        sh.error = "main.py not found at submission root"
        return sh

    _purge_dbs(work)

    port = _free_port()
    sh.port = port
    sh.base = f"http://127.0.0.1:{port}"

    cmd = [str(runner.python), "-m", "uvicorn", "main:app",
           "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"]
    sh.proc = subprocess.Popen(
        cmd, cwd=str(work),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={**os.environ, "PYTHONIOENCODING": "utf-8",
             "PYTHONDONTWRITEBYTECODE": "1"},
    )

    deadline = time.time() + timeout
    last_err = ""
    while time.time() < deadline:
        if sh.proc.poll() is not None:
            try:
                _, err = sh.proc.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                err = b""
            sh.startup_log = (err or b"").decode("utf-8", errors="replace")[-1500:]
            sh.error = "uvicorn process exited during startup"
            return sh

        for probe in ("/docs", "/openapi.json", "/users"):
            try:
                with urllib.request.urlopen(f"{sh.base}{probe}", timeout=0.5) as r:
                    if r.status < 500:
                        sh.started = True
                        return sh
            except urllib.error.HTTPError as e:
                if e.code < 500:
                    sh.started = True
                    return sh
                last_err = f"HTTP {e.code} on {probe}"
            except Exception as e:
                last_err = str(e)
        time.sleep(0.3)

    sh.error = f"server did not respond within {timeout}s ({last_err})"
    _stop(sh)
    return sh


def _stop(sh: ServerHandle) -> None:
    if sh.proc and sh.proc.poll() is None:
        try:
            sh.proc.terminate()
            try:
                sh.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                sh.proc.kill()
                sh.proc.wait(timeout=2)
        except Exception:
            pass
    if sh.proc:
        try:
            _, err = sh.proc.communicate(timeout=1)
            tail = (err or b"").decode("utf-8", errors="replace")[-800:]
            if tail and not sh.startup_log:
                sh.startup_log = tail
        except Exception:
            pass


class ServerStartFailure(RuntimeError):
    """Raised when the student's server can't be brought up."""
    def __init__(self, sh: ServerHandle):
        self.handle = sh
        msg = sh.error or "server failed to start"
        if sh.startup_log:
            msg += f" | tail: {sh.startup_log[-300:]!r}"
        super().__init__(msg)


@contextmanager
def spawn_server(runner: Runner, work: Path,
                 timeout: float = 20.0) -> Iterator[Client]:
    """Yield a Client connected to the student's running uvicorn.

    On startup failure, raises ServerStartFailure with the ServerHandle
    attached so callers can decide whether to mark every check as error.
    """
    sh = _start(runner, work, timeout=timeout)
    if not sh.started:
        _stop(sh)
        raise ServerStartFailure(sh)
    try:
        yield Client(sh.base)
    finally:
        _stop(sh)
