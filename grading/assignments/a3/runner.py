"""A3 grading runner.

Grades one student's test-first-bug-hunt submission. Output is a structured
dict plus a markdown report. Invoked from the top-level `run.py`'s `a3`
subcommand, or directly for one-off testing.

Grading flow:

  Phase 1 (tests only):
    1. Verify phase1/tests/ exists with the three expected test files.
    2. Set up a work dir containing: student tests, Phase 1 pyc bundle,
       and a conftest.py that puts the pyc bundle on sys.path.
    3. Run BUGS="" pytest. If ANY test fails, Phase 1 label/hidden catches
       score 0 (the clean-run gate).
    4. For each labeled bug (20): run with BUGS=<bug>. Caught iff at least
       one test fails while passing under the clean run.
    5. For each hidden bug (3): same.

  Phase 2 (bug fixing):
    1. If no phase2/ directory, Phase 2 score is 0.
    2. Diff phase1/tests against phase2/tests. If different, Phase 2 is 0.
    3. Set up a work dir with student's phase2/src/ on sys.path, student's
       tests/, and a conftest. Run pytest — record pass/fail.
    4. Same work dir but swap student tests for our reference suite. Record
       pass/fail per test.

  Returns: a dict (and writes a markdown report) suitable for the class summary.

Requires Python 3.12 on PATH at `python3.12`. This matches what pyc bundles
are keyed against.
"""
from __future__ import annotations

import argparse
import filecmp
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

GRADING_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(GRADING_ROOT))
from harness import config
ASSIGNMENT_ROOT = Path(os.path.expanduser(str(config.assignment("a3").get("reference_root", ""))))
PHASE1_PYC_ROOT = ASSIGNMENT_ROOT / "starter" / "modules"
REFERENCE_TESTS = ASSIGNMENT_ROOT / "reference" / "tests"
STARTER_CONFTEST = ASSIGNMENT_ROOT / "starter" / "conftest.py"

def _pick_python() -> tuple[str, str]:
    """Pick a supported CPython for the pyc bundles. Returns (executable, pyXY tag)."""
    for ver in ("3.12", "3.13", "3.14"):
        exe = shutil.which(f"python{ver}")
        if exe:
            return exe, f"py{ver.replace('.', '')}"
    raise RuntimeError("No supported CPython (3.12/3.13/3.14) found on PATH for A3.")


PYTHON, PY_VERSION_TAG = _pick_python()

MODULES = ["lru_cache", "interval_merger", "cart"]
EXPECTED_TEST_FILES = [f"test_{m}.py" for m in MODULES]

from .bug_catalog import LABELED, HIDDEN, all_labeled, all_hidden, public_id


@dataclass
class PhaseOneResult:
    clean_run_passed: bool
    clean_run_output: str
    labeled_caught: list[str] = field(default_factory=list)
    labeled_missed: list[str] = field(default_factory=list)
    hidden_caught: list[str] = field(default_factory=list)
    hidden_missed: list[str] = field(default_factory=list)
    test_count: int = 0
    error: str | None = None


@dataclass
class PhaseTwoResult:
    tests_unchanged: bool
    student_tests_passed: int
    student_tests_total: int
    reference_passed: int
    reference_total: int
    phase1_tests_passed: int = 0  # phase-1-submit tests run against fixed source
    phase1_tests_total: int = 0
    test_diff_summary: str = ""   # human-readable diff note when tests_unchanged=False
    error: str | None = None


@dataclass
class A3Result:
    handle: str
    submission_dir: Path
    phase1: PhaseOneResult
    phase2: PhaseTwoResult | None
    phase1_score: float
    phase2_score: float
    gold_score: float
    total_score: float
    review_markdown: str = ""
    review_error: str | None = None


# ---------- venv + subprocess helpers ----------

def _ensure_venv(venv_dir: Path) -> None:
    """Create venv with pytest installed, idempotent."""
    if (venv_dir / "bin" / "pytest").exists():
        return
    if venv_dir.exists():
        shutil.rmtree(venv_dir)
    venv_dir.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([PYTHON, "-m", "venv", str(venv_dir)], check=True, capture_output=True)
    pip = venv_dir / "bin" / "pip"
    subprocess.run([str(pip), "install", "-q", "pytest==8.3.4"], check=True, capture_output=True)


def _run_pytest(
    venv_dir: Path,
    work_dir: Path,
    extra_env: dict[str, str] | None = None,
    timeout: int = 60,
) -> tuple[int, str, list[tuple[str, str]]]:
    """Run pytest once in work_dir. Returns (returncode, combined_output, test_results).

    test_results is a list of (nodeid, status) where status is "passed" or "failed".
    """
    pytest_bin = venv_dir / "bin" / "pytest"
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    if extra_env:
        env.update(extra_env)

    try:
        proc = subprocess.run(
            [str(pytest_bin), "tests/", "-v", "--tb=no",
             "--override-ini=addopts=", "-p", "no:cacheprovider"],
            cwd=work_dir,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
        )
        out = proc.stdout + proc.stderr
        results: list[tuple[str, str]] = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            for status in ("PASSED", "FAILED", "ERROR"):
                if f" {status}" in line:
                    nodeid = line.split(f" {status}")[0].strip()
                    results.append((nodeid, status.lower()))
                    break
        return proc.returncode, out, results
    except subprocess.TimeoutExpired:
        return -1, f"pytest timed out after {timeout}s", []


# ---------- Phase 1 ----------

def _setup_phase1_workdir(work_dir: Path, student_tests: Path) -> None:
    """Lay out a runnable pytest env with Phase 1 pycs + student tests."""
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    # Copy pyc bundle (preserving the pyXY subdir the conftest expects).
    modules_dst = work_dir / "modules" / PY_VERSION_TAG
    modules_dst.mkdir(parents=True)
    src_bundle = PHASE1_PYC_ROOT / PY_VERSION_TAG
    for p in src_bundle.iterdir():
        if p.suffix == ".pyc":
            shutil.copy(p, modules_dst / p.name)

    # conftest.py from starter (already version-aware).
    shutil.copy(STARTER_CONFTEST, work_dir / "conftest.py")

    # Copy student tests.
    tests_dst = work_dir / "tests"
    tests_dst.mkdir()
    for p in student_tests.iterdir():
        if p.is_file() and p.suffix == ".py":
            shutil.copy(p, tests_dst / p.name)


def run_phase1(submission_dir: Path, venv_dir: Path, work_root: Path) -> PhaseOneResult:
    tests_dir = submission_dir / "phase1" / "tests"
    if not tests_dir.exists():
        return PhaseOneResult(
            clean_run_passed=False,
            clean_run_output="",
            error="No phase1/tests/ directory found in submission.",
        )

    work_dir = work_root / "phase1"
    _setup_phase1_workdir(work_dir, tests_dir)

    # Clean run.
    rc, out, results = _run_pytest(venv_dir, work_dir, extra_env={"BUGS": ""})
    clean_passed = rc == 0 and bool(results) and all(r[1] == "passed" for r in results)
    clean_nodeids = {nid for nid, status in results if status == "passed"}

    result = PhaseOneResult(
        clean_run_passed=clean_passed,
        clean_run_output=out[-2000:],
        test_count=len(results),
    )

    if not clean_passed:
        return result

    # Iterate labeled bugs.
    for module, bug in all_labeled():
        rc, _, bug_results = _run_pytest(venv_dir, work_dir, extra_env={"BUGS": bug})
        # "Caught" = at least one test that passed clean now fails/errors.
        caught = any(
            status in ("failed", "error") and nid in clean_nodeids
            for nid, status in bug_results
        )
        if caught:
            result.labeled_caught.append(bug)
        else:
            result.labeled_missed.append(bug)

    # Hidden bugs.
    for module, bug in all_hidden():
        rc, _, bug_results = _run_pytest(venv_dir, work_dir, extra_env={"BUGS": bug})
        caught = any(
            status in ("failed", "error") and nid in clean_nodeids
            for nid, status in bug_results
        )
        if caught:
            result.hidden_caught.append(bug)
        else:
            result.hidden_missed.append(bug)

    return result


# ---------- Phase 2 ----------

def _setup_phase2_workdir(
    work_dir: Path,
    student_src: Path,
    tests_dir: Path,
) -> None:
    """Lay out pytest env with student's fixed src + a tests/ directory."""
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    # Copy student src files flat.
    src_dst = work_dir / "src"
    src_dst.mkdir()
    for p in student_src.iterdir():
        if p.is_file() and p.suffix == ".py":
            shutil.copy(p, src_dst / p.name)

    # conftest.py that puts src/ on sys.path.
    (work_dir / "conftest.py").write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).parent / 'src'))\n"
    )

    # Tests dir.
    tests_dst = work_dir / "tests"
    tests_dst.mkdir()
    for p in tests_dir.iterdir():
        if p.is_file() and p.suffix == ".py":
            shutil.copy(p, tests_dst / p.name)


def _diff_summary(a: Path, b: Path) -> str:
    """Short human-readable summary of differences between two test dirs."""
    if not a.exists() or not b.exists():
        return "one side missing"
    names_a = sorted(p.name for p in a.iterdir() if p.is_file() and p.suffix == ".py")
    names_b = sorted(p.name for p in b.iterdir() if p.is_file() and p.suffix == ".py")
    only_a = [n for n in names_a if n not in names_b]
    only_b = [n for n in names_b if n not in names_a]
    common = [n for n in names_a if n in names_b]
    match, mismatch, _err = filecmp.cmpfiles(a, b, common, shallow=False)
    bits = []
    if only_a:
        bits.append(f"removed in phase2: {', '.join(only_a)}")
    if only_b:
        bits.append(f"added in phase2: {', '.join(only_b)}")
    if mismatch:
        bits.append(f"modified: {', '.join(mismatch)}")
    return "; ".join(bits) or "no differences"


def _dir_contents_equal(a: Path, b: Path) -> bool:
    """True iff a/ and b/ contain the same file names with byte-identical contents."""
    if not a.exists() or not b.exists():
        return False
    names_a = sorted(p.name for p in a.iterdir() if p.is_file() and p.suffix == ".py")
    names_b = sorted(p.name for p in b.iterdir() if p.is_file() and p.suffix == ".py")
    if names_a != names_b:
        return False
    match, mismatch, errors = filecmp.cmpfiles(a, b, names_a, shallow=False)
    return not mismatch and not errors


def run_phase2(submission_dir: Path, venv_dir: Path, work_root: Path) -> PhaseTwoResult | None:
    phase2 = submission_dir / "phase2"
    if not phase2.exists():
        return None

    phase1_tests = submission_dir / "phase1" / "tests"
    phase2_tests = phase2 / "tests"
    src_dir = phase2 / "src"

    tests_unchanged = _dir_contents_equal(phase1_tests, phase2_tests)
    diff_summary = "" if tests_unchanged else _diff_summary(phase1_tests, phase2_tests)

    if not src_dir.exists():
        return PhaseTwoResult(
            tests_unchanged=tests_unchanged,
            student_tests_passed=0, student_tests_total=0,
            reference_passed=0, reference_total=0,
            test_diff_summary=diff_summary,
            error="phase2/src/ not found",
        )

    # Phase 1 tests (canonical, from phase-1-submit) against student's fixed src.
    # This is the load-bearing check: if a student weakened their tests in phase 2,
    # the phase 1 tests will fail here and dock points.
    p1_work = work_root / "phase2_phase1tests"
    _setup_phase2_workdir(p1_work, src_dir, phase1_tests)
    _, _, p1_results = _run_pytest(venv_dir, p1_work)
    p1_passed = sum(1 for _, s in p1_results if s == "passed")
    p1_total = len(p1_results)

    # Student's phase 2 tests (which may include additions) against fixed src.
    student_work = work_root / "phase2_student"
    _setup_phase2_workdir(student_work, src_dir, phase2_tests)
    _, _, student_results = _run_pytest(venv_dir, student_work)
    student_passed = sum(1 for _, s in student_results if s == "passed")
    student_total = len(student_results)

    # Reference tests against student's fixed src.
    ref_work = work_root / "phase2_ref"
    _setup_phase2_workdir(ref_work, src_dir, REFERENCE_TESTS)
    _, _, ref_results = _run_pytest(venv_dir, ref_work)
    ref_passed = sum(1 for _, s in ref_results if s == "passed")
    ref_total = len(ref_results)

    return PhaseTwoResult(
        tests_unchanged=tests_unchanged,
        student_tests_passed=student_passed,
        student_tests_total=student_total,
        reference_passed=ref_passed,
        reference_total=ref_total,
        phase1_tests_passed=p1_passed,
        phase1_tests_total=p1_total,
        test_diff_summary=diff_summary,
    )


# ---------- scoring ----------

def score(p1: PhaseOneResult, p2: PhaseTwoResult | None) -> tuple[float, float, float, float]:
    """Return (phase1, phase2, gold, total)."""
    phase1 = 0.0
    gold = 0.0

    if p1.clean_run_passed:
        phase1 += 3.0  # clean run gate
        phase1 += len(p1.labeled_caught) * 0.9  # up to 18.0

    # Phase 1 quality points (6) and silver breadth (3) are AI-reviewed,
    # surfaced to Andy rather than computed. Default midpoint here; Andy
    # can override in the final report.
    phase1 += 4.0  # placeholder quality midpoint (range 0-6)
    phase1 += 1.5  # placeholder silver midpoint (range 0-3)

    gold = len(p1.hidden_caught) * (5.0 / 3.0)

    phase2_score = 0.0
    if p2:
        # 3 pts: phase 1 tests (canonical) must still pass against fixed source.
        # This catches the "weakened tests" case regardless of additions.
        if p2.phase1_tests_total:
            phase2_score += 3.0 * (p2.phase1_tests_passed / p2.phase1_tests_total)
        if p2.reference_total:
            phase2_score += 9.0 * (p2.reference_passed / p2.reference_total)
        # Fix quality: AI-reviewed, placeholder midpoint.
        phase2_score += 1.5  # range 0-3

    total = phase1 + phase2_score + gold
    return phase1, phase2_score, gold, total


# ---------- report writer ----------

def write_report(result: A3Result, report_dir: Path) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    md = report_dir / f"{result.handle}.md"

    lines: list[str] = []
    lines.append(f"# {result.handle}")
    lines.append("")
    lines.append(f"**Total: {result.total_score:.1f} / 50**  "
                 f"(Phase 1: {result.phase1_score:.1f}/30, "
                 f"Phase 2: {result.phase2_score:.1f}/15, "
                 f"Gold: {result.gold_score:.1f}/5)")
    lines.append("")

    # Phase 1.
    lines.append("## Phase 1 — tests")
    p1 = result.phase1
    if p1.error:
        lines.append(f"Error: {p1.error}")
    elif not p1.clean_run_passed:
        lines.append("❌ Clean run (`BUGS=\"\"`) failed. Phase 1 gate not cleared.")
        lines.append("```")
        lines.append(p1.clean_run_output[:1500])
        lines.append("```")
    else:
        lines.append(f"✅ Clean run: {p1.test_count} tests passed under `BUGS=\"\"`.")
        lines.append("")
        lines.append(f"**Labeled bugs caught: {len(p1.labeled_caught)} / 20**")
        if p1.labeled_caught:
            lines.append("")
            lines.append("Caught:")
            for b in sorted(p1.labeled_caught, key=lambda n: int(public_id(n)[1:])):
                lines.append(f"- ✅ **{public_id(b)}** (`{b}`)")
        if p1.labeled_missed:
            lines.append("")
            lines.append("Missed:")
            for b in sorted(p1.labeled_missed, key=lambda n: int(public_id(n)[1:])):
                lines.append(f"- ❌ **{public_id(b)}** (`{b}`)")
        lines.append("")
        lines.append(f"**Hidden bugs caught: {len(p1.hidden_caught)} / 3**")
        if p1.hidden_caught:
            for b in sorted(p1.hidden_caught, key=lambda n: int(public_id(n)[1:])):
                lines.append(f"- 🏆 **{public_id(b)}** (`{b}`)")

    # Phase 2.
    lines.append("")
    lines.append("## Phase 2 — fixes")
    if result.phase2 is None:
        lines.append("_No phase2/ directory submitted._")
    else:
        p2 = result.phase2
        if p2.error:
            lines.append(f"Error: {p2.error}")
        if not p2.tests_unchanged:
            lines.append(f"⚠️ `phase1/tests` and `phase2/tests` differ ({p2.test_diff_summary}). "
                         f"Scoring uses phase 1 tests against fixed source.")
        else:
            lines.append("✅ Tests unchanged between phases.")
        lines.append("")
        lines.append(f"Phase 1 tests (canonical) against fixed source: "
                     f"**{p2.phase1_tests_passed} / {p2.phase1_tests_total}** passing.")
        lines.append(f"Student's phase 2 tests against fixed source: "
                     f"**{p2.student_tests_passed} / {p2.student_tests_total}** passing.")
        lines.append(f"Held-out reference suite against fixed source: "
                     f"**{p2.reference_passed} / {p2.reference_total}** passing.")

    # Review (if any).
    if result.review_markdown:
        lines.append("")
        lines.append("## AI review")
        lines.append("")
        lines.append(result.review_markdown)
    elif result.review_error:
        lines.append("")
        lines.append(f"_Review generation error: {result.review_error}_")

    md.write_text("\n".join(lines))
    return md


# ---------- main entry ----------

def grade_one(
    handle: str,
    submission_dir: Path,
    grading_root: Path,
    report_dir: Path,
    run_review: bool = False,
) -> A3Result:
    venv_dir = grading_root / "work" / "venvs" / handle
    work_root = grading_root / "work" / "a3" / handle

    _ensure_venv(venv_dir)

    p1 = run_phase1(submission_dir, venv_dir, work_root)
    p2 = run_phase2(submission_dir, venv_dir, work_root)
    s1, s2, sg, st = score(p1, p2)

    result = A3Result(
        handle=handle,
        submission_dir=submission_dir,
        phase1=p1,
        phase2=p2,
        phase1_score=s1,
        phase2_score=s2,
        gold_score=sg,
        total_score=st,
    )

    if run_review and p1.clean_run_passed:
        from .review import generate_review
        rubric_path = Path(__file__).parent / "rubric.md"
        p1_dict = {
            "labeled_caught": p1.labeled_caught,
            "labeled_missed": p1.labeled_missed,
            "hidden_caught": p1.hidden_caught,
            "hidden_missed": p1.hidden_missed,
        }
        p2_dict = None
        if p2:
            p2_dict = {
                "tests_unchanged": p2.tests_unchanged,
                "student_tests_passed": p2.student_tests_passed,
                "student_tests_total": p2.student_tests_total,
                "reference_passed": p2.reference_passed,
                "reference_total": p2.reference_total,
            }
        review = generate_review(handle, submission_dir, rubric_path, p1_dict, p2_dict)
        result.review_markdown = review["markdown"]
        result.review_error = review["error"]

    write_report(result, report_dir)

    # Persist a raw JSON sidecar too.
    raw = {
        "handle": handle,
        "submission_dir": str(submission_dir),
        "phase1": {
            "clean_run_passed": p1.clean_run_passed,
            "test_count": p1.test_count,
            "labeled_caught": p1.labeled_caught,
            "labeled_missed": p1.labeled_missed,
            "hidden_caught": p1.hidden_caught,
            "hidden_missed": p1.hidden_missed,
            "error": p1.error,
        },
        "phase2": None if p2 is None else {
            "tests_unchanged": p2.tests_unchanged,
            "test_diff_summary": p2.test_diff_summary,
            "phase1_tests_passed": p2.phase1_tests_passed,
            "phase1_tests_total": p2.phase1_tests_total,
            "student_tests_passed": p2.student_tests_passed,
            "student_tests_total": p2.student_tests_total,
            "reference_passed": p2.reference_passed,
            "reference_total": p2.reference_total,
            "error": p2.error,
        },
        "scores": {
            "phase1": s1,
            "phase2": s2,
            "gold": sg,
            "total": st,
        },
    }
    (report_dir / "raw").mkdir(exist_ok=True)
    (report_dir / "raw" / f"{handle}.json").write_text(json.dumps(raw, indent=2))
    return result


def write_class_summary(results: list[A3Result], report_dir: Path) -> Path:
    """Write a class-wide summary table."""
    lines = [
        "# A3 — Class summary",
        "",
        "| Handle | Total | P1 (30) | P2 (15) | Gold (5) | Bugs caught | Hidden | Ref suite |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(results, key=lambda x: -x.total_score):
        p1 = r.phase1
        p2 = r.phase2
        bugs = f"{len(p1.labeled_caught)}/20" if p1.clean_run_passed else "—"
        hidden = f"{len(p1.hidden_caught)}/3" if p1.clean_run_passed else "—"
        ref = f"{p2.reference_passed}/{p2.reference_total}" if p2 and p2.reference_total else "—"
        lines.append(
            f"| `{r.handle}` | {r.total_score:.1f} | {r.phase1_score:.1f} | "
            f"{r.phase2_score:.1f} | {r.gold_score:.1f} | {bugs} | {hidden} | {ref} |"
        )
    out = report_dir / "summary.md"
    out.write_text("\n".join(lines))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--handle", help="Grade one student (used with --submission)")
    g.add_argument("--batch", help="Parent directory with one subdirectory per student handle")
    ap.add_argument("--submission", help="Path to the student's A3 submission dir (single-student mode)")
    ap.add_argument("--report-dir", default=None)
    ap.add_argument("--review", action="store_true",
                    help="Also run the AI review (slower; requires `claude` CLI on PATH)")
    args = ap.parse_args()

    grading_root = Path(__file__).parent.parent.parent
    report_dir = Path(args.report_dir) if args.report_dir else grading_root / "reports" / "a3"
    report_dir.mkdir(parents=True, exist_ok=True)

    if args.handle:
        if not args.submission:
            print("--submission required with --handle", file=sys.stderr)
            return 1
        result = grade_one(
            handle=args.handle,
            submission_dir=Path(args.submission).resolve(),
            grading_root=grading_root,
            report_dir=report_dir,
            run_review=args.review,
        )
        print(f"{args.handle}: {result.total_score:.1f} / 50 "
              f"(P1: {result.phase1_score:.1f}, P2: {result.phase2_score:.1f}, Gold: {result.gold_score:.1f})")
        print(f"Report: {report_dir / (args.handle + '.md')}")
        return 0

    # Batch mode.
    batch_root = Path(args.batch).resolve()
    if not batch_root.is_dir():
        print(f"Batch root is not a directory: {batch_root}", file=sys.stderr)
        return 1
    subdirs = [p for p in batch_root.iterdir() if p.is_dir() and (p / "phase1").exists()]
    if not subdirs:
        print(f"No submissions found under {batch_root} (looking for <handle>/phase1/)", file=sys.stderr)
        return 1

    results: list[A3Result] = []
    for subdir in sorted(subdirs):
        handle = subdir.name
        print(f"=== grading {handle} ===", flush=True)
        try:
            r = grade_one(
                handle=handle,
                submission_dir=subdir,
                grading_root=grading_root,
                report_dir=report_dir,
                run_review=args.review,
            )
            results.append(r)
            print(f"    {r.total_score:.1f} / 50")
        except Exception as e:
            print(f"    harness crashed: {e}", flush=True)

    summary_path = write_class_summary(results, report_dir)
    print(f"\nSummary written: {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
