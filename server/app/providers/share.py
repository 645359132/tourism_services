"""Explicit deterministic share verification boundary for local demos."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ShareVerification:
    verified: bool
    points_awarded: int
    provider: str = "demo_share_verifier"
    is_demo: bool = True


class DemoShareVerifier:
    """Verify well-formed local demo shares without calling a social platform."""

    async def verify(
        self,
        *,
        content_type: str,
        ref_id: str,
        platform: str,
        caption: str,
    ) -> ShareVerification:
        verified = all(value.strip() for value in (content_type, ref_id, platform))
        return ShareVerification(
            verified=verified,
            points_awarded=25 if verified else 0,
        )
