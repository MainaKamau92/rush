from pathlib import Path

import pytest

from scripts.check_architecture import REQUIRED, check
from scripts.check_conventions import validate


@pytest.fixture
def layout(tmp_path: Path) -> Path:
    for name in REQUIRED:
        path = tmp_path / name
        if path.suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        else:
            path.mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.mark.parametrize(
    "code", ["import sqlite3", "from ..db import repositories", "from app import db"]
)
def test_router_cannot_query_database(layout: Path, code: str) -> None:
    (layout / "app/routers/unsafe.py").write_text(code)
    assert any("forbidden import" in item for item in check(layout))


@pytest.mark.parametrize(
    "code", ["import httpx", "from app.internal.adapters import model"]
)
def test_service_cannot_import_vendor_client(layout: Path, code: str) -> None:
    (layout / "app/services/unsafe.py").write_text(code)
    assert any("forbidden import" in item for item in check(layout))


def test_dependency_assembly_and_pure_routes_are_allowed(layout: Path) -> None:
    (layout / "app/dependencies.py").write_text("from app.db import repositories")
    (layout / "app/routers/safe.py").write_text(
        "from app.dependencies import build_system"
    )
    assert check(layout) == []
    (layout / "app/main.py").unlink()
    assert "Missing required path: app/main.py" in check(layout)


def test_pr_metadata_is_checked_without_evaluating_its_contents() -> None:
    body = "\n".join(
        f"## {name}\nDetails"
        for name in (
            "Description",
            "Type of change",
            "How this was tested",
            "Checklist",
            "Ticket",
        )
    )
    assert validate("task/TCR-001-project-setup", "[TCR-001] Set up rush", body) == []
    assert validate("main", "Set up rush", "")
    assert validate("task/TCR-001-project-setup", "[TCR-002] Wrong ticket", body)
