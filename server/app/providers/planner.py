"""Explainable rules planner and a future AI adapter boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Protocol

from app.db.models.guide import Attraction, CrowdSnapshot


class AIPlannerAdapter(Protocol):
    """Reserved interface; no AI provider is connected in this MVP."""

    async def propose(self, inputs: dict[str, object]) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class PlanningPreferences:
    interests: frozenset[str]
    companion_type: str
    fitness_level: str
    accessible: bool
    crowd_avoidance: bool = True


@dataclass(frozen=True, slots=True)
class ScoredAttraction:
    attraction: Attraction
    crowd: CrowdSnapshot
    walk_minutes: int
    score: int
    explanation: list[str]
    breakdown: dict[str, int]


class RulesPlanner:
    """Deterministic scorer over interests, crowd, walking, companions, and mobility."""

    source = "rules"
    is_demo = True

    _crowd_labels: ClassVar[dict[str, str]] = {
        "LOW": "较少",
        "MEDIUM": "适中",
        "HIGH": "拥挤",
    }

    def score_candidate(
        self,
        *,
        attraction: Attraction,
        crowd: CrowdSnapshot,
        walk_minutes: int,
        preferences: PlanningPreferences,
    ) -> ScoredAttraction:
        # 创新点 1: 将兴趣、人流、距离、同行人群、体力和无障碍拆成可加总分项。
        # 相同输入始终得到相同分数, 便于复现推荐结果并逐项解释排序原因。
        normalized_tags = {tag.lower() for tag in attraction.tags}
        normalized_tags.add(attraction.category.lower())
        interest_matches = len(preferences.interests & normalized_tags)
        interest_score = interest_matches * 30

        crowd_score = {"LOW": 20, "MEDIUM": 0, "HIGH": -40}[crowd.crowd_level]
        if not preferences.crowd_avoidance:
            crowd_score = max(crowd_score, -5)
        distance_score = -2 * walk_minutes

        companion_score = 0
        if preferences.companion_type == "family" and normalized_tags & {
            "family",
            "education",
            "animals",
        }:
            companion_score += 15
        elif preferences.companion_type == "senior" and "restful" in normalized_tags:
            companion_score += 15
        elif preferences.companion_type == "friends" and "photo" in normalized_tags:
            companion_score += 10

        fitness_score = 0
        if preferences.fitness_level == "low":
            fitness_score -= max(0, walk_minutes - 5) * 2
            fitness_score -= max(0, attraction.visit_minutes - 60) // 5
        elif preferences.fitness_level == "high" and normalized_tags & {"nature", "hiking"}:
            fitness_score += 12

        accessibility_score = 0
        if preferences.accessible:
            # 无障碍是安全硬约束; 不满足时使用压倒性负分, 不能被其他偏好加分抵消。
            accessibility_score = 20 if "wheelchair" in attraction.accessibility else -10_000

        breakdown = {
            "base": 50,
            "interest": interest_score,
            "crowd": crowd_score,
            "distance": distance_score,
            "companion": companion_score,
            "fitness": fitness_score,
            "accessibility": accessibility_score,
        }
        score = sum(breakdown.values())
        crowd_label = self._crowd_labels[crowd.crowd_level]
        # 展示文案直接取自同一组分项, 保证总分、明细与用户可见解释保持一致。
        explanation = [
            f"兴趣匹配: {interest_matches} 项 ({interest_score:+d})",
            f"模拟人流: {crowd_label} ({crowd_score:+d})",
            f"示意步行: {walk_minutes} 分钟 ({distance_score:+d})",
            f"同行人群适配 ({companion_score:+d})",
            f"体力适配 ({fitness_score:+d})",
        ]
        if preferences.accessible:
            explanation.append(f"轮椅无障碍适配 ({accessibility_score:+d})")
        return ScoredAttraction(
            attraction=attraction,
            crowd=crowd,
            walk_minutes=walk_minutes,
            score=score,
            explanation=explanation,
            breakdown=breakdown,
        )
