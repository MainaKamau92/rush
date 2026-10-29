from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.core.errors import StateError
from app.dependencies import get_system
from app.schemas.health import HealthResponse
from app.services.system import SystemService

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(
    system: Annotated[SystemService, Depends(get_system)],
) -> HealthResponse:
    try:
        result = await system.health()
    except StateError as exc:
        raise HTTPException(status_code=503, detail="State unavailable") from exc
    return HealthResponse(schema_version=result.schema_version)
