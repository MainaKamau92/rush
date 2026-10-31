import json

import httpx
import pytest

from app.core.errors import CodeHostError, PublicationUncertainError
from app.db.repositories.finding_events import SQLiteFindingEventRepository
from app.models.model_access import ModelReply
from app.services.disclosure import WITHHELD
from app.services.finding_conversation import (
    FindingConversationService,
    locate,
    parse_request,
)
from app.services.review_jobs import ReviewJobService
from tests.integration.test_github_adapter import GitHub, adapter
from tests.integration.test_github_events import Events, job
from tests.integration.test_pull_request_publication import TENANT, Harness
from tests.unit.test_model_review import Model

EXPLAINED = {
    "problem": "The lookup ignores the caller's tenant <!--",
    "connection": "Your change dropped tenant_id from the call.",
    "consequence": "Customers can see @org/team data from another tenant.",
    "answer": "Example: demo-blue asks for shared-customer and gets demo-amber.",
}


class Conversation:
    def __init__(self, harness, withheld=False):
        self.harness = harness
        self.model = Model()
        self.models = []
        self.events = SQLiteFindingEventRepository(
            harness.worker.mirrors.parent / "rush.sqlite3"
        )
        self.withheld = withheld
        self.service = FindingConversationService(
            harness.host,
            harness.store,
            harness.worker.records,
            self.events,
            self.provider,
            self.disclose,
            harness.worker.clock,
            ("plain", "short"),
        )

    def provider(self):
        self.models.append(self.model)
        return self.model

    async def disclose(self, outcome):
        if not self.withheld:
            return outcome
        result = outcome.record.progress.result
        hidden = result.model_copy(
            update={
                "findings": tuple(
                    item.model_copy(update={"problem": WITHHELD})
                    for item in result.findings
                )
            }
        )
        progress = outcome.record.progress.model_copy(update={"result": hidden})
        return outcome.model_copy(
            update={"record": outcome.record.model_copy(update={"progress": progress})}
        )

    def job(self, text, comment_id=1, actor="nia-moss"):
        return job("job-thread", head=None).model_copy(
            update={
                "trigger": "thread",
                "comment_id": comment_id,
                "request": text,
                "requested_by": actor,
            }
        )

    async def history(self):
        return [
            (item.actor, item.action, item.reason)
            for item in await self.events.history("lantern/demo", 7, f"{TENANT}:1")
        ]


@pytest.fixture
async def conversation(initialized, review_inputs, review_result):
    harness = Harness(initialized, review_inputs, review_result)
    await harness.publisher.publish(
        harness.job, await harness.outcome([(TENANT, "RIGHT")])
    )
    harness.host.permissions["nia-moss"] = "write"
    return Conversation(harness)


def test_requests_separate_focus_complexity_and_verbosity():
    assert parse_request("hello", "plain", "short") is None
    simple = parse_request("/rush explain simpler why?", "technical", "detailed")
    assert (simple.focus, simple.complexity, simple.verbosity, simple.text) == (
        "simpler",
        "plain",
        "detailed",
        "why?",
    )
    technical = parse_request(
        "/RUSH explain technical verbosity=short complexity=plain", "plain", "detailed"
    )
    assert (technical.complexity, technical.verbosity) == ("plain", "short")
    example = parse_request("/rush explain example complexity=odd", "plain", "short")
    assert (example.focus, example.complexity, example.text) == (
        "example",
        "plain",
        "complexity=odd",
    )
    assert parse_request("/rush dismiss  covered by ADR-4", "plain", "short").text == (
        "covered by ADR-4"
    )


async def test_an_explanation_rewords_but_never_changes_the_finding(conversation):
    host = conversation.harness.host
    conversation.model.steps = ["not json", EXPLAINED]
    status, reason = await conversation.service.handle(
        conversation.job("/rush explain example verbosity=detailed what happens?")
    )
    assert (status, reason) == ("completed", "Explained (example) for nia-moss")
    comment_id, body = host.replies[-1]
    assert comment_id == 1
    assert "**high security** at `customers.py` line 5 (new version)" in body
    assert "lantern.tenant-lookup@1" in body and "It is still a finding." in body
    assert "&lt;!--" in body and "@​org/team" in body
    assert "**Evidence (unchanged):** `customer-code` lines 5–5" in body
    request = json.loads(conversation.model.calls[0].prompt)
    assert request["focus"] == "example" and request["verbosity"] == "detailed"
    assert request["evidence"]["customer-code"]["cited"] == [5, 5]
    assert conversation.model.calls[0].model_id == "muse-spark-1.3"
    assert conversation.model.closed
    assert await conversation.history() == [("nia-moss", "explain", "what happens?")]
    conversation.model.steps = ["bad", "still bad"]
    status, reason = await conversation.service.handle(
        conversation.job("/rush explain")
    )
    assert (status, reason) == (
        "failed",
        "Explanation failed: The model did not return a valid answer after one repair",
    )
    assert "could not produce an explanation" in host.replies[-1][1]


async def test_withheld_findings_are_not_explained_to_a_public_audience(
    conversation,
):
    conversation.withheld = True
    status, _ = await conversation.service.handle(conversation.job("/rush explain"))
    assert status == "completed"
    assert conversation.harness.host.replies[-1][1] == WITHHELD
    assert conversation.model.calls == []


async def test_reassessment_rejects_a_changed_pinned_model_revision(
    conversation, monkeypatch
):
    records = conversation.harness.worker.records
    get = records.get

    async def pinned(run_id):
        record = await get(run_id)
        settings = record.inputs.settings.model_copy(
            update={
                "models": tuple(
                    model.model_copy(update={"resolved_revision": "rev-a"})
                    for model in record.inputs.settings.models
                )
            }
        )
        return record.model_copy(
            update={"inputs": record.inputs.model_copy(update={"settings": settings})}
        )

    monkeypatch.setattr(records, "get", pinned)
    conversation.model.steps = [
        ModelReply(
            "meta",
            "muse-spark-1.3",
            json.dumps(verdict("withdraw")),
            None,
            {},
            resolved_revision="rev-b",
        )
    ]
    original = conversation.harness.host.comments["review"][1]
    result = await conversation.service.handle(
        conversation.job("/rush challenge Recheck")
    )
    assert result == ("completed", "Reassessment inconclusive; finding unchanged")
    assert conversation.harness.host.comments["review"][1] == original


async def test_decisions_are_recorded_without_becoming_rules(conversation):
    host = conversation.harness.host
    service = conversation.service
    assert await service.handle(conversation.job("/rush accept")) == (
        "completed",
        "Accepted by nia-moss",
    )
    assert "does not create or change a team rule" in host.replies[-1][1]
    assert (await service.handle(conversation.job("/rush dismiss")))[0] == "skipped"
    assert "Please give a reason" in host.replies[-1][1]
    await service.handle(conversation.job("/rush dismiss Covered by a feature flag"))
    assert "not treated as proof that the finding was wrong" in host.replies[-1][1]
    assert await conversation.history() == [
        ("nia-moss", "accept", None),
        ("nia-moss", "dismiss", "Covered by a feature flag"),
    ]
    reader = conversation.job("/rush accept", actor="ivo")
    assert (await service.handle(reader))[1].startswith("ivo used a rush command")
    assert await service.handle(conversation.job("thanks")) == (
        "skipped",
        "The reply has no rush command",
    )
    unknown = await service.handle(conversation.job("/rush accept", comment_id=77))
    assert unknown == ("skipped", "The thread does not belong to a published finding")
    assert host.replies[-1] == (77, "rush could not find the finding for this thread.")
    record = await conversation.harness.worker.records.get("run-1")
    assert (
        locate(record, f"{TENANT}:x") is None and locate(record, f"{TENANT}:2") is None
    )


def verdict(kind, evidence=(("customer-code", 5, 5),), **changes):
    return {
        "verdict": kind,
        "explanation": "The tenant is passed two lines earlier.",
        "evidence": [
            {"source_id": source, "start": start, "end": end}
            for source, start, end in evidence
        ],
        **changes,
    }


@pytest.mark.parametrize(
    ("steps", "outcome", "note"),
    [
        ([verdict("withdraw")], "withdrawn", "<!-- rush:withdrawn -->"),
        ([verdict("withdraw", ())], "inconclusive", None),
        ([verdict("amend", severity="high")], "amended", "- Severity: high"),
        ([verdict("amend", severity="medium")], "amended", "- Severity: medium"),
        ([verdict("keep")], "kept", None),
        ([verdict("keep", (("invented", 1, 1),))], "inconclusive", None),
        ([verdict("keep", (("customer-code", 5, 99),))], "inconclusive", None),
        ([verdict("keep", ())], "inconclusive", None),
        ([verdict("amend")], "inconclusive", None),
        ([verdict("amend", severity="critical")] * 2, "inconclusive", None),
        (["no", "no"], "inconclusive", None),
    ],
)
async def test_challenges_are_reassessed_from_recorded_evidence_only(
    conversation, steps, outcome, note
):
    host = conversation.harness.host
    original = host.comments["review"][1]
    conversation.model.steps = list(steps)
    status, reason = await conversation.service.handle(
        conversation.job("/rush challenge The tenant is checked upstream")
    )
    assert status == "completed"
    history = await conversation.history()
    assert history[0] == ("nia-moss", "challenge", "The tenant is checked upstream")
    if outcome == "inconclusive":
        assert reason == "Reassessment inconclusive; finding unchanged"
        assert history[1][:2] == ("rush", "inconclusive")
        assert host.comments["review"][1] == original
        assert "needs a human decision" in host.replies[-1][1]
        return
    assert reason == f"Challenge reassessed: {outcome}"
    assert history[1][0] == "rush"
    detail = (await conversation.events.history("lantern/demo", 7, f"{TENANT}:1"))[1]
    assert json.loads(detail.detail)["before"]["severity"] == "high"
    assert f": {outcome}.**" in host.replies[-1][1]
    if note is None:
        assert host.comments["review"][1] == original
    else:
        assert (
            host.comments["review"][1].startswith(original)
            and note in (host.comments["review"][1])
        )


async def test_review_thread_replies_become_thread_jobs(initialized):
    events = Events(initialized.database_path)
    pull = {"number": 7, "state": "open", "head": {"sha": "a" * 40}}

    def reply(body="/rush explain simpler", parent=1, user="User"):
        return {
            "action": "created",
            "comment": {
                "body": body,
                "in_reply_to_id": parent,
                "user": {"login": "nia-moss", "type": user},
            },
            "pull_request": pull,
            "repository": {"full_name": "lantern/demo"},
            "installation": {"id": 42},
            "sender": {"login": "nia-moss", "type": "User"},
        }

    opened = await events.send(
        "pull_request",
        {
            "action": "opened",
            "pull_request": pull,
            "repository": {"full_name": "lantern/demo"},
            "installation": {"id": 42},
            "sender": {"login": "nia-moss", "type": "User"},
        },
        "d-0",
    )
    asked = await events.send("pull_request_review_comment", reply(), "d-1")
    assert asked.status_code == 202
    queued = await events.jobs.get(asked.job_id)
    assert (queued.trigger, queued.comment_id, queued.request) == (
        "thread",
        1,
        "/rush explain simpler",
    )
    again = await events.send(
        "pull_request_review_comment", reply("/rush accept"), "d-2"
    )
    assert again.status_code == 202
    pushed = await events.send(
        "pull_request",
        {
            "action": "synchronize",
            "pull_request": pull | {"head": {"sha": "b" * 40}},
            "repository": {"full_name": "lantern/demo"},
            "installation": {"id": 42},
            "sender": {"login": "nia-moss", "type": "User"},
        },
        "d-3",
    )
    assert pushed.status_code == 202
    assert (await events.jobs.get(opened.job_id)).status == "superseded"
    assert (await events.jobs.get(asked.job_id)).status == "queued"
    for payload, message in [
        (reply(parent=None), "not a new reply in a review thread"),
        (reply("Thanks!"), "the reply has no rush command"),
        (reply(user="Bot"), "sent by a bot"),
    ]:
        receipt = await events.send(
            "pull_request_review_comment", payload, f"d-{message}"
        )
        assert receipt.message == f"Ignored: {message}"


async def test_the_worker_routes_thread_jobs(conversation):
    worker = conversation.harness.worker
    thread = conversation.job("/rush accept")
    await worker.jobs.accept(
        "d-t", "sha-t", "pull_request_review_comment", thread, thread.created_at
    )
    plain = ReviewJobService(
        worker.jobs,
        worker.host,
        worker.review,
        worker.records,
        worker.mirrors,
        worker.clock,
    )
    await plain.run_once()
    assert (
        await plain.get(thread.id)
    ).reason == "Finding conversations are not configured"
    for index, (step, status) in enumerate(
        [(None, "completed"), (RuntimeError("boom"), "failed")]
    ):
        queued = thread.model_copy(update={"id": f"job-t{index}"})
        await worker.jobs.accept(
            f"d-{index}", f"s-{index}", "x", queued, queued.created_at
        )
        if step is not None:

            async def broken(job, error=step):
                raise error

            conversation.service.handle = broken
        service = ReviewJobService(
            worker.jobs,
            worker.host,
            worker.review,
            worker.records,
            worker.mirrors,
            worker.clock,
            conversation=conversation.service,
        )
        await service.run_once()
        assert (await service.get(queued.id)).status == status


async def test_the_adapter_replies_in_the_thread():
    github = GitHub()
    github.routes = {
        "/repos/lantern/demo/pulls/7/comments/1/replies": httpx.Response(
            201, json={"id": 44}
        ),
        "/repos/lantern/demo/pulls/7/comments/2/replies": httpx.Response(201, json={}),
    }
    host = adapter(github)
    assert await host.reply(42, "lantern/demo", 7, 1, "Answer") == 44
    with pytest.raises(PublicationUncertainError, match="confirm the reply"):
        await host.reply(42, "lantern/demo", 7, 2, "Answer")


async def test_verdicts_shape_later_commands_and_survive_republishing(conversation):
    harness = conversation.harness
    host = harness.host
    original = host.comments["review"][1]
    conversation.model.steps = [
        verdict("amend", severity="medium", problem="Only staff can reach it"),
        verdict("amend", severity="low"),
        EXPLAINED,
    ]
    for _ in range(2):
        await conversation.service.handle(
            conversation.job("/rush challenge Staff only")
        )
    body = host.comments["review"][1]
    assert body.count("<!-- rush:reassessment -->") == 1 and "- Severity: low" in body
    assert body.startswith(original)
    await conversation.service.handle(conversation.job("/rush explain"))
    assert "**low security**" in host.replies[-1][1]
    await harness.publisher.publish(
        harness.job, await harness.outcome([(TENANT, "RIGHT")])
    )
    assert "- Severity: low" in host.comments["review"][1]
    conversation.model.steps = [verdict("withdraw")]
    await conversation.service.handle(conversation.job("/rush challenge Not real"))
    refused = await conversation.service.handle(conversation.job("/rush accept"))
    assert refused == ("skipped", "The finding was already withdrawn")
    assert host.replies[-1][1] == "This finding was withdrawn; there is nothing to do."


async def test_resolved_threads_and_failed_edits_are_handled(conversation):
    harness = conversation.harness
    host = harness.host
    host.edit_error = CodeHostError("GitHub returned HTTP 422")
    conversation.model.steps = [verdict("amend", severity="low")]
    status, _ = await conversation.service.handle(
        conversation.job("/rush challenge Not real")
    )
    assert status == "completed"
    assert "could not update the original comment" in host.replies[-1][1]
    host.edit_error = None
    host.comments["review"][1] += "\n\n<!-- rush:resolved -->"
    resolved = await conversation.service.handle(conversation.job("/rush accept"))
    assert resolved == ("skipped", "The finding was already resolved")


def test_excerpts_keep_original_line_numbers_around_far_citations(review_result):
    from app.services.finding_conversation import excerpts

    finding = review_result.findings[0]
    ref = finding.evidence[0].model_copy(update={"start": 480, "end": 481})
    far = finding.model_copy(update={"evidence": (ref,), "causal_path": (ref,)})

    from types import SimpleNamespace

    source = SimpleNamespace(
        id=ref.source_id,
        reference="big.py",
        excerpt="\n".join(f"line {n}" for n in range(1, 1001)),
    )
    record = SimpleNamespace(
        inputs=SimpleNamespace(sources=(source,)),
        progress=SimpleNamespace(result=SimpleNamespace(context_sources=())),
    )
    lines = excerpts(record, far)[ref.source_id]["lines"]
    assert lines["480"] == "line 480" and "459" not in lines and "501" in lines
