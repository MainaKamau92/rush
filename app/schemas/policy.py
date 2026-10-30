from typing import Literal

from pydantic import AwareDatetime, TypeAdapter

from app.schemas.review import Contract, Digest, RuleRef, Text
from app.schemas.skill import Category

Status = Literal["approved", "proposed", "retired"]


class PolicyScope(Contract):
    path: Text
    repository: Text | None = None
    symbol: Text | None = None


class Rule(Contract):
    id: Text
    version: Text
    statement: Text
    rationale: Text
    category: Category
    owner: Text
    scope: PolicyScope
    waivable: bool
    overridable: bool
    overrides_rule_id: Text | None = None
    status: Status
    approved_by: Text | None = None
    approved_at: AwareDatetime | None = None
    expires_at: AwareDatetime | None = None
    source: Text | None = None
    source_sha256: Digest | None = None


class PolicyException(Contract):
    id: Text
    rule: RuleRef
    scope: PolicyScope
    allowed_condition: Text
    rationale: Text
    owner: Text
    approver: Text
    approved_at: AwareDatetime
    expires_at: AwareDatetime | None = None
    status: Status


RULES = TypeAdapter[tuple[Rule, ...]](tuple[Rule, ...])
EXCEPTIONS = TypeAdapter[tuple[PolicyException, ...]](tuple[PolicyException, ...])
