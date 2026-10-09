from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from benmo_backend import __version__
from benmo_backend.api.router import api_router
from benmo_backend.config import Settings, get_settings
from benmo_backend.db import Base, create_engine, create_session_factory
from benmo_backend.errors import AppError
from benmo_backend.queueing.base import TaskQueue
from benmo_backend.queueing.factory import build_task_queue


def create_app(settings: Settings | None = None, task_queue: TaskQueue | None = None) -> FastAPI:
    runtime_settings = settings or get_settings()
    logging.basicConfig(
        level=getattr(logging, runtime_settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    engine = create_engine(runtime_settings)
    session_factory = create_session_factory(engine)
    queue = task_queue or build_task_queue(runtime_settings, session_factory)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if runtime_settings.auto_create_schema:
            # Local/test convenience only; production startup uses Alembic.
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
        yield
        await queue.close()
        await engine.dispose()

    app = FastAPI(
        title=runtime_settings.app_name,
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if runtime_settings.environment != "production" else None,
        redoc_url=None,
    )
    app.state.settings = runtime_settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.task_queue = queue

    app.add_middleware(
        CORSMiddleware,
        allow_origins=runtime_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Idempotency-Key", "Last-Event-ID", "X-Admin-Key"],
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed.",
                    "details": {"errors": exc.errors()},
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )

    app.include_router(api_router)
    return app


app = create_app()
