import argparse
import asyncio
import hashlib
import json
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from app.core.settings import Settings
from app.dependencies import (
    build_investigation,
    build_local_review,
    build_skill_catalog,
    build_system,
)
from app.schemas.local_review import ReviewOutcome
from app.schemas.review import ReviewLimits
from app.schemas.skill import InstalledSkill, ModelProfile, SkillExample
from app.services.model_comparison import ModelComparisonService
from app.services.model_review import protocol_sha256
from scripts.evaluate_skills import CORPORA, ROOT, corpus_digest, request, reset

MODELS = ("muse-spark-1.3", "muse-wonder-1.0")


def write_report(output: Path, report: dict[str, Any]) -> None:
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    temporary.replace(output)


def implementation_digest() -> str:
    digest = hashlib.sha256()
    paths = sorted((ROOT / "app").rglob("*.py")) + [
        ROOT / "scripts" / name
        for name in ("compare_models.py", "evaluate_skills.py", "reset-example.sh")
    ]
    for path in paths:
        digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


async def compare(output: Path, live: bool) -> int:
    catalog = await build_skill_catalog(ROOT / "skills").load()
    profiles = tuple(
        ModelProfile(model_id=model, adapter_version="0.2.0", max_output_tokens=2048)
        for model in MODELS
    )
    metadata = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "protocol_sha256": protocol_sha256(),
        "implementation_sha256": implementation_digest(),
        "limits": ReviewLimits().model_dump(mode="json"),
        "corpora": {name: corpus_digest(path) for name, path in CORPORA.items()},
        "skill_instructions_sha256": {
            skill.pin.id: hashlib.sha256(skill.instructions.encode()).hexdigest()
            for skill in catalog.skills
        },
    }
    if not live:
        plan = {
            "status": "not_run",
            "reason": "Live services require owner authorization; no model was called.",
            "models": [profile.model_dump(mode="json") for profile in profiles],
            "repetitions": 3,
            "examples_per_repetition": sum(
                len(skill.examples.examples) for skill in catalog.skills
            ),
            "skills": [skill.pin.model_dump(mode="json") for skill in catalog.skills],
            **metadata,
        }
        write_report(output, plan)
        return 0
    with TemporaryDirectory(prefix="rush-model-comparison-") as directory:
        settings = Settings(state_dir=Path(directory) / "state")
        await build_system(settings).migrate()
        service = build_local_review(settings, catalog)

        async def run_example(
            skill: InstalledSkill, example: SkillExample, repetition: int
        ) -> ReviewOutcome:
            corpus = CORPORA[skill.examples.corpus]
            cases = {
                item["id"]: item
                for item in json.loads((corpus / "cases.json").read_text())
            }
            repo = await reset(example.case)
            try:
                return await service.finish(
                    await service.review(
                        build_investigation(repo),
                        request(
                            corpus,
                            cases[example.case],
                            f"compare-{skill.model.model_id}-{skill.pin.id}-{repetition}-{example.case}",
                        ),
                        skills=(skill,),
                    )
                )
            finally:
                shutil.rmtree(repo)

        def checkpoint(report: dict[str, Any]) -> None:
            write_report(output, metadata | report)

        result = await ModelComparisonService(run_example, time.monotonic).run(
            catalog.skills, profiles, "live", checkpoint
        )
        return int(not result["passed"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plan or run the three-repeat Meta fixture comparison"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Make paid Meta calls only after owner authorization",
    )
    args = parser.parse_args()
    return asyncio.run(compare(args.output, args.live))


if __name__ == "__main__":
    raise SystemExit(main())
