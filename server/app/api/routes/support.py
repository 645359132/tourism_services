"""Persisted support REST and support-scoped one-time WebSocket routes."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import require_roles, require_tourist
from app.core.errors import AppError
from app.db.models.user import User
from app.db.session import get_session
from app.realtime.support import SupportConnectionHub, SupportTicketStore
from app.schemas.engagement import (
    CreateSupportConversationRequest,
    CreateSupportMessageRequest,
    SupportConversationListResponse,
    SupportConversationResponse,
    SupportMessageListResponse,
    SupportWsTicketRequest,
)
from app.schemas.marketplace import WsTicketResponse
from app.services.auth import get_user_by_id
from app.services.support import (
    accessible_conversation,
    conversation_response,
    create_conversation,
    list_conversations,
    list_messages,
    message_response,
    post_message,
    support_envelope,
)

router = APIRouter(tags=["support"])
require_support_access = require_roles("tourist", "support")


@router.post(
    "/support/conversations",
    response_model=SupportConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_support_conversation(
    payload: CreateSupportConversationRequest,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SupportConversationResponse:
    return conversation_response(
        await create_conversation(
            session,
            user=current_user,
            subject=payload.subject,
        )
    )


@router.get(
    "/support/conversations",
    response_model=SupportConversationListResponse,
)
async def support_conversations(
    current_user: Annotated[User, Depends(require_support_access)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SupportConversationListResponse:
    conversations = await list_conversations(session, user=current_user)
    return SupportConversationListResponse(
        items=[conversation_response(item) for item in conversations]
    )


@router.get(
    "/support/conversations/{conversation_id}/messages",
    response_model=SupportMessageListResponse,
)
async def support_messages(
    conversation_id: UUID,
    current_user: Annotated[User, Depends(require_support_access)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SupportMessageListResponse:
    _, messages = await list_messages(
        session,
        conversation_id=conversation_id,
        user=current_user,
    )
    return SupportMessageListResponse(
        items=[await message_response(session, message) for message in messages]
    )


@router.post(
    "/support/conversations/{conversation_id}/messages",
    response_model=SupportMessageListResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_support_message(
    conversation_id: UUID,
    payload: CreateSupportMessageRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_support_access)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SupportMessageListResponse:
    conversation, messages = await post_message(
        session,
        conversation_id=conversation_id,
        user=current_user,
        content=payload.content,
        idempotency_key=payload.idempotency_key,
    )
    hub: SupportConnectionHub = request.app.state.support_hub
    for message in messages:
        envelope = await support_envelope(
            session,
            conversation=conversation,
            message=message,
            event_type="support.message",
        )
        await hub.broadcast(conversation.id, envelope)
    return SupportMessageListResponse(
        items=[await message_response(session, message) for message in messages]
    )


@router.post("/support/ws-tickets", response_model=WsTicketResponse)
async def create_support_ws_ticket(
    payload: SupportWsTicketRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_support_access)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WsTicketResponse:
    await accessible_conversation(
        session,
        conversation_id=payload.conversation_id,
        user=current_user,
    )
    store: SupportTicketStore = request.app.state.support_tickets
    ticket, expires_at = await store.issue(
        user_id=current_user.id,
        conversation_id=payload.conversation_id,
    )
    return WsTicketResponse(ticket=ticket, expires_at=expires_at)


@router.websocket("/ws/support/{conversation_id}")
async def support_websocket(
    websocket: WebSocket,
    conversation_id: UUID,
    ticket: Annotated[str, Query(min_length=20, max_length=256)],
) -> None:
    store: SupportTicketStore = websocket.app.state.support_tickets
    grant = await store.consume(
        token=ticket,
        conversation_id=conversation_id,
    )
    if grant is None:
        await websocket.close(code=4401)
        return
    hub: SupportConnectionHub = websocket.app.state.support_hub
    connection_id, messages = hub.register(conversation_id)
    factory = websocket.app.state.queue_publisher.session_factory_provider()
    try:
        async with factory() as session:
            user = await get_user_by_id(session, grant.user_id)
            if user is None:
                raise AppError(
                    status_code=404,
                    code="SUPPORT_CONVERSATION_NOT_FOUND",
                    message="Conversation not found",
                )
            conversation = await accessible_conversation(
                session,
                conversation_id=conversation_id,
                user=user,
            )
            initial = await support_envelope(
                session,
                conversation=conversation,
                message=None,
                event_type="support.updated",
            )
    except AppError:
        hub.unregister(conversation_id, connection_id)
        await websocket.close(code=4404)
        return

    await websocket.accept()
    await websocket.send_json(initial.model_dump(mode="json"))

    async def send_updates() -> None:
        while True:
            envelope = await messages.get()
            try:
                await asyncio.wait_for(
                    websocket.send_json(envelope.model_dump(mode="json")),
                    timeout=2.0,
                )
            except (TimeoutError, RuntimeError):
                with suppress(RuntimeError):
                    await websocket.close(code=1013)
                return

    async def receive_messages() -> None:
        while True:
            try:
                raw = await websocket.receive_json()
                if not isinstance(raw, dict):
                    raise ValueError
                if raw.get("type") == "ping":
                    continue
                if raw.get("type") != "message.send":
                    raise ValueError
                payload = CreateSupportMessageRequest.model_validate(raw.get("data"))
            except (ValueError, ValidationError):
                with suppress(RuntimeError):
                    await websocket.close(code=1008)
                return
            async with factory() as session:
                user = await get_user_by_id(session, grant.user_id)
                if user is None:
                    with suppress(RuntimeError):
                        await websocket.close(code=4404)
                    return
                try:
                    conversation, persisted = await post_message(
                        session,
                        conversation_id=conversation_id,
                        user=user,
                        content=payload.content,
                        idempotency_key=payload.idempotency_key,
                    )
                except AppError:
                    with suppress(RuntimeError):
                        await websocket.close(code=1008)
                    return
                for message in persisted:
                    envelope = await support_envelope(
                        session,
                        conversation=conversation,
                        message=message,
                        event_type="support.message",
                    )
                    await hub.broadcast(conversation_id, envelope)

    sender = asyncio.create_task(send_updates())
    receiver = asyncio.create_task(receive_messages())
    try:
        done, pending = await asyncio.wait(
            {sender, receiver},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in done:
            with suppress(WebSocketDisconnect, asyncio.CancelledError, RuntimeError):
                await task
    except WebSocketDisconnect:
        pass
    finally:
        sender.cancel()
        receiver.cancel()
        with suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
            await sender
        with suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
            await receiver
        hub.unregister(conversation_id, connection_id)
