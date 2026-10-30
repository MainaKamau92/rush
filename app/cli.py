import argparse
import asyncio
import json
import logging
import sys
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from app.core.errors import (
    ChangeError,
    ModelError,
    ReviewError,
    SourceError,
    StateError,
)
from app.core.settings import Settings
from app.dependencies import (
    build_code_change_reader,
    build_investigation,
    build_local_review,
    build_model_access,
    build_skill_catalog,
    build_source_access,
    build_system,
    source_credential_status,
)
from app.schemas.local_review import ContextFile, LocalReviewRequest, ReviewOutcome
from app.services.disclosure import DisclosureService
from app.services.review_report import ReviewReportService


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


async def _read_change(args: argparse.Namespace) -> None:
    scope = await build_code_change_reader(args.repository).read(
        args.head, target=args.target, base=args.base
    )
    print(
        json.dumps(
            {
                "name": "rush",
                "status": "complete" if scope.complete else "partial",
                "scope_sha256": scope.manifest_sha256(),
                **scope.model_dump(mode="json"),
            }
        )
    )


async def _list_skills(args: argparse.Namespace) -> None:
    catalog = await build_skill_catalog(args.skills).load()
    print(
        json.dumps(
            {
                "name": "rush",
                "skills": [
                    {
                        "id": skill.pin.id,
                        "version": skill.pin.version,
                        "active": skill.active,
                        "status": skill.status,
                        "paths": skill.manifest.scope.paths,
                        "model": skill.model.model_id,
                    }
                    for skill in catalog.skills
                ],
            }
        )
    )


def _aware_time(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        raise argparse.ArgumentTypeError("include a time zone, for example Z")
    return moment


def _read_text(path: Path) -> str:
    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError):
        raise ReviewError(f"Cannot read {path} as UTF-8 text") from None
    if not text.strip():
        raise ReviewError(f"{path} is empty")
    return text


def _write_report(output: Path, outcome: ReviewOutcome) -> tuple[Path, Path]:
    report = ReviewReportService()
    output.mkdir(parents=True, exist_ok=True)
    summary, data = output / "review.md", output / "review.json"
    summary.write_text(report.summary(outcome))
    data.write_text(json.dumps(report.data(outcome), indent=2) + "\n")
    return summary, data


async def _review(settings: Settings, args: argparse.Namespace) -> int:
    repository = args.repository.resolve()
    for trusted in (args.skills, args.rules, args.exceptions):
        if trusted is not None and trusted.resolve().is_relative_to(repository):
            raise ReviewError(
                "Approved skills and policy must come from outside the reviewed "
                "repository"
            )
    catalog = await build_skill_catalog(args.skills).load()
    service = build_local_review(settings, catalog)
    request = LocalReviewRequest(
        run_id=f"local-{uuid.uuid4().hex[:12]}",
        repository=args.repository.resolve().name,
        head=args.head,
        target=args.target,
        base=args.base,
        disclosure=args.disclosure,
        context=(
            *(
                ContextFile(kind="ticket", reference=path.name, text=_read_text(path))
                for path in args.ticket
            ),
            *(
                ContextFile(
                    kind="guideline", reference=path.name, text=_read_text(path)
                )
                for path in args.guideline
            ),
        ),
        rules=_read_text(args.rules) if args.rules else None,
        exceptions=_read_text(args.exceptions) if args.exceptions else None,
        approvers=tuple(args.approver),
        review_time=args.as_of,
        allow_cached_policy=args.allow_cached_policy,
        ticket_references=tuple(args.ticket_ref),
        pull_request_text=_read_text(args.pr_description)
        if args.pr_description
        else None,
        live_guidelines=args.live_guidelines,
    )
    outcome = await service.review(build_investigation(args.repository), request)
    outcome = await service.finish(outcome)
    shown = DisclosureService(catalog.approved.publishable_disclosures).for_audience(
        outcome, args.audience, args.disclosure
    )
    summary, data = _write_report(args.output, shown)
    status = outcome.record.status
    print(
        json.dumps(
            {
                "name": "rush",
                "run_id": outcome.record.id,
                "status": status,
                "findings": len(outcome.record.progress.result.findings),
                "summary": str(summary),
                "report": str(data),
            }
        )
    )
    return 1 if status in {"failed", "cancelled"} else 0


async def _run(args: argparse.Namespace) -> int:
    command = args.command
    if command == "change-read":
        await _read_change(args)
        return 0
    if command == "skill-list":
        await _list_skills(args)
        return 0
    settings = Settings()  # type: ignore[call-arg]
    if command == "review":
        return await _review(settings, args)
    if command == "model-check":
        await _check_model(settings, args.model_id)
        return 0
    if command == "source-status":
        status = asdict(source_credential_status(settings))
        print(json.dumps({"name": "rush", **status}))
        return 0
    if command.startswith("source-"):
        await _use_source(settings, args)
        return 0
    system = build_system(settings)
    if command == "migrate":
        print(json.dumps({"name": "rush", "schema_version": await system.migrate()}))
        return 0
    if command == "backup":
        await system.backup(args.destination)
        print(json.dumps({"name": "rush", "backup": "complete"}))
        return 0
    await system.start()
    try:
        result = await system.health()
        print(json.dumps({"name": "rush", "schema_version": result.schema_version}))
    finally:
        await system.stop()
    return 0


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
    change = subparsers.add_parser(
        "change-read", help="Read a committed code change without running it"
    )
    change.add_argument("--repository", required=True, type=Path)
    versions = change.add_mutually_exclusive_group(required=True)
    versions.add_argument(
        "--target", help="PR target; compare from its shared starting point with head"
    )
    versions.add_argument("--base", help="Exact base version to compare with head")
    change.add_argument("--head", required=True)
    skills = subparsers.add_parser(
        "skill-list", help="Verify approved review skills and show their status"
    )
    skills.add_argument("--skills", type=Path, default=Path("skills"))
    review = subparsers.add_parser(
        "review", help="Review a committed change locally with the active skills"
    )
    review.add_argument("--repository", required=True, type=Path)
    compared = review.add_mutually_exclusive_group(required=True)
    compared.add_argument(
        "--target", help="PR target; compare from its shared starting point with head"
    )
    compared.add_argument("--base", help="Exact base version to compare with head")
    review.add_argument("--head", required=True)
    review.add_argument("--ticket", type=Path, action="append", default=[])
    review.add_argument("--guideline", type=Path, action="append", default=[])
    review.add_argument("--rules", type=Path, help="Approved rules as a JSON list")
    review.add_argument(
        "--exceptions", type=Path, help="Approved exceptions as a JSON list"
    )
    review.add_argument(
        "--approver",
        action="append",
        default=[],
        help="Person whose approval activates rules and exceptions",
    )
    review.add_argument(
        "--as-of",
        type=_aware_time,
        help="Review time for rule and exception validity (ISO 8601 with zone)",
    )
    review.add_argument(
        "--allow-cached-policy",
        action="store_true",
        help="Apply approved rule text when its guideline changed since approval",
    )
    review.add_argument(
        "--ticket-ref",
        action="append",
        default=[],
        help="Approved ticket to read live through MCP",
    )
    review.add_argument(
        "--pr-description",
        type=Path,
        help="Pull request text whose ticket links are read live through MCP",
    )
    review.add_argument(
        "--live-guidelines",
        action="store_true",
        help="Read the approved guidelines live through MCP",
    )
    review.add_argument(
        "--audience",
        choices=["private", "public"],
        default="private",
        help="Who will read the reports; public withholds non-publishable text",
    )
    review.add_argument(
        "--disclosure",
        choices=["public", "internal", "private"],
        default="private",
        help="Classification of the code and supplied context",
    )
    review.add_argument("--skills", type=Path, default=Path("skills"))
    review.add_argument("--output", type=Path, default=Path("reports/review"))
    args = parser.parse_args()
    # The MCP SDK logs raw OAuth responses; the CLI reports only its own safe errors.
    logging.getLogger("mcp").setLevel(logging.CRITICAL)
    try:
        return asyncio.run(_run(args))
    except ValidationError:
        print(
            "Invalid settings; check RUSH_STATE_DIR, RUSH_ENVIRONMENT, "
            "model and source configuration",
            file=sys.stderr,
        )
        return 2
    except (ChangeError, ModelError, ReviewError, SourceError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except (StateError, OSError):
        print(
            "State operation failed; check configuration and migration state",
            file=sys.stderr,
        )
        return 1
