from fastapi import Request

from app.core.settings import Settings
from app.db.migrate import migration_files
from app.db.repositories.state import SQLiteStateRepository
from app.services.system import SystemService


def build_system(settings: Settings) -> SystemService:
    return SystemService(
        SQLiteStateRepository(settings.database_path), len(migration_files())
    )


def get_system(request: Request) -> SystemService:
    service: SystemService = request.app.state.system
    return service
