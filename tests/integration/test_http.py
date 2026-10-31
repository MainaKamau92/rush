import pytest
from fastapi.testclient import TestClient

from app.core.errors import StateError
from app.core.settings import Settings
from app.dependencies import get_system
from app.main import create_app


def test_startup_never_creates_or_migrates_missing_database(settings: Settings) -> None:
    with (
        pytest.raises(StateError, match="not initialized"),
        TestClient(create_app(settings)),
    ):
        pass
    assert not settings.database_path.exists()


def test_health_and_restart_use_existing_state(initialized: Settings) -> None:
    for _ in range(2):
        with TestClient(create_app(initialized)) as client:
            response = client.get("/health")
            assert response.status_code == 200
            assert response.json() == {
                "name": "rush",
                "status": "ready",
                "schema_version": 5,
            }


def test_factory_loads_explicit_environment_configuration(
    initialized: Settings,
) -> None:
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200


def test_state_failure_is_unavailable_without_disclosing_details(
    initialized: Settings,
) -> None:
    class Unavailable:
        async def health(self) -> None:
            raise StateError("private source value")

    application = create_app(initialized)
    application.dependency_overrides[get_system] = Unavailable
    with TestClient(application) as client:
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"detail": "State unavailable"}
