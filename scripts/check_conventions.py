"""Validate PR metadata as data; never interpolate titles into shell code."""

import json
import os
import re
import sys
from pathlib import Path

BRANCH = re.compile(r"(?:story|task|bug)/TCR-\d{3}[A-Z]?-[a-z0-9]+(?:-[a-z0-9]+)*")
TITLE = re.compile(r"\[TCR-\d{3}[A-Z]?\] \S.+")
SECTIONS = (
    "Description",
    "Type of change",
    "How this was tested",
    "Checklist",
    "Ticket",
)


def validate(branch: str, title: str, body: str) -> list[str]:
    errors = []
    if not BRANCH.fullmatch(branch):
        errors.append("Branch must use story|task|bug/TCR-NNN[-suffix]")
    if not TITLE.fullmatch(title):
        errors.append("PR title must use [TCR-NNN] Imperative subject")
    branch_ticket = re.search(r"TCR-\d{3}[A-Z]?", branch)
    title_ticket = re.search(r"TCR-\d{3}[A-Z]?", title)
    if branch_ticket and title_ticket and branch_ticket[0] != title_ticket[0]:
        errors.append("Branch and PR title must reference the same ticket")
    for section in SECTIONS:
        if not re.search(rf"^## {re.escape(section)}\s*$", body, re.MULTILINE):
            errors.append(f"Missing PR section: {section}")
    return errors


def main() -> int:
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    if "pull_request" not in event:
        print("PR conventions: not applicable to this event")
        return 0
    pr = event["pull_request"]
    errors = validate(pr["head"]["ref"], pr["title"], pr.get("body") or "")
    print("\n".join(errors) if errors else "PR conventions passed")
    return int(bool(errors))


if __name__ == "__main__":
    sys.exit(main())
