from typing import Literal

from app.schemas.code_change import ChangeScope
from app.schemas.review import Contract, Limitation, NonNegative, Positive, Text

Relationship = Literal[
    "import", "callee", "caller", "shared_interface", "configuration", "test"
]
BudgetResource = Literal[
    "changed_files",
    "changed_lines",
    "additional_files",
    "snippet_reads",
    "relationship_depth",
    "mcp_calls",
    "scoped_searches",
    "model_calls",
    "source_bytes",
]


class ReadRequest(Contract):
    question_id: Text
    question: Text
    origin_hunk_id: Text
    relationship: Relationship
    target: Text
    expected_evidence: Text
    start_line: Positive
    end_line: Positive
    parent_read_id: Text | None = None


class Snippet(Contract):
    id: Text
    question_id: Text
    origin_hunk_id: Text
    path: Text
    commit: Text
    object_id: Text
    start_line: Positive
    end_line: Positive
    text: str
    depth: Positive


class ReadAudit(Contract):
    request: ReadRequest
    action: Literal["scoped_search", "read", "denied"]
    path: Text
    reason: Text
    source_path: Text | None = None
    source_start_line: Positive | None = None
    source_end_line: Positive | None = None
    source_object_id: Text | None = None
    snippet: Snippet | None = None


class Question(Contract):
    id: Text
    question: Text
    origin_hunk_id: Text
    required: bool = True
    answer: Text | None = None
    evidence_ids: tuple[Text, ...] = ()


class BudgetCounter(Contract):
    resource: BudgetResource
    used: NonNegative
    limit: NonNegative


class InvestigationReport(Contract):
    scope: ChangeScope | None
    questions: tuple[Question, ...]
    reads: tuple[ReadAudit, ...]
    counters: tuple[BudgetCounter, ...]
    elapsed_seconds: float
    limitations: tuple[Limitation, ...]

    @property
    def complete(self) -> bool:
        return not any(item.affects_completeness for item in self.limitations)
