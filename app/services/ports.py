"""Capabilities required by setup services; implementations own their resources."""

from pathlib import Path
from typing import Protocol


class StateRepository(Protocol):
    """Errors use StateError; cancellation propagates to the caller."""

    async def open(self) -> None: ...

    async def close(self) -> None: ...

    async def schema_version(self) -> int: ...

    async def migrate(self) -> int: ...

    async def backup(self, destination: Path) -> None: ...
