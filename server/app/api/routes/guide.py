"""Public scenic guide, schematic route, simulated crowd, and crowd WS routes."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session, get_session_factory
from app.realtime.crowd import ConnectionHub
from app.schemas.guide import (
    AttractionListResponse,
    AttractionResponse,
    CrowdResponse,
    MapResponse,
    NarrationListResponse,
    RoutePlanRequest,
    RoutePlanResponse,
)
from app.services.guide import (
    crowd_envelope,
    crowd_response,
    get_attraction,
    list_attractions,
    list_narrations,
    map_response,
    plan_route,
)

router = APIRouter(prefix="/guide", tags=["guide"])


@router.get("/attractions", response_model=AttractionListResponse)
async def attractions(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AttractionListResponse:
    return AttractionListResponse(items=await list_attractions(session))


@router.get("/attractions/{attraction_id}", response_model=AttractionResponse)
async def attraction_detail(
    attraction_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AttractionResponse:
    return await get_attraction(session, attraction_id)


@router.get(
    "/attractions/{attraction_id}/narrations",
    response_model=NarrationListResponse,
)
async def attraction_narrations(
    attraction_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NarrationListResponse:
    return NarrationListResponse(items=await list_narrations(session, attraction_id))


@router.get("/map", response_model=MapResponse)
async def guide_map(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MapResponse:
    return await map_response(session)


@router.get("/crowd", response_model=CrowdResponse)
async def crowd(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CrowdResponse:
    return await crowd_response(session)


@router.post("/routes/plan", response_model=RoutePlanResponse)
async def route_plan(
    payload: RoutePlanRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RoutePlanResponse:
    return await plan_route(
        session,
        from_node_id=payload.from_node_id,
        to_node_id=payload.to_node_id,
        wheelchair=payload.wheelchair,
        stroller=payload.stroller,
    )


@router.websocket("/ws/crowd")
async def crowd_websocket(
    websocket: WebSocket,
) -> None:
    """Public server-to-client stream of explicitly simulated snapshots."""

    await websocket.accept()
    publisher = websocket.app.state.crowd_publisher
    factory = publisher.session_factory_provider or get_session_factory
    async with factory()() as initial_session:
        initial = crowd_envelope(await crowd_response(initial_session))
    await websocket.send_json(initial.model_dump(mode="json"))
    hub: ConnectionHub = websocket.app.state.crowd_hub
    connection_id, queue = hub.register()

    async def send_snapshots() -> None:
        while True:
            envelope = await queue.get()
            try:
                await asyncio.wait_for(
                    websocket.send_json(envelope.model_dump(mode="json")),
                    timeout=2.0,
                )
            except (TimeoutError, RuntimeError):
                with suppress(RuntimeError):
                    await websocket.close(code=1013)
                return

    async def receive_pings() -> None:
        while True:
            try:
                message = await websocket.receive_json()
            except ValueError:
                with suppress(RuntimeError):
                    await websocket.close(code=1003)
                return
            if message.get("type") == "ping":
                continue
            with suppress(RuntimeError):
                await websocket.close(code=1008)
            return

    sender = asyncio.create_task(send_snapshots())
    receiver = asyncio.create_task(receive_pings())
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
        with suppress(asyncio.CancelledError, WebSocketDisconnect):
            await sender
        with suppress(asyncio.CancelledError, WebSocketDisconnect):
            await receiver
        hub.unregister(connection_id)
