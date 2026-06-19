"""Recommendation, detail formatting, saved-place, and feedback services."""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from typing import Any, Callable

from fastapi import HTTPException

from .config import (
    ATTRACTION_CACHE,
    CATEGORY_LABELS,
    FEEDBACK_WEIGHT_RULES,
    FRONTEND_MOOD_TO_ALGORITHM,
    LOCATION_HINTS,
    MOOD_LABELS,
    MOOD_QUERIES,
    PROJECT_ROOT,
)
from .database import RECOMMENDATION_DB, USE_POSTGRES, connect_recommendation_db, init_recommendation_db
from .places import PlacesService
from .routing import compare_commute_options, google_geocode, normalize_transport_modes, raw_open_status
from .service_area import validate_criteria_service_area
from .utils import haversine_m, now_iso, to_float


def safe_json_loads(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except Exception:
        return fallback


class RecommendationService:
    def __init__(
        self,
        algorithm,
        weather_aqi_client,
        places: PlacesService,
        build_transport_context: Callable[[list[dict[str, Any]], str | None], dict[str, Any]],
    ):
        self.algorithm = algorithm
        self.weather_aqi_client = weather_aqi_client
        self.places = places
        self.build_transport_context = build_transport_context

    def detail_criteria_from_query(
        self,
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
        self,
        display_place: dict[str, Any],
        criteria: dict[str, Any],
        context: dict[str, Any],
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        lat = to_float(display_place.get("lat"))
        lon = to_float(display_place.get("lon") if display_place.get("lon") is not None else display_place.get("lng"))
        if lat is None or lon is None:
            return []

        indoor_only = bool(self.user_context_from_criteria(criteria, context).indoor_only)
        results: list[dict[str, Any]] = []
        seen = {str(display_place.get("id"))}
        for raw in self.places.search_attraction_places(lat=lat, lon=lon, radius_m=1400, limit=max(18, limit * 7)):
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
            category = self.primary_category(categories, text)
            indoor, _outdoor = self.place_environment(category, categories, text)
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
                "category": self.display_category(category),
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
        self,
        place_id: str,
        criteria: dict[str, Any],
        session_id: str | None = None,
    ) -> dict[str, Any]:
        raw = self.places.get_attraction_place_by_id(place_id)
        if raw is None:
            raise HTTPException(status_code=404, detail="Place not found")
        signals = self.build_session_preference_signals(session_id)
        criteria = self.criteria_with_preference_signals(criteria, signals)
        context = self.recommendation_context(criteria)
        normalized = self.normalize_place_payload(raw, criteria, context)
        self.apply_preference_signals_to_candidates([normalized], signals)
        user = self.user_context_from_criteria(criteria, context)
        recommendations, _filtered_reasons = self.algorithm.recommend(
            [normalized["algorithm_place"]],
            user,
            k=1,
        )
        if recommendations:
            display = self.format_recommendation_result(recommendations[0], normalized["display"], criteria, context)
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
        display["backup_options"] = self.build_nearby_backups(display, criteria, context)
        display["preference_signals"] = signals
        return display

    def record_recommendation(
        self,
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

    def fetch_recommendation_record(self, request_id: str) -> dict[str, Any] | None:
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

    @staticmethod
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

    def list_saved_places(self, session_id: str) -> list[dict[str, Any]]:
        init_recommendation_db()
        with connect_recommendation_db() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                "SELECT * FROM saved_places WHERE session_id = ? ORDER BY updated_at DESC",
                (session_id,),
            ).fetchall()
        return [self.saved_place_from_row(row) for row in rows]

    def upsert_saved_place(self, payload: dict[str, Any]) -> dict[str, Any]:
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
        self.build_session_preference_signals(session_id)
        return self.saved_place_from_row(row)

    def update_saved_place_note(self, session_id: str, place_id: str, note: str) -> dict[str, Any] | None:
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
        return self.saved_place_from_row(row) if row else None

    def remove_saved_place(self, session_id: str, place_id: str) -> dict[str, Any]:
        init_recommendation_db()
        with connect_recommendation_db() as db:
            cursor = db.execute(
                "DELETE FROM saved_places WHERE session_id = ? AND place_id = ?",
                (session_id, place_id),
            )
        self.build_session_preference_signals(session_id)
        return {"ok": True, "deleted": cursor.rowcount}

    def record_feedback(self, payload: dict[str, Any]) -> dict[str, Any]:
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
        signals = self.build_session_preference_signals(session_id)
        return {"ok": True, "id": inserted_id, "signals": signals}

    @staticmethod
    def category_from_saved_row(row: sqlite3.Row) -> str:
        payload = safe_json_loads(row["place_json"], {})
        return str(payload.get("algorithm_category") or payload.get("category") or row["category"] or "").strip()

    def build_session_preference_signals(self, session_id: str | None) -> dict[str, Any]:
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
            category = self.category_from_saved_row(row)
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

    def criteria_location(self, criteria: dict[str, Any]) -> dict[str, Any]:
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

    def recommendation_context(self, criteria: dict[str, Any]) -> dict[str, Any]:
        location = self.criteria_location(criteria)
        return self.weather_aqi_client.context(location["lat"], location["lon"])

    @staticmethod
    def rain_probability_from_context(context: dict[str, Any]) -> float:
        value = context.get("weather", {}).get("rain_probability")
        return float(value) if value is not None else 0.25

    @staticmethod
    def aqi_from_context(context: dict[str, Any]) -> float:
        value = context.get("air_quality", {}).get("aqi")
        return float(value) if value is not None else 65.0

    @staticmethod
    def budget_for_algorithm(value: object) -> str:
        budget = str(value or "medium")
        if budget == "low":
            return "low"
        if budget == "high":
            return "high"
        return "medium"

    def user_context_from_criteria(self, criteria: dict[str, Any], context: dict[str, Any]):
        mood_key = str(criteria.get("mood") or "relaxing_walk")
        algorithm_mood = FRONTEND_MOOD_TO_ALGORITHM.get(mood_key, "relax")
        travel_limit = max(10.0, float(criteria.get("distance") or 30))
        rain_prob = self.rain_probability_from_context(context)
        aqi_value = self.aqi_from_context(context)
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

        return self.algorithm.UserContext(
            scenario=str(criteria.get("scenario") or mood_key),
            mood=algorithm_mood,
            preferred_time=max(8.0, travel_limit * 0.75),
            hard_max_time=travel_limit,
            rain_prob=rain_prob,
            aqi=aqi_value,
            budget=self.budget_for_algorithm(criteria.get("budget")),
            secondary_mood=None,
            ignored_factors=ignored_factors,
            indoor_only=weather_preference == "indoor",
            outdoor_preferred=weather_preference == "any",
            severe_weather=severe_weather,
            user_weight_adjustment=criteria.get("weightAdjustments") or {},
        )

    @staticmethod
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

    def apply_preference_signals_to_candidates(self, candidates: list[dict[str, Any]], signals: dict[str, Any]) -> list[dict[str, Any]]:
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
                place.quality = self.algorithm.clamp(place.quality + quality_delta)
                place.mood_fit = {
                    mood: self.algorithm.clamp(value + quality_delta * 0.45)
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

    @staticmethod
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

    @staticmethod
    def display_category(value: str) -> str:
        return CATEGORY_LABELS.get(value, value or "景點")

    @staticmethod
    def place_price(category: str, categories: list[str]) -> str:
        blob = " ".join([category, *(categories or [])])
        if re.search(r"公園|河濱|古蹟|park|riverside|taipei_featured", blob):
            return "low"
        if re.search(r"餐廳|restaurant", blob):
            return "high"
        return "medium"

    @staticmethod
    def display_budget_from_price(price: str) -> str:
        return price

    @staticmethod
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

    def mood_fit_for_place(self, category: str, place_text: str) -> dict[str, float]:
        fits = {}
        for mood in self.algorithm.MOODS:
            if category in self.algorithm.PREFERRED_CATEGORIES_BY_MOOD[mood]:
                score = 0.94
            elif category in self.algorithm.SECONDARY_CATEGORIES_BY_MOOD[mood]:
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
            fits[mood] = self.algorithm.clamp(score)
        return fits

    def normalize_place_payload(self, raw: dict[str, Any], criteria: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        categories = [str(item) for item in raw.get("categories") or [] if item]
        text = " ".join([
            str(raw.get("name") or ""),
            str(raw.get("description") or ""),
            str(raw.get("district") or ""),
            " ".join(categories),
        ])
        category = self.primary_category(categories, text, raw.get("name") or "")
        quality = float(raw.get("quality_score") or raw.get("score") or 0.55)
        if quality > 1:
            quality /= 100
        distance_m = to_float(raw.get("distance_m"))
        origin = self.criteria_location(criteria)
        destination = {
            "lat": to_float(raw.get("lat")),
            "lon": to_float(raw.get("lon") if raw.get("lon") is not None else raw.get("lng")),
        }
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
        price = self.place_price(category, categories)
        indoor, outdoor = self.place_environment(category, categories, text)
        open_now = open_status.get("open_now") is not False

        place = self.algorithm.Place(
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
            quality=self.algorithm.clamp(quality),
            mood_fit=self.mood_fit_for_place(category, text),
            weather_exposure=0.25 if indoor and not outdoor else 0.55 if indoor and outdoor else 0.9,
            aqi_exposure=0.35 if indoor and not outdoor else 0.65 if indoor and outdoor else 0.95,
        )
        display = {
            **raw,
            "id": place.id,
            "name": raw.get("name") or place.id,
            "category": self.display_category(category),
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
            "budget": self.display_budget_from_price(price),
            "weather_status": "watch" if outdoor and self.rain_probability_from_context(context) >= 0.45 else "suitable" if indoor else "any",
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

    def collect_candidate_places(self, criteria: dict[str, Any], context: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        location = self.criteria_location(criteria)
        base_radius_m = max(1200, int(float(criteria.get("distance") or 30) * 90))
        radius_steps = []
        for radius in (base_radius_m, 2500, 5000, 10000):
            if radius not in radius_steps:
                radius_steps.append(radius)
        queries = MOOD_QUERIES.get(str(criteria.get("mood") or "relaxing_walk"), [""])
        collected: dict[str, dict[str, Any]] = {}

        for radius_m in radius_steps:
            for query in queries:
                for item in self.places.search_attraction_places(
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
            for item in self.places.search_attraction_places(
                lat=location["lat"],
                lon=location["lon"],
                radius_m=radius_m,
                limit=max(24, limit * 6),
            ):
                collected.setdefault(str(item.get("id")), item)

        if not collected:
            fallback_results = self.places.get_attraction_service().search(
                limit=max(50, limit * 12),
                include_missing_coordinates=True,
            )
            for item in self.places.serialize_search_results(fallback_results):
                collected.setdefault(str(item.get("id")), item)

        return [self.normalize_place_payload(item, criteria, context) for item in collected.values()]

    def format_recommendation_result(
        self,
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

    def build_recommendations(self, payload: dict[str, Any]) -> dict[str, Any]:
        criteria = payload.get("criteria") or payload
        if not isinstance(criteria, dict):
            raise ValueError("criteria must be an object")
        limit = max(1, min(int(payload.get("limit") or criteria.get("limit") or 5), 12))
        session_id = payload.get("session_id") or criteria.get("session_id")
        include_transport = bool(payload.get("include_transport", True))
        request_id = str(uuid.uuid4())
        preference_signals = self.build_session_preference_signals(session_id)
        criteria = self.criteria_with_preference_signals(criteria, preference_signals)
        validate_criteria_service_area(criteria)

        context = self.recommendation_context(criteria)
        user = self.user_context_from_criteria(criteria, context)
        candidates = self.apply_preference_signals_to_candidates(
            self.collect_candidate_places(criteria, context, limit),
            preference_signals,
        )
        algorithm_places = [item["algorithm_place"] for item in candidates]
        displays_by_id = {item["algorithm_place"].id: item["display"] for item in candidates}

        recommendations, filtered_reasons = self.algorithm.recommend(algorithm_places, user, k=limit)
        preliminary = [
            self.format_recommendation_result(item, displays_by_id[item.place.id], criteria, context)
            for item in recommendations
        ]
        transport_context = self.build_transport_context(preliminary, None) if include_transport else {"status": {"tdx": "disabled"}, "by_place": {}}
        results = [
            {
                **result,
                "transport": transport_context.get("by_place", {}).get(result["id"]),
                "backup_options": self.build_nearby_backups(result, criteria, context),
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
        self.record_recommendation(request_id, session_id, criteria, context, source_status, results)
        return {
            "request_id": request_id,
            "session_id": session_id,
            "count": len(results),
            "criteria": criteria,
            "context": context,
            "source_status": source_status,
            "results": results,
        }
