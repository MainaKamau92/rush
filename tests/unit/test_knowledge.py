import hashlib
import sys
from pathlib import Path

import pytest

from scripts.knowledge import check, main

PAGE = """---
type: Work State
title: Current work
description: Test checkpoint.
generated: {by: fixture/1, at: "2026-10-29T09:23:11Z"}
sources:
  - resource: https://example.com/source
---
# Current work

TCR-002 is paused; no live model request has been made.
"""


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    bundle = tmp_path / "knowledge"
    bundle.mkdir()
    (bundle / "index.md").write_text(
        '---\nokf_version: "0.2"\n---\n# Knowledge\n'
        "- [Current](current-state.md)\n"
        "- [Maintenance](maintenance.md)\n"
        "- [Log](log.md)\n"
    )
    (bundle / "current-state.md").write_text(PAGE)
    (bundle / "maintenance.md").write_text(PAGE)
    (bundle / "log.md").write_text("# Log\n\n## 2026-10-29\n\n- Created.\n")
    return tmp_path


def test_complete_bundle_allows_new_concept_types_and_extensions(
    checkout: Path,
) -> None:
    page = checkout / "knowledge/current-state.md"
    page.write_text(
        PAGE.replace("Work State", "New Concept").replace(
            "title: Current work", "x_future: retained\ntitle: Current work"
        )
    )
    assert check(checkout) == []


@pytest.mark.parametrize(
    "content",
    [
        "# Missing metadata\n",
        "---\ntype: [\n---\n# Invalid YAML\n",
        PAGE.replace("type: Work State", 'type: ""'),
        PAGE.replace("2026-10-29T09:23:11Z", "2026-10-29T09:23:11"),
        PAGE.replace(
            "  - resource: https://example.com/source", "  - title: No source"
        ),
    ],
)
def test_incomplete_or_invalid_context_cannot_be_handed_off(
    checkout: Path, content: str
) -> None:
    (checkout / "knowledge/current-state.md").write_text(content)
    assert any("current-state.md: invalid page" in error for error in check(checkout))


def test_missing_checkpoint_and_unindexed_topics_fail(checkout: Path) -> None:
    (checkout / "knowledge/current-state.md").unlink()
    (checkout / "knowledge/forgotten.md").write_text(PAGE)
    errors = check(checkout)
    assert "Missing knowledge/current-state.md" in errors
    assert any("missing link target current-state.md" in error for error in errors)
    assert any(
        "forgotten.md: missing from directory index" in error for error in errors
    )


def test_links_resolve_within_bundle_and_skip_examples_and_web_urls(
    checkout: Path,
) -> None:
    page = checkout / "knowledge/current-state.md"
    page.write_text(
        PAGE + "\n[Maintenance](/maintenance.md#steps)\n"
        "[Web](https://example.com/not-a-local-file.md)\n"
        "```markdown\n[Example](not-created.md)\n```\n"
    )
    assert check(checkout) == []
    page.write_text(PAGE + "\n[Outside](../outside.md)\n")
    assert any("invalid page" in error for error in check(checkout))


def test_changed_canonical_source_requires_refreshing_the_summary(
    checkout: Path,
) -> None:
    source = checkout / "policy.md"
    source.write_text("Initial policy")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    page = checkout / "knowledge/current-state.md"
    page.write_text(
        PAGE.replace(
            "  - resource: https://example.com/source",
            "  - resource: https://example.com/policy\n"
            f"    x_repo_path: policy.md\n    x_sha256: {digest}",
        )
    )
    assert check(checkout) == []
    source.write_text("Revised policy")
    assert any("current-state.md: invalid page" in error for error in check(checkout))


def test_invalid_log_and_nested_index_metadata_fail(checkout: Path) -> None:
    (checkout / "knowledge/log.md").write_text(
        "# Log\n\n## 2026-10-28\n\n- Older.\n\n## 2026-10-29\n\n- Newer.\n"
    )
    references = checkout / "knowledge/references"
    references.mkdir()
    (references / "index.md").write_text('---\nokf_version: "0.2"\n---\n# Sources\n')
    errors = check(checkout)
    assert any("log.md: invalid page" in error for error in errors)
    assert any("references/index.md: invalid page" in error for error in errors)


def test_nested_index_is_discovered_from_its_parent(checkout: Path) -> None:
    index = checkout / "knowledge/index.md"
    index.write_text(index.read_text() + "- [Sources](references/)\n")
    references = checkout / "knowledge/references"
    references.mkdir()
    (references / "index.md").write_text("# Sources\n\n- [Source](source.md)\n")
    (references / "source.md").write_text(PAGE)
    assert check(checkout) == []


def test_symlink_cannot_add_files_from_outside_the_bundle(checkout: Path) -> None:
    (checkout / "outside.md").write_text(PAGE)
    (checkout / "knowledge/linked.md").symlink_to(checkout / "outside.md")
    assert any("symlinks are not allowed" in error for error in check(checkout))


def test_context_prints_saved_work_and_refuses_an_incomplete_handoff(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(checkout)
    monkeypatch.setattr(sys, "argv", ["knowledge", "context"])
    assert main() == 0
    result = capsys.readouterr()
    assert "TCR-002 is paused" in result.out
    assert "live Git/PR state" in result.out
    (checkout / "knowledge/current-state.md").unlink()
    assert main() == 1
    result = capsys.readouterr()
    assert result.out == ""
    assert "Missing knowledge/current-state.md" in result.err


def test_fresh_clone_can_skip_absent_internal_knowledge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["knowledge", "check", "--if-present"])
    assert main() == 0
    assert "Local knowledge absent; skipping" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["knowledge", "check"])
    assert main() == 1
    assert "Missing knowledge/index.md" in capsys.readouterr().err


def test_optional_check_still_rejects_incomplete_local_knowledge(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(checkout)
    monkeypatch.setattr(sys, "argv", ["knowledge", "check", "--if-present"])
    (checkout / "knowledge/current-state.md").unlink()
    assert main() == 1
    assert "Missing knowledge/current-state.md" in capsys.readouterr().err


def test_optional_check_does_not_skip_a_broken_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["knowledge", "check", "--if-present"])
    (tmp_path / "knowledge").symlink_to(tmp_path / "absent")
    assert main() == 1
    assert "not a symlink" in capsys.readouterr().err
