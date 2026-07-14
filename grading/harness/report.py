"""Report writers: per-student markdown and class summary."""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path

from .runner import CheckResult


FINAL_SCORE_RE = re.compile(r"Final Score:\s*(\d+)\s*/\s*50")
COMPONENT_RE = {
    "bronze": re.compile(r"\|\s*Bronze harness\s*\|\s*(\d+)\s*\|"),
    "style": re.compile(r"\|\s*Code style / decomposition / reuse\s*\|\s*(\d+)\s*\|"),
    "silver": re.compile(r"\|\s*Silver features\s*\|\s*(\d+)\s*\|"),
    "gold": re.compile(r"\|\s*Gold features\s*\|\s*(\d+)\s*\|"),
}


def _extract_totals(report_dir: Path, handle: str) -> dict | None:
    """Read <handle>.md and pull the reviewer-assigned 50-point breakdown.
    Returns None if the review didn't emit a parseable Final Score table.
    """
    path = report_dir / f"{handle}.md"
    if not path.exists():
        return None
    text = path.read_text()
    m = FINAL_SCORE_RE.search(text)
    if not m:
        return None
    out = {"total": int(m.group(1))}
    for key, pattern in COMPONENT_RE.items():
        cm = pattern.search(text)
        out[key] = int(cm.group(1)) if cm else None
    return out


def _truncate(text: str, limit: int = 1200) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[{len(text) - limit} bytes truncated]"


def render_bronze_section(checks: list[CheckResult]) -> str:
    lines = ["## Bronze Conformance", ""]
    passed = sum(1 for c in checks if c.status == "pass")
    lines.append(f"**Score:** {passed} / {len(checks)} passed")
    lines.append("")
    lines.append("| ID | Check | Status | Note |")
    lines.append("|----|-------|--------|------|")
    status_glyph = {"pass": "✅", "fail": "❌", "error": "⚠️"}
    for c in checks:
        note = c.note.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {c.id} | {c.name} | {status_glyph.get(c.status, '?')} {c.status} | {note} |")
    lines.append("")

    # Failure details
    failures = [c for c in checks if c.status != "pass"]
    if failures:
        lines.append("### Failure details")
        lines.append("")
        for c in failures:
            lines.append(f"#### {c.id} — {c.name}")
            lines.append("")
            for r in c.runs:
                cmd_str = " ".join(r.cmd)
                lines.append(f"**`{cmd_str}`** (exit {r.returncode}{' [TIMEOUT]' if r.timed_out else ''})")
                if r.stdout.strip():
                    lines.append("```")
                    lines.append(_truncate(r.stdout))
                    lines.append("```")
                if r.stderr.strip():
                    lines.append("stderr:")
                    lines.append("```")
                    lines.append(_truncate(r.stderr))
                    lines.append("```")
                lines.append("")
    return "\n".join(lines)


def render_silver_section(checks: list[CheckResult]) -> str:
    """Render the deterministic Silver section. Returns '' if no checks given
    (assignments without a silver harness — caller should not include the
    section at all in that case)."""
    if not checks:
        return ""
    passed = sum(1 for c in checks if c.status == "pass")
    mismatched = sum(1 for c in checks if c.status == "claim_mismatch")
    header = f"## Silver — {passed}/{len(checks)} verified"
    if mismatched:
        header += f", {mismatched} claim mismatch"
    lines = [header, ""]
    lines.append("| ID | Feature | Status | Note |")
    lines.append("|----|---------|--------|------|")
    glyph = {
        "pass": "✅",
        "fail": "❌",
        "skip": "⊘",
        "claim_mismatch": "⚠️",
        "error": "⚠️",
    }
    for c in checks:
        note = c.note.replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {c.id} | {c.name} | {glyph.get(c.status, '?')} {c.status} | {note} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_student_report(
    handle: str,
    student_name: str | None,
    bronze: list[CheckResult],
    worksheet_md: str,
    report_dir: Path,
    setup_log: str = "",
    notes: list[str] = None,
    review_md: str = "",
    review_error: str | None = None,
    silver: list[CheckResult] | None = None,
) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    md = []
    title = f"# {handle}"
    if student_name:
        title += f" ({student_name})"
    md.append(title)
    md.append("")
    if notes:
        for n in notes:
            md.append(f"> {n}")
        md.append("")
    if review_md:
        # review_md already contains its own ### headings for root cause + design review.
        md.append(review_md)
        md.append("")
    elif review_error:
        md.append(f"> ⚠️ Review generation failed: {review_error}")
        md.append("")
    md.append(render_bronze_section(bronze))
    md.append("")
    if silver:
        md.append(render_silver_section(silver))
        md.append("")
    md.append(worksheet_md)
    if setup_log:
        md.append("")
        md.append("<details><summary>Venv setup log</summary>")
        md.append("")
        md.append("```")
        md.append(setup_log)
        md.append("```")
        md.append("</details>")

    path = report_dir / f"{handle}.md"
    path.write_text("\n".join(md))
    return path


def write_raw_json(handle: str, payload: dict, report_dir: Path) -> Path:
    raw_dir = report_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{handle}.json"
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path


def write_summary(
    rows: list[dict],
    not_submitted: list[dict],
    unmatched_branches: list[str],
    report_dir: Path,
    assignment_id: str | None = None,
) -> Path:
    """rows: [{handle, name, email, bronze_score, bronze_total, claims_silver, claims_gold, notes}]"""
    title = f"Assignment {assignment_id[1:].upper()}" if assignment_id else report_dir.name.upper()
    lines = [f"# {title} — Class Summary", ""]
    lines.append(f"**Total submissions:** {len(rows)}")
    lines.append("")

    # Final 50-point scores (from each student's review markdown, if present).
    totals_rows = []
    for r in rows:
        t = _extract_totals(report_dir, r["handle"])
        if t:
            totals_rows.append({**t, "handle": r["handle"]})
    if totals_rows:
        lines.append("## Final Scores (out of 50)")
        lines.append("")
        lines.append("| Handle | Total | Bronze / 25 | Style / 10 | Silver / 8 | Gold / 7 |")
        lines.append("|--------|-------|-------------|------------|------------|----------|")
        for t in sorted(totals_rows, key=lambda x: (-x["total"], x["handle"])):
            fmt = lambda v: "—" if v is None else str(v)
            lines.append(
                f"| [{t['handle']}]({t['handle']}.md) | **{t['total']}** / 50 "
                f"| {fmt(t['bronze'])} | {fmt(t['style'])} | {fmt(t['silver'])} | {fmt(t['gold'])} |"
            )
        lines.append("")

    lines.append("## Bronze + Silver Results")
    lines.append("")
    has_any_silver = any(r.get("silver_total") for r in rows)
    if has_any_silver:
        lines.append("| Handle | Name | Bronze | Silver | Claims | Notes |")
        lines.append("|--------|------|--------|--------|--------|-------|")
    else:
        lines.append("| Handle | Name | Bronze | Claims | Notes |")
        lines.append("|--------|------|--------|--------|-------|")
    for r in sorted(rows, key=lambda x: (-(x.get("bronze_score") or 0), x["handle"])):
        claims = []
        if r.get("claims_silver"):
            claims.append("silver")
        if r.get("claims_gold"):
            claims.append("gold")
        claims_str = "+".join(claims) or "—"
        name = r.get("name") or "_unknown_"
        bronze_score = f"{r.get('bronze_score', 0)}/{r.get('bronze_total', 0)}"
        notes = (r.get("notes") or "").replace("|", "\\|")
        if has_any_silver:
            silver_total = r.get("silver_total") or 0
            silver_passed = r.get("silver_passed") or 0
            silver_mismatch = r.get("silver_mismatch") or 0
            silver_cell = f"{silver_passed}/{silver_total}" if silver_total else "—"
            if silver_mismatch:
                silver_cell += f" (⚠️{silver_mismatch})"
            lines.append(
                f"| [{r['handle']}]({r['handle']}.md) | {name} | {bronze_score} "
                f"| {silver_cell} | {claims_str} | {notes} |"
            )
        else:
            lines.append(
                f"| [{r['handle']}]({r['handle']}.md) | {name} | {bronze_score} "
                f"| {claims_str} | {notes} |"
            )

    if not_submitted:
        lines.append("")
        lines.append("## Not Submitted")
        lines.append("")
        lines.append("| Name | UATX Email | Notes |")
        lines.append("|------|------------|-------|")
        for s in not_submitted:
            lines.append(f"| {s['name']} | {s['email']} | {s.get('notes', '')} |")

    if unmatched_branches:
        lines.append("")
        lines.append("## Unmatched (branch handle not in roster)")
        lines.append("")
        for h in unmatched_branches:
            lines.append(f"- `{h}`")

    path = report_dir / "summary.md"
    path.write_text("\n".join(lines))
    return path
