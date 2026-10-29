import asyncio
from pathlib import Path

import pytest

from app.core.errors import StateError
from app.services.system import SystemService


class ControlledState:
    def __init__(self, version: int = 1) -> None:
        self.version = version
        self.opened = False
        self.cancel = False

    async def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.opened = False

    async def schema_version(self) -> int:
        if self.cancel:
            raise asyncio.CancelledError
        return self.version

    async def migrate(self) -> int:
        return self.version

    async def backup(self, destination: Path) -> None:
        raise StateError("Storage unavailable")


async def test_start_requires_compatible_state_and_closes_on_failure() -> None:
    state = ControlledState(version=2)
    service = SystemService(state, expected_version=1)
    with pytest.raises(StateError, match="Schema"):
        await service.start()
    assert not state.opened


async def test_cancellation_is_not_converted_to_success_and_closes_state() -> None:
    state = ControlledState()
    state.cancel = True
    with pytest.raises(asyncio.CancelledError):
        await SystemService(state, 1).start()
    assert not state.opened


async def test_successful_start_reports_readiness_and_stop_closes_state() -> None:
    state = ControlledState()
    service = SystemService(state, 1)
    await service.start()
    assert state.opened
    health = await service.health()
    assert health.ready and health.schema_version == 1
    await service.stop()
    assert not state.opened
