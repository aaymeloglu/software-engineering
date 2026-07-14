"""Audit: does each student's frontend call API endpoints their submitted backend doesn't serve?

This catches "calls to nowhere" facades like a student's DMs feature (frontend has a full DMs UI but the
backend has no /dms route -> 404 on first use). Compares, per student, the resource ROOTS the
frontend hits (paths handed to fetch/the api client) against the roots the A4-branch backend serves
(route decorators + router prefixes). Flags frontend roots with no backend coverage.

Heuristic + root-level, so it under-flags subtle param mismatches but reliably catches whole-feature
gaps. Verify each flag by hand (a flagged root may be served via a prefix the parser missed).
"""
from __future__ import annotations
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "work" / "a4-src"
# Dedicated dir so this batch diagnostic never collides with the interactive
# render_one.sh viewer, which materializes into work/a4-backends/<handle>.
BE_DIR = ROOT / "work" / "a4-audit-be"
import sys as _sys
_sys.path.insert(0, str(ROOT))
from harness import config
from harness.roster import load_roster

CLASS = config.class_repo()

# Handles come from the roster — never hard-code the cohort here.
HANDLES = [s.github for s in load_roster(config.roster_path())]

METHODS = r"(?:fetch|request|apiFetch|apiClient|get|post|put|patch|delete|del|head)"
CALL_RE = re.compile(METHODS + r"\s*(?:<[^>]+>)?\(\s*[`\"']([^`\"']+)[`\"']")
ROUTE_RE = re.compile(r"@\w+\.(?:get|post|put|patch|delete|head|options)\(\s*[\"']([^\"']+)")
PREFIX_RE = re.compile(r"(?:APIRouter|include_router)\([^)]*prefix\s*=\s*[\"']([^\"']+)")


def _norm(s: str) -> str:
    return re.sub(r"[-_]", "", s.lower())


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(CLASS), *args], capture_output=True, text=True).stdout


def _backend_entry_dir(ref: str, handle: str) -> str | None:
    """Repo path of the dir containing this student's backend main.py (may be nested,
    e.g. <handle>/webserver/main.py). Matches on the handle-dir component; prefers the
    shallowest main.py when several exist."""
    tree = _git("ls-tree", "-r", "--name-only", ref)
    candidates = []
    for p in re.findall(r"assignments/bbs-webserver/[^\n]*?/main\.py", tree):
        m = re.match(r"assignments/bbs-webserver/([^/]+)/", p)
        if m and _norm(m.group(1)) == _norm(handle):
            candidates.append(p)
    if not candidates:
        return None
    best = min(candidates, key=lambda p: p.count("/"))  # shallowest
    return best.rsplit("/main.py", 1)[0]


def materialize_backend(handle: str) -> Path | None:
    dest = BE_DIR / handle
    for ref in (f"origin/bbs-frontend-{handle}", f"origin/bbs-webserver-{handle}"):
        entry = _backend_entry_dir(ref, handle)
        if not entry:
            continue
        # Clean-extract the EXACT entry dir. Never reuse a stale tree and never archive a
        # parent dir: a wrong-handle merge or a leftover schema silently yields false
        # "calls to nowhere" audits (this fooled the audit once already).
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True, exist_ok=True)
        strip = entry.count("/") + 1  # segments in the entry path
        arc = subprocess.run(["git", "-C", str(CLASS), "archive", ref, entry], capture_output=True)
        subprocess.run(["tar", "-x", "-C", str(dest), f"--strip-components={strip}"], input=arc.stdout)
        return dest
    return None


def _segments(path: str) -> list[str]:
    """Literal path segments, params/query/garbage dropped, lowercased."""
    path = re.sub(r"^\$\{[^}]*\}", "", path)          # leading ${base}
    path = path.split("?")[0].split("#")[0]
    path = re.sub(r"/\$\{[^}]*\}", "/{p}", path)      # /${param} path params
    path = re.sub(r"\$\{[^}]*\}", "", path)           # remaining ${...} (query suffixes etc)
    path = re.sub(r"/:[A-Za-z_]+", "/{p}", path)      # /:param style
    out = []
    for s in path.strip("/").split("/"):
        s = s.strip().lower()
        if not s or s.startswith("{"):
            continue
        if re.fullmatch(r"[a-z][a-z0-9._-]*", s):     # clean word only (drops garbled captures)
            out.append(s)
    return out


def backend_segments(be: Path) -> set[str]:
    segs: set[str] = set()
    for p in be.rglob("*.py"):
        txt = p.read_text(errors="replace")
        for m in ROUTE_RE.finditer(txt):
            segs.update(_segments(m.group(1)))
        for m in PREFIX_RE.finditer(txt):
            segs.update(_segments(m.group(1)))
    return segs


def frontend_calls(fe: Path) -> list[str]:
    out: list[str] = []
    for p in (fe / "src").rglob("*"):
        if not (p.is_file() and p.suffix in {".ts", ".tsx", ".js", ".jsx"}):
            continue
        if "node_modules" in p.parts:
            continue
        txt = p.read_text(errors="replace")
        for m in CALL_RE.finditer(txt):
            raw = m.group(1)
            if "/" in raw:  # real URL path, not a bare header/param name like "q" or "ETag"
                out.append(raw)
    return out


def main() -> int:
    print(f"{'handle':<20} frontend-calls-backend-LACKS (calls to nowhere)")
    print("-" * 92)
    any_gap = False
    for h in HANDLES:
        be = materialize_backend(h)
        if be is None:
            print(f"{h:<20} (no backend found to audit)")
            continue
        bsegs = backend_segments(be)
        gaps: dict[str, str] = {}
        for raw in frontend_calls(SRC / h):
            for seg in _segments(raw):
                if seg not in bsegs:
                    gaps.setdefault(seg, raw)
        if gaps:
            any_gap = True
            items = "; ".join(f"/{seg} (e.g. {ex})" for seg, ex in sorted(gaps.items()))
            print(f"{h:<20} {items}")
        else:
            print(f"{h:<20} - none -")
    if not any_gap:
        print("\nNo endpoint gaps found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
