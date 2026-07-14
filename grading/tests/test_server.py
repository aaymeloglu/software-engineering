"""Smoke test: harness.server.spawn_server brings up a reference app."""

def test_full_app_responds(app_full):
    r = app_full.get("/users")
    assert r.status == 200, f"got {r.status}, error={r.error}"
    assert r.json() == []
