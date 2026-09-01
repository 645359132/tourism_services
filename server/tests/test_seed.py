"""Foundation seed idempotency test."""

import json
from hashlib import sha256

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models.commerce import (
    Campaign,
    PointAccount,
    PointLedgerEntry,
    Product,
    ProductInventory,
    Reward,
    ShopCategory,
)
from app.db.models.engagement import FAQ, FacilityPOI
from app.db.models.guide import (
    Attraction,
    CrowdSnapshot,
    Narration,
    RouteEdge,
    RouteNode,
)
from app.db.models.journey import (
    EmergencyBulletin,
    EmergencyResource,
    GreenTask,
    OfflineAsset,
    OfflinePack,
    PassportStampDefinition,
)
from app.db.models.marketplace import (
    BundleComponent,
    Experience,
    ExperienceSession,
    HospitalityOffer,
    HospitalityVenue,
    InventoryBucket,
    QueueCounter,
    UserScheduleLock,
)
from app.db.models.role import Role
from app.db.models.seed_record import SeedRecord
from app.db.models.ticketing import (
    DynamicPriceRule,
    TicketInventory,
    TicketSlot,
    TicketType,
)
from app.db.models.user import User
from app.scripts.seed import DEMO_PASSWORD, seed_database


async def test_foundation_seed_is_idempotent() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    assert await seed_database(session_factory, include_demo_accounts=True) is True

    async with session_factory() as session:
        first_hash = await session.scalar(
            select(User.password_hash).where(User.username == "admin_demo")
        )
        stale_asset = await session.scalar(
            select(OfflineAsset).where(OfflineAsset.asset_key == "narration-core")
        )
        stale_pack = await session.scalar(select(OfflinePack))
        assert stale_asset is not None
        assert stale_pack is not None
        stale_asset.kind = "STALE"
        stale_asset.title = "stale"
        stale_asset.payload = {"stale": True}
        stale_asset.required = False
        stale_asset.content_hash = "0" * 64
        stale_asset.size_bytes = 999
        session.add(
            OfflineAsset(
                pack_id=stale_pack.id,
                asset_key="obsolete-extra",
                kind="OBSOLETE",
                title="obsolete",
                content_hash="f" * 64,
                size_bytes=2,
                required=False,
                payload={"obsolete": True},
            )
        )
        stale_pack.etag = "stale"
        stale_pack.manifest_hash = "stale"
        await session.commit()

    assert await seed_database(session_factory, include_demo_accounts=True) is False

    async with session_factory() as session:
        seed_count = await session.scalar(select(func.count()).select_from(SeedRecord))
        role_count = await session.scalar(select(func.count()).select_from(Role))
        user_count = await session.scalar(select(func.count()).select_from(User))
        ticket_type_count = await session.scalar(select(func.count()).select_from(TicketType))
        slot_count = await session.scalar(select(func.count()).select_from(TicketSlot))
        inventory_count = await session.scalar(select(func.count()).select_from(TicketInventory))
        price_rule_count = await session.scalar(select(func.count()).select_from(DynamicPriceRule))
        attraction_count = await session.scalar(select(func.count()).select_from(Attraction))
        narration_count = await session.scalar(select(func.count()).select_from(Narration))
        route_node_count = await session.scalar(select(func.count()).select_from(RouteNode))
        route_edge_count = await session.scalar(select(func.count()).select_from(RouteEdge))
        crowd_count = await session.scalar(select(func.count()).select_from(CrowdSnapshot))
        experience_count = await session.scalar(select(func.count()).select_from(Experience))
        experience_session_count = await session.scalar(
            select(func.count()).select_from(ExperienceSession)
        )
        venue_count = await session.scalar(select(func.count()).select_from(HospitalityVenue))
        offer_count = await session.scalar(select(func.count()).select_from(HospitalityOffer))
        bundle_component_count = await session.scalar(
            select(func.count()).select_from(BundleComponent)
        )
        shared_bucket_count = await session.scalar(
            select(func.count()).select_from(InventoryBucket)
        )
        queue_counter_count = await session.scalar(select(func.count()).select_from(QueueCounter))
        schedule_lock_count = await session.scalar(
            select(func.count()).select_from(UserScheduleLock)
        )
        category_count = await session.scalar(select(func.count()).select_from(ShopCategory))
        product_count = await session.scalar(select(func.count()).select_from(Product))
        product_inventory_count = await session.scalar(
            select(func.count()).select_from(ProductInventory)
        )
        campaign_count = await session.scalar(select(func.count()).select_from(Campaign))
        reward_count = await session.scalar(select(func.count()).select_from(Reward))
        faq_count = await session.scalar(select(func.count()).select_from(FAQ))
        facility_count = await session.scalar(select(func.count()).select_from(FacilityPOI))
        point_account_count = await session.scalar(select(func.count()).select_from(PointAccount))
        welcome_ledger_count = await session.scalar(
            select(func.count())
            .select_from(PointLedgerEntry)
            .where(PointLedgerEntry.source_type == "WELCOME")
        )
        offline_pack_count = await session.scalar(select(func.count()).select_from(OfflinePack))
        offline_asset_count = await session.scalar(select(func.count()).select_from(OfflineAsset))
        emergency_resource_count = await session.scalar(
            select(func.count()).select_from(EmergencyResource)
        )
        emergency_bulletin_count = await session.scalar(
            select(func.count()).select_from(EmergencyBulletin)
        )
        passport_definition_count = await session.scalar(
            select(func.count()).select_from(PassportStampDefinition)
        )
        green_task_count = await session.scalar(select(func.count()).select_from(GreenTask))
        repaired_asset = await session.scalar(
            select(OfflineAsset).where(OfflineAsset.asset_key == "narration-core")
        )
        repaired_pack = await session.scalar(select(OfflinePack))
        final_assets = list(
            await session.scalars(select(OfflineAsset).order_by(OfflineAsset.asset_key))
        )
        second_hash = await session.scalar(
            select(User.password_hash).where(User.username == "admin_demo")
        )

    assert seed_count == 7
    assert role_count == 4
    assert user_count == 4
    assert ticket_type_count == 4
    assert slot_count == 84
    assert inventory_count == 84
    assert price_rule_count == 2
    assert attraction_count == 8
    assert narration_count == 8
    assert route_node_count == 12
    assert route_edge_count == 15
    assert crowd_count == 8
    assert experience_count == 3
    assert experience_session_count == 63
    assert venue_count == 3
    assert offer_count == 4
    assert bundle_component_count == 2
    assert shared_bucket_count == 121
    assert queue_counter_count == 3
    assert schedule_lock_count == 4
    assert category_count == 3
    assert product_count == 4
    assert product_inventory_count == 4
    assert campaign_count == 1
    assert reward_count == 3
    assert faq_count == 4
    assert facility_count == 4
    assert point_account_count == 4
    assert welcome_ledger_count == 4
    assert offline_pack_count == 1
    assert offline_asset_count == 5
    assert emergency_resource_count == 3
    assert emergency_bulletin_count == 1
    assert passport_definition_count == 3
    assert green_task_count == 4
    assert repaired_asset is not None
    assert repaired_pack is not None
    repaired_encoded = json.dumps(
        repaired_asset.payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert repaired_asset.kind == "NARRATION"
    assert repaired_asset.title == "核心文化离线讲解"
    assert repaired_asset.required is True
    assert repaired_asset.content_hash == sha256(repaired_encoded).hexdigest()
    assert repaired_asset.size_bytes == len(repaired_encoded)
    assert repaired_pack.etag != "stale"
    assert len(repaired_pack.etag) == 64
    assert len(repaired_pack.manifest_hash) == 64
    assert {asset.asset_key for asset in final_assets} == {
        "core-map",
        "culture-intro",
        "emergency-guide",
        "narration-core",
        "travel-guide",
    }
    final_manifest_items = [
        {
            "asset_key": asset.asset_key,
            "content_hash": asset.content_hash,
            "kind": asset.kind,
            "required": asset.required,
            "size_bytes": asset.size_bytes,
            "title": asset.title,
        }
        for asset in final_assets
    ]
    final_manifest_encoded = json.dumps(
        final_manifest_items,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    final_manifest_hash = sha256(final_manifest_encoded).hexdigest()
    assert repaired_pack.manifest_hash == final_manifest_hash
    assert (
        repaired_pack.etag == sha256(f"offline-pack-v1:{final_manifest_hash}".encode()).hexdigest()
    )
    assert first_hash == second_hash
    assert first_hash != DEMO_PASSWORD
    await engine.dispose()
