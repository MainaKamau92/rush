from pathlib import Path

import pytest

from tests.integration.test_code_change_reader import git, run


@pytest.fixture
async def remote(tmp_path):
    example = Path(await run("sh", "scripts/reset-example.sh", "unsafe"))
    bare = tmp_path / "remote/lantern/demo.git"
    await run("git", "clone", "-q", "--bare", str(example), str(bare))
    head = await git(bare, "rev-parse", "fixture-head^{commit}")
    base = await git(bare, "rev-parse", "fixture-base^{commit}")
    await git(bare, "update-ref", "refs/pull/7/head", head)
    await git(bare, "update-ref", "refs/heads/main", base)
    return tmp_path / "remote", head, base
