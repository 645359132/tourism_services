"""Scenic guide, schematic routing, crowd, itinerary, and WS contracts."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

CrowdLevel = Literal["LOW", "MEDIUM", "HIGH"]


class AttractionResponse(BaseModel):
    id: str
    code: str
    name: str
    category: str
    description: str
    visit_minutes: int
    crowd_level: CrowdLevel
    occupancy_bps: int
    wait_minutes: int
    tags: list[str]
    accessibility: list[str]
    x: int
    y: int
    narration_available: bool
    node_id: str


class AttractionListResponse(BaseModel):
    items: list[AttractionResponse]


class NarrationResponse(BaseModel):
    id: str
    attraction_id: str
    title: str
    language: str
    duration_seconds: int
    transcript: str
    audio_url: str
    provider_mode: str = "text_demo"
    is_demo: bool = True


class NarrationListResponse(BaseModel):
    items: list[NarrationResponse]


class MapProviderResponse(BaseModel):
    name: str = "schematic"
    mode: str = "schematic"
    is_demo: bool = True
    description: str = "使用本地示意图, 未接入实时地图服务"


class MapNodeResponse(BaseModel):
    id: str
    code: str
    name: str
    kind: str
    attraction_id: str | None
    x: int
    y: int
    accessibility: list[str]


class MapEdgeResponse(BaseModel):
    id: str
    from_node_id: str
    to_node_id: str
    distance_m: int
    walk_minutes: int
    wheelchair_ok: bool
    stroller_ok: bool
    bidirectional: bool


class MapResponse(BaseModel):
    provider: MapProviderResponse
    nodes: list[MapNodeResponse]
    edges: list[MapEdgeResponse]


class CrowdItemResponse(BaseModel):
    attraction_id: str
    captured_at: datetime
    people_count: int
    occupancy_bps: int
    level: CrowdLevel
    wait_minutes: int
    source: str = "simulated"


class CrowdResponse(BaseModel):
    items: list[CrowdItemResponse]
    sequence: int
    captured_at: datetime
    source: str = "simulated"
    is_demo: bool = True


class RoutePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_node_id: UUID
    to_node_id: UUID
    wheelchair: bool = False
    stroller: bool = False


class RouteProviderResponse(BaseModel):
    mode: str = "schematic"
    is_demo: bool = True
    description: str = "使用本地示意图, 未接入实时地图服务"


class RoutePlanResponse(BaseModel):
    node_ids: list[str]
    distance_m: int
    walk_minutes: int
    accessible: bool
    explanation: list[str]
    provider: RouteProviderResponse


class GenerateItineraryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visit_date: date
    start_time: time
    duration_minutes: int = Field(ge=60, le=720)
    interests: list[str] = Field(default_factory=list, max_length=20)
    companion_type: Literal["solo", "family", "friends", "senior"]
    fitness_level: Literal["low", "medium", "high"]
    accessible: bool = False

    @field_validator("interests")
    @classmethod
    def normalize_interests(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip().lower() for item in value if item.strip()]
        if any(len(item) > 50 for item in cleaned):
            raise ValueError("interests must not exceed 50 characters")
        return list(dict.fromkeys(cleaned))


class ItineraryItemResponse(BaseModel):
    id: str
    ordinal: int
    kind: str
    ref_id: str
    title: str
    start_at: datetime
    end_at: datetime
    locked: bool
    crowd_level: CrowdLevel
    walk_minutes: int
    explanation: list[str]


class ItineraryResponse(BaseModel):
    id: str
    name: str
    visit_date: date
    status: str
    source: str
    revision: int
    total_score: int
    explanation: list[str]
    is_complete: bool
    unscheduled_reasons: list[str]
    items: list[ItineraryItemResponse]


class ConflictCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    walking_buffer_minutes: int = Field(default=10, ge=0, le=120)


class ConflictSuggestionResponse(BaseModel):
    action: str
    message: str
    item_id: str | None
    new_start_at: datetime | None
    new_end_at: datetime | None


class ItineraryConflictResponse(BaseModel):
    code: str
    severity: str
    item_ids: list[str]
    message: str


class ConflictCheckResponse(BaseModel):
    itinerary_id: str
    revision: int
    feasible: bool
    conflicts: list[ItineraryConflictResponse]
    suggestions: list[ConflictSuggestionResponse]


class ReplanItineraryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    crowd_avoidance: bool = True
    preserve_locked: bool = True
    expected_revision: int = Field(ge=1)


class CrowdWebSocketEnvelope(BaseModel):
    id: str
    type: str
    occurred_at: datetime
    data: dict[str, object]
