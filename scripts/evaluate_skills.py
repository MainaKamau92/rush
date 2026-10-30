import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from app.core.errors import ChangeError, ModelError, ReviewError, StateError
from app.core.settings import Settings
from app.dependencies import (
    build_investigation,
    build_local_review,
    build_skill_catalog,
    build_system,
)
from app.schemas.local_review import ContextFile, LocalReviewRequest
from app.schemas.skill import (
    CaseResult,
    EvaluatedModel,
    InstalledSkill,
    SkillEvaluation,
)
from app.services.local_review import LocalReviewService
from app.services.model_review import protocol_sha256
from app.services.skill_evaluation import SkillEvaluationService

ROOT = Path(__file__).resolve().parents[1]
CORPORA = {"customer_lookup": ROOT / "tests/fixtures/customer_lookup"}


def corpus_digest(corpus: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(corpus.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            digest.update(path.relative_to(corpus).as_posix().encode() + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode())
    return digest.hexdigest()


async def reset(case: str) -> Path:
    process = await asyncio.create_subprocess_exec(
        "sh",
        str(ROOT / "scripts/reset-example.sh"),
        case,
        stdout=asyncio.subprocess.PIPE,
    )
    output, _ = await process.communicate()
    if process.returncode:
        raise ReviewError(f"Fictional repository setup failed for {case}")
    return Path(output.decode().strip())


def request(corpus: Path, case: dict[str, object], run_id: str) -> LocalReviewRequest:
    ticket = case["ticket"]
    wiki = case["wiki"]
    rules = case["rules"]
    return LocalReviewRequest(
        run_id=run_id,
        repository="lantern-customer-service",
        head="fixture-head",
        target="fixture-base",
        disclosure="public",
        context=(
            *(
                (
                    ContextFile(
                        kind="ticket",
                        reference=Path(ticket).name,
                        text=(corpus / ticket).read_text(),
                    ),
                )
                if isinstance(ticket, str)
                else ()
            ),
            *(
                ContextFile(
                    kind="guideline",
                    reference=Path(name).name,
                    text=(corpus / name).read_text(),
                )
                for name in (wiki if isinstance(wiki, list) else [])
            ),
        ),
        rules=(corpus / rules).read_text() if isinstance(rules, str) else None,
    )


async def evaluate(
    service: LocalReviewService, skill: InstalledSkill
) -> tuple[CaseResult, ...]:
    corpus = CORPORA.get(skill.examples.corpus)
    if corpus is None:
        raise ReviewError(f"Unknown example corpus: {skill.examples.corpus}")
    cases = {
        case["id"]: case for case in json.loads((corpus / "cases.json").read_text())
    }
    results = []
    for number, example in enumerate(skill.examples.examples, start=1):
        if example.case not in cases:
            raise ReviewError(f"Unknown example case: {example.case}")
        repository = await reset(example.case)
        outcome = await service.review(
            build_investigation(repository),
            request(corpus, cases[example.case], f"evaluate-{skill.pin.id}-{number}"),
            skills=(skill,),
        )
        outcome = await service.finish(outcome)
        results.append(SkillEvaluationService().compare(example, outcome))
    return tuple(results)


async def main_async(skill_ids: list[str], save: bool) -> int:
    catalog_service = build_skill_catalog(ROOT / "skills")
    catalog = await catalog_service.load()
    skills = [catalog.get(item) for item in skill_ids] or list(catalog.skills)
    passed = True
    with TemporaryDirectory(prefix="rush-skill-evaluation-") as directory:
        settings = Settings(state_dir=Path(directory) / "state")
        await build_system(settings).migrate()
        service = build_local_review(settings, catalog)
        for skill in skills:
            evaluation = SkillEvaluation(
                skill=skill.pin,
                model=EvaluatedModel(**skill.model.model_dump()),
                protocol_sha256=protocol_sha256(),
                corpus_sha256=corpus_digest(CORPORA[skill.examples.corpus]),
                evaluated_at=datetime.now(UTC),
                cases=await evaluate(service, skill),
            )
            passed &= evaluation.passed
            if save:
                await catalog_service.record(evaluation)
            print(
                json.dumps(
                    {
                        "skill": skill.pin.id,
                        "passed": evaluation.passed,
                        "saved": save,
                        "cases": [
                            item.model_dump(mode="json") for item in evaluation.cases
                        ],
                    }
                )
            )
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run approved skills against their examples with a live model"
    )
    parser.add_argument("--skill", action="append", default=[], dest="skills")
    parser.add_argument(
        "--save", action="store_true", help="Record the result under skills/evaluations"
    )
    args = parser.parse_args()
    try:
        return asyncio.run(main_async(args.skills, args.save))
    except (ChangeError, ModelError, ReviewError, StateError) as error:
        print(f"Skill evaluation failed: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
