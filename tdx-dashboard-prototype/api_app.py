"""Unified FastAPI app for NEXT STOPS external-data clients.

Run from this directory:
  uvicorn api_app:app --reload --host 127.0.0.1 --port 8790
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import requests

try:
    from fastapi import FastAPI, HTTPException
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("請先安裝 FastAPI dependencies：pip install -r requirements.txt") from exc

from next_stops_backend.config import (
    ATTRACTION_CACHE,
    CATEGORY_LABELS,
    DEFAULT_MAPBOX_TOKEN,
    FEEDBACK_WEIGHT_RULES,
    FRONTEND_MOOD_TO_ALGORITHM,
    LOCATION_HINTS,
    MAX_STATION_RESULTS,
    MOOD_LABELS,
    MOOD_QUERIES,
    PROJECT_ROOT,
    SAMPLE_LOCATIONS,
    ensure_attraction_platform_on_path,
    env_first,
    load_module,
    load_module_from_path,
    load_root_env,
)

load_root_env()

from next_stops_backend.admin import AdminService, require_admin
from next_stops_backend.auth import (
    auth_config,
    delete_user_account,
    login_google_user,
    login_platform_user,
    logout_auth_session,
    normalize_favorite_starts,
    register_platform_user,
    require_current_user,
    update_user_preferences,
    update_user_profile,
)
from next_stops_backend.database import (
    RECOMMENDATION_DB,
    USE_POSTGRES,
    connect_recommendation_db,
    init_recommendation_db,
)
from next_stops_backend.routers import (
    admin as admin_router,
    auth as auth_router,
    places as places_router,
    recommendations as recommendations_router,
    routes as routes_router,
    transport as transport_router,
    weather as weather_router,
)
from next_stops_backend.routing import (
    ROUTE_COMPARE_MODES,
    compare_commute_options,
    google_geocode,
    normalize_transport_modes,
    raw_open_status,
)
from next_stops_backend.security import (
    DEFAULT_MAX_BODY_BYTES,
    RATE_LIMIT_STORE,
    UNSAFE_METHODS,
    allowed_browser_origins,
    check_rate_limit,
    configure_cors,
    env_int,
    install_api_abuse_protection,
    security_config_summary,
    security_headers_for,
    unsafe_request_rejection,
)
from next_stops_backend.service_area import find_service_area, is_within_service_area, validate_criteria_service_area
from next_stops_backend.transport import CachedTDX
from next_stops_backend.utils import (
    haversine_m,
    now_iso,
    to_float,
)

cwa_module = load_module("cwa_weather_api_clients", "CWA-Weather_API_clients.py")
moenv_module = load_module("moenv_aqi_api_clients", "MOENV-AQI_API_clients.py")
weather_aqi_module = load_module("weather_aqi_api_clients", "Weather-AQI_API_clients.py")
bus_module = load_module("tdx_bus_api_clients", "TDX-BUS_API_clients.py")
mrt_module = load_module("tdx_mrt_api_clients", "TDX-MRT_API_clients.py")
recommendation_algorithm = load_module_from_path("next_stops_recommendation_algorithm", PROJECT_ROOT / "algorithm.py")

ensure_attraction_platform_on_path()

try:
    from taipei_attraction_platform.services.search_service import TaipeiAttractionSearchService
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Cannot import Taipei attraction search service") from exc


app = FastAPI(title="NEXT STOPS Data API", version="1.0.0")
configure_cors(app)
install_api_abuse_protection(app)


bus_tdx = CachedTDX(bus_module, "TDX_BUS")
mrt_tdx = CachedTDX(mrt_module, "TDX_MRT")
weather_aqi_client = weather_aqi_module.WeatherAQIClient()
bus_station_cache: dict[str, dict[str, Any]] = {}
mrt_stations_cache: dict[str, Any] = {"items": [], "fetched_at": None}
attraction_service_cache: dict[str, Any] = {"service": None, "loaded_at": None}


def normalize_search_text(value: object) -> str:
    return str(value or "").strip().lower().replace("台", "臺")


def ensure_list_response(data: Any, label: str) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        message = (
            data.get("message")
            or data.get("Message")
            or data.get("error")
            or data.get("Error")
            or json.dumps(data, ensure_ascii=False)
        )
        raise RuntimeError(f"TDX {label} returned an error: {message}")
    raise RuntimeError(f"TDX {label} returned unexpected data: {type(data).__name__}")


def api_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    for module in (bus_module, mrt_module):
        if isinstance(exc, module.TDXRateLimitError):
            return HTTPException(status_code=429, detail=str(exc))
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        status = exc.response.status_code
        return HTTPException(status_code=status if 400 <= status < 600 else 500, detail=f"External API request failed: {exc}")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def run_or_raise(func):
    try:
        return func()
    except Exception as exc:
        raise api_error(exc) from exc


def get_mapbox_token() -> str:
    return env_first("MAPBOX_ACCESS_TOKEN", default=DEFAULT_MAPBOX_TOKEN)


def get_attraction_service() -> TaipeiAttractionSearchService:
    if attraction_service_cache["service"] is not None:
        return attraction_service_cache["service"]

    service = (
        TaipeiAttractionSearchService.from_cache(ATTRACTION_CACHE)
        if ATTRACTION_CACHE.exists()
        else TaipeiAttractionSearchService(cache_path=ATTRACTION_CACHE)
    )
    if not service.index.places:
        try:
            service.build()
        except Exception as exc:
            raise RuntimeError(
                "Attraction cache is empty and automatic build failed. "
                "Run POST /api/places/build after network/API setup, or start the attraction service build first. "
                f"Original error: {exc}"
            ) from exc

    attraction_service_cache["service"] = service
    attraction_service_cache["loaded_at"] = now_iso()
    return service


def serialize_search_results(results: list) -> list[dict[str, Any]]:
    return [result.to_dict() for result in results]


def search_attraction_places(
    q: str | None = None,
    district: str | None = None,
    category: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_m: int | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    service = get_attraction_service()
    return serialize_search_results(
        service.search(
            query=q,
            district=district,
            category=category,
            lat=lat,
            lon=lon,
            radius_m=radius_m,
            limit=limit,
            include_missing_coordinates=False,
        )
    )


def get_attraction_place_by_id(place_id: str) -> dict[str, Any] | None:
    normalized_id = str(place_id or "").strip()
    if not normalized_id:
        return None
    service = get_attraction_service()
    for place in service.index.places:
        if str(place.id) == normalized_id:
            return place.to_dict()
    return None


def detail_criteria_from_query(
    lat: float | None = None,
    lon: float | None = None,
    mood: str = "relaxing_walk",
    distance: int = 30,
    time_minutes: int = 120,
    budget: str = "medium",
    weather_preference: str = "any",
    transport_modes: str | None = None,
) -> dict[str, Any]:
    criteria = {
        "mood": mood or "relaxing_walk",
        "distance": distance or 30,
        "time": time_minutes or 120,
        "budget": budget or "medium",
        "weatherPreference": weather_preference or "any",
        "transportModes": list(normalize_transport_modes(transport_modes)),
        "location": "taipei_main",
        "locationLabel": LOCATION_HINTS["taipei_main"]["label"],
    }
    if lat is not None and lon is not None:
        criteria.update({
            "location": "current",
            "locationLabel": "目前定位",
            "lat": lat,
            "lon": lon,
        })
    return criteria


def build_nearby_backups(
    display_place: dict[str, Any],
    criteria: dict[str, Any],
    context: dict[str, Any],
    limit: int = 3,
) -> list[dict[str, Any]]:
    lat = to_float(display_place.get("lat"))
    lon = to_float(display_place.get("lon") if display_place.get("lon") is not None else display_place.get("lng"))
    if lat is None or lon is None:
        return []

    indoor_only = bool(user_context_from_criteria(criteria, context).indoor_only)
    results: list[dict[str, Any]] = []
    seen = {str(display_place.get("id"))}
    for raw in search_attraction_places(lat=lat, lon=lon, radius_m=1400, limit=max(18, limit * 7)):
        raw_id = str(raw.get("id") or "")
        if not raw_id or raw_id in seen:
            continue
        seen.add(raw_id)
        categories = [str(item) for item in raw.get("categories") or [] if item]
        text = " ".join([
            str(raw.get("name") or ""),
            str(raw.get("description") or ""),
            str(raw.get("district") or ""),
            " ".join(categories),
        ])
        category = primary_category(categories, text)
        indoor, _outdoor = place_environment(category, categories, text)
        if indoor_only and not indoor:
            continue
        open_status = raw_open_status(raw)
        if open_status.get("open_now") is False:
            continue
        raw_lat = to_float(raw.get("lat"))
        raw_lon = to_float(raw.get("lon") if raw.get("lon") is not None else raw.get("lng"))
        if raw_lat is None or raw_lon is None:
            continue
        backup = {
            "id": raw_id,
            "name": raw.get("name") or raw_id,
            "category": display_category(category),
            "address": raw.get("address") or f"{raw.get('district') or '臺北市'} / 臺北市",
            "lat": raw_lat,
            "lon": raw_lon,
            "lng": raw_lon,
            "distance_from_place_m": round(haversine_m(lat, lon, raw_lat, raw_lon) or 0),
            "open_now": open_status.get("open_now"),
            "opening_status": open_status.get("status"),
        }
        results.append(backup)
        if len(results) >= limit:
            break
    return [
        {
            "id": item["id"],
            "name": item["name"],
            "category": item["category"],
            "address": item.get("address"),
            "lat": item.get("lat"),
            "lon": item.get("lon"),
            "lng": item.get("lng"),
            "distance_m": item.get("distance_from_place_m"),
            "open_now": item.get("open_now"),
            "opening_status": item.get("opening_status"),
        }
        for item in results
    ]


def build_place_detail(
    place_id: str,
    criteria: dict[str, Any],
    session_id: str | None = None,
) -> dict[str, Any]:
    raw = get_attraction_place_by_id(place_id)
    if raw is None:
        raise HTTPException(status_code=404, detail="Place not found")
    signals = build_session_preference_signals(session_id)
    criteria = criteria_with_preference_signals(criteria, signals)
    context = recommendation_context(criteria)
    normalized = normalize_place_payload(raw, criteria, context)
    apply_preference_signals_to_candidates([normalized], signals)
    user = user_context_from_criteria(criteria, context)
    recommendations, _filtered_reasons = recommendation_algorithm.recommend(
        [normalized["algorithm_place"]],
        user,
        k=1,
    )
    if recommendations:
        display = format_recommendation_result(recommendations[0], normalized["display"], criteria, context)
    else:
        display = {
            **normalized["display"],
            "score": 0,
            "reason": (
                f"{normalized['display']['name']} 已載入詳細資料，但依目前條件可能不適合直接安排；"
                "請確認營業狀態、天氣與通勤時間後再決定。"
            ),
            "algorithm_reason": "Filtered by the current recommendation constraints.",
            "algorithm": {"fallback": True, "score": 0, "active_factors": []},
            "context": {
                "weather": context.get("weather", {}),
                "air_quality": context.get("air_quality", {}),
                "uv": context.get("uv", {}),
                "outdoor_comfort": context.get("outdoor_comfort"),
            },
        }
    display["backup_options"] = build_nearby_backups(display, criteria, context)
    display["preference_signals"] = signals
    return display


def record_recommendation(
    request_id: str,
    session_id: str | None,
    criteria: dict[str, Any],
    context: dict[str, Any],
    source_status: dict[str, Any],
    results: list[dict[str, Any]],
) -> None:
    init_recommendation_db()
    with connect_recommendation_db() as db:
        db.execute(
            """
            INSERT INTO recommendation_requests (
                id, created_at, session_id, criteria_json, context_json, source_status_json, result_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                now_iso(),
                session_id,
                json.dumps(criteria, ensure_ascii=False),
                json.dumps(context, ensure_ascii=False),
                json.dumps(source_status, ensure_ascii=False),
                len(results),
            ),
        )
        db.executemany(
            """
            INSERT INTO recommendation_results (
                request_id, rank, place_id, place_name, score, uncertainty, reason, result_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    request_id,
                    index + 1,
                    result.get("id", ""),
                    result.get("name", ""),
                    float(result.get("algorithm", {}).get("score", 0)),
                    float(result.get("algorithm", {}).get("uncertainty", 0)),
                    result.get("reason", ""),
                    json.dumps(result, ensure_ascii=False),
                )
                for index, result in enumerate(results)
            ],
        )


def fetch_recommendation_record(request_id: str) -> dict[str, Any] | None:
    init_recommendation_db()
    with connect_recommendation_db() as db:
        db.row_factory = sqlite3.Row
        request = db.execute("SELECT * FROM recommendation_requests WHERE id = ?", (request_id,)).fetchone()
        if request is None:
            return None
        rows = db.execute(
            "SELECT * FROM recommendation_results WHERE request_id = ? ORDER BY rank",
            (request_id,),
        ).fetchall()

    return {
        "id": request["id"],
        "created_at": request["created_at"],
        "session_id": request["session_id"],
        "criteria": json.loads(request["criteria_json"]),
        "context": json.loads(request["context_json"]),
        "source_status": json.loads(request["source_status_json"]),
        "count": request["result_count"],
        "results": [json.loads(row["result_json"]) for row in rows],
    }


def saved_place_from_row(row: sqlite3.Row) -> dict[str, Any]:
    place = json.loads(row["place_json"])
    return {
        **place,
        "id": row["place_id"],
        "name": row["name"],
        "category": row["category"],
        "address": row["address"],
        "lat": row["lat"],
        "lng": row["lng"],
        "note": row["note"] or "",
        "saved_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_saved_places(session_id: str) -> list[dict[str, Any]]:
    init_recommendation_db()
    with connect_recommendation_db() as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT * FROM saved_places WHERE session_id = ? ORDER BY updated_at DESC",
            (session_id,),
        ).fetchall()
    return [saved_place_from_row(row) for row in rows]


def upsert_saved_place(payload: dict[str, Any]) -> dict[str, Any]:
    session_id = str(payload.get("session_id") or "").strip()
    place = payload.get("place") or payload
    if not session_id:
        raise ValueError("session_id is required")
    if not isinstance(place, dict) or not place.get("id") or not place.get("name"):
        raise ValueError("place.id and place.name are required")

    place_id = str(place["id"])
    now = now_iso()
    lat = to_float(place.get("lat"))
    lng = to_float(place.get("lng") if place.get("lng") is not None else place.get("lon"))
    note = str(payload.get("note") if payload.get("note") is not None else place.get("note") or "")
    init_recommendation_db()
    with connect_recommendation_db() as db:
        db.row_factory = sqlite3.Row
        db.execute(
            """
            INSERT INTO saved_places (
                session_id, place_id, name, category, address, lat, lng, note, place_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id, place_id) DO UPDATE SET
                name = excluded.name,
                category = excluded.category,
                address = excluded.address,
                lat = excluded.lat,
                lng = excluded.lng,
                note = excluded.note,
                place_json = excluded.place_json,
                updated_at = excluded.updated_at
            """,
            (
                session_id,
                place_id,
                str(place.get("name") or ""),
                str(place.get("category") or ""),
                str(place.get("address") or ""),
                lat,
                lng,
                note,
                json.dumps({**place, "note": note}, ensure_ascii=False),
                now,
                now,
            ),
        )
        row = db.execute(
            "SELECT * FROM saved_places WHERE session_id = ? AND place_id = ?",
            (session_id, place_id),
        ).fetchone()
    build_session_preference_signals(session_id)
    return saved_place_from_row(row)


def update_saved_place_note(session_id: str, place_id: str, note: str) -> dict[str, Any] | None:
    init_recommendation_db()
    with connect_recommendation_db() as db:
        db.row_factory = sqlite3.Row
        db.execute(
            "UPDATE saved_places SET note = ?, updated_at = ? WHERE session_id = ? AND place_id = ?",
            (note, now_iso(), session_id, place_id),
        )
        row = db.execute(
            "SELECT * FROM saved_places WHERE session_id = ? AND place_id = ?",
            (session_id, place_id),
        ).fetchone()
    return saved_place_from_row(row) if row else None


def remove_saved_place(session_id: str, place_id: str) -> dict[str, Any]:
    init_recommendation_db()
    with connect_recommendation_db() as db:
        cursor = db.execute(
            "DELETE FROM saved_places WHERE session_id = ? AND place_id = ?",
            (session_id, place_id),
        )
    build_session_preference_signals(session_id)
    return {"ok": True, "deleted": cursor.rowcount}


def record_feedback(payload: dict[str, Any]) -> dict[str, Any]:
    session_id = str(payload.get("session_id") or "").strip()
    place_id = str(payload.get("place_id") or "").strip()
    feedback_type = str(payload.get("feedback_type") or "").strip()
    if not session_id:
        raise ValueError("session_id is required")
    if not place_id:
        raise ValueError("place_id is required")
    if not feedback_type:
        raise ValueError("feedback_type is required")

    init_recommendation_db()
    insert_sql = """
            INSERT INTO recommendation_feedback (
                session_id, request_id, place_id, feedback_type, note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """
    if USE_POSTGRES:
        insert_sql += " RETURNING id"
    with connect_recommendation_db() as db:
        cursor = db.execute(
            insert_sql,
            (
                session_id,
                payload.get("request_id"),
                place_id,
                feedback_type,
                payload.get("note"),
                now_iso(),
            ),
        )
        inserted_id = cursor.fetchone()["id"] if USE_POSTGRES else cursor.lastrowid
    signals = build_session_preference_signals(session_id)
    return {"ok": True, "id": inserted_id, "signals": signals}


def _safe_json_loads(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except Exception:
        return fallback


def _category_from_saved_row(row: sqlite3.Row) -> str:
    payload = _safe_json_loads(row["place_json"], {})
    return str(payload.get("algorithm_category") or payload.get("category") or row["category"] or "").strip()


def build_session_preference_signals(session_id: str | None) -> dict[str, Any]:
    session_id = str(session_id or "").strip()
    base = {
        "status": "cold_start",
        "weight_adjustments": {},
        "category_boosts": {},
        "category_penalties": {},
        "place_boosts": {},
        "place_penalties": {},
        "indoor_bias": 0.0,
        "outdoor_penalty": 0.0,
        "feedback_count": 0,
        "saved_count": 0,
    }
    if not session_id:
        return base

    init_recommendation_db()
    with connect_recommendation_db() as db:
        db.row_factory = sqlite3.Row
        feedback_rows = db.execute(
            """
            SELECT place_id, feedback_type
            FROM recommendation_feedback
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT 160
            """,
            (session_id,),
        ).fetchall()
        saved_rows = db.execute(
            """
            SELECT place_id, category, place_json
            FROM saved_places
            WHERE session_id = ?
            ORDER BY updated_at DESC
            LIMIT 80
            """,
            (session_id,),
        ).fetchall()

    if not feedback_rows and not saved_rows:
        return base

    weights: dict[str, float] = {}
    category_boosts: dict[str, float] = {}
    category_penalties: dict[str, float] = {}
    place_boosts: dict[str, float] = {}
    place_penalties: dict[str, float] = {}
    indoor_bias = 0.0
    outdoor_penalty = 0.0

    for row in saved_rows:
        place_id = str(row["place_id"])
        category = _category_from_saved_row(row)
        place_boosts[place_id] = place_boosts.get(place_id, 0.0) + 0.08
        if category:
            category_boosts[category] = category_boosts.get(category, 0.0) + 0.06

    for row in feedback_rows:
        place_id = str(row["place_id"])
        feedback_type = str(row["feedback_type"])
        for factor, delta in FEEDBACK_WEIGHT_RULES.get(feedback_type, {}).items():
            weights[factor] = weights.get(factor, 1.0) + delta
        if feedback_type == "good_fit":
            place_boosts[place_id] = place_boosts.get(place_id, 0.0) + 0.1
        elif feedback_type == "not_my_vibe":
            place_penalties[place_id] = place_penalties.get(place_id, 0.0) + 0.22
        elif feedback_type == "too_far":
            place_penalties[place_id] = place_penalties.get(place_id, 0.0) + 0.12
        elif feedback_type == "prefer_indoor":
            indoor_bias += 0.12
            outdoor_penalty += 0.12

    signals = {
        **base,
        "status": "learned",
        "weight_adjustments": {key: round(min(value, 1.9), 4) for key, value in weights.items()},
        "category_boosts": {key: round(min(value, 0.28), 4) for key, value in category_boosts.items()},
        "category_penalties": {key: round(min(value, 0.28), 4) for key, value in category_penalties.items()},
        "place_boosts": {key: round(min(value, 0.3), 4) for key, value in place_boosts.items()},
        "place_penalties": {key: round(min(value, 0.42), 4) for key, value in place_penalties.items()},
        "indoor_bias": round(min(indoor_bias, 0.4), 4),
        "outdoor_penalty": round(min(outdoor_penalty, 0.4), 4),
        "feedback_count": len(feedback_rows),
        "saved_count": len(saved_rows),
    }
    with connect_recommendation_db() as db:
        db.execute(
            """
            INSERT INTO user_preference_signals (session_id, signals_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                signals_json = excluded.signals_json,
                updated_at = excluded.updated_at
            """,
            (session_id, json.dumps(signals, ensure_ascii=False), now_iso()),
        )
    return signals


def criteria_location(criteria: dict[str, Any]) -> dict[str, Any]:
    lat = to_float(criteria.get("lat"))
    lon = to_float(criteria.get("lon") if criteria.get("lon") is not None else criteria.get("lng"))
    if lat is not None and lon is not None:
        return {
            "lat": lat,
            "lon": lon,
            "district": criteria.get("district"),
            "label": criteria.get("locationLabel") or "目前定位",
            "source": criteria.get("locationSource") or "browser",
        }
    location_key = str(criteria.get("location") or "taipei_main")
    return LOCATION_HINTS.get(location_key, LOCATION_HINTS["taipei_main"])


def recommendation_context(criteria: dict[str, Any]) -> dict[str, Any]:
    location = criteria_location(criteria)
    return weather_aqi_client.context(location["lat"], location["lon"])


def rain_probability_from_context(context: dict[str, Any]) -> float:
    value = context.get("weather", {}).get("rain_probability")
    return float(value) if value is not None else 0.25


def aqi_from_context(context: dict[str, Any]) -> float:
    value = context.get("air_quality", {}).get("aqi")
    return float(value) if value is not None else 65.0


def budget_for_algorithm(value: object) -> str:
    budget = str(value or "medium")
    if budget == "low":
        return "low"
    if budget == "high":
        return "high"
    return "medium"


def user_context_from_criteria(criteria: dict[str, Any], context: dict[str, Any]):
    mood_key = str(criteria.get("mood") or "relaxing_walk")
    algorithm_mood = FRONTEND_MOOD_TO_ALGORITHM.get(mood_key, "relax")
    travel_limit = max(10.0, float(criteria.get("distance") or 30))
    rain_prob = rain_probability_from_context(context)
    aqi_value = aqi_from_context(context)
    ignored_factors = set(criteria.get("ignoredFactors") or [])
    if str(criteria.get("budget") or "medium") == "flexible":
        ignored_factors.add("budget")

    weather_preference = str(criteria.get("weatherPreference") or "any")
    if mood_key == "rainy_backup":
        weather_preference = "indoor"
    outdoor_comfort = str(context.get("outdoor_comfort") or "")
    severe_weather = (
        weather_preference == "avoid_rain"
        and (rain_prob >= 0.5 or outdoor_comfort in {"rain_risk", "poor_air_quality", "air_quality_watch"})
    )

    return recommendation_algorithm.UserContext(
        scenario=str(criteria.get("scenario") or mood_key),
        mood=algorithm_mood,
        preferred_time=max(8.0, travel_limit * 0.75),
        hard_max_time=travel_limit,
        rain_prob=rain_prob,
        aqi=aqi_value,
        budget=budget_for_algorithm(criteria.get("budget")),
        secondary_mood=None,
        ignored_factors=ignored_factors,
        indoor_only=weather_preference == "indoor",
        outdoor_preferred=weather_preference == "any",
        severe_weather=severe_weather,
        user_weight_adjustment=criteria.get("weightAdjustments") or {},
    )


def criteria_with_preference_signals(criteria: dict[str, Any], signals: dict[str, Any]) -> dict[str, Any]:
    adjusted = dict(criteria)
    learned_weights = signals.get("weight_adjustments") or {}
    explicit_weights = adjusted.get("weightAdjustments") or {}
    merged_weights = dict(learned_weights)
    merged_weights.update(explicit_weights)
    if merged_weights:
        adjusted["weightAdjustments"] = merged_weights
    adjusted["learnedPreferenceSignals"] = signals
    return adjusted


def apply_preference_signals_to_candidates(candidates: list[dict[str, Any]], signals: dict[str, Any]) -> list[dict[str, Any]]:
    if not candidates or signals.get("status") == "cold_start":
        return candidates

    category_boosts = signals.get("category_boosts") or {}
    category_penalties = signals.get("category_penalties") or {}
    place_boosts = signals.get("place_boosts") or {}
    place_penalties = signals.get("place_penalties") or {}
    indoor_bias = float(signals.get("indoor_bias") or 0)
    outdoor_penalty = float(signals.get("outdoor_penalty") or 0)

    for item in candidates:
        place = item["algorithm_place"]
        display = item["display"]
        category = place.category
        boost = float(place_boosts.get(place.id, 0)) + float(category_boosts.get(category, 0))
        penalty = float(place_penalties.get(place.id, 0)) + float(category_penalties.get(category, 0))
        environment_delta = 0.0
        if indoor_bias and place.indoor and not place.outdoor:
            environment_delta += indoor_bias * 0.32
        if outdoor_penalty and place.outdoor and not place.indoor:
            environment_delta -= outdoor_penalty * 0.46

        quality_delta = boost * 0.45 - penalty * 0.7 + environment_delta
        if quality_delta:
            place.quality = recommendation_algorithm.clamp(place.quality + quality_delta)
            place.mood_fit = {
                mood: recommendation_algorithm.clamp(value + quality_delta * 0.45)
                for mood, value in place.mood_fit.items()
            }
            display["preference_adjustment"] = {
                "quality_delta": round(quality_delta, 4),
                "category_boost": round(float(category_boosts.get(category, 0)), 4),
                "place_boost": round(float(place_boosts.get(place.id, 0)), 4),
                "place_penalty": round(float(place_penalties.get(place.id, 0)), 4),
                "indoor_bias": round(indoor_bias, 4),
            }

    return candidates


def primary_category(categories: list[str], text: str = "", name: str = "") -> str:
    name_blob = str(name or "").lower()
    venue_pattern = r"大巨蛋|兩廳院|國家戲劇院|國家音樂廳|劇院|劇場|音樂廳|演藝廳|表演廳|文化中心|體育館|體育場|小巨蛋|arena|stadium|theater|theatre|concert hall|performing arts"
    if re.search(r"河濱|水岸|碼頭|渡口|riverside|river|pier|wharf|dock|waterfront", name_blob):
        return "riverside"
    if re.search(r"公園|森林|花園|步道|親山|登山|山系|park|trail", name_blob):
        return "park"
    if re.search(r"商圈|夜市|市場|market", name_blob):
        return "market"
    if re.search(venue_pattern, name_blob):
        return "venue"
    if re.search(r"書店|bookstore", name_blob):
        return "bookstore"
    if re.search(r"博物館|紀念館|museum", name_blob):
        return "museum"
    if re.search(r"美術館|藝文|藝術|gallery|文創", name_blob):
        return "gallery"
    if re.search(r"餐廳|restaurant|food|餐飲", name_blob):
        return "restaurant"
    if re.search(r"咖啡|cafe", name_blob):
        return "cafe"

    category_blob = " ".join(categories or []).lower()
    if re.search(r"自然風景|河濱|riverside", category_blob):
        return "riverside"
    if re.search(r"商圈|市場|夜市|market", category_blob):
        return "market"

    blob = " ".join([*(categories or []), text]).lower()
    checks = [
        ("venue", venue_pattern),
        ("bookstore", r"書店|bookstore"),
        ("museum", r"博物館|紀念館|museum"),
        ("gallery", r"美術館|藝文|藝術|gallery|文創"),
        ("restaurant", r"餐廳|restaurant|food|餐飲"),
        ("cafe", r"咖啡|cafe"),
        ("riverside", r"河濱|水岸|碼頭|渡口|自行車道|riverside|river|pier|wharf|dock|waterfront"),
        ("park", r"公園|森林|花園|步道|親山|登山|山系|park|trail"),
        ("market", r"夜市|市場|market|商圈"),
        ("viewpoint", r"景觀|夜景|古蹟|景點|viewpoint|scenic|attraction|taipei_featured"),
    ]
    for category, pattern in checks:
        if re.search(pattern, blob):
            return category
    return "viewpoint"


def display_category(value: str) -> str:
    return CATEGORY_LABELS.get(value, value or "景點")


def place_price(category: str, categories: list[str]) -> str:
    blob = " ".join([category, *(categories or [])])
    if re.search(r"公園|河濱|古蹟|park|riverside|taipei_featured", blob):
        return "low"
    if re.search(r"餐廳|restaurant", blob):
        return "high"
    return "medium"


def display_budget_from_price(price: str) -> str:
    return price


def place_environment(category: str, categories: list[str], text: str = "") -> tuple[bool, bool]:
    blob = " ".join([category, *(categories or []), text]).lower()
    indoor_categories = {"museum", "gallery", "bookstore", "restaurant", "cafe", "venue"}
    outdoor_categories = {"park", "riverside", "viewpoint", "market"}
    strong_indoor_pattern = r"博物館|美術館|書店|餐廳|咖啡|咖啡館|文創|紀念館|展覽館|劇場|影城|會館|主題館|圖書館|商場|購物中心|旅館|飯店|寺|廟|宮|堂|museum|gallery|bookstore|restaurant|cafe|theater|mall|library"
    strong_outdoor_pattern = r"公園|森林|花園|河濱|水岸|碼頭|渡口|步道|親山|登山|山系|自行車道|廣場|露天|戶外|景觀|觀景|夜市|古蹟|park|riverside|river|pier|wharf|dock|waterfront|trail|outdoor"
    indoor = category in indoor_categories or bool(re.search(strong_indoor_pattern, blob))
    outdoor = category in outdoor_categories or bool(re.search(strong_outdoor_pattern, blob))
    if category in {"park", "riverside"}:
        return False, True
    if category == "viewpoint" and not indoor:
        return False, True
    if outdoor and not indoor:
        return False, True
    if not indoor and not outdoor:
        outdoor = True
    return indoor, outdoor


def mood_fit_for_place(category: str, place_text: str) -> dict[str, float]:
    fits = {}
    for mood in recommendation_algorithm.MOODS:
        if category in recommendation_algorithm.PREFERRED_CATEGORIES_BY_MOOD[mood]:
            score = 0.94
        elif category in recommendation_algorithm.SECONDARY_CATEGORIES_BY_MOOD[mood]:
            score = 0.76
        else:
            score = 0.56

        patterns = {
            "relax": r"公園|河濱|步道|花|山|湖|安靜|放鬆",
            "date": r"景觀|文創|餐廳|夜景|藝術|咖啡",
            "solo": r"博物館|書店|紀念館|美術館|寺|廟|安靜",
            "photo": r"景點|古蹟|藝術|景觀|街|山|夜景",
            "night": r"夜市|商圈|夜景|餐廳|市場",
        }
        if re.search(patterns[mood], place_text):
            score = min(1.0, score + 0.06)
        fits[mood] = recommendation_algorithm.clamp(score)
    return fits


def normalize_place_payload(raw: dict[str, Any], criteria: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    categories = [str(item) for item in raw.get("categories") or [] if item]
    text = " ".join([
        str(raw.get("name") or ""),
        str(raw.get("description") or ""),
        str(raw.get("district") or ""),
        " ".join(categories),
    ])
    category = primary_category(categories, text, raw.get("name") or "")
    quality = float(raw.get("quality_score") or raw.get("score") or 0.55)
    if quality > 1:
        quality /= 100
    distance_m = to_float(raw.get("distance_m"))
    origin = criteria_location(criteria)
    destination = {
        "lat": to_float(raw.get("lat")),
        "lon": to_float(raw.get("lon") if raw.get("lon") is not None else raw.get("lng")),
    }
    geocoded = None
    if destination["lat"] is None or destination["lon"] is None:
        geocode_query = " ".join(
            str(part)
            for part in [
                raw.get("name"),
                raw.get("address"),
                raw.get("district"),
                "臺北市",
            ]
            if part
        )
        try:
            geocoded = google_geocode(geocode_query)
        except Exception:
            geocoded = None
        if geocoded:
            destination = {"lat": geocoded["lat"], "lon": geocoded["lon"]}
            raw = {
                **raw,
                "lat": geocoded["lat"],
                "lon": geocoded["lon"],
                "address": raw.get("address") or geocoded.get("address"),
                "geocoded": True,
                "geocoded_place_id": geocoded.get("place_id"),
            }
    open_status = raw_open_status(raw)
    if open_status.get("google_lat") is not None and open_status.get("google_lon") is not None:
        destination = {"lat": open_status["google_lat"], "lon": open_status["google_lon"]}
        raw = {
            **raw,
            "lat": open_status["google_lat"],
            "lon": open_status["google_lon"],
        }
    commute = None
    if destination["lat"] is not None and destination["lon"] is not None:
        commute = compare_commute_options(origin, destination, modes=normalize_transport_modes(criteria.get("transportModes")))
    best_commute = commute["best"] if commute else None
    best_duration_seconds = (
        to_float(best_commute.get("duration_seconds"))
        if best_commute and best_commute.get("available") is not False
        else None
    )
    travel_time = (
        max(1, round(best_duration_seconds / 60))
        if best_duration_seconds is not None
        else max(999, round(float(criteria.get("distance") or 30) + 999))
        if best_commute and best_commute.get("available") is False
        else max(8, round(distance_m / 420)) if distance_m is not None else max(12, round(float(criteria.get("distance") or 30) * 0.8))
    )
    price = place_price(category, categories)
    indoor, outdoor = place_environment(category, categories, text)
    # Unknown opening hours should not be treated as closed by the ranking filter.
    open_now = open_status.get("open_now") is not False

    place = recommendation_algorithm.Place(
        id=str(raw.get("id") or raw.get("name")),
        category=category,
        indoor=indoor,
        outdoor=outdoor,
        travel_time=float(travel_time),
        price=price,
        open_now=open_now,
        reachable=destination["lat"] is not None and destination["lon"] is not None,
        data_valid=bool(raw.get("id") and raw.get("name")),
        is_event=False,
        event_active=True,
        quality=recommendation_algorithm.clamp(quality),
        mood_fit=mood_fit_for_place(category, text),
        weather_exposure=0.25 if indoor and not outdoor else 0.55 if indoor and outdoor else 0.9,
        aqi_exposure=0.35 if indoor and not outdoor else 0.65 if indoor and outdoor else 0.95,
    )
    display = {
        **raw,
        "id": place.id,
        "name": raw.get("name") or place.id,
        "category": display_category(category),
        "algorithm_category": category,
        "categories": categories,
        "address": raw.get("address") or f"{raw.get('district') or '臺北市'} / 臺北市",
        "lat": raw.get("lat"),
        "lng": raw.get("lon") if raw.get("lon") is not None else raw.get("lng"),
        "lon": raw.get("lon") if raw.get("lon") is not None else raw.get("lng"),
        "google_place_id": open_status.get("place_id"),
        "google_name": open_status.get("google_name"),
        "google_address": open_status.get("google_address"),
        "description": raw.get("description") or "資料來自台北景點搜尋平台，並由後端推薦引擎重新評分。",
        "matched_travel_time": travel_time,
        "travel_time_minutes": travel_time,
        "commute": best_commute,
        "commute_options": commute["options"] if commute else [],
        "budget": display_budget_from_price(price),
        "weather_status": "watch" if outdoor and rain_probability_from_context(context) >= 0.45 else "suitable" if indoor else "any",
        "weather_summary": context.get("weather", {}).get("summary") or "天氣資料已納入後端評分",
        "aqi_value": context.get("air_quality", {}).get("aqi") or "--",
        "aqi_status": context.get("air_quality", {}).get("status") or "unknown",
        "open_now": open_status.get("open_now"),
        "opening_status": open_status.get("status"),
        "opening_status_source": open_status.get("source"),
        "opening_status_detail": open_status.get("detail"),
        "route_hint": (
            "所選交通方式沒有有效路線；已排除作為主要推薦依據。"
            if best_commute and best_commute.get("available") is False
            else f"最快約 {best_commute['duration_text']}，建議方式：{best_commute['mode_label']}。"
            if best_commute
            else "已納入距離與即時情境評分；實際路線請用地圖確認。"
        ),
        "rating": raw.get("rating") or round((3.8 + place.quality * 1.1) * 10) / 10,
    }
    return {"algorithm_place": place, "display": display}


def collect_candidate_places(criteria: dict[str, Any], context: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    location = criteria_location(criteria)
    base_radius_m = max(1200, int(float(criteria.get("distance") or 30) * 90))
    radius_steps = []
    for radius in (base_radius_m, 2500, 5000, 10000):
        if radius not in radius_steps:
            radius_steps.append(radius)
    queries = MOOD_QUERIES.get(str(criteria.get("mood") or "relaxing_walk"), [""])
    collected: dict[str, dict[str, Any]] = {}

    for radius_m in radius_steps:
        for query in queries:
            for item in search_attraction_places(
                q=query,
                lat=location["lat"],
                lon=location["lon"],
                radius_m=radius_m,
                limit=max(18, limit * 5),
            ):
                collected.setdefault(str(item.get("id")), item)
        if len(collected) >= limit * 2:
            break

    for radius_m in radius_steps:
        if len(collected) >= limit * 2:
            break
        for item in search_attraction_places(
            lat=location["lat"],
            lon=location["lon"],
            radius_m=radius_m,
            limit=max(24, limit * 6),
        ):
            collected.setdefault(str(item.get("id")), item)

    if not collected:
        fallback_results = get_attraction_service().search(
            limit=max(50, limit * 12),
            include_missing_coordinates=True,
        )
        for item in serialize_search_results(fallback_results):
            collected.setdefault(str(item.get("id")), item)

    return [normalize_place_payload(item, criteria, context) for item in collected.values()]


def tdx_credentials_configured() -> bool:
    values = [bus_tdx.client_id, bus_tdx.client_secret, mrt_tdx.client_id, mrt_tdx.client_secret]
    return all(values) and not any(str(value).startswith("your_") for value in values)


def nearest_positioned_item(items: list[dict[str, Any]], lat: float | None, lon: float | None, serializer) -> dict[str, Any] | None:
    if lat is None or lon is None:
        return None
    nearest = None
    nearest_distance = None
    for item in items:
        summary = serializer(item)
        position = summary.get("position") or {}
        distance = haversine_m(lat, lon, position.get("lat"), position.get("lon"))
        if distance is None:
            continue
        if nearest_distance is None or distance < nearest_distance:
            nearest = summary
            nearest_distance = distance
    if nearest is None:
        return None
    nearest["distance_m"] = round(nearest_distance)
    return nearest


def serialize_mrt_station_with_position(station: dict[str, Any]) -> dict[str, Any]:
    summary = mrt_station_summary(station)
    position = station.get("StationPosition") or {}
    summary["position"] = {
        "lat": position.get("PositionLat"),
        "lon": position.get("PositionLon"),
    }
    return summary


def build_transport_context(results: list[dict[str, Any]], city: str | None = None) -> dict[str, Any]:
    status = {"tdx": "skipped", "bus": None, "mrt": None}
    if not tdx_credentials_configured():
        status["reason"] = "TDX credentials are not configured."
        return {"status": status, "by_place": {}}

    bus_stations = []
    mrt_stations = []
    selected_city = get_bus_city(city)
    try:
        bus_stations = get_bus_stations(selected_city)
        status["bus"] = "ok"
    except Exception as exc:
        status["bus"] = f"error: {exc}"
    try:
        mrt_stations = get_mrt_stations()
        status["mrt"] = "ok"
    except Exception as exc:
        status["mrt"] = f"error: {exc}"

    status["tdx"] = "ok" if status.get("bus") == "ok" or status.get("mrt") == "ok" else "error"
    by_place = {}
    for result in results:
        lat = to_float(result.get("lat"))
        lon = to_float(result.get("lon") if result.get("lon") is not None else result.get("lng"))
        by_place[result["id"]] = {
            "nearest_bus_station": nearest_positioned_item(bus_stations, lat, lon, bus_module.serialize_station) if bus_stations else None,
            "nearest_mrt_station": nearest_positioned_item(mrt_stations, lat, lon, serialize_mrt_station_with_position) if mrt_stations else None,
        }
    return {"status": status, "by_place": by_place}


def format_recommendation_result(
    recommendation,
    display_place: dict[str, Any],
    criteria: dict[str, Any],
    context: dict[str, Any],
    transport: dict[str, Any] | None = None,
) -> dict[str, Any]:
    score_percent = round(float(recommendation.score) * 100)
    uncertainty_percent = round(float(recommendation.uncertainty) * 100, 1)
    mood_label = MOOD_LABELS.get(str(criteria.get("mood")), "目前情境")
    reason = (
        f"{display_place['name']} 符合「{mood_label}」情境，預估約 "
        f"{display_place['matched_travel_time']} 分鐘可到；後端已納入天氣、AQI、預算、距離與資料品質評分。"
    )
    return {
        **display_place,
        "score": score_percent,
        "reason": reason,
        "algorithm_reason": recommendation.reason,
        "transport": transport,
        "algorithm": {
            "score": recommendation.score,
            "uncertainty": recommendation.uncertainty,
            "worst_score": recommendation.worst_score,
            "normal_score": recommendation.normal_score,
            "best_score": recommendation.best_score,
            "active_factors": recommendation.active_factors,
            "weights": recommendation.weights,
            "fallback": recommendation.fallback,
            "uncertainty_percent": uncertainty_percent,
        },
        "context": {
            "weather": context.get("weather", {}),
            "air_quality": context.get("air_quality", {}),
            "uv": context.get("uv", {}),
            "outdoor_comfort": context.get("outdoor_comfort"),
        },
    }


def build_recommendations(payload: dict[str, Any]) -> dict[str, Any]:
    criteria = payload.get("criteria") or payload
    if not isinstance(criteria, dict):
        raise ValueError("criteria must be an object")
    limit = max(1, min(int(payload.get("limit") or criteria.get("limit") or 5), 12))
    session_id = payload.get("session_id") or criteria.get("session_id")
    include_transport = bool(payload.get("include_transport", True))
    request_id = str(uuid.uuid4())
    preference_signals = build_session_preference_signals(session_id)
    criteria = criteria_with_preference_signals(criteria, preference_signals)
    validate_criteria_service_area(criteria)

    context = recommendation_context(criteria)
    user = user_context_from_criteria(criteria, context)
    candidates = apply_preference_signals_to_candidates(
        collect_candidate_places(criteria, context, limit),
        preference_signals,
    )
    algorithm_places = [item["algorithm_place"] for item in candidates]
    displays_by_id = {item["algorithm_place"].id: item["display"] for item in candidates}

    recommendations, filtered_reasons = recommendation_algorithm.recommend(algorithm_places, user, k=limit)
    preliminary = [
        format_recommendation_result(item, displays_by_id[item.place.id], criteria, context)
        for item in recommendations
    ]
    transport_context = build_transport_context(preliminary) if include_transport else {"status": {"tdx": "disabled"}, "by_place": {}}
    results = [
        {
            **result,
            "transport": transport_context.get("by_place", {}).get(result["id"]),
            "backup_options": build_nearby_backups(result, criteria, context),
        }
        for result in preliminary
    ]
    source_status = {
        "attractions": {
            "status": "ok",
            "cache": str(ATTRACTION_CACHE),
            "candidate_count": len(candidates),
        },
        "weather_aqi": context.get("source_status", {}),
        "transport": transport_context.get("status", {}),
        "algorithm": {
            "status": "ok",
            "module": str(PROJECT_ROOT / "algorithm.py"),
            "filtered_reasons": dict(filtered_reasons),
        },
        "preferences": preference_signals,
        "database": {
            "status": "ok",
            "backend": "postgresql" if USE_POSTGRES else "sqlite",
            "path": "" if USE_POSTGRES else str(RECOMMENDATION_DB),
        },
    }
    record_recommendation(request_id, session_id, criteria, context, source_status, results)
    return {
        "request_id": request_id,
        "session_id": session_id,
        "count": len(results),
        "criteria": criteria,
        "context": context,
        "source_status": source_status,
        "results": results,
    }


def mapbox_config():
    token = get_mapbox_token()
    if not token or token == DEFAULT_MAPBOX_TOKEN:
        return {"access_token": "", "configured": False}
    return {"access_token": token, "configured": True}


def places_build(with_optional: bool = False):
    def build():
        service = TaipeiAttractionSearchService(cache_path=ATTRACTION_CACHE)
        report = service.build(include_optional_nearby=with_optional)
        attraction_service_cache["service"] = service
        attraction_service_cache["loaded_at"] = now_iso()
        return {"final_count": report.final_count, "fetched_counts": report.fetched_counts, "errors": report.errors}

    return run_or_raise(build)


def get_bus_city(city: str | None = None) -> str:
    return (city or os.getenv("TDX_BUS_CITY") or bus_module.DEFAULT_CITY).strip() or bus_module.DEFAULT_CITY


def get_bus_stations(city: str) -> list:
    if city in bus_station_cache:
        return bus_station_cache[city]["items"]
    stations = ensure_list_response(bus_tdx.get_response(bus_module.get_station_url(city)), f"{city} bus station list")
    bus_station_cache[city] = {
        "items": sorted(stations, key=lambda item: item.get("StationID", "")),
        "fetched_at": datetime.now().isoformat(),
    }
    return bus_station_cache[city]["items"]


def find_bus_stations(query: str, city: str) -> list:
    normalized_query = normalize_search_text(query)
    stations = get_bus_stations(city)
    if not normalized_query:
        return stations[:MAX_STATION_RESULTS]

    matches = []
    for station in stations:
        summary = bus_module.serialize_station(station)
        haystack = normalize_search_text(
            " ".join([
                summary.get("id", ""),
                summary.get("uid", ""),
                summary.get("name_zh", ""),
                summary.get("name_en", ""),
                " ".join(summary.get("route_names", [])),
            ])
        )
        if normalized_query in haystack:
            matches.append(station)

    return sorted(
        matches,
        key=lambda item: (
            normalize_search_text(bus_module.get_name_zh(item.get("StationName", ""))) != normalized_query,
            item.get("StationID", ""),
        ),
    )[:MAX_STATION_RESULTS]


def bus_station_option(station: dict) -> dict:
    summary = bus_module.serialize_station(station)
    return {
        "uid": summary["uid"],
        "id": summary["id"],
        "name_zh": summary["name_zh"],
        "name_en": summary["name_en"],
        "address": summary["address"],
        "position": summary["position"],
        "route_names": summary["route_names"],
        "stop_count": summary["stop_count"],
        "route_count": summary["route_count"],
    }


def get_bus_station_by_id(station_id: str, city: str) -> dict | None:
    for station in get_bus_stations(city):
        if station.get("StationID") == station_id or station.get("StationUID") == station_id:
            return station
    return None


def get_bus_stop_summaries_for_station(station: dict, city: str) -> list:
    summary = bus_module.serialize_station(station)
    if summary["stops"]:
        return summary["stops"]
    station_id = station.get("StationID", "")
    if not station_id:
        return []
    stops = ensure_list_response(
        bus_tdx.get_response(bus_module.get_stop_url(city, station_id=station_id)),
        f"{city} bus stops for station {station_id}",
    )
    return [bus_module.serialize_stop(stop) for stop in stops]


def get_bus_station_detail(station_id: str, city: str) -> dict:
    station = get_bus_station_by_id(station_id, city)
    if station is None:
        raise RuntimeError(f"Cannot find bus station {station_id} in {city}")
    summary = bus_module.serialize_station(station)
    summary["stops"] = get_bus_stop_summaries_for_station(station, city)
    summary["stop_count"] = len(summary["stops"])
    return summary


def get_bus_arrivals(stop_uid: str, city: str, route_name: str = "") -> dict:
    arrivals = ensure_list_response(
        bus_tdx.get_response(bus_module.get_eta_url(city, stop_uid=stop_uid, route_name=route_name or None)),
        f"{city} bus arrivals for stop {stop_uid}",
    )
    arrivals = sorted(arrivals, key=bus_module.sort_arrival_item)
    serialized = [bus_module.serialize_arrival(item) for item in arrivals]
    normal_count = sum(1 for item in arrivals if bus_module.parse_int(item.get("StopStatus")) == 0)
    arriving_count = sum(
        1
        for item in arrivals
        if bus_module.parse_int(item.get("StopStatus")) == 0
        and bus_module.parse_int(item.get("EstimateTime"), 999999) <= 180
    )
    return {
        "stop_uid": stop_uid,
        "city": city,
        "route_name": route_name,
        "update_time": serialized[0]["update_time"] if serialized else "",
        "counts": {
            "total": len(serialized),
            "normal": normal_count,
            "arriving": arriving_count,
            "service_issue": len(serialized) - normal_count,
            "routes": len({item["route_name"] for item in serialized if item["route_name"]}),
        },
        "arrivals": serialized,
    }


def mrt_station_name_zh(station: dict) -> str:
    return mrt_module.get_station_name_zh(station.get("StationName", ""))


def mrt_station_name_en(station: dict) -> str:
    name = station.get("StationName", "")
    if isinstance(name, dict):
        return name.get("En", "")
    return ""


def get_mrt_line_id(value: object) -> str:
    if not value:
        return ""
    match = re.match(r"[A-Z]+", str(value))
    return match.group(0) if match else str(value)


def get_mrt_stations() -> list:
    if mrt_stations_cache["items"]:
        return mrt_stations_cache["items"]
    url = f"{mrt_module.BASE_URL}/Rail/Metro/Station/{mrt_module.OPERATOR}?$format=JSON"
    stations = ensure_list_response(mrt_tdx.get_response(url), "MRT station list")
    mrt_stations_cache["items"] = sorted(stations, key=lambda item: item.get("StationID", ""))
    mrt_stations_cache["fetched_at"] = datetime.now().isoformat()
    return mrt_stations_cache["items"]


def find_mrt_stations(query: str) -> list:
    normalized_query = normalize_search_text(query)
    stations = get_mrt_stations()
    if not normalized_query:
        return stations[:MAX_STATION_RESULTS]
    matches = []
    for station in stations:
        station_id = station.get("StationID", "")
        zh = mrt_station_name_zh(station)
        en = mrt_station_name_en(station)
        if normalized_query in normalize_search_text(f"{station_id} {zh} {en}"):
            matches.append(station)
    return sorted(
        matches,
        key=lambda item: (
            normalize_search_text(mrt_station_name_zh(item)) != normalized_query,
            item.get("StationID", ""),
        ),
    )[:MAX_STATION_RESULTS]


def mrt_station_summary(station: dict) -> dict:
    station_id = station.get("StationID", "")
    return {
        "id": station_id,
        "name_zh": mrt_station_name_zh(station),
        "name_en": mrt_station_name_en(station),
        "line_id": station.get("LineID") or station.get("LineNo") or get_mrt_line_id(station_id),
    }


def mrt_status_kind(item: dict) -> str:
    status_code = mrt_module.parse_int(item.get("ServiceStatus"))
    if status_code == 1:
        return "pending"
    if status_code == 2:
        return "skipping"
    if status_code in (3, 4):
        return "closed"
    if status_code != 0:
        return "muted"
    estimate_seconds = mrt_module.parse_int(item.get("EstimateTime"))
    if estimate_seconds <= 0:
        return "arriving"
    if estimate_seconds <= 180:
        return "approaching"
    return "normal"


def serialize_mrt_liveboard_item(item: dict) -> dict:
    service_status_code = mrt_module.parse_int(item.get("ServiceStatus"))
    estimate_seconds = None
    if service_status_code == 0 and item.get("EstimateTime") not in (None, ""):
        estimate_seconds = mrt_module.parse_int(item.get("EstimateTime"))
    return {
        "line_id": item.get("LineID") or item.get("LineNO") or "",
        "line_name": mrt_module.get_name_zh(item.get("LineName", "")),
        "station_id": item.get("StationID", ""),
        "station": mrt_module.get_station_name_zh(item.get("StationName", "")),
        "station_en": item.get("StationName", {}).get("En", "") if isinstance(item.get("StationName"), dict) else "",
        "trip_head_sign": item.get("TripHeadSign", ""),
        "destination_id": item.get("DestinationStationID") or item.get("DestinationStaionID") or "",
        "destination": mrt_module.get_name_zh(item.get("DestinationStationName", "")),
        "destination_en": item.get("DestinationStationName", {}).get("En", "") if isinstance(item.get("DestinationStationName"), dict) else "",
        "estimate_seconds": estimate_seconds,
        "estimate_label": mrt_module.format_estimate_time(item),
        "service_status_code": service_status_code,
        "service_status": mrt_module.get_service_status(item),
        "status": mrt_module.get_mrt_status(item),
        "status_kind": mrt_status_kind(item),
        "update_time": item.get("UpdateTime") or item.get("SrcUpdateTime") or "",
    }


def mrt_direction_key(item: dict) -> str:
    return item.get("DestinationStationID") or item.get("DestinationStaionID") or item.get("TripHeadSign") or "unknown"


def mrt_direction_label(item: dict) -> str:
    trip_head_sign = item.get("TripHeadSign", "")
    destination = mrt_module.get_name_zh(item.get("DestinationStationName", ""))
    if trip_head_sign:
        return trip_head_sign
    if destination:
        return f"往{destination}"
    return "未知方向"


def sort_mrt_liveboard_item(item: dict):
    service_status_code = mrt_module.parse_int(item.get("ServiceStatus"))
    estimate_seconds = mrt_module.parse_int(item.get("EstimateTime"), 999999)
    return (
        item.get("LineID") or item.get("LineNO") or "",
        mrt_direction_key(item),
        service_status_code != 0,
        estimate_seconds,
        mrt_module.get_name_zh(item.get("DestinationStationName", "")),
    )


def build_mrt_direction_groups(liveboard_items: list) -> list:
    groups = []
    by_key: dict[str, dict] = {}
    for item in liveboard_items:
        key = mrt_direction_key(item)
        if key not in by_key:
            by_key[key] = {
                "key": key,
                "line_id": item.get("LineID") or item.get("LineNO") or "",
                "line_name": mrt_module.get_name_zh(item.get("LineName", "")),
                "label": mrt_direction_label(item),
                "destination_id": item.get("DestinationStationID") or item.get("DestinationStaionID") or "",
                "destination": mrt_module.get_name_zh(item.get("DestinationStationName", "")),
                "destination_en": item.get("DestinationStationName", {}).get("En", "") if isinstance(item.get("DestinationStationName"), dict) else "",
                "items": [],
            }
            groups.append(by_key[key])
        by_key[key]["items"].append(serialize_mrt_liveboard_item(item))
    return groups


def get_mrt_liveboard(station_id: str) -> dict:
    liveboard_items = ensure_list_response(
        mrt_tdx.get_response(mrt_module.get_liveboard_url(station_id.strip())),
        f"MRT liveboard for station {station_id}",
    )
    liveboard_items = sorted(liveboard_items, key=sort_mrt_liveboard_item)
    liveboard = [serialize_mrt_liveboard_item(item) for item in liveboard_items]
    direction_groups = build_mrt_direction_groups(liveboard_items)
    if liveboard_items:
        station = {
            "StationID": liveboard_items[0].get("StationID", station_id),
            "StationName": liveboard_items[0].get("StationName", station_id),
        }
    else:
        station = next((item for item in get_mrt_stations() if item.get("StationID") == station_id), None)

    normal_count = sum(1 for item in liveboard_items if mrt_module.parse_int(item.get("ServiceStatus")) == 0)
    arriving_count = sum(
        1
        for item in liveboard_items
        if mrt_module.parse_int(item.get("ServiceStatus")) == 0
        and mrt_module.parse_int(item.get("EstimateTime"), 999999) <= 180
    )
    return {
        "station": mrt_station_summary(station) if station else {"id": station_id, "name_zh": station_id, "name_en": ""},
        "update_time": liveboard_items[0].get("UpdateTime") or liveboard_items[0].get("SrcUpdateTime") if liveboard_items else "",
        "counts": {
            "total": len(liveboard),
            "normal": normal_count,
            "arriving": arriving_count,
            "service_issue": len(liveboard) - normal_count,
            "destinations": len({mrt_direction_key(item) for item in liveboard_items}),
            "directions": len(direction_groups),
        },
        "liveboard": liveboard,
        "direction_groups": direction_groups,
    }


admin_service = AdminService(
    get_attraction_service=get_attraction_service,
    rain_probability_from_context=rain_probability_from_context,
    aqi_from_context=aqi_from_context,
)


def register_api_routers() -> None:
    deps = SimpleNamespace(
        admin_delete_user=admin_service.delete_user,
        admin_feedback=admin_service.feedback,
        admin_overview=admin_service.overview,
        admin_places_summary=admin_service.places_summary,
        admin_recommendations=admin_service.recommendations,
        admin_summary=admin_service.summary,
        admin_users=admin_service.users,
        auth_config=auth_config,
        build_place_detail=build_place_detail,
        build_recommendations=build_recommendations,
        bus_station_option=bus_station_option,
        compare_commute_options=compare_commute_options,
        cwa_module=cwa_module,
        delete_user_account=delete_user_account,
        detail_criteria_from_query=detail_criteria_from_query,
        fetch_recommendation_record=fetch_recommendation_record,
        find_bus_stations=find_bus_stations,
        find_mrt_stations=find_mrt_stations,
        get_attraction_service=get_attraction_service,
        get_bus_arrivals=get_bus_arrivals,
        get_bus_city=get_bus_city,
        get_bus_station_detail=get_bus_station_detail,
        get_mrt_liveboard=get_mrt_liveboard,
        list_saved_places=list_saved_places,
        login_google_user=login_google_user,
        login_platform_user=login_platform_user,
        logout_auth_session=logout_auth_session,
        mapbox_config=mapbox_config,
        moenv_module=moenv_module,
        mrt_station_summary=mrt_station_summary,
        normalize_transport_modes=normalize_transport_modes,
        places_build=places_build,
        record_feedback=record_feedback,
        register_platform_user=register_platform_user,
        remove_saved_place=remove_saved_place,
        require_admin=require_admin,
        require_current_user=require_current_user,
        run_or_raise=run_or_raise,
        sample_locations=SAMPLE_LOCATIONS,
        search_attraction_places=search_attraction_places,
        to_float=to_float,
        update_saved_place_note=update_saved_place_note,
        update_user_preferences=update_user_preferences,
        update_user_profile=update_user_profile,
        upsert_saved_place=upsert_saved_place,
        weather_aqi_client=weather_aqi_client,
    )
    for router_factory in (
        routes_router.create_router,
        auth_router.create_router,
        admin_router.create_router,
        weather_router.create_router,
        places_router.create_router,
        recommendations_router.create_router,
        transport_router.create_router,
    ):
        app.include_router(router_factory(deps))


register_api_routers()
