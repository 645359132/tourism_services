"""Access-token authentication and role authorization dependencies."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any
from uuid import UUID

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import decode_token
from app.db.models.user import User
from app.db.session import get_session
from app.services.auth import authentication_error, get_user_by_id

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise authentication_error("NOT_AUTHENTICATED", "Authentication required")

    try:
        claims = decode_token(
            credentials.credentials,
            expected_type="access",
            settings=request.app.state.settings,
        )
        user_id = UUID(str(claims["sub"]))
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise authentication_error("INVALID_ACCESS_TOKEN", "Invalid access token") from exc

    user = await get_user_by_id(session, user_id)
    if user is None or not user.is_active:
        raise authentication_error("INVALID_ACCESS_TOKEN", "Invalid access token")
    return user


RoleDependency = Callable[..., Coroutine[Any, Any, User]]


def require_roles(*allowed_roles: str) -> RoleDependency:
    """Require any listed role; the admin role is an explicit superuser bypass."""

    allowed = frozenset(allowed_roles)
    if not allowed:
        raise ValueError("At least one role is required")

    async def dependency(
        user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        roles = set(user.role_names)
        if "admin" not in roles and roles.isdisjoint(allowed):
            raise AppError(
                status_code=403,
                code="FORBIDDEN",
                message="Insufficient permissions",
            )
        return user

    return dependency


require_tourist = require_roles("tourist")
require_merchant = require_roles("merchant")
require_support = require_roles("support")
require_admin = require_roles("admin")
