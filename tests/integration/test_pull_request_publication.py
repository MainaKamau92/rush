import pytest

from app.core.errors import CodeHostError, PlacementError, PublicationUncertainError
from app.db.repositories.publications import SQLitePublicationRepository
from app.models.github import Placement
from app.schemas.local_review import ReviewOutcome
from app.schemas.review import Limitation, ReviewBatch, ReviewResult, WaivedFinding
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

    def new_commit(self):
        head = f"{self.runs + 1:040x}"
        self.inputs = self.inputs.model_copy(update={"head_sha": head})
        self.host.pull = self.host.pull.model_copy(update={"head_sha": head})

    def finding(self, run_id, fingerprint, side="RIGHT", number=1):
        return self.template.model_copy(
            update={
                "id": f"{run_id}-{number}",
                "run_id": run_id,
                "fingerprint": fingerprint,
                "anchor": self.template.anchor.model_copy(update={"side": side}),
            }
        )

    async def outcome(
        self, fingerprints=(), status="completed", limitations=(), waived=(), **extra
    ):
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
            waived=tuple(
                WaivedFinding(
                    finding=self.finding(run_id, item),
                    exception_id="exception-1",
                    reason="Approved exception",
                )
                for item in waived
            ),
            **extra,
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
    assert "https://github.com/lantern/demo/pull/7#discussion_r1" in summary


async def test_fenced_assumptions_cannot_hide_host_review_details(harness):
    from markdown_it import MarkdownIt

    outcome = await harness.outcome([(TENANT, "RIGHT")])
    result = outcome.record.progress.result
    finding = result.findings[0].model_copy(
        update={
            "assumptions": ("```html\n<details><summary>hide evidence</summary>\n```",),
        }
    )
    outcome = outcome.model_copy(
        update={
            "record": outcome.record.model_copy(
                update={
                    "progress": outcome.record.progress.model_copy(
                        update={
                            "result": result.model_copy(update={"findings": (finding,)})
                        }
                    )
                }
            )
        }
    )
    await harness.publisher.publish(harness.job, outcome)
    rendered = MarkdownIt().render(harness.host.comments["review"][1])
    assert rendered.count("<details>") == 1
    assert "&lt;details&gt;" in rendered
    assert "<summary>hide evidence" not in rendered


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
    assert "**Exhausted limits**" in summary and "1 not rechecked" in summary
    harness.new_commit()
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
    assert "**Publication problems**" in summary and "HTTP 403" in summary
    assert summary.count("**High security**") == 2
    assert "Suggested fix:" not in summary
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
    assert "Execution error:" in summary
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


async def test_grouped_limits_are_collapsed_deduplicated_and_plain(harness):
    note = Limitation(code="budget", reason="Review budget exhausted: source_bytes")
    outcome = await harness.outcome(status="partial", limitations=(note, note))
    summary = harness.publisher.summary(outcome, "incomplete", Publication())
    assert summary.count("<details>") == 1
    assert summary.count("source allowance") == 1
    assert "source_bytes" not in summary and "`budget`" not in summary
    assert summary.index("source allowance") > summary.index("<details>")


async def test_a_missing_ticket_is_one_plain_note_on_a_complete_review(harness):
    notes = tuple(
        Limitation(code="missing_ticket", reason=reason, affects_completeness=False)
        for reason in ("No ticket link was found", "No ticket.")
    )
    outcome = await harness.outcome(limitations=notes)
    conclusion, title = harness.publisher.conclusion(outcome.record, Publication())
    summary = harness.publisher.summary(outcome, title, Publication())
    assert (conclusion, title) == ("success", "No supported problems found")
    assert "Missing context" not in summary and "<details>" not in summary
    assert summary.count("no linked ClickUp ticket could be used") == 1


async def test_invalid_policy_is_not_hidden_by_the_no_applicable_rules_wording(harness):
    outcome = await harness.outcome(
        status="partial",
        limitations=(
            Limitation(
                code="policy_not_applied",
                reason="The supplied rule's approver is not authorized",
            ),
        ),
    )
    record = outcome.record.model_copy(
        update={"inputs": outcome.record.inputs.model_copy(update={"rules": ()})}
    )
    summary = harness.publisher.summary(
        outcome.model_copy(update={"record": record}), "incomplete", Publication()
    )
    assert "approver is not authorized" in summary
    assert "No approved team rule applies" in summary


async def test_a_placement_rejection_alone_is_disclosed(harness):
    host = harness.host
    host._state()
    host.post_errors = [
        PlacementError("GitHub could not place the comment on that line")
    ]
    title = await harness.publisher.publish(
        harness.job, await harness.outcome([(TENANT, "RIGHT")])
    )
    assert "some results could not be published" in title
    assert not host.comments["review"]
    summary = next(iter(host.comments["issue"].values()))
    assert "Publication problems" in summary and "could not place" in summary
    assert "discussion_r" not in summary
    assert host.checks[-1][1] == "neutral"


async def test_resolution_history_survives_recurrence_and_can_resolve_again(harness):
    from app.services.pull_request_publication import REASSESSMENT, resolved

    host = harness.host
    await harness.publisher.publish(
        harness.job, await harness.outcome([(TENANT, "RIGHT")])
    )
    host.comments["review"][1] += "\n\n" + REASSESSMENT + "\nAn earlier reassessment."
    harness.new_commit()
    await harness.publisher.publish(harness.job, await harness.outcome())
    assert resolved(host.comments["review"][1])
    await harness.publisher.publish(
        harness.job, await harness.outcome([(TENANT, "RIGHT")])
    )
    body = host.comments["review"][1]
    assert "**Resolved:**" in body and "**Reopened:**" in body
    assert "An earlier reassessment." in body and not resolved(body)
    await harness.publisher.publish(
        harness.job, await harness.outcome([(TENANT, "RIGHT")])
    )
    assert host.comments["review"][1].count("**Resolved:**") == 1
    harness.new_commit()
    await harness.publisher.publish(harness.job, await harness.outcome())
    body = host.comments["review"][1]
    assert body.count("**Resolved:**") == 2 and resolved(body)
    assert "An earlier reassessment." in body
    assert len(host.comments["review"]) == 1


@pytest.mark.parametrize("side", ["LEFT", "RIGHT"])
async def test_replacement_evidence_anchors_the_supported_side_range(harness, side):
    from app.schemas.code_change import ChangeLine
    from tests.unit.test_investigation import scope

    outcome = await harness.outcome([(TENANT, side)])
    finding = outcome.record.progress.result.findings[0]
    evidence = finding.evidence[0].model_copy(
        update={"source_id": "diff:lookup", "start": 1, "end": 4}
    )
    finding = finding.model_copy(update={"evidence": (evidence,)})
    original = scope()
    file = original.files[0]
    hunk = file.hunks[0].model_copy(
        update={
            "id": "lookup",
            "lines": (
                ChangeLine(kind="removed", old_line=4, text="old value"),
                ChangeLine(kind="removed", old_line=5, text="old return"),
                ChangeLine(kind="added", new_line=4, text="new value"),
                ChangeLine(kind="added", new_line=5, text="new return"),
            ),
        }
    )
    original = original.model_copy(
        update={"files": (file.model_copy(update={"hunks": (hunk,)}),)}
    )
    placement = harness.publisher._placement(outcome.record, finding, original)
    assert placement.start_line == 4 and placement.line == 5
    assert placement.side == side


async def test_an_intentionally_excluded_file_does_not_resolve_its_old_finding(
    harness, monkeypatch
):
    from dataclasses import replace

    from app.schemas.code_change import Omission
    from tests.unit.test_investigation import scope

    host = harness.host
    await harness.publisher.publish(
        harness.job, await harness.outcome([(TENANT, "RIGHT")])
    )
    comments = host.bot_comments

    async def with_path(*args):
        return [
            replace(comment, path="customers.py") for comment in await comments(*args)
        ]

    monkeypatch.setattr(host, "bot_comments", with_path)
    outcome = await harness.outcome()
    excluded = scope().model_copy(
        update={
            "files": (),
            "omissions": (
                Omission(
                    reason="ignored",
                    old_path="customers.py",
                    new_path="customers.py",
                    detail="Configured exclusion",
                    intentional=True,
                ),
            ),
        }
    )
    outcome = outcome.model_copy(
        update={
            "investigation": outcome.investigation.model_copy(
                update={"scope": excluded}
            )
        }
    )
    await harness.publisher.publish(harness.job, outcome)
    assert "**Resolved:**" not in host.comments["review"][1]
    assert host.checks[-1][1] == "neutral"
    assert "1 not rechecked" in next(iter(host.comments["issue"].values()))


async def test_a_finding_not_repeated_on_the_same_commit_stays_open(harness):
    from app.models.github import HostComment
    from app.services.pull_request_publication import _reported_at

    host = harness.host
    await harness.publisher.publish(
        harness.job, await harness.outcome([(TENANT, "RIGHT")])
    )
    title = await harness.publisher.publish(harness.job, await harness.outcome())
    assert title == "No supported problems found; earlier findings still open"
    assert host.checks[-1][1] == "neutral"
    assert "**Resolved:**" not in host.comments["review"][1]
    assert "1 not reported again on unchanged code" in host.comments["issue"][2]
    harness.new_commit()
    assert await harness.publisher.publish(harness.job, await harness.outcome()) == (
        "No supported problems found"
    )
    assert "**Resolved:**" in host.comments["review"][1]
    # Comments made before the marker existed fall back to their original commit.
    head = harness.inputs.head_sha
    assert _reported_at(HostComment(1, "older body", commit=head)) == head
    assert _reported_at(HostComment(1, "older body")) is None


async def test_a_waiver_or_withdrawal_still_resolves_on_the_same_commit(harness):
    from app.services.pull_request_publication import WITHDRAWN

    host = harness.host
    await harness.publisher.publish(
        harness.job, await harness.outcome([(TENANT, "RIGHT"), (EMAIL, "RIGHT")])
    )
    tenant, email = sorted(host.comments["review"])
    host.comments["review"][email] += (
        f"\n\n{WITHDRAWN}\n**Withdrawn after a challenge**"
    )
    title = await harness.publisher.publish(
        harness.job, await harness.outcome(waived=(TENANT,))
    )
    assert title == "No supported problems found"
    assert host.checks[-1][1] == "success"
    assert "**Resolved:**" in host.comments["review"][tenant]
    assert "**Resolved:**" in host.comments["review"][email]


async def test_files_not_reviewed_for_defects_are_named_and_never_pass(harness):
    host = harness.host
    docs = ReviewBatch(number=1, paths=("README.md",), status="completed")
    title = await harness.publisher.publish(
        harness.job,
        await harness.outcome(batches=(docs,), unreviewed_paths=("README.md",)),
    )
    assert title == "No file was reviewed for defects"
    assert host.checks[-1][1] == "neutral"
    summary = host.comments["issue"][1]
    assert "Not reviewed for defects by any skill: `README.md`" in summary
    mixed = docs.model_copy(update={"paths": ("README.md", "app.py")})
    title = await harness.publisher.publish(
        harness.job,
        await harness.outcome(batches=(mixed,), unreviewed_paths=("README.md",)),
    )
    assert title == "No supported problems found"
    assert host.checks[-1][1] == "success"
    many = tuple(f"doc{i:02}.md" for i in range(25))
    await harness.publisher.publish(
        harness.job,
        await harness.outcome(
            batches=(docs.model_copy(update={"paths": (*many, "app.py")}),),
            unreviewed_paths=many,
        ),
    )
    assert "and 5 more._" in host.comments["issue"][1]
