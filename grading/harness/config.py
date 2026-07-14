"""Harness configuration loader - the ONLY place course-, repo-, and
student-specific values live.

Everything the harness needs to know about a specific cohort (which repo to
read submissions from, the roster, per-student overrides, and the point
weights) is read from `config.yaml`. The harness code itself carries no
class name, repo path, student handle, or grading weight.

Copy the templates and edit them (both are gitignored once copied):

    cp config.example.yaml config.yaml
    cp roster.example.yaml  roster.yaml

Shell scripts read the same config via the CLI bridge at the bottom, e.g.:

    CLASS_REPO=$(python3 harness/config.py --class-repo)
    OVERRIDE=$(python3 harness/config.py --override <handle> a4_backend_ref)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

# grading/ - this file lives at grading/harness/config.py
ROOT = Path(__file__).resolve().parent.parent

_CFG: dict | None = None


def _load() -> dict:
    for name in ("config.yaml", "config.example.yaml"):
        p = ROOT / name
        if p.exists():
            if yaml is None:
                raise SystemExit("PyYAML required: pip install pyyaml")
            data = yaml.safe_load(p.read_text()) or {}
            data["_source"] = name
            return data
    raise SystemExit(
        f"No config.yaml or config.example.yaml found in {ROOT}. "
        "Copy config.example.yaml to config.yaml and edit it."
    )


def cfg() -> dict:
    global _CFG
    if _CFG is None:
        _CFG = _load()
        if _CFG.get("_source") == "config.example.yaml":
            print(
                "[config] using config.example.yaml (placeholder values). "
                "Copy it to config.yaml and edit for your cohort.",
                file=sys.stderr,
            )
    return _CFG


def _expand(p: str) -> Path:
    return Path(os.path.expanduser(str(p)))


def class_repo() -> Path:
    """Local path to a clone of the class submission repo (read-only)."""
    return _expand(cfg()["class_repo"])


def roster_path() -> Path:
    r = cfg().get("roster", "roster.yaml")
    p = _expand(r)
    return p if p.is_absolute() else ROOT / p


def assignment(aid: str) -> dict:
    """Per-assignment settings (branch/tag/path patterns, reference roots)."""
    return (cfg().get("assignments") or {}).get(aid, {}) or {}


def weights(aid: str) -> dict:
    """Point weights per bucket for an assignment. Illustrative in the
    template; your real splits live in the gitignored config.yaml."""
    return (cfg().get("weights") or {}).get(aid, {}) or {}


def override(handle: str, key: str, default=None):
    """Per-student override value, or `default`. The only place student-
    specific knobs belong."""
    ov = (cfg().get("overrides") or {}).get(handle) or {}
    return ov.get(key, default)


# --------------------------------------------------------------------------
# Shell bridge: let bash scripts read the same config without parsing YAML.
# --------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Config accessor for shell scripts.")
    ap.add_argument("--class-repo", action="store_true", help="print class repo path")
    ap.add_argument("--roster", action="store_true", help="print roster path")
    ap.add_argument("--override", nargs=2, metavar=("HANDLE", "KEY"),
                    help="print a per-student override value (empty if unset)")
    args = ap.parse_args()

    if args.class_repo:
        print(class_repo())
    elif args.roster:
        print(roster_path())
    elif args.override:
        print(override(args.override[0], args.override[1], "") or "")
    else:
        ap.print_help()
