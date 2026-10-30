import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app import dependencies
from app.core.errors import ChangeError, ReviewError, SkillError, SourceAccessError
from app.db.repositories.reviews import SQLiteReviewRepository
from app.models.source_access import ToolOutput
from app.schemas.local_review import ContextFile, LocalReviewRequest
from app.schemas.review import ReviewLimits
from app.services.context_retrieval import ContextRetrievalService
from app.services.disclosure import WITHHELD, DisclosureService
from app.services.finding_validation import FindingValidationService
from app.services.local_review import LocalReviewService
from app.services.model_context import ModelContext
from app.services.model_review import ModelReviewService
from app.services.review_records import ReviewRecordService
from app.services.review_report import ReviewReportService
from app.services.review_skills import SkillCatalog
from app.services.skill_evaluation import SkillEvaluationService
from app.services.source_access import SourceAccessService
from tests.integration.test_code_change_reader import run
from tests.unit.test_context_retrieval import Source
from tests.unit.test_model_review import Model

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "tests/fixtures/customer_lookup"


def now():
    return datetime(2026, 1, 15, tzinfo=UTC)


def finding(request, line=5, rule=True, cite_hunk=True):
    data = json.loads(request.prompt)
    hunk = data["change"]["files"][0]["hunks"][0]
    position = next(
        index
        for index, item in enumerate(hunk["lines"], start=1)
        if item["new_line"] == line
    )
    hunk = hunk["id"]
    evidence = [{"source_id": f"diff:{hunk}", "start": position, "end": position}]
    if not cite_hunk:
        evidence = [{"source_id": "policy", "start": 1, "end": 1}]
    draft = {
        "category": "security",
        "severity": "high",
        "anchor": {
            "path": "customers.py",
            "side": "RIGHT",
            "line": line,
            "hunk_id": hunk,
        },
        "problem": "The lookup no longer passes the tenant.",
        "consequence": "Another tenant's customer can be returned.",
        "trigger_scenario": "demo-blue asks for shared-customer and gets demo-amber.",
        "causal_path": evidence,
        "evidence": evidence,
        "remediation": "Pass tenant_id to find_customer.",
    }
    if rule:
        draft["rule_ref"] = {"id": "lantern.tenant-lookup", "version": "1"}
    return {"kind": "candidates", "findings": [draft]}


def verdicts(*kinds):
    return lambda request: {
        "kind": "critique",
        "verdicts": [
            {"candidate": index, "verdict": kind, "reason": "Checked."}
            | (
                {"question": "Is the export path reachable?"}
                if kind == "question"
                else {}
            )
            for index, kind in enumerate(kinds)
        ],
    }


class Harness:
    def __init__(self, settings, catalog, retrieval=None):
        self.provider = Model()
        self.provider.capabilities = self.provider.capabilities.model_copy(
            update={"adapter_version": "0.2.0"}
        )
        self.records = ReviewRecordService(
            SQLiteReviewRepository(settings.database_path), now
        )
        self.catalog = catalog
        self.service = LocalReviewService(
            catalog,
            lambda investigation: ModelReviewService(
                self.provider,
                investigation,
                self.records,
                lambda inputs, disclosure: ModelContext(
                    inputs, investigation, disclosure, now
                ),
            ),
            FindingValidationService(self.records),
            self.records,
            now,
            retrieval,
        )

    async def review(self, case="unsafe", skills=None, limits=None, **changes):
        example = Path(await run("sh", "scripts/reset-example.sh", case))
        request = LocalReviewRequest(
            run_id=f"run-{case}",
            repository="lantern-customer-service",
            head="fixture-head",
            target="fixture-base",
            disclosure="public",
            context=(
                ContextFile(
                    kind="ticket",
                    reference="ticket.md",
                    text=(CORPUS / "context/ticket.md").read_text(),
                ),
                ContextFile(
                    kind="guideline",
                    reference="guideline.md",
                    text=(CORPUS / "context/guideline.md").read_text(),
                ),
            ),
            rules=(CORPUS / "context/rules.json").read_text(),
        ).model_copy(update=changes)
        return await self.service.review(
            dependencies.build_investigation(example, limits),
            request,
            self.catalog.skills if skills is None else skills,
        )


@pytest.fixture
async def harness(initialized):
    catalog = await dependencies.build_skill_catalog(ROOT / "skills").load()
    return Harness(initialized, catalog)


async def test_unsafe_example_produces_one_validated_tenant_finding(harness):
    harness.provider.steps = [
        {"kind": "done"},
        finding,
        {"kind": "done"},
        verdicts("keep"),
    ]
    outcome = await harness.service.finish(await harness.review())
    record = outcome.record
    assert record.status == "completed"
    assert [event.status for event in record.progress.events] == [
        "queued",
        "preparing",
        "reviewing",
        "validating",
        "publishing",
        "completed",
    ]
    (result,) = record.progress.result.findings
    assert (result.rule_ref.id, result.anchor.line, result.skill.id) == (
        "lantern.tenant-lookup",
        5,
        "rush.team-standards",
    )
    assert result.verification == "code_inspected" and result.id == "run-unsafe-1"
    assert record.progress.result.candidate_findings == ()
    assert record.inputs.policy_sha == record.inputs.merge_base_sha
    assert [source.id for source in record.inputs.sources] == [
        "ticket-1",
        "guideline-1",
        "policy",
    ]
    assert [pin.id for pin in record.inputs.rules] == ["lantern.tenant-lookup"]
    assert [model.task for model in record.inputs.settings.models] == [
        "review",
        "critique",
    ]
    assert (await harness.records.get("run-unsafe")) == record
    assert all(call.model_id == "muse-spark-1.3" for call in harness.provider.calls)
    assert "Apply only" not in harness.provider.calls[0].instructions

    report = ReviewReportService()
    data = report.data(outcome)
    assert data["status"] == "completed" and data["complete"]
    assert data["application_tests_executed"] is False
    assert data["reviewed_files"] == ["customers.py"]
    assert data["findings"][0]["fingerprint"] == result.fingerprint
    summary = report.summary(outcome)
    assert summary.startswith("# Review complete")
    assert "customers.py line 5 (new version)" in summary
    assert "No application code or tests were run" in summary
    assert "does not prove the change is correct" in summary


async def test_unchanged_lines_unsupported_citations_and_repeats_are_withdrawn(
    harness,
):
    harness.provider.steps = [
        lambda request: finding(request, rule=False),
        lambda request: {
            "kind": "candidates",
            "findings": [
                *finding(request)["findings"],
                *finding(request, line=4)["findings"],
                *finding(request, cite_hunk=False)["findings"],
            ],
        },
        {"kind": "done"},
        verdicts("keep", "keep", "keep", "keep"),
    ]
    outcome = await harness.review()
    assert outcome.record.status == "publishing"
    (kept,) = outcome.record.progress.result.findings
    assert kept.rule_ref is not None
    reasons = sorted(item.reason for item in outcome.withdrawn)
    assert reasons == [
        "Anchored line is unchanged context, so this change does not add it",
        "Evidence does not quote the changed line the finding is anchored to",
        "Repeats finding run-unsafe-1 at the same changed line",
    ]
    assert "Withdrawn proposals" in ReviewReportService().summary(outcome)


async def test_critique_withdrawals_and_questions_never_become_findings(harness):
    harness.provider.steps = [
        finding,
        lambda request: finding(request, rule=False),
        {"kind": "done"},
        verdicts("withdraw", "question"),
    ]
    outcome = await harness.service.finish(await harness.review())
    result = outcome.record.progress.result
    assert outcome.record.status == "completed" and result.findings == ()
    (question,) = result.limitations
    assert question.code == "unresolved_question" and not question.affects_completeness
    assert "Is the export path reachable?" in question.reason
    assert [item.by for item in outcome.withdrawn] == ["critique"]
    summary = ReviewReportService().summary(outcome)
    assert summary.startswith("# Review complete with open questions")
    assert "No supported findings." in summary
    assert "(does not affect completeness)" in summary


async def test_rule_outside_a_skills_approved_rules_is_withdrawn(harness):
    skill = harness.catalog.get("rush.team-standards")
    narrowed = skill.model_copy(
        update={
            "manifest": skill.manifest.model_copy(update={"rule_ids": ("other.rule",)})
        }
    )
    harness.provider.steps = [finding, verdicts("keep")]
    outcome = await harness.review(skills=(narrowed,))
    assert outcome.record.progress.result.findings == ()
    assert (
        outcome.withdrawn[0].reason
        == "Cited rule is outside the skill's approved rules"
    )
    assert "Apply only these approved rule IDs: other.rule" in (
        harness.provider.calls[0].instructions
    )


async def test_failed_model_stage_is_reported_without_validation(harness):
    harness.provider.steps = ["invalid", "still invalid"]
    skill = harness.catalog.get("rush.correctness")
    outcome = await harness.service.finish(await harness.review(skills=(skill,)))
    assert outcome.record.status == "failed"
    data = ReviewReportService().data(outcome)
    assert (data["status"], data["complete"]) == ("failed", False)
    assert ReviewReportService().summary(outcome).startswith("# Review failed")


async def test_unmatched_skills_skip_the_review_without_a_model_call(harness):
    skill = harness.catalog.get("rush.correctness")
    docs_only = skill.model_copy(
        update={
            "manifest": skill.manifest.model_copy(
                update={
                    "scope": skill.manifest.scope.model_copy(
                        update={"paths": ("docs/**",)}
                    )
                }
            )
        }
    )
    outcome = await harness.review(skills=(docs_only,))
    assert outcome.record.status == "skipped"
    assert outcome.record.progress.events[-1].reason == (
        "No approved skill matches the changed files"
    )
    assert harness.provider.calls == []
    assert ReviewReportService().summary(outcome).startswith("# Review skipped")


async def test_invalid_setup_fails_before_any_record_or_model_call(harness):
    with pytest.raises(SkillError, match="No active review skill"):
        await harness.review(skills=())
    skill = harness.catalog.get("rush.correctness")
    other = skill.model_copy(
        update={
            "pin": skill.pin.model_copy(update={"id": "rush.other"}),
            "model": skill.model.model_copy(update={"model_id": "muse-wonder-1.0"}),
        }
    )
    with pytest.raises(SkillError, match="different model profiles"):
        await harness.review(skills=(skill, other))
    for rules, message in (
        ("not json", "JSON list"),
        ('[{"id": "a"}]', "JSON list"),
        ('[{"id": "a", "version": "1"}, {"id": "a", "version": "2"}]', "once"),
    ):
        with pytest.raises(ReviewError, match=message):
            await harness.review(rules=rules)
    with pytest.raises(ChangeError, match="not available"):
        await harness.review(head="missing-version")
    assert harness.provider.calls == []


async def test_private_code_needs_team_disclosure_approval(harness):
    outcome = await harness.review(disclosure="private")
    assert outcome.record.status == "failed"
    assert "disclosure is not approved" in outcome.record.progress.events[-1].reason
    assert harness.provider.calls == []


async def test_evaluation_matches_findings_one_to_one_and_checks_boundaries(harness):
    team = harness.catalog.get("rush.team-standards")
    violating, _, acceptable = team.examples.examples
    harness.provider.steps = [finding, verdicts("keep")]
    outcome = await harness.service.finish(await harness.review(skills=(team,)))
    compare = SkillEvaluationService().compare
    assert compare(violating, outcome).passed
    failed = compare(acceptable, outcome)
    assert not failed.passed and len(failed.unexpected) == 1
    assert failed.model_calls == 2 and failed.input_tokens == 20

    billing = acceptable.model_copy(
        update={"expected_limitations": ("missing_ticket",)}
    )
    harness.provider.steps = [{"kind": "done"}]
    clean = await harness.service.finish(
        await harness.review(skills=(team,), run_id="clean")
    )
    assert compare(acceptable, clean).passed
    result = compare(billing, clean)
    assert result.missing_limitations == ("missing_ticket",) and not result.passed


async def test_one_skills_missing_context_keeps_other_skills_findings(harness):
    harness.provider.steps = [
        {"kind": "done"},
        finding,
        {
            "kind": "done",
            "limitations": [{"code": "missing_ticket", "reason": "No ticket."}],
        },
        verdicts("keep"),
    ]
    outcome = await harness.service.finish(await harness.review())
    result = outcome.record.progress.result
    assert outcome.record.status == "partial"
    assert [item.rule_ref.id for item in result.findings] == ["lantern.tenant-lookup"]
    assert [item.code for item in result.limitations] == ["missing_ticket"]
    assert ReviewReportService().summary(outcome).startswith("# Review incomplete")


async def test_a_change_with_every_file_omitted_is_partial_not_skipped(harness):
    outcome = await harness.review(limits=ReviewLimits(changed_lines=1))
    record = outcome.record
    assert record.status == "partial" and harness.provider.calls == []
    assert {item.code for item in record.progress.result.limitations} >= {
        "scope_excluded"
    }
    assert ReviewReportService().data(outcome)["omitted_files"]


def live(disclosure, text="Fictional linked ticket: trim names."):
    source = Source({"live-1": ToolOutput(text, False)})
    return source, lambda: ContextRetrievalService(
        SourceAccessService(
            source, {"ticket": frozenset({"live-1"}), "guideline": frozenset()}
        ),
        disclosure,
        now,
    )


def allowing_private(catalog):
    return SkillCatalog(
        catalog.approved.model_copy(
            update={"allowed_disclosures": ("public", "private")}
        ),
        catalog.skills,
    )


async def test_a_linked_ticket_is_read_live_and_supplied_to_the_model(
    initialized, harness
):
    source, factory = live("public")
    live_harness = Harness(initialized, harness.catalog, factory)
    live_harness.provider.steps = [{"kind": "done"}] * 3
    outcome = await live_harness.review(
        context=(), pull_request_text="Closes task:live-1 and task:other"
    )
    record = outcome.record
    assert record.status == "partial"
    live_ticket = next(
        item for item in record.inputs.sources if item.id == "ticket-live-1"
    )
    assert live_ticket.excerpt == "Fictional linked ticket: trim names."
    catalog = json.loads(live_harness.provider.calls[0].prompt)["evidence_catalog"]
    assert any(item["source_id"] == "ticket-live-1" for item in catalog)
    assert [call.arguments["task_id"] for call in source.calls] == ["live-1"]
    assert [item.code for item in record.progress.result.limitations] == [
        "access_denied"
    ]


async def test_private_live_sources_are_not_fetched_or_sent_or_reported(
    initialized, harness, tmp_path
):
    private_text = "Private roadmap detail"
    source, factory = live("private", private_text)
    live_harness = Harness(initialized, harness.catalog, factory)
    live_harness.provider.steps = [{"kind": "done"}] * 3
    outcome = await live_harness.service.finish(
        await live_harness.review(ticket_references=("live-1",))
    )
    record = outcome.record
    assert source.calls == [] and source.listings == 0 and source.closed
    assert all(item.id != "ticket-live-1" for item in record.inputs.sources)
    assert all(private_text not in call.prompt for call in live_harness.provider.calls)
    (denied,) = record.progress.result.limitations
    assert (denied.code, denied.affects_completeness) == ("access_denied", True)
    assert "none were read" in denied.reason
    assert record.status == "partial"
    report = ReviewReportService()
    assert private_text not in report.summary(outcome)
    assert private_text not in json.dumps(report.data(outcome))


async def test_a_missing_credential_becomes_a_denied_source_not_a_crash(
    initialized, harness
):
    def unavailable():
        raise SourceAccessError("ClickUp authorization is required")

    live_harness = Harness(initialized, harness.catalog, unavailable)
    live_harness.provider.steps = [{"kind": "done"}] * 3
    outcome = await live_harness.review(context=(), ticket_references=("live-1",))
    (denied,) = outcome.record.progress.result.limitations
    assert denied.code == "access_denied" and "authorization" in denied.reason


async def test_bypass_ticket_text_cannot_change_reviewer_controls(initialized, harness):
    bypass = (CORPUS / "context/bypass-ticket.md").read_text()
    runs = []
    for text in ("Fictional linked ticket: trim names.", bypass):
        _, factory = live("public", text)
        live_harness = Harness(initialized, harness.catalog, factory)
        live_harness.provider.steps = [{"kind": "done"}] * 3
        outcome = await live_harness.review(
            context=(), ticket_references=("live-1",), run_id=f"run-{len(runs)}"
        )
        runs.append((outcome.record.inputs, live_harness.provider.calls))
    (clean, clean_calls), (hostile, hostile_calls) = runs
    assert hostile.settings == clean.settings and hostile.rules == clean.rules
    assert hostile.skills == clean.skills
    assert [call.instructions for call in hostile_calls] == [
        call.instructions for call in clean_calls
    ]
    for clean_call, hostile_call in zip(clean_calls, hostile_calls, strict=True):
        clean_payload = json.loads(clean_call.prompt)
        hostile_payload = json.loads(hostile_call.prompt)
        assert (
            hostile_payload["effective_permissions"]
            == clean_payload["effective_permissions"]
        )
        assert hostile_payload["frozen_rules"] == clean_payload["frozen_rules"]
    supplied = json.loads(hostile_calls[0].prompt)["evidence_catalog"]
    assert any(item.get("excerpt") == bypass for item in supplied)


async def test_public_audience_withholds_text_after_private_sources_reach_the_model(
    initialized, harness
):
    private_text = "Private roadmap detail"
    _, factory = live("private", private_text)
    catalog = allowing_private(harness.catalog)
    live_harness = Harness(initialized, catalog, factory)
    live_harness.provider.steps = [
        {"kind": "done"},
        finding,
        {"kind": "done"},
        verdicts("keep"),
    ]
    outcome = await live_harness.service.finish(
        await live_harness.review(ticket_references=("live-1",))
    )
    assert any(private_text in call.prompt for call in live_harness.provider.calls)
    policy = DisclosureService(catalog.approved.publishable_disclosures)
    assert policy.for_audience(outcome, "private", "public") == outcome
    public = policy.for_audience(outcome, "public", "public")
    (shown,) = public.record.progress.result.findings
    assert shown.problem == WITHHELD and shown.anchor.line == 5
    assert shown.rule_ref.id == "lantern.tenant-lookup"
    assert "private material" in public.withheld
    summary = ReviewReportService().summary(public)
    assert public.withheld in summary and "no longer passes the tenant" not in summary
    assert ReviewReportService().data(public)["withheld"] == public.withheld
    assert outcome.record == await live_harness.records.get(outcome.record.id)


async def test_public_audience_considers_code_and_denied_read_paths(harness):
    harness.provider.steps = [
        lambda request: {
            "kind": "request_context",
            "requests": [
                {
                    "question_id": "q",
                    "question": "Does the acquisition plan matter?",
                    "origin_hunk_id": json.loads(request.prompt)["change"]["files"][0][
                        "hunks"
                    ][0]["id"],
                    "relationship": "callee",
                    "target": "docs/acme-acquisition.md",
                    "expected_evidence": "Plan",
                    "start_line": 1,
                    "end_line": 5,
                }
            ],
        },
        {"kind": "done"},
        {"kind": "done"},
        {"kind": "done"},
    ]
    outcome = await harness.review()
    policy = DisclosureService(harness.catalog.approved.publishable_disclosures)
    assert policy.for_audience(outcome, "public", "public") == outcome
    public = policy.for_audience(outcome, "public", "internal")
    assert "internal material" in public.withheld
    data = json.dumps(ReviewReportService().data(public))
    assert "acme-acquisition" not in data and "acquisition plan" not in data
    assert "acme-acquisition" in json.dumps(ReviewReportService().data(outcome))


async def test_live_context_without_a_configured_source_fails_before_any_record(
    harness,
):
    with pytest.raises(ReviewError, match="not configured"):
        await harness.review(ticket_references=("live-1",))
    assert harness.provider.calls == []
