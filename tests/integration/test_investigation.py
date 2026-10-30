import json
from pathlib import Path

import pytest

from app.core.errors import ChangeError
from app.dependencies import build_investigation
from app.internal.adapters.git import GitRepositoryAdapter
from app.schemas.investigation import ReadRequest
from tests.integration.test_code_change_reader import git, run

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((ROOT / "tests/fixtures/customer_lookup/cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
async def test_fictional_cases_read_only_the_linked_dependency_and_stop(
    case, monkeypatch
):
    example = Path(await run("sh", "scripts/reset-example.sh", case["id"]))
    calls = []
    original = GitRepositoryAdapter.file

    async def observe(self, commit, path, limit):
        calls.append((commit, path))
        return await original(self, commit, path, limit)

    monkeypatch.setattr(GitRepositoryAdapter, "file", observe)
    service = build_investigation(example)
    report = await service.start("fixture-head", base="fixture-base")
    if not case["permitted_related_reads"]:
        assert service.finish().complete
        assert calls == []
        return
    allowed = case["permitted_related_reads"][0]
    change = next(
        file for file in report.scope.files if file.new_path == "customers.py"
    )
    origin = change.hunks[0].id
    service.open_question("tenant-query", allowed["question"], origin)
    request = ReadRequest(
        question_id="tenant-query",
        question=allowed["question"],
        origin_hunk_id=origin,
        relationship="callee",
        target=allowed["path"],
        expected_evidence="Query scope and tenant argument handling",
        start_line=1,
        end_line=40,
    )
    outcome = await service.read(request)
    assert outcome.action == "read" and outcome.snippet.path == "customer_store.py"
    assert "WHERE external_id = ?" in outcome.snippet.text
    assert outcome.source_path == "customers.py" and outcome.source_object_id
    assert outcome.snippet.commit == report.scope.head_sha
    denied = await service.read(request.model_copy(update={"target": "billing.py"}))
    assert denied.action == "denied"
    service.answer(
        "tenant-query",
        "The helper's tenant behavior is now known",
        (outcome.snippet.id,),
    )
    assert (await service.read(request)).action == "denied"
    final = service.finish()
    assert final.complete
    assert [path for _, path in calls] == ["customers.py", "customer_store.py"]
    assert all(commit == report.scope.head_sha for commit, _ in calls)


async def test_related_reads_keep_frozen_head_and_never_run_helpers(tmp_path):
    example = Path(await run("sh", "scripts/reset-example.sh", "related"))
    marker = tmp_path / "helper-ran"
    helper = tmp_path / "helper.sh"
    helper.write_text(f"#!/bin/sh\ntouch {marker}\n")
    helper.chmod(0o755)
    for key in (
        "core.fsmonitor",
        "core.hooksPath",
        "diff.external",
        "diff.lantern.textconv",
        "filter.lantern.smudge",
    ):
        await git(example, "config", key, str(helper))
    service = build_investigation(example)
    report = await service.start("fixture-head", target="fixture-base")
    (example / "customer_store.py").write_text("raise RuntimeError('dirty worktree')\n")
    origin = report.scope.files[0].hunks[0].id
    service.open_question("lookup", "Which tenant does the helper query?", origin)
    outcome = await service.read(
        ReadRequest(
            question_id="lookup",
            question="Which tenant does the helper query?",
            origin_hunk_id=origin,
            relationship="import",
            target="customer_store.py",
            expected_evidence="The frozen query",
            start_line=1,
            end_line=14,
        )
    )
    assert outcome.action == "read"
    assert "SELECT * FROM customers" in outcome.snippet.text
    assert "dirty worktree" not in outcome.snippet.text
    assert not marker.exists()


async def test_repository_file_paths_are_literal_and_unsafe_paths_are_refused():
    example = Path(await run("sh", "scripts/reset-example.sh", "unsafe"))
    adapter = GitRepositoryAdapter(example, "git")
    head = await adapter.commit("fixture-head")
    with pytest.raises(ChangeError):
        await adapter.file("HEAD", "customers.py", 100)
    for path in ("../secret", "/outside/secret", ".git/config"):
        with pytest.raises(ChangeError):
            await adapter.file(head, path, 100)
    with pytest.raises(ChangeError):
        await adapter.file(head, "missing.py", 100)
    file = await adapter.file(head, "customers.py", 1)
    assert file.content is None
