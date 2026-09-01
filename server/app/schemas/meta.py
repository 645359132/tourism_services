"""Public role capability metadata contract."""

from pydantic import BaseModel


class ProviderCapability(BaseModel):
    mode: str
    is_demo: bool
    description: str


class CapabilitiesResponse(BaseModel):
    roles: dict[str, list[str]]
    providers: dict[str, ProviderCapability]
