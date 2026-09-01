"""Explicit demo-only emergency, passport, and green verification providers."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True, slots=True)
class DemoEmergencyDispatch:
    reference: str
    status: str = "DEMO_RECEIVED"
    provider: str = "demo_sos"
    is_demo: bool = True
    dispatched_real_services: bool = False


class DemoEmergencyProvider:
    """Record an SOS demo without contacting real emergency services."""

    async def submit(
        self,
        *,
        user_id: str,
        kind: str,
        message: str,
        idempotency_key: str,
    ) -> DemoEmergencyDispatch:
        digest = sha256(f"{user_id}:{kind}:{message}:{idempotency_key}".encode()).hexdigest()[:20]
        return DemoEmergencyDispatch(reference=f"demo_sos_{digest}")


@dataclass(frozen=True, slots=True)
class DemoVerification:
    verified: bool
    provider: str
    is_demo: bool = True


class DemoCheckInVerifier:
    """Deterministic local check-in boundary; no geofence or gate is contacted."""

    async def verify(self, *, stamp_code: str) -> DemoVerification:
        return DemoVerification(
            verified=bool(stamp_code.strip()),
            provider="demo_checkin",
        )


class DemoGreenTaskVerifier:
    """Deterministic evidence boundary; it does not certify real-world behavior."""

    async def verify(self, *, evidence: str) -> DemoVerification:
        return DemoVerification(
            verified=len(evidence.strip()) >= 2,
            provider="demo_green_verifier",
        )
