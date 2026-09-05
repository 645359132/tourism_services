"""Deterministic itinerary generation, conflict checks, and crowd replanning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.db.models.guide import (
    Attraction,
    ConflictCheck,
    CrowdSnapshot,
    Itinerary,
    ItineraryItem,
    PlanRun,
    RouteNode,
)
from app.db.models.user import User
from app.providers.map import NoSchematicRouteError, SchematicMapProvider
from app.providers.planner import PlanningPreferences, RulesPlanner, ScoredAttraction
from app.schemas.guide import (
    ConflictCheckResponse,
    ConflictSuggestionResponse,
    GenerateItineraryRequest,
    ItineraryConflictResponse,
    ItineraryItemResponse,
    ItineraryResponse,
    ReplanItineraryRequest,
)
from app.services.guide import latest_crowd_by_attraction

SCENIC_TIMEZONE = ZoneInfo("Asia/Shanghai")
DEFAULT_WALKING_BUFFER_MINUTES = 10


@dataclass(frozen=True, slots=True)
class Commitment:
    order_id: UUID
    title: str
    start_at: datetime
    end_at: datetime


def _error(status_code: int, code: str, message: str) -> AppError:
    return AppError(status_code=status_code, code=code, message=message)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _is_legacy_admission_commitment(item: ItineraryItem) -> bool:
    """Identify ordinary admission windows persisted as commitments by older builds."""

    return item.kind == "COMMITMENT" and item.ref_type == "ticket_order"


def _overlaps(
    first_start: datetime,
    first_end: datetime,
    second_start: datetime,
    second_end: datetime,
) -> bool:
    """Half-open interval overlap: touching endpoints are not a conflict."""

    # 创新点 3: 统一采用 [start, end) 半开区间, 前一项目结束即后一项目开始时不误报冲突。
    return first_start < second_end and second_start < first_end


def _itinerary_statement():
    return (
        select(Itinerary)
        .options(selectinload(Itinerary.items))
        .execution_options(populate_existing=True)
    )


async def _load_itinerary(session: AsyncSession, itinerary_id: UUID) -> Itinerary | None:
    return await session.scalar(_itinerary_statement().where(Itinerary.id == itinerary_id))


async def _owned_itinerary(
    session: AsyncSession,
    *,
    itinerary_id: UUID,
    user: User,
) -> Itinerary:
    itinerary = await _load_itinerary(session, itinerary_id)
    if itinerary is None or (itinerary.user_id != user.id and "admin" not in user.role_names):
        raise _error(404, "ITINERARY_NOT_FOUND", "未找到该行程")
    return itinerary


def itinerary_response(itinerary: Itinerary) -> ItineraryResponse:
    # 旧版本把普通门票的开放窗口保存成独占行程项。响应边界先隐藏这类历史项,
    # 避免升级后恢复的本地缓存继续展示“全天被门票占用”。
    items = sorted(
        (item for item in itinerary.items if not _is_legacy_admission_commitment(item)),
        key=lambda item: item.ordinal,
    )
    return ItineraryResponse(
        id=str(itinerary.id),
        name=itinerary.name,
        visit_date=itinerary.visit_date,
        status=itinerary.status,
        source=itinerary.source,
        revision=itinerary.revision,
        total_score=itinerary.total_score,
        explanation=itinerary.explanation,
        is_complete=itinerary.is_complete,
        unscheduled_reasons=itinerary.unscheduled_reasons,
        items=[
            ItineraryItemResponse(
                id=str(item.id),
                ordinal=item.ordinal,
                kind=item.kind,
                ref_id=str(item.ref_id),
                title=item.title,
                # SQLite 读回 timezone=True 字段时可能丢失 tzinfo; 响应边界统一补回 UTC。
                start_at=_aware(item.start_at),
                end_at=_aware(item.end_at),
                locked=item.locked,
                crowd_level=item.crowd_level,
                walk_minutes=item.walk_minutes,
                explanation=item.explanation,
            )
            for item in items
        ],
    )


async def _scored_candidates(
    session: AsyncSession,
    *,
    preferences: PlanningPreferences,
    map_provider: SchematicMapProvider,
    planner: RulesPlanner,
) -> tuple[list[ScoredAttraction], dict[UUID, RouteNode], list[str]]:
    attractions = list(
        await session.scalars(
            select(Attraction).where(Attraction.is_active.is_(True)).order_by(Attraction.code)
        )
    )
    nodes = list(await session.scalars(select(RouteNode)))
    node_by_attraction = {
        node.attraction_id: node for node in nodes if node.attraction_id is not None
    }
    entrance = next((node for node in nodes if node.kind == "ENTRANCE"), None)
    if entrance is None:
        raise _error(500, "GUIDE_GRAPH_INVALID", "本地示意图缺少入口节点")
    _, crowds = await latest_crowd_by_attraction(session)
    scored: list[ScoredAttraction] = []
    excluded: list[str] = []
    for attraction in attractions:
        node = node_by_attraction.get(attraction.id)
        crowd = crowds.get(attraction.id)
        if node is None or crowd is None:
            excluded.append(f"{attraction.name}: 缺少示意图或模拟人流数据")
            continue
        if preferences.accessible and (
            "wheelchair" not in attraction.accessibility or not node.accessible
        ):
            excluded.append(f"{attraction.name}: 暂不支持轮椅无障碍通行")
            continue
        try:
            route = await map_provider.route(
                session,
                from_node_id=entrance.id,
                to_node_id=node.id,
                wheelchair=preferences.accessible,
                stroller=preferences.companion_type == "family",
            )
        except NoSchematicRouteError:
            excluded.append(f"{attraction.name}: 没有可用的无障碍示意路线")
            continue
        scored.append(
            planner.score_candidate(
                attraction=attraction,
                crowd=crowd,
                walk_minutes=route.walk_minutes,
                preferences=preferences,
            )
        )
    # 创新点 1: 分数降序、景点代码兜底, 相同数据下候选顺序稳定且可复验。
    scored.sort(key=lambda item: (-item.score, item.attraction.code))
    return scored, node_by_attraction, excluded


def _find_start(
    *,
    cursor: datetime,
    walk_minutes: int,
    visit_minutes: int,
    commitments: list[Commitment],
    plan_end: datetime,
) -> tuple[datetime, datetime] | None:
    # 将步行和缓冲计入游览区间; 遇到锁定承诺时整体后移, 而不是改动承诺本身。
    transition = walk_minutes + DEFAULT_WALKING_BUFFER_MINUTES
    start_at = cursor + timedelta(minutes=transition)
    while True:
        end_at = start_at + timedelta(minutes=visit_minutes)
        conflict = next(
            (
                commitment
                for commitment in commitments
                if _overlaps(
                    start_at,
                    end_at,
                    commitment.start_at - timedelta(minutes=DEFAULT_WALKING_BUFFER_MINUTES),
                    commitment.end_at + timedelta(minutes=DEFAULT_WALKING_BUFFER_MINUTES),
                )
            ),
            None,
        )
        if conflict is None:
            return (start_at, end_at) if end_at <= plan_end else None
        start_at = conflict.end_at + timedelta(minutes=DEFAULT_WALKING_BUFFER_MINUTES)
        if start_at >= plan_end:
            return None


async def generate_itinerary(
    session: AsyncSession,
    *,
    user: User,
    payload: GenerateItineraryRequest,
    map_provider: SchematicMapProvider | None = None,
    planner: RulesPlanner | None = None,
) -> Itinerary:
    provider = map_provider or SchematicMapProvider()
    rules = planner or RulesPlanner()
    # 普通门票时段表示可入园窗口, 不是游客时间线上的独占活动。真正定时且占座的
    # 预约仍可在未来以显式业务类型进入 commitments, 但不能再从普通门票推导。
    commitments: list[Commitment] = []
    preferences = PlanningPreferences(
        interests=frozenset(payload.interests),
        companion_type=payload.companion_type,
        fitness_level=payload.fitness_level,
        accessible=payload.accessible,
        crowd_avoidance=True,
    )
    candidates, nodes, excluded = await _scored_candidates(
        session,
        preferences=preferences,
        map_provider=provider,
        planner=rules,
    )
    all_nodes = list(await session.scalars(select(RouteNode)))
    entrance = next(node for node in all_nodes if node.kind == "ENTRANCE")
    plan_start = datetime.combine(
        payload.visit_date,
        payload.start_time,
        tzinfo=SCENIC_TIMEZONE,
    ).astimezone(UTC)
    plan_end = plan_start + timedelta(minutes=payload.duration_minutes)
    itinerary = Itinerary(
        user_id=user.id,
        name=f"规则行程 {payload.visit_date.isoformat()}",
        visit_date=payload.visit_date,
        start_time=payload.start_time,
        duration_minutes=payload.duration_minutes,
        interests=payload.interests,
        companion_type=payload.companion_type,
        fitness_level=payload.fitness_level,
        accessible=payload.accessible,
        status="DRAFT",
        source="rules",
        revision=1,
        total_score=0,
        explanation=[
            "由本地确定性规则生成, 未连接外部智能规划服务",
            "评分综合考虑兴趣、模拟人流、示意距离、同行人群、体力和无障碍需求",
        ],
        is_complete=True,
        unscheduled_reasons=[],
    )

    cursor = plan_start - timedelta(minutes=DEFAULT_WALKING_BUFFER_MINUTES)
    current_node = entrance
    scheduled = 0
    target_count = min(4, len(candidates))
    score_breakdown: dict[str, object] = {}
    for candidate in candidates:
        if scheduled >= target_count:
            break
        destination = nodes[candidate.attraction.id]
        try:
            route = await provider.route(
                session,
                from_node_id=current_node.id,
                to_node_id=destination.id,
                wheelchair=payload.accessible,
                stroller=payload.companion_type == "family",
            )
        except NoSchematicRouteError:
            excluded.append(f"{candidate.attraction.name}: 无法从上一站到达")
            continue
        interval = _find_start(
            cursor=cursor,
            walk_minutes=route.walk_minutes,
            visit_minutes=candidate.attraction.visit_minutes,
            commitments=commitments,
            plan_end=plan_end,
        )
        if interval is None:
            excluded.append(f"{candidate.attraction.name}: 无法排入指定游览时长")
            continue
        start_at, end_at = interval
        try:
            return_route = await provider.route(
                session,
                from_node_id=destination.id,
                to_node_id=entrance.id,
                wheelchair=payload.accessible,
                stroller=payload.companion_type == "family",
            )
        except NoSchematicRouteError:
            excluded.append(f"{candidate.attraction.name}: 没有返回入口的可用路线")
            continue
        if end_at + timedelta(minutes=return_route.walk_minutes) > plan_end:
            excluded.append(f"{candidate.attraction.name}: 返回入口后将超出指定游览时长")
            continue
        itinerary.items.append(
            ItineraryItem(
                ordinal=1,
                kind="ATTRACTION",
                ref_type="attraction",
                ref_id=candidate.attraction.id,
                attraction_id=candidate.attraction.id,
                node_id=destination.id,
                title=candidate.attraction.name,
                start_at=start_at,
                end_at=end_at,
                locked=False,
                crowd_level=candidate.crowd.crowd_level,
                walk_minutes=route.walk_minutes,
                explanation=candidate.explanation + route.explanation,
            )
        )
        itinerary.total_score += candidate.score
        score_breakdown[candidate.attraction.code] = candidate.breakdown
        scheduled += 1
        cursor = end_at
        current_node = destination

    # 最终序号由稳定时间轴生成, 避免数据库返回顺序影响客户端呈现与冲突检查。
    itinerary.items.sort(key=lambda item: (_aware(item.start_at), item.kind, str(item.ref_id)))
    for ordinal, item in enumerate(itinerary.items, start=1):
        item.ordinal = ordinal
    if scheduled < target_count or target_count == 0:
        itinerary.is_complete = False
        itinerary.unscheduled_reasons = excluded or ["没有符合条件且可排入当前时段的景点"]
    session.add(itinerary)
    await session.flush()
    session.add(
        PlanRun(
            itinerary_id=itinerary.id,
            revision=1,
            run_type="generate",
            source="rules",
            inputs=payload.model_dump(mode="json"),
            score_breakdown=score_breakdown,
            explanation=itinerary.explanation,
        )
    )
    await session.commit()
    loaded = await _load_itinerary(session, itinerary.id)
    assert loaded is not None
    return loaded


async def get_itinerary(
    session: AsyncSession,
    *,
    itinerary_id: UUID,
    user: User,
) -> Itinerary:
    return await _owned_itinerary(session, itinerary_id=itinerary_id, user=user)


async def check_itinerary_conflicts(
    session: AsyncSession,
    *,
    itinerary_id: UUID,
    user: User,
    walking_buffer_minutes: int,
    map_provider: SchematicMapProvider | None = None,
) -> ConflictCheckResponse:
    itinerary = await _owned_itinerary(session, itinerary_id=itinerary_id, user=user)
    provider = map_provider or SchematicMapProvider()
    items = sorted(
        (item for item in itinerary.items if not _is_legacy_admission_commitment(item)),
        key=lambda item: _aware(item.start_at),
    )
    conflicts: list[ItineraryConflictResponse] = []
    suggestions: list[ConflictSuggestionResponse] = []
    # 创新点 3: 沿排序后的时间轴同时检查重叠、路线可达性和步行缓冲;
    # locked 只决定“建议移动谁”, 不会让冲突被静默忽略。
    for previous, current in pairwise(items):
        previous_start = _aware(previous.start_at)
        previous_end = _aware(previous.end_at)
        current_start = _aware(current.start_at)
        current_end = _aware(current.end_at)
        if _overlaps(previous_start, previous_end, current_start, current_end):
            conflicts.append(
                ItineraryConflictResponse(
                    code="ITEM_OVERLAP",
                    severity="ERROR",
                    message="行程项目存在时间重叠",
                    item_ids=[str(previous.id), str(current.id)],
                )
            )
            if not current.locked:
                shifted_start = previous_end + timedelta(minutes=walking_buffer_minutes)
                suggestions.append(
                    ConflictSuggestionResponse(
                        action="SHIFT_ITEM",
                        message="将后一个未锁定项目调整到前一项目及缓冲时间之后",
                        item_id=str(current.id),
                        new_start_at=shifted_start,
                        new_end_at=shifted_start + (current_end - current_start),
                    )
                )
            elif not previous.locked:
                shifted_end = current_start - timedelta(minutes=walking_buffer_minutes)
                suggestions.append(
                    ConflictSuggestionResponse(
                        action="SHIFT_ITEM",
                        message="将前一个未锁定项目调整到锁定安排之前",
                        item_id=str(previous.id),
                        new_start_at=shifted_end - (previous_end - previous_start),
                        new_end_at=shifted_end,
                    )
                )
            else:
                suggestions.append(
                    ConflictSuggestionResponse(
                        action="REVIEW_MANDATORY",
                        message="两个冲突安排均已锁定, 需要手动处理",
                        item_id=None,
                        new_start_at=None,
                        new_end_at=None,
                    )
                )
            continue

        required_walk = 0
        if previous.node_id is not None and current.node_id is not None:
            try:
                route = await provider.route(
                    session,
                    from_node_id=previous.node_id,
                    to_node_id=current.node_id,
                    wheelchair=itinerary.accessible,
                    stroller=itinerary.companion_type == "family",
                )
                required_walk = route.walk_minutes
            except NoSchematicRouteError:
                conflicts.append(
                    ItineraryConflictResponse(
                        code="NO_ACCESSIBLE_ROUTE",
                        severity="ERROR",
                        message="相邻行程项目之间没有可用的示意路线",
                        item_ids=[str(previous.id), str(current.id)],
                    )
                )
                movable = (
                    current if not current.locked else previous if not previous.locked else None
                )
                suggestions.append(
                    ConflictSuggestionResponse(
                        action="REMOVE_ITEM" if movable is not None else "REVIEW_MANDATORY",
                        message=(
                            "移除或替换无法到达的未锁定项目"
                            if movable is not None
                            else "两个无法衔接的安排均已锁定, 需要手动处理"
                        ),
                        item_id=str(movable.id) if movable is not None else None,
                        new_start_at=None,
                        new_end_at=None,
                    )
                )
                continue
        required_gap = required_walk + walking_buffer_minutes
        actual_gap = int((current_start - previous_end).total_seconds() // 60)
        if actual_gap < required_gap:
            shifted_start = previous_end + timedelta(minutes=required_gap)
            conflicts.append(
                ItineraryConflictResponse(
                    code="WALK_BUFFER",
                    severity="ERROR",
                    message=(
                        f"需要步行 {required_walk} 分钟, 另需预留 "
                        f"{walking_buffer_minutes} 分钟缓冲时间"
                    ),
                    item_ids=[str(previous.id), str(current.id)],
                )
            )
            if not current.locked:
                suggestions.append(
                    ConflictSuggestionResponse(
                        action="SHIFT_ITEM",
                        message="调整后一个未锁定项目, 为步行和缓冲时间留出空间",
                        item_id=str(current.id),
                        new_start_at=shifted_start,
                        new_end_at=shifted_start + (current_end - current_start),
                    )
                )
            elif not previous.locked:
                shifted_end = current_start - timedelta(minutes=required_gap)
                suggestions.append(
                    ConflictSuggestionResponse(
                        action="SHIFT_ITEM",
                        message="将前一个未锁定项目调整到锁定安排之前",
                        item_id=str(previous.id),
                        new_start_at=shifted_end - (previous_end - previous_start),
                        new_end_at=shifted_end,
                    )
                )
            else:
                suggestions.append(
                    ConflictSuggestionResponse(
                        action="REVIEW_MANDATORY",
                        message="锁定安排之间缺少步行缓冲时间, 需要手动处理",
                        item_id=None,
                        new_start_at=None,
                        new_end_at=None,
                    )
                )

    serialized_conflicts = [conflict.model_dump(mode="json") for conflict in conflicts]
    check = ConflictCheck(
        itinerary_id=itinerary.id,
        user_id=user.id,
        has_conflicts=bool(conflicts),
        conflicts=serialized_conflicts,
        checked_at=datetime.now(UTC),
    )
    session.add(check)
    await session.commit()
    return ConflictCheckResponse(
        itinerary_id=str(itinerary.id),
        revision=itinerary.revision,
        feasible=not conflicts,
        conflicts=conflicts,
        suggestions=suggestions,
    )


async def replan_itinerary(
    session: AsyncSession,
    *,
    itinerary_id: UUID,
    user: User,
    payload: ReplanItineraryRequest,
) -> Itinerary:
    itinerary = await _owned_itinerary(session, itinerary_id=itinerary_id, user=user)
    # expected_revision 是乐观并发令牌, 先快速拒绝基于旧页面发起的重排。
    if itinerary.revision != payload.expected_revision:
        raise _error(409, "REVISION_CONFLICT", "行程版本已发生变化")
    legacy_admission_items = [
        item for item in itinerary.items if _is_legacy_admission_commitment(item)
    ]
    _, crowds = await latest_crowd_by_attraction(session)
    # 锁定项目不进入候选集合, 其原时间段稍后作为硬约束参与排程。
    unlocked_slots = sorted(
        [
            item
            for item in itinerary.items
            if not item.locked and item.kind == "ATTRACTION" and item.attraction_id is not None
        ],
        key=lambda item: (_aware(item.start_at), item.ordinal),
    )
    attraction_ids = {item.attraction_id for item in unlocked_slots}
    attractions = {
        attraction.id: attraction
        for attraction in await session.scalars(
            select(Attraction).where(Attraction.id.in_(attraction_ids))
        )
    }
    nodes = list(await session.scalars(select(RouteNode)))
    node_by_attraction = {
        node.attraction_id: node for node in nodes if node.attraction_id is not None
    }
    entrance = next((node for node in nodes if node.kind == "ENTRANCE"), None)
    if entrance is None:
        raise _error(500, "GUIDE_GRAPH_INVALID", "本地示意图缺少入口节点")

    candidates = [
        (
            attractions[item.attraction_id],
            crowds[item.attraction_id],
            node_by_attraction[item.attraction_id],
        )
        for item in unlocked_slots
    ]
    if payload.crowd_avoidance:
        # 创新点 2: 基于最新持久化人流快照重排, 并用景点代码保证同级人流下顺序确定。
        level_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
        candidates.sort(
            key=lambda candidate: (
                level_order[candidate[1].crowd_level],
                candidate[0].code,
            )
        )

    locked_intervals = [
        Commitment(
            order_id=item.ref_id,
            title=item.title,
            start_at=_aware(item.start_at),
            end_at=_aware(item.end_at),
        )
        for item in itinerary.items
        if item.locked and not _is_legacy_admission_commitment(item)
    ]
    plan_start = datetime.combine(
        itinerary.visit_date,
        itinerary.start_time,
        tzinfo=SCENIC_TIMEZONE,
    ).astimezone(UTC)
    plan_end = plan_start + timedelta(minutes=itinerary.duration_minutes)
    cursor = plan_start - timedelta(minutes=DEFAULT_WALKING_BUFFER_MINUTES)
    current_node = entrance
    provider = SchematicMapProvider()
    planner = RulesPlanner()
    preferences = PlanningPreferences(
        interests=frozenset(itinerary.interests),
        companion_type=itinerary.companion_type,
        fitness_level=itinerary.fitness_level,
        accessible=itinerary.accessible,
        crowd_avoidance=payload.crowd_avoidance,
    )
    # 先在内存中完整求解, 全部可行后再统一写回, 避免半条行程已经变更的中间状态。
    planned_updates: list[
        tuple[
            ItineraryItem,
            Attraction,
            CrowdSnapshot,
            RouteNode,
            datetime,
            datetime,
            int,
            int,
            list[str],
        ]
    ] = []
    for slot_item, (attraction, crowd, destination) in zip(
        unlocked_slots,
        candidates,
        strict=True,
    ):
        if itinerary.accessible and (
            "wheelchair" not in attraction.accessibility or not destination.accessible
        ):
            raise _error(
                409,
                "REPLAN_INFEASIBLE",
                f"{attraction.name} 暂不支持轮椅无障碍通行",
            )
        try:
            route = await provider.route(
                session,
                from_node_id=current_node.id,
                to_node_id=destination.id,
                wheelchair=itinerary.accessible,
                stroller=itinerary.companion_type == "family",
            )
            return_route = await provider.route(
                session,
                from_node_id=destination.id,
                to_node_id=entrance.id,
                wheelchair=itinerary.accessible,
                stroller=itinerary.companion_type == "family",
            )
        except NoSchematicRouteError as exc:
            raise _error(409, "REPLAN_INFEASIBLE", str(exc)) from exc
        interval = _find_start(
            cursor=cursor,
            walk_minutes=route.walk_minutes,
            visit_minutes=attraction.visit_minutes,
            commitments=locked_intervals,
            plan_end=plan_end,
        )
        if interval is None:
            raise _error(
                409,
                "REPLAN_INFEASIBLE",
                f"{attraction.name} 无法避开锁定项目排入当前行程",
            )
        start_at, end_at = interval
        if end_at + timedelta(minutes=return_route.walk_minutes) > plan_end:
            raise _error(
                409,
                "REPLAN_INFEASIBLE",
                "返回入口后将超出当前行程时段",
            )
        scored = planner.score_candidate(
            attraction=attraction,
            crowd=crowd,
            walk_minutes=route.walk_minutes,
            preferences=preferences,
        )
        planned_updates.append(
            (
                slot_item,
                attraction,
                crowd,
                destination,
                start_at,
                end_at,
                route.walk_minutes,
                scored.score,
                [
                    *scored.explanation,
                    *route.explanation,
                    "已根据最新保存的模拟人流数据重新规划",
                ],
            )
        )
        cursor = end_at
        current_node = destination

    next_revision = itinerary.revision + 1
    total_score = sum(update_data[7] for update_data in planned_updates)
    # 创新点 3: 写入时再次用 revision 做原子比较并递增, 封住校验后到提交前的并发窗口。
    transitioned = await session.execute(
        update(Itinerary)
        .execution_options(synchronize_session=False)
        .where(
            Itinerary.id == itinerary.id,
            Itinerary.revision == payload.expected_revision,
        )
        .values(
            revision=next_revision,
            explanation=[
                *itinerary.explanation,
                "已根据模拟人流数据通过确定性规则重新规划",
            ],
            total_score=total_score,
            is_complete=True,
            unscheduled_reasons=[],
            updated_at=datetime.now(UTC),
        )
    )
    if transitioned.rowcount != 1:
        await session.rollback()
        raise _error(409, "REVISION_CONFLICT", "行程版本已发生变化")
    # 重排是现有行程的写入边界, 在版本 CAS 成功后顺手清除旧版普通门票项。
    # 其他来源的真实 locked 项仍保留并继续参与排程。
    for legacy_item in legacy_admission_items:
        await session.delete(legacy_item)
    for (
        item,
        attraction,
        crowd,
        node,
        start_at,
        end_at,
        walk_minutes,
        _,
        explanation,
    ) in planned_updates:
        item.ref_type = "attraction"
        item.ref_id = attraction.id
        item.attraction_id = attraction.id
        item.node_id = node.id
        item.title = attraction.name
        item.start_at = start_at
        item.end_at = end_at
        item.crowd_level = crowd.crowd_level
        item.walk_minutes = walk_minutes
        item.explanation = explanation
    # 记录本次采用的人流 sequence, 使每次自动重排都能追溯到确定的快照版本。
    session.add(
        PlanRun(
            itinerary_id=itinerary.id,
            revision=next_revision,
            run_type="replan",
            source="rules",
            inputs=payload.model_dump(mode="json"),
            score_breakdown={
                "crowd_sequence": max(
                    (snapshot.sequence for snapshot in crowds.values()),
                    default=0,
                )
            },
            explanation=["仅调整了未锁定的行程项目"],
        )
    )
    await session.commit()
    loaded = await _load_itinerary(session, itinerary.id)
    assert loaded is not None
    return loaded
