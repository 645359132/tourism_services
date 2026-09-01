"""Idempotent foundation seed command.

Run after ``alembic upgrade head`` with ``uv run tourism-seed`` or
``uv run python -m app.scripts.seed``.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.models.preference import TouristPreference
from app.db.models.role import Role, UserRole
from app.db.models.seed_record import SeedRecord
from app.db.models.user import User
from app.db.session import dispose_database, get_session_factory

FOUNDATION_SEED_KEY = "foundation-v1"
AUTH_DEMO_SEED_KEY = "auth-demo-v1"
DEMO_PASSWORD = "Tourism123!"
ROLE_DESCRIPTIONS = {
    "tourist": "Visitor using tourism discovery and personalization features",
    "merchant": "Tourism service merchant operator",
    "support": "Customer support operator",
    "admin": "Platform administrator",
}
DEMO_ACCOUNTS = (
    ("tourist_demo", "游客演示账号", "tourist"),
    ("merchant_demo", "商户演示账号", "merchant"),
    ("support_demo", "客服演示账号", "support"),
    ("admin_demo", "管理员演示账号", "admin"),
)


async def seed_database(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    *,
    include_demo_accounts: bool | None = None,
) -> bool:
    """Apply foundation data and explicitly enabled non-production demos."""

    factory = session_factory or get_session_factory()
    demos_enabled = (
        get_settings().enable_demo_accounts
        if include_demo_accounts is None
        else include_demo_accounts
    )
    async with factory() as session:
        inserted = False
        foundation_seed = await session.get(SeedRecord, FOUNDATION_SEED_KEY)
        if foundation_seed is None:
            session.add(
                SeedRecord(
                    key=FOUNDATION_SEED_KEY,
                    description="Smart Tourism Service foundation initialized",
                )
            )
            inserted = True

        auth_seed = await session.get(SeedRecord, AUTH_DEMO_SEED_KEY)
        if demos_enabled and auth_seed is None:
            roles: dict[str, Role] = {}
            for role_name, description in ROLE_DESCRIPTIONS.items():
                role = await session.scalar(select(Role).where(Role.name == role_name))
                if role is None:
                    role = Role(name=role_name, description=description)
                    session.add(role)
                    await session.flush()
                roles[role_name] = role

            for username, display_name, role_name in DEMO_ACCOUNTS:
                user = await session.scalar(select(User).where(User.username == username))
                if user is None:
                    user = User(
                        username=username,
                        display_name=display_name,
                        password_hash=hash_password(DEMO_PASSWORD),
                        is_active=True,
                    )
                    session.add(user)
                    await session.flush()

                role = roles[role_name]
                assignment = await session.get(
                    UserRole,
                    {"user_id": user.id, "role_id": role.id},
                )
                if assignment is None:
                    session.add(UserRole(user_id=user.id, role_id=role.id))

                if role_name == "tourist":
                    preference = await session.get(TouristPreference, user.id)
                    if preference is None:
                        session.add(
                            TouristPreference(
                                user_id=user.id,
                                preferred_language="zh-CN",
                                interests=[],
                                accessibility_needs=[],
                                notifications_enabled=True,
                            )
                        )

            session.add(
                SeedRecord(
                    key=AUTH_DEMO_SEED_KEY,
                    description="Explicitly enabled local authentication demos initialized",
                )
            )
            inserted = True

        await session.commit()
        return inserted


async def _main() -> None:
    inserted = await seed_database()
    print("Application seed applied." if inserted else "Application seed already applied.")
    await dispose_database()


def run() -> None:
    """Synchronous console-script adapter."""

    asyncio.run(_main())


if __name__ == "__main__":
    run()
