"""Bug catalog interface for Assignment 3 - PUBLIC STUB (answer key withheld).

A3 is a test-first bug hunt: students write tests to catch bugs seeded into
compiled reference modules. This module is the *answer key* - it enumerates
every bug the grader checks each student's tests against - so the real one is
kept private. What ships here is the interface the A3 runner imports, with an
EMPTY catalog, so the harness is runnable and self-documenting without handing
out the answers.

To grade a real A3 cohort, drop in your own catalog with the same shape:

 - `LABELED` - bugs published to students at the Phase 1 deadline (they know
                 these exist and write tests to catch them). Keyed by module.
 - `HIDDEN`  - bugs never published; catching them counts toward the gold
                 tier. Keyed by module.
 - `PUBLIC_ID` -  maps each internal bug name to the opaque student-facing ID
                 (e.g. "A1", "H2") used in reports.

Each bug name must match a `BUGS=<name>` toggle your compiled reference modules
respond to (see the assignment's reference materials).
"""
from __future__ import annotations

# Replace with your real catalog. Shape example (values are per-module bug names):
#   LABELED = {"lru_cache": ["lru_no_promote_on_get", ...], "cart": [...]}
LABELED: dict[str, list[str]] = {}

# Replace with your real hidden (gold-tier) catalog. Same shape as LABELED.
HIDDEN: dict[str, list[str]] = {}

# Map internal bug name -> student-facing opaque ID. Replace with your real map.
PUBLIC_ID: dict[str, str] = {}


def all_labeled() -> list[tuple[str, str]]:
    return [(mod, b) for mod, bugs in LABELED.items() for b in bugs]


def all_hidden() -> list[tuple[str, str]]:
    return [(mod, b) for mod, bugs in HIDDEN.items() for b in bugs]


def public_id(internal_name: str) -> str:
    """Map internal bug name to the student-facing opaque ID (A1, H2, ...)."""
    return PUBLIC_ID.get(internal_name, internal_name)
