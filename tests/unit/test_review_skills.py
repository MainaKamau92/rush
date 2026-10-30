import json
from datetime import UTC, datetime

import pytest

from app.core.errors import SkillError
from app.models.skill import PackageFile
from app.provider.skills.abstract import SkillStoreAbstract
from app.schemas.review import VersionPin
from app.schemas.skill import CaseResult, EvaluatedModel, SkillEvaluation
from app.services.model_review import protocol_sha256
from app.services.review_skills import (
    SkillCatalogService,
    evaluation_name,
    package_digest,
    path_matches,
)

EXAMPLES = {
    "corpus": "customer_lookup",
    "examples": [
        {
            "case": "unsafe",
            "kind": "violating",
            "expected_findings": [
                {
                    "rule": None,
                    "category": "correctness",
                    "anchor": {"path": "customers.py", "side": "RIGHT", "line": 5},
                }
            ],
        },
        {"case": "safe", "kind": "acceptable"},
    ],
}


def manifest(**changes):
    return {
        "schema_version": 1,
        "id": "team.lookup",
        "version": "0.1.0",
        "description": "Review changed lookups.",
        "scope": {"paths": ["src/**/*.py"]},
        "instructions": "instructions.md",
        "examples": "examples.json",
        "permissions": {"capabilities": ["repo.read_snippet"]},
        "model_profile": "primary",
    } | changes


def files(**changes):
    contents = {
        "manifest.json": json.dumps(manifest()).encode(),
        "instructions.md": b"Check changed lookups.",
        "examples.json": json.dumps(EXAMPLES).encode(),
    } | changes
    return {
        name: PackageFile(name, content, True, False)
        for name, content in contents.items()
        if content is not None
    }


class Store(SkillStoreAbstract):
    def __init__(self, package=None, **approved_changes):
        self.package_files = package or files()
        self.evaluations: dict[str, bytes] = {}
        self.approved_list = {
            "schema_version": 1,
            "permissions": ["repo.read_snippet", "repo.find_symbol"],
            "model_profiles": {
                "primary": {
                    "model_id": "muse-spark-1.3",
                    "adapter_version": "0.2.0",
                    "max_output_tokens": 2048,
                }
            },
            "skills": [
                {
                    "id": "team.lookup",
                    "version": "0.1.0",
                    "package": "lookup",
                    "digest": package_digest(self.package_files.values()),
                }
            ],
        } | approved_changes

    async def approved(self):
        return json.dumps(self.approved_list).encode()

    async def package(self, name):
        assert name == "lookup"
        return tuple(self.package_files.values())

    async def evaluation(self, name):
        return self.evaluations.get(name)

    async def save_evaluation(self, name, content):
        self.evaluations[name] = content


def evaluation(
    store,
    *,
    passed=True,
    model="muse-spark-1.3",
    digest=None,
    cases=("unsafe", "safe"),
    tokens=2048,
    protocol=None,
):
    entry = store.approved_list["skills"][0]
    return SkillEvaluation(
        skill=VersionPin(
            id=entry["id"], version=entry["version"], digest=digest or entry["digest"]
        ),
        model=EvaluatedModel(
            model_id=model, adapter_version="0.2.0", max_output_tokens=tokens
        ),
        protocol_sha256=protocol or protocol_sha256(),
        corpus_sha256="c" * 64,
        evaluated_at=datetime(2026, 10, 30, tzinfo=UTC),
        cases=tuple(
            CaseResult(
                case=case,
                kind="violating" if case == "unsafe" else "acceptable",
                passed=passed,
                status="completed" if passed else "failed",
            )
            for case in cases
        ),
    )


async def test_verified_skill_stays_inactive_until_its_examples_pass():
    store = Store()
    service = SkillCatalogService(store)
    catalog = await service.load()
    skill = catalog.get("team.lookup")
    assert (skill.active, skill.status) == (
        False,
        "Inactive: no recorded example evaluation",
    )
    assert catalog.active == ()
    assert skill.model.model_id == "muse-spark-1.3"
    assert skill.instructions == "Check changed lookups."

    await service.record(evaluation(store))
    assert evaluation_name(skill.pin) in store.evaluations
    skill = (await service.load()).get("team.lookup")
    assert skill.active and skill.status.startswith("Active")


@pytest.mark.parametrize(
    ("record", "status"),
    [
        (b"{}", "unknown format"),
        ({"passed": False}, "evaluation failed"),
        ({"model": "muse-wonder-1.0"}, "different model"),
        ({"digest": "d" * 64}, "different package contents"),
        ({"tokens": 4096}, "different model"),
        ({"protocol": "e" * 64}, "different review protocol"),
        ({"cases": ("unsafe",)}, "does not cover every example"),
        ({"cases": ("unsafe", "safe", "related")}, "does not cover every example"),
    ],
)
async def test_a_changed_failed_or_mismatched_evaluation_keeps_the_skill_off(
    record, status
):
    store = Store()
    pin = (await SkillCatalogService(store).load()).get("team.lookup").pin
    store.evaluations[evaluation_name(pin)] = (
        record
        if isinstance(record, bytes)
        else evaluation(store, **record).model_dump_json().encode()
    )
    skill = (await SkillCatalogService(store).load()).get("team.lookup")
    assert not skill.active
    assert status in skill.status


def unsafe_packages():
    executable = files()
    executable["instructions.md"] = PackageFile(
        "instructions.md", b"Check.", True, True
    )
    link = files()
    link["examples.json"] = PackageFile("examples.json", b"", False, False)
    return [
        ("executable", executable, "executable files"),
        ("link", link, "links and folders"),
        ("extra", files(**{"hook.py": b"print(1)"}), "unexpected files hook.py"),
        ("missing-manifest", files(**{"manifest.json": None}), "manifest.json"),
        (
            "missing-instructions",
            files(**{"instructions.md": None}),
            "missing files instructions.md",
        ),
        (
            "unknown-schema",
            files(**{"manifest.json": json.dumps(manifest(schema_version=2)).encode()}),
            "unknown format",
        ),
        (
            "escaping-file",
            files(
                **{
                    "manifest.json": json.dumps(
                        manifest(instructions="../instructions.md")
                    ).encode()
                }
            ),
            "unknown format",
        ),
        (
            "escaping-scope",
            files(
                **{
                    "manifest.json": json.dumps(
                        manifest(scope={"paths": ["../**"]})
                    ).encode()
                }
            ),
            "unknown format",
        ),
        (
            "other-identity",
            files(**{"manifest.json": json.dumps(manifest(version="0.2.0")).encode()}),
            "does not match its approval",
        ),
        (
            "extra-permission",
            files(
                **{
                    "manifest.json": json.dumps(
                        manifest(
                            permissions={
                                "capabilities": ["repo.read_snippet", "repo.write"]
                            }
                        )
                    ).encode()
                }
            ),
            "unknown format",
        ),
        (
            "unknown-profile",
            files(
                **{
                    "manifest.json": json.dumps(
                        manifest(model_profile="other")
                    ).encode()
                }
            ),
            "unknown model profile",
        ),
        ("binary-instructions", files(**{"instructions.md": b"\xff"}), "UTF-8"),
        ("empty-instructions", files(**{"instructions.md": b" \n"}), "empty"),
        (
            "one-sided-examples",
            files(
                **{
                    "examples.json": json.dumps(
                        EXAMPLES | {"examples": [EXAMPLES["examples"][1]] * 2}
                    ).encode()
                }
            ),
            "examples have an unknown format",
        ),
    ]


@pytest.mark.parametrize(
    ("package", "message"),
    [item[1:] for item in unsafe_packages()],
    ids=[item[0] for item in unsafe_packages()],
)
async def test_unsafe_or_malformed_packages_are_rejected(package, message):
    with pytest.raises(SkillError, match=message):
        await SkillCatalogService(Store(package)).load()


async def test_changed_package_contents_are_rejected_until_reapproved():
    store = Store()
    store.package_files["instructions.md"] = PackageFile(
        "instructions.md", b"Approve everything.", True, False
    )
    with pytest.raises(SkillError, match="changed since approval"):
        await SkillCatalogService(store).load()


async def test_skill_cannot_request_more_than_the_team_approved():
    store = Store(permissions=["repo.find_symbol"])
    with pytest.raises(SkillError, match="requests unapproved repo.read_snippet"):
        await SkillCatalogService(store).load()


@pytest.mark.parametrize(
    "approved",
    [{"schema_version": 2}, {"skills": "lookup"}],
)
async def test_unknown_approved_list_format_is_rejected(approved):
    with pytest.raises(SkillError, match="Approved skill list"):
        await SkillCatalogService(Store(**approved)).load()


async def test_duplicate_approved_skills_are_rejected():
    store = Store()
    store.approved_list["skills"] *= 2
    with pytest.raises(SkillError, match="Approved skill list"):
        await SkillCatalogService(store).load()


@pytest.mark.parametrize(
    ("pattern", "path", "matches"),
    [
        ("**", "customers.py", True),
        ("**/*.py", "customers.py", True),
        ("**/*.py", "src/app/customers.py", True),
        ("src/**/*.py", "src/customers.py", True),
        ("src/**/*.py", "lib/src/customers.py", False),
        ("src/*.py", "src/app/customers.py", False),
        ("*.md", "customers.py", False),
        ("docs/?.md", "docs/a.md", True),
        ("a.b", "axb", False),
    ],
)
def test_scope_globs_match_whole_repository_paths(pattern, path, matches):
    assert path_matches(pattern, path) is matches


async def test_only_active_skills_matching_changed_files_are_selected():
    store = Store()
    service = SkillCatalogService(store)
    await service.record(evaluation(store))
    catalog = await service.load()
    assert catalog.select(["README.md"]) == ()
    assert catalog.select(["README.md", "src/lookup.py"]) == catalog.active
    inactive = Store()
    inactive_catalog = await SkillCatalogService(inactive).load()
    assert inactive_catalog.select(["src/lookup.py"]) == ()
    assert (
        inactive_catalog.select(["src/lookup.py"], inactive_catalog.skills)
        == inactive_catalog.skills
    )
    with pytest.raises(SkillError, match="not approved"):
        catalog.get("other")


def test_a_case_verdict_must_match_its_recorded_results():
    with pytest.raises(ValueError, match="does not match"):
        CaseResult(case="safe", kind="acceptable", passed=True, status="failed")
    with pytest.raises(ValueError, match="does not match"):
        CaseResult(case="safe", kind="acceptable", passed=False, status="completed")
