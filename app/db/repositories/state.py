import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path

import aiosqlite

from app.core.errors import StateError
from app.db.migrate import migrate


class SQLiteStateRepository:
    def __init__(self, database: Path) -> None:
        self._database = database
        self._connection: aiosqlite.Connection | None = None

    async def open(self) -> None:
        if self._connection is not None:
            raise StateError("State is already open")
        if not self._database.is_file():
            raise StateError("Database is not initialized; run rush migrate")
        # mode=rw prevents a missing database from being silently recreated.
        uri = self._database.resolve().as_uri() + "?mode=rw"
        try:
            self._connection = await aiosqlite.connect(uri, uri=True)
            await self._connection.execute("PRAGMA foreign_keys = ON")
            # Opening a SQLite handle alone does not validate an existing file.
            async with self._connection.execute(
                "SELECT name FROM sqlite_master LIMIT 1"
            ):
                pass
        except sqlite3.Error as exc:
            await self.close()
            raise StateError("Cannot open state") from exc

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def schema_version(self) -> int:
        if self._connection is None:
            raise StateError("State is not open")
        try:
            async with self._connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    raise StateError("Schema version is unavailable")
                return int(row[0])
        except sqlite3.Error as exc:
            raise StateError("Cannot read state; run rush migrate") from exc

    async def migrate(self) -> int:
        return await asyncio.to_thread(migrate, self._database)

    async def backup(self, destination: Path) -> None:
        await asyncio.to_thread(_backup, self._database, destination)


def _backup(database: Path, destination: Path) -> None:
    if not database.is_file():
        raise StateError("Database is not initialized; run rush migrate")
    try:
        # Exclusive creation prevents accidentally overwriting an earlier backup.
        with destination.open("xb"):
            destination.chmod(0o600)
    except FileExistsError as exc:
        raise StateError("Backup destination already exists") from exc
    try:
        with (
            closing(
                sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
            ) as source,
            closing(sqlite3.connect(destination)) as target,
        ):
            source.backup(target)
        destination.chmod(0o600)
    except (OSError, sqlite3.Error) as exc:
        destination.unlink(missing_ok=True)
        raise StateError("Backup failed") from exc
