"""Admin dashboard services for NEXT STOPS."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
from typing import Any, Callable

from fastapi import Header, HTTPException

from .auth import delete_user_account, public_user
from .config import ATTRACTION_CACHE
from .database import RECOMMENDATION_DB, USE_POSTGRES, connect_recommendation_db, init_recommendation_db
from .security import security_config_summary
from .utils import now_iso


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    supplied = str(x_admin_token or "").strip()
    expected = os.getenv("ADMIN_TOKEN", "").strip()
    expected_sha256 = os.getenv("ADMIN_TOKEN_SHA256", "").strip().lower()
    if not expected and not expected_sha256:
        raise HTTPException(status_code=503, detail="ADMIN_TOKEN 或 ADMIN_TOKEN_SHA256 尚未設定")
    if not supplied:
        raise HTTPException(status_code=401, detail="Admin token 不正確")
    supplied_ok = bool(expected and hmac.compare_digest(supplied, expected))
    if expected_sha256:
        supplied_hash = hashlib.sha256(supplied.encode("utf-8")).hexdigest()
        supplied_ok = supplied_ok or hmac.compare_digest(supplied_hash, expected_sha256)
    if not supplied_ok:
        raise HTTPException(status_code=401, detail="Admin token 不正確")


def scalar_count(db, table: str) -> int:
    row = db.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    return int(row["count"] if isinstance(row, dict) else row["count"])


def db_scalar(db, sql: str, params: tuple = ()) -> int:
    row = db.execute(sql, params).fetchone()
    if row is None:
        return 0
    value = row[0] if not isinstance(row, dict) else next(iter(row.values()))
    return int(value or 0)


def db_single_value(db, sql: str, params: tuple = (), default: Any = None) -> Any:
    row = db.execute(sql, params).fetchone()
    if row is None:
        return default
    if isinstance(row, dict):
        return next(iter(row.values()))
    try:
        return row[0]
    except Exception:
        return default


def safe_json_loads(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except Exception:
        return fallback


def group_count(rows: list[sqlite3.Row], key: str) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row[key] or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return [
        {"label": label, "count": count}
        for label, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
    ]


def security_summary() -> dict[str, Any]:
    summary = security_config_summary()
    summary.update({
        "admin": {
            "token_mode": "sha256" if os.getenv("ADMIN_TOKEN_SHA256", "").strip() else ("plain" if os.getenv("ADMIN_TOKEN", "").strip() else "unset"),
            "query_token_allowed": False,
        },
    })
    return summary


class AdminService:
    def __init__(
        self,
        get_attraction_service: Callable[[], Any],
        rain_probability_from_context: Callable[[dict[str, Any]], float],
        aqi_from_context: Callable[[dict[str, Any]], float],
    ):
        self.get_attraction_service = get_attraction_service
        self.rain_probability_from_context = rain_probability_from_context
        self.aqi_from_context = aqi_from_context

    def summary(self) -> dict[str, Any]:
        init_recommendation_db()
        with connect_recommendation_db() as db:
            db.row_factory = sqlite3.Row
            counts = {
                "users": scalar_count(db, "users"),
                "auth_sessions": scalar_count(db, "auth_sessions"),
                "recommendation_requests": scalar_count(db, "recommendation_requests"),
                "saved_places": scalar_count(db, "saved_places"),
                "recommendation_feedback": scalar_count(db, "recommendation_feedback"),
            }
        places = self.get_attraction_service().index.places
        return {
            "database": {
                "backend": "postgresql" if USE_POSTGRES else "sqlite",
                "path": "" if USE_POSTGRES else str(RECOMMENDATION_DB),
            },
            "counts": counts,
            "places": {
                "cache": str(ATTRACTION_CACHE),
                "count": len(places),
                "cache_exists": ATTRACTION_CACHE.exists(),
            },
            "api": {"status": "ok", "time": now_iso()},
            "security": security_summary(),
        }

    def users(self, limit: int = 80) -> dict[str, Any]:
        init_recommendation_db()
        limit = max(1, min(int(limit or 80), 200))
        with connect_recommendation_db() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                """
                SELECT id, provider, account, email, display_name, avatar_url, preferences_json, created_at, updated_at
                FROM users
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        users = []
        for row in rows:
            preferences = safe_json_loads(row["preferences_json"], {})
            users.append({
                "id": row["id"],
                "provider": row["provider"],
                "account": row["account"],
                "email": row["email"],
                "name": row["display_name"],
                "avatar_url": row["avatar_url"],
                "favorite_starts_count": len(preferences.get("favoriteStarts") or []),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            })
        return {"users": users}

    def delete_user(self, user_id: str) -> dict[str, Any]:
        init_recommendation_db()
        with connect_recommendation_db() as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="User not found")
        return delete_user_account(public_user(row))

    def recommendations(self, limit: int = 80) -> dict[str, Any]:
        init_recommendation_db()
        limit = max(1, min(int(limit or 80), 200))
        with connect_recommendation_db() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                """
                SELECT id, created_at, session_id, criteria_json, source_status_json, result_count
                FROM recommendation_requests
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        requests = []
        for row in rows:
            criteria = safe_json_loads(row["criteria_json"], {})
            source_status = safe_json_loads(row["source_status_json"], {})
            requests.append({
                "id": row["id"],
                "created_at": row["created_at"],
                "session_id": row["session_id"],
                "mood": criteria.get("mood"),
                "location": criteria.get("locationLabel") or criteria.get("location"),
                "distance": criteria.get("distance"),
                "transport_modes": criteria.get("transportModes") or [],
                "result_count": row["result_count"],
                "database": source_status.get("database") or source_status.get("sqlite") or {},
            })
        return {"requests": requests}

    def feedback(self, limit: int = 120) -> dict[str, Any]:
        init_recommendation_db()
        limit = max(1, min(int(limit or 120), 300))
        with connect_recommendation_db() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                """
                SELECT session_id, request_id, place_id, feedback_type, note, created_at
                FROM recommendation_feedback
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return {
            "feedback": [
                {
                    "session_id": row["session_id"],
                    "request_id": row["request_id"],
                    "place_id": row["place_id"],
                    "feedback_type": row["feedback_type"],
                    "note": row["note"],
                    "created_at": row["created_at"],
                }
                for row in rows
            ]
        }

    def places_summary(self) -> dict[str, Any]:
        places = self.get_attraction_service().index.places
        categories: dict[str, int] = {}
        for place in places:
            payload = place.to_dict() if hasattr(place, "to_dict") else dict(place)
            category = str(payload.get("category") or payload.get("algorithm_category") or "unknown")
            categories[category] = categories.get(category, 0) + 1
        top_categories = [
            {"category": category, "count": count}
            for category, count in sorted(categories.items(), key=lambda item: item[1], reverse=True)[:12]
        ]
        return {
            "cache": str(ATTRACTION_CACHE),
            "cache_exists": ATTRACTION_CACHE.exists(),
            "count": len(places),
            "top_categories": top_categories,
        }

    def overview(self, limit: int = 80) -> dict[str, Any]:
        init_recommendation_db()
        limit = max(1, min(int(limit or 80), 200))
        with connect_recommendation_db() as db:
            db.row_factory = sqlite3.Row
            counts = {
                "users": scalar_count(db, "users"),
                "auth_sessions": scalar_count(db, "auth_sessions"),
                "recommendation_requests": scalar_count(db, "recommendation_requests"),
                "recommendation_results": scalar_count(db, "recommendation_results"),
                "saved_places": scalar_count(db, "saved_places"),
                "recommendation_feedback": scalar_count(db, "recommendation_feedback"),
                "user_preference_signals": scalar_count(db, "user_preference_signals"),
            }
            users_raw = db.execute(
                """
                SELECT id, provider, account, email, display_name, avatar_url, preferences_json, created_at, updated_at
                FROM users
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            requests_raw = db.execute(
                """
                SELECT id, created_at, session_id, criteria_json, context_json, source_status_json, result_count
                FROM recommendation_requests
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            feedback_raw = db.execute(
                """
                SELECT session_id, request_id, place_id, feedback_type, note, created_at
                FROM recommendation_feedback
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            saved_raw = db.execute(
                """
                SELECT session_id, place_id, name, category, address, note, created_at, updated_at
                FROM saved_places
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            top_place_rows = db.execute(
                """
                SELECT place_id, MAX(place_name) AS place_name, COUNT(*) AS recommended_count, AVG(score) AS avg_score
                FROM recommendation_results
                GROUP BY place_id
                ORDER BY recommended_count DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

            users = []
            user_by_session = {}
            for row in users_raw:
                session_id = f"user:{row['id']}"
                preferences = safe_json_loads(row["preferences_json"], {})
                user_by_session[session_id] = {
                    "id": row["id"],
                    "name": row["display_name"],
                    "provider": row["provider"],
                    "account": row["account"],
                    "email": row["email"],
                }
                users.append({
                    "id": row["id"],
                    "session_id": session_id,
                    "provider": row["provider"],
                    "account": row["account"],
                    "email": row["email"],
                    "name": row["display_name"],
                    "avatar_url": row["avatar_url"],
                    "favorite_starts_count": len(preferences.get("favoriteStarts") or []),
                    "weight_count": len((preferences.get("weightAdjustments") or {}).keys()),
                    "auth_sessions": db_scalar(db, "SELECT COUNT(*) FROM auth_sessions WHERE user_id = ?", (row["id"],)),
                    "saved_places": db_scalar(db, "SELECT COUNT(*) FROM saved_places WHERE session_id = ?", (session_id,)),
                    "recommendations": db_scalar(db, "SELECT COUNT(*) FROM recommendation_requests WHERE session_id = ?", (session_id,)),
                    "feedback": db_scalar(db, "SELECT COUNT(*) FROM recommendation_feedback WHERE session_id = ?", (session_id,)),
                    "last_recommendation_at": db_single_value(
                        db,
                        "SELECT MAX(created_at) FROM recommendation_requests WHERE session_id = ?",
                        (session_id,),
                        "",
                    ),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                })

            requests = []
            for row in requests_raw:
                criteria = safe_json_loads(row["criteria_json"], {})
                context = safe_json_loads(row["context_json"], {})
                source_status = safe_json_loads(row["source_status_json"], {})
                top_result = db.execute(
                    """
                    SELECT place_id, place_name, score
                    FROM recommendation_results
                    WHERE request_id = ?
                    ORDER BY rank ASC
                    LIMIT 1
                    """,
                    (row["id"],),
                ).fetchone()
                feedback_count = db_scalar(db, "SELECT COUNT(*) FROM recommendation_feedback WHERE request_id = ?", (row["id"],))
                requests.append({
                    "id": row["id"],
                    "created_at": row["created_at"],
                    "session_id": row["session_id"],
                    "user": user_by_session.get(row["session_id"]),
                    "mood": criteria.get("mood"),
                    "location": criteria.get("locationLabel") or criteria.get("location"),
                    "time": criteria.get("time"),
                    "distance": criteria.get("distance"),
                    "budget": criteria.get("budget"),
                    "weather_preference": criteria.get("weatherPreference"),
                    "transport_modes": criteria.get("transportModes") or [],
                    "rain_probability": self.rain_probability_from_context(context),
                    "aqi": self.aqi_from_context(context),
                    "result_count": row["result_count"],
                    "feedback_count": feedback_count,
                    "top_result": dict(top_result) if top_result else None,
                    "source_status": source_status,
                })

            feedback = []
            for row in feedback_raw:
                feedback.append({
                    "session_id": row["session_id"],
                    "user": user_by_session.get(row["session_id"]),
                    "request_id": row["request_id"],
                    "place_id": row["place_id"],
                    "feedback_type": row["feedback_type"],
                    "note": row["note"],
                    "created_at": row["created_at"],
                })

            saved = []
            for row in saved_raw:
                saved.append({
                    "session_id": row["session_id"],
                    "user": user_by_session.get(row["session_id"]),
                    "place_id": row["place_id"],
                    "name": row["name"],
                    "category": row["category"],
                    "address": row["address"],
                    "note": row["note"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                })

            saved_count_by_place = {
                row["place_id"]: row["count"]
                for row in db.execute(
                    "SELECT place_id, COUNT(*) AS count FROM saved_places GROUP BY place_id"
                ).fetchall()
            }
            feedback_count_by_place = {
                row["place_id"]: row["count"]
                for row in db.execute(
                    "SELECT place_id, COUNT(*) AS count FROM recommendation_feedback GROUP BY place_id"
                ).fetchall()
            }
            places = []
            for row in top_place_rows:
                places.append({
                    "place_id": row["place_id"],
                    "name": row["place_name"],
                    "recommended_count": int(row["recommended_count"] or 0),
                    "saved_count": int(saved_count_by_place.get(row["place_id"], 0)),
                    "feedback_count": int(feedback_count_by_place.get(row["place_id"], 0)),
                    "avg_score": round(float(row["avg_score"] or 0) * 100, 1),
                })

            all_request_rows = db.execute("SELECT id, session_id, created_at, criteria_json FROM recommendation_requests").fetchall()
            all_feedback_rows = db.execute("SELECT feedback_type, request_id, session_id, place_id, created_at FROM recommendation_feedback").fetchall()
            provider_rows = db.execute("SELECT provider FROM users").fetchall()
            session_ids = {row["session_id"] for row in all_request_rows if row["session_id"]}
            guest_sessions = [sid for sid in session_ids if not str(sid).startswith("user:")]
            linked_user_sessions = [sid for sid in session_ids if str(sid).startswith("user:") and sid in user_by_session]
            orphan_user_sessions = [
                sid for sid in session_ids
                if str(sid).startswith("user:") and sid not in user_by_session
            ]
            request_ids = {row["id"] for row in all_request_rows}
            orphan_feedback = [
                row for row in all_feedback_rows
                if row["request_id"] and row["request_id"] not in request_ids
            ]

        places_summary = self.places_summary()
        return {
            "database": {
                "backend": "postgresql" if USE_POSTGRES else "sqlite",
                "path": "" if USE_POSTGRES else str(RECOMMENDATION_DB),
            },
            "counts": counts,
            "health": {
                "guest_sessions": len(guest_sessions),
                "linked_user_sessions": len(linked_user_sessions),
                "orphan_user_sessions": len(orphan_user_sessions),
                "orphan_feedback": len(orphan_feedback),
                "place_cache_exists": places_summary.get("cache_exists"),
            },
            "breakdowns": {
                "providers": group_count(provider_rows, "provider"),
                "feedback_types": group_count(all_feedback_rows, "feedback_type"),
            },
            "users": users,
            "requests": requests,
            "feedback": feedback,
            "saved": saved,
            "places": places,
            "place_cache": places_summary,
            "api": {"status": "ok", "time": now_iso()},
            "security": security_summary(),
        }
