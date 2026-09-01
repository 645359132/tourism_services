"""Public, non-user-specific role capability metadata."""

from fastapi import APIRouter

from app.schemas.meta import CapabilitiesResponse, ProviderCapability

router = APIRouter(prefix="/meta", tags=["metadata"])

ROLE_CAPABILITIES: dict[str, list[str]] = {
    "admin": ["*"],
    "merchant": ["merchant:manage", "profile:read"],
    "support": ["profile:read", "support:assist"],
    "tourist": ["preferences:read", "preferences:write", "profile:read"],
}

PROVIDER_CAPABILITIES: dict[str, ProviderCapability] = {
    "ai": ProviderCapability(
        mode="rules",
        is_demo=True,
        description="Deterministic local rules; no external AI provider is connected",
    ),
    "crowd": ProviderCapability(
        mode="simulated",
        is_demo=True,
        description="Synthetic crowd levels for MVP demonstrations",
    ),
    "gate": ProviderCapability(
        mode="demo",
        is_demo=True,
        description="Demo gate workflow without physical turnstile integration",
    ),
    "map": ProviderCapability(
        mode="schematic",
        is_demo=True,
        description="Schematic local map data without a live map provider",
    ),
    "merchant": ProviderCapability(
        mode="demo",
        is_demo=True,
        description="Local demo merchant data without an external marketplace",
    ),
    "notification": ProviderCapability(
        mode="in_process",
        is_demo=True,
        description="In-process notifications without an external delivery provider",
    ),
    "payment": ProviderCapability(
        mode="demo",
        is_demo=True,
        description="Demo payment flow that never moves real funds",
    ),
}


@router.get("/capabilities", response_model=CapabilitiesResponse)
async def capabilities() -> CapabilitiesResponse:
    """Return stable UI metadata; backend authorization remains authoritative."""

    return CapabilitiesResponse(
        roles=ROLE_CAPABILITIES,
        providers=PROVIDER_CAPABILITIES,
    )
