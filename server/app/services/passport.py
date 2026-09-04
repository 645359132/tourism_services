"""Digital passport stamps and green-task completion with atomic point awards."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models.journey import (
    GreenTask,
    GreenTaskCompletion,
    JourneyIdempotencyReceipt,
    PassportStamp,
    PassportStampDefinition,
)
from app.db.models.user import User
from app.providers.journey import DemoCheckInVerifier, DemoGreenTaskVerifier
from app.schemas.journey import (
    GreenTaskCompletionResponse,
    GreenTaskListResponse,
    GreenTaskResponse,
    PassportCheckInResponse,
    PassportStampResponse,
    PassportSummaryResponse,
)
from app.services.points import award_points, point_account_response


def _error(status_code: int, code: str, message: str) -> AppError:
    return AppError(status_code=status_code, code=code, message=message)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _hash_payload(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode()).hexdigest()


async def _rejected_receipt(
    session: AsyncSession,
    *,
    user_id: UUID,
    scope: str,
    idempotency_key: str,
) -> JourneyIdempotencyReceipt | None:
    return await session.scalar(
        select(JourneyIdempotencyReceipt).where(
            JourneyIdempotencyReceipt.user_id == user_id,
            JourneyIdempotencyReceipt.scope == scope,
            JourneyIdempotencyReceipt.idempotency_key == idempotency_key,
        )
    )


async def _record_duplicate_rejection(
    session: AsyncSession,
    *,
    user_id: UUID,
    scope: str,
    idempotency_key: str,
    request_hash: str,
    target_id: UUID,
    result_id: UUID,
) -> None:
    receipt = await _rejected_receipt(
        session,
        user_id=user_id,
        scope=scope,
        idempotency_key=idempotency_key,
    )
    if receipt is not None:
        if receipt.request_hash != request_hash:
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Idempotency key payload differs")
        return
    session.add(
        JourneyIdempotencyReceipt(
            user_id=user_id,
            scope=scope,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            target_id=target_id,
            result_id=result_id,
            outcome="DUPLICATE_REJECTED",
        )
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        receipt = await _rejected_receipt(
            session,
            user_id=user_id,
            scope=scope,
            idempotency_key=idempotency_key,
        )
        if receipt is None:
            raise
        if receipt.request_hash != request_hash:
            raise _error(
                409,
                "IDEMPOTENCY_CONFLICT",
                "Idempotency key payload differs",
            ) from exc


def _stamp_response(
    definition: PassportStampDefinition,
    collected: PassportStamp | None,
) -> PassportStampResponse:
    return PassportStampResponse(
        id=str(definition.id),
        code=definition.code,
        title=definition.title,
        description=definition.description,
        node_id=str(definition.node_id),
        points_award=definition.points_award,
        collected=collected is not None,
        collected_at=(None if collected is None else _aware(collected.collected_at)),
        provider=("demo_checkin" if collected is None else collected.provider),
        is_demo=True if collected is None else collected.is_demo,
    )


async def passport_summary(
    session: AsyncSession,
    *,
    user: User,
) -> PassportSummaryResponse:
    definitions = list(
        await session.scalars(
            select(PassportStampDefinition)
            .where(PassportStampDefinition.is_active.is_(True))
            .order_by(PassportStampDefinition.code)
        )
    )
    collected = list(
        await session.scalars(select(PassportStamp).where(PassportStamp.user_id == user.id))
    )
    by_definition = {stamp.definition_id: stamp for stamp in collected}
    account = await point_account_response(session, user_id=user.id)
    response = PassportSummaryResponse(
        collected_count=len(collected),
        total_count=len(definitions),
        points_earned=sum(stamp.points_awarded for stamp in collected),
        point_balance=account.balance,
        stamps=[
            _stamp_response(definition, by_definition.get(definition.id))
            for definition in definitions
        ],
        provider="demo_checkin",
        is_demo=True,
    )
    await session.commit()
    return response


async def check_in_stamp(
    session: AsyncSession,
    *,
    user: User,
    stamp_code: str,
    idempotency_key: str,
    verifier: DemoCheckInVerifier | None = None,
) -> tuple[PassportStamp, int]:
    actor_id = user.id
    normalized_code = stamp_code.strip().lower()
    request_hash = _hash_payload({"stamp_code": normalized_code})
    # 创新点 8: 幂等键处理同一次打卡的网络重试, 用户与印章定义的唯一约束阻止换键重复领奖;
    # 对“不同键但同一印章”的拒绝也留存回执, 使后续重试得到一致结果。
    existing_by_key = await session.scalar(
        select(PassportStamp).where(
            PassportStamp.user_id == actor_id,
            PassportStamp.idempotency_key == idempotency_key,
        )
    )
    if existing_by_key is not None:
        if existing_by_key.request_hash != request_hash:
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Check-in key payload differs")
        account = await point_account_response(session, user_id=actor_id)
        return existing_by_key, account.balance
    rejected = await _rejected_receipt(
        session,
        user_id=actor_id,
        scope="PASSPORT_STAMP",
        idempotency_key=idempotency_key,
    )
    if rejected is not None:
        if rejected.request_hash != request_hash:
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Check-in key payload differs")
        raise _error(
            409,
            "PASSPORT_STAMP_ALREADY_COLLECTED",
            "Passport stamp was already collected under another operation",
        )
    definition = await session.scalar(
        select(PassportStampDefinition).where(
            PassportStampDefinition.code == normalized_code,
            PassportStampDefinition.is_active.is_(True),
        )
    )
    if definition is None:
        raise _error(404, "PASSPORT_STAMP_NOT_FOUND", "Passport stamp not found")
    definition_id = definition.id
    definition_title = definition.title
    points_award = definition.points_award
    duplicate = await session.scalar(
        select(PassportStamp).where(
            PassportStamp.user_id == actor_id,
            PassportStamp.definition_id == definition_id,
        )
    )
    if duplicate is not None:
        await _record_duplicate_rejection(
            session,
            user_id=actor_id,
            scope="PASSPORT_STAMP",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            target_id=definition_id,
            result_id=duplicate.id,
        )
        raise _error(
            409,
            "PASSPORT_STAMP_ALREADY_COLLECTED",
            "Passport stamp was already collected under another operation",
        )
    provider = verifier or DemoCheckInVerifier()
    verified = await provider.verify(stamp_code=normalized_code)
    if not verified.verified:
        raise _error(409, "CHECK_IN_NOT_VERIFIED", "Demo check-in was not verified")
    stamp_id = uuid4()
    try:
        # 创新点 8: 印章记录与积分入账共用一个事务, 避免出现只打卡未加分或只加分未打卡。
        await award_points(
            session,
            user_id=actor_id,
            points=points_award,
            source_type="PASSPORT_STAMP",
            source_id=stamp_id,
            description=f"文化护照印章 {definition_title}",
        )
        session.add(
            PassportStamp(
                id=stamp_id,
                user_id=actor_id,
                definition_id=definition_id,
                points_awarded=points_award,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                provider=verified.provider,
                is_demo=verified.is_demo,
            )
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        concurrent = await session.scalar(
            select(PassportStamp).where(
                PassportStamp.user_id == actor_id,
                PassportStamp.definition_id == definition_id,
            )
        )
        if concurrent is None:
            raise _error(409, "CHECK_IN_CONFLICT", "Check-in could not complete") from exc
        if concurrent.idempotency_key != idempotency_key:
            await _record_duplicate_rejection(
                session,
                user_id=actor_id,
                scope="PASSPORT_STAMP",
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                target_id=definition_id,
                result_id=concurrent.id,
            )
            raise _error(
                409,
                "PASSPORT_STAMP_ALREADY_COLLECTED",
                "Passport stamp was already collected under another operation",
            ) from exc
        if concurrent.request_hash != request_hash:
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Check-in key payload differs") from exc
        stamp_id = concurrent.id
    stamp = await session.get(PassportStamp, stamp_id, populate_existing=True)
    assert stamp is not None
    account = await point_account_response(session, user_id=actor_id)
    await session.commit()
    return stamp, account.balance


def check_in_response(
    stamp: PassportStamp,
    *,
    point_balance: int,
) -> PassportCheckInResponse:
    return PassportCheckInResponse(
        stamp=_stamp_response(stamp.definition, stamp),
        points_awarded=stamp.points_awarded,
        point_balance=point_balance,
        provider=stamp.provider,
        is_demo=stamp.is_demo,
    )


async def green_task_list(
    session: AsyncSession,
    *,
    user: User,
) -> GreenTaskListResponse:
    tasks = list(
        await session.scalars(
            select(GreenTask).where(GreenTask.is_active.is_(True)).order_by(GreenTask.code)
        )
    )
    completions = list(
        await session.scalars(
            select(GreenTaskCompletion).where(GreenTaskCompletion.user_id == user.id)
        )
    )
    by_task = {completion.task_id: completion for completion in completions}
    account = await point_account_response(session, user_id=user.id)
    response = GreenTaskListResponse(
        items=[
            GreenTaskResponse(
                id=str(task.id),
                code=task.code,
                kind=task.kind,
                title=task.title,
                description=task.description,
                points_award=task.points_award,
                evidence_hint=task.evidence_hint,
                completed=task.id in by_task,
                completed_at=(
                    None if task.id not in by_task else _aware(by_task[task.id].completed_at)
                ),
                provider="demo_green_verifier",
                is_demo=task.is_demo,
            )
            for task in tasks
        ],
        point_balance=account.balance,
    )
    await session.commit()
    return response


async def complete_green_task(
    session: AsyncSession,
    *,
    user: User,
    task_id: UUID,
    evidence: str,
    idempotency_key: str,
    verifier: DemoGreenTaskVerifier | None = None,
) -> tuple[GreenTaskCompletion, int]:
    actor_id = user.id
    request_hash = _hash_payload({"evidence": evidence.strip(), "task_id": str(task_id)})
    existing_by_key = await session.scalar(
        select(GreenTaskCompletion).where(
            GreenTaskCompletion.user_id == actor_id,
            GreenTaskCompletion.idempotency_key == idempotency_key,
        )
    )
    if existing_by_key is not None:
        if existing_by_key.request_hash != request_hash:
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Green task key payload differs")
        account = await point_account_response(session, user_id=actor_id)
        return existing_by_key, account.balance
    rejected = await _rejected_receipt(
        session,
        user_id=actor_id,
        scope="GREEN_TASK",
        idempotency_key=idempotency_key,
    )
    if rejected is not None:
        if rejected.request_hash != request_hash:
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Green task key payload differs")
        raise _error(
            409,
            "GREEN_TASK_ALREADY_COMPLETED",
            "Green task was already completed under another operation",
        )
    task = await session.get(GreenTask, task_id)
    if task is None or not task.is_active:
        raise _error(404, "GREEN_TASK_NOT_FOUND", "Green task not found")
    task_identity = task.id
    task_title = task.title
    task_points = task.points_award
    duplicate = await session.scalar(
        select(GreenTaskCompletion).where(
            GreenTaskCompletion.user_id == actor_id,
            GreenTaskCompletion.task_id == task_identity,
        )
    )
    if duplicate is not None:
        await _record_duplicate_rejection(
            session,
            user_id=actor_id,
            scope="GREEN_TASK",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            target_id=task_identity,
            result_id=duplicate.id,
        )
        raise _error(
            409,
            "GREEN_TASK_ALREADY_COMPLETED",
            "Green task was already completed under another operation",
        )
    provider = verifier or DemoGreenTaskVerifier()
    verified = await provider.verify(evidence=evidence)
    if not verified.verified:
        raise _error(409, "GREEN_TASK_NOT_VERIFIED", "Task evidence was not verified")
    completion_id = uuid4()
    try:
        await award_points(
            session,
            user_id=actor_id,
            points=task_points,
            source_type="GREEN_TASK",
            source_id=completion_id,
            description=f"绿色任务 {task_title}",
        )
        session.add(
            GreenTaskCompletion(
                id=completion_id,
                user_id=actor_id,
                task_id=task_identity,
                evidence=evidence.strip(),
                points_awarded=task_points,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                provider=verified.provider,
                is_demo=verified.is_demo,
            )
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        concurrent = await session.scalar(
            select(GreenTaskCompletion).where(
                GreenTaskCompletion.user_id == actor_id,
                GreenTaskCompletion.task_id == task_identity,
            )
        )
        if concurrent is None:
            raise _error(
                409,
                "GREEN_TASK_CONFLICT",
                "Green task could not complete",
            ) from exc
        if concurrent.idempotency_key != idempotency_key:
            await _record_duplicate_rejection(
                session,
                user_id=actor_id,
                scope="GREEN_TASK",
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                target_id=task_identity,
                result_id=concurrent.id,
            )
            raise _error(
                409,
                "GREEN_TASK_ALREADY_COMPLETED",
                "Green task was already completed under another operation",
            ) from exc
        if concurrent.request_hash != request_hash:
            raise _error(
                409,
                "IDEMPOTENCY_CONFLICT",
                "Green task key payload differs",
            ) from exc
        completion_id = concurrent.id
    completion = await session.get(
        GreenTaskCompletion,
        completion_id,
        populate_existing=True,
    )
    assert completion is not None
    account = await point_account_response(session, user_id=actor_id)
    await session.commit()
    return completion, account.balance


def green_completion_response(
    completion: GreenTaskCompletion,
    *,
    point_balance: int,
) -> GreenTaskCompletionResponse:
    return GreenTaskCompletionResponse(
        id=str(completion.id),
        task_id=str(completion.task_id),
        task_code=completion.task.code,
        points_awarded=completion.points_awarded,
        evidence=completion.evidence,
        point_balance=point_balance,
        completed_at=_aware(completion.completed_at),
        provider=completion.provider,
        is_demo=completion.is_demo,
    )
