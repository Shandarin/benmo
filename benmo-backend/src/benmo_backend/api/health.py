from fastapi import APIRouter, Request

from benmo_backend import __version__
from benmo_backend.db import check_database
from benmo_backend.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
@router.get("/health/live", response_model=HealthResponse)
async def live(request: Request) -> HealthResponse:
    return HealthResponse(
        status="ok", service=request.app.state.settings.app_name, version=__version__
    )


@router.get("/health/ready", response_model=HealthResponse)
async def ready(request: Request) -> HealthResponse:
    try:
        await check_database(request.app.state.engine)
    except Exception:
        return HealthResponse(
            status="degraded",
            service=request.app.state.settings.app_name,
            version=__version__,
            database="unavailable",
        )
    return HealthResponse(
        status="ok",
        service=request.app.state.settings.app_name,
        version=__version__,
        database="ok",
    )
