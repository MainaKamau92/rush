from dataclasses import dataclass


@dataclass(frozen=True)
class Health:
    ready: bool
    schema_version: int
