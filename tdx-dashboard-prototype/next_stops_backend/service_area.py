"""Service-area validation for NEXT STOPS.

The current production service area is limited to Shuangbei:
Taipei City and New Taipei City.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVICE_AREA_LABEL = "雙北地區"
SERVICE_AREA_NOTICE = "NEXT STOPS 目前提供服務區域僅限雙北地區。"
SERVICE_AREA_FILE = PROJECT_ROOT / "shared" / "geo" / "service-area-shuangbei.json"
SERVICE_AREA_CACHE: dict[str, Any] | None = None


def _to_float(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def load_service_area() -> dict[str, Any]:
    global SERVICE_AREA_CACHE
    if SERVICE_AREA_CACHE is None:
        with SERVICE_AREA_FILE.open("r", encoding="utf-8") as file:
            SERVICE_AREA_CACHE = json.load(file)
    return SERVICE_AREA_CACHE


def point_in_ring(lat: float, lon: float, ring: list[list[float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i, (xi, yi) in enumerate(ring):
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat):
            boundary_lon = ((xj - xi) * (lat - yi)) / ((yj - yi) or sys.float_info.epsilon) + xi
            if lon < boundary_lon:
                inside = not inside
        j = i
    return inside


def point_in_polygon(lat: float, lon: float, polygon: list[list[list[float]]]) -> bool:
    if not polygon or not point_in_ring(lat, lon, polygon[0]):
        return False
    return not any(point_in_ring(lat, lon, hole) for hole in polygon[1:])


def find_service_area(lat: float, lon: float) -> dict[str, Any] | None:
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return None
    for feature in load_service_area().get("features", []):
        if any(point_in_polygon(lat, lon, polygon) for polygon in feature.get("polygons", [])):
            return feature
    return None


def is_within_service_area(lat: float, lon: float) -> bool:
    return find_service_area(lat, lon) is not None


def validate_criteria_service_area(criteria: dict[str, Any]) -> None:
    lat = _to_float(criteria.get("lat"))
    lon = _to_float(criteria.get("lon") if criteria.get("lon") is not None else criteria.get("lng"))
    if lat is None or lon is None:
        return
    if not is_within_service_area(lat, lon):
        raise ValueError(f"目前定位不在服務範圍內；目前提供服務區域僅限{SERVICE_AREA_LABEL}")
