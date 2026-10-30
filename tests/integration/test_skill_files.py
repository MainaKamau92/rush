import json
from pathlib import Path

import pytest

from app.core.errors import SkillError
from app.dependencies import build_skill_catalog
from app.internal.adapters.skill_files import MAX_FILE_BYTES, SkillFileAdapter

ROOT = Path(__file__).resolve().parents[2]


async def test_adapter_reports_links_folders_and_executables_without_following(
    tmp_path,
):
    package = tmp_path / "lookup"
    package.mkdir()
    (package / "manifest.json").write_text("{}")
    (package / "run.sh").write_text("echo unsafe")
    (package / "run.sh").chmod(0o755)
    (package / "nested").mkdir()
    (tmp_path / "secret.txt").write_text("outside")
    (package / "linked.md").symlink_to(tmp_path / "secret.txt")
    files = {
        item.name: item for item in await SkillFileAdapter(tmp_path).package("lookup")
    }
    assert list(files) == ["linked.md", "manifest.json", "nested", "run.sh"]
    assert (files["linked.md"].regular, files["linked.md"].content) == (False, b"")
    assert not files["nested"].regular
    assert files["run.sh"].executable and files["run.sh"].content == b"echo unsafe"
    assert files["manifest.json"].content == b"{}"


@pytest.mark.parametrize("name", ["", ".", "..", "a/b", "a\\b", "a\0b"])
async def test_adapter_refuses_names_that_are_not_single_components(tmp_path, name):
    adapter = SkillFileAdapter(tmp_path)
    for call in (adapter.package, adapter.evaluation):
        with pytest.raises(SkillError, match="single path components"):
            await call(name)


async def test_adapter_refuses_missing_linked_and_oversized_inputs(tmp_path):
    adapter = SkillFileAdapter(tmp_path)
    with pytest.raises(SkillError, match="missing"):
        await adapter.approved()
    with pytest.raises(SkillError, match="missing"):
        await adapter.package("absent")
    (tmp_path / "real").mkdir()
    (tmp_path / "alias").symlink_to(tmp_path / "real")
    with pytest.raises(SkillError, match="missing"):
        await adapter.package("alias")
    (tmp_path / "approved.json").write_bytes(b"x" * (MAX_FILE_BYTES + 1))
    with pytest.raises(SkillError, match="exceeds"):
        await adapter.approved()


async def test_adapter_saves_and_reads_evaluations_atomically(tmp_path):
    adapter = SkillFileAdapter(tmp_path)
    assert await adapter.evaluation("team.lookup@0.1.0.json") is None
    await adapter.save_evaluation("team.lookup@0.1.0.json", b"{}\n")
    assert await adapter.evaluation("team.lookup@0.1.0.json") == b"{}\n"
    assert [path.name for path in (tmp_path / "evaluations").iterdir()] == [
        "team.lookup@0.1.0.json"
    ]
    (tmp_path / "evaluations" / "linked.json").symlink_to(tmp_path / "approved.json")
    with pytest.raises(SkillError, match="regular files"):
        await adapter.evaluation("linked.json")


def test_missing_skills_directory_is_reported(tmp_path):
    with pytest.raises(SkillError, match="Skills directory is missing"):
        build_skill_catalog(tmp_path / "absent")


async def test_repository_starter_skills_verify_and_are_activated_by_evaluation():
    catalog = await build_skill_catalog(ROOT / "skills").load()
    assert [skill.pin.id for skill in catalog.skills] == [
        "rush.correctness",
        "rush.team-standards",
        "rush.ticket-intent",
    ]
    cases = {
        case["id"]
        for case in json.loads(
            (ROOT / "tests/fixtures/customer_lookup/cases.json").read_text()
        )
    }
    for skill in catalog.skills:
        assert {example.kind for example in skill.examples.examples} == {
            "acceptable",
            "violating",
        }
        assert {example.case for example in skill.examples.examples} <= cases
        assert skill.active, skill.status
    assert catalog.approved.allowed_disclosures == ("public",)
