"""Deterministic demo payment provider; it never moves real funds."""

from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True, slots=True)
class DemoPaymentResult:
    reference: str
    status: str = "SUCCEEDED"
    is_demo: bool = True


class DemoPaymentProvider:
    """Local provider boundary with deterministic idempotent authorization."""

    async def authorize(
        self,
        *,
        order_no: str,
        amount_cents: int,
        idempotency_key: str,
    ) -> DemoPaymentResult:
        if amount_cents <= 0:
            raise ValueError("Demo payment amount must be positive")
        digest = sha256(f"{order_no}:{amount_cents}:{idempotency_key}".encode()).hexdigest()[:24]
        return DemoPaymentResult(reference=f"demo_pay_{digest}")
