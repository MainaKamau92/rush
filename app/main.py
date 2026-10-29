from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.settings import Settings
from app.dependencies import build_system
from app.routers.health import router


def create_app(settings: Settings | None = None) -> FastAPI:
    configured = settings if settings is not None else Settings()  # type: ignore[call-arg]
    system = build_system(configured)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        await system.start()
        application.state.system = system
        try:
            yield
        finally:
            await system.stop()

    application = FastAPI(title="rush", lifespan=lifespan)
    application.include_router(router)
    return application
