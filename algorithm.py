from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Set


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """Clamp a number into a fixed range."""
    return max(low, min(high, value))


# ============================================================
# Data models
# ============================================================

@dataclass
class Place:
    """Candidate place used by the recommendation algorithm."""

    id: str
    category: str
    indoor: bool
    outdoor: bool
    travel_time: float
    price: str
    open_now: bool
    reachable: bool
    data_valid: bool
    is_event: bool
    event_active: bool
    quality: float
    mood_fit: Dict[str, float]
    weather_exposure: float
    aqi_exposure: float


@dataclass
class UserContext:
    """User state and preference settings."""

    scenario: str
    mood: str
    preferred_time: float
    hard_max_time: float
    rain_prob: float
    aqi: float
    budget: str
    secondary_mood: str | None = None
    secondary_mood_weight: float = 0.35
    ignored_factors: Set[str] = field(default_factory=set)
    indoor_only: bool = False
    outdoor_preferred: bool = False
    severe_weather: bool = False
    user_weight_adjustment: Dict[str, float] = field(default_factory=dict)


@dataclass
class RecommendationResult:
    """One ranked recommendation result."""

    place: Place
    score: float
    uncertainty: float
    worst_score: float
    normal_score: float
    best_score: float
    active_factors: List[str]
    weights: Dict[str, float]
    fallback: bool = False
    reason: str = ""


# ============================================================
# Configuration
# ============================================================

MOODS = ["relax", "date", "solo", "photo", "night"]

CATEGORIES = [
    "cafe",
    "park",
    "museum",
    "market",
    "bookstore",
    "riverside",
    "gallery",
    "restaurant",
    "viewpoint",
]

BASE_WEIGHTS = {
    "mood": 0.24,
    "distance": 0.18,
    "weather": 0.15,
    "aqi": 0.10,
    "budget": 0.08,
    "category": 0.10,
    "quality": 0.15,
    "environment": 0.08,
}

PRICE_ORDER = {
    "low": 0,
    "medium": 1,
    "high": 2,
}

PREFERRED_CATEGORIES_BY_MOOD = {
    "relax": {"park", "riverside", "cafe", "bookstore"},
    "date": {"cafe", "gallery", "restaurant", "viewpoint"},
    "solo": {"bookstore", "cafe", "museum", "riverside"},
    "photo": {"viewpoint", "riverside", "gallery", "market"},
    "night": {"restaurant", "viewpoint", "market", "riverside"},
}

SECONDARY_CATEGORIES_BY_MOOD = {
    "relax": {"museum", "gallery", "viewpoint"},
    "date": {"park", "riverside", "market", "museum"},
    "solo": {"park", "gallery", "viewpoint"},
    "photo": {"park", "museum", "bookstore", "cafe"},
    "night": {"cafe", "gallery", "museum"},
}

# ============================================================
# Algorithm implementation
# ============================================================

def hard_filter(place: Place, user: UserContext) -> Tuple[bool, str | None]:
    """
    Apply non-negotiable hard constraints.

    These conditions are not treated as weighted preferences.
    If violated, the place should not be recommended.
    """

    if not place.data_valid:
        return False, "invalid_data"

    if not place.reachable:
        return False, "unreachable"

    if not place.open_now:
        return False, "closed"

    if place.is_event and not place.event_active:
        return False, "event_ended"

    if user.indoor_only and not place.indoor:
        return False, "not_indoor"

    if place.travel_time > user.hard_max_time:
        return False, "over_hard_max_time"

    if (
        user.severe_weather
        and place.outdoor
        and place.weather_exposure >= 0.75
        and place.travel_time > user.preferred_time
    ):
        return False, "unsafe_weather"

    return True, None


def cap_and_redistribute_weights(
    weights: Dict[str, float],
    max_weight: float = 0.45,
) -> Dict[str, float]:
    """
    Cap dominant factors and redistribute the remaining weight.

    A strict 0.45 cap is only possible when enough factors are active. If the
    user leaves one or two factors active, the effective cap is relaxed to the
    lowest mathematically possible value.
    """

    if not weights:
        return {}

    effective_max = max(max_weight, 1.0 / len(weights))
    uncapped = dict(weights)
    capped: Dict[str, float] = {}
    remaining_budget = 1.0

    while uncapped:
        total_uncapped = sum(uncapped.values())
        changed = False

        for factor, weight in list(uncapped.items()):
            redistributed = (weight / total_uncapped) * remaining_budget

            if redistributed > effective_max:
                capped[factor] = effective_max
                remaining_budget -= effective_max
                del uncapped[factor]
                changed = True

        if not changed:
            for factor, weight in uncapped.items():
                capped[factor] = (weight / total_uncapped) * remaining_budget
            break

    return capped


def normalize_active_weights(user: UserContext) -> Tuple[Dict[str, float], List[str]]:
    """
    Normalize weights only across active factors.

    Ignored factors receive weight = 0 and are excluded from scoring.
    Active factors are softly capped to prevent single-factor domination.
    """

    active_factors = []

    for factor in BASE_WEIGHTS:
        if factor in user.ignored_factors:
            continue

        if factor == "environment" and not user.outdoor_preferred:
            continue

        active_factors.append(factor)

    if not active_factors:
        return {}, []

    raw_weights = {
        factor: BASE_WEIGHTS[factor] * user.user_weight_adjustment.get(factor, 1.0)
        for factor in active_factors
    }

    total_raw = sum(raw_weights.values())
    normalized = {
        factor: raw_weights[factor] / total_raw
        for factor in raw_weights
    }

    # Prevent one preference from dominating the whole ranking.
    final_weights = cap_and_redistribute_weights(normalized, max_weight=0.45)

    return final_weights, active_factors


# ----------------------------
# Utility mapping
# ----------------------------

def utility_distance(place: Place, user: UserContext, variant: str) -> float:
    """
    Convert travel time into a 0~1 utility score.

    variant:
        low  -> worse case
        mid  -> normal case
        high -> better case
    """

    travel_time = place.travel_time

    if variant == "low":
        travel_time *= 1.25
    elif variant == "high":
        travel_time *= 0.85

    preferred_time = max(5, user.preferred_time)

    return clamp(
        math.exp(-((travel_time / preferred_time) ** 2) * 0.65)
    )


def utility_weather(place: Place, user: UserContext, variant: str) -> float:
    """Convert rain probability into a weather suitability score."""

    rain_prob = user.rain_prob

    if variant == "low":
        rain_prob = min(1.0, rain_prob + 0.15)
    elif variant == "high":
        rain_prob = max(0.0, rain_prob - 0.15)

    exposure_penalty = 0.20 + 0.70 * place.weather_exposure

    if user.outdoor_preferred and place.outdoor:
        exposure_penalty *= 0.88

    return clamp(1 - exposure_penalty * rain_prob)


def utility_aqi(place: Place, user: UserContext, variant: str) -> float:
    """Convert AQI into a 0~1 suitability score."""

    aqi = user.aqi

    if variant == "low":
        aqi += 25
    elif variant == "high":
        aqi -= 20

    if aqi <= 50:
        base = 1.0
    elif aqi <= 100:
        base = 0.82
    elif aqi <= 150:
        base = 0.55
    else:
        base = 0.30

    # Indoor and sheltered places are less affected by AQI, but not immune.
    base = 1 - ((1 - base) * place.aqi_exposure)

    return clamp(base)


def utility_budget(place: Place, user: UserContext) -> float:
    """Convert price difference into a 0~1 utility score."""

    diff = abs(PRICE_ORDER[place.price] - PRICE_ORDER[user.budget])

    return {
        0: 1.0,
        1: 0.72,
        2: 0.42,
    }[diff]


def utility_mood(place: Place, user: UserContext) -> float:
    """Blend primary and secondary mood when the user state is mixed."""

    primary = place.mood_fit[user.mood]

    if not user.secondary_mood:
        return primary

    secondary_weight = clamp(user.secondary_mood_weight, 0.0, 0.7)
    secondary = place.mood_fit[user.secondary_mood]

    return ((1 - secondary_weight) * primary) + (secondary_weight * secondary)


def utility_category(place: Place, user: UserContext) -> float:
    """Evaluate whether the place category matches the user's mood."""

    def category_affinity(mood: str) -> float:
        preferred_categories = PREFERRED_CATEGORIES_BY_MOOD[mood]
        secondary_categories = SECONDARY_CATEGORIES_BY_MOOD[mood]

        if place.category in preferred_categories:
            return 0.96

        if place.category in secondary_categories:
            return 0.78

        return 0.62

    primary = category_affinity(user.mood)

    if not user.secondary_mood:
        return primary

    secondary_weight = clamp(user.secondary_mood_weight, 0.0, 0.7)
    secondary = category_affinity(user.secondary_mood)

    return ((1 - secondary_weight) * primary) + (secondary_weight * secondary)


def utility_environment(place: Place, user: UserContext) -> float:
    """Evaluate soft indoor/outdoor preference fit."""

    if user.outdoor_preferred:
        return 1.0 if place.outdoor else 0.75

    return 1.0


def compute_interval_utilities(
    place: Place,
    user: UserContext,
    active_factors: List[str],
) -> Dict[str, Dict[str, float]]:
    """
    Build low / mid / high utility values for active factors only.
    """

    intervals = {
        "low": {},
        "mid": {},
        "high": {},
    }

    for variant in intervals:
        if "mood" in active_factors:
            base = utility_mood(place, user)
            multiplier = 0.92 if variant == "low" else 1.05 if variant == "high" else 1.0
            intervals[variant]["mood"] = clamp(base * multiplier)

        if "distance" in active_factors:
            intervals[variant]["distance"] = utility_distance(place, user, variant)

        if "weather" in active_factors:
            intervals[variant]["weather"] = utility_weather(place, user, variant)

        if "aqi" in active_factors:
            intervals[variant]["aqi"] = utility_aqi(place, user, variant)

        if "budget" in active_factors:
            intervals[variant]["budget"] = utility_budget(place, user)

        if "category" in active_factors:
            intervals[variant]["category"] = utility_category(place, user)

        if "quality" in active_factors:
            intervals[variant]["quality"] = place.quality

        if "environment" in active_factors:
            intervals[variant]["environment"] = utility_environment(place, user)

    return intervals


# ----------------------------
# Scoring
# ----------------------------

def weighted_product(
    utilities: Dict[str, float],
    weights: Dict[str, float],
    epsilon: float = 0.001,
) -> float:
    """
    Weighted product score.

    score = ? (utility_i + epsilon) ^ weight_i

    Compared with weighted sum, this reduces the chance that a very high factor
    completely compensates for a very poor important factor.
    """

    score = 1.0

    for factor, weight in weights.items():
        score *= (utilities[factor] + epsilon) ** weight

    return clamp(score)


def robust_score_from_interval(
    worst_score: float,
    normal_score: float,
    best_score: float,
) -> Tuple[float, float]:
    """
    Calculate robust score from worst / normal / best scores.

    The system mainly trusts normal performance, still values worst-case stability,
    slightly considers best-case upside, and penalizes high uncertainty.
    """

    uncertainty_width = best_score - worst_score

    robust_score = (
        0.60 * normal_score
        + 0.30 * worst_score
        + 0.10 * best_score
        - 0.20 * uncertainty_width
    )

    return clamp(robust_score), clamp(uncertainty_width)


def weak_personalization_mode(active_factors: List[str]) -> bool:
    """Detect cases where ranking should explore more instead of overusing quality."""

    return "mood" not in active_factors and "category" not in active_factors


def deterministic_fraction(*parts: object) -> float:
    """Small deterministic tie-breaker for simulations without using global randomness."""

    text = "|".join(str(part) for part in parts)
    value = sum((index + 1) * ord(char) for index, char in enumerate(text))

    return (value % 1000) / 1000


def contextual_exploration_adjustment(place: Place, user: UserContext) -> float:
    """
    Add a tiny context-dependent adjustment when personalization signals are weak.

    This prevents stable sort order from repeatedly making the same category the
    top result when several candidates are effectively tied.
    """

    return (
        deterministic_fraction(
            place.category,
            user.scenario,
            round(user.rain_prob, 2),
            round(user.aqi),
            user.budget,
        )
        - 0.5
    ) * 0.012


# ----------------------------
# Post-processing
# ----------------------------

def diversity_rerank(
    ranked_results: List[RecommendationResult],
    k: int = 5,
    score_adjustment=None,
) -> List[RecommendationResult]:
    """
    Avoid returning too many recommendations of the same category.

    Example:
        Instead of returning 5 cafes, return cafe + park + gallery + riverside.
    """

    selected: List[RecommendationResult] = []
    category_counter: Counter = Counter()

    pool = ranked_results[:60]

    while pool and len(selected) < k:
        best_index = 0
        best_adjusted_score = -1.0

        for index, result in enumerate(pool):
            category = result.place.category
            diversity_penalty = 0.08 * category_counter[category]
            contextual_adjustment = score_adjustment(result) if score_adjustment else 0.0
            adjusted_score = result.score + contextual_adjustment - diversity_penalty

            if adjusted_score > best_adjusted_score:
                best_index = index
                best_adjusted_score = adjusted_score

        chosen = pool.pop(best_index)
        selected.append(chosen)
        category_counter[chosen.place.category] += 1

    return selected


def generate_reason(
    place: Place,
    user: UserContext,
    active_factors: List[str],
    weights: Dict[str, float],
) -> str:
    """
    Generate a human-readable recommendation reason.

    This is a simple MVP version.
    In production, this can be improved with templates or an AI agent.
    """

    reasons = []

    if "mood" in active_factors:
        if user.secondary_mood:
            reasons.append(f"balances your '{user.mood}' and '{user.secondary_mood}' moods")
        else:
            reasons.append(f"matches your current '{user.mood}' mood")

    if "distance" in active_factors:
        reasons.append(f"is around {place.travel_time:.0f} minutes away")

    if "weather" in active_factors:
        if place.indoor:
            reasons.append("is less affected by current weather")
        else:
            reasons.append("has acceptable weather suitability")

    if "aqi" in active_factors:
        if place.indoor:
            reasons.append("is a safer choice under uncertain air quality")
        else:
            reasons.append("has acceptable air quality suitability")

    if "budget" in active_factors:
        reasons.append(f"fits your '{user.budget}' budget preference")

    if "quality" in active_factors:
        reasons.append("has a solid overall place quality signal")

    if "environment" in active_factors and user.outdoor_preferred:
        if place.outdoor:
            reasons.append("matches your outdoor preference")
        else:
            reasons.append("is still a reasonable backup to outdoor options")

    if not reasons:
        return "Recommended as a general exploration option."

    return "This place is recommended because it " + ", ".join(reasons[:3]) + "."


def fallback_recommendation(
    feasible_places: List[Place],
    user: UserContext,
    k: int = 5,
) -> List[RecommendationResult]:
    """
    Exploration fallback mode.

    Used when the user ignores all preference factors.
    """

    results = []

    for place in feasible_places:
        results.append(
            RecommendationResult(
                place=place,
                score=place.quality,
                uncertainty=0.0,
                worst_score=place.quality,
                normal_score=place.quality,
                best_score=place.quality,
                active_factors=[],
                weights={},
                fallback=True,
                reason="Recommended in exploration mode because few preference factors were enabled.",
            )
        )

    ranked = sorted(results, key=lambda item: item.score, reverse=True)

    return diversity_rerank(
        ranked,
        k=k,
        score_adjustment=lambda result: contextual_exploration_adjustment(result.place, user),
    )


def count_output_constraint_violations(
    recommendations: List[RecommendationResult],
    user: UserContext,
) -> int:
    """Count recommended places that violate hard constraints."""

    violations = 0

    for result in recommendations:
        is_valid, _ = hard_filter(result.place, user)

        if not is_valid:
            violations += 1

    return violations


def recommend(
    candidates: List[Place],
    user: UserContext,
    k: int = 5,
) -> Tuple[List[RecommendationResult], Counter]:
    """
    Main recommendation pipeline.
    """

    feasible_places: List[Place] = []
    filtered_reasons: Counter = Counter()

    # Step 1: Hard constraint filter
    for place in candidates:
        is_valid, reason = hard_filter(place, user)

        if is_valid:
            feasible_places.append(place)
        else:
            filtered_reasons[reason] += 1

    # Step 2: Active factor selection and weight normalization
    weights, active_factors = normalize_active_weights(user)

    # Step 3: Fallback if user ignores everything
    if not active_factors:
        return fallback_recommendation(feasible_places, user=user, k=k), filtered_reasons

    results: List[RecommendationResult] = []

    # Step 4: Score each feasible place
    for place in feasible_places:
        intervals = compute_interval_utilities(
            place=place,
            user=user,
            active_factors=active_factors,
        )

        worst_score = weighted_product(intervals["low"], weights)
        normal_score = weighted_product(intervals["mid"], weights)
        best_score = weighted_product(intervals["high"], weights)

        score, uncertainty = robust_score_from_interval(
            worst_score=worst_score,
            normal_score=normal_score,
            best_score=best_score,
        )

        result = RecommendationResult(
            place=place,
            score=score,
            uncertainty=uncertainty,
            worst_score=worst_score,
            normal_score=normal_score,
            best_score=best_score,
            active_factors=active_factors,
            weights=weights,
            fallback=False,
            reason=generate_reason(place, user, active_factors, weights),
        )

        results.append(result)

    # Step 5: Sort by robust score
    ranked = sorted(results, key=lambda item: item.score, reverse=True)

    # Step 6: Diversity reranking
    exploration_adjustment = (
        (lambda result: contextual_exploration_adjustment(result.place, user))
        if weak_personalization_mode(active_factors)
        else None
    )
    final_results = diversity_rerank(ranked, k=k, score_adjustment=exploration_adjustment)

    return final_results, filtered_reasons
