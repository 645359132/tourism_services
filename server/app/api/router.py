"""Top-level API router composition."""

from fastapi import APIRouter

from app.api.routes.auth import router as auth_router
from app.api.routes.guide import router as guide_router
from app.api.routes.health import router as health_router
from app.api.routes.itineraries import router as itineraries_router
from app.api.routes.marketplace import router as marketplace_router
from app.api.routes.meta import router as meta_router
from app.api.routes.ticketing import router as ticketing_router
from app.api.routes.users import router as users_router

api_router = APIRouter()
api_router.include_router(health_router)

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(auth_router)
v1_router.include_router(users_router)
v1_router.include_router(meta_router)
v1_router.include_router(ticketing_router)
v1_router.include_router(guide_router)
v1_router.include_router(itineraries_router)
v1_router.include_router(marketplace_router)
api_router.include_router(v1_router)
