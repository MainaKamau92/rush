import argparse
import asyncio
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

from pydantic import ValidationError

from app.core.errors import ModelError, SourceError, StateError
from app.core.settings import Settings
from app.dependencies import (
    build_model_access,
    build_source_access,
    build_system,
    source_credential_status,
)


async def _check_model(settings: Settings, model_id: str) -> None:
    service = build_model_access(settings)
    try:
        result = await service.check(model_id)
        print(json.dumps({"name": "rush", "status": "available", **asdict(result)}))
    finally:
        await service.close()


def _show_authorization(url: str) -> None:
    print(
        "Open this address, approve read access, then paste the full address "
        f"your browser is sent to:\n{url}",
        file=sys.stderr,
    )


def _read_redirect() -> str:
    print("Redirected address: ", end="", file=sys.stderr, flush=True)
    return sys.stdin.readline()


async def _use_source(settings: Settings, args: argparse.Namespace) -> None:
    if args.command == "source-connect":
        service = build_source_access(settings, _show_authorization, _read_redirect)
    else:
        service = build_source_access(settings)
    try:
        if args.command == "source-read":
            evidence = await service.read(args.kind, args.reference)
            print(json.dumps({"name": "rush", "status": "read", **asdict(evidence)}))
            return
        tools = await service.tools()
    finally:
        await service.close()
    payload: dict[str, object] = {"name": "rush", "status": "connected"}
    if args.command == "source-connect":
        payload |= {"tools": len(tools), **asdict(source_credential_status(settings))}
    else:
        payload["tools"] = [asdict(tool) for tool in tools]
    print(json.dumps(payload))


async def _run(args: argparse.Namespace) -> None:
    settings = Settings()  # type: ignore[call-arg]
    command = args.command
    if command == "model-check":
        await _check_model(settings, args.model_id)
        return
    if command == "source-status":
        status = asdict(source_credential_status(settings))
        print(json.dumps({"name": "rush", **status}))
        return
    if command.startswith("source-"):
        await _use_source(settings, args)
        return
    system = build_system(settings)
    if command == "migrate":
        print(json.dumps({"name": "rush", "schema_version": await system.migrate()}))
        return
    if command == "backup":
        await system.backup(args.destination)
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
    subparsers.add_parser("source-connect", help="Sign in to ClickUp for read access")
    subparsers.add_parser("source-status", help="Show stored source credential state")
    subparsers.add_parser("source-tools", help="List the connected source's tools")
    read = subparsers.add_parser("source-read", help="Read one approved source item")
    read.add_argument("--kind", required=True, choices=["ticket", "guideline"])
    read.add_argument("--reference", required=True)
    args = parser.parse_args()
    # The MCP SDK logs raw OAuth responses; the CLI reports only its own safe errors.
    logging.getLogger("mcp").setLevel(logging.CRITICAL)
    try:
        asyncio.run(_run(args))
    except ValidationError:
        print(
            "Invalid settings; check RUSH_STATE_DIR, RUSH_ENVIRONMENT, "
            "model and source configuration",
            file=sys.stderr,
        )
        return 2
    except (ModelError, SourceError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except (StateError, OSError):
        print(
            "State operation failed; check configuration and migration state",
            file=sys.stderr,
        )
        return 1
    return 0
