"""Silver-feature checks for Assignment 2 (BBS Webserver).

Each check is a function taking (client, claimed_keys) and returning a
CheckResult with one of:
  - "pass"            — feature implemented and conformant
  - "fail"            — feature implemented but doesn't meet spec
  - "skip"            — feature not implemented; not claimed in README
  - "claim_mismatch"  — README claims it; presence probe says no

Each check generates UUID-suffixed identifiers so it doesn't collide with
bronze-created data or sibling silver checks within the same server
lifecycle.
"""
from __future__ import annotations

import uuid

from harness.runner import CheckResult
from harness.server import Client


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _absent(claim_key: str, claimed_keys: set[str]) -> str:
    """Return the right status when a presence probe says 'not implemented'."""
    return "claim_mismatch" if claim_key in claimed_keys else "skip"


# ---------------------------------------------------------------------------
# S1 — bio field on user responses
# ---------------------------------------------------------------------------

def s1_bio_field(client: Client, claimed_keys: set[str]) -> CheckResult:
    """`bio` key visible on user responses (POST, GET single, GET list).

    Per the rubric, bio is "visible on the USER object" — settable later
    via PATCH /users (which is a separate silver feature, S3). We do NOT
    require bio to round-trip through POST /users; some students design
    their API so bio is null at creation and only ever set via PATCH,
    which is a defensible reading of the rubric.

    The >200-char length validation is exercised via PATCH in S3.
    """
    u = _uniq("bio")
    r_post = client.post("/users", json_body={"username": u})
    bio_in_post = (
        r_post.status == 201
        and isinstance(r_post.json(), dict)
        and "bio" in r_post.json()
    )

    r_get = client.get(f"/users/{u}")
    bio_in_get = (
        r_get.status == 200
        and isinstance(r_get.json(), dict)
        and "bio" in r_get.json()
    )

    if not (bio_in_post or bio_in_get):
        return CheckResult(
            id="S1", name="bio field on user responses",
            status=_absent("bio", claimed_keys),
            note=("README claims bio; "
                  "neither POST /users response nor GET /users/{u} returned a `bio` key"
                  if "bio" in claimed_keys
                  else "feature not implemented"),
        )

    if not bio_in_post:
        return CheckResult(
            id="S1", name="bio field on user responses", status="fail",
            note="POST /users response missing `bio` key (present in GET)",
        )
    if not bio_in_get:
        return CheckResult(
            id="S1", name="bio field on user responses", status="fail",
            note="GET /users/{u} response missing `bio` key (present in POST)",
        )

    r_list = client.get("/users")
    if r_list.status != 200 or not isinstance(r_list.json(), list):
        return CheckResult(
            id="S1", name="bio field on user responses", status="fail",
            note=f"GET /users returned status={r_list.status}",
        )
    matching = [x for x in r_list.json() if x.get("username") == u]
    if not matching or "bio" not in matching[0]:
        return CheckResult(
            id="S1", name="bio field on user responses", status="fail",
            note="GET /users (list) item missing `bio` key for the test user",
        )

    return CheckResult(
        id="S1", name="bio field on user responses", status="pass",
        note="`bio` key present in POST, GET single, and GET list responses",
    )


# ---------------------------------------------------------------------------
# S2 — post_count field on user responses
# ---------------------------------------------------------------------------

def s2_post_count(client: Client, claimed_keys: set[str]) -> CheckResult:
    """post_count present and accurate on user views; updates as posts are added."""
    u = _uniq("count")
    r_create = client.post("/users", json_body={"username": u})
    if r_create.status != 201:
        return CheckResult(
            id="S2", name="post_count on user responses", status="error",
            note=f"could not create test user (POST /users -> {r_create.status})",
        )

    r_get = client.get(f"/users/{u}")
    if r_get.status != 200 or "post_count" not in (r_get.json() or {}):
        return CheckResult(
            id="S2", name="post_count on user responses",
            status=_absent("post_count", claimed_keys),
            note=("README claims post_count; GET /users/{u} returned no `post_count` key"
                  if "post_count" in claimed_keys
                  else "feature not implemented"),
        )

    if r_get.json().get("post_count") != 0:
        return CheckResult(
            id="S2", name="post_count on user responses", status="fail",
            note=f"new user has post_count={r_get.json().get('post_count')!r}, expected 0",
        )

    # Create two posts and re-check.
    for i in range(2):
        rp = client.post("/posts",
                         json_body={"message": f"silver count {i}"},
                         headers={"X-Username": u})
        if rp.status != 201:
            return CheckResult(
                id="S2", name="post_count on user responses", status="error",
                note=f"POST /posts failed during S2 setup (status={rp.status})",
            )

    r_after = client.get(f"/users/{u}")
    if r_after.json().get("post_count") != 2:
        return CheckResult(
            id="S2", name="post_count on user responses", status="fail",
            note=f"after 2 posts, post_count={r_after.json().get('post_count')!r}, expected 2",
        )

    r_list = client.get("/users")
    matching = [x for x in (r_list.json() or []) if x.get("username") == u]
    if not matching or matching[0].get("post_count") != 2:
        return CheckResult(
            id="S2", name="post_count on user responses", status="fail",
            note="GET /users (list) post_count out of sync with detail view",
        )

    return CheckResult(
        id="S2", name="post_count on user responses", status="pass",
        note="post_count=0 on new user; =2 after 2 posts; consistent in list view",
    )


# ---------------------------------------------------------------------------
# S3 — PATCH /users/{username}
# ---------------------------------------------------------------------------

def s3_patch_user(client: Client, claimed_keys: set[str]) -> CheckResult:
    """PATCH /users/{u} updates bio; 200 / 404 / 422 contracts."""
    u = _uniq("patch_u")
    r_create = client.post("/users", json_body={"username": u, "bio": "before"})
    if r_create.status != 201:
        # Bio param may be rejected by bronze-only servers — try without bio.
        r_create = client.post("/users", json_body={"username": u})
        if r_create.status != 201:
            return CheckResult(
                id="S3", name="PATCH /users/{u}", status="error",
                note=f"setup failed: POST /users -> {r_create.status}",
            )

    # Presence probe.
    r_probe = client.patch(f"/users/{u}", json_body={"bio": "after"})
    if r_probe.status in (404, 405) or r_probe.error:
        return CheckResult(
            id="S3", name="PATCH /users/{u}",
            status=_absent("patch_users", claimed_keys),
            note=("README claims PATCH /users/{u}; route returns "
                  f"{r_probe.status or r_probe.error}"
                  if "patch_users" in claimed_keys
                  else "feature not implemented"),
        )
    if r_probe.status != 200:
        return CheckResult(
            id="S3", name="PATCH /users/{u}", status="fail",
            note=f"PATCH /users/{{u}} returned {r_probe.status}, expected 200",
        )
    if "after" not in str(r_probe.json() or {}):
        return CheckResult(
            id="S3", name="PATCH /users/{u}", status="fail",
            note="PATCH succeeded but response doesn't reflect the new bio",
        )

    # 404 on unknown user.
    r_404 = client.patch(f"/users/{_uniq('ghost')}", json_body={"bio": "x"})
    if r_404.status != 404:
        return CheckResult(
            id="S3", name="PATCH /users/{u}", status="fail",
            note=f"PATCH on unknown user returned {r_404.status}, expected 404",
        )

    # 422 on bio>200.
    r_422 = client.patch(f"/users/{u}", json_body={"bio": "x" * 201})
    if r_422.status not in (400, 422):
        return CheckResult(
            id="S3", name="PATCH /users/{u}", status="fail",
            note=f"PATCH with bio>200 returned {r_422.status}, expected 422 (or 400)",
        )

    return CheckResult(
        id="S3", name="PATCH /users/{u}", status="pass",
        note="200 + bio updated; 404 unknown; 422 oversized bio",
    )


# ---------------------------------------------------------------------------
# S4 — PATCH /posts/{id}
# ---------------------------------------------------------------------------

def s4_patch_post(client: Client, claimed_keys: set[str]) -> CheckResult:
    """PATCH /posts/{id} edits message; response includes updated_at."""
    u = _uniq("patch_p")
    if client.post("/users", json_body={"username": u}).status != 201:
        return CheckResult(
            id="S4", name="PATCH /posts/{id}", status="error",
            note="setup failed: could not create test user",
        )
    r_post = client.post("/posts",
                         json_body={"message": "before"},
                         headers={"X-Username": u})
    if r_post.status != 201:
        return CheckResult(
            id="S4", name="PATCH /posts/{id}", status="error",
            note=f"setup failed: POST /posts -> {r_post.status}",
        )
    pid = (r_post.json() or {}).get("id")
    if pid is None:
        return CheckResult(
            id="S4", name="PATCH /posts/{id}", status="error",
            note="setup: POST /posts response missing `id`",
        )

    # Send X-Username matching the post's author so ownership-enforcing
    # designs (rubric-allowed) reach the 200 path instead of 400/403.
    auth = {"X-Username": u}

    r_probe = client.patch(f"/posts/{pid}", json_body={"message": "after"}, headers=auth)
    if r_probe.status in (404, 405) or r_probe.error:
        return CheckResult(
            id="S4", name="PATCH /posts/{id}",
            status=_absent("patch_posts", claimed_keys),
            note=("README claims PATCH /posts/{id}; route returns "
                  f"{r_probe.status or r_probe.error}"
                  if "patch_posts" in claimed_keys
                  else "feature not implemented"),
        )
    if r_probe.status != 200:
        return CheckResult(
            id="S4", name="PATCH /posts/{id}", status="fail",
            note=f"PATCH /posts/{{id}} returned {r_probe.status}, expected 200",
        )
    body = r_probe.json() or {}
    if body.get("message") != "after":
        return CheckResult(
            id="S4", name="PATCH /posts/{id}", status="fail",
            note=f"PATCH succeeded but message is {body.get('message')!r}, expected 'after'",
        )
    if "updated_at" not in body:
        return CheckResult(
            id="S4", name="PATCH /posts/{id}", status="fail",
            note="PATCH response missing `updated_at` field",
        )

    r_404 = client.patch("/posts/9999999", json_body={"message": "x"}, headers=auth)
    if r_404.status != 404:
        return CheckResult(
            id="S4", name="PATCH /posts/{id}", status="fail",
            note=f"PATCH on bogus id returned {r_404.status}, expected 404",
        )

    r_422 = client.patch(f"/posts/{pid}", json_body={"message": ""}, headers=auth)
    if r_422.status not in (400, 422):
        return CheckResult(
            id="S4", name="PATCH /posts/{id}", status="fail",
            note=f"PATCH with empty message returned {r_422.status}, expected 422",
        )

    return CheckResult(
        id="S4", name="PATCH /posts/{id}", status="pass",
        note="200 + message updated + updated_at present; 404 bogus; 422 empty",
    )


# ---------------------------------------------------------------------------
# S5 — ?username= filter on /posts
# ---------------------------------------------------------------------------

def s5_username_filter(client: Client, claimed_keys: set[str]) -> CheckResult:
    """GET /posts?username=alice filters by author; composes with q+limit+offset.

    SKIP detection: a server that doesn't implement the filter silently
    drops the unknown query param. We create two users with disjoint posts
    and check whether the filtered response excludes the other user — if
    not, the filter is unimplemented.
    """
    a = _uniq("filterA")
    b = _uniq("filterB")
    for u in (a, b):
        if client.post("/users", json_body={"username": u}).status != 201:
            return CheckResult(
                id="S5", name="?username= filter on /posts", status="error",
                note=f"setup failed: could not create user {u}",
            )

    needle = uuid.uuid4().hex[:8]
    for msg in (f"alpha {needle} 1", f"alpha {needle} 2"):
        if client.post("/posts", json_body={"message": msg},
                       headers={"X-Username": a}).status != 201:
            return CheckResult(id="S5", name="?username= filter on /posts",
                               status="error", note="setup failed creating A's posts")
    for msg in (f"beta {needle} 1", f"beta {needle} 2"):
        if client.post("/posts", json_body={"message": msg},
                       headers={"X-Username": b}).status != 201:
            return CheckResult(id="S5", name="?username= filter on /posts",
                               status="error", note="setup failed creating B's posts")

    # Presence probe: filter A. If response contains B's posts, filter
    # is unimplemented (server silently dropped the unknown query param).
    r_filt = client.get("/posts", params={"username": a, "q": needle, "limit": 50})
    if r_filt.status != 200:
        return CheckResult(
            id="S5", name="?username= filter on /posts", status="fail",
            note=f"GET /posts?username=A returned {r_filt.status}",
        )
    items = r_filt.json() or []
    if not isinstance(items, list) or not all(isinstance(p, dict) for p in items):
        return CheckResult(
            id="S5", name="?username= filter on /posts", status="fail",
            note=f"GET /posts response shape unexpected (not list of objects): {type(items).__name__}",
        )
    has_b = any(p.get("username") == b for p in items)
    has_a = any(p.get("username") == a for p in items)
    if has_b or not has_a:
        if has_b:
            return CheckResult(
                id="S5", name="?username= filter on /posts",
                status=_absent("username_filter", claimed_keys),
                note=("README claims ?username=; B's posts leaked into A's filtered response"
                      if "username_filter" in claimed_keys
                      else "feature not implemented"),
            )
        return CheckResult(
            id="S5", name="?username= filter on /posts", status="fail",
            note="?username= filter returns empty even though A has posts",
        )

    # Compose with q.
    r_q = client.get("/posts", params={"username": a, "q": "alpha", "limit": 50})
    items_q = r_q.json() or []
    if not isinstance(items_q, list) or not all(isinstance(p, dict) for p in items_q):
        return CheckResult(
            id="S5", name="?username= filter on /posts", status="fail",
            note=f"GET /posts?q= response shape unexpected: {type(items_q).__name__}",
        )
    if not items_q:
        return CheckResult(
            id="S5", name="?username= filter on /posts", status="fail",
            note="?username=A&q=alpha returned empty list (A has 2 matching posts)",
        )
    if any(p.get("username") == b for p in items_q):
        return CheckResult(
            id="S5", name="?username= filter on /posts", status="fail",
            note="?username=A&q=alpha leaked B's posts",
        )
    if not all("alpha" in (p.get("message") or "") for p in items_q):
        return CheckResult(
            id="S5", name="?username= filter on /posts", status="fail",
            note="?username=A&q=alpha returned posts not matching q",
        )

    # Compose with limit + offset.
    r_paged = client.get("/posts", params={"username": a, "limit": 1, "offset": 0})
    if (r_paged.json() or []).__len__() != 1:
        return CheckResult(
            id="S5", name="?username= filter on /posts", status="fail",
            note=f"?username=A&limit=1 returned {len(r_paged.json() or [])} items",
        )

    # Empty for nonexistent user.
    r_none = client.get("/posts", params={"username": _uniq("nobody")})
    if (r_none.json() or []) != []:
        return CheckResult(
            id="S5", name="?username= filter on /posts", status="fail",
            note="?username=<unknown> returned non-empty list",
        )

    return CheckResult(
        id="S5", name="?username= filter on /posts", status="pass",
        note="filters; composes with q + limit/offset; empty for unknown user",
    )


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------

_CHECKS = [
    ("S1", "bio field on user responses",   s1_bio_field),
    ("S2", "post_count on user responses",  s2_post_count),
    ("S3", "PATCH /users/{u}",              s3_patch_user),
    ("S4", "PATCH /posts/{id}",             s4_patch_post),
    ("S5", "?username= filter on /posts",   s5_username_filter),
]


def run(client: Client, claimed_keys: set[str]) -> list[CheckResult]:
    """Run all silver checks against an already-running student server.

    Each check is shielded from raising — an unexpected exception (typically
    from a malformed student response shape) becomes a CheckResult with
    status="error" so the rest of the cohort run continues.
    """
    results: list[CheckResult] = []
    for check_id, name, fn in _CHECKS:
        try:
            results.append(fn(client, claimed_keys))
        except Exception as e:
            results.append(CheckResult(
                id=check_id, name=name, status="error",
                note=f"{type(e).__name__}: {e}"[:300],
            ))
    return results
