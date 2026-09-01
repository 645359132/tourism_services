"""Feedback, support, group collaboration, and facility API contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FeedbackFollowUpResponse(BaseModel):
    id: str
    author_name: str
    rating: int
    comment: str
    created_at: datetime


class FeedbackResponse(BaseModel):
    id: str
    ticket_no: str
    kind: Literal["FEEDBACK", "COMPLAINT", "SUGGESTION"]
    title: str
    content: str
    status: Literal["SUBMITTED", "IN_PROGRESS", "RESOLVED", "CLOSED"]
    priority: Literal["LOW", "NORMAL", "HIGH"]
    latest_response: str | None
    rating: int | None
    follow_ups: list[FeedbackFollowUpResponse]
    created_at: datetime
    updated_at: datetime


class FeedbackListResponse(BaseModel):
    items: list[FeedbackResponse]


class CreateFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["FEEDBACK", "COMPLAINT", "SUGGESTION"]
    title: str = Field(min_length=2, max_length=160)
    content: str = Field(min_length=2, max_length=2000)
    priority: Literal["LOW", "NORMAL", "HIGH"] = "NORMAL"


class AssignFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assigned_to_user_id: UUID | None = None
    note: str | None = Field(default=None, max_length=1000)


class ResolveFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution: str = Field(min_length=2, max_length=2000)


class FeedbackFollowUpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rating: int = Field(ge=1, le=5)
    comment: str = Field(min_length=1, max_length=1000)


class FAQResponse(BaseModel):
    id: str
    category: str
    question: str
    answer: str
    sort_order: int


class FAQListResponse(BaseModel):
    items: list[FAQResponse]


class SupportMessageResponse(BaseModel):
    id: str
    conversation_id: str
    sender_type: Literal["TOURIST", "SUPPORT", "BOT"]
    sender_name: str
    content: str
    sequence: int
    created_at: datetime
    provider: str
    is_demo: bool


class SupportConversationResponse(BaseModel):
    id: str
    subject: str
    status: Literal["OPEN", "CLOSED"]
    provider: str
    is_demo: bool
    last_message_at: datetime
    created_at: datetime


class SupportConversationListResponse(BaseModel):
    items: list[SupportConversationResponse]


class SupportMessageListResponse(BaseModel):
    items: list[SupportMessageResponse]


class CreateSupportConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=2, max_length=160)


class CreateSupportMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=128)


class SupportWsTicketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID


class SupportEventData(BaseModel):
    conversation: SupportConversationResponse
    message: SupportMessageResponse | None
    source: Literal["demo_support_bot", "human"] = "demo_support_bot"
    is_demo: bool = True


class SupportWebSocketEnvelope(BaseModel):
    id: str
    type: Literal["support.message", "support.updated"]
    occurred_at: datetime
    data: SupportEventData


class GroupMemberResponse(BaseModel):
    user_id: str
    display_name: str
    role: Literal["OWNER", "MEMBER"]
    status: Literal["TOGETHER", "MOVING", "WAITING", "LOST", "HIDDEN"]
    share_location: bool
    share_status: bool
    note: str
    updated_at: datetime
    latitude: float | None
    longitude: float | None


class MeetingPointResponse(BaseModel):
    id: str
    name: str
    node_id: str | None
    note: str
    created_at: datetime


class GroupResponse(BaseModel):
    id: str
    name: str
    invite_code: str
    revision: int
    itinerary_id: str | None
    itinerary_revision: int | None
    share_itinerary: bool
    share_location: bool
    share_member_status: bool
    members: list[GroupMemberResponse]
    meeting_point: MeetingPointResponse | None
    provider: str = "local_collaboration"
    is_demo: bool = True
    updated_at: datetime


class CreateGroupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=160)
    invite_valid_minutes: int = Field(default=60, ge=1, le=1440)
    itinerary_id: UUID | None = None


class JoinGroupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invite_code: str = Field(min_length=6, max_length=32)


class GroupPrivacyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    share_itinerary: bool
    share_location: bool
    share_member_status: bool


class GroupItineraryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    itinerary_id: UUID | None
    expected_revision: int = Field(ge=1)


class MeetingPointRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    note: str = Field(min_length=1, max_length=500)
    node_id: UUID | None = None
    meeting_at: datetime | None = None


class MemberStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["TOGETHER", "MOVING", "WAITING", "LOST"]
    note: str = Field(default="", max_length=500)
    share_location: bool | None = None
    share_status: bool | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @field_validator("longitude")
    @classmethod
    def require_coordinate_pair(
        cls,
        longitude: float | None,
        info,
    ) -> float | None:
        latitude = info.data.get("latitude")
        if (latitude is None) != (longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        return longitude


class LostAlertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_member_id: UUID | None = None
    message: str = Field(min_length=1, max_length=500)
    last_seen_node_id: UUID | None = None


class LostAlertResponse(BaseModel):
    id: str
    group_id: str
    message: str
    status: Literal["ACTIVE", "RESOLVED"]
    last_seen_node_id: str | None
    provider: str = "local_collaboration"
    is_demo: bool = True
    created_at: datetime


class FacilityResponse(BaseModel):
    id: str
    kind: str
    name: str
    description: str
    node_id: str | None
    accessible: bool
    wheelchair_ok: bool
    stroller_ok: bool
    open_status: str
    source: str
    is_demo: bool = True


class FacilityListResponse(BaseModel):
    items: list[FacilityResponse]
