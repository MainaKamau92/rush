from collections.abc import Iterable
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from pathlib import Path

import aiosqlite
from pydantic import ValidationError

from app.core.errors import ReviewError, StateError
from app.db.repositories.connection import connect
from app.models.github import Acceptance
from app.schemas.github import JobStatus, ReviewJob

NAMES = (
    "id",
    "repository",
    "pull_request",
    "installation_id",
    "head_sha",
    "trigger",
    "requested_by",
    "status",
    "reason",
    "run_id",
    "attempts",
    "created_at",
    "updated_at",
    "comment_id",
    "request",
)
SELECTED = (
    "SELECT job_id, repository, pull_request, installation_id, head_sha, trigger, "
    "requested_by, status, reason, run_id, attempts, created_at, updated_at, "
    "comment_id, request FROM review_jobs"
)
SUPERSEDED = "A newer commit arrived before this review started"
NEWER_REQUEST = "A newer review of this PR was requested while this one was stopped"


def _job(row: Iterable[object]) -> ReviewJob:
    values = dict(zip(NAMES, row, strict=True))
    try:
        for name in ("created_at", "updated_at"):
            values[name] = datetime.fromisoformat(str(values[name]))
        return ReviewJob.model_validate(values)
    except (ValueError, ValidationError) as exc:
        raise StateError("Stored review job is invalid") from exc


class SQLiteJobRepository:
    def __init__(self, database: Path) -> None:
        self._database = database

    def _connect(self) -> AbstractAsyncContextManager[aiosqlite.Connection]:
        return connect(
            self._database,
            "Cannot access review jobs; check state and run rush migrate",
        )

    async def accept(
        self,
        delivery_id: str,
        payload_sha256: str,
        event: str,
        job: ReviewJob | None,
        at: datetime,
    ) -> Acceptance:
        async with self._connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            # Delivery IDs are not signed, so a replayed body is matched by its digest.
            async with connection.execute(
                "SELECT 1 FROM github_deliveries "
                "WHERE delivery_id = ? OR payload_sha256 = ?",
                (delivery_id, payload_sha256),
            ) as cursor:
                if await cursor.fetchone() is not None:
                    await connection.rollback()
                    return Acceptance("duplicate_delivery")
            acceptance = Acceptance("ignored")
            if job is not None:
                acceptance = await self._enqueue(connection, job, at)
            await connection.execute(
                "INSERT INTO github_deliveries "
                "(delivery_id, payload_sha256, event, outcome, job_id, received_at) "
                "VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', ?))",
                (
                    delivery_id,
                    payload_sha256,
                    event,
                    acceptance.outcome,
                    acceptance.job_id,
                    at.isoformat(),
                ),
            )
            await connection.commit()
        return acceptance

    @staticmethod
    async def _enqueue(
        connection: aiosqlite.Connection, job: ReviewJob, at: datetime
    ) -> Acceptance:
        if job.trigger == "thread":
            await SQLiteJobRepository._insert(connection, job)
            return Acceptance("queued", job.id)
        async with connection.execute(
            "SELECT job_id, head_sha FROM review_jobs WHERE repository = ? "
            "AND pull_request = ? AND status IN ('queued', 'running') "
            "AND trigger != 'thread' "
            "ORDER BY created_at, rowid",
            (job.repository, job.pull_request),
        ) as cursor:
            active = list(await cursor.fetchall())
        for job_id, head_sha in active:
            if job.head_sha is None or head_sha == job.head_sha:
                return Acceptance("already_active", str(job_id))
        await connection.execute(
            "UPDATE review_jobs SET status = 'superseded', reason = ?, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', ?) "
            "WHERE repository = ? AND pull_request = ? AND status = 'queued' "
            "AND trigger != 'thread'",
            (SUPERSEDED, at.isoformat(), job.repository, job.pull_request),
        )
        await SQLiteJobRepository._insert(connection, job)
        return Acceptance("queued", job.id)

    @staticmethod
    async def _insert(connection: aiosqlite.Connection, job: ReviewJob) -> None:
        await connection.execute(
            "INSERT INTO review_jobs (job_id, repository, pull_request, "
            "installation_id, head_sha, trigger, requested_by, status, reason, "
            "run_id, attempts, created_at, updated_at, comment_id, request) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "strftime('%Y-%m-%dT%H:%M:%fZ', ?), strftime('%Y-%m-%dT%H:%M:%fZ', ?), "
            "?, ?)",
            (
                job.id,
                job.repository,
                job.pull_request,
                job.installation_id,
                job.head_sha,
                job.trigger,
                job.requested_by,
                job.status,
                job.reason,
                job.run_id,
                job.attempts,
                job.created_at.isoformat(),
                job.updated_at.isoformat(),
                job.comment_id,
                job.request,
            ),
        )

    async def claim(self, at: datetime) -> ReviewJob | None:
        async with self._connect() as connection:
            async with connection.execute(
                "UPDATE review_jobs SET status = 'running', attempts = attempts + 1, "
                "run_id = job_id || '-' || (attempts + 1), "
                "reason = 'Preparing the review', "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', ?) "
                "WHERE job_id = (SELECT job_id FROM review_jobs "
                "WHERE status = 'queued' ORDER BY created_at, rowid LIMIT 1) "
                "RETURNING job_id, repository, pull_request, installation_id, "
                "head_sha, trigger, requested_by, status, reason, run_id, attempts, "
                "created_at, updated_at, comment_id, request",
                (at.isoformat(),),
            ) as cursor:
                row = await cursor.fetchone()
            await connection.commit()
        return None if row is None else _job(row)

    async def note(self, job_id: str, reason: str, at: datetime) -> None:
        async with self._connect() as connection:
            await connection.execute(
                "UPDATE review_jobs SET reason = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', ?) "
                "WHERE job_id = ? AND status = 'running'",
                (reason, at.isoformat(), job_id),
            )
            await connection.commit()

    async def finish(
        self, job_id: str, status: JobStatus, reason: str, at: datetime
    ) -> None:
        async with self._connect() as connection:
            async with connection.execute(
                "UPDATE review_jobs SET status = ?, reason = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', ?) "
                "WHERE job_id = ? AND status = 'running'",
                (status, reason, at.isoformat(), job_id),
            ) as cursor:
                changed = cursor.rowcount
            await connection.commit()
        if changed != 1:
            raise ReviewError("Only a running review job can finish")

    async def recover(self, at: datetime, max_attempts: int) -> tuple[ReviewJob, ...]:
        async with self._connect() as connection:
            async with connection.execute(
                "UPDATE review_jobs SET "
                "status = CASE WHEN attempts >= ? THEN 'failed' ELSE 'queued' END, "
                "reason = CASE WHEN attempts >= ? "
                "THEN 'The service stopped during every attempt; not retried' "
                "ELSE 'The service stopped during this review; queued again' END, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', ?) "
                "WHERE status = 'running' "
                "RETURNING job_id, repository, pull_request, installation_id, "
                "head_sha, trigger, requested_by, status, reason, run_id, attempts, "
                "created_at, updated_at, comment_id, request",
                (max_attempts, max_attempts, at.isoformat()),
            ) as cursor:
                rows = list(await cursor.fetchall())
            await connection.execute(
                "UPDATE review_jobs SET status = 'superseded', reason = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', ?) "
                "WHERE status = 'queued' AND trigger != 'thread' AND EXISTS "
                "(SELECT 1 FROM review_jobs AS newer "
                "WHERE newer.repository = review_jobs.repository "
                "AND newer.pull_request = review_jobs.pull_request "
                "AND newer.status = 'queued' AND newer.trigger != 'thread' "
                "AND (newer.created_at, newer.rowid) > "
                "(review_jobs.created_at, review_jobs.rowid))",
                (NEWER_REQUEST, at.isoformat()),
            )
            await connection.commit()
        return tuple(_job(row) for row in rows)

    async def get(self, job_id: str) -> ReviewJob:
        async with (
            self._connect() as connection,
            connection.execute(SELECTED + " WHERE job_id = ?", (job_id,)) as cursor,
        ):
            row = await cursor.fetchone()
        if row is None:
            raise ReviewError("Review job not found")
        return _job(row)

    async def recent(self, limit: int) -> tuple[ReviewJob, ...]:
        async with (
            self._connect() as connection,
            connection.execute(
                SELECTED + " ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (limit,),
            ) as cursor,
        ):
            rows = list(await cursor.fetchall())
        return tuple(_job(row) for row in rows)
