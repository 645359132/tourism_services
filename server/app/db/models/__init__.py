"""Model imports used to populate SQLAlchemy metadata."""

from app.db.models.guide import (
    Attraction,
    ConflictCheck,
    CrowdSnapshot,
    Itinerary,
    ItineraryItem,
    Narration,
    PlanRun,
    RouteEdge,
    RouteNode,
)
from app.db.models.preference import TouristPreference
from app.db.models.refresh_session import RefreshSession
from app.db.models.role import Role, UserRole
from app.db.models.seed_record import SeedRecord
from app.db.models.ticketing import (
    DynamicPriceRule,
    ElectronicTicket,
    RefundRequest,
    RescheduleRequest,
    TicketInventory,
    TicketOrder,
    TicketOrderItem,
    TicketSlot,
    TicketType,
    TicketValidation,
)
from app.db.models.user import User

__all__ = [
    "Attraction",
    "ConflictCheck",
    "CrowdSnapshot",
    "DynamicPriceRule",
    "ElectronicTicket",
    "Itinerary",
    "ItineraryItem",
    "Narration",
    "PlanRun",
    "RefreshSession",
    "RefundRequest",
    "RescheduleRequest",
    "Role",
    "RouteEdge",
    "RouteNode",
    "SeedRecord",
    "TicketInventory",
    "TicketOrder",
    "TicketOrderItem",
    "TicketSlot",
    "TicketType",
    "TicketValidation",
    "TouristPreference",
    "User",
    "UserRole",
]
