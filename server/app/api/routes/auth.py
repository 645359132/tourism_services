"""Login, refresh rotation, and logout endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.auth import AuthTokenResponse, LoginRequest, RefreshTokenRequest, UserResponse
from app.services.auth import (
    AuthResult,
    authenticate_and_issue,
    logout_refresh_family,
    rotate_refresh_token,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


def _token_response(result: AuthResult) -> AuthTokenResponse:
    return AuthTokenResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        token_type="bearer",
        expires_in=result.expires_in,
        user=UserResponse.from_user(result.user),
    )


@router.post("/login", response_model=AuthTokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthTokenResponse:
    result = await authenticate_and_issue(
        session,
        username=payload.username,
        password=payload.password,
        settings=request.app.state.settings,
    )
    return _token_response(result)


@router.post("/refresh", response_model=AuthTokenResponse)
async def refresh(
    payload: RefreshTokenRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthTokenResponse:
    result = await rotate_refresh_token(
        session,
        refresh_token=payload.refresh_token,
        settings=request.app.state.settings,
    )
    return _token_response(result)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: RefreshTokenRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    await logout_refresh_family(
        session,
        refresh_token=payload.refresh_token,
        settings=request.app.state.settings,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
