"""Startup, readiness, and explicit maintenance workflows."""

from pathlib import Path

from app.core.errors import StateError
from app.models.health import Health
from app.services.ports import StateRepository


class SystemService:
    """Share startup and maintenance decisions between HTTP and CLI."""

    def __init__(self, state: StateRepository, expected_version: int) -> None:
        self._state = state
        self._expected_version = expected_version

    async def start(self) -> None:
        await self._state.open()
        try:
            await self.health()
        except BaseException:
            await self._state.close()
            raise

    async def stop(self) -> None:
        await self._state.close()

    async def health(self) -> Health:
        version = await self._state.schema_version()
        if version != self._expected_version:
            raise StateError("Schema does not match this release; run rush migrate")
        return Health(ready=True, schema_version=version)

    async def migrate(self) -> int:
        return await self._state.migrate()

    async def backup(self, destination: Path) -> None:
        await self._state.backup(destination)
