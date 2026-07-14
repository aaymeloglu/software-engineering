"""A1 (BBS) — phase orchestration.

A1 is CLI-driven, not server-driven, so it has no shared server lifecycle
and no silver-check module. grade() returns {"bronze": [...]} and the
absence of a "silver" key signals to run.py that the LLM should score
silver as before.
"""
from __future__ import annotations

from pathlib import Path

from harness.runner import Runner, CheckResult

from . import bronze
from .bronze import run_bronze_checks
from .worksheet import build_worksheet

__all__ = ["grade", "run_bronze_checks", "build_worksheet"]


def grade(runner: Runner, work: Path,
          claim_keys: dict[str, set[str]]) -> dict[str, list[CheckResult]]:
    return {"bronze": bronze.run_bronze_checks(runner, work)}
