import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal

from pydantic import ValidationError

from app.core.errors import ReviewError
from app.schemas.code_change import ChangeScope
from app.schemas.policy import EXCEPTIONS, RULES, PolicyException, PolicyScope, Rule
from app.schemas.review import Finding, Limitation, SourceSnapshot, VersionPin
from app.services.review_skills import path_matches


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _covers(scope: PolicyScope, repository: str, path: str) -> bool:
    return scope.repository in {None, repository} and path_matches(scope.path, path)


_DEFINITION = re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)")
UNCHECKED_CONDITION = (
    "rush matched the rule, version, category, path and function; it did not "
    "verify the allowed condition."
)


@dataclass(frozen=True)
class Judgement:
    decision: Literal["keep", "withdraw", "waive"]
    reason: str = ""
    exception_id: str | None = None


def enclosing_symbol(scope: ChangeScope, finding: Finding) -> str | None:
    anchor = finding.anchor
    right = anchor.side == "RIGHT"
    for file in scope.files:
        if (file.new_path if right else file.old_path) != anchor.path:
            continue
        for hunk in file.hunks:
            if hunk.id != anchor.hunk_id:
                continue
            symbol = None
            for line in hunk.lines:
                number = line.new_line if right else line.old_line
                if number is None:
                    continue
                if number > anchor.line:
                    break
                if match := _DEFINITION.match(line.text):
                    symbol = match[1]
            return symbol
    return None


def _same_source(reference: str, source: SourceSnapshot) -> bool:
    if source.reference == reference:
        return True
    return (
        source.workspace is None
        and PurePosixPath(source.reference).name == PurePosixPath(reference).name
    )


class ResolvedPolicy:
    def __init__(
        self,
        repository: str,
        rules: tuple[Rule, ...],
        exceptions: tuple[PolicyException, ...],
        withheld: frozenset[str],
        limitations: tuple[Limitation, ...],
    ) -> None:
        self.repository, self.rules, self.exceptions = repository, rules, exceptions
        self.withheld, self.limitations = withheld, limitations

    @property
    def rule_pins(self) -> tuple[VersionPin, ...]:
        return tuple(
            VersionPin(
                id=rule.id,
                version=rule.version,
                digest=_digest(rule.model_dump(mode="json")),
            )
            for rule in self.rules
        )

    @property
    def exception_pins(self) -> tuple[VersionPin, ...]:
        return tuple(
            VersionPin(
                id=item.id,
                version=f"{item.rule.id}@{item.rule.version}",
                digest=_digest(item.model_dump(mode="json")),
            )
            for item in self.exceptions
        )

    def model_text(self) -> str | None:
        if not self.rules:
            return None
        return json.dumps(
            [
                rule.model_dump(
                    mode="json",
                    include={
                        "id",
                        "version",
                        "statement",
                        "rationale",
                        "category",
                        "scope",
                        "overrides_rule_id",
                    },
                    exclude_none=True,
                )
                for rule in self.rules
            ],
            indent=1,
        )

    def record(self) -> str | None:
        if not self.rules and not self.exceptions:
            return None
        return json.dumps(
            {
                "rules": [rule.model_dump(mode="json") for rule in self.rules],
                "exceptions": [
                    item.model_dump(mode="json") for item in self.exceptions
                ],
            },
            sort_keys=True,
        )

    def judge(
        self, finding: Finding, scope: ChangeScope, conflicted: frozenset[str]
    ) -> Judgement:
        reference = finding.rule_ref
        if reference is None:
            return Judgement("keep")
        path = finding.anchor.path
        rule = next(
            (
                item
                for item in self.rules
                if (item.id, item.version) == (reference.id, reference.version)
            ),
            None,
        )
        if rule is None or not _covers(rule.scope, self.repository, path):
            return Judgement(
                "withdraw", f"Rule {reference.id} does not apply to {path}"
            )
        if rule.id in conflicted:
            return Judgement(
                "withdraw", f"Rule {rule.id} is in an unresolved policy conflict"
            )
        for narrower in self.rules:
            if narrower.overrides_rule_id == rule.id and _covers(
                narrower.scope, self.repository, path
            ):
                return Judgement(
                    "withdraw",
                    f"Rule {narrower.id} explicitly replaces {rule.id} for {path}",
                )
        for exception in self.exceptions:
            if (
                exception.rule != reference
                or finding.category != rule.category
                or not _covers(exception.scope, self.repository, path)
            ):
                continue
            symbol = exception.scope.symbol
            if symbol and enclosing_symbol(scope, finding) != symbol:
                return Judgement(
                    "keep",
                    f"Exception {exception.id} is limited to {symbol}, which could "
                    f"not be confirmed for {path} line {finding.anchor.line}; "
                    "not applied",
                )
            expiry = (
                f", until {exception.expires_at.isoformat()}"
                if exception.expires_at
                else ""
            )
            return Judgement(
                "waive",
                f"Exception {exception.id} waives {rule.id}@{rule.version} for "
                f"{exception.scope.path}"
                + (f" ({symbol})" if symbol else "")
                + f": {exception.allowed_condition} Reason: {exception.rationale} "
                f"Owner {exception.owner}; approved by {exception.approver} on "
                f"{exception.approved_at.date().isoformat()}{expiry}. "
                + UNCHECKED_CONDITION,
                exception.id,
            )
        return Judgement("keep")


class PolicyService:
    def resolve(
        self,
        *,
        repository: str,
        paths: Iterable[str],
        sources: tuple[SourceSnapshot, ...],
        review_time: datetime,
        rules: str | None,
        exceptions: str | None,
        approvers: tuple[str, ...],
        allow_cached_policy: bool,
    ) -> ResolvedPolicy:
        try:
            all_rules = RULES.validate_json(rules) if rules else ()
            all_exceptions = EXCEPTIONS.validate_json(exceptions) if exceptions else ()
        except ValidationError:
            raise ReviewError(
                "Rules and exceptions must match the approved policy format"
            ) from None
        for items in (all_rules, all_exceptions):
            identities = [item.id for item in items]
            if len(identities) != len(set(identities)):
                raise ReviewError("Each rule and exception ID may appear once")
        if (all_rules or all_exceptions) and not approvers:
            raise ReviewError(
                "Name at least one approver for the supplied rules and exceptions"
            )
        changed = tuple(paths)
        notes: list[Limitation] = []
        withheld: set[str] = set()
        applicable = []
        dropped = []
        for rule in all_rules:
            if not any(_covers(rule.scope, repository, path) for path in changed):
                continue
            problem = self._rule_problem(rule, approvers, review_time)
            if problem:
                notes.append(Limitation(code="policy_not_applied", reason=problem))
                dropped.append(rule)
            elif self._drifted(rule, sources, withheld, notes, allow_cached_policy):
                dropped.append(rule)
            else:
                applicable.append(rule)
        kept = self._overrides(applicable, notes, repository, changed)
        dropped += [rule for rule in applicable if rule not in kept]
        withheld.update(
            source.id
            for rule in dropped
            if rule.source
            for source in sources
            if source.kind == "guideline" and _same_source(rule.source, source)
        )
        applicable = kept
        active = self._exceptions(
            all_exceptions, applicable, dropped, approvers, review_time, notes
        )
        return ResolvedPolicy(
            repository, tuple(applicable), active, frozenset(withheld), tuple(notes)
        )

    @staticmethod
    def _rule_problem(
        rule: Rule, approvers: tuple[str, ...], review_time: datetime
    ) -> str | None:
        label = f"{rule.id}@{rule.version}"
        if (
            rule.status != "approved"
            or rule.approved_by not in approvers
            or rule.approved_at is None
            or rule.approved_at > review_time
        ):
            return f"Rule {label} has no authorized approval and was not applied"
        if rule.expires_at is not None and rule.expires_at <= review_time:
            return f"Rule {label} expired and was not applied"
        return None

    @staticmethod
    def _drifted(
        rule: Rule,
        sources: tuple[SourceSnapshot, ...],
        withheld: set[str],
        notes: list[Limitation],
        allow_cached_policy: bool,
    ) -> bool:
        if rule.source is None or rule.source_sha256 is None:
            return False
        changed = [
            source
            for source in sources
            if source.kind == "guideline"
            and _same_source(rule.source, source)
            and source.content_sha256 != rule.source_sha256
        ]
        if not changed:
            return False
        withheld.update(source.id for source in changed)
        if allow_cached_policy:
            notes.append(
                Limitation(
                    code="guideline_changed",
                    reason=f"The guideline for {rule.id} changed after approval; the "
                    "approved rule text is applied as the team permits, and the "
                    "new text is not used",
                    affects_completeness=False,
                )
            )
            return False
        notes.append(
            Limitation(
                code="guideline_changed",
                reason=f"The guideline for {rule.id} changed after approval and the "
                "new text is not approved; the rule was not applied",
            )
        )
        return True

    @staticmethod
    def _overrides(
        rules: list[Rule],
        notes: list[Limitation],
        repository: str,
        changed: tuple[str, ...],
    ) -> list[Rule]:
        by_id = {rule.id: rule for rule in rules}
        kept = []
        for rule in rules:
            target = by_id.get(rule.overrides_rule_id or "")
            narrower = target is not None and (
                rule.scope.path != target.scope.path
                and rule.scope.repository in {None, target.scope.repository}
                and all(
                    _covers(target.scope, repository, path)
                    for path in changed
                    if _covers(rule.scope, repository, path)
                )
            )
            if rule.overrides_rule_id and (
                target is None or not target.overridable or not narrower
            ):
                notes.append(
                    Limitation(
                        code="policy_conflict",
                        reason=f"Rule {rule.id} claims to replace "
                        f"{rule.overrides_rule_id}, which does not apply, does not "
                        f"allow overrides, or is not broader; {rule.id} was not "
                        "applied",
                    )
                )
                continue
            kept.append(rule)
        return kept

    @staticmethod
    def _exceptions(
        exceptions: tuple[PolicyException, ...],
        rules: list[Rule],
        dropped: list[Rule],
        approvers: tuple[str, ...],
        review_time: datetime,
        notes: list[Limitation],
    ) -> tuple[PolicyException, ...]:
        by_id = {rule.id: rule for rule in rules}
        unused = {rule.id for rule in dropped}
        active = []
        for exception in exceptions:
            rule = by_id.get(exception.rule.id)
            if rule is None:
                if exception.rule.id in unused:
                    notes.append(
                        Limitation(
                            code="policy_not_applied",
                            reason=f"Exception {exception.id} has no effect because "
                            f"{exception.rule.id} was not applied",
                            affects_completeness=False,
                        )
                    )
                continue
            problem = None
            if exception.status != "approved" or exception.approver not in approvers:
                problem = "has no authorized approval"
            elif exception.approved_at > review_time:
                problem = "is not active yet"
            elif exception.expires_at and exception.expires_at <= review_time:
                problem = f"expired on {exception.expires_at.date().isoformat()}"
            elif exception.rule.version != rule.version:
                problem = (
                    f"was approved for version {exception.rule.version}, but the rule "
                    f"is now version {rule.version}; it needs reapproval"
                )
            elif not rule.waivable:
                problem = f"targets {rule.id}, which does not allow exceptions"
            if problem:
                notes.append(
                    Limitation(
                        code="policy_not_applied",
                        reason=f"Exception {exception.id} {problem}; not applied",
                        affects_completeness=False,
                    )
                )
            else:
                active.append(exception)
        return tuple(active)
