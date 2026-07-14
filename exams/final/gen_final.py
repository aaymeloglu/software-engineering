#!/usr/bin/env python3
"""Generate the real Final (student paper, no answers) and a separate solutions
PDF, from a selected list of question ids. Parallel to the Sample: same seven
categories, different questions and domains so the two papers do not overlap.

Run:  python3 gen_final.py   ->  final.html, final-solutions.html
"""
import os
from questions import (QBYID, DEFAULT_SPACE, BASE_CSS,
                       render_blocks, page)

# Real Final slate -- the HARD set, built for a 50-60 mean. Seven distinct
# topics; no question reused from the Sample; each has a counterintuitive core
# or real synthesis, not recall.
SELECTION = [
    "T3-Q5",   # Trace        -- React: `&&` renders a stray 0 on an empty cart  [T3]
    "T8-Q7",   # Trace        -- lost update on a counter, inside a transaction  [T8]
    "T9-Q7",   # Spot the bug -- transfer authz against client-supplied user_id  [T9]
    "T4-Q5",   # Short design -- React frontend: state, freshness, UI states      [T4]
    "T5-Q6",   # Specification-- ticket stampede: oversell + idempotency         [T5]
    "T2-Q4",   # Code review  -- useEffect fetch race vs active-flag cleanup     [T2]
    "T7-Q5",   # Short design -- CI->registry->deploy: latest tag, tests, secrets [T7]
]

META = [
    ("Format", "Pencil and paper. No computer, phone, notes, or coding agent."),
    ("Time", "150 minutes."),
    ("Length", "Seven questions."),
    ("Coverage", "Lectures 5.1 through 10.1 (JS/TS and the browser, React, deployment, "
                 "Docker, CI/CD, concurrency, security, agents), plus assignments 3 and 4."),
    ("Categories", "Trace-through, spot the bug, specification, code review, short design."),
    ("Grading", "Curved. The exam is intentionally hard; expect to leave some parts unfinished."),
]

AGENTS_BLURB = (
    "The whole semester has leaned into coding agents as the way real engineers work, so an exam "
    "that asks you to write working code from scratch on paper would punish you for taking the "
    "course seriously. Instead, the exam is built around being able to work with agents: "
    "reading code carefully, finding bugs by inspection, writing the spec you'd hand to the agent, "
    "judging which of two implementations is better, and making design calls under uncertainty.")


def cover():
    rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in META)
    nf = '<div class="name-field">Name: <span class="blank">&nbsp;</span></div>'
    return (f"{nf}<h1>Final Exam</h1>"
            f"<p class='subtitle'>Software Engineering — UATX — Spring 2026</p>"
            f"<table class='meta-table'>{rows}</table>"
            f"<h3>How this exam thinks about agents</h3><p>{AGENTS_BLURB}</p>")


# Questions that get a full extra blank page after them (more room to hand-write).
EXTRA_PAGE_AFTER = {2, 3, 5, 6}
EXTRA_CSS = "\n.extra-page { page-break-before: always; }\n"


def build_student():
    body = [cover()]
    for i, qid in enumerate(SELECTION, 1):
        q = QBYID[qid]
        space = q.get("space", DEFAULT_SPACE.get(q["type"], 5.0))
        body.append(f"""
<div class="question">
  <div class="q-header"><span class="q-id">Question {i}</span></div>
  {render_blocks(q['stem'])}
  <div class="lines" style="height: {space}in;">&nbsp;</div>
</div>""")
        if i in EXTRA_PAGE_AFTER:
            body.append('<div class="extra-page">&nbsp;</div>')
    return page("Final Exam", BASE_CSS + EXTRA_CSS, "\n".join(body))


def build_solutions():
    head = ("<h1>Final Exam — Solutions</h1>"
            "<p class='subtitle'>Software Engineering — UATX — Spring 2026</p>")
    sol_css = BASE_CSS + "\n.question:first-of-type { page-break-before: auto; }\n"
    body = [head]
    for i, qid in enumerate(SELECTION, 1):
        q = QBYID[qid]
        body.append(f"""
<div class="question">
  <div class="q-header"><span class="q-id">Question {i}</span></div>
  {render_blocks(q['stem'])}
  <div class="answer"><span class="answer-label">Solution</span>
  {render_blocks(q['answer'])}</div>
</div>""")
    return page("Final Exam — Solutions", sol_css, "\n".join(body))


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "final.html"), "w") as f:
        f.write(build_student())
    with open(os.path.join(here, "final-solutions.html"), "w") as f:
        f.write(build_solutions())
    print("Wrote final.html and final-solutions.html")
    print("Slate:", " ".join(SELECTION))
