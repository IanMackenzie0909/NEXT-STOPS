"""Routing and Google Maps/Places helpers for NEXT STOPS."""

from __future__ import annotations

import os
import re
from typing import Any

import requests

from .utils import (
    decode_polyline,
    format_distance,
    format_duration,
    haversine_m,
    parse_google_duration_seconds,
    to_float,
)


GOOGLE_DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"
GOOGLE_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
GOOGLE_GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"
GOOGLE_PLACE_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
GOOGLE_FIND_PLACE_URL = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
ROUTE_COMPARE_MODES = ("CAR", "BUS", "MRT", "MOTORCYCLE", "WALKING", "BICYCLE")

COMMUTE_MODE_LABELS = {
    "TRANSIT": "大眾運輸",
    "CAR": "開車",
    "BUS": "公車",
    "MRT": "捷運",
    "MOTORCYCLE": "機車",
    "BICYCLE": "腳踏車",
    "WALKING": "步行",
    "DRIVING": "開車",
}

BUS_VEHICLE_TYPES = {"BUS", "INTERCITY_BUS", "TROLLEYBUS"}
RAIL_VEHICLE_TYPES = {
    "SUBWAY",
    "METRO_RAIL",
    "RAIL",
    "HEAVY_RAIL",
    "COMMUTER_TRAIN",
    "HIGH_SPEED_TRAIN",
    "TRAM",
    "MONORAIL",
}

FRONTEND_TRANSPORT_TO_BACKEND = {
    "car": "CAR",
    "bus": "BUS",
    "mrt": "MRT",
    "motorcycle": "MOTORCYCLE",
    "scooter": "MOTORCYCLE",
    "walking": "WALKING",
    "walk": "WALKING",
    "bicycle": "BICYCLE",
    "bike": "BICYCLE",
}

google_place_status_cache: dict[str, dict[str, Any]] = {}
google_place_lookup_cache: dict[str, str] = {}


class TransitModeMismatchError(RuntimeError):
    """Raised when Google returns a transit route that uses a different vehicle type."""


class RouteUnavailableError(RuntimeError):
    """Raised when a route provider confirms that the requested mode has no route."""


def get_google_maps_key() -> str:
    return (
        os.getenv("GOOGLE_MAPS_SERVER_KEY")
        or os.getenv("GOOGLE_MAPS_API_KEY")
        or os.getenv("GOOGLE_MAPS_BROWSER_KEY")
        or ""
    )


def google_route_params(mode: str) -> dict[str, str]:
    mapping = {
        "CAR": {"mode": "driving"},
        "DRIVING": {"mode": "driving"},
        "WALKING": {"mode": "walking"},
        "BICYCLE": {"mode": "bicycling"},
        "BUS": {"mode": "transit", "transit_mode": "bus"},
        "MRT": {"mode": "transit", "transit_mode": "subway|train"},
        "TRANSIT": {"mode": "transit"},
    }
    return mapping.get(mode, {"mode": "transit"})


def transit_step_summary(leg: dict[str, Any]) -> dict[str, Any]:
    steps = []
    walking_seconds = 0
    transfers = 0
    lines = []
    for step in leg.get("steps") or []:
        travel_mode = step.get("travel_mode")
        duration_seconds = step.get("duration", {}).get("value")
        if travel_mode == "WALKING":
            walking_seconds += int(duration_seconds or 0)
            steps.append({
                "type": "walk",
                "duration_text": step.get("duration", {}).get("text", ""),
                "distance_text": step.get("distance", {}).get("text", ""),
                "instruction": re.sub(r"<[^>]+>", "", step.get("html_instructions") or ""),
            })
            continue
        if travel_mode == "TRANSIT":
            details = step.get("transit_details") or {}
            line = details.get("line") or {}
            vehicle = line.get("vehicle") or {}
            line_name = line.get("short_name") or line.get("name") or vehicle.get("name") or "大眾運輸"
            lines.append(str(line_name))
            transfers += 1
            steps.append({
                "type": "transit",
                "line": line_name,
                "vehicle_type": vehicle.get("type") or "",
                "vehicle": vehicle.get("name") or "",
                "departure_stop": (details.get("departure_stop") or {}).get("name", ""),
                "arrival_stop": (details.get("arrival_stop") or {}).get("name", ""),
                "num_stops": details.get("num_stops"),
                "duration_text": step.get("duration", {}).get("text", ""),
            })
    return {
        "walking_duration_seconds": walking_seconds,
        "walking_duration_text": format_duration(walking_seconds) if walking_seconds else "",
        "transfer_count": max(0, transfers - 1),
        "board_count": transfers,
        "lines": lines,
        "steps": steps,
    }


def validate_transit_route_for_mode(mode: str, leg: dict[str, Any]) -> None:
    if mode not in {"BUS", "MRT"}:
        return

    allowed_types = BUS_VEHICLE_TYPES if mode == "BUS" else RAIL_VEHICLE_TYPES
    transit_vehicle_types = []
    for step in leg.get("steps") or []:
        if step.get("travel_mode") != "TRANSIT":
            continue
        details = step.get("transit_details") or {}
        line = details.get("line") or {}
        vehicle = line.get("vehicle") or {}
        vehicle_type = str(vehicle.get("type") or "").upper()
        if vehicle_type:
            transit_vehicle_types.append(vehicle_type)

    if not transit_vehicle_types:
        raise TransitModeMismatchError(f"Google returned no transit segment for {mode}")

    invalid_types = sorted({vehicle_type for vehicle_type in transit_vehicle_types if vehicle_type not in allowed_types})
    if invalid_types:
        expected = "bus" if mode == "BUS" else "subway/train"
        raise TransitModeMismatchError(
            f"Google returned {', '.join(invalid_types)} segment for {mode}; expected {expected} only"
        )


def google_routes_two_wheeler(origin: dict[str, Any], destination: dict[str, Any], include_geometry: bool = False) -> dict[str, Any]:
    key = get_google_maps_key()
    if not key:
        raise RuntimeError("Google Maps API key is not configured")

    response = requests.post(
        GOOGLE_ROUTES_URL,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": key,
            "X-Goog-FieldMask": "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline,routes.description,routes.localizedValues",
        },
        json={
            "origin": {"location": {"latLng": {"latitude": origin["lat"], "longitude": origin["lon"]}}},
            "destination": {"location": {"latLng": {"latitude": destination["lat"], "longitude": destination["lon"]}}},
            "travelMode": "TWO_WHEELER",
            "languageCode": "zh-TW",
            "regionCode": "TW",
            "computeAlternativeRoutes": False,
            "polylineEncoding": "ENCODED_POLYLINE",
        },
        timeout=10,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise RouteUnavailableError(f"Google Routes two-wheeler unavailable: {exc}") from exc
    payload = response.json()
    routes = payload.get("routes") or []
    if not routes:
        raise RouteUnavailableError("Google Routes returned no two-wheeler route")

    route = routes[0]
    localized = route.get("localizedValues") or {}
    duration_seconds = parse_google_duration_seconds(route.get("duration"))
    distance_meters = route.get("distanceMeters")
    result = {
        "provider": "google_routes",
        "mode": "MOTORCYCLE",
        "mode_label": COMMUTE_MODE_LABELS["MOTORCYCLE"],
        "distance_text": (localized.get("distance") or {}).get("text") or format_distance(distance_meters),
        "distance_meters": distance_meters,
        "duration_text": (localized.get("duration") or {}).get("text") or format_duration(duration_seconds),
        "duration_seconds": duration_seconds,
        "summary": route.get("description") or "two-wheeler route",
        "origin": {"lat": origin["lat"], "lon": origin["lon"]},
        "destination": {"lat": destination["lat"], "lon": destination["lon"]},
        "notice": "Google two-wheeler routes can vary by region and may be beta quality.",
    }
    encoded = (route.get("polyline") or {}).get("encodedPolyline")
    if include_geometry and encoded:
        result["geometry"] = {
            "type": "LineString",
            "coordinates": decode_polyline(encoded),
        }
    return result


def google_directions(origin: dict[str, Any], destination: dict[str, Any], mode: str, include_geometry: bool = False) -> dict[str, Any]:
    key = get_google_maps_key()
    if not key:
        raise RuntimeError("Google Maps API key is not configured")
    if mode == "MOTORCYCLE":
        return google_routes_two_wheeler(origin, destination, include_geometry=include_geometry)

    route_params = google_route_params(mode)
    response = requests.get(
        GOOGLE_DIRECTIONS_URL,
        params={
            "origin": f"{origin['lat']},{origin['lon']}",
            "destination": f"{destination['lat']},{destination['lon']}",
            **route_params,
            "region": "tw",
            "language": "zh-TW",
            "key": key,
        },
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    status = payload.get("status")
    if status != "OK":
        message = payload.get("error_message") or status or "Google Directions failed"
        if status in {"ZERO_RESULTS", "NOT_FOUND", "MAX_ROUTE_LENGTH_EXCEEDED"}:
            raise RouteUnavailableError(message)
        raise RuntimeError(message)

    route = payload["routes"][0]
    leg = route["legs"][0]
    validate_transit_route_for_mode(mode, leg)
    result = {
        "provider": "google",
        "mode": mode,
        "mode_label": COMMUTE_MODE_LABELS.get(mode, mode),
        "distance_text": leg.get("distance", {}).get("text", ""),
        "distance_meters": leg.get("distance", {}).get("value"),
        "duration_text": leg.get("duration", {}).get("text", ""),
        "duration_seconds": leg.get("duration", {}).get("value"),
        "summary": route.get("summary", ""),
        "origin": {
            "lat": origin["lat"],
            "lon": origin["lon"],
            "address": leg.get("start_address", ""),
        },
        "destination": {
            "lat": destination["lat"],
            "lon": destination["lon"],
            "address": leg.get("end_address", ""),
        },
    }
    if route_params.get("mode") == "transit":
        transit = transit_step_summary(leg)
        result["transit"] = transit
        result["transfer_count"] = transit["transfer_count"]
        result["walking_duration_text"] = transit["walking_duration_text"]
        if transit["lines"]:
            result["summary"] = " / ".join(transit["lines"][:3])
    if include_geometry:
        result["geometry"] = {
            "type": "LineString",
            "coordinates": decode_polyline(route["overview_polyline"]["points"]),
        }
    return result


def google_geocode(query: str) -> dict[str, Any] | None:
    key = get_google_maps_key()
    if not key or not query.strip():
        return None
    response = requests.get(
        GOOGLE_GEOCODING_URL,
        params={
            "address": query,
            "region": "tw",
            "language": "zh-TW",
            "key": key,
        },
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != "OK" or not payload.get("results"):
        return None
    result = payload["results"][0]
    location = result.get("geometry", {}).get("location", {})
    lat = to_float(location.get("lat"))
    lon = to_float(location.get("lng"))
    if lat is None or lon is None:
        return None
    return {
        "lat": lat,
        "lon": lon,
        "address": result.get("formatted_address", ""),
        "place_id": result.get("place_id", ""),
    }


def google_find_place_id(query: str) -> str:
    normalized_query = " ".join(str(query or "").split())
    if not normalized_query:
        return ""
    if normalized_query in google_place_lookup_cache:
        return google_place_lookup_cache[normalized_query]

    key = get_google_maps_key()
    if not key:
        return ""
    try:
        response = requests.get(
            GOOGLE_FIND_PLACE_URL,
            params={
                "input": normalized_query,
                "inputtype": "textquery",
                "fields": "place_id,name,formatted_address,business_status",
                "language": "zh-TW",
                "locationbias": "circle:35000@25.0478,121.5170",
                "key": key,
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return ""

    candidates = payload.get("candidates") or []
    place_id = str(candidates[0].get("place_id") or "").strip() if candidates else ""
    google_place_lookup_cache[normalized_query] = place_id
    return place_id


def raw_google_place_id(raw: dict[str, Any]) -> str:
    direct = str(raw.get("geocoded_place_id") or raw.get("place_id") or "").strip()
    if direct:
        return direct
    source_ids = raw.get("source_ids") if isinstance(raw.get("source_ids"), dict) else {}
    for key in ("google_places", "google", "place_id"):
        value = str(source_ids.get(key) or "").strip()
        if value:
            return value
    base_query = " ".join(
        str(part)
        for part in [
            raw.get("name"),
            raw.get("address"),
            raw.get("district"),
            "臺北市",
        ]
        if part
    )
    name = str(raw.get("name") or "")
    description = str(raw.get("description") or "")
    query_variants = []
    if re.search(r"台北\s*101|臺北\s*101|taipei\s*101", name, re.IGNORECASE):
        if re.search(r"觀景|觀景台|89", description):
            query_variants.append("台北101 觀景台")
        query_variants.extend(["台北101 購物中心", "台北101"])
    query_variants.append(base_query)
    for query in query_variants:
        place_id = google_find_place_id(query)
        if place_id:
            return place_id
    return ""


def google_place_open_status(place_id: str | None) -> dict[str, Any]:
    place_id = str(place_id or "").strip()
    if not place_id:
        return {"open_now": None, "status": "unknown", "source": "none", "detail": "missing_place_id"}
    if place_id in google_place_status_cache:
        return google_place_status_cache[place_id]

    key = get_google_maps_key()
    if not key:
        return {"open_now": None, "status": "unknown", "source": "none", "detail": "missing_google_key"}

    try:
        response = requests.get(
            GOOGLE_PLACE_DETAILS_URL,
            params={
                "place_id": place_id,
                "fields": "business_status,opening_hours,name,formatted_address,geometry",
                "language": "zh-TW",
                "region": "tw",
                "key": key,
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return {"open_now": None, "status": "unknown", "source": "google_places", "detail": str(exc)}

    if payload.get("status") != "OK":
        return {
            "open_now": None,
            "status": "unknown",
            "source": "google_places",
            "detail": payload.get("error_message") or payload.get("status") or "place_details_failed",
        }

    result = payload.get("result") or {}
    business_status = result.get("business_status") or ""
    location = result.get("geometry", {}).get("location", {})
    detail_base = {
        "place_id": place_id,
        "google_name": result.get("name") or "",
        "google_address": result.get("formatted_address") or "",
        "google_lat": to_float(location.get("lat")),
        "google_lon": to_float(location.get("lng")),
    }
    if business_status in {"CLOSED_TEMPORARILY", "CLOSED_PERMANENTLY"}:
        status = {
            **detail_base,
            "open_now": False,
            "status": "closed",
            "source": "google_places",
            "detail": business_status,
        }
    else:
        open_now = result.get("opening_hours", {}).get("open_now")
        status = {
            **detail_base,
            "open_now": open_now if isinstance(open_now, bool) else None,
            "status": "open" if open_now is True else "closed" if open_now is False else "unknown",
            "source": "google_places",
            "detail": business_status or "opening_hours",
        }
    google_place_status_cache[place_id] = status
    return status


def raw_open_status(raw: dict[str, Any]) -> dict[str, Any]:
    explicit = raw.get("open_now")
    if isinstance(explicit, bool):
        return {
            "open_now": explicit,
            "status": "open" if explicit else "closed",
            "source": "raw_open_now",
            "detail": "",
        }

    opening_hours = str(raw.get("opening_hours") or raw.get("open_time") or raw.get("OpenTime") or "").strip()
    if opening_hours and re.search(r"24\s*小時|24\s*hours|24/7|全天", opening_hours, re.IGNORECASE):
        return {"open_now": True, "status": "open", "source": "opening_hours", "detail": opening_hours}

    place_id = raw_google_place_id(raw)
    status = google_place_open_status(place_id)
    if place_id:
        status = {**status, "place_id": place_id}
    return status


def fallback_commute(origin: dict[str, Any], destination: dict[str, Any], mode: str, include_geometry: bool = False) -> dict[str, Any]:
    distance = haversine_m(origin.get("lat"), origin.get("lon"), destination.get("lat"), destination.get("lon")) or 0
    speed_mps = {
        "WALKING": 1.25,
        "TRANSIT": 5.8,
        "DRIVING": 7.5,
        "CAR": 7.5,
        "BUS": 5.2,
        "MRT": 6.4,
        "MOTORCYCLE": 8.5,
        "BICYCLE": 3.8,
    }.get(mode, 5.8)
    overhead_seconds = {
        "WALKING": 0,
        "TRANSIT": 420,
        "DRIVING": 300,
        "CAR": 300,
        "BUS": 540,
        "MRT": 660,
        "MOTORCYCLE": 240,
        "BICYCLE": 120,
    }.get(mode, 300)
    seconds = max(60, round(distance / speed_mps + overhead_seconds))
    result = {
        "provider": "heuristic",
        "mode": mode,
        "mode_label": COMMUTE_MODE_LABELS.get(mode, mode),
        "distance_text": format_distance(distance),
        "distance_meters": round(distance),
        "duration_text": format_duration(seconds),
        "duration_seconds": seconds,
        "summary": "heuristic fallback",
        "origin": {"lat": origin.get("lat"), "lon": origin.get("lon")},
        "destination": {"lat": destination.get("lat"), "lon": destination.get("lon")},
    }
    if mode in {"BUS", "MRT", "TRANSIT"}:
        result["transit"] = {
            "walking_duration_seconds": min(round(seconds * 0.28), 900),
            "walking_duration_text": format_duration(min(round(seconds * 0.28), 900)),
            "transfer_count": 0,
            "board_count": 1,
            "lines": [],
            "steps": [],
        }
        result["walking_duration_text"] = result["transit"]["walking_duration_text"]
        result["transfer_count"] = 0
    if include_geometry:
        result["geometry"] = {
            "type": "LineString",
            "coordinates": [
                [origin.get("lon"), origin.get("lat")],
                [destination.get("lon"), destination.get("lat")],
            ],
        }
    return result


def unavailable_commute(
    origin: dict[str, Any],
    destination: dict[str, Any],
    mode: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "provider": "unavailable",
        "available": False,
        "mode": mode,
        "mode_label": COMMUTE_MODE_LABELS.get(mode, mode),
        "distance_text": "",
        "distance_meters": None,
        "duration_text": "路線不可用",
        "duration_seconds": None,
        "summary": reason,
        "origin": {"lat": origin.get("lat"), "lon": origin.get("lon")},
        "destination": {"lat": destination.get("lat"), "lon": destination.get("lon")},
    }


def normalize_transport_modes(value: Any) -> tuple[str, ...]:
    if value in (None, "", []):
        return ROUTE_COMPARE_MODES
    raw_items = value
    if isinstance(value, str):
        raw_items = [item.strip() for item in value.split(",")]
    if not isinstance(raw_items, (list, tuple, set)):
        return ROUTE_COMPARE_MODES
    modes = []
    for item in raw_items:
        key = str(item or "").strip()
        upper = key.upper()
        mode = FRONTEND_TRANSPORT_TO_BACKEND.get(key.lower(), upper)
        if mode in ROUTE_COMPARE_MODES and mode not in modes:
            modes.append(mode)
    return tuple(modes) if modes else ROUTE_COMPARE_MODES


def compare_commute_options(
    origin: dict[str, Any],
    destination: dict[str, Any],
    modes: tuple[str, ...] = ROUTE_COMPARE_MODES,
    include_geometry: bool = False,
) -> dict[str, Any]:
    options = []
    errors = {}
    for mode in modes:
        try:
            option = google_directions(origin, destination, mode, include_geometry=include_geometry)
        except (TransitModeMismatchError, RouteUnavailableError) as exc:
            errors[mode] = str(exc)
            option = unavailable_commute(origin, destination, mode, str(exc))
        except Exception as exc:
            errors[mode] = str(exc)
            option = fallback_commute(origin, destination, mode, include_geometry=include_geometry)
        options.append(option)

    best = min(
        options,
        key=lambda item: (
            999999
            if item.get("available") is False
            else item.get("duration_seconds") or 999999
        ),
    )
    if include_geometry and best.get("available") is not False and "geometry" not in best:
        best = {
            **best,
            **fallback_commute(origin, destination, best["mode"], include_geometry=True),
        }
    return {
        "best": best,
        "options": options,
        "errors": errors,
    }
