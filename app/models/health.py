from dataclasses import dataclass


@dataclass(frozen=True)
class Health:
    """
    Readiness requires a reachable database at the expected schema.
    """

    ready: bool
    schema_version: int
