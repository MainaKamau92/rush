import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app import cli, dependencies
from app.core.errors import ReviewError
from app.db.repositories.learning import SQLiteLearningRepository
from app.schemas.learning import CaseResult, LearningDraft, LearningExamples
from app.schemas.review import ModelConfiguration, VersionPin
from app.services.learning import LearningService
from app.services.policy import PolicyService
from tests.integration.test_finding_conversation import Conversation
from tests.integration.test_local_review import finding, verdicts
from tests.integration.test_pull_request_publication import TENANT, Harness
from tests.unit.test_model_review import Model

ROOT = Path(__file__).resolve().parents[2]
START = datetime(2026, 10, 31, 9, tzinfo=UTC)
DRAFT = {
    "rule_id": "learned.tenant-scope",
    "statement": "Every customer lookup passes the caller's tenant.",
    "rationale": "Tenant-less lookups leaked data in the demo incident.",
    "category": "security",
    "owner": "Mira Vale",
    "scope": {"path": "customers.py"},
    "source": "lantern/demo#7 review thread 1",
    "examples": {"violating": ["unsafe"], "acceptable": ["safe"]},
}
PIN = VersionPin(id="rush.team-standards", version="0.1.0", digest="b" * 64)
MODEL = ModelConfiguration(
    task="review",
    model_id="muse-spark-1.3",
    adapter_version="0.2.0",
    max_output_tokens=2048,
)


def draft(**changes):
    return LearningDraft.model_validate_json(json.dumps(DRAFT | changes))


class Clock:
    def __init__(self):
        self.ticks = 0

    def __call__(self):
        self.ticks += 1
        return START + timedelta(seconds=self.ticks)


def service(database, approvers=("Ivo Reed",)):
    numbers = iter(range(1, 100))
    return LearningService(
        SQLiteLearningRepository(database),
        frozenset(approvers),
        Clock(),
        lambda: f"L{next(numbers)}",
    )


def evaluator(*statuses):
    async def run(draft, rule):
        cases = tuple(
            CaseResult(
                case=case,
                expected=expected,
                status=status,
                rule_findings=int(expected == "violating" and status == "passed"),
                run_status="completed" if status != "incomplete" else "partial",
            )
            for (case, expected), status in zip(
                [("unsafe", "violating"), ("safe", "acceptable")], statuses, strict=True
            )
        )
        return PIN, MODEL, cases

    return run


async def test_only_an_evaluated_exact_version_can_become_a_rule(initialized):
    learning = service(initialized.database_path)
    with pytest.raises(ValidationError):
        draft(permissions=["publish"])
    first = await learning.propose(draft(examples={}), "nia-moss")
    assert (first.id, first.revision, first.status) == ("L1", 1, "proposed")
    with pytest.raises(ReviewError, match="already uses rule ID"):
        await learning.propose(draft(), "nia-moss")
    with pytest.raises(ReviewError, match="violating and one acceptable"):
        await learning.evaluate("L1", evaluator("passed", "passed"))
    revised = await learning.revise("L1", draft())
    assert (revised.revision, revised.evaluation) == (2, None)
    assert await learning.revise("L1", draft()) == revised
    failed = await learning.evaluate("L1", evaluator("passed", "failed"))
    assert (failed.status, failed.evaluation.passed) == ("proposed", False)
    with pytest.raises(ReviewError, match="passed evaluation"):
        await learning.approve("L1", failed.content_sha256, "Ivo Reed", True)
    incomplete = await learning.evaluate("L1", evaluator("passed", "incomplete"))
    assert incomplete.evaluation.passed is False
    passed = await learning.evaluate("L1", evaluator("passed", "passed"))
    assert passed.status == "evaluated"
    assert passed.evaluation.rule.version == "2"
    assert (passed.evaluation.skill, passed.evaluation.model) == (PIN, MODEL)
    digest = passed.content_sha256
    for approver, authorized in (("Nia Moss", True), ("Ivo Reed", False)):
        with pytest.raises(ReviewError, match="currently authorized approver"):
            await learning.approve("L1", digest, approver, authorized)
    for stale in (first.content_sha256, digest[:8]):
        with pytest.raises(ReviewError, match="not the current version"):
            await learning.approve("L1", stale, "Ivo Reed", True)
    assert await learning.active_rules() == ()
    approved, created = await learning.approve("L1", digest[:12], "Ivo Reed", True)
    again, repeated = await learning.approve("L1", digest, "Ivo Reed", True)
    assert (created, repeated, again.approved_by) == (True, False, "Ivo Reed")
    (rule,) = await learning.active_rules()
    assert (rule.id, rule.version, rule.status, rule.approved_by) == (
        "learned.tenant-scope",
        "2",
        "approved",
        "Ivo Reed",
    )
    assert rule.source == "learning:L1@2" and rule.overridable is False
    with pytest.raises(ReviewError, match="cannot change"):
        await learning.revise("L1", draft(statement="Changed"))
    with pytest.raises(ReviewError, match="already approved"):
        await learning.evaluate("L1", evaluator("passed", "passed"))
    with pytest.raises(ReviewError, match="not found"):
        await learning.show("L9")
    assert json.loads(await learning.bundle())[0]["id"] == "learned.tenant-scope"
    policy = PolicyService().resolve(
        repository="lantern/demo",
        paths=("customers.py",),
        sources=(),
        review_time=START + timedelta(hours=1),
        rules=json.dumps([rule.model_dump(mode="json")]),
        exceptions=None,
        approvers=("Ivo Reed",),
        allow_cached_policy=False,
    )
    assert [item.id for item in policy.rules] == ["learned.tenant-scope"]
    elsewhere = PolicyService().resolve(
        repository="lantern/demo",
        paths=("billing.py",),
        sources=(),
        review_time=START + timedelta(hours=1),
        rules=json.dumps([rule.model_dump(mode="json")]),
        exceptions=None,
        approvers=("Ivo Reed",),
        allow_cached_policy=False,
    )
    assert elsewhere.rules == ()


async def test_the_evaluator_runs_the_proposal_on_every_affected_example(
    initialized, monkeypatch
):
    from tests.e2e.test_pr_journey import Steps

    settings = initialized.model_copy(update={"review_skills_dir": ROOT / "skills"})
    miss_proposal = False

    def respond(request):
        data = json.loads(request.prompt)
        if "candidates" in data:
            return verdicts("keep")(request)
        rules = data["frozen_rules"]
        if any(rule["id"] == "lantern.global-preview" for rule in rules):
            return {
                "kind": "done",
                "limitations": [
                    {
                        "code": "policy_conflict",
                        "reason": "lantern.tenant-lookup conflicts with "
                        "lantern.global-preview",
                    }
                ],
            }
        learned = next(
            (rule for rule in rules if rule["id"].startswith("learned.")), None
        )
        if miss_proposal and learned:
            return {"kind": "done"}
        changed = any(
            line["kind"] == "added"
            and (
                "find_customer(connection, external_id)" in line["text"]
                or "lookup_for_export(connection, external_id)" in line["text"]
            )
            for file in data["change"]["files"]
            for hunk in file["hunks"]
            for line in hunk["lines"]
        )
        if not changed:
            return {"kind": "done"}
        step = finding(request)
        if learned:
            step["findings"][0]["rule_ref"] = {
                "id": learned["id"],
                "version": learned["version"],
            }
        return step

    def model(_settings):
        provider = Model()
        provider.capabilities = provider.capabilities.model_copy(
            update={"adapter_version": "0.2.0"}
        )
        provider.steps = Steps(respond)
        return provider

    monkeypatch.setattr(dependencies, "_build_model_provider", model)
    learning = service(initialized.database_path)
    examples = {
        "violating": [
            "unsafe",
            "related",
            "expired-exception",
            "valid-exception",
            "conflicting-rules",
        ],
        "acceptable": ["safe"],
    }
    proposal_draft = draft(examples=examples)
    await learning.propose(proposal_draft, "nia-moss")
    evaluated = await learning.evaluate(
        "L1", lambda d, r: dependencies.evaluate_learning(settings, d, r)
    )
    result = evaluated.evaluation
    assert result.passed and result.skill.id == "rush.team-standards"
    proposed = [case for case in result.cases if case.purpose == "proposal"]
    regressions = [case for case in result.cases if case.purpose == "skill_regression"]
    assert (
        {case.case for case in proposed}
        == {case.case for case in regressions}
        == set(examples["violating"] + examples["acceptable"])
    )
    assert all(case.status == "passed" for case in result.cases)
    assert (
        next(
            case for case in regressions if case.case == "conflicting-rules"
        ).run_status
        == "partial"
    )
    assert (
        next(case for case in proposed if case.case == "valid-exception").rule_findings
        == 1
    )
    assert (
        next(
            case for case in regressions if case.case == "valid-exception"
        ).rule_findings
        == 0
    )
    miss_proposal = True
    await learning.revise(
        "L1", proposal_draft.model_copy(update={"rationale": "Revised"})
    )
    missed = await learning.evaluate(
        "L1", lambda d, r: dependencies.evaluate_learning(settings, d, r)
    )
    assert not missed.evaluation.passed
    assert all(
        case.status == "failed"
        for case in missed.evaluation.cases
        if case.purpose == "proposal" and case.expected == "violating"
    )
    with pytest.raises(ReviewError, match="not a known fixture case"):
        await dependencies._example("no-such-case")


async def test_learning_requires_explicit_proposal_labels_for_the_whole_skill(
    initialized,
):
    settings = initialized.model_copy(update={"review_skills_dir": ROOT / "skills"})
    learning = service(initialized.database_path)
    await learning.propose(draft(), "nia-moss")
    with pytest.raises(ReviewError, match="Label every affected skill example"):
        await learning.evaluate(
            "L1", lambda d, r: dependencies.evaluate_learning(settings, d, r)
        )
    assert (await learning.show("L1")).status == "proposed"


async def test_legacy_cached_evaluation_requires_reevaluation_before_approval(
    initialized,
):
    learning = service(initialized.database_path)
    proposal = await learning.propose(draft(), "nia-moss")
    current = await learning.evaluate("L1", evaluator("passed", "passed"))
    legacy = current.model_copy(
        update={
            "evaluation": current.evaluation.model_copy(
                update={"evaluator_version": None}
            )
        }
    )
    await SQLiteLearningRepository(initialized.database_path).save(legacy, current)
    with pytest.raises(ReviewError, match="passed evaluation"):
        await learning.approve("L1", proposal.content_sha256, "Ivo Reed", True)
    assert await learning.active_rules() == ()
    await learning.evaluate("L1", evaluator("passed", "passed"))
    approved, created = await learning.approve(
        "L1", proposal.content_sha256, "Ivo Reed", True
    )
    assert created and approved.evaluation.evaluator_version == 2


async def test_learning_rejects_contradictory_labels_before_model_access(initialized):
    settings = initialized.model_copy(update={"review_skills_dir": ROOT / "skills"})
    learning = service(initialized.database_path)
    await learning.propose(
        draft(examples={"violating": ["unsafe"], "acceptable": ["unsafe"]}), "nia-moss"
    )
    with pytest.raises(ReviewError, match="both violating and acceptable"):
        await learning.evaluate(
            "L1", lambda d, r: dependencies.evaluate_learning(settings, d, r)
        )


def test_fixture_context_refuses_unknown_cases_and_escaping_paths(tmp_path):
    fixture = dependencies.build_example_context()
    with pytest.raises(ReviewError, match="not a known fixture case"):
        fixture.request("../secret", "trial")
    (tmp_path / "cases.json").write_text(
        json.dumps([{"id": "escape", "team": "../secret"}])
    )
    isolated = dependencies.build_example_context(tmp_path)
    with pytest.raises(ReviewError, match="inside its corpus"):
        isolated.request("escape", "trial")


async def test_approved_learning_joins_github_rules_as_an_ordinary_rule(
    initialized, tmp_path
):
    learning = service(initialized.database_path)
    proposal = await learning.propose(draft(), "nia-moss")
    await learning.evaluate("L1", evaluator("passed", "passed"))
    rules = tmp_path / "rules.json"
    rules.write_text(
        (ROOT / "tests/fixtures/customer_lookup/context/rules.json").read_text()
    )
    settings = initialized.model_copy(
        update={
            "review_rules_file": rules,
            "learning_approvers": frozenset({"Ivo Reed"}),
        }
    )
    settings = settings.model_copy(update={"review_approvers": frozenset({"Ivo Reed"})})
    text, approvers = await dependencies._rules_with_learning(settings)
    assert json.loads(text)[0]["id"] == "lantern.tenant-lookup"
    assert approvers == ("Ivo Reed",)
    approved, _ = await dependencies.build_learning(settings).approve(
        "L1", proposal.content_sha256, "Ivo Reed", True
    )
    assert approved.approval_channel == "cli"
    text, approvers = await dependencies._rules_with_learning(settings)
    merged = json.loads(text)
    assert [item["id"] for item in merged] == [
        "lantern.tenant-lookup",
        "learned.tenant-scope",
    ]
    assert merged[1]["approved_by"] == "team learning approval by Ivo Reed"
    assert approvers == ("Ivo Reed", "team learning approval by Ivo Reed")
    bare = settings.model_copy(update={"review_rules_file": None})
    assert len(json.loads((await dependencies._rules_with_learning(bare))[0])) == 1
    removed = settings.model_copy(update={"learning_approvers": frozenset()})
    assert len(json.loads((await dependencies._rules_with_learning(removed))[0])) == 1
    clash = json.loads(rules.read_text())
    clash.append(clash[0] | {"id": "learned.tenant-scope"})
    rules.write_text(json.dumps(clash))
    text, _ = await dependencies._rules_with_learning(settings)
    assert [item["id"] for item in json.loads(text)].count("learned.tenant-scope") == 1
    rules.write_text("{}")
    with pytest.raises(ReviewError, match="approved policy format"):
        await dependencies._rules_with_learning(settings)


async def test_learning_is_requested_and_approved_in_review_threads(
    initialized, review_inputs, review_result
):
    harness = Harness(initialized, review_inputs, review_result)
    await harness.publisher.publish(
        harness.job, await harness.outcome([(TENANT, "RIGHT")])
    )
    harness.host.permissions |= {"nia-moss": "write", "ivo-reed": "admin"}
    conversation = Conversation(harness)
    learning = service(initialized.database_path, approvers=("ivo-reed",))
    conversation.service._learning = learning
    handle = conversation.service.handle
    assert (await handle(conversation.job("/rush learn Always scope lookups")))[0] == (
        "skipped"
    )
    status, reason = await handle(
        conversation.job("/rush learn Always pass the tenant because it leaked")
    )
    assert (status, reason) == ("completed", "Learning proposal L1 created")
    reply = harness.host.replies[-1][1]
    assert "inactive learning proposal **L1**" in reply and "changes nothing" in reply
    proposal = await learning.show("L1")
    assert proposal.draft.scope.path == "customers.py"
    assert proposal.draft.scope.repository == "lantern/demo"
    assert proposal.draft.category == "security"
    assert (
        "nia-moss",
        "learn",
        "Always pass the tenant",
    ) in await conversation.history()
    duplicate = await handle(conversation.job("/rush learn Again because twice"))
    assert duplicate[0] == "skipped" and "already uses rule ID" in duplicate[1]
    digest = proposal.content_sha256
    early = await handle(
        conversation.job(f"/rush approve-learning L1 {digest}", actor="ivo-reed")
    )
    assert early[0] == "skipped" and "passed evaluation" in early[1]
    revised = await learning.revise(
        "L1",
        proposal.draft.model_copy(
            update={
                "examples": LearningExamples(
                    violating=("unsafe",), acceptable=("safe",)
                )
            }
        ),
    )
    await learning.evaluate("L1", evaluator("passed", "passed"))
    old = await handle(
        conversation.job(f"/rush approve-learning L1 {digest}", actor="ivo-reed")
    )
    assert "not the current version" in old[1]
    outsider = await handle(
        conversation.job(f"/rush approve-learning L1 {revised.content_sha256}")
    )
    assert "not a designated" in outsider[1]
    approved = await handle(
        conversation.job(
            f"/rush approve-learning L1 {revised.content_sha256}", actor="ivo-reed"
        )
    )
    assert approved == ("completed", "Learning proposal L1 approved")
    assert "applies to future reviews" in harness.host.replies[-1][1]
    again = await handle(
        conversation.job(
            f"/rush approve-learning L1 {revised.content_sha256}", actor="ivo-reed"
        )
    )
    assert again == ("completed", "Learning proposal L1 was already approved")
    assert len(await learning.active_rules()) == 1
    assert (await handle(conversation.job("/rush approve-learning L1")))[0] == "skipped"
    record = await harness.worker.records.get("run-1")
    assert record.inputs.rules == harness.inputs.rules
    elsewhere = await learning.propose(
        draft(rule_id="learned.other-repo", scope={"path": "*.py"}), "nia-moss"
    )
    await learning.evaluate(elsewhere.id, evaluator("passed", "passed"))
    refused = await handle(
        conversation.job(
            f"/rush approve-learning {elsewhere.id} {elsewhere.content_sha256}",
            actor="ivo-reed",
        )
    )
    assert (
        refused[0] == "skipped" and "locally with rush learning-approve" in refused[1]
    )
    assert (await learning.show(elsewhere.id)).status == "evaluated"


def invoke(monkeypatch, capsys, *args):
    monkeypatch.setattr(sys, "argv", ["rush", *args])
    code = cli.main()
    output = capsys.readouterr()
    return code, (json.loads(output.out) if output.out else output.err)


def test_the_cli_proposes_inspects_evaluates_approves_and_exports(
    initialized, monkeypatch, capsys, tmp_path
):
    monkeypatch.setenv("RUSH_STATE_DIR", str(initialized.state_dir))
    monkeypatch.setenv("RUSH_LEARNING_APPROVERS", "Ivo Reed")
    monkeypatch.setattr(
        cli,
        "evaluate_learning",
        lambda settings, d, r: evaluator("passed", "passed")(d, r),
    )
    proposal = tmp_path / "proposal.json"
    proposal.write_text(json.dumps(DRAFT))
    code, created = invoke(
        monkeypatch, capsys, "learning-propose", str(proposal), "--proposer", "nia-moss"
    )
    assert code == 0
    proposal_id = created["learning"]["id"]
    proposal.write_text(json.dumps(DRAFT | {"rationale": "Clearer"}))
    _, revised = invoke(
        monkeypatch, capsys, "learning-revise", proposal_id, str(proposal)
    )
    assert revised["learning"]["revision"] == 2
    _, evaluated = invoke(monkeypatch, capsys, "learning-evaluate", proposal_id)
    digest = evaluated["learning"]["content_sha256"]
    _, shown = invoke(monkeypatch, capsys, "learning-show", proposal_id)
    assert shown["learning"]["evaluation"]["passed"] is True
    _, approved = invoke(
        monkeypatch,
        capsys,
        "learning-approve",
        proposal_id,
        "--sha",
        digest,
        "--approver",
        "Ivo Reed",
    )
    assert approved["learning"]["approved"] is True
    _, listed = invoke(monkeypatch, capsys, "learning-list")
    assert [item["status"] for item in listed["learning"]] == ["approved"]
    bundle = tmp_path / "learned.json"
    _, exported = invoke(monkeypatch, capsys, "learning-export", str(bundle))
    assert exported["learning"]["rules"] == 1
    assert json.loads(bundle.read_text())[0]["version"] == "2"
    proposal.write_text(json.dumps(DRAFT | {"permissions": ["publish"]}))
    code, error = invoke(
        monkeypatch, capsys, "learning-propose", str(proposal), "--proposer", "x"
    )
    assert code == 1 and "no other fields" in error


async def test_learning_commands_are_accepted_from_review_threads(initialized):
    from tests.integration.test_github_events import Events

    events = Events(initialized.database_path)

    def reply(body):
        return {
            "action": "created",
            "comment": {
                "body": body,
                "in_reply_to_id": 1,
                "user": {"login": "nia-moss", "type": "User"},
            },
            "pull_request": {"number": 7},
            "repository": {"full_name": "lantern/demo"},
            "installation": {"id": 42},
            "sender": {"login": "nia-moss", "type": "User"},
        }

    for index, (body, status) in enumerate(
        [
            ("/rush learn Scope it because it leaked", 202),
            ("/rush approve-learning L1 0123456789ab", 202),
            ("/rush approve-learningX L1", 200),
        ]
    ):
        receipt = await events.send(
            "pull_request_review_comment", reply(body), f"d{index}"
        )
        assert receipt.status_code == status


async def test_concurrent_changes_never_undo_a_revision_or_approval(initialized):
    learning = service(initialized.database_path)
    with pytest.raises(ValidationError):
        draft(rule_id="lantern.tenant-lookup")
    await learning.propose(draft(), "nia-moss")
    other = service(initialized.database_path)

    async def racing(draft_, rule):
        await other.revise("L1", draft(rationale="Changed during evaluation"))
        return await evaluator("passed", "passed")(draft_, rule)

    with pytest.raises(ReviewError, match="changed meanwhile"):
        await learning.evaluate("L1", racing)
    current = await learning.show("L1")
    assert (current.revision, current.status) == (2, "proposed")
    duplicate = service(initialized.database_path)
    with pytest.raises(ReviewError, match="already uses"):
        await duplicate._repository.save(
            current.model_copy(update={"id": "L9", "revision": 1})
        )
