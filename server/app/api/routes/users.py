"""Authenticated current-user profile and preference endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user, require_tourist
from app.db.models.preference import TouristPreference
from app.db.models.user import User
from app.db.session import get_session
from app.schemas.auth import UserResponse
from app.schemas.users import PreferencePatch, PreferenceResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    return UserResponse.from_user(current_user)


@router.patch("/me/preferences", response_model=PreferenceResponse)
async def patch_preferences(
    payload: PreferencePatch,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PreferenceResponse:
    preference = await session.get(TouristPreference, current_user.id)
    if preference is None:
        preference = TouristPreference(
            user_id=current_user.id,
            preferred_language="zh-CN",
            interests=[],
            accessibility_needs=[],
            notifications_enabled=True,
        )
        session.add(preference)

    for field_name in payload.model_fields_set:
        setattr(preference, field_name, getattr(payload, field_name))

    await session.commit()
    await session.refresh(preference)
    return PreferenceResponse.from_preference(preference)
