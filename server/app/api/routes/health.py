"""Service liveness endpoint."""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.core.config import Settings

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str
    environment: str


@router.get("/health", response_model=HealthResponse, summary="Check service liveness")
async def health(request: Request) -> HealthResponse:
    settings: Settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.app_env,
    )
