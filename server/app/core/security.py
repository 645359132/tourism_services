"""Argon2id password hashing and strictly validated JWT primitives."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings

TokenType = Literal["access", "refresh", "ticket_qr", "ticket_quote"]

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
    token_type: TokenType,
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


def create_ticket_qr(
    *,
    ticket_id: UUID,
    ticket_version: int,
    slot_id: UUID,
    settings: Settings,
) -> tuple[str, datetime]:
    token, expires_at, _ = _encode_token(
        subject=ticket_id,
        token_type="ticket_qr",
        expires_delta=timedelta(seconds=settings.ticket_qr_ttl_seconds),
        settings=settings,
        extra_claims={
            "purpose": "gate_validation",
            "sid": str(slot_id),
            "ver": ticket_version,
        },
    )
    return token, expires_at


def create_ticket_quote(
    *,
    slot_id: UUID,
    quantity: int,
    unit_price_cents: int,
    settings: Settings,
) -> tuple[str, datetime, str]:
    """Sign a short-lived price promise without persisting a quote table."""

    return _encode_token(
        subject=slot_id,
        token_type="ticket_quote",
        expires_delta=timedelta(seconds=settings.ticket_quote_ttl_seconds),
        settings=settings,
        extra_claims={
            "purpose": "ticket_purchase",
            "quantity": quantity,
            "unit_price_cents": unit_price_cents,
        },
    )


def decode_token(
    token: str,
    *,
    expected_type: TokenType,
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
