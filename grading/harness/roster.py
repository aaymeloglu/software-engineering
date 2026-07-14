"""Roster loader and matching."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None


@dataclass
class Student:
    github: str
    name: str
    uatx_email: str = ""
    personal_email: str = ""
    section: str = ""
    extension_until: str = ""
    notes: str = ""


def load_roster(path: Path) -> list[Student]:
    if not path.exists():
        return []
    if yaml is None:
        raise RuntimeError("PyYAML not installed. `pip install pyyaml`")
    data = yaml.safe_load(path.read_text()) or {}
    students = []
    for row in data.get("students", []):
        students.append(Student(
            github=row.get("github", ""),
            name=row.get("name", ""),
            uatx_email=row.get("uatx_email", ""),
            personal_email=row.get("personal_email", ""),
            section=row.get("section", ""),
            extension_until=row.get("extension_until", ""),
            notes=row.get("notes", ""),
        ))
    return students


def match_handle(roster: list[Student], handle: str, committer_emails: list[str]) -> Student | None:
    """Match a submission handle to a roster entry. Tries GitHub handle first, then committer email."""
    handle_lower = handle.lower()
    handle_squished = handle_lower.replace("-", "").replace("_", "")
    # Direct github handle match (case insensitive)
    for s in roster:
        if s.github.lower() == handle_lower:
            return s
    # Loose match: ignore dashes/underscores. Catches students who switched
    # GitHub handles between assignments (e.g., Foo-Bar → FooBar).
    for s in roster:
        if s.github.lower().replace("-", "").replace("_", "") == handle_squished:
            return s
    # Fallback: committer email match
    for email in committer_emails:
        for s in roster:
            if email and (email == s.uatx_email or email == s.personal_email):
                return s
    return None


def missing_submissions(roster: list[Student], submitted_handles: set[str], today: date | None = None) -> list[Student]:
    """Return students who haven't submitted, respecting extension_until."""
    today = today or date.today()
    submitted = {h.lower() for h in submitted_handles}
    submitted_squished = {h.replace("-", "").replace("_", "") for h in submitted}

    missing = []
    for s in roster:
        gh = s.github.lower()
        gh_squished = gh.replace("-", "").replace("_", "")
        if gh in submitted or gh_squished in submitted_squished:
            continue
        if s.extension_until:
            try:
                ext_date = date.fromisoformat(s.extension_until)
                if today <= ext_date:
                    continue  # Still within extension window
            except ValueError:
                pass
        missing.append(s)
    return missing
