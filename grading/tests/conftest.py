"""Test fixtures: spin up a reference FastAPI app for silver-check unit tests.

Three flavors:
  - full     — every silver feature implemented correctly
  - none     — no silver features (just bronze contract)
  - mismatch — README claims silver features, but app doesn't implement them

Each fixture writes a main.py to a tempdir, then spawns uvicorn against it via
harness.server.spawn_server, yielding a Client.
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

GRADING_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GRADING_ROOT))

from harness.runner import Runner
from harness.server import spawn_server


# ---- Reference main.py templates ---------------------------------------

# Bronze contract only. Stores users + posts in module-level dicts.
APP_NONE = textwrap.dedent('''
    from fastapi import FastAPI, Header, HTTPException, Query
    from pydantic import BaseModel, constr
    from datetime import datetime
    import itertools

    app = FastAPI()
    USERS = {}        # username -> {username, created_at}
    POSTS = {}        # id -> {id, username, message, created_at}
    _ID = itertools.count(1)

    class UserIn(BaseModel):
        username: constr(min_length=1, max_length=50)

    class PostIn(BaseModel):
        message: constr(min_length=1, max_length=500)

    @app.post("/users", status_code=201)
    def create_user(p: UserIn):
        if p.username in USERS:
            raise HTTPException(409, "exists")
        u = {"username": p.username, "created_at": datetime.utcnow().isoformat()}
        USERS[p.username] = u
        return u

    @app.get("/users")
    def list_users():
        return list(USERS.values())

    @app.get("/users/{u}")
    def get_user(u: str):
        if u not in USERS:
            raise HTTPException(404, "not found")
        return USERS[u]

    @app.post("/posts", status_code=201)
    def create_post(p: PostIn, x_username: str = Header(...)):
        if x_username not in USERS:
            raise HTTPException(404, "user not found")
        i = next(_ID)
        post = {"id": i, "username": x_username, "message": p.message,
                "created_at": datetime.utcnow().isoformat()}
        POSTS[i] = post
        return post

    @app.get("/posts")
    def list_posts(q: str | None = None,
                   limit: int = Query(50, ge=1, le=200),
                   offset: int = Query(0, ge=0)):
        items = list(POSTS.values())
        if q:
            items = [p for p in items if q in p["message"]]
        return items[offset:offset+limit]
''').strip()

# All five silver features wired correctly.
APP_FULL = textwrap.dedent('''
    from fastapi import FastAPI, Header, HTTPException, Query
    from pydantic import BaseModel, constr
    from datetime import datetime
    from typing import Optional
    import itertools

    app = FastAPI()
    USERS = {}
    POSTS = {}
    _ID = itertools.count(1)

    class UserIn(BaseModel):
        username: constr(min_length=1, max_length=50)
        bio: Optional[constr(max_length=200)] = None

    class UserPatch(BaseModel):
        bio: constr(max_length=200)

    class PostIn(BaseModel):
        message: constr(min_length=1, max_length=500)

    class PostPatch(BaseModel):
        message: constr(min_length=1, max_length=500)

    def _user_view(u):
        return {**u, "post_count": sum(1 for p in POSTS.values()
                                       if p["username"] == u["username"])}

    @app.post("/users", status_code=201)
    def create_user(p: UserIn):
        if p.username in USERS:
            raise HTTPException(409, "exists")
        u = {"username": p.username, "bio": p.bio or "",
             "created_at": datetime.utcnow().isoformat()}
        USERS[p.username] = u
        return _user_view(u)

    @app.get("/users")
    def list_users():
        return [_user_view(u) for u in USERS.values()]

    @app.get("/users/{u}")
    def get_user(u: str):
        if u not in USERS:
            raise HTTPException(404)
        return _user_view(USERS[u])

    @app.patch("/users/{u}")
    def patch_user(u: str, p: UserPatch):
        if u not in USERS:
            raise HTTPException(404)
        USERS[u]["bio"] = p.bio
        return _user_view(USERS[u])

    @app.post("/posts", status_code=201)
    def create_post(p: PostIn, x_username: str = Header(...)):
        if x_username not in USERS:
            raise HTTPException(404)
        i = next(_ID)
        post = {"id": i, "username": x_username, "message": p.message,
                "created_at": datetime.utcnow().isoformat()}
        POSTS[i] = post
        return post

    @app.patch("/posts/{i}")
    def patch_post(i: int, p: PostPatch):
        if i not in POSTS:
            raise HTTPException(404)
        POSTS[i]["message"] = p.message
        POSTS[i]["updated_at"] = datetime.utcnow().isoformat()
        return POSTS[i]

    @app.get("/posts")
    def list_posts(q: Optional[str] = None,
                   username: Optional[str] = None,
                   limit: int = Query(50, ge=1, le=200),
                   offset: int = Query(0, ge=0)):
        items = list(POSTS.values())
        if username:
            items = [p for p in items if p["username"] == username]
        if q:
            items = [p for p in items if q in p["message"]]
        return items[offset:offset+limit]
''').strip()

# README mentions every feature, app implements none. Used to test CLAIM_MISMATCH.
README_FULL_CLAIMS = textwrap.dedent('''
    # BBS Webserver

    ## Silver features
    - bio field on users
    - post_count on user responses
    - PATCH /users to update bio
    - PATCH /posts to edit message
    - ?username= filter on /posts
''').strip()


# ---- Fixtures ----------------------------------------------------------

def _write_app(tmp_path: Path, source: str, readme: str = "# stub\n") -> Path:
    work = tmp_path / "submission"
    work.mkdir()
    (work / "main.py").write_text(source)
    (work / "requirements.txt").write_text("fastapi\nuvicorn\npydantic\n")
    (work / "README.md").write_text(readme)
    return work


def _runner_for(work: Path, tmp_path: Path) -> Runner:
    venv_dir = tmp_path / "venv"
    r = Runner(work, venv_dir)
    ok, log = r.setup_venv()
    assert ok, f"venv setup failed: {log[-500:]}"
    return r


@pytest.fixture
def app_full(tmp_path):
    """Reference server with every silver feature wired correctly."""
    work = _write_app(tmp_path, APP_FULL, readme=README_FULL_CLAIMS)
    runner = _runner_for(work, tmp_path)
    with spawn_server(runner, work) as client:
        yield client


@pytest.fixture
def app_none(tmp_path):
    """Reference server with no silver features (bronze contract only)."""
    work = _write_app(tmp_path, APP_NONE, readme="# stub\n")
    runner = _runner_for(work, tmp_path)
    with spawn_server(runner, work) as client:
        yield client


@pytest.fixture
def app_mismatch(tmp_path):
    """Bronze-only server, but README claims every silver feature."""
    work = _write_app(tmp_path, APP_NONE, readme=README_FULL_CLAIMS)
    runner = _runner_for(work, tmp_path)
    with spawn_server(runner, work) as client:
        yield client
