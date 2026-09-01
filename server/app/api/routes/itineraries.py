"""Authenticated deterministic itinerary endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import require_tourist
from app.db.models.user import User
from app.db.session import get_session
from app.schemas.guide import (
    ConflictCheckRequest,
    ConflictCheckResponse,
    GenerateItineraryRequest,
    ItineraryResponse,
    ReplanItineraryRequest,
)
from app.services.itinerary import (
    check_itinerary_conflicts,
    generate_itinerary,
    get_itinerary,
    itinerary_response,
    replan_itinerary,
)

router = APIRouter(prefix="/itineraries", tags=["itineraries"])


@router.post("/generate", response_model=ItineraryResponse)
async def generate(
    payload: GenerateItineraryRequest,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ItineraryResponse:
    itinerary = await generate_itinerary(
        session,
        user=current_user,
        payload=payload,
    )
    return itinerary_response(itinerary)


@router.get("/{itinerary_id}", response_model=ItineraryResponse)
async def itinerary_detail(
    itinerary_id: UUID,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ItineraryResponse:
    itinerary = await get_itinerary(
        session,
        itinerary_id=itinerary_id,
        user=current_user,
    )
    return itinerary_response(itinerary)


@router.post("/{itinerary_id}/conflicts/check", response_model=ConflictCheckResponse)
async def conflicts_check(
    itinerary_id: UUID,
    payload: ConflictCheckRequest,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConflictCheckResponse:
    return await check_itinerary_conflicts(
        session,
        itinerary_id=itinerary_id,
        user=current_user,
        walking_buffer_minutes=payload.walking_buffer_minutes,
    )


@router.post("/{itinerary_id}/replan", response_model=ItineraryResponse)
async def replan(
    itinerary_id: UUID,
    payload: ReplanItineraryRequest,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ItineraryResponse:
    itinerary = await replan_itinerary(
        session,
        itinerary_id=itinerary_id,
        user=current_user,
        payload=payload,
    )
    return itinerary_response(itinerary)
