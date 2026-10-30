import asyncio
import shutil
import sqlite3
from pathlib import Path

import pytest

from app.core.errors import StateError
from app.core.settings import Settings
from app.db.migrate import MIGRATIONS, migrate, migration_files
from app.db.repositories.state import SQLiteStateRepository

CURRENT = len(migration_files())
NEXT = f"{CURRENT + 1:03d}"


def test_migrations_are_repeatable_and_upgrades_preserve_data(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    assert migrate(database) == migrate(database) == len(migration_files())
    directory = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS, directory)
    (directory / f"{NEXT}_notes.sql").write_text(
        "ALTER TABLE app_metadata ADD COLUMN note TEXT;\n"
    )
    assert migrate(database, directory) == CURRENT + 1
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT value FROM app_metadata WHERE key='application'"
        ).fetchone() == ("rush",)


def test_failed_upgrade_rolls_back_schema_and_version(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    migrate(database)
    directory = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS, directory)
    (directory / f"{NEXT}_broken.sql").write_text(
        "CREATE TABLE transient (id INTEGER);\nINVALID SQL;\n"
    )
    with pytest.raises(StateError, match="rolled back"):
        migrate(database, directory)
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone() == (CURRENT,)
        assert not connection.execute(
            "SELECT name FROM sqlite_master WHERE name='transient'"
        ).fetchall()


def test_applied_migration_edits_and_newer_databases_are_rejected(
    tmp_path: Path,
) -> None:
    database = tmp_path / "state.sqlite3"
    migrate(database)
    directory = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS, directory)
    first = directory / "001_initial.sql"
    first.write_text(first.read_text() + "\n-- changed\n")
    with pytest.raises(StateError, match="applied migration changed"):
        migrate(database, directory)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO schema_migrations VALUES (?, 'future')", (CURRENT + 1,)
        )
    with pytest.raises(StateError, match="newer"):
        migrate(database)


def test_invalid_migration_sequences_and_incomplete_sql_are_rejected(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "migrations"
    directory.mkdir()
    database = tmp_path / "state.sqlite3"
    with pytest.raises(StateError, match="sequence"):
        migrate(database, directory)
    (directory / "001_missing_terminator.sql").write_text(
        "CREATE TABLE unfinished (id INT)"
    )
    with pytest.raises(StateError, match="incomplete"):
        migrate(database, directory)


async def test_concurrent_migration_commands_serialize(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    results = await asyncio.gather(
        *(asyncio.to_thread(migrate, database) for _ in range(2))
    )
    assert results == [CURRENT, CURRENT]
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM schema_migrations"
        ).fetchone() == (CURRENT,)


async def test_explicit_initialization_backup_and_restart(
    settings: Settings, tmp_path: Path
) -> None:
    repository = SQLiteStateRepository(settings.database_path)
    with pytest.raises(StateError, match="not initialized"):
        await repository.open()
    assert not settings.database_path.exists()
    assert await repository.migrate() == CURRENT
    await repository.open()
    with pytest.raises(StateError, match="already open"):
        await repository.open()
    assert await repository.schema_version() == CURRENT
    backup = tmp_path / "backup.sqlite3"
    await repository.backup(backup)
    with pytest.raises(StateError, match="already exists"):
        await repository.backup(backup)
    await repository.close()
    await repository.close()
    with pytest.raises(StateError, match="not open"):
        await repository.schema_version()
    restored = SQLiteStateRepository(backup)
    await restored.open()
    assert await restored.schema_version() == CURRENT
    await restored.close()


async def test_missing_or_invalid_database_does_not_report_readiness(
    tmp_path: Path,
) -> None:
    database = tmp_path / "missing.sqlite3"
    repository = SQLiteStateRepository(database)
    with pytest.raises(StateError, match="not initialized"):
        await repository.backup(tmp_path / "backup.sqlite3")
    with sqlite3.connect(database):
        pass
    await repository.open()
    try:
        with pytest.raises(StateError, match="Cannot read"):
            await repository.schema_version()
    finally:
        await repository.close()


async def test_corrupt_database_closes_failed_connection(tmp_path: Path) -> None:
    database = tmp_path / "corrupt.sqlite3"
    database.write_text("not a SQLite database")
    repository = SQLiteStateRepository(database)
    with pytest.raises(StateError, match="Cannot open"):
        await repository.open()
    with pytest.raises(StateError, match="not open"):
        await repository.schema_version()


async def test_failed_backup_removes_partial_output(
    initialized: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(*args: object, **kwargs: object) -> None:
        raise sqlite3.OperationalError("unavailable")

    monkeypatch.setattr("app.db.repositories.state.sqlite3.connect", unavailable)
    destination = tmp_path / "failed-backup.sqlite3"
    with pytest.raises(StateError, match="Backup failed"):
        await SQLiteStateRepository(initialized.database_path).backup(destination)
    assert not destination.exists()
