"""Unified FastAPI app for NEXT STOPS external-data clients.

Run from this directory:
  uvicorn api_app:app --reload --host 127.0.0.1 --port 8790
"""

from __future__ import annotations

import importlib.util
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - PostgreSQL is optional for local SQLite mode.
    psycopg = None
    dict_row = None

try:
    from fastapi import Body, FastAPI, Header, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("請先安裝 FastAPI dependencies：pip install -r requirements.txt") from exc


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
ATTRACTION_PLATFORM_ROOT = ROOT / "taipei_attraction_search_platform"
ATTRACTION_CACHE = ATTRACTION_PLATFORM_ROOT / "data" / "taipei_places.json"
RECOMMENDATION_DB = Path(os.getenv("NEXT_STOPS_DB_PATH", ROOT / "data" / "next_stops.sqlite3"))
DATABASE_URL = (
    os.getenv("DATABASE_URL")
    or os.getenv("POSTGRES_URL")
    or os.getenv("NEXT_STOPS_DATABASE_URL")
    or ""
)
USE_POSTGRES = bool(DATABASE_URL)
GOOGLE_DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"
GOOGLE_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
GOOGLE_GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"
GOOGLE_PLACE_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
GOOGLE_FIND_PLACE_URL = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
DEFAULT_MAPBOX_TOKEN = "your_mapbox_access_token"
MAX_STATION_RESULTS = 300
TDX_REQUEST_RETRIES = 2
ROUTE_COMPARE_MODES = ("CAR", "BUS", "MRT", "MOTORCYCLE", "WALKING", "BICYCLE")

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

OPENING_UNKNOWN_ALLOWED_CATEGORIES = {"park", "riverside", "viewpoint"}


class TransitModeMismatchError(RuntimeError):
    """Raised when Google returns a transit route that uses a different vehicle type."""


class RouteUnavailableError(RuntimeError):
    """Raised when a route provider confirms that the requested mode has no route."""


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
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv(
        "NEXT_STOPS_CORS_ORIGINS",
        "http://127.0.0.1:5174,http://localhost:5174",
    ).split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CachedTDX:
    def __init__(self, module, env_prefix: str):
        self.module = module
        self.env_prefix = env_prefix
        self.client_id = env_first(f"{env_prefix}_CLIENT_ID", "TDX_CLIENT_ID", default=module.client_id)
        self.client_secret = env_first(f"{env_prefix}_CLIENT_SECRET", "TDX_CLIENT_SECRET", default=module.client_secret)
        self._token = ""
        self._token_expires_at = 0.0
        self._lock = threading.Lock()

    def get_token(self) -> str:
        now = time.time()
        with self._lock:
            if self._token and now < self._token_expires_at:
                return self._token

            token_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
            headers = {"content-type": "application/x-www-form-urlencoded"}
            data = {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
            response = requests.post(token_url, headers=headers, data=data, timeout=10)
            response.raise_for_status()
            payload = response.json()
            self._token = payload["access_token"]
            self._token_expires_at = now + int(payload.get("expires_in", 3600)) - 60
            return self._token

    def get_response(self, url: str, retries: int = TDX_REQUEST_RETRIES):
        headers = {"authorization": f"Bearer {self.get_token()}"}
        for attempt in range(retries + 1):
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 429:
                retry_after = self.module.parse_int(response.headers.get("Retry-After"), 5)
                if attempt < retries:
                    time.sleep(retry_after)
                    continue
                raise self.module.TDXRateLimitError("TDX API request limit reached. Please wait and try again.")
            response.raise_for_status()
            return response.json()
        return []


bus_tdx = CachedTDX(bus_module, "TDX_BUS")
mrt_tdx = CachedTDX(mrt_module, "TDX_MRT")
weather_aqi_client = weather_aqi_module.WeatherAQIClient()
bus_station_cache: dict[str, dict[str, Any]] = {}
mrt_stations_cache: dict[str, Any] = {"items": [], "fetched_at": None}
google_place_status_cache: dict[str, dict[str, Any]] = {}
google_place_lookup_cache: dict[str, str] = {}
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


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_float(value: object, default: float | None = None) -> float | None:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def haversine_m(lat1: float | None, lon1: float | None, lat2: float | None, lon2: float | None) -> float | None:
    if None in (lat1, lon1, lat2, lon2):
        return None
    radius = 6371000
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    delta_phi = math.radians(float(lat2) - float(lat1))
    delta_lambda = math.radians(float(lon2) - float(lon1))
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def get_google_maps_key() -> str:
    return env_first("GOOGLE_MAPS_SERVER_KEY", "GOOGLE_MAPS_API_KEY", "GOOGLE_MAPS_BROWSER_KEY")


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


def convert_sql_for_postgres(sql: str) -> str:
    return (
        sql
        .replace("?", "%s")
        .replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
    )


class PostgresCursor:
    def __init__(self, cursor):
        self.cursor = cursor
        self.lastrowid = None

    @property
    def rowcount(self) -> int:
        return self.cursor.rowcount

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()


class PostgresConnection:
    def __init__(self):
        if psycopg is None:
            raise RuntimeError("PostgreSQL mode requires psycopg. Install dependencies with: pip install -r requirements.txt")
        self.conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        self.row_factory = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self.conn.rollback()
        else:
            self.conn.commit()
        self.conn.close()
        return False

    def execute(self, sql: str, params: tuple | list | None = None):
        cursor = self.conn.execute(convert_sql_for_postgres(sql), params or ())
        return PostgresCursor(cursor)

    def executemany(self, sql: str, seq_of_params):
        cursor = self.conn.cursor()
        cursor.executemany(convert_sql_for_postgres(sql), seq_of_params)
        return PostgresCursor(cursor)


def connect_recommendation_db():
    if USE_POSTGRES:
        return PostgresConnection()
    return sqlite3.connect(RECOMMENDATION_DB)


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


@app.get("/health")
def health():
    return {"status": "ok", "service": "next-stops-data-api"}


@app.get("/api/sample-locations")
def sample_locations():
    return {"locations": SAMPLE_LOCATIONS}


@app.get("/api/context")
def next_stops_context(lat: float, lon: float, real: bool = False):
    return run_or_raise(lambda: weather_aqi_client.real_context(lat, lon) if real else weather_aqi_client.context(lat, lon))


@app.get("/api/mapbox-config")
def mapbox_config():
    token = get_mapbox_token()
    if not token or token == DEFAULT_MAPBOX_TOKEN:
        return {"access_token": "", "configured": False}
    return {"access_token": token, "configured": True}


@app.get("/api/auth/config")
def auth_config():
    client_id = os.getenv("VITE_GOOGLE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID") or ""
    return {"google_client_id": client_id, "google_enabled": bool(client_id)}


@app.post("/api/auth/register")
def api_auth_register(payload: dict[str, Any] | None = Body(default=None)):
    return run_or_raise(lambda: register_platform_user(payload or {}))


@app.post("/api/auth/login")
def api_auth_login(payload: dict[str, Any] | None = Body(default=None)):
    return run_or_raise(lambda: login_platform_user(payload or {}))


@app.post("/api/auth/google")
def api_auth_google(payload: dict[str, Any] | None = Body(default=None)):
    return run_or_raise(lambda: login_google_user(payload or {}))


@app.get("/api/auth/me")
def api_auth_me(authorization: str | None = Header(default=None)):
    user = require_current_user(authorization)
    return {"user": user}


@app.patch("/api/auth/preferences")
def api_auth_preferences(payload: dict[str, Any] | None = Body(default=None), authorization: str | None = Header(default=None)):
    user = require_current_user(authorization)
    updated = run_or_raise(lambda: update_user_preferences(user, payload or {}))
    return {"user": updated}


@app.patch("/api/auth/profile")
def api_auth_profile(payload: dict[str, Any] | None = Body(default=None), authorization: str | None = Header(default=None)):
    user = require_current_user(authorization)
    updated = run_or_raise(lambda: update_user_profile(user, payload or {}))
    return {"user": updated}


@app.post("/api/auth/logout")
def api_auth_logout(authorization: str | None = Header(default=None), token: str | None = Query(default=None)):
    return run_or_raise(lambda: logout_auth_session(authorization or token or ""))


@app.delete("/api/auth/account")
def api_auth_delete_account(authorization: str | None = Header(default=None)):
    user = require_current_user(authorization)
    return run_or_raise(lambda: delete_user_account(user))


@app.post("/api/route")
def api_route(payload: dict[str, Any] | None = Body(default=None)):
    def build_route():
        data = payload or {}
        origin = data.get("origin") or {}
        destination = data.get("destination") or {}
        if origin.get("lng") is not None and origin.get("lon") is None:
            origin["lon"] = origin.get("lng")
        if destination.get("lng") is not None and destination.get("lon") is None:
            destination["lon"] = destination.get("lng")
        if to_float(origin.get("lat")) is None or to_float(origin.get("lon")) is None:
            raise ValueError("origin.lat and origin.lon are required")
        if to_float(destination.get("lat")) is None or to_float(destination.get("lon")) is None:
            raise ValueError("destination.lat and destination.lon are required")
        normalized_origin = {"lat": to_float(origin["lat"]), "lon": to_float(origin["lon"])}
        normalized_destination = {"lat": to_float(destination["lat"]), "lon": to_float(destination["lon"])}
        return compare_commute_options(
            normalized_origin,
            normalized_destination,
            modes=normalize_transport_modes(data.get("transportModes")),
            include_geometry=True,
        )

    return run_or_raise(build_route)


@app.get("/api/weather-aqi")
def weather_aqi(lat: float, lon: float, real: bool = False):
    return next_stops_context(lat=lat, lon=lon, real=real)


@app.get("/api/cwa/current-weather")
def cwa_current_weather(lat: float, lon: float):
    return run_or_raise(lambda: cwa_module.CWAWeatherClient().current_weather(lat, lon))


@app.get("/api/cwa/rainfall")
def cwa_rainfall(lat: float, lon: float):
    return run_or_raise(lambda: cwa_module.CWAWeatherClient().rainfall(lat, lon))


@app.get("/api/cwa/uv")
def cwa_uv(lat: float, lon: float, station_id: str = ""):
    return run_or_raise(lambda: cwa_module.CWAWeatherClient().uv(lat, lon, station_id))


@app.get("/api/cwa/forecast")
def cwa_forecast(location_name: str | None = None):
    return run_or_raise(lambda: cwa_module.CWAWeatherClient().forecast(location_name))


@app.get("/api/cwa/township-forecast")
def cwa_township_forecast(lat: float, lon: float):
    return run_or_raise(lambda: cwa_module.CWAWeatherClient().township_forecast(lat, lon))


@app.get("/api/moenv/aqi")
def moenv_aqi(lat: float, lon: float):
    return run_or_raise(lambda: moenv_module.MOENVAQIClient().aqi(lat, lon))


@app.post("/api/places/build")
def places_build(with_optional: bool = False):
    def build():
        service = TaipeiAttractionSearchService(cache_path=ATTRACTION_CACHE)
        report = service.build(include_optional_nearby=with_optional)
        attraction_service_cache["service"] = service
        attraction_service_cache["loaded_at"] = now_iso()
        return {"final_count": report.final_count, "fetched_counts": report.fetched_counts, "errors": report.errors}

    return run_or_raise(build)


@app.get("/api/places/search")
def api_places_search(
    q: str | None = None,
    district: str | None = None,
    category: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_m: int | None = None,
    limit: int = 20,
):
    return run_or_raise(
        lambda: {
            "count": len(
                results := search_attraction_places(
                    q=q,
                    district=district,
                    category=category,
                    lat=lat,
                    lon=lon,
                    radius_m=radius_m,
                    limit=limit,
                )
            ),
            "results": results,
        }
    )


@app.get("/api/places/{place_id}")
def api_place_detail(
    place_id: str,
    lat: float | None = None,
    lon: float | None = None,
    mood: str = "relaxing_walk",
    distance: int = 30,
    time_minutes: int = Query(120, alias="time"),
    budget: str = "medium",
    weather_preference: str = Query("any", alias="weatherPreference"),
    transport_modes: str | None = Query(None, alias="transportModes"),
    session_id: str | None = None,
):
    criteria = detail_criteria_from_query(
        lat=lat,
        lon=lon,
        mood=mood,
        distance=distance,
        time_minutes=time_minutes,
        budget=budget,
        weather_preference=weather_preference,
        transport_modes=transport_modes,
    )
    return run_or_raise(lambda: build_place_detail(place_id, criteria, session_id=session_id))


@app.get("/api/districts")
def api_districts():
    return run_or_raise(lambda: get_attraction_service().districts())


@app.post("/api/recommend")
def api_recommend(payload: dict[str, Any] | None = Body(default=None)):
    return run_or_raise(lambda: build_recommendations(payload or {}))


@app.post("/api/recommendations")
def api_recommendations(payload: dict[str, Any] | None = Body(default=None)):
    return run_or_raise(lambda: build_recommendations(payload or {}))


@app.get("/api/recommendations/{request_id}")
def api_recommendation_record(request_id: str):
    record = run_or_raise(lambda: fetch_recommendation_record(request_id))
    if record is None:
        raise HTTPException(status_code=404, detail="Recommendation request not found")
    return record


@app.get("/api/saved-places")
def api_saved_places(session_id: str = Query(...)):
    return run_or_raise(lambda: {"saved": list_saved_places(session_id.strip())})


@app.post("/api/saved-places")
def api_save_place(payload: dict[str, Any] | None = Body(default=None)):
    return run_or_raise(lambda: upsert_saved_place(payload or {}))


@app.patch("/api/saved-places/{place_id}")
def api_update_saved_place(place_id: str, payload: dict[str, Any] | None = Body(default=None)):
    data = payload or {}
    session_id = str(data.get("session_id") or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    updated = run_or_raise(lambda: update_saved_place_note(session_id, place_id, str(data.get("note") or "")))
    if updated is None:
        raise HTTPException(status_code=404, detail="Saved place not found")
    return updated


@app.delete("/api/saved-places/{place_id}")
def api_delete_saved_place(place_id: str, session_id: str = Query(...)):
    return run_or_raise(lambda: remove_saved_place(session_id.strip(), place_id))


@app.post("/api/recommendation-feedback")
def api_recommendation_feedback(payload: dict[str, Any] | None = Body(default=None)):
    return run_or_raise(lambda: record_feedback(payload or {}))


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


@app.get("/api/bus/stations")
def bus_stations(q: str = "", city: str | None = None):
    selected_city = get_bus_city(city)
    return run_or_raise(lambda: [bus_station_option(item) for item in find_bus_stations(q, selected_city)])


@app.get("/api/bus/station")
def bus_station(station_id: str = Query(...), city: str | None = None):
    selected_city = get_bus_city(city)
    return run_or_raise(lambda: get_bus_station_detail(station_id.strip(), selected_city))


@app.get("/api/bus/arrivals")
def bus_arrivals(stop_uid: str = Query(...), city: str | None = None, route_name: str = ""):
    selected_city = get_bus_city(city)
    return run_or_raise(lambda: get_bus_arrivals(stop_uid.strip(), selected_city, route_name.strip()))


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


@app.get("/api/mrt/stations")
def mrt_stations(q: str = ""):
    return run_or_raise(lambda: [mrt_station_summary(item) for item in find_mrt_stations(q)])


@app.get("/api/mrt/liveboard")
def mrt_liveboard(station_id: str = Query(...)):
    return run_or_raise(lambda: get_mrt_liveboard(station_id.strip()))
