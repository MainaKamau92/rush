"""Public errors contain safe explanations, never provider payloads."""


class StateError(Exception):
    """Persistent state is unavailable or incompatible with this release."""
