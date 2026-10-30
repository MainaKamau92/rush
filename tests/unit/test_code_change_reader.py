import pytest
from pydantic import ValidationError

from app.core.errors import ChangeError
from app.models.code_change import TreeChange
from app.schemas.code_change import ChangeScope
from app.services.code_change_reader import CodeChangeReaderService

BASE = "a" * 40
HEAD = "b" * 40
OLD = "c" * 40
NEW = "d" * 40


class FakeRepository:
    def __init__(self, changes, patch="", blobs=None):
        self._changes = changes
        self.patch = patch
        self.blobs = blobs or {OLD: b"one\n", NEW: b"two\n"}

    async def commit(self, revision):
        return {"base": BASE, "head": HEAD}[revision]

    async def merge_base(self, target, head):
        return target

    async def changes(self, base, head):
        return self._changes

    async def blob(self, object_id, limit):
        return self.blobs[object_id]

    async def compare(self, old_object, new_object):
        return self.patch


def modified(**changes):
    values = {
        "status": "M",
        "old_mode": "100644",
        "new_mode": "100644",
        "old_object": OLD,
        "new_object": NEW,
        "old_path": "app.py",
        "new_path": "app.py",
    } | changes
    return TreeChange(**values)


@pytest.mark.parametrize(
    "patch",
    [
        "@@ -1 +1 @@\n-one\n",
        "@@ -1 +1 @@\n-one\n*two\n",
    ],
)
async def test_inconsistent_comparisons_fail_instead_of_dropping_lines(patch):
    reader = CodeChangeReaderService(FakeRepository([modified()], patch))
    with pytest.raises(ChangeError, match="cannot read"):
        await reader.read("head", base="base")


async def test_no_newline_markers_and_mode_only_changes_are_read():
    patch = (
        "diff\n--- a\n+++ b\n@@ -1 +1 @@\n-one\n\\ No newline at end of file\n+two\r\n"
    )
    reader = CodeChangeReaderService(
        FakeRepository(
            [
                modified(),
                modified(
                    old_path="tool.sh",
                    new_path="tool.sh",
                    new_mode="100755",
                    new_object=OLD,
                ),
            ],
            patch,
        )
    )
    scope = await reader.read("head", base="base")
    first, mode_only = scope.files
    assert (first.additions, first.deletions) == (1, 1)
    assert first.hunks[0].lines[-1].text == "two\r"
    assert (mode_only.new_mode, mode_only.hunks) == ("100755", ())
    assert scope.complete and scope.limitations() == ()


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (modified(status="C"), "unsupported_entry"),
        (modified(status="T", new_mode="040000"), "unsupported_entry"),
        (modified(old_path="../app.py", new_path="../app.py"), "invalid_path"),
        (modified(old_path="/app.py", new_path="/app.py"), "invalid_path"),
        (modified(old_path="src/.GIT/x", new_path="src/.GIT/x"), "invalid_path"),
    ],
)
async def test_unsupported_or_unsafe_entries_are_omitted(change, reason):
    scope = await CodeChangeReaderService(FakeRepository([change])).read(
        "head", target="base"
    )
    assert scope.files == ()
    assert [omission.reason for omission in scope.omissions] == [reason]
    assert scope.limitations()[0].code == "scope_excluded"


def test_scope_records_a_target_only_for_merge_base_comparisons():
    with pytest.raises(ValidationError, match="target"):
        ChangeScope(
            comparison="exact",
            target_sha=BASE,
            base_sha=BASE,
            head_sha=HEAD,
            files=(),
            omissions=(),
        )
