"""Argon2id password hashing and strictly validated JWT primitives."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings

password_hasher = PasswordHasher(
    time_cost=2,
    memory_cost=19_456,
    parallelism=1,
    hash_len=32,
    salt_len=16,
)


def hash_password(password: str) -> str:
    """Hash a password with Argon2id and a fresh random salt."""

    return password_hasher.hash(password)


def verify_password(password: str, encoded_hash: str) -> bool:
    """Verify without leaking malformed hashes as application errors."""

    try:
        return password_hasher.verify(encoded_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def password_needs_rehash(encoded_hash: str) -> bool:
    try:
        return password_hasher.check_needs_rehash(encoded_hash)
    except InvalidHashError:
        return True


def _encode_token(
    *,
    subject: UUID,
    token_type: Literal["access", "refresh"],
    expires_delta: timedelta,
    settings: Settings,
    extra_claims: dict[str, Any] | None = None,
) -> tuple[str, datetime, str]:
    now = datetime.now(UTC)
    expires_at = now + expires_delta
    jti = uuid4().hex
    claims: dict[str, Any] = {
        "sub": str(subject),
        "jti": jti,
        "type": token_type,
        "iat": now,
        "exp": expires_at,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    if extra_claims:
        claims.update(extra_claims)
    token = jwt.encode(
        claims,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return token, expires_at, jti


def create_access_token(
    user_id: UUID,
    roles: list[str],
    settings: Settings,
) -> tuple[str, int]:
    expires_in = settings.jwt_access_token_expire_minutes * 60
    token, _, _ = _encode_token(
        subject=user_id,
        token_type="access",
        expires_delta=timedelta(seconds=expires_in),
        settings=settings,
        extra_claims={"roles": roles},
    )
    return token, expires_in


def create_refresh_token(
    *,
    user_id: UUID,
    session_id: UUID,
    family_id: UUID,
    settings: Settings,
) -> tuple[str, datetime, str]:
    return _encode_token(
        subject=user_id,
        token_type="refresh",
        expires_delta=timedelta(days=settings.jwt_refresh_token_expire_days),
        settings=settings,
        extra_claims={"sid": str(session_id), "fid": str(family_id)},
    )


def decode_token(
    token: str,
    *,
    expected_type: Literal["access", "refresh"],
    settings: Settings,
    verify_expiration: bool = True,
) -> dict[str, Any]:
    """Decode only the configured algorithm, issuer, audience, and token type."""

    claims = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
        options={
            "require": ["sub", "jti", "type", "iat", "exp", "iss", "aud"],
            "verify_exp": verify_expiration,
        },
    )
    if claims.get("type") != expected_type:
        raise jwt.InvalidTokenError("Unexpected token type")
    return claims
