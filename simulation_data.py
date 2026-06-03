from __future__ import annotations

import random
from typing import Any, Dict, List

from algorithm import (
    BASE_WEIGHTS,
    CATEGORIES,
    MOODS,
    PREFERRED_CATEGORIES_BY_MOOD,
    SECONDARY_CATEGORIES_BY_MOOD,
    Place,
    UserContext,
    clamp,
)


# ============================================================
# Simulation-only configuration
# ============================================================

SEED = 42
_random = random.Random(SEED)

SHELTERED_OUTDOOR_CATEGORIES = {"market", "riverside"}


def category_mood_mean(mood: str, category: str) -> float:
    """Return a soft prior rather than a hard mood-to-category stereotype."""

    if category in PREFERRED_CATEGORIES_BY_MOOD[mood]:
        return 0.67

    if category in SECONDARY_CATEGORIES_BY_MOOD[mood]:
        return 0.58

    return 0.49


# ============================================================
# Synthetic candidate generation
# ============================================================

def generate_candidates(n: int = 360) -> List[Place]:
    """
    Generate synthetic candidate places for algorithm stress testing.

    In production, candidates should come from real data sources such as:
        - Tourism API
        - Google Places API
        - Event API
        - Internal curated data
    """

    candidates: List[Place] = []

    for i in range(n):
        category = _random.choice(CATEGORIES)
        indoor = category in ["cafe", "museum", "bookstore", "gallery", "restaurant"]
        outdoor = not indoor
        sheltered_outdoor = category in SHELTERED_OUTDOOR_CATEGORIES

        travel_time = max(5, _random.gauss(35, 22))
        price = _random.choice(["low", "medium", "high"])

        mood_fit = {
            "relax": clamp(
                _random.gauss(
                    category_mood_mean("relax", category),
                    0.18,
                )
            ),
            "date": clamp(
                _random.gauss(
                    category_mood_mean("date", category),
                    0.18,
                )
            ),
            "solo": clamp(
                _random.gauss(
                    category_mood_mean("solo", category),
                    0.18,
                )
            ),
            "photo": clamp(
                _random.gauss(
                    category_mood_mean("photo", category),
                    0.18,
                )
            ),
            "night": clamp(
                _random.gauss(
                    category_mood_mean("night", category),
                    0.18,
                )
            ),
        }

        is_event = category == "market" or (
            category in ["gallery", "museum"] and _random.random() < 0.35
        )

        place = Place(
            id=f"place_{i:03d}",
            category=category,
            indoor=indoor,
            outdoor=outdoor,
            travel_time=travel_time,
            price=price,
            open_now=_random.random() > 0.12,
            reachable=_random.random() > 0.03,
            data_valid=_random.random() > 0.02,
            is_event=is_event,
            event_active=_random.random() > 0.08 if is_event else True,
            quality=clamp(_random.gauss(0.72, 0.16)),
            mood_fit=mood_fit,
            weather_exposure=0.15 if indoor else 0.48 if sheltered_outdoor else 0.82,
            aqi_exposure=0.08 if indoor else 0.62 if sheltered_outdoor else 0.88,
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
    "Rainy Date Near Only": {
        "mood": "date",
        "rain": (0.65, 0.90),
        "preferred_time": 20,
        "hard_max_time": 35,
        "budget": "medium",
        "boost": {"weather": 1.8, "distance": 1.5},
    },
    "Poor AQI Outdoor Craving": {
        "mood": "photo",
        "aqi": (120, 180),
        "outdoor_preferred": True,
        "preferred_time": 45,
        "hard_max_time": 70,
        "boost": {"aqi": 1.9, "environment": 1.6},
    },
    "Tired But Social": {
        "mood": "relax",
        "secondary_mood": "night",
        "secondary_mood_weight": 0.45,
        "preferred_time": 30,
        "hard_max_time": 55,
        "boost": {"mood": 1.4, "quality": 1.2},
    },
    "Low Budget Night Rain": {
        "mood": "night",
        "rain": (0.45, 0.80),
        "budget": "low",
        "preferred_time": 35,
        "boost": {"budget": 1.8, "weather": 1.4},
    },
    "Photo Walk Short Time": {
        "mood": "photo",
        "outdoor_preferred": True,
        "rain": (0.10, 0.45),
        "preferred_time": 18,
        "hard_max_time": 32,
        "boost": {"distance": 1.8, "environment": 1.3},
    },
    "Indoor Nature Craving": {
        "mood": "relax",
        "secondary_mood": "photo",
        "secondary_mood_weight": 0.30,
        "indoor_only": True,
        "rain": (0.55, 0.85),
        "boost": {"weather": 1.5, "category": 1.3},
    },
    "Weekend Flexible Crowds": {
        "mood": "date",
        "secondary_mood": "night",
        "secondary_mood_weight": 0.40,
        "ignored": ["distance"],
        "preferred_time": 75,
        "budget": "high",
        "boost": {"quality": 1.5, "category": 1.2},
    },
    "Strict Budget Poor AQI Near": {
        "mood": "solo",
        "aqi": (110, 170),
        "budget": "low",
        "preferred_time": 20,
        "hard_max_time": 35,
        "boost": {"budget": 1.8, "aqi": 1.6, "distance": 1.5},
    },
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
        focus_factor = _random.choice(list(BASE_WEIGHTS.keys()))
        user_weight_adjustment = {factor: 0.25 for factor in BASE_WEIGHTS}
        user_weight_adjustment[focus_factor] = 5.0

    user = UserContext(
        scenario=scenario_name,
        mood=config.get("mood", _random.choice(MOODS)),
        preferred_time=config.get("preferred_time", _random.choice([25, 35, 45, 60])),
        hard_max_time=config.get("hard_max_time", 120),
        rain_prob=_random.uniform(rain_low, rain_high),
        aqi=_random.uniform(aqi_low, aqi_high),
        budget=config.get("budget", _random.choice(["low", "medium", "high"])),
        secondary_mood=config.get("secondary_mood"),
        secondary_mood_weight=config.get("secondary_mood_weight", 0.35),
        ignored_factors=set(config.get("ignored", [])),
        indoor_only=config.get("indoor_only", False),
        outdoor_preferred=config.get("outdoor_preferred", False),
        user_weight_adjustment=user_weight_adjustment,
    )

    if config.get("conflict"):
        # Example conflict: photo/outdoor preference under poor weather, AQI,
        # and a strict distance limit.
        user.mood = "photo"
        user.rain_prob = _random.uniform(0.75, 0.95)
        user.aqi = _random.uniform(100, 160)
        user.preferred_time = 20
        user.hard_max_time = 35
        user.outdoor_preferred = True

    if config.get("cold_start"):
        # Cold start: no learned mood/category preference.
        user.ignored_factors = {"mood", "category"}

    user.severe_weather = user.rain_prob > 0.90

    return user
