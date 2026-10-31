from contextlib import AbstractAsyncContextManager
from pathlib import Path

import aiosqlite

from app.db.repositories.connection import connect
from app.models.github import FindingEvent


class SQLiteFindingEventRepository:
    def __init__(self, database: Path) -> None:
        self._database = database

    def _connect(self) -> AbstractAsyncContextManager[aiosqlite.Connection]:
        return connect(
            self._database,
            "Cannot access finding history; check state and run rush migrate",
        )

    async def record(self, event: FindingEvent) -> None:
        async with self._connect() as connection:
            await connection.execute(
                "INSERT INTO finding_events (repository, pull_request, identity, "
                "run_id, actor, action, reason, detail_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', ?))",
                (
                    event.repository,
                    event.pull_request,
                    event.identity,
                    event.run_id,
                    event.actor,
                    event.action,
                    event.reason,
                    event.detail,
                    event.created_at,
                ),
            )
            await connection.commit()

    async def history(
        self, repository: str, pull_request: int, identity: str
    ) -> tuple[FindingEvent, ...]:
        async with (
            self._connect() as connection,
            connection.execute(
                "SELECT repository, pull_request, identity, run_id, actor, action, "
                "reason, detail_json, created_at FROM finding_events "
                "WHERE repository = ? AND pull_request = ? AND identity = ? "
                "ORDER BY event_id",
                (repository, pull_request, identity),
            ) as cursor,
        ):
            rows = await cursor.fetchall()
        return tuple(
            FindingEvent(
                str(row[0]),
                int(row[1]),
                str(row[2]),
                str(row[3]),
                str(row[4]),
                str(row[5]),
                None if row[6] is None else str(row[6]),
                str(row[7]),
                str(row[8]),
            )
            for row in rows
        )
