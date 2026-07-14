"""Pairwise similarity analysis across student submissions.

Signals we care about (in decreasing order of "this is human copying, not LLM
convergence"):
  1. Identical comment text (especially typos, personal phrasing).
  2. Identical README prose paragraphs.
  3. Long identical code runs with matching variable names in non-obvious ways.
  4. Same committer email appearing on multiple students' branches.

Signals we DON'T care about (LLM convergence is expected):
  - Shared library choices (everyone uses SQLAlchemy `text()`).
  - Shared boilerplate (argparse skeletons, `if __name__ == "__main__":`).
  - Same column names (most schemas will look alike).
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "work" / "a1"

IGNORE: set[str] = set()  # handles to skip, if any
PY_GLOBS = ["*.py"]
README_GLOBS = ["README.md", "README.MD", "readme.md"]


def normalize_py_line(line: str) -> str:
    """Collapse whitespace and strip comments for code-similarity comparison."""
    # Strip comments
    line = re.sub(r"#.*$", "", line)
    # Collapse whitespace
    line = re.sub(r"\s+", " ", line).strip()
    return line


def extract_comments(source: str) -> list[str]:
    """Pull standalone and inline comments — these are idiosyncratic."""
    comments = []
    for line in source.splitlines():
        # Docstrings are handled separately
        m = re.search(r"#\s*(.+)$", line)
        if m:
            txt = m.group(1).strip()
            if len(txt) >= 15:  # skip "# TODO" and other boilerplate
                comments.append(txt)
    return comments


def extract_docstrings(source: str) -> list[str]:
    """Triple-quoted strings — functions, modules, classes."""
    # Crude: grab all triple-quoted blocks
    return re.findall(r'"""(.*?)"""', source, flags=re.DOTALL)


def ngrams(tokens: list[str], n: int = 5) -> set[tuple]:
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def collect_py(student_dir: Path) -> dict[str, str]:
    """Map filename -> source text for a student's python files."""
    out = {}
    for p in sorted(student_dir.rglob("*.py")):
        if "__pycache__" in p.parts or ".venv" in p.parts:
            continue
        try:
            out[p.name] = p.read_text(errors="replace")
        except Exception:
            pass
    return out


def collect_readme(student_dir: Path) -> str:
    for g in README_GLOBS:
        for p in student_dir.rglob(g):
            try:
                return p.read_text(errors="replace")
            except Exception:
                return ""
    return ""


def code_shingles(source: str) -> set[tuple]:
    """5-line shingles of normalized, non-empty code lines."""
    lines = [normalize_py_line(l) for l in source.splitlines()]
    lines = [l for l in lines if l and not l.startswith(('"""', "'''", "import ", "from "))]
    return ngrams(lines, n=5)


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def longest_shared_run(a: str, b: str, min_len: int = 60) -> str | None:
    """Find the longest identical substring between two texts; None if too short."""
    m = SequenceMatcher(None, a, b, autojunk=False)
    match = m.find_longest_match(0, len(a), 0, len(b))
    if match.size < min_len:
        return None
    snippet = a[match.a : match.a + match.size]
    return snippet


def find_shared_comments(src_a: str, src_b: str) -> list[str]:
    ca = set(extract_comments(src_a))
    cb = set(extract_comments(src_b))
    return sorted(ca & cb)


def main():
    students = sorted(d.name for d in ROOT.iterdir() if d.is_dir() and d.name not in IGNORE)
    print(f"Analyzing {len(students)} submissions\n")

    # Per-student code shingles, concatenated comments, full readme
    shingles = {}
    comments = {}
    readmes = {}
    source_by_student = {}
    for s in students:
        py = collect_py(ROOT / s)
        all_src = "\n".join(py.values())
        shingles[s] = code_shingles(all_src)
        comments[s] = set()
        for src in py.values():
            comments[s].update(c for c in extract_comments(src) if len(c) >= 25)
        readmes[s] = collect_readme(ROOT / s)
        source_by_student[s] = all_src

    # Pairwise code similarity
    print("=== Top code-shingle similarities (5-line windows of normalized code) ===\n")
    pairs = []
    for i, a in enumerate(students):
        for b in students[i + 1 :]:
            j = jaccard(shingles[a], shingles[b])
            if j > 0:
                pairs.append((j, a, b))
    pairs.sort(reverse=True)
    for j, a, b in pairs[:10]:
        print(f"  {j:.3f}  {a} <-> {b}   ({len(shingles[a] & shingles[b])} shared shingles)")

    # Pairwise shared comments (strongest signal — comments are idiosyncratic)
    print("\n=== Shared comment lines (>=25 chars, verbatim) ===\n")
    any_shared = False
    for i, a in enumerate(students):
        for b in students[i + 1 :]:
            shared = comments[a] & comments[b]
            if shared:
                any_shared = True
                print(f"  {a} <-> {b}: {len(shared)} shared comments")
                for c in sorted(shared)[:5]:
                    print(f"    - {c[:100]}")
    if not any_shared:
        print("  (none)")

    # Pairwise README overlap — look for longest shared substring
    print("\n=== README longest shared runs (>=80 chars verbatim) ===\n")
    any_readme = False
    for i, a in enumerate(students):
        ra = readmes[a]
        if len(ra) < 80:
            continue
        for b in students[i + 1 :]:
            rb = readmes[b]
            if len(rb) < 80:
                continue
            snippet = longest_shared_run(ra, rb, min_len=80)
            if snippet:
                # Normalize whitespace to make the match meaningful
                sn = re.sub(r"\s+", " ", snippet).strip()
                if len(sn) >= 80:
                    any_readme = True
                    print(f"  {a} <-> {b}: {len(sn)} chars")
                    print(f"    {sn[:200]}")
    if not any_readme:
        print("  (none)")

    # High-similarity pairs get a drill-down on the actual shared shingles
    print("\n=== Drill-down on highest-similarity pair ===\n")
    if pairs:
        j, a, b = pairs[0]
        shared = shingles[a] & shingles[b]
        print(f"  {a} <-> {b} (jaccard {j:.3f}, {len(shared)} shared shingles)")
        for sh in sorted(shared)[:8]:
            print(f"    {' / '.join(sh)[:160]}")


if __name__ == "__main__":
    main()
