import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from app.core.errors import StateError


@asynccontextmanager
async def connect(database: Path, failure: str) -> AsyncIterator[aiosqlite.Connection]:
    if not database.is_file():
        raise StateError("Database is not initialized; run rush migrate")
    uri = database.resolve().as_uri() + "?mode=rw"
    try:
        async with aiosqlite.connect(uri, uri=True, timeout=30) as connection:
            await connection.execute("PRAGMA foreign_keys = ON")
            yield connection
    except sqlite3.Error as exc:
        raise StateError(failure) from exc
