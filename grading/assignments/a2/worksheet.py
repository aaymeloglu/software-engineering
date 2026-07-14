"""Per-student silver/gold worksheet for A2 (BBS Webserver).

Surfaces what the student claims (README) and what the source actually
contains (route scan of main.py). The reviewer prompt uses both.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


MIN_FILES = {"main.py", "db.py", "verify_api.py", "requirements.txt", "README.md", "readme.md"}

SILVER_FEATURE_HINTS = {
    "bio":             ["bio", "biography"],
    "post_count":      ["post_count", "post count", "postcount"],
    "patch_users":     ["patch /users", "@app.patch(\"/users", "@app.patch('/users", "PATCH /users"],
    "patch_posts":     ["patch /posts", "@app.patch(\"/posts", "@app.patch('/posts", "PATCH /posts"],
    "username_filter": ["?username=", "username=alice", "username filter",
                        "username param", "filter by username"],
}

GOLD_FEATURE_HINTS = {
    "cursor_pagination": ["cursor", "next_cursor", "?cursor=", "cursor-based"],
    "boards": ["/boards", "board_name", "board:", "boards table",
               "boards/{name}", '"board"'],
    "feed": ["/feed", "GET /feed", '"feed"', "@app.get(\"/feed", "@app.get('/feed"],
    "reactions": ["reaction", "/reactions", "+1", "emoji"],
}


@dataclass
class A2Worksheet:
    handle: str
    student_name: str | None
    files: list[str]
    py_loc: int
    py_files: int
    extra_files: list[str]
    routes: list[str]
    has_user_bio_field: bool
    has_post_count_field: bool
    has_patch_user: bool
    has_patch_post: bool
    has_username_filter: bool
    has_cursor: bool
    has_boards: bool
    has_feed: bool
    has_reactions: bool
    readme_section: str
    full_readme: str
    extended_verify: list[str]   # sub-functions present in their verify_api.py
    claimed_silver: list[str]
    claimed_gold: list[str]


_ROUTE_RE = re.compile(
    r'@\w+\.(get|post|put|patch|delete|head|options)\s*\(\s*[\'"]([^\'"]+)[\'"]',
    re.IGNORECASE,
)


def _read(p: Path) -> str:
    try:
        return p.read_text(errors="replace")
    except Exception:
        return ""


def _scan_routes(work: Path) -> list[str]:
    """Walk every .py and pull @app.<verb>('<path>') decorators."""
    out: list[str] = []
    for py in sorted(work.rglob("*.py")):
        if "__pycache__" in py.parts or ".venv" in py.parts:
            continue
        text = _read(py)
        for verb, path in _ROUTE_RE.findall(text):
            out.append(f"{verb.upper()} {path}")
    return sorted(set(out))


def _count_loc(work: Path) -> tuple[int, int, list[str]]:
    loc = 0
    n = 0
    files = []
    for py in sorted(work.rglob("*.py")):
        if "__pycache__" in py.parts or ".venv" in py.parts:
            continue
        text = _read(py)
        loc += len(text.splitlines())
        n += 1
        files.append(str(py.relative_to(work)))
    return loc, n, files


def _extras(work: Path) -> list[str]:
    extras = []
    for p in sorted(work.iterdir()):
        if p.name.lower() in MIN_FILES or p.name.startswith("."):
            continue
        if p.name == "__pycache__":
            continue
        extras.append(p.name + ("/" if p.is_dir() else ""))
    return extras


def _readme_text(work: Path) -> str:
    for cand in ("README.md", "readme.md", "Readme.md"):
        p = work / cand
        if p.exists():
            return _read(p)
    found = list(work.rglob("README.md")) + list(work.rglob("readme.md"))
    return _read(found[0]) if found else ""


def _silver_gold_section(readme: str) -> str:
    if not readme:
        return "_no README found_"
    m = re.search(
        r"(#+\s*(silver|gold|tier|feature|extra|extension)[^\n]*\n.*?)(?=\n#+ |\Z)",
        readme,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        return m.group(1).strip()
    return "_(no silver/gold section header found — last 600 chars of README)_\n\n" + readme[-600:]


def _verify_extensions(work: Path) -> list[str]:
    """Which TODO functions did the student implement in verify_api.py?"""
    v = work / "verify_api.py"
    if not v.exists():
        return []
    text = _read(v)
    found = []
    for fn in ("run_delete_checks", "run_pagination_checks", "run_field_shape_checks"):
        # Implemented if the function definition does NOT raise NotImplementedError
        # immediately after its docstring/comment.
        m = re.search(rf"def {fn}\([^)]*\):(.*?)(?=\ndef |\Z)", text, re.DOTALL)
        if not m:
            continue
        body = m.group(1)
        if "raise NotImplementedError" in body:
            continue
        # Has at least one check( call — basic implemented-ness signal.
        if "check(" in body or "assert " in body:
            found.append(fn)
    return found


def _scan_user_response_shape(work: Path) -> tuple[bool, bool]:
    """Look at main.py — does any user-returning path mention bio / post_count?"""
    main = _read(work / "main.py")
    if not main:
        for p in work.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            main += _read(p)
    has_bio = bool(re.search(r'\bbio\b', main))
    has_count = bool(re.search(r'post_count', main))
    return has_bio, has_count


def _scan_patch(work: Path) -> tuple[bool, bool]:
    main_text = _read(work / "main.py")
    if not main_text:
        for p in work.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            main_text += "\n" + _read(p)
    patch_user = bool(re.search(r'@\w+\.patch\s*\([\'"]/users', main_text, re.IGNORECASE))
    patch_post = bool(re.search(r'@\w+\.patch\s*\([\'"]/posts', main_text, re.IGNORECASE))
    return patch_user, patch_post


def _scan_username_filter(work: Path) -> bool:
    main_text = _read(work / "main.py")
    if not main_text:
        for p in work.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            main_text += "\n" + _read(p)
    # Look for `username` as a Query/keyword in /posts handler.
    return bool(re.search(
        r'def\s+\w*posts\w*\([^)]*username[^)]*\)|'
        r'username\s*:\s*\w+\s*\|\s*None\s*=\s*Query|'
        r'username\s*:\s*Optional\[\w+\]\s*=\s*Query',
        main_text,
    ))


def _scan_features(routes: list[str], work: Path) -> dict:
    main_text = ""
    for p in work.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        main_text += "\n" + _read(p)

    has_cursor = "cursor" in main_text.lower()
    has_boards = any("/boards" in r.lower() for r in routes) or "boards" in main_text.lower()
    # Distinguish boards-the-feature from incidental string. Tighten:
    if has_boards:
        has_boards = bool(re.search(r'/boards|board_name|board\s*:|boards\s+table', main_text, re.IGNORECASE))
    has_feed = any("/feed" in r.lower() for r in routes)
    has_reactions = any("reaction" in r.lower() for r in routes) or "reactions" in main_text.lower()
    return {
        "cursor": has_cursor,
        "boards": has_boards,
        "feed": has_feed,
        "reactions": has_reactions,
    }


def _claimed_features(readme: str) -> tuple[list[str], list[str]]:
    blob = readme.lower()
    silver = [n for n, hints in SILVER_FEATURE_HINTS.items() if any(h.lower() in blob for h in hints)]
    gold = [n for n, hints in GOLD_FEATURE_HINTS.items() if any(h.lower() in blob for h in hints)]
    return silver, gold


def build_a2_worksheet(handle: str, student_name: str | None, work: Path) -> A2Worksheet:
    py_loc, py_files, files = _count_loc(work)
    routes = _scan_routes(work)
    readme = _readme_text(work)
    section = _silver_gold_section(readme)

    has_bio, has_count = _scan_user_response_shape(work)
    patch_user, patch_post = _scan_patch(work)
    has_username_filter = _scan_username_filter(work)
    feats = _scan_features(routes, work)
    silver_claims, gold_claims = _claimed_features(readme)

    return A2Worksheet(
        handle=handle,
        student_name=student_name,
        files=files,
        py_loc=py_loc,
        py_files=py_files,
        extra_files=_extras(work),
        routes=routes,
        has_user_bio_field=has_bio,
        has_post_count_field=has_count,
        has_patch_user=patch_user,
        has_patch_post=patch_post,
        has_username_filter=has_username_filter,
        has_cursor=feats["cursor"],
        has_boards=feats["boards"],
        has_feed=feats["feed"],
        has_reactions=feats["reactions"],
        readme_section=section,
        full_readme=readme,
        extended_verify=_verify_extensions(work),
        claimed_silver=silver_claims,
        claimed_gold=gold_claims,
    )


def render(w: A2Worksheet) -> str:
    L = []
    L.append("## Silver / Gold Evaluation Worksheet")
    L.append("")
    L.append("### Size / shape")
    L.append("")
    L.append(f"- Total Python LOC: **{w.py_loc}** across {w.py_files} files")
    if w.extra_files:
        L.append(f"- Files beyond minimum set: {', '.join(f'`{x}`' for x in w.extra_files)}")
    L.append("")
    L.append("### Routes detected in source")
    L.append("")
    if w.routes:
        for r in w.routes:
            L.append(f"- `{r}`")
    else:
        L.append("_(no @app.<verb>('...') decorators found)_")
    L.append("")
    L.append("### Auto-detected feature signals")
    L.append("")
    L.append("Silver:")
    L.append(f"- `bio` field referenced in code: **{w.has_user_bio_field}**")
    L.append(f"- `post_count` field referenced in code: **{w.has_post_count_field}**")
    L.append(f"- `PATCH /users/...` route present: **{w.has_patch_user}**")
    L.append(f"- `PATCH /posts/...` route present: **{w.has_patch_post}**")
    L.append(f"- `?username=` filter on /posts: **{w.has_username_filter}**")
    L.append("")
    L.append("Gold:")
    L.append(f"- Cursor-based pagination: **{w.has_cursor}**")
    L.append(f"- Boards/topics: **{w.has_boards}**")
    L.append(f"- /feed endpoint: **{w.has_feed}**")
    L.append(f"- Reactions: **{w.has_reactions}**")
    L.append("")
    L.append(f"### verify_api.py extensions")
    L.append("")
    if w.extended_verify:
        L.append("Implemented: " + ", ".join(f"`{n}`" for n in w.extended_verify))
    else:
        L.append("_(no STUDENT TODO functions look implemented)_")
    L.append("")
    L.append("### README claimed features (auto-detected)")
    L.append("")
    if w.claimed_silver:
        L.append("**Silver:** " + ", ".join(f"`{f}`" for f in w.claimed_silver))
    else:
        L.append("**Silver:** _none detected_")
    if w.claimed_gold:
        L.append("**Gold:** " + ", ".join(f"`{f}`" for f in w.claimed_gold))
    else:
        L.append("**Gold:** _none detected_")
    L.append("")
    L.append("### README silver/gold excerpt")
    L.append("")
    L.append("```")
    L.append(w.readme_section[:2000])
    L.append("```")
    L.append("")
    L.append(f"### Quick open")
    L.append("")
    L.append("```")
    L.append(f"python run.py a2 --student {w.handle}")
    L.append("# then in the venv:")
    L.append("uvicorn main:app --port 8000")
    L.append("# in another shell:")
    L.append("python verify_api.py")
    L.append("```")
    L.append("")
    return "\n".join(L)


def build_worksheet(handle: str, student_name: str | None, work: Path) -> tuple[str, dict]:
    w = build_a2_worksheet(handle, student_name, work)
    md = render(w)
    payload = {
        "handle": handle,
        "student_name": student_name,
        "stats": {
            "py_loc": w.py_loc,
            "py_files": w.py_files,
            "files": w.files,
            "extra_files": w.extra_files,
        },
        "routes": w.routes,
        "feature_signals": {
            "user_bio": w.has_user_bio_field,
            "post_count": w.has_post_count_field,
            "patch_users": w.has_patch_user,
            "patch_posts": w.has_patch_post,
            "username_filter": w.has_username_filter,
            "cursor_pagination": w.has_cursor,
            "boards": w.has_boards,
            "feed": w.has_feed,
            "reactions": w.has_reactions,
        },
        "verify_api_extensions": w.extended_verify,
        "readme_tier_section": w.readme_section,
        "claimed_features": {
            "silver": w.claimed_silver,
            "gold": w.claimed_gold,
        },
        # Normalized for downstream silver-check consumption. The values
        # are sets so silver.py can do membership tests cheaply.
        "claim_keys": {
            "silver": set(w.claimed_silver),
            "gold": set(w.claimed_gold),
        },
    }
    return md, payload
