import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.settings import Settings
from app.dependencies import build_github_reviews, build_system
from app.routers import github, health


def create_app(settings: Settings | None = None) -> FastAPI:
    configured = settings if settings is not None else Settings()  # type: ignore[call-arg]
    system = build_system(configured)
    reviews = build_github_reviews(configured) if configured.github_enabled else None

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        await system.start()
        application.state.system = system
        application.state.github = reviews
        worker = asyncio.create_task(reviews.worker.run()) if reviews else None
        try:
            yield
        finally:
            try:
                if reviews is not None and worker is not None:
                    worker.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await worker
                    await reviews.worker.close()
            finally:
                await system.stop()

    application = FastAPI(title="rush", lifespan=lifespan)
    application.include_router(health.router)
    application.include_router(github.router)
    return application
