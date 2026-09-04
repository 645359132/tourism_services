"""Create deterministic, isolated tourist identities for local load tests.

The command intentionally refuses to run outside development/test.  It reuses one
Argon2 hash for the requested local-only password so creating a large identity pool
does not spend minutes hashing the same synthetic credential.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.security import hash_password, verify_password
from app.db.models.preference import TouristPreference
from app.db.models.role import Role, UserRole
from app.db.models.user import User
from app.db.session import dispose_database, get_session_factory
from app.scripts.seed import seed_database

DEFAULT_LOAD_USER_COUNT = 100
DEFAULT_LOAD_USER_PREFIX = "load_tourist_"
MAX_LOAD_USER_COUNT = 10_000
_PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,48}$")


@dataclass(frozen=True, slots=True)
class LoadSeedResult:
    """Summary of one idempotent load-user seed operation."""

    requested: int
    created: int
    repaired: int

    @property
    def unchanged(self) -> int:
        return self.requested - self.created - self.repaired


def load_username(index: int, *, prefix: str = DEFAULT_LOAD_USER_PREFIX) -> str:
    """Return the stable one-based username used by the Locust allocator."""

    if index < 1 or index > MAX_LOAD_USER_COUNT:
        raise ValueError(f"load-user index must be between 1 and {MAX_LOAD_USER_COUNT}")
    if not _PREFIX_PATTERN.fullmatch(prefix):
        raise ValueError("load-user prefix must contain 1-48 ASCII letters, digits, or underscores")
    username = f"{prefix}{index:05d}"
    if len(username) > 64:
        raise ValueError("load-user prefix produces usernames longer than 64 characters")
    return username


def _validated_count(value: int) -> int:
    if value < 1 or value > MAX_LOAD_USER_COUNT:
        raise ValueError(f"load-user count must be between 1 and {MAX_LOAD_USER_COUNT}")
    return value


def _id_chunks(values: list[UUID], *, size: int = 500) -> Iterator[list[UUID]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


async def seed_load_users(
    *,
    count: int = DEFAULT_LOAD_USER_COUNT,
    prefix: str = DEFAULT_LOAD_USER_PREFIX,
    password: str,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> LoadSeedResult:
    """Insert or repair the deterministic load-user pool without deleting data."""

    _validated_count(count)
    usernames = [load_username(index, prefix=prefix) for index in range(1, count + 1)]
    username_set = set(usernames)
    if len(password) < 12:
        raise ValueError("load-user password must contain at least 12 characters")

    factory = session_factory or get_session_factory()
    async with factory() as session:
        tourist_role = await session.scalar(select(Role).where(Role.name == "tourist"))
        if tourist_role is None:
            raise RuntimeError("tourist role is missing; run the application seed first")

        existing_users = list(
            await session.scalars(
                select(User).where(User.username.startswith(prefix, autoescape=True))
            )
        )
        existing_by_name = {user.username: user for user in existing_users}
        target_existing_ids = [
            user.id for username, user in existing_by_name.items() if username in username_set
        ]
        linked_user_ids: set[UUID] = set()
        preferred_user_ids: set[UUID] = set()
        for chunk in _id_chunks(target_existing_ids):
            linked_user_ids.update(
                await session.scalars(
                    select(UserRole.user_id).where(
                        UserRole.role_id == tourist_role.id,
                        UserRole.user_id.in_(chunk),
                    )
                )
            )
            preferred_user_ids.update(
                await session.scalars(
                    select(TouristPreference.user_id).where(TouristPreference.user_id.in_(chunk))
                )
            )
        password_hash = hash_password(password)
        password_matches: dict[str, bool] = {}
        created = 0
        repaired = 0

        for index, username in enumerate(usernames, start=1):
            user = existing_by_name.get(username)
            if user is None:
                user = User(
                    id=uuid4(),
                    username=username,
                    display_name=f"压测游客 {index:05d}",
                    password_hash=password_hash,
                    is_active=True,
                )
                session.add(user)
                session.add(UserRole(user_id=user.id, role_id=tourist_role.id))
                session.add(
                    TouristPreference(
                        user_id=user.id,
                        preferred_language="zh-CN",
                        interests=[],
                        accessibility_needs=[],
                        notifications_enabled=False,
                    )
                )
                created += 1
                continue

            changed = False
            matches = password_matches.get(user.password_hash)
            if matches is None:
                matches = verify_password(password, user.password_hash)
                password_matches[user.password_hash] = matches
            if not matches:
                user.password_hash = password_hash
                changed = True
            if not user.is_active:
                user.is_active = True
                changed = True
            if user.id not in linked_user_ids:
                session.add(UserRole(user_id=user.id, role_id=tourist_role.id))
                changed = True
            if user.id not in preferred_user_ids:
                session.add(
                    TouristPreference(
                        user_id=user.id,
                        preferred_language="zh-CN",
                        interests=[],
                        accessibility_needs=[],
                        notifications_enabled=False,
                    )
                )
                changed = True
            if changed:
                repaired += 1

        await session.commit()
        return LoadSeedResult(requested=count, created=created, repaired=repaired)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--count",
        type=int,
        default=int(os.getenv("TOURISM_LOAD_USER_COUNT", str(DEFAULT_LOAD_USER_COUNT))),
        help=f"number of identities to ensure (1-{MAX_LOAD_USER_COUNT})",
    )
    parser.add_argument(
        "--prefix",
        default=os.getenv("TOURISM_LOAD_USER_PREFIX", DEFAULT_LOAD_USER_PREFIX),
        help="username prefix shared with server/load/locustfile.py",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("TOURISM_LOAD_USER_PASSWORD"),
        help="local synthetic password (or set TOURISM_LOAD_USER_PASSWORD)",
    )
    return parser


async def _main(args: argparse.Namespace) -> None:
    try:
        settings: Settings = get_settings()
        if settings.app_env not in {"development", "test"}:
            raise RuntimeError("load-user seeding is restricted to development/test environments")
        if not args.password:
            raise RuntimeError(
                "set TOURISM_LOAD_USER_PASSWORD or pass --password before seeding load users"
            )

        await seed_database(include_demo_accounts=True)
        result = await seed_load_users(
            count=args.count,
            prefix=args.prefix,
            password=args.password,
        )
        print(
            "Load identities ready: "
            f"requested={result.requested} created={result.created} "
            f"repaired={result.repaired} unchanged={result.unchanged}."
        )
    finally:
        await dispose_database()


def run() -> None:
    """Synchronous console-script adapter."""

    args = _parser().parse_args()
    asyncio.run(_main(args))


if __name__ == "__main__":
    run()
