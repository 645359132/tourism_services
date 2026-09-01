"""Atomic point accounts, immutable ledgers, rewards, redemption, and sharing."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models.commerce import (
    ContentShare,
    PointAccount,
    PointLedgerEntry,
    Product,
    Redemption,
    Reward,
)
from app.db.models.user import User
from app.providers.share import DemoShareVerifier
from app.schemas.commerce import (
    PointAccountResponse,
    PointLedgerResponse,
    RedemptionResponse,
    RewardResponse,
    ShareResponse,
)


def _error(status_code: int, code: str, message: str) -> AppError:
    return AppError(status_code=status_code, code=code, message=message)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _hash_payload(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode()).hexdigest()


async def ensure_point_account(session: AsyncSession, user_id: UUID) -> PointAccount:
    bind = session.get_bind()
    values = {"user_id": user_id, "balance": 0, "version": 1}
    if bind.dialect.name == "sqlite":
        await session.execute(sqlite_insert(PointAccount).values(**values).on_conflict_do_nothing())
    elif bind.dialect.name == "postgresql":
        await session.execute(
            postgresql_insert(PointAccount)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[PointAccount.user_id])
        )
    elif await session.get(PointAccount, user_id) is None:
        session.add(PointAccount(**values))
        await session.flush()
    account = await session.get(PointAccount, user_id, populate_existing=True)
    assert account is not None
    return account


async def _lock_point_account(session: AsyncSession, user_id: UUID) -> PointAccount:
    await ensure_point_account(session, user_id)
    locked = await session.execute(
        update(PointAccount)
        .execution_options(synchronize_session=False)
        .where(PointAccount.user_id == user_id)
        .values(version=PointAccount.version + 1)
    )
    if locked.rowcount != 1:
        raise RuntimeError("Point account lock could not be acquired")
    account = await session.get(PointAccount, user_id, populate_existing=True)
    assert account is not None
    return account


async def award_points(
    session: AsyncSession,
    *,
    user_id: UUID,
    points: int,
    source_type: str,
    source_id: UUID,
    description: str,
) -> PointLedgerEntry:
    if points <= 0:
        raise ValueError("Award points must be positive")
    await _lock_point_account(session, user_id)
    existing = await session.scalar(
        select(PointLedgerEntry).where(
            PointLedgerEntry.user_id == user_id,
            PointLedgerEntry.source_type == source_type,
            PointLedgerEntry.source_id == source_id,
            PointLedgerEntry.entry_type == "EARN",
        )
    )
    if existing is not None:
        return existing
    result = await session.execute(
        update(PointAccount)
        .execution_options(synchronize_session=False)
        .where(PointAccount.user_id == user_id)
        .values(
            balance=PointAccount.balance + points,
            updated_at=datetime.now(UTC),
        )
        .returning(PointAccount.balance)
    )
    balance_after = result.scalar_one()
    ledger = PointLedgerEntry(
        user_id=user_id,
        entry_type="EARN",
        delta=points,
        balance_after=balance_after,
        source_type=source_type,
        source_id=source_id,
        description=description,
    )
    session.add(ledger)
    await session.flush()
    return ledger


async def point_account_response(
    session: AsyncSession,
    *,
    user_id: UUID,
) -> PointAccountResponse:
    account = await ensure_point_account(session, user_id)
    lifetime_earned = int(
        await session.scalar(
            select(func.coalesce(func.sum(PointLedgerEntry.delta), 0)).where(
                PointLedgerEntry.user_id == user_id,
                PointLedgerEntry.delta > 0,
            )
        )
        or 0
    )
    lifetime_spent = int(
        await session.scalar(
            select(
                func.coalesce(
                    func.sum(
                        case(
                            (PointLedgerEntry.delta < 0, -PointLedgerEntry.delta),
                            else_=0,
                        )
                    ),
                    0,
                )
            ).where(PointLedgerEntry.user_id == user_id)
        )
        or 0
    )
    return PointAccountResponse(
        balance=account.balance,
        lifetime_earned=lifetime_earned,
        lifetime_spent=lifetime_spent,
        updated_at=_aware(account.updated_at),
    )


def ledger_response(entry: PointLedgerEntry) -> PointLedgerResponse:
    return PointLedgerResponse(
        id=str(entry.id),
        kind=entry.entry_type,
        amount=entry.delta,
        balance_after=entry.balance_after,
        reason=entry.description,
        reference_type=entry.source_type,
        reference_id=str(entry.source_id),
        created_at=_aware(entry.created_at),
    )


async def list_point_ledger(
    session: AsyncSession,
    *,
    user_id: UUID,
) -> list[PointLedgerResponse]:
    entries = list(
        await session.scalars(
            select(PointLedgerEntry)
            .where(PointLedgerEntry.user_id == user_id)
            .order_by(PointLedgerEntry.created_at.desc(), PointLedgerEntry.id)
        )
    )
    return [ledger_response(entry) for entry in entries]


def reward_response(reward: Reward) -> RewardResponse:
    return RewardResponse(
        id=str(reward.id),
        code=reward.code,
        name=reward.name,
        description=reward.description,
        points_cost=reward.points_cost,
        stock=reward.stock,
        provider="demo_rewards",
        is_demo=reward.is_demo,
    )


async def list_rewards(session: AsyncSession) -> list[RewardResponse]:
    rewards = list(
        await session.scalars(
            select(Reward).where(Reward.is_active.is_(True)).order_by(Reward.code)
        )
    )
    return [reward_response(reward) for reward in rewards]


def redemption_response(redemption: Redemption) -> RedemptionResponse:
    return RedemptionResponse(
        id=str(redemption.id),
        redemption_no=redemption.redemption_no,
        reward_id=str(redemption.reward_id),
        reward_name=redemption.reward.name,
        quantity=redemption.quantity,
        points_spent=redemption.total_points,
        status=redemption.status,
        provider="demo_rewards",
        is_demo=redemption.reward.is_demo,
        created_at=_aware(redemption.created_at),
    )


async def redeem_reward(
    session: AsyncSession,
    *,
    user: User,
    reward_id: UUID,
    quantity: int,
    idempotency_key: str,
) -> Redemption:
    actor_id = user.id
    request_hash = _hash_payload({"quantity": quantity, "reward_id": str(reward_id)})
    existing = await session.scalar(
        select(Redemption).where(
            Redemption.user_id == actor_id,
            Redemption.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Redemption key payload differs")
        return existing

    await _lock_point_account(session, actor_id)
    existing = await session.scalar(
        select(Redemption).where(
            Redemption.user_id == actor_id,
            Redemption.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            await session.rollback()
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Redemption key payload differs")
        redemption_id = existing.id
        await session.rollback()
        replayed = await session.get(Redemption, redemption_id)
        assert replayed is not None
        return replayed
    reward = await session.get(Reward, reward_id, populate_existing=True)
    if reward is None or not reward.is_active:
        await session.rollback()
        raise _error(404, "REWARD_NOT_FOUND", "Reward not found")
    total_points = reward.points_cost * quantity
    claimed = await session.execute(
        update(Reward)
        .execution_options(synchronize_session=False)
        .where(
            Reward.id == reward.id,
            Reward.is_active.is_(True),
            Reward.stock >= quantity,
        )
        .values(
            stock=Reward.stock - quantity,
            version=Reward.version + 1,
        )
    )
    if claimed.rowcount != 1:
        await session.rollback()
        raise _error(409, "REWARD_SOLD_OUT", "Reward stock is insufficient")
    debited = await session.execute(
        update(PointAccount)
        .execution_options(synchronize_session=False)
        .where(
            PointAccount.user_id == actor_id,
            PointAccount.balance >= total_points,
        )
        .values(
            balance=PointAccount.balance - total_points,
            updated_at=datetime.now(UTC),
        )
        .returning(PointAccount.balance)
    )
    balance_after = debited.scalar_one_or_none()
    if balance_after is None:
        await session.rollback()
        raise _error(409, "INSUFFICIENT_POINTS", "Point balance is insufficient")
    redemption_id = uuid4()
    redemption = Redemption(
        id=redemption_id,
        redemption_no=f"PR-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:12].upper()}",
        user_id=actor_id,
        reward_id=reward.id,
        quantity=quantity,
        total_points=total_points,
        status="CONFIRMED",
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    session.add(redemption)
    session.add(
        PointLedgerEntry(
            user_id=actor_id,
            entry_type="SPEND",
            delta=-total_points,
            balance_after=balance_after,
            source_type="REDEMPTION",
            source_id=redemption_id,
            description=f"积分兑换 {reward.name}",
        )
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        concurrent = await session.scalar(
            select(Redemption).where(
                Redemption.user_id == actor_id,
                Redemption.idempotency_key == idempotency_key,
            )
        )
        if concurrent is None or concurrent.request_hash != request_hash:
            raise _error(409, "REDEMPTION_CONFLICT", "Redemption could not complete") from exc
        redemption_id = concurrent.id
    loaded = await session.get(Redemption, redemption_id, populate_existing=True)
    assert loaded is not None
    return loaded


def share_response(share: ContentShare) -> ShareResponse:
    return ShareResponse(
        id=str(share.id),
        content_type=share.target_type,
        ref_id=share.target_ref,
        platform=share.channel,
        caption=share.caption,
        verified=share.verified,
        points_awarded=share.points_awarded,
        provider=share.provider,
        is_demo=share.is_demo,
        created_at=_aware(share.created_at),
    )


async def verify_share(
    session: AsyncSession,
    *,
    user: User,
    content_type: str,
    ref_id: str,
    platform: str,
    caption: str,
    idempotency_key: str,
    verifier: DemoShareVerifier | None = None,
) -> ContentShare:
    actor_id = user.id
    normalized = {
        "caption": caption.strip(),
        "content_type": content_type.strip(),
        "platform": platform.strip(),
        "ref_id": ref_id.strip(),
    }
    if normalized["content_type"] != "PRODUCT":
        raise _error(422, "SHARE_CONTENT_UNSUPPORTED", "Only product shares are eligible")
    try:
        product_id = UUID(normalized["ref_id"])
    except ValueError as exc:
        raise _error(404, "SHARE_TARGET_NOT_FOUND", "Share target not found") from exc
    product = await session.get(Product, product_id)
    if product is None or not product.is_active:
        raise _error(404, "SHARE_TARGET_NOT_FOUND", "Share target not found")
    request_hash = _hash_payload(normalized)
    share_key = sha256(f"{normalized['content_type']}:{normalized['ref_id']}".encode()).hexdigest()
    existing = await session.scalar(
        select(ContentShare).where(
            ContentShare.user_id == actor_id,
            ContentShare.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Share key payload differs")
        return existing
    duplicate = await session.scalar(
        select(ContentShare).where(
            ContentShare.user_id == actor_id,
            ContentShare.share_key == share_key,
        )
    )
    if duplicate is not None:
        return duplicate
    provider = verifier or DemoShareVerifier()
    verification = await provider.verify(**normalized)
    if not verification.verified:
        raise _error(409, "SHARE_NOT_VERIFIED", "Demo share verification failed")
    share_id = uuid4()
    share = ContentShare(
        id=share_id,
        user_id=actor_id,
        share_key=share_key,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        channel=normalized["platform"],
        target_type=normalized["content_type"],
        target_ref=normalized["ref_id"],
        caption=normalized["caption"],
        verified=True,
        provider=verification.provider,
        is_demo=verification.is_demo,
        points_awarded=verification.points_awarded,
    )
    session.add(share)
    await award_points(
        session,
        user_id=actor_id,
        points=verification.points_awarded,
        source_type="CONTENT_SHARE",
        source_id=share_id,
        description="演示内容分享积分",
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        concurrent = await session.scalar(
            select(ContentShare).where(
                ContentShare.user_id == actor_id,
                or_(
                    ContentShare.idempotency_key == idempotency_key,
                    ContentShare.share_key == share_key,
                ),
            )
        )
        if concurrent is None:
            raise _error(409, "SHARE_CONFLICT", "Share could not be recorded") from exc
        if (
            concurrent.idempotency_key == idempotency_key
            and concurrent.request_hash != request_hash
        ):
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Share key payload differs") from exc
        share_id = concurrent.id
    loaded = await session.get(ContentShare, share_id, populate_existing=True)
    assert loaded is not None
    return loaded
