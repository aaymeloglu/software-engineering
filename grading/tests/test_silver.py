"""Unit tests for silver harness components."""
from __future__ import annotations

from pathlib import Path

from assignments.a2.worksheet import build_worksheet


def test_worksheet_claim_keys_extracted(tmp_path: Path):
    work = tmp_path / "submission"
    work.mkdir()
    (work / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    (work / "README.md").write_text(
        "# Silver\n- bio field on users\n- PATCH /users to update bio\n"
    )
    _, payload = build_worksheet("test", None, work)
    assert "bio" in payload["claim_keys"]["silver"]
    assert "patch_users" in payload["claim_keys"]["silver"]
    assert "patch_posts" not in payload["claim_keys"]["silver"]


from assignments.a2 import silver


def test_s1_bio_pass_on_full(app_full):
    r = silver.s1_bio_field(app_full, claimed_keys=set())
    assert r.id == "S1"
    assert r.status == "pass", f"got {r.status}: {r.note}"


def test_s1_bio_skip_when_absent_and_unclaimed(app_none):
    r = silver.s1_bio_field(app_none, claimed_keys=set())
    assert r.status == "skip"


def test_s1_bio_claim_mismatch_when_claimed_but_absent(app_mismatch):
    r = silver.s1_bio_field(app_mismatch, claimed_keys={"bio"})
    assert r.status == "claim_mismatch"


def test_s2_post_count_pass_on_full(app_full):
    r = silver.s2_post_count(app_full, claimed_keys=set())
    assert r.status == "pass", r.note


def test_s2_post_count_skip_on_none(app_none):
    r = silver.s2_post_count(app_none, claimed_keys=set())
    assert r.status == "skip"


def test_s2_post_count_claim_mismatch(app_mismatch):
    r = silver.s2_post_count(app_mismatch, claimed_keys={"post_count"})
    assert r.status == "claim_mismatch"


def test_s3_patch_users_pass(app_full):
    r = silver.s3_patch_user(app_full, claimed_keys=set())
    assert r.status == "pass", r.note


def test_s3_patch_users_skip(app_none):
    r = silver.s3_patch_user(app_none, claimed_keys=set())
    assert r.status == "skip"


def test_s3_patch_users_claim_mismatch(app_mismatch):
    r = silver.s3_patch_user(app_mismatch, claimed_keys={"patch_users"})
    assert r.status == "claim_mismatch"


def test_s4_patch_posts_pass(app_full):
    r = silver.s4_patch_post(app_full, claimed_keys=set())
    assert r.status == "pass", r.note


def test_s4_patch_posts_skip(app_none):
    r = silver.s4_patch_post(app_none, claimed_keys=set())
    assert r.status == "skip"


def test_s4_patch_posts_claim_mismatch(app_mismatch):
    r = silver.s4_patch_post(app_mismatch, claimed_keys={"patch_posts"})
    assert r.status == "claim_mismatch"


def test_s5_username_filter_pass(app_full):
    r = silver.s5_username_filter(app_full, claimed_keys=set())
    assert r.status == "pass", r.note


def test_s5_username_filter_skip(app_none):
    r = silver.s5_username_filter(app_none, claimed_keys=set())
    assert r.status == "skip"


def test_s5_username_filter_claim_mismatch(app_mismatch):
    r = silver.s5_username_filter(app_mismatch, claimed_keys={"username_filter"})
    assert r.status == "claim_mismatch"


def test_silver_run_all_pass_on_full(app_full):
    results = silver.run(app_full, claimed_keys=set())
    assert [r.id for r in results] == ["S1", "S2", "S3", "S4", "S5"]
    bad = [r for r in results if r.status != "pass"]
    assert not bad, "\n".join(f"{r.id}: {r.status} — {r.note}" for r in bad)


def test_silver_run_all_skip_on_none(app_none):
    results = silver.run(app_none, claimed_keys=set())
    assert all(r.status == "skip" for r in results), \
        "\n".join(f"{r.id}: {r.status} — {r.note}" for r in results)


def test_silver_run_all_claim_mismatch_on_mismatch(app_mismatch):
    claimed = {"bio", "post_count", "patch_users", "patch_posts", "username_filter"}
    results = silver.run(app_mismatch, claimed_keys=claimed)
    assert all(r.status == "claim_mismatch" for r in results), \
        "\n".join(f"{r.id}: {r.status} — {r.note}" for r in results)


from harness.runner import CheckResult
from harness.report import render_silver_section


def test_render_silver_section_counts_pass_and_mismatch():
    checks = [
        CheckResult(id="S1", name="bio field", status="pass", note="ok"),
        CheckResult(id="S2", name="post_count", status="skip", note="not impl"),
        CheckResult(id="S3", name="PATCH /users", status="claim_mismatch", note="claimed but absent"),
    ]
    md = render_silver_section(checks)
    assert "## Silver — 1/3 verified, 1 claim mismatch" in md
    assert "S1" in md and "S3" in md
    assert "claim_mismatch" in md


def test_render_silver_section_empty():
    assert render_silver_section([]) == ""
