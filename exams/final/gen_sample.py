#!/usr/bin/env python3
"""Generate the student-facing Sample Final (no answers, blank work space) and a
separate solutions PDF, from a selected list of question ids.

Edit SELECTION to change the slate. Q1 is locked to T1-Q1 (Andy-approved).
Run:  python3 gen_sample.py   ->  sample-final.html, sample-final-solutions.html
"""
import os
from questions import (QBYID, TOPIC_LABEL, DEFAULT_SPACE, BASE_CSS,
                       render_blocks, page)

# Slate for the Sample Final. Q1 locked; Q2/Q4/Q5/Q7 revised per round-2 feedback.
SELECTION = [
    "T1-Q1",   # Trace-through (JS)                         [locked]
    "T8-Q5",   # Trace-through (promo double-redeem; "does a txn fix it?")
    "T2-Q1",   # Spot the bug (async / JS)
    "T9-Q6",   # Spot the bug (container-vs-item authz, no SQLi gimme)
    "T3-Q4",   # Specification (read agent's live-search; spec the gaps)
    "T7-Q4",   # Code review (CI yaml + tests, reasoning)   [Andy: best so far]
    "T6-Q4",   # Short design (Docker: caching + secrets + rotate, design-forward)
]

META = [
    ("Format", "Pencil and paper. No computer, phone, notes, or coding agent."),
    ("Time", "150 minutes."),
    ("Length", "Seven questions, one to two per category."),
    ("Coverage", "Lectures 5.1 through 10.1 (JS/TS and the browser, React, deployment, "
                 "Docker, CI/CD, concurrency, security, agents), plus assignments 3 and 4."),
    ("Categories", "Trace-through, spot the bug, specification, code review, short design."),
    ("Grading", "Curved. The exam is intentionally hard; expect to leave some parts unfinished."),
]

AGENTS_BLURB = (
    "The whole semester has leaned into coding agents as the way real engineers work, so an exam "
    "that asks you to write working code from scratch on paper would punish you for taking the "
    "course seriously. Instead, every question is built around a skill the agent can't do for you: "
    "reading code carefully, finding bugs by inspection, writing the spec you'd hand to the agent, "
    "judging which of two implementations is better, and making design calls under uncertainty.")

SAMPLE_BLURB = (
    "This is a representative exam, not the actual one -- the real final will have seven questions "
    "in the same five categories at roughly the same difficulty. Solutions are in a separate "
    "document; try the questions cold first, then check.")


def cover(meta_rows, name_field, extra_h3):
    rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in meta_rows)
    nf = ('<div class="name-field">Name: <span class="blank">&nbsp;</span></div>'
          if name_field else "")
    return (f"{nf}<h1>Final Exam — Sample</h1>"
            f"<p class='subtitle'>Software Engineering — UATX — Spring 2026</p>"
            f"<table class='meta-table'>{rows}</table>"
            f"<h3>How this exam thinks about agents</h3><p>{AGENTS_BLURB}</p>"
            f"{extra_h3}")


def build_student():
    body = [cover(META, name_field=True,
                  extra_h3=f"<h3>How to use this sample</h3><p>{SAMPLE_BLURB}</p>")]
    for i, qid in enumerate(SELECTION, 1):
        q = QBYID[qid]
        space = q.get("space", DEFAULT_SPACE.get(q["type"], 5.0))
        body.append(f"""
<div class="question">
  <div class="q-header"><span class="q-id">Question {i}</span>
    <span class="q-meta">{q['type']}</span></div>
  {render_blocks(q['stem'])}
  <div class="lines" style="height: {space}in;">&nbsp;</div>
</div>""")
    return page("Final Exam — Sample", BASE_CSS, "\n".join(body))


def build_solutions():
    head = ("<h1>Final Exam — Sample Solutions</h1>"
            "<p class='subtitle'>Software Engineering — UATX — Spring 2026</p>")
    sol_css = BASE_CSS + "\n.question:first-of-type { page-break-before: auto; }\n"
    body = [head]
    for i, qid in enumerate(SELECTION, 1):
        q = QBYID[qid]
        meta = f"{TOPIC_LABEL[q['topic']]} &middot; {q['type']}"
        body.append(f"""
<div class="question">
  <div class="q-header"><span class="q-id">Question {i}</span>
    <span class="q-meta">{meta}</span></div>
  {render_blocks(q['stem'])}
  <div class="answer"><span class="answer-label">Solution</span>
  {render_blocks(q['answer'])}</div>
</div>""")
    return page("Final Exam — Sample Solutions", sol_css, "\n".join(body))


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "sample-final.html"), "w") as f:
        f.write(build_student())
    with open(os.path.join(here, "sample-final-solutions.html"), "w") as f:
        f.write(build_solutions())
    print("Wrote sample-final.html and sample-final-solutions.html")
    print("Slate:", " ".join(SELECTION))
