import httpx
from fastapi import Request

from app.core.errors import ModelError
from app.core.settings import Settings
from app.db.migrate import migration_files
from app.db.repositories.state import SQLiteStateRepository
from app.internal.adapters.meta import MetaModelProvider
from app.services.model_access import ModelAccessService
from app.services.system import SystemService


def build_system(settings: Settings) -> SystemService:
    return SystemService(
        SQLiteStateRepository(settings.database_path), len(migration_files())
    )


def build_model_access(settings: Settings) -> ModelAccessService:
    if settings.meta_api_key is None or not settings.meta_api_key.get_secret_value():
        raise ModelError("Set META_AI_KEY before checking model access")
    client = httpx.AsyncClient(
        base_url=settings.meta_base_url + "/",
        headers={"Authorization": f"Bearer {settings.meta_api_key.get_secret_value()}"},
        timeout=settings.model_timeout_seconds,
        follow_redirects=False,
        trust_env=False,
    )
    return ModelAccessService(MetaModelProvider(client), settings.model_timeout_seconds)


def get_system(request: Request) -> SystemService:
    service: SystemService = request.app.state.system
    return service
