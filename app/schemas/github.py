from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, field_validator

from app.schemas.review import Commit, Contract, NonNegative, Positive, Text

Repository = Annotated[str, Field(pattern=r"^[a-z0-9_.-]+/[a-z0-9_.-]+$")]
JobStatus = Literal[
    "queued", "running", "completed", "partial", "failed", "skipped", "superseded"
]
Trigger = Literal["opened", "reopened", "synchronize", "command", "thread"]
ACTIVE_JOB_STATUSES = frozenset({"queued", "running"})
WRITE_PERMISSIONS = frozenset({"admin", "maintain", "write"})


class ReviewJob(Contract):
    id: Text
    repository: Repository
    pull_request: Positive
    installation_id: Positive
    head_sha: Commit | None = None
    trigger: Trigger
    requested_by: Text
    status: JobStatus = "queued"
    reason: Text = "Waiting for the review worker"
    run_id: Text | None = None
    attempts: NonNegative = 0
    created_at: AwareDatetime
    updated_at: AwareDatetime
    comment_id: Positive | None = None
    request: str | None = None


class PullRequest(Contract):
    repository: Repository
    number: Positive
    state: Literal["open", "closed"]
    head_sha: Commit
    base_sha: Commit
    base_ref: Annotated[str, Field(pattern=r"^[A-Za-z0-9_][A-Za-z0-9._/-]*$")]
    body: str | None = None

    @field_validator("base_ref")
    @classmethod
    def plain_branch(cls, value: str) -> str:
        if ".." in value or "//" in value or value.endswith(("/", ".", ".lock")):
            raise ValueError("The PR target must be a plain branch name")
        return value
