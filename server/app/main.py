"""FastAPI application factory and development entry point."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.db.session import dispose_database


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_database()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an independently configurable FastAPI application."""

    resolved_settings = settings or get_settings()
    configure_logging(
        resolved_settings.log_level,
        json_logs=resolved_settings.log_json,
    )

    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        debug=resolved_settings.debug,
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings

    register_exception_handlers(application)
    application.add_middleware(RequestContextMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=resolved_settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(api_router)
    return application


app = create_app()


def run() -> None:
    """Run the local development server through the project script."""

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug and settings.app_env == "development",
    )


if __name__ == "__main__":
    run()
