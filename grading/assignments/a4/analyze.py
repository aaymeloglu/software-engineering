"""A4 (BBS Frontend) static analyzer.

A4 is a React + TypeScript + Vite app. There is no verify_api.py-style behavioral
harness the way A1/A2/A3 had, because most of what makes a frontend good is visual,
stateful, and async (the assignment says so explicitly). What CAN be checked
deterministically are *signals*: does it build, are the eight A2 endpoints wired up,
is routing/localStorage/VITE_API_BASE present, how many real tests exist, is there CI.

These signals inform — but do not rote-decide — the 50-pt scoring. The nuanced grade
(loading/error states actually rendering, optimistic update correctness, visual taste,
accessibility, code organization) comes from the AI code+README review, fed these signals.

Usage: python3 assignments/a4/analyze.py            # all students in work/a4-src
       python3 assignments/a4/analyze.py <handle>   # one student
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

GRADING_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = GRADING_ROOT / "work" / "a4-src"
sys.path.insert(0, str(GRADING_ROOT))
from harness import config
CLASS_REPO = config.class_repo()


def _norm_handle(h: str) -> str:
    return h.lower().replace("-", "").replace("_", "")


def report_not_submitted() -> None:
    """Flag roster students with no A4 submission so non-submitters can't vanish from
    the report (a non-submitter did once). Keyed off the existence of an
    origin/bbs-frontend-<handle> branch, NOT off work/a4-src: a materialization failure
    (e.g. the nested-entry-point bug) must never read as 'not submitted'. Prints to
    stderr so it never corrupts the JSON on stdout."""
    roster_path = config.roster_path()
    if yaml is None or not roster_path.exists():
        print("[not-submitted check skipped: no roster.yaml or PyYAML]", file=sys.stderr)
        return
    students = (yaml.safe_load(roster_path.read_text()) or {}).get("students", [])
    if not students:
        return
    try:
        branches = subprocess.run(
            ["git", "-C", str(CLASS_REPO), "branch", "-r", "--format=%(refname:short)"],
            capture_output=True, text=True, check=True,
        ).stdout
    except Exception as e:  # noqa: BLE001 — diagnostic, never fatal to analysis
        print(f"[not-submitted check skipped: {e}]", file=sys.stderr)
        return
    submitted = {_norm_handle(m.group(1)) for m in re.finditer(r"origin/bbs-frontend-(\S+)", branches)}
    missing = [s for s in students if _norm_handle(s.get("github", "")) not in submitted]
    if missing:
        print(f"\n=== A4 NOT SUBMITTED ({len(missing)} of {len(students)} roster students) ===", file=sys.stderr)
        for s in missing:
            print(f"  MISSING: {s.get('name', '?')} ({s.get('github', '?')}) — no bbs-frontend-<handle> branch", file=sys.stderr)
        print("  -> record these in summary.md under 'Not submitted' (do not let them drop silently)\n", file=sys.stderr)
    else:
        print(f"[A4: all {len(students)} roster students have a submission branch]", file=sys.stderr)

# The eight A2 bronze endpoints the spec says must be "wired up somewhere in the UI".
# Each entry: (label, method, regex over source). Frontend usually builds the path as a
# template literal, so we match the path shape + a nearby method hint loosely.
ENDPOINTS = [
    ("GET /posts (feed)", r"""['"`]/posts(\?|['"`])"""),
    ("POST /posts (compose)", r"""/posts['"`]"""),  # paired with POST method check below
    ("GET /users (list)", r"""['"`]/users(\?|['"`])"""),
    ("POST /users (signup)", r"""/users['"`]"""),
    ("GET /users/{u} (profile)", r"""/users/\$\{[^}]+\}['"`]"""),
    ("GET /users/{u}/posts", r"""/users/\$\{[^}]+\}/posts"""),
    ("GET /posts/{id} (detail)", r"""/posts/\$\{[^}]+\}['"`]"""),
    ("DELETE /posts/{id}", r"""/posts/\$\{[^}]+\}"""),
]

CODE_EXT = {".ts", ".tsx", ".js", ".jsx"}


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _all_code(root: Path) -> str:
    parts = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix in CODE_EXT and "node_modules" not in p.parts:
            parts.append(_read(p))
    return "\n".join(parts)


def _src_code(root: Path) -> str:
    """Only the app's src/ (exclude tests) for endpoint-wiring checks."""
    src = root / "src"
    parts = []
    base = src if src.is_dir() else root
    for p in base.rglob("*"):
        if not (p.is_file() and p.suffix in CODE_EXT):
            continue
        if "node_modules" in p.parts:
            continue
        rel = p.as_posix()
        if "/tests/" in rel or ".test." in rel or ".spec." in rel:
            continue
        parts.append(_read(p))
    return "\n".join(parts)


def analyze(handle: str) -> dict:
    root = SRC_ROOT / handle
    pkg_path = root / "package.json"
    pkg = {}
    if pkg_path.exists():
        try:
            pkg = json.loads(_read(pkg_path))
        except Exception:
            pkg = {}
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    scripts = pkg.get("scripts", {})

    src = _src_code(root)
    allcode = _all_code(root)

    # Endpoint wiring (heuristic: path shape present in src/)
    has_post_method = bool(re.search(r"method\s*:\s*['\"]POST['\"]", src, re.I)) or "POST" in src
    has_delete_method = bool(re.search(r"method\s*:\s*['\"]DELETE['\"]", src, re.I)) or "DELETE" in src
    endpoints = {}
    for label, pat in ENDPOINTS:
        hit = bool(re.search(pat, src))
        if label.startswith("POST"):
            hit = hit and has_post_method
        if label.startswith("DELETE"):
            hit = hit and has_delete_method
        endpoints[label] = hit
    endpoints_wired = sum(endpoints.values())

    # Test files + a rough case count. The silver bar is "≥3 real tests" (cases, not
    # files): one file can hold many it()/test() blocks or none, so a file count alone
    # can't tell you whether the bar is met. test_case_count sums it()/test() blocks
    # across the test files. It's a lower-bound signal (doesn't judge whether a case is
    # real vs a render-without-crash tautology — a human still confirms that), but it
    # flags the "looks like tests, actually has <3 cases" gap the file count hides.
    test_files = []
    test_case_count = 0
    case_re = re.compile(r"\b(?:it|test)\s*(?:\.\w+)?\s*\(")  # it( / test( / it.each( / test.skip(
    for p in root.rglob("*"):
        if not p.is_file() or "node_modules" in p.parts:
            continue
        rel = p.as_posix()
        if re.search(r"(\.test\.|\.spec\.)", rel):
            test_files.append(str(p.relative_to(root)))
            test_case_count += len(case_re.findall(p.read_text(errors="ignore")))
    e2e_files = [t for t in test_files if "e2e" in t or ".spec." in t]

    # Largest source file (style/quality signal — "App.tsx is 800 lines")
    largest = ("", 0)
    for p in root.rglob("*"):
        if p.is_file() and p.suffix in CODE_EXT and "node_modules" not in p.parts:
            rel = p.as_posix()
            if "/tests/" in rel or ".test." in rel or ".spec." in rel:
                continue
            n = len(_read(p).splitlines())
            if n > largest[1]:
                largest = (str(p.relative_to(root)), n)

    # README sections
    readme = _read(root / "README.md")
    readme_lc = readme.lower()

    # CI
    ci_files = [str(p.relative_to(root)) for p in root.rglob("*")
                if p.is_file() and (".github/workflows" in p.as_posix()
                                    or p.name in (".gitlab-ci.yml", ".gitlab-ci.yaml"))]
    ci_runs_tests = any(("vitest" in _read(root / f) or "playwright" in _read(root / f)
                         or "npm test" in _read(root / f) or "npm run test" in _read(root / f))
                        for f in ci_files)

    return {
        "handle": handle,
        "files": sum(1 for p in root.rglob("*") if p.is_file() and "node_modules" not in p.parts),
        "deps": {
            "react_router": next((k for k in deps if k.startswith("react-router")), None),
            "vitest": "vitest" in deps,
            "playwright": any("playwright" in k for k in deps),
            "testing_library": any("@testing-library" in k for k in deps),
        },
        "scripts": {k: scripts.get(k) for k in ("dev", "build", "test", "test:e2e", "e2e", "lint")},
        "endpoints_wired": endpoints_wired,
        "endpoints": endpoints,
        "uses_localStorage": "localstorage" in allcode.lower(),
        "uses_VITE_API_BASE": "VITE_API_BASE" in allcode,
        "uses_setInterval_polling": "setInterval" in src,
        "test_file_count": len(test_files),
        "test_case_count": test_case_count,
        "test_files": test_files,
        "has_e2e": bool(e2e_files),
        "e2e_files": e2e_files,
        "largest_source_file": {"path": largest[0], "lines": largest[1]},
        "readme": {
            "present": bool(readme.strip()),
            "lines": len(readme.splitlines()),
            "mentions_cors": "cors" in readme_lc,
            "mentions_tier": any(t in readme_lc for t in ("bronze", "silver", "gold")),
            "mentions_optimistic": "optimistic" in readme_lc,
            "mentions_routing": "rout" in readme_lc,
            "mentions_test_command": "test" in readme_lc,
            "mentions_agent_pushback": ("push back" in readme_lc or "pushed back"
                                        in readme_lc or "agent" in readme_lc),
        },
        "ci": {"files": ci_files, "present": bool(ci_files), "runs_tests": ci_runs_tests},
    }


def main() -> int:
    handles = sys.argv[1:] or sorted(p.name for p in SRC_ROOT.iterdir() if p.is_dir())
    if len(sys.argv) <= 1:  # full-cohort run — surface anyone who didn't submit
        report_not_submitted()
    out = {h: analyze(h) for h in handles}
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
