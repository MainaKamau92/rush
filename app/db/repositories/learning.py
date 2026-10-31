import sqlite3
from contextlib import AbstractAsyncContextManager
from pathlib import Path

import aiosqlite
from pydantic import ValidationError

from app.core.errors import ReviewConflictError, StateError
from app.db.repositories.connection import connect
from app.schemas.learning import LearningProposal
from app.schemas.policy import Rule


class SQLiteLearningRepository:
    def __init__(self, database: Path) -> None:
        self._database = database

    def _connect(self) -> AbstractAsyncContextManager[aiosqlite.Connection]:
        return connect(
            self._database,
            "Cannot access team learning; check state and run rush migrate",
        )

    async def save(
        self,
        proposal: LearningProposal,
        previous: LearningProposal | None = None,
        rule: Rule | None = None,
    ) -> None:
        text = proposal.model_dump_json()
        async with self._connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            try:
                await self._write(connection, proposal, previous, text)
                await connection.execute(
                    "INSERT INTO learning_revisions (proposal_id, revision, "
                    "content_sha256, proposal_json) VALUES (?, ?, ?, ?)",
                    (proposal.id, proposal.revision, proposal.content_sha256, text),
                )
                if rule is not None:
                    await connection.execute(
                        "INSERT INTO learned_rules (rule_id, version, proposal_id, "
                        "content_sha256, rule_json, approved_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            rule.id,
                            rule.version,
                            proposal.id,
                            proposal.content_sha256,
                            rule.model_dump_json(),
                            proposal.updated_at.isoformat(),
                        ),
                    )
            except sqlite3.IntegrityError as exc:
                await connection.rollback()
                raise ReviewConflictError(
                    "Another proposal or active rule already uses that ID"
                ) from exc
            await connection.commit()

    @staticmethod
    async def _write(
        connection: aiosqlite.Connection,
        proposal: LearningProposal,
        previous: LearningProposal | None,
        text: str,
    ) -> None:
        if previous is None:
            await connection.execute(
                "INSERT INTO learning_proposals (proposal_id, rule_id, revision, "
                "content_sha256, status, proposal_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    proposal.id,
                    proposal.draft.rule_id,
                    proposal.revision,
                    proposal.content_sha256,
                    proposal.status,
                    text,
                    proposal.updated_at.isoformat(),
                ),
            )
            return
        # Only the version that was read may be replaced, so concurrent changes
        # can't silently undo a revision or an approval.
        async with connection.execute(
            "UPDATE learning_proposals SET revision = ?, content_sha256 = ?, "
            "status = ?, proposal_json = ?, updated_at = ? WHERE proposal_id = ? "
            "AND revision = ? AND status = ? AND content_sha256 = ?",
            (
                proposal.revision,
                proposal.content_sha256,
                proposal.status,
                text,
                proposal.updated_at.isoformat(),
                previous.id,
                previous.revision,
                previous.status,
                previous.content_sha256,
            ),
        ) as cursor:
            changed = cursor.rowcount
        if changed != 1:
            await connection.rollback()
            raise ReviewConflictError(
                "The proposal changed meanwhile; inspect it again"
            )

    async def get(self, proposal_id: str) -> LearningProposal | None:
        async with (
            self._connect() as connection,
            connection.execute(
                "SELECT proposal_json FROM learning_proposals WHERE proposal_id = ?",
                (proposal_id,),
            ) as cursor,
        ):
            row = await cursor.fetchone()
        return None if row is None else _proposal(str(row[0]))

    async def proposals(self) -> tuple[LearningProposal, ...]:
        async with (
            self._connect() as connection,
            connection.execute(
                "SELECT proposal_json FROM learning_proposals ORDER BY rowid"
            ) as cursor,
        ):
            rows = await cursor.fetchall()
        return tuple(_proposal(str(row[0])) for row in rows)

    async def rules(self) -> tuple[Rule, ...]:
        async with (
            self._connect() as connection,
            connection.execute(
                "SELECT rule_json FROM learned_rules ORDER BY rule_id, version"
            ) as cursor,
        ):
            rows = await cursor.fetchall()
        try:
            return tuple(Rule.model_validate_json(str(row[0])) for row in rows)
        except ValidationError as exc:
            raise StateError("A stored learned rule is invalid") from exc


def _proposal(text: str) -> LearningProposal:
    try:
        return LearningProposal.model_validate_json(text)
    except ValidationError as exc:
        raise StateError("A stored learning proposal is invalid") from exc
