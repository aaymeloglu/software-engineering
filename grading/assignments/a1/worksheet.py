"""Per-student silver/gold evaluation worksheet.

The worksheet is an aid for Andy — not an auto-grader. It surfaces what the
student claims to have built, raw size stats, and a blank rubric for Andy to
fill in. A second-pass Claude agent can also consume the structured JSON
sidecar (see harness.evaluation) to verify feature claims programmatically.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


MIN_FILES = {"bbs.py", "bbs_db.py", "db.py", "migrate.py", "README.md"}

SILVER_FEATURE_HINTS = {
    "boards": ["board", "topic", "channel"],
    "threads": ["thread", "reply", "replies", "parent", "reply_to"],
    "profiles": ["profile", "bio", "join date", "set_bio"],
}

GOLD_FEATURE_HINTS = {
    "ansi_ui": ["ansi", "rich", "color", "banner", "ascii"],
    "private_messages": ["private message", " dm ", "whisper", "pm "],
    "interactive_mode": ["interactive", "repl", "prompt", "loop", "bbs>"],
    "leaderboard": ["leaderboard", "upvote", "reaction", "trending", "score"],
    "import_export": ["import", "export", "dump", "backup"],
}


@dataclass
class WorksheetData:
    handle: str
    student_name: str | None
    files: list[str]
    total_loc: int
    py_file_count: int
    extra_files: list[str]
    readme_silver_gold_section: str
    claimed_silver: list[str]
    claimed_gold: list[str]
    quick_open: str


def _count_py_loc(work: Path) -> tuple[int, int, list[str]]:
    loc = 0
    count = 0
    files = []
    for py in sorted(work.rglob("*.py")):
        if "__pycache__" in str(py):
            continue
        try:
            loc += len(py.read_text(errors="replace").splitlines())
            count += 1
            files.append(str(py.relative_to(work)))
        except Exception:
            pass
    return loc, count, files


def _list_extra_files(work: Path) -> list[str]:
    extras = []
    for p in sorted(work.iterdir()):
        if p.name in MIN_FILES or p.name.startswith("."):
            continue
        if p.name == "__pycache__":
            continue
        extras.append(p.name + ("/" if p.is_dir() else ""))
    return extras


def _extract_readme_tier_section(work: Path) -> str:
    """Pull the silver/gold subsection from the student's README."""
    readmes = list(work.rglob("README.md")) + list(work.rglob("readme.md"))
    if not readmes:
        return "_no README found_"
    text = readmes[0].read_text(errors="replace")
    # Look for a header mentioning silver/gold/tier/feature
    m = re.search(
        r"(#+\s*(silver|gold|tier|feature|extra|extension)[^\n]*\n.*?)(?=\n#+ |\Z)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        return m.group(1).strip()
    # Fallback: last 500 chars
    return "_(no silver/gold section header found — showing last 500 chars of README)_\n\n" + text[-500:]


def _guess_claimed_features(readme_section: str, full_readme: str) -> tuple[list[str], list[str]]:
    blob = (readme_section + "\n" + full_readme).lower()
    silver = [name for name, hints in SILVER_FEATURE_HINTS.items() if any(h in blob for h in hints)]
    gold = [name for name, hints in GOLD_FEATURE_HINTS.items() if any(h in blob for h in hints)]
    return silver, gold


def build_worksheet_data(
    handle: str,
    student_name: str | None,
    work: Path,
) -> WorksheetData:
    readme_section = _extract_readme_tier_section(work)
    readmes = list(work.rglob("README.md")) + list(work.rglob("readme.md"))
    full_readme = readmes[0].read_text(errors="replace") if readmes else ""

    loc, py_count, files = _count_py_loc(work)
    extras = _list_extra_files(work)
    silver, gold = _guess_claimed_features(readme_section, full_readme)

    return WorksheetData(
        handle=handle,
        student_name=student_name,
        files=files,
        total_loc=loc,
        py_file_count=py_count,
        extra_files=extras,
        readme_silver_gold_section=readme_section,
        claimed_silver=silver,
        claimed_gold=gold,
        quick_open=f"code <class-repo>/assignments/bbs/{handle}  # or the branch worktree",
    )


def render(data: WorksheetData) -> str:
    lines = []
    lines.append("## Silver / Gold Evaluation Worksheet")
    lines.append("")

    # Stats
    lines.append("### Size / shape")
    lines.append("")
    lines.append(f"- Total Python LOC: **{data.total_loc}**")
    lines.append(f"- Python files: **{data.py_file_count}**")
    if data.extra_files:
        lines.append(f"- Files beyond the minimum set: {', '.join(f'`{x}`' for x in data.extra_files)}")
    else:
        lines.append("- No files beyond the minimum set.")
    lines.append("")

    # Claimed features
    lines.append("### Claimed features (auto-detected from README)")
    lines.append("")
    if data.claimed_silver:
        lines.append("**Silver candidates:** " + ", ".join(f"`{f}`" for f in data.claimed_silver))
    else:
        lines.append("**Silver candidates:** _none detected_")
    if data.claimed_gold:
        lines.append("")
        lines.append("**Gold candidates:** " + ", ".join(f"`{f}`" for f in data.claimed_gold))
    else:
        lines.append("")
        lines.append("**Gold candidates:** _none detected_")
    lines.append("")

    # README excerpt
    lines.append("### README silver/gold excerpt")
    lines.append("")
    lines.append("```")
    lines.append(data.readme_silver_gold_section[:2000])
    lines.append("```")
    lines.append("")

    # Manual checklist
    lines.append("### Feature verification checklist")
    lines.append("")
    lines.append("_Andy: check what the code actually implements._")
    lines.append("")
    lines.append("Silver:")
    lines.append("- [ ] Boards / topics")
    lines.append("- [ ] Threads")
    lines.append("- [ ] User profiles")
    lines.append("- [ ] Other: _______________")
    lines.append("")
    lines.append("Gold:")
    lines.append("- [ ] ANSI / rich terminal UI")
    lines.append("- [ ] Private messages")
    lines.append("- [ ] Interactive mode")
    lines.append("- [ ] Leaderboard / reactions / trending")
    lines.append("- [ ] Import / export")
    lines.append("- [ ] Other: _______________")
    lines.append("")

    # Rubric
    lines.append("### Rubric (1–5)")
    lines.append("")
    lines.append("| Dimension | Score | Notes |")
    lines.append("|-----------|-------|-------|")
    lines.append("| Correctness beyond bronze | ☐ | |")
    lines.append("| Code structure | ☐ | |")
    lines.append("| SQL hygiene | ☐ | |")
    lines.append("| Error handling | ☐ | |")
    lines.append("| README thoughtfulness | ☐ | |")
    lines.append("")
    lines.append("**Tier call:** ☐ bronze  ☐ silver  ☐ gold")
    lines.append("")

    # Quick open
    lines.append("### Quick open")
    lines.append("")
    lines.append("```")
    lines.append(data.quick_open)
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


def build_worksheet(handle: str, student_name: str | None, work: Path) -> tuple[str, dict]:
    """Return (markdown, sidecar_json_payload)."""
    data = build_worksheet_data(handle, student_name, work)
    md = render(data)
    payload = {
        "handle": handle,
        "student_name": student_name,
        "stats": {
            "total_loc": data.total_loc,
            "py_files": data.py_file_count,
            "files": data.files,
            "extra_files": data.extra_files,
        },
        "readme_tier_section": data.readme_silver_gold_section,
        "claimed_features": {
            "silver": data.claimed_silver,
            "gold": data.claimed_gold,
        },
        "second_pass": None,
    }
    return md, payload
