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
    description = "使用本地示意图, 未接入实时地图服务"

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
            raise NoSchematicRouteError("路线起点或终点不在本地示意图中")
        constrained = wheelchair or stroller
        if constrained and (not nodes[from_node_id].accessible or not nodes[to_node_id].accessible):
            raise NoSchematicRouteError("所选出行方式无法通行路线起点或终点")
        if from_node_id == to_node_id:
            return SchematicRoute(
                node_ids=[from_node_id],
                edge_ids=[],
                distance_m=0,
                walk_minutes=0,
                accessible=True,
                explanation=["起点与终点为同一个示意节点"],
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
            raise NoSchematicRouteError("没有符合无障碍要求的可用路线")

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
            filters.append("轮椅可通行路段")
        if stroller:
            filters.append("婴儿车可通行路段")
        explanation = [
            "基于本地示意图计算的确定性最短路线",
            f"已应用: {'、'.join(filters)}" if filters else "未应用无障碍路段筛选",
        ]
        return SchematicRoute(
            node_ids=node_ids,
            edge_ids=edge_ids,
            distance_m=distance_m,
            walk_minutes=walk_minutes,
            accessible=wheelchair or stroller,
            explanation=explanation,
        )
