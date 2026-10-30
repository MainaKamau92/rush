import asyncio
import json
import os
import shutil
from pathlib import Path

import pytest

from app.core.errors import ChangeError
from app.dependencies import build_code_change_reader
from app.provider.repository.base import RepositoryServiceProvider
from app.services.code_change_reader import CodeChangeReaderService

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((ROOT / "tests/fixtures/customer_lookup/cases.json").read_text())
GIT_ENVIRONMENT = {
    "PATH": os.environ["PATH"],
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_AUTHOR_NAME": "Lantern Cart",
    "GIT_AUTHOR_EMAIL": "team@example.invalid",
    "GIT_COMMITTER_NAME": "Lantern Cart",
    "GIT_COMMITTER_EMAIL": "team@example.invalid",
    "GIT_AUTHOR_DATE": "2026-01-15T00:00:00+00:00",
    "GIT_COMMITTER_DATE": "2026-01-15T00:00:00+00:00",
}


async def run(*arguments: str, cwd: Path = ROOT) -> str:
    process = await asyncio.create_subprocess_exec(
        *arguments,
        cwd=cwd,
        env=GIT_ENVIRONMENT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    assert process.returncode == 0, stderr.decode()
    return stdout.decode().strip()


async def git(repository: Path, *arguments: str) -> str:
    return await run(
        "git", "-c", "commit.gpgsign=false", "-C", str(repository), *arguments
    )


async def commit(repository: Path, files: dict[str, str | bytes | None]) -> str:
    for name, content in files.items():
        path = repository / name
        if content is None:
            await git(repository, "rm", "-q", "--", name)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content)
        await git(repository, "add", "--", name)
    await git(repository, "commit", "-q", "-m", "Fictional change")
    return await git(repository, "rev-parse", "HEAD")


@pytest.fixture
async def repository(tmp_path: Path) -> Path:
    path = tmp_path / "lantern"
    await git(tmp_path, "init", "-q", "--template=", "-b", "main", str(path))
    return path


def lines(scope, path, kind):
    change = next(
        item for item in scope.files if path in {item.old_path, item.new_path}
    )
    return [
        (line.old_line, line.new_line, line.text)
        for hunk in change.hunks
        for line in hunk.lines
        if line.kind == kind
    ]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
async def test_examples_load_with_expected_anchors_inside_the_change(case):
    example = Path(await run("sh", "scripts/reset-example.sh", case["id"]))
    scope = await build_code_change_reader(example).read(
        "fixture-head", target="fixture-base"
    )
    assert scope.complete
    assert scope.base_sha == scope.target_sha
    for finding in case["expected_findings"]:
        anchor = finding["anchor"]
        assert scope.anchor(anchor["path"], anchor["side"], anchor["line"])
    unchanged_defect = case["forbidden_findings"][0]["anchor"]
    assert unchanged_defect["path"] == "billing.py"
    assert scope.anchor("billing.py", "RIGHT", unchanged_defect["line"]) is None
    assert "billing.py" not in {change.new_path for change in scope.files}


async def test_pr_comparison_excludes_target_only_changes(repository):
    start = await commit(repository, {"app.py": "one\ntwo\n", "notes.py": "a\n"})
    await git(repository, "switch", "-q", "-c", "feature")
    head = await commit(repository, {"app.py": "one\ntwo\nthree\n"})
    await git(repository, "switch", "-q", "main")
    target = await commit(repository, {"notes.py": "b\n", "target_only.py": "x\n"})
    reader = build_code_change_reader(repository)

    scope = await reader.read("feature", target="main")

    assert (scope.comparison, scope.target_sha, scope.base_sha, scope.head_sha) == (
        "merge_base",
        target,
        start,
        head,
    )
    assert [change.new_path for change in scope.files] == ["app.py"]
    exact = await reader.read("feature", base="main")
    assert exact.comparison == "exact" and exact.target_sha is None
    assert {change.old_path for change in exact.files} >= {"notes.py", "target_only.py"}


async def test_deletions_renames_and_line_positions_are_preserved(repository):
    original = "".join(f"line {number}\n" for number in range(1, 11))
    await commit(repository, {"gone.py": "a\nb\nc\n", "old_name.py": original})
    renamed = "header\n" + original.replace("line 7\n", "line seven\n")
    await git(repository, "mv", "old_name.py", "new_name.py")
    await commit(
        repository, {"gone.py": None, "new_name.py": renamed, "tail.py": "x\ny"}
    )

    scope = await build_code_change_reader(repository).read("HEAD", base="HEAD~1")

    gone = next(change for change in scope.files if change.old_path == "gone.py")
    assert (gone.status, gone.new_path, gone.deletions) == ("deleted", None, 3)
    assert lines(scope, "gone.py", "removed") == [
        (1, None, "a"),
        (2, None, "b"),
        (3, None, "c"),
    ]
    assert scope.anchor("gone.py", "LEFT", 2)
    assert scope.anchor("gone.py", "RIGHT", 2) is None
    moved = next(change for change in scope.files if change.status == "renamed")
    assert (moved.old_path, moved.new_path) == ("old_name.py", "new_name.py")
    assert moved.similarity is not None and moved.similarity >= 50
    assert lines(scope, "new_name.py", "removed") == [(7, None, "line 7")]
    assert lines(scope, "new_name.py", "added") == [
        (None, 1, "header"),
        (None, 8, "line seven"),
    ]
    assert (6, 7, "line 6") in lines(scope, "new_name.py", "context")
    assert scope.anchor("old_name.py", "LEFT", 7)
    assert scope.anchor("new_name.py", "LEFT", 7) is None
    assert lines(scope, "tail.py", "added") == [(None, 1, "x"), (None, 2, "y")]


async def test_committed_head_is_read_instead_of_working_tree(repository):
    await commit(repository, {"app.py": "one\n"})
    await commit(repository, {"app.py": "one\ntwo\n"})
    reader = build_code_change_reader(repository)
    before = await reader.read("HEAD", base="HEAD~1")
    (repository / "app.py").write_text("dirty\n")
    (repository / "untracked.py").write_text("untracked\n")
    (repository / "staged.py").write_text("staged\n")
    await git(repository, "add", "staged.py")

    after = await reader.read("HEAD", base="HEAD~1")

    assert after.manifest_sha256() == before.manifest_sha256()
    assert [change.new_path for change in after.files] == ["app.py"]
    assert (repository / "app.py").read_text() == "dirty\n"


async def test_unreadable_entries_are_reported_and_never_counted_as_read(repository):
    await commit(repository, {"keep.py": "keep\n", "missing.py": "old\n"})
    for name, content in {
        "readable.py": b"print('ok')\n",
        "binary.bin": b"\x00\x01",
        "latin.txt": b"caf\xe9\n",
        "bad\nname.py": b"x\n",
        "missing.py": b"new\n",
    }.items():
        (repository / name).write_bytes(content)
    with open(os.fsencode(repository) + b"/\xff.py", "wb") as file:
        file.write(b"x\n")
    (repository / "link").symlink_to("keep.py")
    await git(repository, "add", "-A")
    gitlink = await git(repository, "rev-parse", "HEAD")
    await git(
        repository, "update-index", "--add", "--cacheinfo", f"160000,{gitlink},vendor"
    )
    await git(repository, "commit", "-q", "-m", "Fictional unreadable entries")
    missing = await git(repository, "rev-parse", "HEAD:missing.py")
    (repository / ".git/objects" / missing[:2] / missing[2:]).unlink()

    scope = await build_code_change_reader(repository).read("HEAD", base="HEAD~1")

    assert [change.new_path for change in scope.files] == ["readable.py"]
    reasons = {(item.reason, item.new_path) for item in scope.omissions}
    assert reasons == {
        ("binary", "binary.bin"),
        ("not_utf8", "latin.txt"),
        ("invalid_path", "bad\\x0aname.py"),
        ("invalid_path", "\\xff.py"),
        ("symlink", "link"),
        ("submodule", "vendor"),
        ("missing_object", "missing.py"),
    }
    assert not scope.complete
    assert {
        (limitation.code, limitation.affects_completeness)
        for limitation in scope.limitations()
    } == {("scope_excluded", True)}

    executable = shutil.which("git")
    assert executable
    limited = CodeChangeReaderService(
        RepositoryServiceProvider(repository, executable), max_file_bytes=4
    )
    small = await limited.read("HEAD", base="HEAD~1")
    assert ("too_large", "readable.py") in {
        (item.reason, item.new_path) for item in small.omissions
    }


async def test_repository_controlled_helpers_and_replacements_are_ignored(
    repository, tmp_path
):
    marker = tmp_path / "helper-ran"
    helper = tmp_path / "helper.sh"
    helper.write_text(f"#!/bin/sh\ntouch {marker}\ncat\n")
    helper.chmod(0o755)
    await commit(repository, {".gitattributes": "* diff=lantern filter=lantern\n"})
    await commit(repository, {"app.py": "a\n\nb\nc\nd\n"})
    head = await commit(repository, {"app.py": "a\n\nb\nchanged\nd\n"})
    decoy = await commit(repository, {"decoy.py": "decoy\n"})
    await git(repository, "replace", head, decoy)
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    for name in ("reference-transaction", "post-index-change", "post-checkout"):
        shutil.copy(helper, hooks / name)
    for key, value in {
        "core.hooksPath": str(hooks),
        "core.fsmonitor": str(helper),
        "core.pager": str(helper),
        "diff.external": str(helper),
        "diff.lantern.textconv": str(helper),
        "diff.lantern.command": str(helper),
        "filter.lantern.clean": str(helper),
        "filter.lantern.smudge": str(helper),
        "diff.suppressBlankEmpty": "true",
        "diff.context": "0",
        "diff.noprefix": "true",
    }.items():
        await git(repository, "config", key, value)

    scope = await build_code_change_reader(repository).read(head, base=f"{head}~1")

    assert not marker.exists()
    assert [change.new_path for change in scope.files] == ["app.py"]
    assert (2, 2, "") in lines(scope, "app.py", "context")
    assert lines(scope, "app.py", "added") == [(None, 4, "changed")]


async def test_unavailable_versions_and_repositories_are_explicit(repository, tmp_path):
    await commit(repository, {"app.py": "one\n"})
    await git(repository, "switch", "-q", "--orphan", "unrelated")
    await commit(repository, {"other.py": "two\n"})
    reader = build_code_change_reader(repository)

    with pytest.raises(ChangeError, match="either"):
        await reader.read("HEAD")
    with pytest.raises(ChangeError, match="either"):
        await reader.read("HEAD", target="main", base="main")
    for revision in ("--output=written", "main..HEAD", "main:app.py", ""):
        with pytest.raises(ChangeError, match="Unsupported version"):
            await reader.read("HEAD", base=revision)
    assert not (repository / "written").exists()
    with pytest.raises(ChangeError, match="not available"):
        await reader.read("HEAD", base="does-not-exist")
    with pytest.raises(ChangeError, match="shared starting point"):
        await reader.read("unrelated", target="main")
    (repository / "nested").mkdir()
    with pytest.raises(ChangeError, match="not a Git repository"):
        await build_code_change_reader(repository / "nested").read("HEAD", base="HEAD")
    with pytest.raises(ChangeError, match="not a directory"):
        build_code_change_reader(tmp_path / "absent")


async def test_slow_git_is_stopped_and_reported(repository):
    await commit(repository, {"app.py": "one\n"})
    executable = shutil.which("git")
    assert executable
    reader = CodeChangeReaderService(
        RepositoryServiceProvider(repository, executable, timeout_seconds=0)
    )
    with pytest.raises(ChangeError, match="in time"):
        await reader.read("HEAD", base="HEAD")
