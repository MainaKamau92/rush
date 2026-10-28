"""A missing, skipped, cancelled or failed prerequisite must fail the merge gate."""

import json
import os
import sys

REQUIRED = {"quality", "tests", "security", "package", "conventions"}


def failures(results: dict[str, dict[str, str]]) -> list[str]:
    return sorted(
        name for name in REQUIRED if results.get(name, {}).get("result") != "success"
    )


def main() -> int:
    failed = failures(json.loads(os.environ["RUSH_JOB_RESULTS"]))
    print(
        f"Required prerequisites failed or missing: {', '.join(failed)}"
        if failed
        else "All required prerequisites succeeded"
    )
    return int(bool(failed))


if __name__ == "__main__":
    sys.exit(main())
