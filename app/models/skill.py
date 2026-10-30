from dataclasses import dataclass


@dataclass(frozen=True)
class PackageFile:
    name: str
    content: bytes
    regular: bool
    executable: bool
