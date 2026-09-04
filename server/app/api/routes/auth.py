"""Registration, login, refresh rotation, and logout endpoints."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.auth import (
    AuthTokenResponse,
    LoginRequest,
    RefreshTokenRequest,
    RegisterRequest,
    UserResponse,
)
from app.services.auth import (
    AuthResult,
    authenticate_and_issue,
    logout_refresh_family,
    register_tourist_and_issue,
    rotate_refresh_token,
)


class SensitiveInputRoute(APIRoute):
    """Keep submitted credentials out of validation error responses."""

    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        original_handler = super().get_route_handler()

        async def sanitized_handler(request: Request) -> Response:
            try:
                return await original_handler(request)
            except RequestValidationError as exc:
                sanitized_errors = [
                    {key: value for key, value in error.items() if key != "input"}
                    for error in exc.errors()
                ]
                raise RequestValidationError(sanitized_errors) from exc

        return sanitized_handler


router = APIRouter(
    prefix="/auth",
    tags=["authentication"],
    route_class=SensitiveInputRoute,
)


def _token_response(result: AuthResult) -> AuthTokenResponse:
    return AuthTokenResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        token_type="bearer",
        expires_in=result.expires_in,
        user=UserResponse.from_user(result.user),
    )


@router.post(
    "/register",
    response_model=AuthTokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    payload: RegisterRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthTokenResponse:
    result = await register_tourist_and_issue(
        session,
        username=payload.username,
        display_name=payload.display_name,
        password=payload.password,
        settings=request.app.state.settings,
    )
    return _token_response(result)


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
