"""Bronze conformance checks for Assignment 1 (BBS).

Each check is loose on output format but strict on behavior. We use
substring/regex matching so students who add ANSI colors, emojis, or
reformat timestamps still pass.

Checks use a shared per-submission work directory. The runner wipes
`bbs.json` and `bbs.db` between checks so each starts from a clean state.
"""
from __future__ import annotations

import re
import shutil
import sqlite3
from pathlib import Path

from harness.runner import Runner, RunResult, CheckResult
from harness.sql_safety import find_unsafe_sql_strings


def _normalize(text: str) -> str:
    """Collapse runs of whitespace (including newlines) to single spaces."""
    return re.sub(r'\s+', ' ', text)


def _contains_all(text: str, needles: list[str]) -> tuple[bool, str]:
    norm = _normalize(text)
    missing = [n for n in needles if n not in text and n not in norm]
    if missing:
        return False, f"missing: {', '.join(repr(m) for m in missing)}"
    return True, ""


def _ran_ok(results: list[RunResult]) -> tuple[bool, str]:
    """True if every run exited cleanly (no crashes, no timeouts)."""
    for r in results:
        if r.timed_out:
            return False, f"timeout on `{' '.join(r.cmd[-4:])}`"
        if r.returncode != 0:
            tail = (r.stderr or r.stdout).strip().splitlines()[-3:]
            return False, f"exit {r.returncode} on `{' '.join(r.cmd[-4:])}` — {' | '.join(tail)}"
    return True, ""


DEFAULT_BOARD = "general"


_USAGE_PATTERN = re.compile(r"\b(usage|Usage|USAGE):")


def _looks_like_usage_error(r: RunResult) -> bool:
    """Some students print 'Usage: ...' and exit 0 on bad args. Treat that as a failure."""
    if r.returncode != 0:
        return True
    combined = f"{r.stdout}\n{r.stderr}"
    # Only the first ~200 chars — a usage line at the top is the signal.
    return bool(_USAGE_PATTERN.search(combined[:400]))


def _post(runner: Runner, script: str, user: str, msg: str, work: Path) -> RunResult:
    """Post tolerantly: if `post <user> <msg>` fails (likely because the
    student made a `board` argument required for their Silver boards
    extension), retry with `post <user> general <msg>`. Returns whichever
    invocation succeeded, or the original failure if both fail.

    Also tolerates students who print 'Usage: ...' and exit 0 on bad args.
    """
    r = runner.run(["python", script, "post", user, msg], cwd=work)
    if not _looks_like_usage_error(r):
        return r
    r2 = runner.run(["python", script, "post", user, DEFAULT_BOARD, msg], cwd=work)
    if not _looks_like_usage_error(r2):
        return r2
    return r


def _bbs_script(work: Path, name: str) -> str:
    """Locate a student's script (bbs.py, bbs_db.py, migrate.py).

    Returns the script name if found at root, otherwise a relative path to a
    subdirectory copy. Raises FileNotFoundError if not found.
    """
    if (work / name).exists():
        return name
    # Try common alternate roots
    for sub in work.iterdir():
        if sub.is_dir() and (sub / name).exists():
            return str(sub.relative_to(work) / name)
    raise FileNotFoundError(name)


def _find_db_file(work: Path) -> Path | None:
    """Find bbs.db (may live in a subdirectory if student scripts do)."""
    candidates = list(work.rglob("bbs.db"))
    return candidates[0] if candidates else None


def _find_json_file(work: Path) -> Path | None:
    candidates = list(work.rglob("bbs.json"))
    return candidates[0] if candidates else None


# ============================================================
# Individual checks
# ============================================================

def check_b1_json_smoke(runner: Runner, work: Path) -> CheckResult:
    """B1: bbs.py post/read/users/search smoke test."""
    cr = CheckResult(id="B1", name="JSON: post/read/users/search", status="fail")
    try:
        bbs = _bbs_script(work, "bbs.py")
    except FileNotFoundError:
        cr.status = "error"
        cr.note = "bbs.py not found"
        return cr

    runner.clean_state_files(work)
    runs = [
        _post(runner, bbs, "alice", "sunrise", work),
        _post(runner, bbs, "bob", "zenith", work),
        _post(runner, bbs, "alice", "dusk", work),
        runner.run(["python", bbs, "read"], cwd=work),
        runner.run(["python", bbs, "users"], cwd=work),
        runner.run(["python", bbs, "search", "zenith"], cwd=work),
    ]
    cr.runs = runs
    ok, why = _ran_ok(runs)
    if not ok:
        cr.note = why
        return cr

    read_out = runs[3].stdout
    users_out = runs[4].stdout
    search_out = runs[5].stdout

    ok, why = _contains_all(read_out, ["sunrise", "zenith", "dusk"])
    if not ok:
        cr.note = f"read output — {why}"
        return cr
    if "alice" not in read_out or "bob" not in read_out:
        cr.note = "read output missing alice or bob attribution"
        return cr
    ok, why = _contains_all(users_out, ["alice", "bob"])
    if not ok:
        cr.note = f"users output — {why}"
        return cr
    if "zenith" not in search_out:
        cr.note = f"search 'zenith' didn't return the expected post"
        return cr
    cr.status = "pass"
    return cr


def check_b2_user_dedup_json(runner: Runner, work: Path) -> CheckResult:
    cr = CheckResult(id="B2", name="JSON: user list deduplicates", status="fail")
    try:
        bbs = _bbs_script(work, "bbs.py")
    except FileNotFoundError:
        cr.status = "error"
        cr.note = "bbs.py not found"
        return cr

    runner.clean_state_files(work)
    runs = []
    for i in range(5):
        runs.append(_post(runner, bbs, "dave", f"Message {i+1}", work))
    runs.append(runner.run(["python", bbs, "users"], cwd=work))
    cr.runs = runs

    ok, why = _ran_ok(runs)
    if not ok:
        cr.note = why
        return cr

    users_out = runs[-1].stdout
    # Must contain "dave", and shouldn't list it 5 times.
    dave_lines = [l for l in users_out.splitlines() if re.search(r"\bdave\b", l)]
    if not dave_lines:
        cr.note = "dave not in users output"
        return cr
    if len(dave_lines) >= 3:  # Allow 1 or 2 (2 if there's a header); 3+ = not dedup'd
        cr.note = f"dave appears {len(dave_lines)} times in users output (expected 1)"
        return cr
    cr.status = "pass"
    return cr


def check_b3_db_smoke(runner: Runner, work: Path) -> CheckResult:
    cr = CheckResult(id="B3", name="SQLite: post/read/users/search", status="fail")
    try:
        bbs_db = _bbs_script(work, "bbs_db.py")
    except FileNotFoundError:
        cr.status = "error"
        cr.note = "bbs_db.py not found"
        return cr

    runner.clean_state_files(work)
    # Also remove any lingering db in subdirs
    for db in work.rglob("bbs.db"):
        db.unlink()

    runs = [
        _post(runner, bbs_db, "alice", "sunrise", work),
        _post(runner, bbs_db, "bob", "zenith", work),
        _post(runner, bbs_db, "alice", "dusk", work),
        runner.run(["python", bbs_db, "read"], cwd=work),
        runner.run(["python", bbs_db, "users"], cwd=work),
        runner.run(["python", bbs_db, "search", "zenith"], cwd=work),
    ]
    cr.runs = runs
    ok, why = _ran_ok(runs)
    if not ok:
        cr.note = why
        return cr

    read_out = runs[3].stdout
    users_out = runs[4].stdout
    search_out = runs[5].stdout

    ok, why = _contains_all(read_out, ["sunrise", "zenith", "dusk"])
    if not ok:
        cr.note = f"read — {why}"
        return cr
    ok, why = _contains_all(users_out, ["alice", "bob"])
    if not ok:
        cr.note = f"users — {why}"
        return cr
    if "zenith" not in search_out:
        cr.note = "search 'zenith' didn't return the expected post"
        return cr
    cr.status = "pass"
    return cr


def check_b4_db_schema(runner: Runner, work: Path) -> CheckResult:
    """B4: verify users/posts tables exist with sane columns after B3 ran."""
    cr = CheckResult(id="B4", name="SQLite: schema (users + posts tables)", status="fail")
    db_path = _find_db_file(work)
    if not db_path:
        cr.note = "bbs.db not found after running bbs_db.py"
        return cr

    try:
        con = sqlite3.connect(str(db_path))
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}
        if "users" not in tables or "posts" not in tables:
            cr.note = f"expected users+posts tables, found: {sorted(tables)}"
            con.close()
            return cr

        cur.execute("PRAGMA table_info(users)")
        user_cols = {row[1] for row in cur.fetchall()}
        cur.execute("PRAGMA table_info(posts)")
        post_cols = {row[1] for row in cur.fetchall()}
        con.close()

        if "username" not in user_cols and "name" not in user_cols:
            cr.note = f"users table has no username column. cols={sorted(user_cols)}"
            return cr
        # Look for something that references users
        has_user_link = any("user" in c.lower() for c in post_cols)
        if not has_user_link:
            cr.note = f"posts table has no user_id-like column. cols={sorted(post_cols)}"
            return cr
        cr.status = "pass"
    except sqlite3.DatabaseError as e:
        cr.note = f"could not open bbs.db: {e}"
    return cr


def check_b5_migrate_roundtrip(runner: Runner, work: Path) -> CheckResult:
    cr = CheckResult(id="B5", name="Migrate: JSON → SQLite round-trip", status="fail")
    try:
        bbs = _bbs_script(work, "bbs.py")
        bbs_db = _bbs_script(work, "bbs_db.py")
        migrate = _bbs_script(work, "migrate.py")
    except FileNotFoundError as e:
        cr.status = "error"
        cr.note = f"{e.args[0]} not found"
        return cr

    runner.clean_state_files(work)
    for db in work.rglob("bbs.db"):
        db.unlink()
    for j in work.rglob("bbs.json"):
        j.unlink()

    runs = [
        _post(runner, bbs, "alice", "morning", work),
        _post(runner, bbs, "bob", "world", work),
        _post(runner, bbs, "alice", "night", work),
        runner.run(["python", migrate], cwd=work),
        runner.run(["python", bbs_db, "read"], cwd=work),
        runner.run(["python", bbs_db, "users"], cwd=work),
    ]
    cr.runs = runs
    ok, why = _ran_ok(runs)
    if not ok:
        cr.note = why
        return cr

    read_out = runs[4].stdout
    users_out = runs[5].stdout
    ok, why = _contains_all(read_out, ["morning", "world", "night", "alice", "bob"])
    if not ok:
        cr.note = f"post-migration read — {why}"
        return cr
    ok, why = _contains_all(users_out, ["alice", "bob"])
    if not ok:
        cr.note = f"post-migration users — {why}"
        return cr
    cr.status = "pass"
    return cr


def check_b6_migrate_dedup(runner: Runner, work: Path) -> CheckResult:
    cr = CheckResult(id="B6", name="Migrate: dedupes repeated users", status="fail")
    try:
        bbs = _bbs_script(work, "bbs.py")
        migrate = _bbs_script(work, "migrate.py")
    except FileNotFoundError as e:
        cr.status = "error"
        cr.note = f"{e.args[0]} not found"
        return cr

    runner.clean_state_files(work)
    for db in work.rglob("bbs.db"):
        db.unlink()

    runs = []
    for i in range(5):
        runs.append(_post(runner, bbs, "dave", f"msg {i+1}", work))
    runs.append(runner.run(["python", migrate], cwd=work))
    cr.runs = runs
    ok, why = _ran_ok(runs)
    if not ok:
        cr.note = why
        return cr

    db_path = _find_db_file(work)
    if not db_path:
        cr.note = "bbs.db not found after migrate"
        return cr

    try:
        con = sqlite3.connect(str(db_path))
        user_count = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        post_count = con.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        con.close()
    except sqlite3.DatabaseError as e:
        cr.note = f"db query failed: {e}"
        return cr

    if user_count != 1:
        cr.note = f"expected 1 user, got {user_count}"
        return cr
    if post_count != 5:
        cr.note = f"expected 5 posts, got {post_count}"
        return cr
    cr.status = "pass"
    return cr


def check_b7_sql_injection(runner: Runner, work: Path) -> CheckResult:
    cr = CheckResult(id="B7", name="SQL injection safety", status="fail")
    try:
        bbs_db = _bbs_script(work, "bbs_db.py")
    except FileNotFoundError:
        cr.status = "error"
        cr.note = "bbs_db.py not found"
        return cr

    runner.clean_state_files(work)
    for db in work.rglob("bbs.db"):
        db.unlink()

    injection_user = "Robert'; DROP TABLE posts;--"
    runs = [
        _post(runner, bbs_db, "alice", "normal", work),
        _post(runner, bbs_db, injection_user, "oh no", work),
        runner.run(["python", bbs_db, "search", "'; DROP TABLE posts;--"], cwd=work),
        runner.run(["python", bbs_db, "read"], cwd=work),
    ]
    cr.runs = runs
    ok, why = _ran_ok(runs)
    if not ok:
        cr.note = why
        return cr

    # Posts table should still exist and contain both posts
    db_path = _find_db_file(work)
    if not db_path:
        cr.note = "bbs.db missing after injection attempt"
        return cr
    try:
        con = sqlite3.connect(str(db_path))
        cur = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='posts'")
        if not cur.fetchone():
            cr.note = "posts table was dropped! SQL injection vulnerability."
            con.close()
            return cr
        post_count = con.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        con.close()
    except sqlite3.DatabaseError as e:
        cr.note = f"db check failed: {e}"
        return cr

    if post_count < 2:
        cr.note = f"expected 2 posts, found {post_count}"
        return cr
    cr.status = "pass"
    return cr


def check_b8_no_fstring_sql(runner: Runner, work: Path) -> CheckResult:
    """Static check: no interpolation-based SQL construction where the
    interpolated value isn't a proven compile-time string literal.

    Uses AST analysis (harness.sql_safety) so patterns like
        for table in ("users", "posts"): f"DELETE FROM {table}"
    don't trip the check — there's no injection risk when every interpolation
    resolves to a string literal at parse time.
    """
    cr = CheckResult(id="B8", name="Static: no f-string SQL", status="fail")
    offenders = []
    for py in sorted(work.rglob("*.py")):
        if "__pycache__" in str(py) or "/test" in str(py):
            continue
        try:
            src = py.read_text(errors="replace")
        except Exception:
            continue
        for off in find_unsafe_sql_strings(src, py.name):
            offenders.append(
                f"{off.filename}:{off.lineno} ({off.kind}) — `{off.snippet}` [{off.reason}]"
            )

    if offenders:
        cr.note = "; ".join(offenders[:3])
        return cr
    cr.status = "pass"
    return cr


def check_b9_empty_state(runner: Runner, work: Path) -> CheckResult:
    cr = CheckResult(id="B9", name="Empty state: no crash on read/users/search", status="fail")
    try:
        bbs = _bbs_script(work, "bbs.py")
        bbs_db = _bbs_script(work, "bbs_db.py")
    except FileNotFoundError as e:
        cr.status = "error"
        cr.note = f"{e.args[0]} not found"
        return cr

    runner.clean_state_files(work)
    for db in work.rglob("bbs.db"):
        db.unlink()
    for j in work.rglob("bbs.json"):
        j.unlink()

    runs = [
        runner.run(["python", bbs, "read"], cwd=work),
        runner.run(["python", bbs, "users"], cwd=work),
        runner.run(["python", bbs, "search", "xyzzy"], cwd=work),
        runner.run(["python", bbs_db, "read"], cwd=work),
        runner.run(["python", bbs_db, "users"], cwd=work),
        runner.run(["python", bbs_db, "search", "xyzzy"], cwd=work),
    ]
    cr.runs = runs
    ok, why = _ran_ok(runs)
    if not ok:
        cr.note = why
        return cr
    cr.status = "pass"
    return cr


def check_b10_readme(runner: Runner, work: Path) -> CheckResult:
    cr = CheckResult(id="B10", name="README covers search comparison + migration", status="fail")
    readmes = list(work.rglob("README.md")) + list(work.rglob("README.MD")) + list(work.rglob("readme.md"))
    if not readmes:
        cr.note = "no README.md found"
        return cr
    text = readmes[0].read_text(errors="replace").lower()

    if "search" not in text:
        cr.note = "README doesn't mention 'search'"
        return cr
    if not any(k in text for k in ["sql", "sqlite", "database"]):
        cr.note = "README doesn't mention SQL/SQLite/database"
        return cr
    if "json" not in text:
        cr.note = "README doesn't mention JSON"
        return cr
    if not any(k in text for k in ["migrat", "wipe", "overwrite", "skip", "replace", "delete", "drop", "exist"]):
        cr.note = "README doesn't discuss migration behavior"
        return cr
    cr.status = "pass"
    return cr


# ============================================================
# Orchestrator
# ============================================================

BRONZE_CHECKS = [
    check_b1_json_smoke,
    check_b2_user_dedup_json,
    check_b3_db_smoke,
    check_b4_db_schema,
    check_b5_migrate_roundtrip,
    check_b6_migrate_dedup,
    check_b7_sql_injection,
    check_b8_no_fstring_sql,
    check_b9_empty_state,
    check_b10_readme,
]


def run_bronze_checks(runner: Runner, work_dir: Path) -> list[CheckResult]:
    results = []
    for fn in BRONZE_CHECKS:
        try:
            results.append(fn(runner, work_dir))
        except Exception as e:
            results.append(CheckResult(
                id=fn.__name__.split("_", 2)[1].upper(),
                name=fn.__name__,
                status="error",
                note=f"harness exception: {e}",
            ))
    return results
