from fastapi import APIRouter

from benmo_backend.api import (
    admin,
    analyses,
    chains,
    edges,
    events,
    evidence,
    health,
    internal,
    public,
    verification,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(analyses.router, prefix="/v1")
api_router.include_router(events.router, prefix="/v1")
api_router.include_router(chains.router, prefix="/v1")
api_router.include_router(edges.router, prefix="/v1")
api_router.include_router(evidence.router, prefix="/v1")
api_router.include_router(verification.router, prefix="/v1")
api_router.include_router(public.router, prefix="/v1")
api_router.include_router(admin.router, prefix="/v1")
api_router.include_router(internal.router, prefix="/v1")
