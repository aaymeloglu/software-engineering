"""Bronze conformance checks for Assignment 2 (BBS Webserver).

Each B-check is one CheckResult. Within a group, ALL sub-checks must pass
for the group to count as a pass — mirrors verify_api.py's group semantics.
The first failing sub-check's detail goes into the note for debuggability.

Server lifecycle is owned by `harness.server.spawn_server`; this module
just consumes the connected Client.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from harness.runner import CheckResult
from harness.server import Client, Response


# ----------------------------------------------------------------------------
# Check helpers
# ----------------------------------------------------------------------------

@dataclass
class SubCheck:
    name: str
    ok: bool
    detail: str = ""


def _group(check_id: str, name: str, subs: list[SubCheck]) -> CheckResult:
    failed = [s for s in subs if not s.ok]
    if not failed:
        return CheckResult(id=check_id, name=name, status="pass",
                           note=f"{len(subs)} sub-checks passed")
    first = failed[0]
    note = f"{first.name}"
    if first.detail:
        note += f" — {first.detail}"
    if len(failed) > 1:
        note += f" (+{len(failed)-1} more)"
    return CheckResult(id=check_id, name=name, status="fail", note=note[:600])


def _all_skipped(reason: str) -> list[CheckResult]:
    names = [
        "Server starts",
        "POST /users happy path + response shape",
        "POST /users error cases (409, 422)",
        "GET /users + GET /users/{username} + 404",
        "POST /posts happy path + response shape",
        "POST /posts error cases (400, 404, 422)",
        "GET /posts + GET /posts/{id} + GET /users/{u}/posts",
        "Search ?q= filtering",
        "DELETE /posts/{id}",
        "Pagination + Query() validation",
    ]
    return [
        CheckResult(
            id=f"B{i+1}",
            name=n,
            status="error" if i == 0 else "fail",
            note=reason if i == 0 else "skipped (server didn't start)",
        )
        for i, n in enumerate(names)
    ]


# ----------------------------------------------------------------------------
# Per-check probes
# ----------------------------------------------------------------------------

USER_FIELDS = {"username", "created_at"}
POST_FIELDS = {"id", "username", "message", "created_at"}


def _check_b1(c: Client, state: dict) -> CheckResult:
    subs = [SubCheck("server reachable", True)]
    return _group("B1", "Server starts", subs)


def _check_b2(c: Client, state: dict) -> CheckResult:
    alice = state["alice"]
    subs = []
    r = c.post("/users", json_body={"username": alice})
    subs.append(SubCheck(f"POST /users {alice} → 201", r.status == 201, f"got {r.status}: {r.body[:200]!r}"))
    if r.status == 201:
        body = r.json() or {}
        keys_ok = isinstance(body, dict) and USER_FIELDS.issubset(body.keys())
        missing = USER_FIELDS - (set(body.keys()) if isinstance(body, dict) else set())
        subs.append(SubCheck(
            "response includes {username, created_at}",
            keys_ok,
            f"missing {sorted(missing)}; got keys {sorted(body.keys()) if isinstance(body, dict) else type(body).__name__}",
        ))
        subs.append(SubCheck(
            f"response username == {alice}",
            isinstance(body, dict) and body.get("username") == alice,
            f"got {body!r}",
        ))
    return _group("B2", "POST /users happy path + response shape", subs)


def _check_b3(c: Client, state: dict) -> CheckResult:
    alice = state["alice"]
    subs = []
    # duplicate
    r = c.post("/users", json_body={"username": alice})
    subs.append(SubCheck("duplicate user → 409", r.status == 409, f"got {r.status}"))
    # too short
    r = c.post("/users", json_body={"username": "ab"})
    subs.append(SubCheck("too-short username → 422", r.status == 422, f"got {r.status}"))
    # invalid chars
    r = c.post("/users", json_body={"username": "has spaces"})
    subs.append(SubCheck("invalid chars → 422", r.status == 422, f"got {r.status}"))
    # missing field
    r = c.post("/users", json_body={})
    subs.append(SubCheck("missing username field → 422", r.status == 422, f"got {r.status}"))
    return _group("B3", "POST /users error cases (409, 422)", subs)


def _check_b4(c: Client, state: dict) -> CheckResult:
    alice = state["alice"]
    bob = state["bob"]
    ghost = state["ghost"]
    subs = []
    r = c.post("/users", json_body={"username": bob})
    subs.append(SubCheck(f"create {bob}", r.status == 201, f"got {r.status}"))

    r = c.get("/users")
    subs.append(SubCheck("GET /users → 200", r.status == 200, f"got {r.status}"))
    if r.status == 200:
        users = r.json()
        ok_array = isinstance(users, list)
        subs.append(SubCheck("GET /users returns array", ok_array, f"got {type(users).__name__}"))
        if ok_array:
            usernames = [u.get("username") for u in users if isinstance(u, dict)]
            subs.append(SubCheck(
                f"includes {alice} and {bob}",
                alice in usernames and bob in usernames,
                f"usernames sample: {usernames[:5]}",
            ))

    r = c.get(f"/users/{alice}")
    subs.append(SubCheck(f"GET /users/{alice} → 200", r.status == 200, f"got {r.status}"))
    if r.status == 200:
        body = r.json() or {}
        subs.append(SubCheck(
            f"body.username == {alice}",
            isinstance(body, dict) and body.get("username") == alice,
            f"got {body!r}",
        ))

    r = c.get(f"/users/{ghost}")
    subs.append(SubCheck(f"GET /users/{ghost} → 404", r.status == 404, f"got {r.status}"))

    return _group("B4", "GET /users + GET /users/{username} + 404", subs)


def _check_b5(c: Client, state: dict) -> CheckResult:
    alice = state["alice"]
    msg = "hello world"
    subs = []
    r = c.post("/posts", json_body={"message": msg}, headers={"X-Username": alice})
    subs.append(SubCheck("POST /posts → 201", r.status == 201, f"got {r.status}: {r.body[:200]!r}"))
    if r.status == 201:
        body = r.json() or {}
        keys_ok = isinstance(body, dict) and POST_FIELDS.issubset(body.keys())
        missing = POST_FIELDS - (set(body.keys()) if isinstance(body, dict) else set())
        subs.append(SubCheck(
            "response includes {id, username, message, created_at}",
            keys_ok,
            f"missing {sorted(missing)}; got keys {sorted(body.keys()) if isinstance(body, dict) else type(body).__name__}",
        ))
        if isinstance(body, dict):
            subs.append(SubCheck("response.username == X-Username", body.get("username") == alice,
                                 f"got {body.get('username')!r}"))
            subs.append(SubCheck("response.message matches body", body.get("message") == msg,
                                 f"got {body.get('message')!r}"))
            if "id" in body:
                state["alice_post_id"] = body["id"]
    return _group("B5", "POST /posts happy path + response shape", subs)


def _check_b6(c: Client, state: dict) -> CheckResult:
    alice = state["alice"]
    ghost = state["ghost"]
    subs = []

    r = c.post("/posts", json_body={"message": "hi"})
    subs.append(SubCheck("missing X-Username → 400", r.status == 400, f"got {r.status}"))

    r = c.post("/posts", json_body={"message": "hi"}, headers={"X-Username": ghost})
    subs.append(SubCheck(f"unknown user {ghost} → 404", r.status == 404, f"got {r.status}"))

    r = c.post("/posts", json_body={"message": ""}, headers={"X-Username": alice})
    subs.append(SubCheck("empty message → 422", r.status == 422, f"got {r.status}"))

    r = c.post("/posts", json_body={"message": "x" * 501}, headers={"X-Username": alice})
    subs.append(SubCheck("501-char message → 422", r.status == 422, f"got {r.status}"))

    r = c.post("/posts", json_body={}, headers={"X-Username": alice})
    subs.append(SubCheck("missing message field → 422", r.status == 422, f"got {r.status}"))

    return _group("B6", "POST /posts error cases (400, 404, 422)", subs)


def _check_b7(c: Client, state: dict) -> CheckResult:
    alice = state["alice"]
    bob = state["bob"]
    ghost = state["ghost"]
    subs = []

    # Make sure bob has at least one post
    r = c.post("/posts", json_body={"message": "second post"}, headers={"X-Username": bob})
    if r.status == 201:
        state["bob_post_id"] = (r.json() or {}).get("id")

    r = c.get("/posts")
    subs.append(SubCheck("GET /posts → 200", r.status == 200, f"got {r.status}"))
    if r.status == 200:
        posts = r.json()
        subs.append(SubCheck("GET /posts is array", isinstance(posts, list),
                             f"got {type(posts).__name__}"))

    pid = state.get("alice_post_id")
    if pid is not None:
        r = c.get(f"/posts/{pid}")
        subs.append(SubCheck(f"GET /posts/{pid} → 200", r.status == 200, f"got {r.status}"))

    r = c.get("/posts/99999999")
    subs.append(SubCheck("GET /posts/99999999 → 404", r.status == 404, f"got {r.status}"))

    r = c.get(f"/users/{alice}/posts")
    subs.append(SubCheck(f"GET /users/{alice}/posts → 200", r.status == 200, f"got {r.status}"))
    if r.status == 200:
        posts = r.json()
        if isinstance(posts, list):
            only_alice = all(isinstance(p, dict) and p.get("username") == alice for p in posts)
            subs.append(SubCheck(
                f"all posts belong to {alice}",
                only_alice and len(posts) >= 1,
                f"got {len(posts)} posts",
            ))

    r = c.get(f"/users/{ghost}/posts")
    subs.append(SubCheck(f"GET /users/{ghost}/posts → 404", r.status == 404, f"got {r.status}"))

    return _group("B7", "GET /posts + GET /posts/{id} + GET /users/{u}/posts", subs)


def _check_b8(c: Client, state: dict) -> CheckResult:
    alice = state["alice"]
    needle = state["needle"]
    subs = []
    r = c.post("/posts", json_body={"message": f"a post with {needle} in it"},
               headers={"X-Username": alice})
    subs.append(SubCheck("seed search post", r.status == 201, f"got {r.status}"))
    c.post("/posts", json_body={"message": "a noisy unrelated post"},
           headers={"X-Username": alice})

    r = c.get("/posts", params={"q": needle})
    subs.append(SubCheck(f"GET /posts?q={needle} → 200", r.status == 200, f"got {r.status}"))
    if r.status == 200:
        matches = r.json()
        if isinstance(matches, list):
            ok_match = all(needle in (p.get("message") or "") for p in matches if isinstance(p, dict))
            subs.append(SubCheck(
                f"all matches contain {needle!r}",
                ok_match and len(matches) >= 1,
                f"{len(matches)} matches; sample: "
                f"{[p.get('message') for p in matches[:3]] if matches else []}",
            ))
    return _group("B8", "Search ?q= filtering", subs)


def _check_b9(c: Client, state: dict) -> CheckResult:
    alice = state["alice"]
    subs = []
    # Fresh post to delete.
    r = c.post("/posts", json_body={"message": "to be deleted"},
               headers={"X-Username": alice})
    subs.append(SubCheck("create post for delete test", r.status == 201, f"got {r.status}"))
    if r.status != 201:
        return _group("B9", "DELETE /posts/{id}", subs)
    pid = (r.json() or {}).get("id")

    r = c.delete(f"/posts/{pid}")
    subs.append(SubCheck(f"DELETE /posts/{pid} → 204", r.status == 204, f"got {r.status}"))

    r = c.get(f"/posts/{pid}")
    subs.append(SubCheck(f"GET /posts/{pid} after delete → 404", r.status == 404, f"got {r.status}"))

    r = c.delete("/posts/99999999")
    subs.append(SubCheck("DELETE /posts/99999999 → 404", r.status == 404, f"got {r.status}"))

    return _group("B9", "DELETE /posts/{id}", subs)


def _check_b10(c: Client, state: dict) -> CheckResult:
    alice = state["alice"]
    subs = []

    # Make sure there are at least 3 posts.
    for i in range(3):
        c.post("/posts", json_body={"message": f"pagination seed {i} {state['needle']}"},
               headers={"X-Username": alice})

    r = c.get("/posts", params={"limit": 1})
    subs.append(SubCheck("limit=1 → 200", r.status == 200, f"got {r.status}"))
    if r.status == 200:
        items = r.json()
        if isinstance(items, list):
            subs.append(SubCheck("limit=1 returns ≤1 items",
                                 len(items) <= 1, f"got {len(items)}"))

    # offset behaviour: 2 items at offset=0 vs 1 item at offset=1 of those two
    r0 = c.get("/posts", params={"limit": 2, "offset": 0})
    r1 = c.get("/posts", params={"limit": 2, "offset": 1})
    if r0.status == 200 and r1.status == 200:
        a = r0.json() if isinstance(r0.json(), list) else []
        b = r1.json() if isinstance(r1.json(), list) else []
        if a and b:
            ids_a = [p.get("id") for p in a if isinstance(p, dict)]
            ids_b = [p.get("id") for p in b if isinstance(p, dict)]
            subs.append(SubCheck(
                "offset shifts the window",
                ids_a != ids_b and (len(ids_a) >= 2 and ids_a[1] in ids_b
                                    if len(ids_a) >= 2 else True),
                f"offset=0 ids={ids_a} offset=1 ids={ids_b}",
            ))

    r = c.get("/posts", params={"limit": 0})
    subs.append(SubCheck("limit=0 → 422", r.status == 422, f"got {r.status}"))

    r = c.get("/posts", params={"limit": 500})
    subs.append(SubCheck("limit=500 → 422", r.status == 422, f"got {r.status}"))

    r = c.get("/posts", params={"offset": -1})
    subs.append(SubCheck("offset=-1 → 422", r.status == 422, f"got {r.status}"))

    return _group("B10", "Pagination + Query() validation", subs)


# ----------------------------------------------------------------------------
# Top-level entries
# ----------------------------------------------------------------------------

def run(client: Client) -> list[CheckResult]:
    """Run B1..B10 against an already-running student server.

    State isolation: each B-check generates UUID-suffixed identifiers via
    the shared `state` dict, so checks don't collide with each other or
    with silver checks running in the same server lifecycle.
    """
    run_id = uuid.uuid4().hex[:8]
    state = {
        "alice": f"alice_{run_id}",
        "bob": f"bob_{run_id}",
        "ghost": f"ghost_{run_id}",
        "needle": f"needle_{run_id}",
    }
    return [
        _check_b1(client, state),
        _check_b2(client, state),
        _check_b3(client, state),
        _check_b4(client, state),
        _check_b5(client, state),
        _check_b6(client, state),
        _check_b7(client, state),
        _check_b8(client, state),
        _check_b9(client, state),
        _check_b10(client, state),
    ]


