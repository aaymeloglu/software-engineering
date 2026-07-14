"""Top-level grading orchestrator.

Usage:
    python run.py a1                    # Grade all submissions
    python run.py a1 --student <handle> # Grade a single student
    python run.py a1 --discover         # Just list submissions, don't grade
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

GRADING_ROOT = Path(__file__).parent
sys.path.insert(0, str(GRADING_ROOT))

from harness.checkout import discover_submissions, materialize, Submission
from harness.roster import load_roster, match_handle, missing_submissions
from harness.runner import Runner
from harness.report import (
    write_student_report,
    write_raw_json,
    write_summary,
    render_bronze_section,
)
from harness.review import generate_review
from harness.config import class_repo, roster_path


_ENTRY_FILES = {"a2": "main.py"}


def _maybe_promote_nested_submission(assignment_id: str, work: Path) -> str | None:
    """If the expected entry file isn't at the work-dir root but lives in
    exactly one immediate subdir alongside requirements.txt, promote that
    subdir's contents up to the root. Returns the promoted dir's name, or
    None if no promotion happened.

    Conservative on purpose: only fires when (a) the entry file isn't at
    root, (b) exactly one immediate subdir contains both the entry file
    and requirements.txt, (c) no other immediate subdir contains the
    entry file. Properly-structured submissions hit none of these and
    are left alone.
    """
    entry = _ENTRY_FILES.get(assignment_id)
    if not entry:
        return None
    if (work / entry).exists():
        return None
    candidates = []
    for child in work.iterdir():
        if not child.is_dir() or child.name.startswith(".") or child.name in ("__pycache__",):
            continue
        if (child / entry).exists() and (child / "requirements.txt").exists():
            candidates.append(child)
    if len(candidates) != 1:
        return None
    chosen = candidates[0]
    # Move contents up. If a name collides with something already at root,
    # rename the existing root entry to <name>__outer to preserve it.
    import shutil as _sh
    for item in list(chosen.iterdir()):
        target = work / item.name
        if target.exists():
            target.rename(work / f"{item.name}__outer")
        _sh.move(str(item), str(target))
    chosen.rmdir()
    return chosen.name


def grade_one(
    assignment_id: str,
    submission: Submission,
    work_root: Path,
    venv_root: Path,
    roster: list,
) -> dict:
    """Run all phases for one submission via assignments.<id>.grade().
    Returns a context dict consumed by the review + report stages."""
    assignment_pkg = importlib.import_module(f"assignments.{assignment_id}")
    ws_mod = importlib.import_module(f"assignments.{assignment_id}.worksheet")

    matched = match_handle(roster, submission.handle, submission.committers)
    student_name = matched.name if matched else None

    ctx = {
        "handle": submission.handle,
        "name": student_name,
        "email": matched.uatx_email if matched else "",
        "submission": submission,
        "notes": [],
        "checks": [],          # bronze
        "silver": [],          # silver (may be empty)
        "worksheet_md": "",
        "worksheet_payload": {
            "claimed_features": {"silver": [], "gold": []},
            "claim_keys": {"silver": set(), "gold": set()},
        },
        "work_dir": None,
        "setup_log": "",
        "skip_review": False,
    }

    if submission.is_gitlink:
        ctx["notes"].append("⚠️ Submission path is a **gitlink** (accidental submodule). No actual files to grade.")
        ctx["worksheet_md"] = "_(no files to evaluate)_"
        ctx["skip_review"] = True
        return ctx

    work = materialize(submission, work_root)
    if work is None or not any(work.iterdir() if work else []):
        ctx["notes"].append("❌ Could not materialize submission.")
        ctx["worksheet_md"] = "_(no files)_"
        ctx["skip_review"] = True
        return ctx

    promoted = _maybe_promote_nested_submission(assignment_id, work)
    if promoted:
        ctx["notes"].append(
            f"📁 Submission was nested under `{promoted}/`; promoted to root for grading."
        )

    ctx["work_dir"] = work

    runner = Runner(work, venv_root / submission.handle)
    setup_ok, setup_log = runner.setup_venv()
    ctx["setup_log"] = setup_log
    if not setup_ok:
        ctx["notes"].append(f"⚠️ Venv setup had issues — {setup_log.splitlines()[-1] if setup_log else 'unknown'}")

    # Worksheet runs first so claim_keys are available for silver checks.
    worksheet_md, worksheet_payload = ws_mod.build_worksheet(
        submission.handle, student_name, work
    )
    ctx["worksheet_md"] = worksheet_md
    ctx["worksheet_payload"] = worksheet_payload

    claim_keys = worksheet_payload.get("claim_keys") or {"silver": set(), "gold": set()}
    phases = assignment_pkg.grade(runner, work, claim_keys)
    ctx["checks"] = phases.get("bronze", [])
    ctx["silver"] = phases.get("silver", [])
    return ctx


def generate_reviews_parallel(
    assignment_id: str,
    contexts: list[dict],
    rubric_path: Path,
    max_workers: int = 6,
) -> dict[str, dict]:
    targets = [c for c in contexts if not c["skip_review"] and c["work_dir"] is not None]
    if not targets:
        return {}

    def _one(ctx):
        return ctx["handle"], generate_review(
            assignment_id=assignment_id,
            handle=ctx["handle"],
            work=ctx["work_dir"],
            bronze=ctx["checks"],
            silver=ctx["silver"],
            rubric_path=rubric_path,
        )

    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for handle, review in ex.map(_one, targets):
            results[handle] = review
            err = review.get("error")
            suffix = f"error: {err}" if err else f"{len(review['markdown'])} chars"
            print(f"    review {handle}: {suffix}", flush=True)
    return results


def finalize_report(
    assignment_id: str,
    ctx: dict,
    review: dict | None,
    report_dir: Path,
) -> dict:
    """Write student report + raw json. Returns the summary row."""
    review_md = (review or {}).get("markdown", "")
    review_err = (review or {}).get("error")

    write_student_report(
        ctx["handle"],
        ctx["name"],
        ctx["checks"],
        ctx["worksheet_md"],
        report_dir,
        setup_log=ctx["setup_log"],
        notes=ctx["notes"],
        review_md=review_md,
        review_error=review_err,
        silver=ctx["silver"] or None,
    )

    checks = ctx["checks"]
    passed = sum(1 for c in checks if c.status == "pass")
    total = len(checks) if checks else 10

    silver = ctx["silver"] or []
    silver_passed = sum(1 for c in silver if c.status == "pass")
    silver_mismatch = sum(1 for c in silver if c.status == "claim_mismatch")

    if ctx["checks"]:
        raw = {
            "assignment": assignment_id,
            "handle": ctx["handle"],
            "student_name": ctx["name"],
            "source": ctx["submission"].source,
            "committers": ctx["submission"].committers,
            "submission_path": str(ctx["work_dir"]) if ctx["work_dir"] else None,
            "bronze": {c.id: {"status": c.status, "name": c.name, "note": c.note} for c in checks},
            "bronze_score": passed,
            "bronze_total": total,
            "silver": [
                {"id": c.id, "name": c.name, "status": c.status, "note": c.note}
                for c in silver
            ],
            "silver_passed": silver_passed,
            "silver_total": len(silver),
            "silver_mismatch": silver_mismatch,
            "review_error": review_err,
            "review_included_files": (review or {}).get("included_files", []),
            **{k: v for k, v in ctx["worksheet_payload"].items() if k != "claim_keys"},
        }
        write_raw_json(ctx["handle"], raw, report_dir)

    note_str = "; ".join(ctx["notes"]) if ctx["notes"] else ""
    if ctx["skip_review"] and not note_str:
        note_str = "gitlink — no files"

    return {
        "handle": ctx["handle"],
        "name": ctx["name"],
        "email": ctx["email"],
        "bronze_score": passed if ctx["checks"] else 0,
        "bronze_total": total,
        "silver_passed": silver_passed,
        "silver_total": len(silver),
        "silver_mismatch": silver_mismatch,
        "claims_silver": bool(ctx["worksheet_payload"]["claimed_features"]["silver"]),
        "claims_gold": bool(ctx["worksheet_payload"]["claimed_features"]["gold"]),
        "notes": note_str,
    }


_A3_REPO = class_repo()


def _discover_a3() -> list[dict]:
    """Return list of {handle, phase1_ref, phase2_ref, notes} for A3.

    phase1_ref prefers phase-1-submit-<handle> tag; falls back to branch.
    phase2_ref prefers phase-2-submit-<handle> tag; falls back to branch if it
    contains a phase2/ subtree; otherwise None.
    """
    import subprocess as _sp
    tags = _sp.check_output(["git", "tag"], cwd=_A3_REPO, text=True).splitlines()
    branches = _sp.check_output(["git", "branch", "-r"], cwd=_A3_REPO, text=True).splitlines()
    p1_tags: dict[str, str] = {}
    p2_tags: dict[str, str] = {}
    for t in tags:
        t = t.strip()
        if t.startswith("phase-1-submit-"):
            p1_tags[t[len("phase-1-submit-"):]] = t
        elif t.startswith("phase-2-submit-"):
            p2_tags[t[len("phase-2-submit-"):]] = t
    branch_handles: dict[str, str] = {}
    for b in branches:
        b = b.strip()
        if not b or "HEAD" in b:
            continue
        short = b.replace("origin/", "")
        if short.startswith("a3-testing-"):
            branch_handles[short[len("a3-testing-"):]] = b
    handles = sorted(set(p1_tags) | set(p2_tags) | set(branch_handles))

    def _branch_has(ref: str, handle: str, subdir: str) -> bool:
        try:
            out = _sp.check_output(
                ["git", "ls-tree", ref, f"assignments/a3-testing/{handle}/{subdir}/"],
                cwd=_A3_REPO, text=True, stderr=_sp.DEVNULL,
            )
            return bool(out.strip())
        except _sp.CalledProcessError:
            return False

    out_rows: list[dict] = []
    for h in handles:
        notes: list[str] = []
        # Phase 1
        if h in p1_tags:
            p1 = p1_tags[h]
        elif h in branch_handles and _branch_has(branch_handles[h], h, "phase1"):
            p1 = branch_handles[h]
            notes.append("no phase-1-submit tag; using branch for phase 1")
        else:
            p1 = None
            notes.append("no phase 1 source")
        # Phase 2
        if h in p2_tags:
            p2 = p2_tags[h]
        elif h in branch_handles and _branch_has(branch_handles[h], h, "phase2"):
            p2 = branch_handles[h]
            notes.append("no phase-2-submit tag; using branch for phase 2")
        else:
            p2 = None
        out_rows.append({"handle": h, "phase1_ref": p1, "phase2_ref": p2, "notes": notes})
    return out_rows


def _git_extract(ref: str, source_in_repo: str, dest: Path, strip: int) -> bool:
    """git archive <ref> <source_in_repo> | tar -x -C dest --strip-components=<strip>."""
    import subprocess as _sp
    try:
        archive = _sp.run(
            ["git", "archive", ref, source_in_repo],
            cwd=_A3_REPO, capture_output=True, check=True,
        )
    except _sp.CalledProcessError:
        return False
    tar = _sp.run(
        ["tar", "-x", "-C", str(dest), f"--strip-components={strip}"],
        input=archive.stdout, capture_output=True,
    )
    return tar.returncode == 0


def _materialize_a3(handle: str, phase1_ref: str | None, phase2_ref: str | None,
                    src_root: Path) -> Path | None:
    """Build a per-student submission tree at src_root/<handle>/ combining phase1
    (from phase1_ref) and phase2 (from phase2_ref). Strips any phase2/ that came
    along with phase1_ref so phase2 only comes from phase2_ref.
    """
    import shutil as _sh
    rel = f"assignments/a3-testing/{handle}"
    dest = src_root / handle
    if dest.exists():
        _sh.rmtree(dest)
    dest.mkdir(parents=True)
    if phase1_ref:
        # Strip "assignments/a3-testing/<handle>/" (3 components) so contents land at dest root.
        if not _git_extract(phase1_ref, rel, dest, strip=3):
            return None
        phase2_from_p1 = dest / "phase2"
        if phase2_from_p1.exists():
            _sh.rmtree(phase2_from_p1)
    if phase2_ref:
        # Strip 3 components again: "assignments/a3-testing/<handle>/" so
        # "<rel>/phase2/foo.py" lands at "dest/phase2/foo.py".
        if not _git_extract(phase2_ref, f"{rel}/phase2", dest, strip=3):
            return None
    if not any(dest.iterdir()):
        return None
    return dest


def _run_a3(args) -> int:
    from assignments.a3.runner import (
        grade_one as a3_grade_one,
        write_class_summary as a3_summary,
        write_report as a3_write_report,
    )
    from assignments.a3.review import generate_review as a3_generate_review
    roster = load_roster(Path(args.roster))
    rows = _discover_a3()
    if args.student:
        rows = [r for r in rows if r["handle"] == args.student]
        if not rows:
            print(f"No A3 submission for handle '{args.student}'", file=sys.stderr)
            return 1
    if args.discover:
        for r in rows:
            note = f"   [{'; '.join(r['notes'])}]" if r["notes"] else ""
            print(f"{r['handle']}\tp1:{r['phase1_ref'] or '—'}\tp2:{r['phase2_ref'] or '—'}{note}")
        return 0
    src_root = GRADING_ROOT / "work" / "a3-src"
    report_dir = GRADING_ROOT / "reports" / "a3"
    report_dir.mkdir(parents=True, exist_ok=True)
    src_root.mkdir(parents=True, exist_ok=True)

    # Materialize all submissions first (serial; cheap).
    sub_dirs: dict[str, Path] = {}
    for row in rows:
        handle = row["handle"]
        sub_dir = _materialize_a3(handle, row["phase1_ref"], row["phase2_ref"], src_root)
        if sub_dir is None:
            print(f"!! could not materialize {handle}")
            continue
        sub_dirs[handle] = sub_dir

    print(f"=== grading {len(sub_dirs)} students in parallel (up to 6 at a time) ===", flush=True)

    def _grade(handle_dir):
        handle, sub_dir = handle_dir
        return a3_grade_one(
            handle=handle,
            submission_dir=sub_dir,
            grading_root=GRADING_ROOT,
            report_dir=report_dir,
            run_review=False,
        )

    results = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for r in ex.map(_grade, sub_dirs.items()):
            results.append(r)
            print(f"    {r.handle}: {r.total_score:.1f}/50  "
                  f"(P1 {r.phase1_score:.1f}/30, P2 {r.phase2_score:.1f}/15, "
                  f"Gold {r.gold_score:.1f}/5)", flush=True)

    if args.review and results:
        print(f"\n=== generating AI reviews ({len(results)} students, up to 6 in parallel) ===", flush=True)
        rubric_path = GRADING_ROOT / "assignments" / "a3" / "rubric.md"

        def _one(r):
            sd = sub_dirs[r.handle]
            p1_dict = {
                "labeled_caught": r.phase1.labeled_caught,
                "labeled_missed": r.phase1.labeled_missed,
                "hidden_caught": r.phase1.hidden_caught,
                "hidden_missed": r.phase1.hidden_missed,
            }
            p2_dict = None
            if r.phase2:
                p2_dict = {
                    "tests_unchanged": r.phase2.tests_unchanged,
                    "test_diff_summary": r.phase2.test_diff_summary,
                    "phase1_tests_passed": r.phase2.phase1_tests_passed,
                    "phase1_tests_total": r.phase2.phase1_tests_total,
                    "student_tests_passed": r.phase2.student_tests_passed,
                    "student_tests_total": r.phase2.student_tests_total,
                    "reference_passed": r.phase2.reference_passed,
                    "reference_total": r.phase2.reference_total,
                }
            return r.handle, a3_generate_review(r.handle, sd, rubric_path, p1_dict, p2_dict)

        with ThreadPoolExecutor(max_workers=6) as ex:
            for handle, review in ex.map(_one, results):
                r = next(x for x in results if x.handle == handle)
                r.review_markdown = review["markdown"]
                r.review_error = review["error"]
                # Re-emit report with review attached.
                a3_write_report(r, report_dir)
                err = review.get("error")
                suffix = f"error: {err}" if err else f"{len(review['markdown'])} chars"
                print(f"    review {handle}: {suffix}", flush=True)

    if results:
        summary_path = a3_summary(results, report_dir)
        print(f"\nSummary written: {summary_path}")
    submitted = {r["handle"] for r in rows}
    not_submitted = [s for s in roster if s.github not in submitted]
    if not_submitted:
        print("\nNo A3 submission from:")
        for s in not_submitted:
            print(f"  - {s.github} ({s.name})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("assignment", choices=["a1", "a2", "a3"])
    ap.add_argument("--student", help="Grade a single handle")
    ap.add_argument("--discover", action="store_true", help="List submissions and exit")
    ap.add_argument("--setup-only", action="store_true",
                    help="Materialize work dirs and set up venvs; skip bronze/review")
    ap.add_argument("--review", action="store_true",
                    help="(a3 only) also run AI review via `claude -p`")
    ap.add_argument("--roster", default=str(roster_path()))
    args = ap.parse_args()

    if args.assignment == "a3":
        return _run_a3(args)

    subs = discover_submissions(args.assignment)
    if args.student:
        subs = [s for s in subs if s.handle == args.student]
        if not subs:
            print(f"No submission matching handle '{args.student}'", file=sys.stderr)
            return 1

    if args.discover:
        for s in subs:
            print(f"{s.handle}\t{s.source}\t{','.join(s.committers)}")
        return 0

    roster = load_roster(Path(args.roster))
    work_root = GRADING_ROOT / "work" / args.assignment
    venv_root = GRADING_ROOT / "work" / "venvs" / args.assignment
    report_dir = GRADING_ROOT / "reports" / args.assignment
    report_dir.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)

    if args.setup_only:
        for sub in subs:
            print(f"=== setup {sub.handle} ===", flush=True)
            if sub.is_gitlink:
                print("    skipped (gitlink)")
                continue
            work = materialize(sub, work_root)
            if work is None:
                print("    skipped (could not materialize)")
                continue
            _maybe_promote_nested_submission(args.assignment, work)
            runner = Runner(work, venv_root / sub.handle)
            ok, log = runner.setup_venv()
            tail = log.splitlines()[-1] if log else ""
            print(f"    venv {'ok' if ok else 'FAIL'} — {tail}")
        return 0

    # Phase 1 — bronze + worksheet (serial; per-submission venv setup is expensive).
    contexts = []
    for sub in subs:
        print(f"=== grading {sub.handle} ===", flush=True)
        try:
            ctx = grade_one(args.assignment, sub, work_root, venv_root, roster)
        except Exception as e:
            traceback.print_exc()
            ctx = {
                "handle": sub.handle, "name": None, "email": "", "submission": sub,
                "notes": [f"harness crashed: {e}"], "checks": [], "silver": [],
                "worksheet_md": "_(crash)_",
                "worksheet_payload": {
                    "claimed_features": {"silver": [], "gold": []},
                    "claim_keys": {"silver": set(), "gold": set()},
                },
                "work_dir": None, "setup_log": "", "skip_review": True,
            }
        contexts.append(ctx)
        passed = sum(1 for c in ctx["checks"] if c.status == "pass")
        total = len(ctx["checks"]) or 10
        print(f"    bronze {passed}/{total}")

    # Phase 2 — parallel design reviews (each shells out to `claude -p`).
    rubric_path = GRADING_ROOT / "assignments" / args.assignment / "rubric.md"
    print(f"\n=== generating design reviews ({sum(1 for c in contexts if not c['skip_review'])} submissions) ===", flush=True)
    reviews = generate_reviews_parallel(args.assignment, contexts, rubric_path)

    # Phase 3 — write reports for this run's students.
    rows_this_run = {}
    for ctx in contexts:
        row = finalize_report(args.assignment, ctx, reviews.get(ctx["handle"]), report_dir)
        rows_this_run[row["handle"]] = row

    # Merge with existing raw sidecars so --student runs don't wipe the class-wide summary.
    rows = list(rows_this_run.values())
    raw_dir = report_dir / "raw"
    if raw_dir.exists():
        for raw_path in raw_dir.glob("*.json"):
            handle = raw_path.stem
            if handle in rows_this_run:
                continue  # already have fresher data from this run
            try:
                import json as _json
                sidecar = _json.loads(raw_path.read_text())
            except Exception:
                continue
            rows.append({
                "handle": sidecar.get("handle", handle),
                "name": sidecar.get("student_name"),
                "email": "",
                "bronze_score": sidecar.get("bronze_score", 0),
                "bronze_total": sidecar.get("bronze_total", 10),
                "silver_passed": sidecar.get("silver_passed", 0),
                "silver_total": sidecar.get("silver_total", 0),
                "silver_mismatch": sidecar.get("silver_mismatch", 0),
                "claims_silver": bool(sidecar.get("claimed_features", {}).get("silver")),
                "claims_gold": bool(sidecar.get("claimed_features", {}).get("gold")),
                "notes": "",
            })

    # Missing-submission detection — against the FULL set of graded handles, not just this run.
    submitted_handles = {r["handle"] for r in rows}
    missing = missing_submissions(roster, submitted_handles) if roster else []
    not_submitted_rows = [{"name": s.name, "email": s.uatx_email, "notes": s.notes} for s in missing]

    # Unmatched branches: handles with submissions but no roster entry
    unmatched = []
    for sub in subs:
        if not match_handle(roster, sub.handle, sub.committers):
            unmatched.append(sub.handle)

    summary_path = write_summary(rows, not_submitted_rows, unmatched, report_dir, args.assignment)
    print(f"\nSummary written: {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
