"""Require complete coverage data before evaluating changed executable lines."""

import json
import os
import re
import shutil

# Fixed tools use argument arrays and never a shell.
import subprocess  # nosec B404
import sys
from pathlib import Path


def compare_base() -> str:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if event_path is None:
        return "origin/main"
    event = json.loads(Path(event_path).read_text())
    base: str = event.get("pull_request", {}).get("base", {}).get("sha") or event.get(
        "before", ""
    )
    if not re.fullmatch(r"[0-9a-f]{40}", base) or base == "0" * 40:
        raise ValueError("Missing actual PR or push base")
    return base


def main() -> int:
    try:
        report = json.loads(Path("coverage.json").read_text())
        if not report["meta"]["branch_coverage"]:
            raise ValueError("Branch coverage is required")
        expected = {p.as_posix() for p in Path("app").rglob("*.py")}
        if not expected.issubset(report["files"]):
            raise ValueError("Application files missing from coverage report")
        base = compare_base()
        git = shutil.which("git")
        diff_cover = shutil.which("diff-cover")
        if git is None or diff_cover is None:
            raise ValueError("Required coverage tools are unavailable")
        # Only a fixed local ref or a validated SHA reaches these argument arrays.
        subprocess.run(  # noqa: S603  # nosec B603
            [git, "rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}"],
            check=True,
        )
        subprocess.run(  # noqa: S603  # nosec B603
            [
                diff_cover,
                "coverage.xml",
                "--compare-branch",
                base,
                "--fail-under",
                "90",
                "--format",
                "json:reports/diff-coverage.json",
            ],
            check=True,
        )
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(f"Coverage gate failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    diff = json.loads(Path("reports/diff-coverage.json").read_text())
    if diff["total_num_lines"] == 0:
        print("Changed executable line coverage: not applicable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
