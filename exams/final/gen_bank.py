#!/usr/bin/env python3
"""Generate the Final Exam question bank: one question per page, answer key on
the same page (for selection). Content + rendering live in questions.py."""
import os
from questions import (QUESTIONS, TOPICS, TOPIC_LABEL, BASE_CSS,
                       render_blocks, page)

BLUEPRINT = [
    ("Q1", "Trace-through", "read code, predict behavior", ""),
    ("Q2", "Trace-through", "second trace (JS/React or concurrency)", "JS/React"),
    ("Q3", "Spot the bug", "agent output, multi-defect", "JS/React"),
    ("Q4", "Spot the bug", "security endpoint", ""),
    ("Q5", "Specification", "contract + decisions, in prose", ""),
    ("Q6", "Code review", "judge two implementations", ""),
    ("Q7", "Short design", "a design call under uncertainty", ""),
]


def counts():
    c = {}
    for q in QUESTIONS:
        c[q["topic"]] = c.get(q["topic"], 0) + 1
    return c


def build_html():
    cnt = counts()
    legend = "<table class='legend'><tr><th>Topic</th><th>Lecture</th><th>Qs</th><th>Tests</th></tr>" + "".join(
        f"<tr><td>{t[0]} — {t[1]}</td><td>{t[2]}</td><td>{cnt.get(t[0],0)}</td><td>{t[3]}</td></tr>"
        for t in TOPICS) + "</table>"
    blueprint = "<table><tr><th>Slot</th><th>Type</th><th>Draws</th><th>JS/React</th></tr>" + "".join(
        f"<tr><td>{b[0]}</td><td>{b[1]}</td><td>{b[2]}</td><td>{b[3]}</td></tr>"
        for b in BLUEPRINT) + "</table>"

    total = len(QUESTIONS)
    cover = f"""
<h1>Final Exam — Question Bank</h1>
<p class="subtitle">Software Engineering — UATX — Spring 2026</p>
<p>Working bank of <b>{total} questions</b> spanning lectures 5.1 through 10.1. From it we
draw two parallel seven-question papers: a <b>Sample Exam</b> (released for practice, with a
key) and the real <b>Final</b>, same shape, different questions.</p>
<p><b>How these questions are built.</b> The class codes with agents, so every question tests a
skill the agent cannot do for the student: reading code and predicting behavior, finding bugs by
inspection, writing the spec and decisions you would hand the agent (in prose, not syntax),
judging which of two implementations is better, and making design calls under uncertainty.
Nothing here rewards recalling syntax an agent would type for you. The shaded key on each page is
for selection, not part of the student paper.</p>

<h2>Topics</h2>
{legend}

<h2>Proposed blueprint (7 questions)</h2>
<p>Keeps all five midterm categories and adds a second trace and a second spot-the-bug, with
JS/React guaranteed in at least two slots.</p>
{blueprint}
"""
    parts = [cover]
    for q in QUESTIONS:
        meta = f"{TOPIC_LABEL[q['topic']]}<br>{q['type']}"
        parts.append(f"""
<div class="question">
  <div class="q-header"><span class="q-id">{q['id']}</span><span class="q-meta">{meta}</span></div>
  {render_blocks(q['stem'])}
  <div class="answer"><span class="answer-label">Answer / key</span>
  {render_blocks(q['answer'])}</div>
</div>""")
    return page("Final Exam — Question Bank", BASE_CSS, "\n".join(parts))


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, "question-bank.html")
    with open(out, "w") as f:
        f.write(build_html())
    print(f"Wrote {out} with {len(QUESTIONS)} questions.")
