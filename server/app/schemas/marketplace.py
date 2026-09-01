"""Experience, reservation, queue, hospitality, fast-pass, and review contracts."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ExperienceResponse(BaseModel):
    id: str
    code: str
    kind: Literal["RIDE", "SHOW"]
    name: str
    description: str
    node_id: str
    duration_minutes: int
    min_height_cm: int
    fastpass_allowed: bool
    fastpass_price_cents: int
    accessibility: list[str]
    wait_minutes: int


class ExperienceListResponse(BaseModel):
    items: list[ExperienceResponse]


class ExperienceSessionResponse(BaseModel):
    id: str
    experience_id: str
    experience_name: str
    starts_at: datetime
    ends_at: datetime
    capacity: int
    remaining: int
    status: Literal["OPEN", "CLOSED", "CANCELLED"]


class ExperienceSessionListResponse(BaseModel):
    items: list[ExperienceSessionResponse]


class CreateReservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    party_size: int = Field(ge=1, le=20)
    idempotency_key: str = Field(min_length=8, max_length=128)


class ReservationOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=8, max_length=128)


class CancelReservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=128)


class ReservationAllocationResponse(BaseModel):
    bucket_id: str
    business_date: date
    starts_at: datetime
    ends_at: datetime
    quantity: int


class ReservationResponse(BaseModel):
    id: str
    booking_no: str
    kind: Literal["EXPERIENCE", "STAY", "DINING", "BUNDLE"]
    resource_type: str
    resource_id: str
    resource_name: str
    starts_at: datetime
    ends_at: datetime
    party_size: int
    quantity: int
    total_cents: int
    status: Literal["HELD", "CONFIRMED", "COMPLETED", "CANCELLED", "EXPIRED", "NO_SHOW"]
    provider: str = "demo"
    is_demo: bool = True
    allocations: list[ReservationAllocationResponse]


class ReservationListResponse(BaseModel):
    items: list[ReservationResponse]


class NearbyRecommendationResponse(BaseModel):
    kind: Literal["ATTRACTION", "RESTAURANT"]
    ref_id: str
    name: str
    reason: str
    walk_minutes: int
    crowd_level: Literal["LOW", "MEDIUM", "HIGH"]


class JoinQueueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experience_id: UUID
    party_size: int = Field(ge=1, le=20)
    itinerary_id: UUID | None = None
    idempotency_key: str = Field(min_length=8, max_length=128)


class CreateFastPassRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=8, max_length=128)


class FastPassResponse(BaseModel):
    id: str
    code: str
    experience_id: str
    experience_name: str
    price_cents: int
    status: Literal["ACTIVE", "USED", "CANCELLED", "EXPIRED"]
    valid_from: datetime
    valid_to: datetime
    provider: str = "demo"
    is_demo: bool = True


class QueueResponse(BaseModel):
    id: str
    queue_no: str
    experience_id: str
    experience_name: str
    status: Literal["WAITING", "CALLED", "SERVING", "COMPLETED", "LEFT", "EXPIRED"]
    party_size: int
    estimated_wait_minutes: int
    sequence: int
    joined_at: datetime
    called_at: datetime | None
    itinerary_id: str | None
    itinerary_revision: int | None
    nearby_recommendations: list[NearbyRecommendationResponse]
    fast_pass: FastPassResponse | None


class WsTicketResponse(BaseModel):
    ticket: str
    expires_at: datetime


class WsTicketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel_type: Literal["queue"]
    channel_id: UUID


class QueueEventData(BaseModel):
    queue: QueueResponse
    source: str = "simulated"
    is_demo: bool = True
    recommendation: NearbyRecommendationResponse | None
    itinerary_id: str | None
    itinerary_revision: int | None


class QueueWebSocketEnvelope(BaseModel):
    id: str
    type: Literal["queue.updated", "nearby.recommended", "itinerary.replan_available"]
    occurred_at: datetime
    data: QueueEventData


class VenueResponse(BaseModel):
    id: str
    code: str
    kind: Literal["HOTEL", "HOMESTAY", "RESTAURANT"]
    name: str
    description: str
    address: str
    node_id: str
    accessibility: list[str]
    amenities: list[str]
    rating: float
    is_demo: bool = True


class VenueListResponse(BaseModel):
    items: list[VenueResponse]


class BundleComponentResponse(BaseModel):
    kind: str
    ref_id: str
    name: str
    quantity: int
    offset_minutes: int


class OfferResponse(BaseModel):
    id: str
    venue_id: str
    code: str
    kind: Literal["ROOM", "MEAL", "BUNDLE"]
    name: str
    description: str
    base_price_cents: int
    capacity: int
    max_party_size: int
    provider: str = "demo"
    is_demo: bool = True
    bundle_components: list[BundleComponentResponse]
    attributes: list[str]


class OfferListResponse(BaseModel):
    items: list[OfferResponse]


class AvailabilityItemResponse(BaseModel):
    bucket_id: str
    resource_type: str
    resource_id: str
    business_date: date
    start_at: datetime
    end_at: datetime
    remaining: int
    unit_price_cents: int


class AvailabilityResponse(BaseModel):
    items: list[AvailabilityItemResponse]


class StayBookingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_id: UUID
    check_in: date
    check_out: date
    quantity: int = Field(ge=1, le=10)
    party_size: int = Field(ge=1, le=30)
    idempotency_key: str = Field(min_length=8, max_length=128)


class DiningBookingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_id: UUID
    starts_at: datetime
    party_size: int = Field(ge=1, le=30)
    idempotency_key: str = Field(min_length=8, max_length=128)


class BundleBookingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_id: UUID
    visit_date: date
    party_size: int = Field(ge=1, le=30)
    idempotency_key: str = Field(min_length=8, max_length=128)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reservation_id: UUID
    rating: int = Field(ge=1, le=5)
    content: str = Field(min_length=1, max_length=1000)


class ReviewResponse(BaseModel):
    id: str
    reservation_id: str
    target_type: str
    target_id: str
    rating: int
    content: str
    status: str = "PUBLISHED"
    created_at: datetime
