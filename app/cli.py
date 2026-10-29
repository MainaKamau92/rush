import argparse
import asyncio
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from app.core.errors import StateError
from app.core.settings import Settings
from app.dependencies import build_system


async def _run(command: str, destination: Path | None) -> None:
    system = build_system(Settings())  # type: ignore[call-arg]
    if command == "migrate":
        print(json.dumps({"name": "rush", "schema_version": await system.migrate()}))
        return
    if command == "backup" and destination is not None:
        await system.backup(destination)
        print(json.dumps({"name": "rush", "backup": "complete"}))
        return
    await system.start()
    try:
        result = await system.health()
        print(json.dumps({"name": "rush", "schema_version": result.schema_version}))
    finally:
        await system.stop()


def main() -> int:
    parser = argparse.ArgumentParser(prog="rush")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("migrate", help="Explicitly apply versioned SQL migrations")
    subparsers.add_parser("health", help="Check configured state and schema")
    backup = subparsers.add_parser("backup", help="Create a consistent SQLite backup")
    backup.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        asyncio.run(_run(args.command, getattr(args, "destination", None)))
    except ValidationError:
        print(
            "Invalid settings; check RUSH_STATE_DIR and RUSH_ENVIRONMENT",
            file=sys.stderr,
        )
        return 2
    except (StateError, OSError):
        print(
            "State operation failed; check configuration and migration state",
            file=sys.stderr,
        )
        return 1
    return 0
