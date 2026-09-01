"""Offline, sync, emergency, passport, and green-task API contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MutationType = Literal["NOTE", "ITINERARY_ACK", "EMERGENCY_ACK"]


class OfflinePackResponse(BaseModel):
    id: str
    version: int
    name: str
    description: str
    etag: str
    published_at: datetime
    expires_at: datetime | None
    asset_count: int
    total_size_bytes: int
    manifest_url: str
    provider: str = "local_offline_pack"
    is_demo: bool = True


class OfflineAssetManifestResponse(BaseModel):
    id: str
    asset_key: str
    kind: str
    title: str
    content_hash: str
    encoding: Literal["json"] = "json"
    size_bytes: int
    required: bool
    download_url: str


class OfflineManifestResponse(BaseModel):
    pack_id: str
    version: int
    etag: str
    assets: list[OfflineAssetManifestResponse]
    provider: str = "local_offline_pack"
    is_demo: bool = True


class OfflineAssetContentResponse(BaseModel):
    id: str
    pack_id: str
    asset_key: str
    kind: str
    content_hash: str
    encoding: Literal["json"] = "json"
    size_bytes: int
    payload: dict[str, object]


class OfflineMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_mutation_id: str = Field(min_length=8, max_length=128)
    client_version: int = Field(ge=1)
    entity_type: MutationType
    entity_id: str = Field(min_length=1, max_length=128)
    operation: Literal["UPSERT", "DELETE"]
    payload: dict[str, object] = Field(default_factory=dict)


class SyncPushRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{4,100}$")
    base_cursor: str | None = Field(default=None, max_length=300)
    mutations: list[OfflineMutationRequest] = Field(min_length=1, max_length=50)

    @field_validator("mutations")
    @classmethod
    def require_strict_client_versions(
        cls,
        value: list[OfflineMutationRequest],
    ) -> list[OfflineMutationRequest]:
        versions = [mutation.client_version for mutation in value]
        if versions != sorted(set(versions)):
            raise ValueError("client versions must be unique and strictly increasing")
        mutation_ids = [mutation.client_mutation_id for mutation in value]
        if len(mutation_ids) != len(set(mutation_ids)):
            raise ValueError("client mutation IDs must be unique")
        return value


class SyncPushResult(BaseModel):
    client_mutation_id: str
    client_version: int
    server_cursor: str
    status: Literal["APPLIED", "REPLAYED"]


class SyncPushResponse(BaseModel):
    device_id: str
    accepted: int
    replayed: int
    server_cursor: str
    results: list[SyncPushResult]


class SyncMutationResponse(BaseModel):
    server_cursor: str
    device_id: str
    client_mutation_id: str
    client_version: int
    entity_type: MutationType
    entity_id: str
    operation: Literal["UPSERT", "DELETE"]
    payload: dict[str, object]
    created_at: datetime


class SyncPullResponse(BaseModel):
    device_id: str
    cursor: str
    next_cursor: str
    has_more: bool
    items: list[SyncMutationResponse]


class SyncStatusResponse(BaseModel):
    device_id: str
    cursor: str
    last_client_version: int
    server_cursor: str
    updated_at: datetime


class EmergencyResourceResponse(BaseModel):
    id: str
    code: str
    kind: str
    title: str
    description: str
    phone: str | None
    node_id: str | None
    instructions: list[str]
    priority: int
    provider: str = "curated_demo"
    is_demo: bool = True


class EmergencyResourceListResponse(BaseModel):
    items: list[EmergencyResourceResponse]


class EmergencyBulletinResponse(BaseModel):
    id: str
    code: str
    title: str
    content: str
    severity: Literal["INFO", "WARNING", "CRITICAL"]
    starts_at: datetime
    ends_at: datetime
    provider: str = "curated_demo"
    is_demo: bool = True


class EmergencyBulletinListResponse(BaseModel):
    items: list[EmergencyBulletinResponse]


class CreateSosRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["MEDICAL", "LOST", "SAFETY", "OTHER"]
    message: str = Field(min_length=2, max_length=1000)
    node_id: UUID | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    idempotency_key: str = Field(min_length=8, max_length=128)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("message must contain at least two non-whitespace characters")
        return normalized

    @model_validator(mode="after")
    def require_coordinate_pair(self) -> CreateSosRequest:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        return self


class SosTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(default="", max_length=500)


class SosResponse(BaseModel):
    id: str
    sos_no: str
    kind: Literal["MEDICAL", "LOST", "SAFETY", "OTHER"]
    message: str
    status: Literal["DEMO_RECEIVED", "ACKNOWLEDGED", "RESOLVED"]
    node_id: str | None
    latitude: float | None
    longitude: float | None
    provider: Literal["demo_sos"] = "demo_sos"
    is_demo: bool = True
    real_dispatch: Literal[False] = False
    disclaimer: str = "演示 SOS 仅持久化请求, 未联系真实急救或公共安全机构"
    created_at: datetime
    updated_at: datetime


class SosListResponse(BaseModel):
    items: list[SosResponse]


class PassportStampResponse(BaseModel):
    id: str
    code: str
    title: str
    description: str
    node_id: str
    points_award: int
    collected: bool
    collected_at: datetime | None
    provider: str = "demo_checkin"
    is_demo: bool = True


class PassportSummaryResponse(BaseModel):
    collected_count: int
    total_count: int
    points_earned: int
    point_balance: int
    stamps: list[PassportStampResponse]
    provider: str = "demo_checkin"
    is_demo: bool = True


class PassportCheckInRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stamp_code: str = Field(min_length=2, max_length=50)
    idempotency_key: str = Field(min_length=8, max_length=128)


class PassportCheckInResponse(BaseModel):
    stamp: PassportStampResponse
    points_awarded: int
    point_balance: int
    provider: str = "demo_checkin"
    is_demo: bool = True


class GreenTaskResponse(BaseModel):
    id: str
    code: str
    kind: Literal["TRANSPORT", "REFILL", "CULTURE", "RECYCLE"]
    title: str
    description: str
    points_award: int
    evidence_hint: str
    completed: bool
    completed_at: datetime | None
    provider: str = "demo_green_verifier"
    is_demo: bool = True


class GreenTaskListResponse(BaseModel):
    items: list[GreenTaskResponse]
    point_balance: int


class CompleteGreenTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence: str = Field(min_length=2, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=128)


class GreenTaskCompletionResponse(BaseModel):
    id: str
    task_id: str
    task_code: str
    points_awarded: int
    evidence: str
    point_balance: int
    completed_at: datetime
    provider: str = "demo_green_verifier"
    is_demo: bool = True
