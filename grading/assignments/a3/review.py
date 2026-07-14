"""AI review for A3 submissions.

Shells out to `claude -p --model opus` with a prompt that bundles the
student's Phase 1 tests, Phase 1 README, Phase 2 source (if any), Phase 2
README (if any), and the mechanical grading result. Claude returns a markdown
review that Andy uses to set the AI-reviewed component scores (test quality,
silver breadth, fix quality) and to flag evidence of bug-list reverse-
engineering.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

MAX_FILE_BYTES = 30_000
MAX_TOTAL_BYTES = 120_000


def _read_clipped(path: Path) -> str:
    try:
        text = path.read_text(errors="replace")
    except Exception:
        return ""
    if len(text) > MAX_FILE_BYTES:
        text = text[:MAX_FILE_BYTES] + f"\n...[{len(text) - MAX_FILE_BYTES} bytes truncated]"
    return text


def _dump_dir(root: Path, exts: tuple[str, ...]) -> str:
    """Concatenate files in root matching exts, each prefixed with its relative path."""
    if not root.exists():
        return "(directory not present)"
    chunks: list[str] = []
    total = 0
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix not in exts:
            continue
        if "__pycache__" in p.parts:
            continue
        rel = p.relative_to(root)
        body = _read_clipped(p)
        block = f"\n===== {rel} =====\n{body}\n"
        if total + len(block) > MAX_TOTAL_BYTES:
            chunks.append("\n[remaining files truncated]\n")
            break
        chunks.append(block)
        total += len(block)
    return "".join(chunks)


def _build_prompt(
    handle: str,
    submission_dir: Path,
    rubric_text: str,
    phase1_result: dict,
    phase2_result: dict | None,
) -> str:
    phase1_tests = _dump_dir(submission_dir / "phase1" / "tests", (".py",))
    phase1_readme = _read_clipped(submission_dir / "phase1" / "README.md") or "(no phase1 README)"

    phase2_src = _dump_dir(submission_dir / "phase2" / "src", (".py",)) if (submission_dir / "phase2").exists() else "(no phase2 submitted)"
    phase2_readme = _read_clipped(submission_dir / "phase2" / "README.md") or "(no phase2 README)"

    labeled_caught = phase1_result.get("labeled_caught", [])
    labeled_missed = phase1_result.get("labeled_missed", [])
    hidden_caught = phase1_result.get("hidden_caught", [])
    hidden_missed = phase1_result.get("hidden_missed", [])

    ref_line = ""
    if phase2_result:
        ref_line = (
            f"- Phase 2 reference suite: {phase2_result.get('reference_passed', 0)} / "
            f"{phase2_result.get('reference_total', 0)} passing on fixed source.\n"
            f"- Phase 2 student tests: {phase2_result.get('student_tests_passed', 0)} / "
            f"{phase2_result.get('student_tests_total', 0)} passing.\n"
            f"- phase1/tests == phase2/tests: {phase2_result.get('tests_unchanged', False)}\n"
        )

    return f"""You are reviewing UATX Software Engineering Assignment 3 for student `{handle}`.
A3 is a test-first bug hunt: students wrote tests against opaque .pyc modules
in Phase 1, then fixed buggy source in Phase 2 using those tests.

Output ONLY the sections described below.

### Rubric
{rubric_text}

### Mechanical grading results

- Labeled bugs caught: {len(labeled_caught)} / {len(labeled_caught) + len(labeled_missed)}
  - Caught: {', '.join(labeled_caught) or 'none'}
  - Missed: {', '.join(labeled_missed) or 'none'}
- Hidden bugs caught: {len(hidden_caught)} / {len(hidden_caught) + len(hidden_missed)}
  - Caught: {', '.join(hidden_caught) or 'none'}
{ref_line}

### Phase 1 README
{phase1_readme}

### Phase 1 tests
{phase1_tests}

### Phase 2 README
{phase2_readme}

### Phase 2 source (student's fixes)
{phase2_src}

=================================================================

## What to produce

Six short sections, each 2-4 sentences or a short bullet list. Cite specific
test names and line numbers. Be direct.

### Test quality (0-6 points suggested)
Cover: naming, arrange-act-assert structure, parametrization use, flakiness
(sleeps where determinism works), and whether tests look clause-derived (good)
or bug-ID-derived (bad). Suggest a points value. If tests are well-named like
`test_c3_touching_endpoints_merge`, that's clause-derived. If names look like
`test_bug_5` or suspiciously narrow tests hit exactly one seeded bug, flag it
as possible reverse-engineering.

### Silver coverage breadth (0-3 points suggested)
Did the student write 3+ tests PER MODULE that go beyond the published bug
catalog? Genuine edge cases (zero, empty, very large, unicode, boundary)
count. Tests that only check the listed bugs do not. Suggest a points value.

### Phase 2 fix quality (0-3 points suggested, or "n/a - no phase2")
Did they remove the buggy code paths cleanly, or patch around them with
conditionals / dead code / commented-out-bug-behavior? Source smell hints.

### Reverse-engineering flags
List any signs that the student may have decompiled the .pyc or worked
backwards from the bug catalog rather than from the spec. If nothing
suspicious, say "no evidence." Specifically flag: test names that match
internal bug IDs verbatim, very narrow tests that happen to hit exactly one
seeded bug and nothing else, or tests that check implementation details
(like LRU internal ordering via repr) rather than observable behavior.

### README quality
Brief note on whether the READMEs show genuine reflection or look LLM-
generated boilerplate.

### Andy, focus on this
One or two sentences — the single most important thing for Andy to look at
when finalizing this student's grade.
""".strip()


def generate_review(
    handle: str,
    submission_dir: Path,
    rubric_path: Path,
    phase1_result: dict,
    phase2_result: dict | None,
    timeout: int = 300,
) -> dict:
    rubric_text = rubric_path.read_text() if rubric_path.exists() else "(rubric not found)"
    prompt = _build_prompt(handle, submission_dir, rubric_text, phase1_result, phase2_result)

    try:
        proc = subprocess.run(
            ["claude", "-p", "--model", "opus"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"markdown": "", "error": f"claude -p timed out after {timeout}s"}
    except FileNotFoundError:
        return {"markdown": "", "error": "claude CLI not on PATH"}

    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-5:]
        return {"markdown": "", "error": f"claude -p exit {proc.returncode}: {' | '.join(tail)}"}

    return {"markdown": proc.stdout.strip(), "error": None}
