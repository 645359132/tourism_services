"""Authentication use cases with refresh-family replay protection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import jwt
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    password_needs_rehash,
    verify_password,
)
from app.db.models.refresh_session import RefreshSession
from app.db.models.role import UserRole
from app.db.models.user import User

DUMMY_PASSWORD_HASH = hash_password("not-a-real-user-password")


@dataclass(frozen=True, slots=True)
class AuthResult:
    access_token: str
    refresh_token: str
    expires_in: int
    user: User


def authentication_error(
    code: str = "INVALID_CREDENTIALS",
    message: str = "Invalid username or password",
) -> AppError:
    return AppError(
        status_code=401,
        code=code,
        message=message,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _user_statement():
    return select(User).options(selectinload(User.role_links).selectinload(UserRole.role))


async def get_user_by_id(session: AsyncSession, user_id: UUID) -> User | None:
    return await session.scalar(_user_statement().where(User.id == user_id))


async def authenticate_and_issue(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    settings: Settings,
) -> AuthResult:
    user = await session.scalar(_user_statement().where(User.username == username))
    encoded_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
    password_valid = verify_password(password, encoded_hash)

    if user is None or not password_valid or not user.is_active:
        raise authentication_error()

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    family_id = uuid4()
    session_id = uuid4()
    refresh_token, refresh_expires_at, refresh_jti = create_refresh_token(
        user_id=user.id,
        session_id=session_id,
        family_id=family_id,
        settings=settings,
    )
    session.add(
        RefreshSession(
            id=session_id,
            family_id=family_id,
            user_id=user.id,
            token_jti=refresh_jti,
            expires_at=refresh_expires_at,
        )
    )
    access_token, expires_in = create_access_token(user.id, user.role_names, settings)
    await session.commit()
    return AuthResult(access_token, refresh_token, expires_in, user)


def _parse_refresh_claims(claims: dict[str, object]) -> tuple[UUID, UUID, UUID, str]:
    try:
        user_id = UUID(str(claims["sub"]))
        session_id = UUID(str(claims["sid"]))
        family_id = UUID(str(claims["fid"]))
        jti = str(claims["jti"])
    except (KeyError, TypeError, ValueError) as exc:
        raise authentication_error(
            "INVALID_REFRESH_TOKEN",
            "Invalid refresh token",
        ) from exc
    if not jti or len(jti) > 64:
        raise authentication_error("INVALID_REFRESH_TOKEN", "Invalid refresh token")
    return user_id, session_id, family_id, jti


async def _revoke_family(
    session: AsyncSession,
    *,
    family_id: UUID,
    user_id: UUID,
    reason: str,
) -> None:
    await session.execute(
        update(RefreshSession)
        .where(
            RefreshSession.family_id == family_id,
            RefreshSession.user_id == user_id,
            RefreshSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC), revocation_reason=reason)
    )


async def rotate_refresh_token(
    session: AsyncSession,
    *,
    refresh_token: str,
    settings: Settings,
) -> AuthResult:
    try:
        claims = decode_token(
            refresh_token,
            expected_type="refresh",
            settings=settings,
        )
    except jwt.InvalidTokenError as exc:
        raise authentication_error(
            "INVALID_REFRESH_TOKEN",
            "Invalid refresh token",
        ) from exc

    user_id, current_session_id, family_id, current_jti = _parse_refresh_claims(claims)
    now = datetime.now(UTC)
    next_session_id = uuid4()
    next_refresh_token, next_expires_at, next_jti = create_refresh_token(
        user_id=user_id,
        session_id=next_session_id,
        family_id=family_id,
        settings=settings,
    )

    consume_result = await session.execute(
        update(RefreshSession)
        .where(
            RefreshSession.id == current_session_id,
            RefreshSession.family_id == family_id,
            RefreshSession.user_id == user_id,
            RefreshSession.token_jti == current_jti,
            RefreshSession.consumed_at.is_(None),
            RefreshSession.revoked_at.is_(None),
            RefreshSession.expires_at > now,
        )
        .values(consumed_at=now, replaced_by_jti=next_jti)
    )
    if consume_result.rowcount != 1:
        await session.rollback()
        existing = await session.get(RefreshSession, current_session_id)
        if existing is not None:
            await _revoke_family(
                session,
                family_id=existing.family_id,
                user_id=existing.user_id,
                reason="replay_detected",
            )
            await session.commit()
            raise authentication_error(
                "REFRESH_TOKEN_REUSED",
                "Refresh token reuse detected",
            )
        raise authentication_error("INVALID_REFRESH_TOKEN", "Invalid refresh token")

    user = await get_user_by_id(session, user_id)
    if user is None or not user.is_active:
        await _revoke_family(
            session,
            family_id=family_id,
            user_id=user_id,
            reason="account_unavailable",
        )
        await session.commit()
        raise authentication_error("INVALID_REFRESH_TOKEN", "Invalid refresh token")

    session.add(
        RefreshSession(
            id=next_session_id,
            family_id=family_id,
            user_id=user_id,
            parent_session_id=current_session_id,
            token_jti=next_jti,
            expires_at=next_expires_at,
        )
    )
    access_token, expires_in = create_access_token(user.id, user.role_names, settings)
    await session.commit()
    return AuthResult(access_token, next_refresh_token, expires_in, user)


async def logout_refresh_family(
    session: AsyncSession,
    *,
    refresh_token: str,
    settings: Settings,
) -> None:
    """Idempotently revoke a valid signed token family without token oracles."""

    try:
        claims = decode_token(
            refresh_token,
            expected_type="refresh",
            settings=settings,
            verify_expiration=False,
        )
        user_id, _, family_id, _ = _parse_refresh_claims(claims)
    except (AppError, jwt.InvalidTokenError):
        return

    await _revoke_family(
        session,
        family_id=family_id,
        user_id=user_id,
        reason="logout",
    )
    await session.commit()
