import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from app.core.errors import ModelError, ReviewError, StateError
from app.core.settings import Settings
from app.dependencies import build_investigation, build_model_review, build_system
from app.schemas.model_review import Capability, ReviewPermissions, ReviewTask
from app.schemas.review import (
    ModelConfiguration,
    ReviewInputs,
    ReviewLimits,
    ReviewSettings,
    SourceSnapshot,
    VersionPin,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/customer_lookup"
INSTRUCTIONS = (
    "Inspect only the changed customer lookup for behavior regressions. "
    "Preserve tenant isolation. If the called helper is needed, request its "
    "snippet through the protocol, then answer the question when resolved. "
    "Propose concrete, supported findings or finish with explicit limitations. "
    "Do not inspect billing or execute application tests."
)


def snapshot(kind: Literal["ticket", "guideline"]) -> SourceSnapshot:
    text = (FIXTURE / "context" / f"{kind}.md").read_text()
    return SourceSnapshot(
        id=kind,
        kind=kind,
        reference=f"demo://lantern/{kind}",
        revision="1",
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        retrieved_at=datetime.now(UTC),
        disclosure="public",
        excerpt=text,
    )


async def check(model_id: str, case: str) -> int:
    process = await asyncio.create_subprocess_exec(
        "sh",
        str(ROOT / "scripts/reset-example.sh"),
        case,
        stdout=asyncio.subprocess.PIPE,
    )
    output, _ = await process.communicate()
    if process.returncode:
        raise ReviewError("Fictional repository setup failed")
    limits = ReviewLimits(model_calls=4)
    broker = build_investigation(Path(output.decode().strip()), limits)
    scope = (await broker.start("fixture-head", target="fixture-base")).scope
    if scope is None:
        raise ReviewError("Fictional change discovery failed")
    skill = VersionPin(
        id="demo.protocol",
        version="1",
        digest=hashlib.sha256(INSTRUCTIONS.encode()).hexdigest(),
    )
    guideline = snapshot("guideline")
    inputs = ReviewInputs(
        repository="lantern-customer-service",
        target_sha=scope.target_sha or scope.base_sha,
        merge_base_sha=scope.base_sha,
        head_sha=scope.head_sha,
        policy_sha=scope.base_sha,
        memory_revision="demo-1",
        skills=(skill,),
        rules=(
            VersionPin(
                id="lantern.tenant-lookup", version="1", digest=guideline.content_sha256
            ),
        ),
        sources=(snapshot("ticket"), guideline),
        scope_manifest_sha256=scope.manifest_sha256(),
        settings=ReviewSettings(
            models=(
                ModelConfiguration(
                    task="review",
                    model_id=model_id,
                    adapter_version="0.2.0",
                    max_output_tokens=2048,
                ),
            ),
            limits=limits,
        ),
    )
    permissions: tuple[Capability, ...] = ("repo.read_snippet", "repo.find_symbol")
    task = ReviewTask(
        skill=skill,
        instructions=INSTRUCTIONS,
        code_disclosure="public",
        permissions=ReviewPermissions(
            runtime=permissions, repository=permissions, skill=permissions
        ),
    )
    with TemporaryDirectory(prefix="rush-model-review-") as directory:
        settings = Settings(state_dir=Path(directory) / "state")
        await build_system(settings).migrate()
        service = build_model_review(settings, broker)
        try:
            report = await service.run("fictional-model-check", inputs, task)
        finally:
            await service.close()
        print(
            json.dumps(
                {
                    "name": "rush",
                    "ticket": "TCR-008",
                    "recorded_at": datetime.now(UTC).isoformat(),
                    "case": case,
                    "status": report.status,
                    "reason": report.reason,
                    "requested_model": model_id,
                    "base_sha": scope.base_sha,
                    "head_sha": scope.head_sha,
                    "scope_manifest_sha256": inputs.scope_manifest_sha256,
                    "instructions_sha256": report.result.instructions_sha256,
                    "capabilities": report.capabilities.model_dump(mode="json")
                    if report.capabilities
                    else None,
                    "attempts": [
                        item.model_dump(mode="json")
                        for item in report.result.model_attempts
                    ],
                    "usage": report.result.usage.model_dump(mode="json"),
                    "candidate_count": len(report.result.candidate_findings),
                    "related_reads": [
                        read.path
                        for read in report.investigation.reads
                        if read.action == "read"
                    ],
                    "limitation_codes": [
                        item.code for item in report.result.limitations
                    ],
                    "application_tests_executed": False,
                }
            )
        )
        return 0 if report.status == "ready" else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Exercise live Meta review on public fictional code"
    )
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--case", choices=("safe", "unsafe", "related"), default="related"
    )
    args = parser.parse_args()
    try:
        return asyncio.run(check(args.model, args.case))
    except (ModelError, ReviewError, StateError):
        print("Model review check failed; check model access and local configuration")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
