import asyncio
import json
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.core.errors import ReviewConflictError, ReviewError, StateError
from app.core.settings import Settings
from app.db.migrate import MIGRATIONS, migrate
from app.db.repositories.reviews import SQLiteReviewRepository
from app.db.repositories.state import SQLiteStateRepository
from app.dependencies import build_review_records
from app.schemas.review import (
    EvidenceRef,
    ReviewInputs,
    ReviewProgress,
    ReviewRecord,
    RunEvent,
    SourceSnapshot,
)
from app.services.review_records import ReviewRecordService


async def test_assembled_record_flow_survives_restart_and_freezes_inputs(
    initialized, review_inputs, review_result
):
    service = build_review_records(initialized)
    accepted = await service.create("demo-run", review_inputs)
    for status in ("preparing", "reviewing"):
        saved = await service.advance(
            "demo-run", status, f"Entered {status}", review_result
        )
    changed = json.loads(review_inputs.model_dump_json())
    changed["rules"][0]["version"] = "2"
    changed["skills"][0]["digest"] = "f" * 64
    changed["settings"]["models"][0]["model_id"] = "muse-wonder-1.0"
    changed["sources"][0]["revision"] = "changed"
    changed["sources"][0]["excerpt"] = "Replacement content"
    next_inputs = ReviewInputs.model_validate_json(json.dumps(changed))
    restarted = build_review_records(initialized)
    await restarted.create("next-run", next_inputs)
    assert (await restarted.get("demo-run")).status == "reviewing"
    for status in ("validating", "publishing", "completed"):
        saved = await restarted.advance(
            "demo-run", status, f"Entered {status}", review_result
        )
    restored = await restarted.get("demo-run")
    assert restored == saved
    assert restored.inputs == accepted.inputs == review_inputs
    assert restored.progress.result == review_result
    assert (await restarted.get("next-run")).inputs == next_inputs
    assert restored.progress.events[-1].status == "completed"
    assert len(restored.progress.events) == 6


async def test_backup_retains_review_inputs_and_partial_results(
    initialized, review_inputs, review_result, tmp_path
):
    from app.schemas.review import Limitation

    service = build_review_records(initialized)
    await service.create("demo-run", review_inputs)
    result = review_result.model_copy(
        update={
            "limitations": (
                Limitation(code="missing_context", reason="Guideline unavailable"),
            )
        }
    )
    saved = await service.advance("demo-run", "partial", "Context unavailable", result)
    destination = tmp_path / "review-backup.sqlite3"
    await SQLiteStateRepository(initialized.database_path).backup(destination)
    assert await SQLiteReviewRepository(destination).get("demo-run") == saved


async def test_duplicate_identity_and_missing_run_are_explicit(
    initialized, review_inputs
):
    service = build_review_records(initialized)
    accepted = await service.create("demo-run", review_inputs)
    with pytest.raises(ReviewConflictError, match="already exists"):
        await service.create("demo-run", review_inputs)
    assert await service.get("demo-run") == accepted
    with pytest.raises(ReviewError, match="not found"):
        await service.get("unknown")


async def test_concurrent_saves_cannot_lose_progress(initialized, review_inputs):
    service = build_review_records(initialized)
    accepted = await service.create("demo-run", review_inputs)
    update = ReviewRecord(
        id=accepted.id,
        inputs=accepted.inputs,
        progress=ReviewProgress(
            events=(
                *accepted.progress.events,
                RunEvent(
                    status="preparing",
                    reason="Start",
                    at=accepted.progress.events[0].at,
                ),
            )
        ),
    )
    results = await asyncio.gather(
        SQLiteReviewRepository(initialized.database_path).save(update, 0),
        SQLiteReviewRepository(initialized.database_path).save(update, 0),
        return_exceptions=True,
    )
    assert sum(result is None for result in results) == 1
    assert sum(isinstance(result, ReviewConflictError) for result in results) == 1
    assert await service.get("demo-run") == update


async def test_storage_refuses_input_replacement_or_non_append_progress(
    initialized, review_inputs
):
    service = build_review_records(initialized)
    accepted = await service.create("demo-run", review_inputs)
    repository = SQLiteReviewRepository(initialized.database_path)
    with pytest.raises(ReviewConflictError, match="one event"):
        await repository.save(accepted, 0)
    changed = accepted.model_copy(
        update={
            "inputs": review_inputs.model_copy(update={"head_sha": "f" * 40}),
            "progress": ReviewProgress(
                events=(
                    *accepted.progress.events,
                    RunEvent(
                        status="preparing",
                        reason="Changed inputs",
                        at=accepted.progress.events[0].at,
                    ),
                )
            ),
        }
    )
    with pytest.raises(ReviewConflictError, match="inputs"):
        await repository.save(changed, 0)
    assert await service.get("demo-run") == accepted


async def test_upgrade_from_setup_preserves_metadata_and_existing_reviews(
    tmp_path, review_inputs
):
    old_migrations = tmp_path / "old-migrations"
    old_migrations.mkdir()
    shutil.copy2(MIGRATIONS / "001_initial.sql", old_migrations)
    database = tmp_path / "state" / "rush.sqlite3"
    assert migrate(database, old_migrations) == 1
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO app_metadata VALUES ('retained', 'before-upgrade')"
        )
    assert migrate(database) == 3
    settings = Settings(state_dir=database.parent)
    accepted = await build_review_records(settings).create("demo-run", review_inputs)
    assert migrate(database) == 3
    assert await build_review_records(settings).get("demo-run") == accepted
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT value FROM app_metadata WHERE key='retained'"
        ).fetchone() == ("before-upgrade",)


async def test_uninitialized_or_old_database_does_not_silently_create_schema(
    tmp_path, review_inputs
):
    database = tmp_path / "rush.sqlite3"
    repository = SQLiteReviewRepository(database)
    with pytest.raises(StateError, match="rush migrate"):
        await repository.get("demo-run")
    assert not database.exists()
    old = tmp_path / "migrations"
    old.mkdir()
    shutil.copy2(MIGRATIONS / "001_initial.sql", old)
    migrate(database, old)
    settings = Settings(state_dir=tmp_path)
    with pytest.raises(StateError, match="rush migrate"):
        await build_review_records(settings).create("demo-run", review_inputs)
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone() == (1,)


@pytest.mark.parametrize("corruption", ["json", "revision"])
async def test_corrupt_record_is_not_reported_as_a_valid_review(
    initialized, review_inputs, corruption
):
    service = build_review_records(initialized)
    await service.create("demo-run", review_inputs)
    with sqlite3.connect(initialized.database_path) as connection:
        if corruption == "json":
            connection.execute(
                "UPDATE review_runs SET inputs_json = '{}' WHERE run_id = 'demo-run'"
            )
        else:
            connection.execute(
                "UPDATE review_runs SET revision = 99 WHERE run_id = 'demo-run'"
            )
    with pytest.raises(StateError, match="Stored review"):
        await service.get("demo-run")


@pytest.mark.parametrize("revision", ["omitted", None])
async def test_unversioned_context_and_evidence_survive_restart(
    initialized, review_inputs, review_result, revision
):
    context = {
        "id": "ticket-context",
        "kind": "ticket",
        "reference": "demo://lantern/ticket",
        "content_sha256": "a" * 64,
        "retrieved_at": datetime(2026, 1, 15, tzinfo=UTC),
    }
    if revision is None:
        context["revision"] = None
    source = SourceSnapshot.model_validate(context)
    inputs = review_inputs.model_copy(
        update={"sources": (*review_inputs.sources, source)}
    )
    evidence = EvidenceRef(
        source_id=source.id,
        content_sha256=source.content_sha256,
        start=1,
        end=1,
    )
    finding = review_result.findings[0].model_copy(
        update={
            "evidence": (*review_result.findings[0].evidence, evidence),
        }
    )
    result = review_result.model_copy(update={"findings": (finding,)})
    service = build_review_records(initialized)
    await service.create("demo-run", inputs)
    saved = await service.advance(
        "demo-run", "preparing", "Read unversioned context", result
    )
    restored = await build_review_records(initialized).get("demo-run")
    assert restored == saved
    assert restored.inputs.sources[-1].revision is None
    assert restored.progress.result.findings[0].evidence[-1].revision is None
    bad = evidence.model_copy(update={"content_sha256": "f" * 64})
    invalid = result.model_copy(
        update={"findings": (finding.model_copy(update={"evidence": (bad,)}),)}
    )
    with pytest.raises(ReviewError, match="frozen source"):
        await service.advance("demo-run", "reviewing", "Wrong content hash", invalid)
    assert await service.get("demo-run") == saved


async def test_equivalent_json_encodings_do_not_block_progress(
    initialized, review_inputs
):
    service = build_review_records(initialized)
    accepted = await service.create("demo-run", review_inputs)
    different_encoding = json.dumps(
        json.loads(review_inputs.model_dump_json()),
        sort_keys=True,
        indent=4,
    )
    assert different_encoding != review_inputs.model_dump_json()
    with sqlite3.connect(initialized.database_path) as connection:
        connection.execute(
            "UPDATE review_runs SET inputs_json = ? WHERE run_id = ?",
            (different_encoding, accepted.id),
        )
    updated = await service.advance(
        "demo-run", "preparing", "Same inputs, different JSON"
    )
    assert updated.inputs == accepted.inputs
    assert updated.revision == 1
    with sqlite3.connect(initialized.database_path) as connection:
        assert connection.execute(
            "SELECT inputs_json FROM review_runs WHERE run_id = ?",
            (accepted.id,),
        ).fetchone() == (different_encoding,)


async def test_lookup_columns_track_progress_and_support_pr_queries(
    initialized, review_inputs
):
    now = datetime(2026, 1, 15, 15, tzinfo=timezone(timedelta(hours=3)))
    service = ReviewRecordService(
        SQLiteReviewRepository(initialized.database_path),
        lambda: now,
    )
    await service.create("demo-run", review_inputs)
    now += timedelta(minutes=1)
    await service.advance("demo-run", "preparing", "Preparing inputs")
    with sqlite3.connect(initialized.database_path) as connection:
        assert connection.execute(
            "SELECT run_id, head_sha, status, created_at, updated_at FROM review_runs "
            "WHERE repository = ? AND pull_request = ? AND head_sha = ? AND status = ?",
            (
                review_inputs.repository,
                review_inputs.pull_request,
                review_inputs.head_sha,
                "preparing",
            ),
        ).fetchall() == [
            (
                "demo-run",
                review_inputs.head_sha,
                "preparing",
                "2026-01-15T12:00:00.000Z",
                "2026-01-15T12:01:00.000Z",
            )
        ]


async def test_lookup_upgrade_backfills_existing_records_without_changing_payloads(
    tmp_path, review_inputs
):
    old = tmp_path / "old-migrations"
    old.mkdir()
    for name in ("001_initial.sql", "002_review_records.sql"):
        shutil.copy2(MIGRATIONS / name, old)
    database = tmp_path / "rush.sqlite3"
    assert migrate(database, old) == 2
    at = datetime(2026, 1, 15, 15, tzinfo=timezone(timedelta(hours=3)))
    progress = ReviewProgress(
        events=(
            RunEvent(status="queued", reason="Accepted", at=at),
            RunEvent(
                status="preparing", reason="Preparing", at=at + timedelta(minutes=1)
            ),
        )
    )
    inputs_json = review_inputs.model_dump_json()
    progress_json = progress.model_dump_json()
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO review_runs VALUES (?, ?, ?, ?)",
            ("legacy-run", inputs_json, progress_json, 1),
        )
    assert migrate(database) == 3
    restored = await SQLiteReviewRepository(database).get("legacy-run")
    assert restored.inputs == review_inputs and restored.progress == progress
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT repository, pull_request, head_sha, status, created_at, updated_at "
            "FROM review_runs WHERE run_id = 'legacy-run'",
        ).fetchone() == (
            review_inputs.repository,
            review_inputs.pull_request,
            review_inputs.head_sha,
            "preparing",
            "2026-01-15T12:00:00.000Z",
            "2026-01-15T12:01:00.000Z",
        )
        assert connection.execute(
            "SELECT inputs_json, progress_json, revision FROM review_runs "
            "WHERE run_id = 'legacy-run'",
        ).fetchone() == (inputs_json, progress_json, 1)
        indexes = connection.execute("PRAGMA index_list(review_runs)").fetchall()
        assert "review_runs_by_pull_request" in [index[1] for index in indexes]
    updated = await build_review_records(Settings(state_dir=tmp_path)).advance(
        "legacy-run", "reviewing", "Resume after upgrade"
    )
    assert updated.inputs == review_inputs
    assert updated.revision == 2


@pytest.mark.parametrize("storage_state", ["corrupt", "missing"])
async def test_save_rejects_unreadable_original_inputs(
    initialized, review_inputs, storage_state
):
    service = build_review_records(initialized)
    accepted = await service.create("demo-run", review_inputs)
    progress = ReviewProgress(
        events=(
            *accepted.progress.events,
            RunEvent(
                status="preparing",
                reason="Preparing",
                at=accepted.progress.events[0].at,
            ),
        )
    )
    update = ReviewRecord(id=accepted.id, inputs=accepted.inputs, progress=progress)
    with sqlite3.connect(initialized.database_path) as connection:
        if storage_state == "corrupt":
            connection.execute(
                "UPDATE review_runs SET inputs_json = '{}' WHERE run_id = 'demo-run'"
            )
        else:
            connection.execute("DELETE FROM review_runs WHERE run_id = 'demo-run'")
    error = StateError if storage_state == "corrupt" else ReviewConflictError
    with pytest.raises(error):
        await SQLiteReviewRepository(initialized.database_path).save(update, 0)
