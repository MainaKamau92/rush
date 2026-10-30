import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

from app.core.errors import (
    ChangeError,
    CodeHostError,
    ModelError,
    ReviewError,
    SourceError,
    StateError,
)
from app.models.review import TERMINAL_STATUSES
from app.provider.github.abstract import CodeHostAbstract
from app.schemas.github import JobStatus, PullRequest, ReviewJob
from app.schemas.review import ReviewRecord
from app.services.ports import JobRepository
from app.services.review_records import ReviewRecordService

MAX_ATTEMPTS = 3
POLL_SECONDS = 5.0
WRITE_PERMISSIONS = frozenset({"admin", "maintain", "write"})
EXPECTED_ERRORS = (
    ChangeError,
    CodeHostError,
    ModelError,
    ReviewError,
    SourceError,
)
REVIEW_STATUSES: dict[str, JobStatus] = {
    "completed": "completed",
    "partial": "partial",
    "skipped": "skipped",
    "superseded": "superseded",
}

Reviewer = Callable[[ReviewJob, PullRequest, Path], Awaitable[ReviewRecord]]
logger = logging.getLogger(__name__)


def mirror_name(repository: str) -> str:
    return repository.replace("/", "__") + ".git"


class ReviewJobService:
    """
    Review queued PR jobs one at a time. Interrupted jobs are queued again on
    start, so a restart never runs two reviews of the same PR at once.
    """

    def __init__(
        self,
        jobs: JobRepository,
        host: CodeHostAbstract,
        reviewer: Reviewer,
        records: ReviewRecordService,
        mirrors: Path,
        clock: Callable[[], datetime],
        poll_seconds: float = POLL_SECONDS,
    ) -> None:
        self._jobs, self._host, self._reviewer = jobs, host, reviewer
        self._records, self._mirrors, self._clock = records, mirrors, clock
        self._poll = poll_seconds
        self._wake = asyncio.Event()

    def wake(self) -> None:
        self._wake.set()

    async def recover(self) -> tuple[ReviewJob, ...]:
        recovered = await self._jobs.recover(self._clock(), MAX_ATTEMPTS)
        for job in recovered:
            await self._close_run(job, "The service stopped during this review")
        return recovered

    async def run(self) -> None:
        recovered = False
        while True:
            self._wake.clear()
            try:
                if not recovered:
                    # Only this worker runs jobs, so any running row is orphaned.
                    await self.recover()
                    recovered = True
                if await self.run_once():
                    continue
            except Exception:  # The worker must outlive any single failure.
                logger.exception("The review worker failed; recovering its jobs")
                recovered = False
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(self._poll):
                    await self._wake.wait()

    async def run_once(self) -> bool:
        job = await self._jobs.claim(self._clock())
        if job is None:
            return False
        status, reason = await self._process(job)
        await self._jobs.finish(job.id, status, reason, self._clock())
        return True

    async def recent(self, limit: int) -> tuple[ReviewJob, ...]:
        return await self._jobs.recent(limit)

    async def get(self, job_id: str) -> ReviewJob:
        return await self._jobs.get(job_id)

    async def close(self) -> None:
        await self._host.close()

    async def _process(self, job: ReviewJob) -> tuple[JobStatus, str]:
        try:
            pull = await self._host.pull_request(
                job.installation_id, job.repository, job.pull_request
            )
            skipped = await self._skip(job, pull)
            if skipped is not None:
                return skipped
            await self._jobs.note(job.id, "Fetching the PR versions", self._clock())
            await self._host.fetch(
                job.installation_id, pull, self._mirrors / mirror_name(job.repository)
            )
            await self._jobs.note(
                job.id, f"Reviewing {pull.head_sha[:12]}", self._clock()
            )
            record = await self._reviewer(
                job, pull, self._mirrors / mirror_name(job.repository)
            )
        except EXPECTED_ERRORS as error:
            await self._close_run(job, str(error))
            return "failed", str(error)
        except Exception as error:  # A failed job must never stop the worker.
            logger.exception("Review job %s failed unexpectedly", job.id)
            reason = f"Unexpected {type(error).__name__}; see the service log"
            await self._close_run(job, reason)
            return "failed", reason
        return REVIEW_STATUSES.get(record.status, "failed"), (
            record.progress.events[-1].reason
        )

    async def _skip(
        self, job: ReviewJob, pull: PullRequest
    ) -> tuple[JobStatus, str] | None:
        if pull.repository != job.repository:
            return "skipped", "The PR now targets a different repository"
        if pull.state != "open":
            return "skipped", "The PR is closed"
        if job.head_sha is not None and job.head_sha != pull.head_sha:
            return "superseded", "The PR moved to a newer commit before review"
        if job.trigger == "command":
            permission = await self._host.permission(
                job.installation_id, job.repository, job.requested_by
            )
            if permission not in WRITE_PERMISSIONS:
                return (
                    "skipped",
                    f"{job.requested_by} asked for a review but does not have "
                    "write access to the repository",
                )
        return None

    async def _close_run(self, job: ReviewJob, reason: str) -> None:
        if job.run_id is None:
            return
        try:
            record = await self._records.get(job.run_id)
            if record.status not in TERMINAL_STATUSES:
                await self._records.advance(job.run_id, "failed", reason)
        except (ReviewError, StateError):
            return
