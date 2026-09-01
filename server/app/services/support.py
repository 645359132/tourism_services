"""Persisted support conversations, idempotent messages, and demo-bot replies."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.db.models.engagement import SupportConversation, SupportMessage
from app.db.models.user import User
from app.providers.support import DemoSupportBot
from app.schemas.engagement import (
    SupportConversationResponse,
    SupportEventData,
    SupportMessageResponse,
    SupportWebSocketEnvelope,
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


def _is_support(user: User) -> bool:
    return bool({"support", "admin"}.intersection(user.role_names))


def _conversation_statement():
    return (
        select(SupportConversation)
        .execution_options(populate_existing=True)
        .options(selectinload(SupportConversation.messages))
    )


async def _load_conversation(
    session: AsyncSession,
    conversation_id: UUID,
) -> SupportConversation | None:
    return await session.scalar(
        _conversation_statement().where(SupportConversation.id == conversation_id)
    )


async def accessible_conversation(
    session: AsyncSession,
    *,
    conversation_id: UUID,
    user: User,
) -> SupportConversation:
    conversation = await _load_conversation(session, conversation_id)
    if conversation is None or (conversation.tourist_user_id != user.id and not _is_support(user)):
        raise _error(404, "SUPPORT_CONVERSATION_NOT_FOUND", "Conversation not found")
    return conversation


def conversation_response(
    conversation: SupportConversation,
) -> SupportConversationResponse:
    last_message_at = max(
        (_aware(message.created_at) for message in conversation.messages),
        default=_aware(conversation.created_at),
    )
    return SupportConversationResponse(
        id=str(conversation.id),
        subject=conversation.subject,
        status=conversation.status,
        provider=("demo_support_bot" if conversation.mode == "DEMO_BOT" else "human_support"),
        is_demo=conversation.mode == "DEMO_BOT",
        last_message_at=last_message_at,
        created_at=_aware(conversation.created_at),
    )


async def message_response(
    session: AsyncSession,
    message: SupportMessage,
) -> SupportMessageResponse:
    if message.sender_type == "BOT":
        sender_name = "演示客服"
    elif message.sender_user_id is None:
        sender_name = "未知发送者"
    else:
        sender = await session.get(User, message.sender_user_id)
        sender_name = "已离开用户" if sender is None else sender.display_name
    return SupportMessageResponse(
        id=str(message.id),
        conversation_id=str(message.conversation_id),
        sender_type=message.sender_type,
        sender_name=sender_name,
        content=message.content,
        sequence=message.sequence,
        created_at=_aware(message.created_at),
        provider=message.provider,
        is_demo=message.is_demo,
    )


async def support_envelope(
    session: AsyncSession,
    *,
    conversation: SupportConversation,
    message: SupportMessage | None,
    event_type: str,
) -> SupportWebSocketEnvelope:
    return SupportWebSocketEnvelope(
        id=str(uuid4()),
        type=event_type,
        occurred_at=datetime.now(UTC),
        data=SupportEventData(
            conversation=conversation_response(conversation),
            message=(None if message is None else await message_response(session, message)),
            source=("demo_support_bot" if message is None or message.is_demo else "human"),
            is_demo=message is None or message.is_demo,
        ),
    )


async def create_conversation(
    session: AsyncSession,
    *,
    user: User,
    subject: str,
) -> SupportConversation:
    conversation = SupportConversation(
        conversation_no=f"SC-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:10].upper()}",
        tourist_user_id=user.id,
        subject=subject.strip(),
        status="OPEN",
        mode="DEMO_BOT",
        next_sequence=1,
    )
    session.add(conversation)
    await session.commit()
    loaded = await _load_conversation(session, conversation.id)
    assert loaded is not None
    return loaded


async def list_conversations(
    session: AsyncSession,
    *,
    user: User,
) -> list[SupportConversation]:
    statement = _conversation_statement().order_by(SupportConversation.updated_at.desc())
    if not _is_support(user):
        statement = statement.where(SupportConversation.tourist_user_id == user.id)
    return list(await session.scalars(statement))


async def list_messages(
    session: AsyncSession,
    *,
    conversation_id: UUID,
    user: User,
) -> tuple[SupportConversation, list[SupportMessage]]:
    conversation = await accessible_conversation(
        session,
        conversation_id=conversation_id,
        user=user,
    )
    return conversation, list(conversation.messages)


async def _append_message(
    session: AsyncSession,
    *,
    conversation_id: UUID,
    sender_user_id: UUID | None,
    sender_type: str,
    content: str,
    idempotency_key: str,
    provider: str,
    is_demo: bool,
) -> tuple[SupportMessage, bool]:
    sender_key = "BOT" if sender_user_id is None else str(sender_user_id)
    request_hash = _hash_payload({"content": content.strip()})
    existing = await session.scalar(
        select(SupportMessage).where(
            SupportMessage.conversation_id == conversation_id,
            SupportMessage.sender_key == sender_key,
            SupportMessage.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Message key payload differs")
        return existing, False
    next_value = await session.execute(
        update(SupportConversation)
        .execution_options(synchronize_session=False)
        .where(
            SupportConversation.id == conversation_id,
            SupportConversation.status == "OPEN",
        )
        .values(
            next_sequence=SupportConversation.next_sequence + 1,
            updated_at=datetime.now(UTC),
        )
        .returning(SupportConversation.next_sequence)
    )
    next_sequence = next_value.scalar_one_or_none()
    if next_sequence is None:
        raise _error(409, "SUPPORT_CONVERSATION_CLOSED", "Conversation is closed")
    existing = await session.scalar(
        select(SupportMessage).where(
            SupportMessage.conversation_id == conversation_id,
            SupportMessage.sender_key == sender_key,
            SupportMessage.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Message key payload differs")
        return existing, False
    message = SupportMessage(
        conversation_id=conversation_id,
        sender_user_id=sender_user_id,
        sender_key=sender_key,
        sender_type=sender_type,
        content=content.strip(),
        sequence=next_sequence - 1,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        provider=provider,
        is_demo=is_demo,
    )
    session.add(message)
    await session.flush()
    return message, True


async def post_message(
    session: AsyncSession,
    *,
    conversation_id: UUID,
    user: User,
    content: str,
    idempotency_key: str,
    bot: DemoSupportBot | None = None,
) -> tuple[SupportConversation, list[SupportMessage]]:
    actor_id = user.id
    conversation = await accessible_conversation(
        session,
        conversation_id=conversation_id,
        user=user,
    )
    conversation_identity = conversation.id
    if conversation.status != "OPEN":
        raise _error(409, "SUPPORT_CONVERSATION_CLOSED", "Conversation is closed")
    if conversation.tourist_user_id == user.id:
        sender_type = "TOURIST"
    elif _is_support(user):
        sender_type = "SUPPORT"
    else:
        raise _error(403, "FORBIDDEN", "Conversation access denied")
    message, created = await _append_message(
        session,
        conversation_id=conversation.id,
        sender_user_id=actor_id,
        sender_type=sender_type,
        content=content,
        idempotency_key=idempotency_key,
        provider="human",
        is_demo=False,
    )
    persisted = [message]
    if sender_type == "TOURIST" and conversation.mode == "DEMO_BOT":
        responder = bot or DemoSupportBot()
        reply = await responder.reply(message=content)
        bot_message, bot_created = await _append_message(
            session,
            conversation_id=conversation.id,
            sender_user_id=None,
            sender_type="BOT",
            content=reply.content,
            idempotency_key=f"bot-{message.id}",
            provider=reply.provider,
            is_demo=reply.is_demo,
        )
        persisted.append(bot_message)
    else:
        bot_created = False
    if created or bot_created:
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            replay = await session.scalar(
                select(SupportMessage).where(
                    SupportMessage.conversation_id == conversation_id,
                    SupportMessage.sender_key == str(actor_id),
                    SupportMessage.idempotency_key == idempotency_key,
                )
            )
            if replay is None:
                raise _error(
                    409,
                    "SUPPORT_MESSAGE_CONFLICT",
                    "Message could not be persisted",
                ) from exc
            message = replay
    loaded = await _load_conversation(session, conversation_identity)
    assert loaded is not None
    persisted_ids = {item.id for item in persisted}
    returned = [item for item in loaded.messages if item.id in persisted_ids]
    if not returned:
        returned = [item for item in loaded.messages if item.id == message.id]
    return loaded, returned
