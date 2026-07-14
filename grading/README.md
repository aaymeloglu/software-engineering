# Grading harness

An assignment-grading harness for this course. It materializes each student's
submission from a class repo, runs a deterministic conformance check ("bronze"),
runs deterministic feature probes ("silver"), and then hands the code plus those
signals to an AI reviewer for the judgment-heavy part of the score.

It is partly agent-driven: the review step shells out to the `claude` CLI. If
you are an agent reading this, you can drive the whole thing from the commands
below.

## Setup

```bash
pip install -r requirements.txt

cp config.example.yaml config.yaml     # then edit: point class_repo at your repo
cp roster.example.yaml  roster.yaml     # then edit: your students

# The AI-review step needs the Claude CLI on PATH:
#   https://docs.claude.com/claude-code
```

`config.yaml` and `roster.yaml` are gitignored on purpose (see "What's not
here"). Everything cohort-, repo-, and weight-specific lives in `config.yaml`;
the harness code itself carries none of it.

## Configure

`config.example.yaml` is fully commented. The pieces:

- **`class_repo`** — a local clone of the repo students push to. Read-only.
- **`roster`** — path to your roster (handle to name/email).
- **`assignments`** — how each assignment maps onto branches / tags / paths in
  the class repo (e.g. `origin/bbs-webserver-{handle}`). `{handle}` is the
  student's GitHub handle.
- **`overrides`** — per-student knobs for anyone who deviated from the branch
  convention. The only place student-specific values belong.
- **`weights`** — points per bucket. The committed values are illustrative
  placeholders; set your own.

## Run

```bash
python run.py a2                  # grade every A2 submission
python run.py a2 --student <handle>
python run.py a2 --discover       # list submissions, don't grade
python run.py a2 --review         # include the AI review pass
```

`run.py` drives `a1`, `a2`, `a3`. Each writes a per-student markdown report and
a JSON sidecar, plus a class summary.

**A4** (a React frontend) has its own flow, since most of what makes a frontend
good is visual and stateful rather than API-checkable:

```bash
python assignments/a4/analyze.py         # static signals for every submission
bash   assignments/a4/build_check.sh     # npm install + build, per submission
bash   run_student.sh <handle>           # stand up one student's full stack to view
```

## How a score is built

- **Bronze** — deterministic conformance. The harness boots the student's server
  in an isolated venv and hits the required endpoints. Pass/fail per check.
- **Silver** — deterministic probes for the spec'd optional features.
- **AI review** — `harness/review.py` builds a prompt (rubric + numbered source
  + bronze/silver results) and calls `claude -p --model opus`. It writes the
  design review, verifies feature claims against the code, and proposes a final
  score. This is guidance for the grader, not an automatic grade.

## What's not here

This is a public copy. A few things are intentionally absent so that reusing the
harness does not hand out answers or bake in one course's private choices:

- **No reference solutions or answer keys.** Assignment reference
  implementations and test suites are not published.
- **No real point weights.** `config.example.yaml` ships illustrative
  placeholders; keep your real split in your gitignored `config.yaml`.
- **`assignments/a3/bug_catalog.py` is an empty stub.** A3 is a test-first bug
  hunt; the real catalog (the bugs students' tests are checked against) is the
  answer key. Drop in your own catalog with the documented shape to grade A3.
  Point `assignments.a3.reference_root` in `config.yaml` at your A3 reference
  materials.
- **No student work.** `work/` (materialized submissions) and `reports/`
  (generated per-student reports) are gitignored.

## Layout

```
config.example.yaml   copy to config.yaml
roster.example.yaml   copy to roster.yaml
requirements.txt
run.py                orchestrator for a1/a2/a3
run_student.sh        stand up one A4 student's backend + frontend
harness/              framework: config, checkout, roster, runner, server, review, report
assignments/          per-assignment checkers (a1..a4)
scripts/              copy_detect.py (cross-submission similarity)
tests/                the harness's own tests
```
