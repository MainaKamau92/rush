import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

from app.core.errors import StateError

MIGRATIONS = Path(__file__).with_name("migrations")


def migration_files(directory: Path = MIGRATIONS) -> list[Path]:
    paths = sorted(directory.glob("[0-9][0-9][0-9]_*.sql"))
    versions = [int(path.name.split("_", 1)[0]) for path in paths]
    if not paths or versions != list(range(1, len(paths) + 1)):
        raise StateError("Migration sequence must start at 001 without gaps")
    return paths


def _statements(sql: str) -> list[str]:
    statements: list[str] = []
    pending = ""
    for line in sql.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            statements.append(pending)
            pending = ""
    if pending.strip():
        raise StateError("Migration contains an incomplete SQL statement")
    return statements


def migrate(database: Path, directory: Path = MIGRATIONS) -> int:
    paths = migration_files(directory)
    database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        with closing(sqlite3.connect(database, timeout=30)) as connection, connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, digest TEXT NOT NULL)"
            )
            applied = dict(connection.execute("SELECT * FROM schema_migrations"))
            _apply(connection, paths, applied)
        database.chmod(0o600)
    except sqlite3.Error as exc:
        raise StateError("Migration failed; transaction rolled back") from exc
    return len(paths)


def _apply(
    connection: sqlite3.Connection, paths: list[Path], applied: dict[int, str]
) -> None:
    if set(applied) - set(range(1, len(paths) + 1)):
        raise StateError("Database is newer than this release")
    for version, path in enumerate(paths, start=1):
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if version in applied:
            if applied[version] != digest:
                raise StateError(
                    "An applied migration changed; restore its original file"
                )
            continue
        for statement in _statements(content.decode()):
            connection.execute(statement)
        connection.execute(
            "INSERT INTO schema_migrations VALUES (?, ?)", (version, digest)
        )
