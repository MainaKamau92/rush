import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

from pydantic import ValidationError

from app.core.errors import ModelError, StateError
from app.core.settings import Settings
from app.dependencies import build_model_access, build_system


async def _check_model(settings: Settings, model_id: str) -> None:
    service = build_model_access(settings)
    try:
        result = await service.check(model_id)
        print(json.dumps({"name": "rush", "status": "available", **asdict(result)}))
    finally:
        await service.close()


async def _run(
    command: str, destination: Path | None, model_id: str | None = None
) -> None:
    settings = Settings()  # type: ignore[call-arg]
    if command == "model-check" and model_id is not None:
        await _check_model(settings, model_id)
        return
    system = build_system(settings)
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
    model = subparsers.add_parser(
        "model-check", help="Check one selected model's access"
    )
    model.add_argument("--model", required=True, dest="model_id")
    args = parser.parse_args()
    try:
        asyncio.run(
            _run(
                args.command,
                getattr(args, "destination", None),
                getattr(args, "model_id", None),
            )
        )
    except ValidationError:
        print(
            "Invalid settings; check RUSH_STATE_DIR, RUSH_ENVIRONMENT "
            "and model configuration",
            file=sys.stderr,
        )
        return 2
    except ModelError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (StateError, OSError):
        print(
            "State operation failed; check configuration and migration state",
            file=sys.stderr,
        )
        return 1
    return 0
