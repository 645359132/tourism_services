"""Deterministic shortest paths over the local schematic guide graph."""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.guide import RouteEdge, RouteNode


class NoSchematicRouteError(Exception):
    """Raised when accessibility filters disconnect the requested nodes."""


@dataclass(frozen=True, slots=True)
class SchematicRoute:
    node_ids: list[UUID]
    edge_ids: list[UUID]
    distance_m: int
    walk_minutes: int
    accessible: bool
    explanation: list[str]


class SchematicMapProvider:
    """Local graph provider; it does not represent live navigation data."""

    mode = "schematic"
    is_demo = True
    description = "Connected local schematic graph; no live map provider"

    async def route(
        self,
        session: AsyncSession,
        *,
        from_node_id: UUID,
        to_node_id: UUID,
        wheelchair: bool,
        stroller: bool,
    ) -> SchematicRoute:
        nodes = {node.id: node for node in await session.scalars(select(RouteNode))}
        if from_node_id not in nodes or to_node_id not in nodes:
            raise NoSchematicRouteError("Route endpoint is missing from the schematic graph")
        constrained = wheelchair or stroller
        if constrained and (not nodes[from_node_id].accessible or not nodes[to_node_id].accessible):
            raise NoSchematicRouteError("Route endpoint is not accessible for the requested mode")
        if from_node_id == to_node_id:
            return SchematicRoute(
                node_ids=[from_node_id],
                edge_ids=[],
                distance_m=0,
                walk_minutes=0,
                accessible=True,
                explanation=["Origin and destination are the same schematic node"],
            )

        edges = list(await session.scalars(select(RouteEdge)))
        adjacency: dict[UUID, list[tuple[UUID, RouteEdge]]] = {node_id: [] for node_id in nodes}
        for edge in edges:
            if wheelchair and not edge.wheelchair_ok:
                continue
            if stroller and not edge.stroller_ok:
                continue
            if constrained and (
                not nodes[edge.from_node_id].accessible or not nodes[edge.to_node_id].accessible
            ):
                continue
            adjacency[edge.from_node_id].append((edge.to_node_id, edge))
            if edge.bidirectional:
                adjacency[edge.to_node_id].append((edge.from_node_id, edge))

        distances: dict[UUID, tuple[int, int]] = {from_node_id: (0, 0)}
        previous: dict[UUID, tuple[UUID, RouteEdge]] = {}
        queue: list[tuple[int, int, str, UUID]] = [(0, 0, str(from_node_id), from_node_id)]
        while queue:
            minutes, meters, _, node_id = heapq.heappop(queue)
            if distances.get(node_id) != (minutes, meters):
                continue
            if node_id == to_node_id:
                break
            for next_id, edge in sorted(
                adjacency[node_id],
                key=lambda pair: (pair[1].walk_minutes, str(pair[0])),
            ):
                candidate = (minutes + edge.walk_minutes, meters + edge.distance_meters)
                if next_id not in distances or candidate < distances[next_id]:
                    distances[next_id] = candidate
                    previous[next_id] = (node_id, edge)
                    heapq.heappush(queue, (*candidate, str(next_id), next_id))

        if to_node_id not in distances:
            raise NoSchematicRouteError("No route satisfies the accessibility requirements")

        node_ids = [to_node_id]
        edge_ids: list[UUID] = []
        cursor = to_node_id
        while cursor != from_node_id:
            parent, edge = previous[cursor]
            edge_ids.append(edge.id)
            node_ids.append(parent)
            cursor = parent
        node_ids.reverse()
        edge_ids.reverse()
        walk_minutes, distance_m = distances[to_node_id]
        filters = []
        if wheelchair:
            filters.append("wheelchair-safe edges")
        if stroller:
            filters.append("stroller-safe edges")
        explanation = [
            "Shortest deterministic path over the local schematic graph",
            f"Applied: {', '.join(filters)}" if filters else "No accessibility edge filter",
        ]
        return SchematicRoute(
            node_ids=node_ids,
            edge_ids=edge_ids,
            distance_m=distance_m,
            walk_minutes=walk_minutes,
            accessible=wheelchair or stroller,
            explanation=explanation,
        )
