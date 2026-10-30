import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
from pydantic import ValidationError

from app.core.errors import ReviewConflictError, ReviewError, StateError
from app.schemas.review import ReviewInputs, ReviewProgress, ReviewRecord


class SQLiteReviewRepository:
    def __init__(self, database: Path) -> None:
        self._database = database

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        if not self._database.is_file():
            raise StateError("Database is not initialized; run rush migrate")
        uri = self._database.resolve().as_uri() + "?mode=rw"
        try:
            async with aiosqlite.connect(uri, uri=True, timeout=30) as connection:
                await connection.execute("PRAGMA foreign_keys = ON")
                yield connection
        except sqlite3.Error as exc:
            raise StateError(
                "Cannot access review records; check state and run rush migrate"
            ) from exc

    async def create(self, record: ReviewRecord) -> None:
        record = ReviewRecord.model_validate_json(record.model_dump_json())
        async with self._connect() as connection:
            try:
                await connection.execute(
                    "INSERT INTO review_runs VALUES (?, ?, ?, ?)",
                    (
                        record.id,
                        record.inputs.model_dump_json(),
                        record.progress.model_dump_json(),
                        record.revision,
                    ),
                )
                await connection.commit()
            except sqlite3.IntegrityError as exc:
                raise ReviewConflictError("Review identity already exists") from exc

    async def get(self, run_id: str) -> ReviewRecord:
        async with (
            self._connect() as connection,
            connection.execute(
                "SELECT inputs_json, progress_json, revision FROM review_runs "
                "WHERE run_id = ?",
                (run_id,),
            ) as cursor,
        ):
            row = await cursor.fetchone()
        if row is None:
            raise ReviewError("Review run not found")
        try:
            record = ReviewRecord(
                id=run_id,
                inputs=ReviewInputs.model_validate_json(row[0]),
                progress=ReviewProgress.model_validate_json(row[1]),
            )
        except ValidationError as exc:
            raise StateError("Stored review record is invalid") from exc
        if record.revision != row[2]:
            raise StateError("Stored review revision does not match its history")
        return record

    async def save(self, record: ReviewRecord, expected_revision: int) -> None:
        record = ReviewRecord.model_validate_json(record.model_dump_json())
        if record.revision != expected_revision + 1:
            raise ReviewConflictError("Review progress must append one event")
        async with self._connect() as connection:
            async with connection.execute(
                "UPDATE review_runs SET progress_json = ?, revision = ? "
                "WHERE run_id = ? AND revision = ? AND inputs_json = ?",
                (
                    record.progress.model_dump_json(),
                    record.revision,
                    record.id,
                    expected_revision,
                    record.inputs.model_dump_json(),
                ),
            ) as cursor:
                if cursor.rowcount != 1:
                    raise ReviewConflictError(
                        "Review changed concurrently or its inputs were altered"
                    )
            await connection.commit()
