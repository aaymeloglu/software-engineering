"""Second-pass evaluation hook protocol.

The first-pass grading harness writes a structured JSON sidecar per student.
A later Claude-driven pass can read that sidecar, open the submission, verify
feature claims, and write findings back into the `second_pass` field.

This module defines the schema and provides helpers to merge findings back
into the per-student markdown report.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SECOND_PASS_SCHEMA = {
    "verified_features": {
        # feature_name: {"status": "confirmed" | "partial" | "missing", "evidence": "..."}
    },
    "code_quality": {
        "correctness_beyond_bronze": None,   # 1-5
        "structure": None,
        "sql_hygiene": None,
        "error_handling": None,
        "readme_thoughtfulness": None,
    },
    "tier_recommendation": None,   # "bronze" | "silver" | "gold"
    "free_text": "",
    "reviewer": "",                # e.g., "claude-opus-4-6"
    "reviewed_at": "",              # ISO timestamp
}


def load_raw(raw_path: Path) -> dict[str, Any]:
    return json.loads(raw_path.read_text())


def save_raw(raw_path: Path, payload: dict[str, Any]) -> None:
    raw_path.write_text(json.dumps(payload, indent=2, default=str))


def init_second_pass_slot(payload: dict[str, Any]) -> dict[str, Any]:
    if "second_pass" not in payload:
        payload["second_pass"] = None
    return payload
