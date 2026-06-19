"""General utility helpers for the NEXT STOPS backend."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def haversine_m(
    lat1: float | None,
    lon1: float | None,
    lat2: float | None,
    lon2: float | None,
) -> float | None:
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None
    radius = 6371000
    lat1_float = float(lat1)
    lon1_float = float(lon1)
    lat2_float = float(lat2)
    lon2_float = float(lon2)
    phi1 = math.radians(lat1_float)
    phi2 = math.radians(lat2_float)
    delta_phi = math.radians(lat2_float - lat1_float)
    delta_lambda = math.radians(lon2_float - lon1_float)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def decode_polyline(polyline: str) -> list[list[float]]:
    coordinates = []
    index = 0
    lat = 0
    lng = 0

    while index < len(polyline):
        shift = 0
        result = 0
        while True:
            byte = ord(polyline[index]) - 63
            index += 1
            result |= (byte & 0x1F) << shift
            shift += 5
            if byte < 0x20:
                break
        lat += ~(result >> 1) if result & 1 else result >> 1

        shift = 0
        result = 0
        while True:
            byte = ord(polyline[index]) - 63
            index += 1
            result |= (byte & 0x1F) << shift
            shift += 5
            if byte < 0x20:
                break
        lng += ~(result >> 1) if result & 1 else result >> 1
        coordinates.append([lng / 100000.0, lat / 100000.0])

    return coordinates


def format_duration(seconds: int | float | None) -> str:
    if seconds is None:
        return "--"
    minutes = max(1, round(float(seconds) / 60))
    if minutes < 60:
        return f"{minutes} 分"
    hours = minutes // 60
    rest = minutes % 60
    return f"{hours} 小時 {rest} 分" if rest else f"{hours} 小時"


def format_distance(meters: int | float | None) -> str:
    if meters is None:
        return "--"
    meters = float(meters)
    if meters >= 1000:
        return f"{meters / 1000:.1f} 公里"
    return f"{round(meters)} 公尺"


def parse_google_duration_seconds(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith("s"):
        text = text[:-1]
    try:
        return max(1, round(float(text)))
    except ValueError:
        return None
