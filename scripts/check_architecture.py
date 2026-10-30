import ast
import sys
from pathlib import Path

REQUIRED = (
    "app/main.py",
    "app/dependencies.py",
    "app/cli.py",
    "app/services/ports.py",
    "app/provider/model/abstract.py",
    "app/provider/model/base.py",
    "app/provider/repository/abstract.py",
    "app/provider/repository/base.py",
    "app/routers",
    "app/internal/adapters",
    "app/core",
    "app/models",
    "app/schemas",
    "app/services",
    "app/db/repositories",
    "app/db/migrations",
    "tests/unit",
    "tests/integration",
    "tests/e2e",
    "tests/fixtures",
    "skills",
    "scripts",
    "docs",
)
INFRASTRUCTURE = (
    "app.db",
    "app.internal",
    "app.provider.model.base",
    "app.provider.source.base",
    "app.provider.repository.base",
    "app.provider.skills.base",
    "app.dependencies",
    "app.routers",
    "fastapi",
    "httpx",
    "httpx2",
    "mcp",
    "aiosqlite",
    "sqlite3",
    "subprocess",
    "uvicorn",
)
ROUTER_FORBIDDEN = (
    "app.db",
    "app.internal",
    "app.provider",
    "httpx",
    "httpx2",
    "mcp",
    "aiosqlite",
    "sqlite3",
    "urllib",
)


def imports(path: Path, root: Path) -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    parts = path.relative_to(root).with_suffix("").parts
    package = parts[:-1]
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            result.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                base = ".".join(
                    (*package[: len(package) - node.level + 1], base)
                ).strip(".")
            result.append((node.lineno, base))
            result.extend((node.lineno, f"{base}.{alias.name}") for alias in node.names)
    return result


def check(root: Path) -> list[str]:
    errors = [
        f"Missing required path: {name}"
        for name in REQUIRED
        if not (root / name).exists()
    ]
    for path in (root / "app").rglob("*.py"):
        relative = path.relative_to(root).as_posix()
        forbidden: tuple[str, ...] = ()
        if relative.startswith(("app/services/", "app/models/")):
            forbidden = INFRASTRUCTURE
        elif relative.startswith("app/routers/") or relative == "app/cli.py":
            forbidden = ROUTER_FORBIDDEN
        for line, module in imports(path, root):
            if any(
                module == item or module.startswith(item + ".") for item in forbidden
            ):
                errors.append(f"{relative}:{line}: forbidden import {module}")
    return errors


def main() -> int:
    errors = check(Path.cwd())
    print("\n".join(errors) if errors else "Architecture checks passed")
    return int(bool(errors))


if __name__ == "__main__":
    sys.exit(main())
