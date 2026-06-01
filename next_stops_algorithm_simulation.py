from __future__ import annotations

import math
import os
import random
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Dict, List, Tuple, Set, Any

import pandas as pd

os.environ.setdefault("MPLCONFIGDIR", "/tmp/next-stops-matplotlib")

import matplotlib.pyplot as plt


# ============================================================
# Basic utilities
# ============================================================

SEED = 42
random.seed(SEED)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """Clamp a number into a fixed range."""
    return max(low, min(high, value))


# ============================================================
# Data models
# ============================================================

@dataclass
class Place:
    """Synthetic candidate place used for simulation."""

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


# ============================================================
# Synthetic candidate generation
# ============================================================

def generate_candidates(n: int = 360) -> List[Place]:
    """
    Generate synthetic candidate places.

    This is only for algorithm stress testing.
    In production, candidates should come from:
        - Tourism API
        - Google Places API
        - Event API
        - Internal curated data
    """

    candidates: List[Place] = []

    for i in range(n):
        category = random.choice(CATEGORIES)
        indoor = category in ["cafe", "museum", "bookstore", "gallery", "restaurant"]
        outdoor = not indoor

        travel_time = max(5, random.gauss(35, 22))
        price = random.choice(["low", "medium", "high"])

        mood_fit = {
            "relax": clamp(
                random.gauss(
                    0.65 if category in ["park", "riverside", "cafe", "bookstore"] else 0.45,
                    0.18,
                )
            ),
            "date": clamp(
                random.gauss(
                    0.70 if category in ["cafe", "gallery", "restaurant", "viewpoint"] else 0.42,
                    0.18,
                )
            ),
            "solo": clamp(
                random.gauss(
                    0.72 if category in ["bookstore", "cafe", "museum", "riverside"] else 0.42,
                    0.18,
                )
            ),
            "photo": clamp(
                random.gauss(
                    0.72 if category in ["viewpoint", "riverside", "gallery", "market"] else 0.45,
                    0.18,
                )
            ),
            "night": clamp(
                random.gauss(
                    0.70 if category in ["restaurant", "viewpoint", "market", "riverside"] else 0.40,
                    0.18,
                )
            ),
        }

        is_event = category == "market" or (
            category in ["gallery", "museum"] and random.random() < 0.35
        )

        place = Place(
            id=f"place_{i:03d}",
            category=category,
            indoor=indoor,
            outdoor=outdoor,
            travel_time=travel_time,
            price=price,
            open_now=random.random() > 0.12,
            reachable=random.random() > 0.03,
            data_valid=random.random() > 0.02,
            is_event=is_event,
            event_active=random.random() > 0.08 if is_event else True,
            quality=clamp(random.gauss(0.72, 0.16)),
            mood_fit=mood_fit,
        )

        candidates.append(place)

    return candidates


# ============================================================
# User scenario generation
# ============================================================

SCENARIO_CONFIGS: Dict[str, Dict[str, Any]] = {
    "Balanced": {},
    "Distance Ignored": {"ignored": ["distance"]},
    "Mood Ignored": {"ignored": ["mood"]},
    "Weather Sensitive": {"boost": {"weather": 2.2}},
    "AQI Sensitive": {"boost": {"aqi": 2.3}},
    "Budget Sensitive": {"boost": {"budget": 2.2}},
    "Minimal Preferences": {"ignored": ["mood", "distance", "budget", "category"]},
    "Extreme Weights": {"extreme": True},
    "Rainy Day": {"rain": (0.65, 0.95)},
    "Poor AQI": {"aqi": (120, 180)},
    "Long Distance OK": {"ignored": ["distance"], "preferred_time": 90},
    "Near Only": {"preferred_time": 20, "hard_max_time": 35},
    "Date Planning": {"mood": "date"},
    "Solo Relaxation": {"mood": "solo"},
    "Photo Exploration": {"mood": "photo"},
    "Night Outing": {"mood": "night"},
    "Indoor Only": {"indoor_only": True},
    "Outdoor Preferred": {"outdoor_preferred": True},
    "Conflicting Preferences": {"conflict": True},
    "Cold Start": {"cold_start": True},
}


def make_user_state(scenario_name: str, config: Dict[str, Any]) -> UserContext:
    """Create a synthetic user state based on scenario configuration."""

    rain_low, rain_high = config.get("rain", (0.05, 0.55))
    aqi_low, aqi_high = config.get("aqi", (25, 110))

    user_weight_adjustment = {factor: 1.0 for factor in BASE_WEIGHTS}

    if config.get("boost"):
        for factor, multiplier in config["boost"].items():
            user_weight_adjustment[factor] = multiplier

    if config.get("extreme"):
        # User strongly overemphasizes one random factor.
        focus_factor = random.choice(list(BASE_WEIGHTS.keys()))
        user_weight_adjustment = {factor: 0.25 for factor in BASE_WEIGHTS}
        user_weight_adjustment[focus_factor] = 5.0

    user = UserContext(
        scenario=scenario_name,
        mood=config.get("mood", random.choice(MOODS)),
        preferred_time=config.get("preferred_time", random.choice([25, 35, 45, 60])),
        hard_max_time=config.get("hard_max_time", 120),
        rain_prob=random.uniform(rain_low, rain_high),
        aqi=random.uniform(aqi_low, aqi_high),
        budget=random.choice(["low", "medium", "high"]),
        ignored_factors=set(config.get("ignored", [])),
        indoor_only=config.get("indoor_only", False),
        outdoor_preferred=config.get("outdoor_preferred", False),
        user_weight_adjustment=user_weight_adjustment,
    )

    if config.get("conflict"):
        # Example conflict:
        # User wants photo exploration and outdoor places, but weather and AQI are poor,
        # and distance limit is strict.
        user.mood = "photo"
        user.rain_prob = random.uniform(0.75, 0.95)
        user.aqi = random.uniform(100, 160)
        user.preferred_time = 20
        user.hard_max_time = 35
        user.outdoor_preferred = True

    if config.get("cold_start"):
        # Cold start: no learned mood/category preference.
        user.ignored_factors = {"mood", "category"}

    user.severe_weather = user.rain_prob > 0.90

    return user


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

    if user.severe_weather and place.outdoor:
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

    if place.indoor:
        return clamp(1 - 0.25 * rain_prob)

    return clamp(1 - 0.85 * rain_prob)


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

    if place.indoor:
        # Indoor places are less affected by AQI.
        base = 0.75 + 0.25 * base

    return clamp(base)


def utility_budget(place: Place, user: UserContext) -> float:
    """Convert price difference into a 0~1 utility score."""

    diff = abs(PRICE_ORDER[place.price] - PRICE_ORDER[user.budget])

    return {
        0: 1.0,
        1: 0.72,
        2: 0.42,
    }[diff]


def utility_category(place: Place, user: UserContext) -> float:
    """Evaluate whether the place category matches the user's mood."""

    preferred_categories = PREFERRED_CATEGORIES_BY_MOOD[user.mood]

    return 1.0 if place.category in preferred_categories else 0.55


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
            base = place.mood_fit[user.mood]
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

    score = Π (utility_i + epsilon) ^ weight_i

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


# ----------------------------
# Post-processing
# ----------------------------

def diversity_rerank(
    ranked_results: List[RecommendationResult],
    k: int = 5,
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
            adjusted_score = result.score - diversity_penalty

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
    k: int = 5,
) -> List[RecommendationResult]:
    """
    Exploration fallback mode.

    Used when the user ignores all preference factors.
    """

    ranked_places = sorted(
        feasible_places,
        key=lambda place: place.quality,
        reverse=True,
    )

    results = []

    for place in ranked_places[:k]:
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

    return results


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
        return fallback_recommendation(feasible_places, k=k), filtered_reasons

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
    final_results = diversity_rerank(ranked, k=k)

    return final_results, filtered_reasons


# ============================================================
# Stress test
# ============================================================

def run_stress_test(
    candidates: List[Place],
    n_per_scenario: int = 180,
) -> pd.DataFrame:
    """
    Run deterministic stress test across all user-state categories.
    """

    rows = []

    for scenario_name, config in SCENARIO_CONFIGS.items():
        for _ in range(n_per_scenario):
            user = make_user_state(scenario_name, config)

            recommendations, filtered_reasons = recommend(
                candidates=candidates,
                user=user,
                k=5,
            )

            scores = [item.score for item in recommendations]
            uncertainties = [item.uncertainty for item in recommendations]
            categories = [item.place.category for item in recommendations]
            qualities = [item.place.quality for item in recommendations]
            constraint_violations = count_output_constraint_violations(
                recommendations=recommendations,
                user=user,
            )

            rows.append(
                {
                    "scenario": scenario_name,
                    "valid_recommendation_count": len(recommendations),
                    "has_3plus": len(recommendations) >= 3,
                    "avg_top5_score": mean(scores) if scores else 0.0,
                    "top1_score": scores[0] if scores else 0.0,
                    "avg_uncertainty": mean(uncertainties) if uncertainties else 0.0,
                    "avg_quality": mean(qualities) if qualities else 0.0,
                    "diversity_top5": len(set(categories)) / 5 if categories else 0.0,
                    "fallback_used": int(any(item.fallback for item in recommendations)),
                    "output_constraint_violations": constraint_violations,
                }
            )

    return pd.DataFrame(rows)


def summarize_results(test_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate stress test results by scenario."""

    summary = (
        test_df
        .groupby("scenario")
        .agg(
            pass_rate=("has_3plus", "mean"),
            avg_top5_score=("avg_top5_score", "mean"),
            avg_uncertainty=("avg_uncertainty", "mean"),
            avg_quality=("avg_quality", "mean"),
            diversity_top5=("diversity_top5", "mean"),
            fallback_rate=("fallback_used", "mean"),
            output_constraint_violations=("output_constraint_violations", "sum"),
        )
        .reset_index()
    )

    # Composite simulation stability index.
    # This is not a recommendation accuracy metric. It is only a practical
    # evaluation index for comparing scenario-level stability during development.
    violation_penalty = (
        summary["output_constraint_violations"]
        / test_df.groupby("scenario").size().reindex(summary["scenario"]).values
    ).clip(0, 1)

    summary["stability_index"] = (
        0.30 * summary["pass_rate"]
        + 0.25 * summary["avg_top5_score"]
        + 0.20 * summary["diversity_top5"]
        + 0.15 * summary["avg_quality"]
        + 0.10 * (1 - summary["avg_uncertainty"].clip(0, 1))
        - 0.25 * violation_penalty
        - 0.10 * summary["fallback_rate"]
    ).clip(0, 1)

    summary = summary.sort_values("stability_index", ascending=False)

    return summary


def save_chart(summary: pd.DataFrame, output_path: Path) -> None:
    """Save simulation stability chart."""

    plt.figure(figsize=(13, 7))
    plt.bar(summary["scenario"], summary["stability_index"])
    plt.xticks(rotation=55, ha="right")
    plt.ylim(0, 1)
    plt.ylabel("Simulation Stability Index")
    plt.title("NEXT STOPS Algorithm Stress Test: Stability by User-State Category")
    plt.tight_layout()
    plt.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close()


# ============================================================
# Main entry
# ============================================================

def main() -> None:
    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)

    candidates = generate_candidates(n=360)

    test_df = run_stress_test(
        candidates=candidates,
        n_per_scenario=180,
    )

    summary = summarize_results(test_df)

    summary_csv = output_dir / "next_stops_algorithm_simulation_summary.csv"
    detail_csv = output_dir / "next_stops_algorithm_simulation_detail.csv"
    chart_png = output_dir / "next_stops_algorithm_stress_test_chart.png"

    summary.to_csv(summary_csv, index=False, encoding="utf-8-sig")
    test_df.to_csv(detail_csv, index=False, encoding="utf-8-sig")
    save_chart(summary, chart_png)

    print("NEXT STOPS algorithm stress test completed.")
    print(f"Summary CSV: {summary_csv}")
    print(f"Detail CSV: {detail_csv}")
    print(f"Chart PNG: {chart_png}")
    print()
    print(summary)


if __name__ == "__main__":
    main()
