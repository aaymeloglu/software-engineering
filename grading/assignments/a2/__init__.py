"""A2 (BBS Webserver) — phase orchestration.

One uvicorn lifecycle per submission, shared between bronze and silver.
Both phases consume the same Client.
"""
from __future__ import annotations

from pathlib import Path

from harness.runner import Runner, CheckResult
from harness.server import spawn_server, ServerStartFailure

from . import bronze, silver


def grade(runner: Runner, work: Path,
          claim_keys: dict[str, set[str]]) -> dict[str, list[CheckResult]]:
    """Spawn one server, run bronze + silver, return phase → results.

    On server-start failure, return a synthetic B1=error + skipped B2..B10
    so the rest of the report rendering still has something to render.
    """
    try:
        with spawn_server(runner, work) as client:
            return {
                "bronze": bronze.run(client),
                "silver": silver.run(client, claim_keys.get("silver", set())),
            }
    except ServerStartFailure as e:
        sh = e.handle
        first = CheckResult(
            id="B1", name="Server starts", status="error",
            note=(sh.error or "unknown")[:300] +
                 (f" | startup tail: {sh.startup_log[-300:]!r}" if sh.startup_log else ""),
        )
        rest = bronze._all_skipped(sh.error or "server didn't start")[1:]
        return {"bronze": [first, *rest], "silver": []}
