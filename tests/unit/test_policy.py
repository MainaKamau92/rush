import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.errors import ReviewError
from app.schemas.code_change import ChangeLine, ChangeScope, FileChange, Hunk
from app.schemas.review import (
    DiffAnchor,
    EvidenceRef,
    Finding,
    RuleRef,
    SourceSnapshot,
    VersionPin,
)
from app.services.policy import Judgement, PolicyService

CONTEXT = Path(__file__).resolve().parents[1] / "fixtures/customer_lookup/context"
NOW = datetime(2026, 1, 15, 12, tzinfo=UTC)
TENANT = json.loads((CONTEXT / "rules.json").read_text())[0]
WAIVER = json.loads((CONTEXT / "valid-exception.json").read_text())[0]
GUIDELINE = (CONTEXT / "guideline.md").read_text()


def resolve(rules=(TENANT,), exceptions=(), sources=(), paths=("customers.py",), **kw):
    return PolicyService().resolve(
        repository=kw.get("repository", "lantern"),
        paths=paths,
        sources=sources,
        review_time=kw.get("review_time", NOW),
        rules=json.dumps(list(rules)),
        exceptions=json.dumps(list(exceptions)),
        approvers=kw.get("approvers", ("Ivo Reed",)),
        allow_cached_policy=kw.get("allow_cached_policy", False),
    )


def scope(definition="def customer_name(connection, tenant_id, external_id):"):
    return ChangeScope(
        comparison="exact",
        target_sha=None,
        base_sha="a" * 40,
        head_sha="b" * 40,
        omissions=(),
        files=tuple(
            FileChange(
                status="modified",
                old_path=path,
                new_path=path,
                old_object="c" * 40,
                new_object="d" * 40,
                old_mode="100644",
                new_mode="100644",
                additions=1,
                deletions=1,
                hunks=(
                    Hunk(
                        id="h",
                        old_start=4,
                        old_lines=2,
                        new_start=4,
                        new_lines=2,
                        lines=(
                            ChangeLine(
                                kind="context", old_line=4, new_line=4, text=definition
                            ),
                            ChangeLine(kind="removed", old_line=5, text="    old()"),
                            ChangeLine(kind="added", new_line=5, text="    new()"),
                        ),
                    ),
                ),
            )
            for path in ("customers.py", "orders.py")
        ),
    )


def judge(policy, item, conflicted=frozenset(), changed=None):
    return policy.judge(item, changed or scope(), conflicted)


def finding(rule=("lantern.tenant-lookup", "1"), path="customers.py"):
    evidence = EvidenceRef(source_id="diff:h", content_sha256="a" * 64, start=1, end=1)
    return Finding(
        id="run-1",
        fingerprint="f",
        run_id="run",
        skill=VersionPin(id="rush.team-standards", version="0.1.0", digest="b" * 64),
        rule_ref=RuleRef(id=rule[0], version=rule[1]) if rule else None,
        category="security",
        severity="high",
        anchor=DiffAnchor(path=path, side="RIGHT", line=5, hunk_id="h"),
        problem="Unscoped lookup.",
        consequence="Wrong tenant.",
        trigger_scenario="Shared external ID.",
        causal_path=(evidence,),
        evidence=(evidence,),
        remediation="Pass the tenant.",
        verification="code_inspected",
    )


def guideline(text=GUIDELINE, reference="guideline.md", workspace=None):
    return SourceSnapshot(
        id="guideline-1",
        kind="guideline",
        reference=reference,
        workspace=workspace,
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        retrieved_at=NOW,
        excerpt=text,
    )


def codes(policy):
    return [(item.code, item.affects_completeness) for item in policy.limitations]


def test_only_approved_current_rules_scoped_to_the_change_apply():
    policy = resolve()
    assert [rule.id for rule in policy.rules] == ["lantern.tenant-lookup"]
    assert policy.rule_pins[0].id == "lantern.tenant-lookup"
    text = json.loads(policy.model_text())
    assert text[0]["statement"] == TENANT["statement"]
    assert "approved_by" not in text[0] and "owner" not in text[0]
    assert resolve(paths=("billing.py",)).rules == ()
    scoped = TENANT | {"scope": {"path": "*.py", "repository": "other"}}
    assert resolve(rules=(scoped,)).rules == ()
    assert resolve(rules=()).model_text() is None


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"status": "proposed"}, "no authorized approval"),
        ({"approved_by": "Nia Moss"}, "no authorized approval"),
        ({"approved_at": "2026-02-01T00:00:00Z"}, "no authorized approval"),
        ({"expires_at": "2026-01-15T00:00:00Z"}, "expired"),
    ],
)
def test_unapproved_or_expired_rules_are_not_applied_and_are_explained(changes, reason):
    linked = TENANT | changes | {"source": "context/guideline.md"}
    policy = resolve(rules=(linked,), sources=(guideline(),))
    assert policy.rules == () and policy.withheld == {"guideline-1"}
    assert codes(policy) == [("policy_not_applied", True)]
    assert reason in policy.limitations[0].reason


@pytest.mark.parametrize(
    "policy_text",
    [
        "not json",
        json.dumps([{"id": "x"}]),
        json.dumps([TENANT | {"status": "maybe"}]),
        json.dumps([TENANT | {"permissions": ["publish"]}]),
    ],
)
def test_malformed_policy_is_rejected(policy_text):
    with pytest.raises(ReviewError, match="approved policy format"):
        PolicyService().resolve(
            repository="r",
            paths=(),
            sources=(),
            review_time=NOW,
            rules=policy_text,
            exceptions=None,
            approvers=(),
            allow_cached_policy=False,
        )
    with pytest.raises(ReviewError, match="once"):
        resolve(rules=(TENANT, TENANT))
    with pytest.raises(ReviewError, match="approver"):
        resolve(approvers=())


def test_changed_guidelines_block_the_rule_unless_cached_policy_is_allowed():
    approved = TENANT | {
        "source": "context/guideline.md",
        "source_sha256": hashlib.sha256(GUIDELINE.encode()).hexdigest(),
    }
    assert resolve(rules=(approved,), sources=(guideline(),)).limitations == ()
    changed = guideline(GUIDELINE + "\nNew unapproved sentence.")
    policy = resolve(rules=(approved,), sources=(changed,))
    assert policy.rules == () and policy.withheld == {"guideline-1"}
    assert codes(policy) == [("guideline_changed", True)]
    cached = resolve(rules=(approved,), sources=(changed,), allow_cached_policy=True)
    assert [rule.id for rule in cached.rules] == ["lantern.tenant-lookup"]
    assert cached.withheld == {"guideline-1"}
    assert codes(cached) == [("guideline_changed", False)]
    live = guideline(
        "Changed", reference="clickup:guideline:doc/page", workspace="clickup"
    )
    remote = approved | {"source": "clickup:guideline:doc/page"}
    assert resolve(rules=(remote,), sources=(live,)).rules == ()
    elsewhere = guideline("Changed", reference="other/guideline.md", workspace="w")
    assert resolve(rules=(approved,), sources=(elsewhere,)).limitations == ()


def test_only_explicit_overrides_of_overridable_rules_take_effect():
    broad = TENANT | {"scope": {"path": "*.py"}, "overridable": True}
    narrow = TENANT | {
        "id": "lantern.preview-lookup",
        "statement": "Staff preview may omit the tenant.",
        "overrides_rule_id": "lantern.tenant-lookup",
    }
    policy = resolve(rules=(broad, narrow), paths=("customers.py", "orders.py"))
    assert len(policy.rules) == 2 and policy.limitations == ()
    replaced = judge(policy, finding())
    assert replaced.decision == "withdraw" and "explicitly replaces" in replaced.reason
    assert judge(policy, finding(path="orders.py")).decision == "keep"
    locked = resolve(rules=(TENANT, narrow))
    assert [rule.id for rule in locked.rules] == ["lantern.tenant-lookup"]
    assert codes(locked) == [("policy_conflict", True)]
    orphan = resolve(rules=(narrow,))
    assert orphan.rules == () and codes(orphan) == [("policy_conflict", True)]
    wider = narrow | {"scope": {"path": "**"}}
    broadened = resolve(rules=(broad, wider), paths=("customers.py", "README.md"))
    assert [rule.id for rule in broadened.rules] == ["lantern.tenant-lookup"]
    same = narrow | {"scope": {"path": "*.py"}}
    assert codes(resolve(rules=(broad, same))) == [("policy_conflict", True)]


def test_a_valid_exception_waives_only_its_rule_in_its_scope():
    policy = resolve(exceptions=(WAIVER,))
    assert [item.id for item in policy.exceptions] == ["lantern.preview-waiver"]
    assert policy.exception_pins[0].version == "lantern.tenant-lookup@1"
    waived = judge(policy, finding())
    assert (waived.decision, waived.exception_id) == (
        "waive",
        "lantern.preview-waiver",
    )
    assert "approved by Ivo Reed on 2026-01-14" in waived.reason
    assert "(customer_name)" in waived.reason and "until" in waived.reason
    assert "did not verify the allowed condition" in waived.reason
    assert judge(policy, finding(rule=None)).decision == "keep"
    assert judge(policy, finding(rule=("lantern.other", "1"))).decision == "withdraw"
    assert judge(policy, finding(path="orders.py")).decision == "withdraw"
    narrow = WAIVER | {"scope": {"path": "admin/*.py"}}
    assert judge(resolve(exceptions=(narrow,)), finding()).decision == "keep"
    conflicted = judge(policy, finding(), frozenset({"lantern.tenant-lookup"}))
    assert conflicted.decision == "withdraw" and "conflict" in conflicted.reason
    other_category = finding().model_copy(update={"category": "correctness"})
    assert judge(policy, other_category) == Judgement("keep")
    elsewhere = judge(policy, finding(), changed=scope("def export_all():"))
    assert elsewhere.decision == "keep" and "could not be confirmed" in elsewhere.reason
    unnamed = judge(policy, finding(), changed=scope("    row = None"))
    assert unnamed.decision == "keep" and "customer_name" in unnamed.reason
    anywhere = resolve(exceptions=(WAIVER | {"scope": {"path": "customers.py"}},))
    assert judge(anywhere, finding(), changed=scope("x = 1")).decision == "waive"
    record = json.loads(policy.record())
    assert record["rules"][0]["approved_by"] == "Ivo Reed"
    assert record["exceptions"][0]["owner"] == "Mira Vale"


@pytest.mark.parametrize(
    ("rule", "changes", "reason"),
    [
        (TENANT, {"expires_at": "2026-01-14T00:00:00Z"}, "expired on 2026-01-14"),
        (TENANT, {"approver": "Nia Moss"}, "no authorized approval"),
        (TENANT, {"status": "proposed"}, "no authorized approval"),
        (TENANT, {"approved_at": "2026-02-01T00:00:00Z"}, "not active yet"),
        (TENANT | {"version": "2"}, {}, "needs reapproval"),
        (TENANT | {"waivable": False}, {}, "does not allow exceptions"),
    ],
)
def test_invalid_exceptions_never_suppress_and_are_explained(rule, changes, reason):
    policy = resolve(rules=(rule,), exceptions=(WAIVER | changes,))
    assert policy.exceptions == ()
    assert codes(policy) == [("policy_not_applied", False)]
    assert reason in policy.limitations[0].reason
    reference = (rule["id"], rule["version"])
    assert judge(policy, finding(rule=reference)).decision == "keep"


def test_exceptions_for_rules_outside_the_change_are_ignored_quietly():
    policy = resolve(exceptions=(WAIVER | {"rule": {"id": "x", "version": "1"}},))
    assert policy.exceptions == () and policy.limitations == ()
    assert policy.record() is not None and resolve(rules=()).record() is None
    moot = resolve(rules=(TENANT | {"status": "proposed"},), exceptions=(WAIVER,))
    assert codes(moot) == [("policy_not_applied", True), ("policy_not_applied", False)]
    assert "has no effect" in moot.limitations[1].reason
