from contextlib import AbstractAsyncContextManager
from datetime import datetime
from pathlib import Path

import aiosqlite

from app.db.repositories.connection import connect


class SQLitePublicationRepository:
    def __init__(self, database: Path) -> None:
        self._database = database

    def _connect(self) -> AbstractAsyncContextManager[aiosqlite.Connection]:
        return connect(
            self._database,
            "Cannot access publications; check state and run rush migrate",
        )

    async def plan(self, run_id: str, item: str, kind: str, at: datetime) -> None:
        async with self._connect() as connection:
            await connection.execute(
                "INSERT INTO publications (run_id, item, kind, status, updated_at) "
                "VALUES (?, ?, ?, 'planned', strftime('%Y-%m-%dT%H:%M:%fZ', ?)) "
                "ON CONFLICT (run_id, item) DO UPDATE SET status = 'planned', "
                "updated_at = excluded.updated_at",
                (run_id, item, kind, at.isoformat()),
            )
            await connection.commit()

    async def settle(
        self,
        run_id: str,
        item: str,
        status: str,
        comment_id: int | None,
        detail: str | None,
        at: datetime,
    ) -> None:
        async with self._connect() as connection:
            await connection.execute(
                "UPDATE publications SET status = ?, comment_id = ?, detail = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', ?) "
                "WHERE run_id = ? AND item = ?",
                (status, comment_id, detail, at.isoformat(), run_id, item),
            )
            await connection.commit()

    async def items(self, run_id: str) -> tuple[tuple[str, str, int | None], ...]:
        async with (
            self._connect() as connection,
            connection.execute(
                "SELECT item, status, comment_id FROM publications WHERE run_id = ? "
                "ORDER BY item",
                (run_id,),
            ) as cursor,
        ):
            return tuple(
                (str(item), str(status), comment)
                for item, status, comment in await cursor.fetchall()
            )
