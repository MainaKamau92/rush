import json
from datetime import UTC, datetime

import pytest

from app.core.errors import ChangeError, ReviewError
from app.models.code_change import RepositoryFile, SearchMatch
from app.schemas.code_change import Omission
from app.schemas.review import ReviewLimits, VersionPin
from app.services.model_context import ModelContext
from app.services.review_submission import (
    SubmittedFinding,
    nearest_anchor,
    parse_submission,
    to_draft,
)
from app.services.review_tools import RepositoryTools, is_secret_file, render_change
from tests.unit.test_investigation import HEAD, make_service, scope


def now():
    return datetime(2026, 1, 15, tzinfo=UTC)


class SearchRepository:
    """The investigation test repository plus search and listing."""

    def __init__(self, repository):
        self._repository = repository
        self.files = repository.files
        self.searches = []

    async def file(self, commit, path, limit):
        return await self._repository.file(commit, path, limit)

    async def search(self, commit, pattern, path, *, fixed, ignore_case):
        self.searches.append((commit, pattern, path, fixed, ignore_case))
        if pattern == "broken":
            raise ChangeError("Search failed; check the pattern")
        return [
            SearchMatch("store.py", 3, "def lookup():"),
            SearchMatch(".env", 1, "SECRET=1"),
            SearchMatch("pkg/many.py", 9, "x" * 400),
        ]

    async def list_files(self, commit, path):
        if path == "missing":
            raise ChangeError("Listing failed at the frozen commit")
        return [f"file{number}.py" for number in range(3 if path else 501)]


async def tools(budget=600_000, files=None):
    service, repository, _, _ = make_service(ReviewLimits())
    await service.start("head", base="base")
    searching = SearchRepository(repository)
    repository.files.update(files or {})
    service._repository = searching
    limits = []
    return (
        RepositoryTools(service, service.active_scope, budget, limits.append),
        service,
        limits,
    )


async def test_reads_whole_files_ranges_and_base_versions_with_an_audit_trail():
    runner, service, _ = await tools()
    whole = await runner.run("read_file", json.dumps({"path": "store.py"}))
    assert whole.splitlines()[0] == "store.py (head) lines 1-4 of 4"
    assert "3| def lookup():" in whole
    part = await runner.run(
        "read_file", json.dumps({"path": "store.py", "start_line": 2, "end_line": 3})
    )
    assert part.splitlines()[0] == "store.py (head) lines 2-3 of 4"
    base = await runner.run(
        "read_file", json.dumps({"path": "store.py", "ref": "base"})
    )
    assert base.startswith("store.py (base)")
    assert runner.commit("base") == "a" * 40
    assert await runner.run("read_file", '{"path": "store.py", "start_line": 9}') == (
        "Error: store.py has only 4 lines."
    )
    uses = service.report().tool_uses
    assert [(use.tool, use.outcome) for use in uses] == [
        ("read_file", "ok"),
        ("read_file", "ok"),
        ("read_file", "ok"),
        ("read_file", "failed"),
    ]
    assert uses[0].bytes > 0


async def test_long_files_are_returned_in_parts():
    long = "\n".join(f"line {number}" for number in range(1, 2001)).encode()
    runner, _, _ = await tools(
        files={"long.py": RepositoryFile("long.py", "9" * 40, "100644", long)}
    )
    first = await runner.run("read_file", '{"path": "long.py"}')
    assert first.splitlines()[0] == (
        "long.py (head) lines 1-1500 of 2000; continue with start_line=1501"
    )
    wide = ("y" * 400 + "\n") * 1000
    runner, _, _ = await tools(
        files={"wide.py": RepositoryFile("wide.py", "8" * 40, "100644", wide.encode())}
    )
    header = (await runner.run("read_file", '{"path": "wide.py"}')).splitlines()[0]
    assert header.startswith("wide.py (head) lines 1-") and "continue with" in header


@pytest.mark.parametrize(
    ("name", "arguments", "message"),
    [
        ("read_file", '{"path": "missing.py"}', "does not exist at head"),
        ("read_file", '{"path": ".env"}', "cannot be read"),
        ("read_file", '{"path": "../x"}', "cannot be read"),
        ("read_file", '{"path": "link"}', "Not a regular file"),
        ("read_file", '{"path": "big.bin"}', "larger than 2 MB"),
        ("read_file", '{"path": "blob.bin"}', "Binary file"),
        ("read_file", "[1]", "JSON object"),
        ("read_file", "{not json", "JSON object"),
        ("read_file", '{"path": 3, "extra": 1}', "invalid arguments"),
        ("delete_file", "{}", "unknown tool"),
    ],
)
async def test_refused_and_invalid_calls_explain_themselves(name, arguments, message):
    runner, _, _ = await tools(
        files={
            "link": RepositoryFile("link", "7" * 40, "120000", b"store.py"),
            "big.bin": RepositoryFile("big.bin", "6" * 40, "100644", None),
            "blob.bin": RepositoryFile("blob.bin", "5" * 40, "100644", b"a\0b"),
        }
    )
    assert message in await runner.run(name, arguments)


def test_secret_files_are_refused_but_examples_are_not():
    assert is_secret_file(".env") and is_secret_file("app/.env.production")
    assert is_secret_file("APP/.ENV") and is_secret_file("infra/prod.tfvars")
    assert is_secret_file("deploy/server.pem") and is_secret_file("secrets/db.txt")
    assert not is_secret_file(".env.example") and not is_secret_file("app/env.py")


async def test_search_filters_secrets_and_globs_and_reports_failures():
    runner, service, _ = await tools()
    result = await runner.run(
        "search", json.dumps({"pattern": "lookup", "path": "pkg", "ignore_case": True})
    )
    assert result.splitlines() == [
        "store.py:3: def lookup():",
        "pkg/many.py:9: " + "x" * 300,
    ]
    assert service.repository.searches[0] == (HEAD, "lookup", "pkg", False, True)
    filtered = await runner.run(
        "search", json.dumps({"pattern": "lookup", "glob": "pkg/**", "fixed": True})
    )
    assert filtered.startswith("pkg/many.py:9:")
    none = await runner.run("search", json.dumps({"pattern": "lookup", "glob": "*.go"}))
    assert none == "No matches."
    assert "check the pattern" in await runner.run("search", '{"pattern": "broken"}')
    assert "invalid arguments" in await runner.run("search", '{"pattern": ""}')


async def test_search_results_are_capped():
    runner, service, _ = await tools()

    async def many(commit, pattern, path, *, fixed, ignore_case):
        return [SearchMatch("a.py", number, "x") for number in range(1, 201)]

    service.repository.search = many
    rows = (await runner.run("search", '{"pattern": "x"}')).splitlines()
    assert len(rows) == 151 and rows[-1].startswith("[50 more matches")


async def test_listing_is_capped_and_failures_are_reported():
    runner, _, _ = await tools()
    rows = (await runner.run("list_files", "{}")).splitlines()
    assert len(rows) == 501 and rows[-1].startswith("[1 more files")
    assert await runner.run("list_files", '{"path": "pkg"}') == (
        "file0.py\nfile1.py\nfile2.py"
    )
    assert "Listing failed" in await runner.run("list_files", '{"path": "missing"}')


async def test_conversation_read_limit_truncates_then_refuses():
    runner, service, limits = await tools(budget=60)
    first = await runner.run("read_file", '{"path": "store.py"}')
    assert first.endswith("[truncated: conversation read limit reached]")
    assert limits == ["read_file"] and runner.remaining_bytes == 0
    refused = await runner.run("search", '{"pattern": "x"}')
    assert refused.startswith("Error: this conversation's read limit is reached")
    assert service.report().tool_uses[-1].outcome == "refused"


def test_change_is_rendered_with_head_and_base_line_numbers():
    change = scope()
    file = change.files[0]
    renamed = replace_file(file, status="renamed", old_path="old.py")
    text = render_change(
        change.model_copy(
            update={
                "files": (renamed,),
                "omissions": (
                    Omission(
                        reason="ignored",
                        old_path=None,
                        new_path="package-lock.json",
                        detail="ignored by the review settings",
                        intentional=True,
                    ),
                ),
            }
        )
    )
    assert text.splitlines() == [
        "## customers.py (renamed, +1 -1) renamed from old.py",
        "@@ base 4,1 head 4,1 @@",
        "-    4 |     return None",
        "+    4 |     return lookup()",
        "## package-lock.json (not shown: ignored by the review settings)",
    ]


def replace_file(file, **changes):
    return file.model_copy(update=changes)


def submitted(**changes):
    return SubmittedFinding.model_validate(
        {
            "path": "customers.py",
            "line": 4,
            "category": "security",
            "severity": "high",
            "problem": "Unscoped lookup.",
            "consequence": "Another tenant's data.",
            "trigger_scenario": "Two tenants share an ID.",
            "remediation": "Pass the tenant.",
            "evidence": [{"path": "store.py", "start_line": 3, "end_line": 4}],
        }
        | changes,
        strict=False,
    )


def test_submissions_are_parsed_or_explained():
    parsed = parse_submission(
        json.dumps({"findings": [submitted().model_dump(mode="json")]})
    )
    assert parsed.findings[0].side == "RIGHT" and parsed.limitations == ()
    assert parse_submission("").findings == ()
    with pytest.raises(ReviewError, match="findings.0.severity"):
        parse_submission(json.dumps({"findings": [{"severity": "huge"}]}))


def test_findings_snap_to_the_nearest_changed_line_on_their_side():
    change = scope()
    assert nearest_anchor(change, submitted(line=40)).line == 4
    left = nearest_anchor(change, submitted(side="LEFT", line=1))
    assert (left.side, left.line, left.hunk_id) == ("LEFT", 4, "lookup-hunk")
    with pytest.raises(ReviewError, match="no added line"):
        nearest_anchor(change, submitted(path="other.py"))


async def test_drafts_freeze_cited_file_lines_and_the_anchored_change(review_inputs):
    runner, service, _ = await tools()
    inputs = review_inputs.model_copy(update={"sources": review_inputs.sources[:1]})
    context = ModelContext(inputs, service, "public", now)
    context.prepare()
    rules = (VersionPin(id="team.rule", version="2", digest="0" * 64),)
    draft = await to_draft(
        submitted(
            rule_id="team.rule",
            evidence=[
                {"path": "store.py", "start_line": 3, "end_line": 99},
                {
                    "source_id": inputs.sources[0].id,
                    "start_line": 1,
                    "end_line": 1,
                },
            ],
        ),
        service.active_scope,
        context,
        runner,
        rules,
    )
    assert draft.rule_ref.version == "2"
    assert draft.anchor.hunk_id == "lookup-hunk"
    assert [item.source_id for item in draft.evidence] == [
        "diff:lookup-hunk",
        "file:head:store.py#L3-L4",
        inputs.sources[0].id,
    ]
    assert (draft.evidence[0].start, draft.evidence[0].end) == (2, 2)
    assert context.quote("file:head:store.py#L3-L4", 1, 2) == (
        "def lookup():\n    return value()"
    )
    assert draft.causal_path == draft.evidence
    assert "source_id: " + inputs.sources[0].id in context.sources_text()
    assert "file:head" not in context.sources_text()


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"rule_id": "unknown"}, "not an approved rule"),
        (
            {"evidence": [{"source_id": "nope", "start_line": 1, "end_line": 1}]},
            "not a supplied source passage",
        ),
        ({"evidence": [{"start_line": 1, "end_line": 1}]}, "path or a source_id"),
        (
            {"evidence": [{"path": "gone.py", "start_line": 1, "end_line": 1}]},
            "cannot be read",
        ),
        (
            {"evidence": [{"path": "store.py", "start_line": 50, "end_line": 51}]},
            "only 4 lines",
        ),
    ],
)
async def test_invalid_draft_evidence_is_explained(review_inputs, changes, message):
    runner, service, _ = await tools()
    context = ModelContext(
        review_inputs.model_copy(update={"sources": ()}),
        service,
        "public",
        now,
    )
    context.prepare()
    with pytest.raises(ReviewError, match=message):
        await to_draft(submitted(**changes), service.active_scope, context, runner, ())


async def test_tool_findings_are_placed_inline_on_their_changed_line(review_inputs):
    from types import SimpleNamespace

    from app.models.github import Placement
    from app.services.pull_request_publication import PullRequestPublisher

    runner, service, _ = await tools()
    context = ModelContext(
        review_inputs.model_copy(update={"sources": ()}), service, "public", now
    )
    context.prepare()
    change = service.active_scope
    for side, line in (("RIGHT", 40), ("LEFT", 4)):
        draft = await to_draft(
            submitted(side=side, line=line), change, context, runner, ()
        )
        moved = "This concerns line 40 of the new customers.py"
        assert (moved in draft.problem) == (line == 40)
        record = SimpleNamespace(inputs=SimpleNamespace(head_sha=HEAD))
        assert PullRequestPublisher._placement(record, draft, change) == Placement(
            HEAD, "customers.py", 4, side
        )


def test_lines_are_numbered_as_git_numbers_them():
    from app.services.review_tools import file_lines

    assert file_lines("a\x0cb\nc\r\n\u2028d\n") == ["a b", "c ", " d"]
    assert file_lines("") == [] and file_lines("x") == ["x"]


async def test_huge_lines_and_folder_paths_are_handled():
    wide = ("z" * 300_000 + "\nshort\n").encode()
    runner, service, _ = await tools(
        files={"min.js": RepositoryFile("min.js", "4" * 40, "100644", wide)}
    )
    first = await runner.run("read_file", '{"path": "min.js"}')
    assert first.splitlines()[0].endswith("continue with start_line=2")
    assert first.endswith(" [line cut short]") and len(first) < 170_000
    await runner.run("search", '{"pattern": "x", "path": "pkg/"}')
    await runner.run("search", '{"pattern": "x", "path": "./"}')
    assert [item[2] for item in service.repository.searches] == ["pkg", None]
