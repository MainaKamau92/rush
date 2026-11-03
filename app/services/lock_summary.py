import json
import re
from typing import Any
from urllib.parse import urlsplit

MAX_LINES = 200
MAX_FIELD = 100
CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def _clean(value: object) -> str:
    # Lockfile text is untrusted: keep each field on one bounded line.
    text = CONTROL.sub(" ", str(value)).strip()
    return text if len(text) <= MAX_FIELD else text[: MAX_FIELD - 1] + "…"


def _packages(content: bytes | None) -> dict[str, dict[str, Any]] | None:
    if content is None:
        return {}
    try:
        data = json.loads(content)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    packages = data.get("packages") if isinstance(data, dict) else None
    if not isinstance(packages, dict):
        return None
    return {
        _clean(
            name.removeprefix("node_modules/").replace("/node_modules/", " > ")
        ): item
        for name, item in packages.items()
        if name and isinstance(item, dict)
    }


def _describe(item: dict[str, Any]) -> str:
    parts = [_clean(item.get("version", "?"))]
    resolved = str(item.get("resolved", ""))
    host = urlsplit(resolved).hostname if "://" in resolved else None
    if host and host != "registry.npmjs.org":
        parts.append(f"from {_clean(host)}")
    elif resolved and not host:
        parts.append(f"from {_clean(resolved)}")
    if "integrity" not in item and resolved:
        parts.append("no integrity hash")
    if item.get("dev"):
        parts.append("dev")
    if item.get("hasInstallScript"):
        parts.append("runs an install script")
    engines = item.get("engines")
    if isinstance(engines, dict) and "node" in engines:
        parts.append(f"node {_clean(engines['node'])}")
    return ", ".join(parts)


def summarize_package_lock(
    path: str, old: bytes | None, new: bytes | None
) -> str | None:
    """
    A package-level summary of an npm lockfile change, so the model sees what a
    regenerated lock adds or changes without its full diff. None if unreadable.
    """
    before, after = _packages(old), _packages(new)
    if before is None or after is None:
        return None
    lines = []
    for name in sorted(before.keys() | after.keys()):
        if name not in before:
            lines.append(f"+ {name} {_describe(after[name])}")
        elif name not in after:
            lines.append(f"- {name} {_describe(before[name])}")
        elif _describe(before[name]) != _describe(after[name]):
            lines.append(
                f"~ {name} {_describe(before[name])} -> {_describe(after[name])}"
            )
        elif before[name].get("integrity") != after[name].get("integrity"):
            lines.append(f"~ {name} {_describe(after[name])}, integrity hash changed")
    if not lines:
        return None
    shown = lines[:MAX_LINES]
    if len(lines) > MAX_LINES:
        shown.append(f"... {len(lines) - MAX_LINES} more package changes not shown")
    header = (
        f"Package changes in {_clean(path)}, summarized by rush because the "
        "lockfile itself is not shown (+ added, - removed, ~ changed):"
    )
    return "\n".join([header, *shown])
