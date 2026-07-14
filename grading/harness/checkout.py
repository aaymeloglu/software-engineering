"""Enumerate and materialize student submissions from the class repo."""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from harness.config import class_repo

REPO = class_repo()


@dataclass
class Submission:
    handle: str                  # Directory name under the assignment dir
    source: str                  # "main" or a branch ref like "origin/bbs-foo"
    branch: str | None           # Branch this came from (if not main)
    path_in_repo: Path           # Relative path within the repo tree
    committers: list[str]        # Email addresses that touched this dir
    is_gitlink: bool = False     # True if the entry is a submodule/gitlink (broken submission)


@dataclass
class AssignmentLayout:
    """Per-assignment knobs for discovering submissions.

    `assignment_dir` — relative path under the repo root that holds per-student
        directories (e.g., "assignments/bbs" for A1, "assignments/bbs-webserver"
        for A2).
    `branch_match` — given a fully-qualified remote ref like "origin/bbs-foo",
        return True if it's an in-scope branch for this assignment.
    `handle_from_branch` — extract the student handle from such a ref. Used to
        remap directories when a student kept a non-conforming dir name on
        their branch.
    """
    assignment_dir: str
    branch_match: Callable[[str], bool]
    handle_from_branch: Callable[[str], str | None]


def _a1_match(ref: str) -> bool:
    short = ref.replace("origin/", "").lower()
    if short.startswith("bbs-webserver-"):
        return False
    return short.startswith("bbs-") or short.startswith("bbs-")


def _a1_handle(ref: str) -> str | None:
    short = ref.replace("origin/", "")
    if short.lower().startswith("bbs-webserver-"):
        return None
    for prefix in ("bbs-", "BBS-"):
        if short.startswith(prefix):
            return short[len(prefix):]
    return None


def _a2_match(ref: str) -> bool:
    short = ref.replace("origin/", "").lower()
    return short.startswith("bbs-webserver-")


def _a2_handle(ref: str) -> str | None:
    short = ref.replace("origin/", "")
    for prefix in ("bbs-webserver-", "BBS-webserver-", "bbs-Webserver-"):
        if short.startswith(prefix):
            return short[len(prefix):]
    if short.lower().startswith("bbs-webserver-"):
        return short[len("bbs-webserver-"):]
    return None


LAYOUTS: dict[str, AssignmentLayout] = {
    "a1": AssignmentLayout(
        assignment_dir="assignments/bbs",
        branch_match=_a1_match,
        handle_from_branch=_a1_handle,
    ),
    "a2": AssignmentLayout(
        assignment_dir="assignments/bbs-webserver",
        branch_match=_a2_match,
        handle_from_branch=_a2_handle,
    ),
}


def git(*args: str, cwd: Path = REPO) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True)


def list_main_submissions(assignment_dir: str) -> list[str]:
    """Return directory names under <assignment_dir>/ on main."""
    out = git("ls-tree", "main", assignment_dir + "/")
    names = []
    for line in out.strip().splitlines():
        parts = line.split(maxsplit=3)
        if len(parts) < 4:
            continue
        mode, obj_type, _sha, path = parts
        if obj_type == "tree":
            names.append(Path(path).name)
    return sorted(names)


def list_branches(layout: AssignmentLayout) -> list[str]:
    """Return remote branch refs that match this assignment."""
    out = git("branch", "-r")
    refs = []
    for line in out.splitlines():
        ref = line.strip()
        if not ref or "HEAD" in ref:
            continue
        if layout.branch_match(ref):
            refs.append(ref)
    return sorted(refs)


def list_student_dirs_in_ref(ref: str, assignment_dir: str) -> list[tuple[str, bool]]:
    """Return (dirname, is_gitlink) tuples under <assignment_dir>/ at the given ref."""
    try:
        out = git("ls-tree", ref, assignment_dir + "/")
    except subprocess.CalledProcessError:
        return []
    result = []
    for line in out.strip().splitlines():
        parts = line.split(maxsplit=3)
        if len(parts) < 4:
            continue
        mode, obj_type, _sha, path = parts
        name = Path(path).name
        if obj_type == "tree":
            result.append((name, False))
        elif obj_type == "commit":  # Gitlink / accidental submodule
            result.append((name, True))
    return result


def committers_for_path(path: str) -> list[str]:
    try:
        out = git("log", "--all", "--pretty=%ae", "--", path)
    except subprocess.CalledProcessError:
        return []
    return sorted({line.strip() for line in out.splitlines() if line.strip()})


def discover_submissions(layout: AssignmentLayout | str = "a1") -> list[Submission]:
    """Walk the repo and produce one Submission per unique handle.

    Edge cases handled:
      - Branch with the assignment prefix where the student's code lives in
        a directory not named after them. We remap the directory to the
        branch-implied handle.
      - Branches whose handle never adds a NEW directory beyond what main
        already has (e.g., a re-submitted branch that only rebased without
        adding files). We skip these — the student isn't considered to have
        submitted on this branch.
      - Accidental gitlinks (submodule commits instead of trees): kept so
        they show up in the report as a failed submission.
    """
    if isinstance(layout, str):
        layout = LAYOUTS[layout]

    main_dirs = set(list_main_submissions(layout.assignment_dir))
    branches = list_branches(layout)

    observations: dict[str, list[tuple[str, str, bool]]] = {}
    for ref in ["main", *branches]:
        for name, is_gitlink in list_student_dirs_in_ref(ref, layout.assignment_dir):
            observations.setdefault(name, []).append(
                (ref, f"{layout.assignment_dir}/{name}", is_gitlink)
            )

    # Dir-to-handle remap.
    for dirname in list(observations.keys()):
        if dirname in main_dirs:
            continue
        obs = observations[dirname]
        sources = {o[0] for o in obs}
        if len(sources) != 1:
            continue
        (ref,) = sources
        if ref == "main":
            continue
        handle = layout.handle_from_branch(ref)
        if handle and handle != dirname and handle not in observations:
            observations[handle] = observations.pop(dirname)

    # Filter out branch-only "submissions" that don't add ANY new directory
    # beyond main. Common case: a student opened an A2 branch but it just
    # mirrors main (their A1 dir + another student's A2 dir; nothing of their own).
    for dirname in list(observations.keys()):
        obs = observations[dirname]
        sources = {o[0] for o in obs}
        if "main" in sources:
            continue  # submitted to main — keep
        # branch-only — only keep if at least one branch has THIS dir as its handle
        keepers = [o for o in obs if layout.handle_from_branch(o[0]) == dirname]
        if not keepers:
            del observations[dirname]

    submissions: list[Submission] = []
    for name, obs in sorted(observations.items()):
        main_obs = [o for o in obs if o[0] == "main"]
        branch_obs = [o for o in obs if o[0] != "main"]

        if main_obs:
            ref, path, is_gitlink = main_obs[0]
            branch = None
            source = "main"
        else:
            def score(o):
                ref = o[0].replace("origin/", "")
                return 0 if name.lower() in ref.lower() else 1
            obs_sorted = sorted(branch_obs, key=score)
            ref, path, is_gitlink = obs_sorted[0]
            branch = ref
            source = ref

        submissions.append(Submission(
            handle=name,
            source=source,
            branch=branch,
            path_in_repo=Path(path),
            committers=committers_for_path(path),
            is_gitlink=is_gitlink,
        ))

    # Branches whose handle never appears anywhere as a directory.
    seen = {s.handle for s in submissions}
    for ref in branches:
        handle = layout.handle_from_branch(ref)
        if not handle or handle in seen:
            continue
        expected = f"{layout.assignment_dir}/{handle}"
        try:
            entries = git("ls-tree", ref, expected)
        except subprocess.CalledProcessError:
            entries = ""
        if not entries.strip():
            continue
        first_line = entries.strip().splitlines()[0]
        is_gitlink = " commit " in f" {first_line.split(maxsplit=3)[1]} "
        submissions.append(Submission(
            handle=handle,
            source=ref,
            branch=ref,
            path_in_repo=Path(expected),
            committers=committers_for_path(expected),
            is_gitlink=is_gitlink,
        ))

    return submissions


def materialize(submission: Submission, work_root: Path) -> Path | None:
    """Copy a submission into a fresh working directory."""
    dest = work_root / submission.handle
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    if submission.is_gitlink:
        return None

    try:
        archive = subprocess.run(
            ["git", "archive", submission.source, str(submission.path_in_repo)],
            cwd=REPO,
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return None

    tar = subprocess.run(
        ["tar", "-x", "-C", str(dest)],
        input=archive.stdout,
        capture_output=True,
    )
    if tar.returncode != 0:
        return None

    nested = dest / submission.path_in_repo
    if nested.exists() and nested.is_dir():
        for item in nested.iterdir():
            shutil.move(str(item), str(dest / item.name))
        prefix_root = dest / submission.path_in_repo.parts[0]
        if prefix_root.exists():
            shutil.rmtree(prefix_root)

    if not any(dest.iterdir()):
        return None

    return dest


if __name__ == "__main__":
    import sys
    layout_name = sys.argv[1] if len(sys.argv) > 1 else "a1"
    for s in discover_submissions(layout_name):
        marker = " [gitlink]" if s.is_gitlink else ""
        main_marker = " [merged→main]" if s.source == "main" else ""
        print(f"{s.handle}{main_marker}{marker}")
        print(f"  source: {s.source}")
        print(f"  committers: {', '.join(s.committers) or '(none)'}")
