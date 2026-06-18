"""Unified FastAPI app for NEXT STOPS external-data clients.

Run from this directory:
  uvicorn api_app:app --reload --host 127.0.0.1 --port 8790
"""

from __future__ import annotations

import importlib.util
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import requests

try:
    from fastapi import FastAPI, Header, HTTPException
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("請先安裝 FastAPI dependencies：pip install -r requirements.txt") from exc

from next_stops_backend.routers import (
    admin as admin_router,
    auth as auth_router,
    places as places_router,
    recommendations as recommendations_router,
    routes as routes_router,
    transport as transport_router,
    weather as weather_router,
)
from next_stops_backend.database import (
    RECOMMENDATION_DB,
    USE_POSTGRES,
    connect_recommendation_db,
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
from next_stops_backend.service_area import (
    SERVICE_AREA_LABEL,
    find_service_area,
    is_within_service_area,
    validate_criteria_service_area,
)
from next_stops_backend.transport import CachedTDX
from next_stops_backend.utils import (
    haversine_m,
    now_iso,
    to_float,
)


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
ATTRACTION_PLATFORM_ROOT = ROOT / "taipei_attraction_search_platform"
ATTRACTION_CACHE = ATTRACTION_PLATFORM_ROOT / "data" / "taipei_places.json"
GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
DEFAULT_MAPBOX_TOKEN = "your_mapbox_access_token"
MAX_STATION_RESULTS = 300

SAMPLE_LOCATIONS = [
    {"name": "臺北車站", "lat": 25.0478, "lon": 121.5170},
    {"name": "信義區市府", "lat": 25.0375, "lon": 121.5637},
    {"name": "士林夜市", "lat": 25.0881, "lon": 121.5240},
    {"name": "北投溫泉", "lat": 25.1368, "lon": 121.5064},
    {"name": "南港展覽館", "lat": 25.0553, "lon": 121.6175},
]

LOCATION_HINTS = {
    "taipei_main": {"lat": 25.0478, "lon": 121.5170, "district": "中正區", "label": "台北車站"},
    "xinyi": {"lat": 25.0339, "lon": 121.5645, "district": "信義區", "label": "信義區"},
    "daan": {"lat": 25.0262, "lon": 121.5353, "district": "大安區", "label": "大安森林公園"},
    "songshan": {"lat": 25.0496, "lon": 121.5777, "district": "松山區", "label": "松山"},
}

FRONTEND_MOOD_TO_ALGORITHM = {
    "relaxing_walk": "relax",
    "date": "date",
    "solo_quiet": "solo",
    "photo": "photo",
    "rainy_backup": "solo",
    "night_out": "night",
}

MOOD_LABELS = {
    "relaxing_walk": "散步放鬆",
    "date": "約會",
    "solo_quiet": "一個人安靜",
    "photo": "拍照探索",
    "rainy_backup": "雨天備案",
    "night_out": "夜晚出門",
}

MOOD_QUERIES = {
    "relaxing_walk": ["公園", "步道", "河濱"],
    "date": ["景觀", "文創", "餐廳"],
    "solo_quiet": ["博物館", "書店", "紀念館"],
    "photo": ["景點", "古蹟", "藝術"],
    "rainy_backup": ["博物館", "美術館", "文創"],
    "night_out": ["夜市", "商圈", "景觀"],
}

CATEGORY_LABELS = {
    "cafe": "咖啡",
    "park": "公園",
    "museum": "博物館",
    "market": "市集",
    "bookstore": "書店",
    "riverside": "河濱",
    "gallery": "藝文",
    "venue": "場館",
    "restaurant": "餐飲",
    "viewpoint": "景觀",
    "scenic_spot": "景點",
    "attraction": "景點",
    "taipei_featured": "精選景點",
}

OPENING_UNKNOWN_ALLOWED_CATEGORIES = {"park", "riverside", "viewpoint"}


PASSWORD_PATTERN = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$_-])[A-Za-z\d@$_-]{8,16}$")


FEEDBACK_WEIGHT_RULES = {
    "too_far": {"distance": 0.16},
    "too_expensive": {"budget": 0.16},
    "prefer_indoor": {"weather": 0.14, "environment": 0.12},
    "prefer_quieter": {"mood": 0.08, "quality": 0.06},
    "prefer_scenic": {"mood": 0.08, "quality": 0.06},
    "good_fit": {"mood": 0.05, "quality": 0.05},
    "not_my_vibe": {"mood": 0.08},
}


def load_root_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def load_module(module_name: str, filename: str):
    module_path = ROOT / filename
    return load_module_from_path(module_name, module_path)


def load_module_from_path(module_name: str, module_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


load_root_env()

cwa_module = load_module("cwa_weather_api_clients", "CWA-Weather_API_clients.py")
moenv_module = load_module("moenv_aqi_api_clients", "MOENV-AQI_API_clients.py")
weather_aqi_module = load_module("weather_aqi_api_clients", "Weather-AQI_API_clients.py")
bus_module = load_module("tdx_bus_api_clients", "TDX-BUS_API_clients.py")
mrt_module = load_module("tdx_mrt_api_clients", "TDX-MRT_API_clients.py")
recommendation_algorithm = load_module_from_path("next_stops_recommendation_algorithm", PROJECT_ROOT / "algorithm.py")

if str(ATTRACTION_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(ATTRACTION_PLATFORM_ROOT))

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


def public_user(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    get_value = row.get if isinstance(row, dict) else row.__getitem__
    try:
        preferences = json.loads(get_value("preferences_json") or "{}")
    except Exception:
        preferences = {}
    return {
        "id": get_value("id"),
        "provider": get_value("provider"),
        "account": get_value("account"),
        "email": get_value("email"),
        "name": get_value("display_name") or get_value("account") or get_value("email"),
        "avatar_url": get_value("avatar_url"),
        "session_id": f"user:{get_value('id')}",
        "preferences": preferences,
    }


def clean_password(value: object) -> str:
    return str(value or "").rstrip()


def validate_password(account: str, password: str, confirm: str | None = None) -> None:
    if confirm is not None and password != clean_password(confirm):
        raise ValueError("兩次輸入的密碼不一致")
    if account and account == password:
        raise ValueError("帳號與密碼不可相同")
    if re.search(r"\s", password):
        raise ValueError("密碼開頭與中間不得包含空白字元")
    if not PASSWORD_PATTERN.match(password):
        raise ValueError("密碼需為 8-16 字元，包含大小寫英文字母、數字，且至少一個 @、$、_ 或 -")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 180000)
    return f"pbkdf2_sha256$180000${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    try:
        algorithm, iterations, salt_hex, digest_hex = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        expected = bytes.fromhex(digest_hex)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(digest, expected)
    except Exception:
        return False


def create_auth_session(user_id: str) -> str:
    init_recommendation_db()
    token = secrets.token_urlsafe(40)
    now = now_iso()
    with connect_recommendation_db() as db:
        db.execute(
            "INSERT INTO auth_sessions (token, user_id, created_at, last_seen) VALUES (?, ?, ?, ?)",
            (token, user_id, now, now),
        )
    return token


def auth_response(user_row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    user = public_user(user_row)
    return {"token": create_auth_session(user["id"]), "user": user}


def bearer_token(authorization: str | None) -> str:
    text = str(authorization or "").strip()
    return text[7:].strip() if text.lower().startswith("bearer ") else text


def current_user_from_token(token: str) -> dict[str, Any] | None:
    token = bearer_token(token)
    if not token:
        return None
    init_recommendation_db()
    with connect_recommendation_db() as db:
        db.row_factory = sqlite3.Row
        row = db.execute(
            """
            SELECT users.*
            FROM auth_sessions
            JOIN users ON users.id = auth_sessions.user_id
            WHERE auth_sessions.token = ?
            """,
            (token,),
        ).fetchone()
        if row:
            db.execute("UPDATE auth_sessions SET last_seen = ? WHERE token = ?", (now_iso(), token))
    return public_user(row) if row else None


def require_current_user(authorization: str | None) -> dict[str, Any]:
    user = current_user_from_token(authorization or "")
    if not user:
        raise HTTPException(status_code=401, detail="請先登入")
    return user


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


def verify_google_id_token(id_token: str) -> dict[str, Any]:
    client_id = os.getenv("GOOGLE_CLIENT_ID") or os.getenv("VITE_GOOGLE_CLIENT_ID")
    if not client_id:
        raise ValueError("GOOGLE_CLIENT_ID 尚未設定")
    response = requests.get(GOOGLE_TOKENINFO_URL, params={"id_token": id_token}, timeout=10)
    response.raise_for_status()
    info = response.json()
    if info.get("aud") != client_id:
        raise ValueError("Google token audience 不符合目前應用程式")
    if info.get("email_verified") not in {True, "true", "True", "1", 1}:
        raise ValueError("Google 帳戶尚未完成 email 驗證")
    return info


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


def init_recommendation_db() -> None:
    if not USE_POSTGRES:
        RECOMMENDATION_DB.parent.mkdir(parents=True, exist_ok=True)
    with connect_recommendation_db() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS recommendation_requests (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                session_id TEXT,
                criteria_json TEXT NOT NULL,
                context_json TEXT NOT NULL,
                source_status_json TEXT NOT NULL,
                result_count INTEGER NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS recommendation_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL,
                rank INTEGER NOT NULL,
                place_id TEXT NOT NULL,
                place_name TEXT NOT NULL,
                score REAL NOT NULL,
                uncertainty REAL NOT NULL,
                reason TEXT,
                result_json TEXT NOT NULL,
                FOREIGN KEY(request_id) REFERENCES recommendation_requests(id)
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_recommendation_results_request ON recommendation_results(request_id)")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_places (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                place_id TEXT NOT NULL,
                name TEXT NOT NULL,
                category TEXT,
                address TEXT,
                lat REAL,
                lng REAL,
                note TEXT,
                place_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(session_id, place_id)
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_saved_places_session ON saved_places(session_id)")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS recommendation_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                request_id TEXT,
                place_id TEXT NOT NULL,
                feedback_type TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_feedback_session ON recommendation_feedback(session_id)")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_preference_signals (
                session_id TEXT PRIMARY KEY,
                signals_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                account TEXT UNIQUE,
                email TEXT,
                display_name TEXT NOT NULL,
                avatar_url TEXT,
                password_hash TEXT,
                google_sub TEXT UNIQUE,
                preferences_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_account ON users(account) WHERE account IS NOT NULL")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_sub ON users(google_sub) WHERE google_sub IS NOT NULL")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id)")


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


def register_platform_user(payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    account = str(payload.get("account") or "").strip()
    password = clean_password(payload.get("password"))
    confirm = clean_password(payload.get("confirm_password"))
    if not name:
        raise ValueError("名稱為必填")
    if not account:
        raise ValueError("帳號為必填")
    validate_password(account, password, confirm)

    init_recommendation_db()
    user_id = uuid.uuid4().hex
    now = now_iso()
    try:
        with connect_recommendation_db() as db:
            db.row_factory = sqlite3.Row
            db.execute(
                """
                INSERT INTO users (
                    id, provider, account, email, display_name, avatar_url, password_hash, google_sub,
                    preferences_json, created_at, updated_at
                ) VALUES (?, 'platform', ?, NULL, ?, NULL, ?, NULL, '{}', ?, ?)
                """,
                (user_id, account, name, hash_password(password), now, now),
            )
            row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    except Exception as exc:
        if not isinstance(exc, sqlite3.IntegrityError) and exc.__class__.__name__ != "UniqueViolation":
            raise
        raise ValueError("這個帳號已經被使用") from exc
    return {"ok": True, "user": public_user(row)}


def login_platform_user(payload: dict[str, Any]) -> dict[str, Any]:
    account = str(payload.get("account") or "").strip()
    password = clean_password(payload.get("password"))
    if not account or not password:
        raise ValueError("帳號與密碼為必填")
    init_recommendation_db()
    with connect_recommendation_db() as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM users WHERE account = ? AND provider = 'platform'", (account,)).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        raise ValueError("帳號或密碼錯誤")
    return auth_response(row)


def login_google_user(payload: dict[str, Any]) -> dict[str, Any]:
    id_token = str(payload.get("id_token") or payload.get("credential") or "").strip()
    if not id_token:
        raise ValueError("Google ID token is required")
    info = verify_google_id_token(id_token)
    google_sub = str(info.get("sub") or "")
    email = str(info.get("email") or "")
    name = str(info.get("name") or email or "Google User")
    avatar_url = str(info.get("picture") or "")
    if not google_sub:
        raise ValueError("Google token 缺少 sub")

    init_recommendation_db()
    now = now_iso()
    with connect_recommendation_db() as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM users WHERE google_sub = ?", (google_sub,)).fetchone()
        if row is None:
            user_id = uuid.uuid4().hex
            db.execute(
                """
                INSERT INTO users (
                    id, provider, account, email, display_name, avatar_url, password_hash, google_sub,
                    preferences_json, created_at, updated_at
                ) VALUES (?, 'google', ?, ?, ?, ?, NULL, ?, '{}', ?, ?)
                """,
                (user_id, email or None, email or None, name, avatar_url or None, google_sub, now, now),
            )
            row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        else:
            db.execute(
                """
                UPDATE users SET email = ?, display_name = ?, avatar_url = ?, updated_at = ?
                WHERE id = ?
                """,
                (email or row["email"], row["display_name"] or name, row["avatar_url"] or avatar_url or None, now, row["id"]),
            )
            row = db.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
    return auth_response(row)


def update_user_preferences(user: dict[str, Any], preferences: dict[str, Any]) -> dict[str, Any]:
    allowed_weights = {"mood", "distance", "weather", "aqi", "budget", "category", "quality", "environment"}
    current_preferences = dict(user.get("preferences") or {})
    clean_preferences = dict(current_preferences)
    if "weightAdjustments" in preferences or "weight_adjustments" in preferences:
        raw_weights = preferences.get("weightAdjustments") or preferences.get("weight_adjustments") or {}
        weights = {}
        for key, value in raw_weights.items():
            if key in allowed_weights:
                weights[key] = max(0.5, min(1.6, float(value)))
        clean_preferences["weightAdjustments"] = weights
    if "favoriteStarts" in preferences or "favorite_starts" in preferences:
        clean_preferences["favoriteStarts"] = normalize_favorite_starts(
            preferences.get("favoriteStarts") or preferences.get("favorite_starts") or []
        )
    init_recommendation_db()
    with connect_recommendation_db() as db:
        db.row_factory = sqlite3.Row
        db.execute(
            "UPDATE users SET preferences_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(clean_preferences, ensure_ascii=False), now_iso(), user["id"]),
        )
        row = db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    return public_user(row)


def normalize_favorite_starts(raw_starts: Any) -> list[dict[str, Any]]:
    starts = []
    if not isinstance(raw_starts, list):
        raise ValueError("常用起始點格式錯誤")
    for item in raw_starts[:2]:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()[:24]
        lat = float(item.get("lat"))
        lon = float(item.get("lon"))
        if not label:
            raise ValueError("請先為常用起點命名")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("常用起始點座標不正確")
        if not is_within_service_area(lat, lon):
            raise ValueError(f"常用起始點不在服務區域內；目前服務區域暫定為{SERVICE_AREA_LABEL}")
        starts.append({
            "id": str(item.get("id") or uuid.uuid4().hex),
            "label": label,
            "lat": round(lat, 6),
            "lon": round(lon, 6),
        })
    return starts


def update_user_profile(user: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    avatar_url = str(payload.get("avatar_url") or "").strip()
    if not name:
        raise ValueError("名稱為必填")
    if len(name) > 40:
        raise ValueError("名稱最多 40 個字元")
    if len(avatar_url) > 800000:
        raise ValueError("頭像圖片過大，請選擇較小的圖片")
    if avatar_url and not (avatar_url.startswith("data:image/") or avatar_url.startswith("https://")):
        raise ValueError("頭像格式不支援")

    init_recommendation_db()
    with connect_recommendation_db() as db:
        db.row_factory = sqlite3.Row
        db.execute(
            "UPDATE users SET display_name = ?, avatar_url = ?, updated_at = ? WHERE id = ?",
            (name, avatar_url or None, now_iso(), user["id"]),
        )
        row = db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    return public_user(row)


def logout_auth_session(token: str) -> dict[str, Any]:
    token = bearer_token(token)
    if token:
        init_recommendation_db()
        with connect_recommendation_db() as db:
            db.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))
    return {"ok": True}


def delete_user_account(user: dict[str, Any]) -> dict[str, Any]:
    session_id = user["session_id"]
    init_recommendation_db()
    with connect_recommendation_db() as db:
        db.row_factory = sqlite3.Row
        request_ids = [
            row["id"]
            for row in db.execute("SELECT id FROM recommendation_requests WHERE session_id = ?", (session_id,)).fetchall()
        ]
        if request_ids:
            placeholders = ",".join("?" for _ in request_ids)
            db.execute(f"DELETE FROM recommendation_results WHERE request_id IN ({placeholders})", request_ids)
        db.execute("DELETE FROM recommendation_requests WHERE session_id = ?", (session_id,))
        db.execute("DELETE FROM saved_places WHERE session_id = ?", (session_id,))
        db.execute("DELETE FROM recommendation_feedback WHERE session_id = ?", (session_id,))
        db.execute("DELETE FROM user_preference_signals WHERE session_id = ?", (session_id,))
        db.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user["id"],))
        db.execute("DELETE FROM users WHERE id = ?", (user["id"],))
    return {"ok": True, "deleted_user_id": user["id"]}


def scalar_count(db, table: str) -> int:
    row = db.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    return int(row["count"] if isinstance(row, dict) else row["count"])


def security_summary() -> dict[str, Any]:
    summary = security_config_summary()
    summary.update({
        "admin": {
            "token_mode": "sha256" if os.getenv("ADMIN_TOKEN_SHA256", "").strip() else ("plain" if os.getenv("ADMIN_TOKEN", "").strip() else "unset"),
            "query_token_allowed": False,
        },
    })
    return summary


def admin_summary() -> dict[str, Any]:
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
    places = get_attraction_service().index.places
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


def admin_users(limit: int = 80) -> dict[str, Any]:
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
        preferences = _safe_json_loads(row["preferences_json"], {})
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


def admin_delete_user(user_id: str) -> dict[str, Any]:
    init_recommendation_db()
    with connect_recommendation_db() as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    return delete_user_account(public_user(row))


def admin_recommendations(limit: int = 80) -> dict[str, Any]:
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
        criteria = _safe_json_loads(row["criteria_json"], {})
        source_status = _safe_json_loads(row["source_status_json"], {})
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


def admin_feedback(limit: int = 120) -> dict[str, Any]:
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


def admin_places_summary() -> dict[str, Any]:
    places = get_attraction_service().index.places
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


def _group_count(rows: list[sqlite3.Row], key: str) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row[key] or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return [
        {"label": label, "count": count}
        for label, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
    ]


def admin_overview(limit: int = 80) -> dict[str, Any]:
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
            preferences = _safe_json_loads(row["preferences_json"], {})
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
            criteria = _safe_json_loads(row["criteria_json"], {})
            context = _safe_json_loads(row["context_json"], {})
            source_status = _safe_json_loads(row["source_status_json"], {})
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
                "rain_probability": rain_probability_from_context(context),
                "aqi": aqi_from_context(context),
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

    places_summary = admin_places_summary()
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
            "providers": _group_count(provider_rows, "provider"),
            "feedback_types": _group_count(all_feedback_rows, "feedback_type"),
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


def auth_config():
    client_id = os.getenv("VITE_GOOGLE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID") or ""
    return {"google_client_id": client_id, "google_enabled": bool(client_id)}


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


def register_api_routers() -> None:
    deps = SimpleNamespace(
        admin_delete_user=admin_delete_user,
        admin_feedback=admin_feedback,
        admin_overview=admin_overview,
        admin_places_summary=admin_places_summary,
        admin_recommendations=admin_recommendations,
        admin_summary=admin_summary,
        admin_users=admin_users,
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
