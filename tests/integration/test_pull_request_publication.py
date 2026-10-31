import pytest

from app.core.errors import CodeHostError, PlacementError, PublicationUncertainError
from app.db.repositories.publications import SQLitePublicationRepository
from app.models.github import Placement
from app.schemas.local_review import ReviewOutcome
from app.schemas.review import Limitation, ReviewResult
from app.services.pull_request_publication import (
    SUMMARY_MARKER,
    Publication,
    PullRequestPublisher,
)
from tests.integration.test_github_events import job
from tests.integration.test_review_jobs import NOTHING_READ, PULL, Host, Worker

TENANT, EMAIL = "a" * 64, "b" * 64


class Harness:
    def __init__(self, settings, inputs, result):
        inputs = inputs.model_copy(update={"head_sha": PULL.head_sha})
        self.worker = Worker(settings, inputs)
        self.host = self.worker.host
        self.inputs = inputs
        self.template = result.findings[0]
        self.store = SQLitePublicationRepository(settings.database_path)
        self.publisher = PullRequestPublisher(self.host, self.store, self.worker.clock)
        self.job = job("job-1")
        self.runs = 0

    def finding(self, run_id, fingerprint, side="RIGHT", number=1):
        return self.template.model_copy(
            update={
                "id": f"{run_id}-{number}",
                "run_id": run_id,
                "fingerprint": fingerprint,
                "anchor": self.template.anchor.model_copy(update={"side": side}),
            }
        )

    async def outcome(self, fingerprints=(), status="completed", limitations=()):
        self.runs += 1
        run_id = f"run-{self.runs}"
        records = self.worker.records
        await records.create(run_id, self.inputs)
        result = ReviewResult(
            findings=tuple(
                self.finding(run_id, item, side, number)
                for number, (item, side) in enumerate(fingerprints, start=1)
            ),
            limitations=limitations,
        )
        if status == "completed":
            for stage in ("preparing", "reviewing", "validating"):
                await records.advance(run_id, stage, "Working")
            await records.advance(run_id, "publishing", "Validated", result)
            record = await records.advance(run_id, "completed", "Review complete")
        else:
            record = await records.advance(run_id, status, "Stopped early", result)
        return ReviewOutcome(record=record, investigation=NOTHING_READ)


@pytest.fixture
def harness(initialized, review_inputs, review_result):
    return Harness(initialized, review_inputs, review_result)


async def test_repeated_runs_update_one_summary_and_one_comment_per_finding(harness):
    host = harness.host
    first = await harness.outcome([(TENANT, "RIGHT"), (EMAIL, "LEFT")])
    title = await harness.publisher.publish(harness.job, first)
    assert title == "2 findings"
    assert len(host.comments["review"]) == 2 and len(host.comments["issue"]) == 1
    assert [placement.side for placement in host.placements[:2]] == ["RIGHT", "LEFT"]
    assert host.placements[0] == Placement(
        harness.inputs.head_sha, "customers.py", 5, "RIGHT"
    )
    assert host.checks[-1] == (harness.inputs.head_sha, "neutral", "2 findings")
    assert await harness.store.items("run-1") == (
        (f"finding:{TENANT}:1", "published", 1),
        (f"finding:{EMAIL}:1", "published", 2),
        ("summary", "published", 3),
    )
    second = await harness.outcome([(TENANT, "RIGHT"), (EMAIL, "LEFT")])
    await harness.publisher.publish(harness.job, second)
    assert len(host.comments["review"]) == 2 and len(host.comments["issue"]) == 1
    summary = next(iter(host.comments["issue"].values()))
    assert summary.startswith(SUMMARY_MARKER) and "run-2" in summary
    assert "commented on the line" in summary


async def test_findings_resolve_only_after_a_complete_recheck(harness):
    host = harness.host
    await harness.publisher.publish(
        harness.job, await harness.outcome([(TENANT, "RIGHT")])
    )
    budget = Limitation(code="budget", reason="The model-call budget ran out")
    incomplete = await harness.outcome(status="partial", limitations=(budget,))
    title = await harness.publisher.publish(harness.job, incomplete)
    assert title == "Review incomplete; no findings so far"
    assert host.checks[-1][1] == "neutral"
    assert "Resolved" not in host.comments["review"][1]
    summary = host.comments["issue"][2]
    assert "### Exhausted limits" in summary and "1 not rechecked" in summary
    clean = await harness.outcome()
    assert await harness.publisher.publish(harness.job, clean) == (
        "No supported problems found"
    )
    assert host.checks[-1][1] == "success"
    assert "**Resolved:**" in host.comments["review"][1]
    assert "1 resolved after a recheck" in host.comments["issue"][2]
    await harness.publisher.publish(harness.job, await harness.outcome())
    assert host.comments["review"][1].count("**Resolved:**") == 1
    host.comments["review"][1] = host.comments["review"][1].split("\n\n<!--")[0]
    host.edit_error = CodeHostError("GitHub returned HTTP 403")
    with pytest.raises(CodeHostError):
        await harness.publisher.publish(harness.job, await harness.outcome())


async def test_unplaceable_and_failed_comments_fall_back_to_the_summary(harness):
    host = harness.host
    host._state()
    host.post_errors = [
        PlacementError("GitHub could not place the comment on that line"),
        CodeHostError("GitHub returned HTTP 403"),
    ]
    outcome = await harness.outcome([(TENANT, "RIGHT"), (EMAIL, "LEFT")])
    title = await harness.publisher.publish(harness.job, outcome)
    assert title == "2 findings; some results could not be published"
    summary = host.comments["issue"][1]
    assert "### Publication problems" in summary and "HTTP 403" in summary
    assert summary.count("- Problem:") == 2 and summary.count(": below") == 2
    assert await harness.store.items("run-1") == (
        (f"finding:{TENANT}:1", "in_summary", None),
        (f"finding:{EMAIL}:1", "failed", None),
        ("summary", "published", 1),
    )


async def test_an_uncertain_response_is_checked_before_posting_again(harness):
    host = harness.host
    host._state()
    host.post_errors = [PublicationUncertainError("saved")]
    await harness.publisher.publish(harness.job, await harness.outcome())
    assert len(host.comments["issue"]) == 1
    host.comments["issue"].clear()
    host.post_errors = [PublicationUncertainError("lost")]
    await harness.publisher.publish(harness.job, await harness.outcome())
    assert len(host.comments["issue"]) == 1
    host.comments["issue"].clear()
    host.post_errors = [CodeHostError("refused"), CodeHostError("refused")]
    with pytest.raises(CodeHostError, match="refused"):
        await harness.publisher.publish(harness.job, await harness.outcome())
    assert (await harness.store.items("run-3"))[-1] == ("summary", "failed", None)


async def test_execution_errors_and_skips_are_never_reported_as_passing(harness):
    failed = await harness.outcome(status="failed")
    assert PullRequestPublisher.conclusion(failed.record, Publication()) == (
        "failure",
        "Review could not run: Stopped early",
    )
    skipped = await harness.outcome(status="skipped")
    assert PullRequestPublisher.conclusion(skipped.record, Publication())[0] == (
        "neutral"
    )
    summary = harness.publisher.summary(failed, "x", Publication())
    assert "### Execution error" in summary
    await harness.publisher.failure(harness.job, "run-9", "c" * 40, "Git failed")
    assert harness.host.checks[-1] == ("c" * 40, "failure", "Review could not run")
    assert "Execution error: Git failed" in harness.host.comments["issue"][1]
    broken = Host()
    broken._state()
    broken.post_errors = [CodeHostError("down")]
    publisher = PullRequestPublisher(broken, harness.store, harness.worker.clock)
    await publisher.failure(harness.job, "run-9", "c" * 40, "Git failed")
    assert broken.checks == []


async def test_identical_lines_keep_separate_comments_and_model_text_is_neutral(
    harness,
):
    host = harness.host
    for _ in range(3):
        outcome = await harness.outcome([(TENANT, "RIGHT"), (TENANT, "LEFT")])
        await harness.publisher.publish(harness.job, outcome)
    assert len(host.comments["review"]) == 2
    template = harness.template
    harness.template = template.model_copy(
        update={"problem": "<!-- hide @org/team ![x](https://example.invalid/a.png)"}
    )
    await harness.publisher.publish(
        harness.job, await harness.outcome([(EMAIL, "RIGHT")])
    )
    body = host.comments["review"][max(host.comments["review"])]
    assert "&lt;!-- hide @\u200borg/team !\\[x]" in body
    assert body.startswith(f"<!-- rush:finding:{EMAIL}:1 -->")
    long = Limitation(code="missing_context", reason="x" * 70000)
    summary = harness.publisher.summary(
        await harness.outcome(status="partial", limitations=(long,)),
        "Review incomplete",
        Publication(),
    )
    assert len(summary) < 61000 and "cut to fit" in summary


async def test_publication_stops_when_a_newer_commit_arrives(harness):
    host = harness.host
    outcome = await harness.outcome([(TENANT, "RIGHT")])
    host.pull = PULL.model_copy(update={"head_sha": "b" * 40})
    assert await harness.publisher.publish(harness.job, outcome) is None
    assert host.comments["issue"] == {} and host.checks == []
    calls = []

    async def moving(installation_id, repository, number):
        calls.append(number)
        return PULL if len(calls) == 1 else host.pull

    host.pull_request = moving
    assert await harness.publisher.publish(harness.job, outcome) is None
    assert host.comments["issue"] == {}


def test_only_real_mentions_are_defanged():
    from app.services.pull_request_publication import safe_text

    assert safe_text("rule lantern.tenant-lookup@1, mail a@b.c") == (
        "rule lantern.tenant-lookup@1, mail a@b.c"
    )
    for text in ("@admin", "Thanks.@admin", "é@admin", "中@admin", "(@org/team)"):
        assert "@\u200b" in safe_text(text)
    assert safe_text("<!-- x --> ![i](u)") == "&lt;!-- x --> !\\[i](u)"
