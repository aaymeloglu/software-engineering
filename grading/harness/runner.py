"""Subprocess runner with per-check timeouts and a per-submission venv."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Strip ANSI CSI sequences (colors, cursor moves) from captured output.
# Students who color their output shouldn't defeat substring or \b-anchored
# regex checks in the bronze harness, and the markdown reports look cleaner
# without raw escape codes in fenced code blocks.
_ANSI_CSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _strip_ansi(s: str) -> str:
    return _ANSI_CSI_RE.sub("", s) if s else s

try:
    import tomllib  # py3.11+
except ImportError:  # pragma: no cover
    tomllib = None


def _parse_pyproject_deps(pyproject: Path) -> list[str]:
    """Pull `[project].dependencies` out of a pyproject.toml. Returns [] on
    any parse error. We intentionally ignore optional-dependencies and
    [dependency-groups] for now — a submission should run on its base deps.
    """
    if tomllib is None:
        return []
    try:
        data = tomllib.loads(pyproject.read_text())
    except Exception:
        return []
    return list(data.get("project", {}).get("dependencies") or [])


@dataclass
class RunResult:
    cmd: list[str]
    cwd: str
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False


@dataclass
class CheckResult:
    """Outcome of a single graded check.

    Bronze checks use: "pass" | "fail" | "error".
    Silver checks additionally use:
      - "skip"             — feature not implemented; not claimed in README. Neutral.
      - "claim_mismatch"   — README claims the feature; presence probe says no.
                             Counts as fail for scoring AND surfaces an
                             over-claim flag for the reviewer.
    """
    id: str                     # e.g., "B1", "S3"
    name: str
    status: str
    note: str = ""
    runs: list[RunResult] = field(default_factory=list)


class Runner:
    """Runs student code inside a per-submission venv and a clean working dir.

    Each bronze check invokes runner.run([...]). The first call lazily creates
    the venv and installs dependencies. Working directory is wiped between runs
    so file-based storage (bbs.json / bbs.db) doesn't leak across checks.
    """

    def __init__(self, submission_dir: Path, venv_dir: Path, default_timeout: int = 30):
        self.submission_dir = submission_dir
        self.venv_dir = venv_dir
        self.default_timeout = default_timeout
        self._venv_ready = False
        self._pip_log: list[str] = []

    @property
    def python(self) -> Path:
        return self.venv_dir / "bin" / "python"

    @property
    def pip(self) -> Path:
        return self.venv_dir / "bin" / "pip"

    def setup_venv(self) -> tuple[bool, str]:
        """Create venv and install dependencies. Returns (ok, log)."""
        if self._venv_ready:
            return True, "\n".join(self._pip_log)

        # Create venv
        if self.venv_dir.exists():
            shutil.rmtree(self.venv_dir)
        self.venv_dir.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            ["python3", "-m", "venv", str(self.venv_dir)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            return False, f"venv creation failed:\n{proc.stderr}"

        self._pip_log.append("venv created")

        # Decide what to install.
        req_txt = self.submission_dir / "requirements.txt"
        pyproject = self.submission_dir / "pyproject.toml"

        install_ok = True
        if req_txt.exists():
            self._pip_log.append(f"installing from requirements.txt")
            proc = subprocess.run(
                [str(self.pip), "install", "-q", "-r", str(req_txt)],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if proc.returncode != 0:
                self._pip_log.append(f"requirements.txt install FAILED: {proc.stderr[-500:]}")
                install_ok = False
        elif pyproject.exists():
            self._pip_log.append(f"installing from pyproject.toml")
            proc = subprocess.run(
                [str(self.pip), "install", "-q", str(self.submission_dir)],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if proc.returncode != 0:
                # `pip install <dir>` commonly fails when pyproject declares
                # deps but has no [tool.setuptools] package config. Fall back
                # to installing just the dependency list so optional features
                # (bleak, flask, etc.) still become available to bronze checks.
                deps = _parse_pyproject_deps(pyproject)
                if deps:
                    self._pip_log.append(f"pyproject install failed; installing {len(deps)} deps directly")
                    proc2 = subprocess.run(
                        [str(self.pip), "install", "-q", *deps],
                        capture_output=True,
                        text=True,
                        timeout=600,
                    )
                    if proc2.returncode != 0:
                        self._pip_log.append(f"pyproject deps install FAILED: {proc2.stderr[-500:]}")
                        install_ok = False
                    else:
                        self._pip_log.append(f"pyproject deps ok ({len(deps)} packages)")
                else:
                    self._pip_log.append(f"pyproject install FAILED and no deps to extract: {proc.stderr[-500:]}")
                    install_ok = False

        # Always ensure common libs are present as a fallback. A1 didn't teach
        # requirements.txt, so many submissions import libs without declaring them.
        for pkg in ("sqlalchemy", "rich", "Pillow"):
            proc = subprocess.run(
                [str(self.pip), "install", "-q", pkg],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if proc.returncode != 0:
                self._pip_log.append(f"{pkg} fallback install FAILED: {proc.stderr[-500:]}")
                install_ok = False
            else:
                self._pip_log.append(f"{pkg} ok")

        self._venv_ready = True
        return install_ok, "\n".join(self._pip_log)

    def run(self, cmd: list[str], cwd: Path, timeout: int | None = None) -> RunResult:
        """Run a command. First element may be 'python' which resolves to the venv."""
        if cmd and cmd[0] == "python":
            cmd = [str(self.python), *cmd[1:]]
        timeout = timeout or self.default_timeout
        try:
            proc = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"},
            )
            return RunResult(
                cmd=cmd, cwd=str(cwd),
                stdout=_strip_ansi(proc.stdout), stderr=_strip_ansi(proc.stderr),
                returncode=proc.returncode,
            )
        except subprocess.TimeoutExpired as e:
            raw_out = (e.stdout or b"").decode("utf-8", errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            raw_err = (e.stderr or b"").decode("utf-8", errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
            return RunResult(
                cmd=cmd, cwd=str(cwd),
                stdout=_strip_ansi(raw_out), stderr=_strip_ansi(raw_err),
                returncode=-1,
                timed_out=True,
            )

    def clean_state_files(self, work_dir: Path) -> None:
        """Remove persistent state between checks.

        Students store BBS state in a variety of places beyond the canonical
        `bbs.json` / `bbs.db`:
          - `bbs_users.json`, `bbs_boards.json`, etc. — sidecar metadata
          - `bbs_data/` — per-board directory layout
        Anything starting with `bbs` at the work-dir root is fair game; source
        files (`bbs.py`, `bbs_db.py`) are excluded by extension.
        """
        for p in work_dir.iterdir():
            name = p.name
            if not name.startswith(("bbs", "BBS")):
                continue
            if p.is_file() and p.suffix == ".py":
                continue  # bbs.py / bbs_db.py are source, leave alone
            if p.is_file():
                p.unlink()
            elif p.is_dir() and name != "__pycache__":
                shutil.rmtree(p, ignore_errors=True)
