"""Guide catalog, schematic map, and explicitly simulated crowd services."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.db.models.guide import (
    Attraction,
    CrowdSnapshot,
    Narration,
    RouteEdge,
    RouteNode,
)
from app.providers.map import NoSchematicRouteError, SchematicMapProvider
from app.schemas.guide import (
    AttractionResponse,
    CrowdItemResponse,
    CrowdResponse,
    CrowdWebSocketEnvelope,
    MapEdgeResponse,
    MapNodeResponse,
    MapProviderResponse,
    MapResponse,
    NarrationResponse,
    RoutePlanResponse,
    RouteProviderResponse,
)


def _error(status_code: int, code: str, message: str) -> AppError:
    return AppError(status_code=status_code, code=code, message=message)


async def latest_crowd_by_attraction(
    session: AsyncSession,
) -> tuple[int, dict[UUID, CrowdSnapshot]]:
    sequence = int(await session.scalar(select(func.max(CrowdSnapshot.sequence))) or 0)
    if sequence == 0:
        return 0, {}
    snapshots = list(
        await session.scalars(select(CrowdSnapshot).where(CrowdSnapshot.sequence == sequence))
    )
    return sequence, {snapshot.attraction_id: snapshot for snapshot in snapshots}


def _crowd_item(snapshot: CrowdSnapshot) -> CrowdItemResponse:
    return CrowdItemResponse(
        attraction_id=str(snapshot.attraction_id),
        captured_at=snapshot.observed_at,
        people_count=snapshot.people_count,
        occupancy_bps=snapshot.occupancy_bps,
        level=snapshot.crowd_level,
        wait_minutes=snapshot.wait_minutes,
        source="simulated",
    )


async def crowd_response(session: AsyncSession) -> CrowdResponse:
    sequence, snapshots = await latest_crowd_by_attraction(session)
    items = [_crowd_item(snapshot) for snapshot in snapshots.values()]
    items.sort(key=lambda item: item.attraction_id)
    return CrowdResponse(
        items=items,
        sequence=sequence,
        captured_at=max(
            (item.captured_at for item in items),
            default=datetime.now(UTC),
        ),
        source="simulated",
        is_demo=True,
    )


async def list_attractions(session: AsyncSession) -> list[AttractionResponse]:
    attractions = list(
        await session.scalars(
            select(Attraction)
            .options(selectinload(Attraction.narrations))
            .where(Attraction.is_active.is_(True))
            .order_by(Attraction.code)
        )
    )
    _, crowds = await latest_crowd_by_attraction(session)
    nodes = list(
        await session.scalars(select(RouteNode).where(RouteNode.attraction_id.is_not(None)))
    )
    node_by_attraction = {node.attraction_id: node for node in nodes}
    responses: list[AttractionResponse] = []
    for attraction in attractions:
        crowd = crowds.get(attraction.id)
        node = node_by_attraction.get(attraction.id)
        if crowd is None or node is None:
            continue
        responses.append(
            AttractionResponse(
                id=str(attraction.id),
                code=attraction.code,
                name=attraction.name,
                category=attraction.category,
                description=attraction.description,
                visit_minutes=attraction.visit_minutes,
                crowd_level=crowd.crowd_level,
                occupancy_bps=crowd.occupancy_bps,
                wait_minutes=crowd.wait_minutes,
                tags=attraction.tags,
                accessibility=attraction.accessibility,
                x=attraction.x,
                y=attraction.y,
                narration_available=bool(attraction.narrations),
                node_id=str(node.id),
            )
        )
    return responses


async def get_attraction(session: AsyncSession, attraction_id: UUID) -> AttractionResponse:
    items = await list_attractions(session)
    match = next((item for item in items if item.id == str(attraction_id)), None)
    if match is None:
        raise _error(404, "ATTRACTION_NOT_FOUND", "Attraction not found")
    return match


async def list_narrations(
    session: AsyncSession,
    attraction_id: UUID,
) -> list[NarrationResponse]:
    exists = await session.get(Attraction, attraction_id)
    if exists is None:
        raise _error(404, "ATTRACTION_NOT_FOUND", "Attraction not found")
    narrations = list(
        await session.scalars(
            select(Narration)
            .where(Narration.attraction_id == attraction_id)
            .order_by(Narration.language)
        )
    )
    return [
        NarrationResponse(
            id=str(narration.id),
            attraction_id=str(narration.attraction_id),
            language=narration.language,
            title=narration.title,
            transcript=narration.transcript,
            audio_url=narration.audio_url or "",
            duration_seconds=narration.duration_seconds,
            provider_mode="text_demo",
            is_demo=True,
        )
        for narration in narrations
    ]


async def map_response(session: AsyncSession) -> MapResponse:
    nodes = list(await session.scalars(select(RouteNode).order_by(RouteNode.code)))
    edges = list(await session.scalars(select(RouteEdge).order_by(RouteEdge.id)))
    return MapResponse(
        provider=MapProviderResponse(),
        nodes=[
            MapNodeResponse(
                id=str(node.id),
                code=node.code,
                name=node.name,
                kind=node.kind,
                attraction_id=str(node.attraction_id) if node.attraction_id else None,
                x=node.x,
                y=node.y,
                accessibility=["wheelchair", "stroller"] if node.accessible else [],
            )
            for node in nodes
        ],
        edges=[
            MapEdgeResponse(
                id=str(edge.id),
                from_node_id=str(edge.from_node_id),
                to_node_id=str(edge.to_node_id),
                distance_m=edge.distance_meters,
                walk_minutes=edge.walk_minutes,
                wheelchair_ok=edge.wheelchair_ok,
                stroller_ok=edge.stroller_ok,
                bidirectional=edge.bidirectional,
            )
            for edge in edges
        ],
    )


async def plan_route(
    session: AsyncSession,
    *,
    from_node_id: UUID,
    to_node_id: UUID,
    wheelchair: bool,
    stroller: bool,
    provider: SchematicMapProvider | None = None,
) -> RoutePlanResponse:
    map_provider = provider or SchematicMapProvider()
    try:
        route = await map_provider.route(
            session,
            from_node_id=from_node_id,
            to_node_id=to_node_id,
            wheelchair=wheelchair,
            stroller=stroller,
        )
    except NoSchematicRouteError as exc:
        raise _error(409, "NO_ACCESSIBLE_ROUTE", str(exc)) from exc
    return RoutePlanResponse(
        node_ids=[str(node_id) for node_id in route.node_ids],
        distance_m=route.distance_m,
        walk_minutes=route.walk_minutes,
        accessible=route.accessible,
        explanation=route.explanation,
        provider=RouteProviderResponse(
            mode=map_provider.mode,
            is_demo=map_provider.is_demo,
            description=map_provider.description,
        ),
    )


def _crowd_level(occupancy_bps: int) -> str:
    if occupancy_bps < 4_000:
        return "LOW"
    if occupancy_bps < 7_000:
        return "MEDIUM"
    return "HIGH"


async def simulate_crowd_tick(session: AsyncSession) -> CrowdResponse:
    """Persist one deterministic simulated sequence; no sensor data is involved."""

    sequence, current = await latest_crowd_by_attraction(session)
    attractions = list(
        await session.scalars(
            select(Attraction).where(Attraction.is_active.is_(True)).order_by(Attraction.code)
        )
    )
    next_sequence = sequence + 1
    captured_at = datetime.now(UTC)
    for index, attraction in enumerate(attractions):
        previous = current.get(attraction.id)
        prior_occupancy = previous.occupancy_bps if previous else 3_000
        delta = ((next_sequence * 733 + index * 977) % 2_000) - 850
        occupancy = max(500, min(9_500, prior_occupancy + delta))
        session.add(
            CrowdSnapshot(
                attraction_id=attraction.id,
                crowd_level=_crowd_level(occupancy),
                occupancy_bps=occupancy,
                people_count=max(0, occupancy // 20),
                wait_minutes=max(0, occupancy // 450),
                source="simulated",
                sequence=next_sequence,
                observed_at=captured_at,
            )
        )
    await session.commit()
    return await crowd_response(session)


def crowd_envelope(response: CrowdResponse) -> CrowdWebSocketEnvelope:
    return CrowdWebSocketEnvelope(
        id=str(uuid4()),
        type="crowd.snapshot",
        occurred_at=datetime.now(UTC),
        data=response.model_dump(mode="json"),
    )
