"""Unified FastAPI app for NEXT STOPS external-data clients.

Run from this directory:
  uvicorn api_app:app --reload --host 127.0.0.1 --port 8790
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import re
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
    from fastapi import Body, FastAPI, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("請先安裝 FastAPI dependencies：pip install -r requirements.txt") from exc


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
ATTRACTION_PLATFORM_ROOT = ROOT / "taipei_attraction_search_platform"
ATTRACTION_CACHE = ATTRACTION_PLATFORM_ROOT / "data" / "taipei_places.json"
RECOMMENDATION_DB = Path(os.getenv("NEXT_STOPS_DB_PATH", ROOT / "data" / "next_stops.sqlite3"))
GOOGLE_DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"
GOOGLE_GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"
DEFAULT_MAPBOX_TOKEN = "your_mapbox_access_token"
MAX_STATION_RESULTS = 300
TDX_REQUEST_RETRIES = 2
ROUTE_COMPARE_MODES = ("TRANSIT", "WALKING", "DRIVING")

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
    "restaurant": "餐飲",
    "viewpoint": "景觀",
    "scenic_spot": "景點",
    "attraction": "景點",
    "taipei_featured": "精選景點",
}

COMMUTE_MODE_LABELS = {
    "TRANSIT": "大眾運輸",
    "WALKING": "步行",
    "DRIVING": "開車",
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
    allow_origins=os.getenv("NEXT_STOPS_CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(","),
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


def google_directions(origin: dict[str, Any], destination: dict[str, Any], mode: str, include_geometry: bool = False) -> dict[str, Any]:
    key = get_google_maps_key()
    if not key:
        raise RuntimeError("Google Maps API key is not configured")

    google_mode = {
        "TRANSIT": "transit",
        "WALKING": "walking",
        "DRIVING": "driving",
    }.get(mode, "transit")
    response = requests.get(
        GOOGLE_DIRECTIONS_URL,
        params={
            "origin": f"{origin['lat']},{origin['lon']}",
            "destination": f"{destination['lat']},{destination['lon']}",
            "mode": google_mode,
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
        raise RuntimeError(payload.get("error_message") or status or "Google Directions failed")

    route = payload["routes"][0]
    leg = route["legs"][0]
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


def fallback_commute(origin: dict[str, Any], destination: dict[str, Any], mode: str, include_geometry: bool = False) -> dict[str, Any]:
    distance = haversine_m(origin.get("lat"), origin.get("lon"), destination.get("lat"), destination.get("lon")) or 0
    speed_mps = {
        "WALKING": 1.25,
        "TRANSIT": 5.8,
        "DRIVING": 7.5,
    }.get(mode, 5.8)
    overhead_seconds = {
        "WALKING": 0,
        "TRANSIT": 420,
        "DRIVING": 300,
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
    if include_geometry:
        result["geometry"] = {
            "type": "LineString",
            "coordinates": [
                [origin.get("lon"), origin.get("lat")],
                [destination.get("lon"), destination.get("lat")],
            ],
        }
    return result


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
        except Exception as exc:
            errors[mode] = str(exc)
            option = fallback_commute(origin, destination, mode, include_geometry=include_geometry)
        options.append(option)

    best = min(options, key=lambda item: item.get("duration_seconds") or 999999)
    if include_geometry and "geometry" not in best:
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


def init_recommendation_db() -> None:
    RECOMMENDATION_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(RECOMMENDATION_DB) as db:
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


def record_recommendation(
    request_id: str,
    session_id: str | None,
    criteria: dict[str, Any],
    context: dict[str, Any],
    source_status: dict[str, Any],
    results: list[dict[str, Any]],
) -> None:
    init_recommendation_db()
    with sqlite3.connect(RECOMMENDATION_DB) as db:
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
    with sqlite3.connect(RECOMMENDATION_DB) as db:
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
    if budget in {"high", "flexible"}:
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


def primary_category(categories: list[str], text: str = "") -> str:
    blob = " ".join([*(categories or []), text]).lower()
    checks = [
        ("bookstore", r"書店|bookstore"),
        ("riverside", r"河濱|riverside|river"),
        ("museum", r"博物館|紀念館|museum"),
        ("gallery", r"美術館|藝文|藝術|gallery|文創"),
        ("restaurant", r"餐廳|restaurant|food|餐飲"),
        ("market", r"夜市|市場|market|商圈"),
        ("park", r"公園|步道|山|湖|park|trail"),
        ("viewpoint", r"景觀|夜景|古蹟|景點|viewpoint|scenic|attraction|taipei_featured"),
        ("cafe", r"咖啡|cafe"),
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
    if re.search(r"餐廳|商圈|restaurant|market", blob):
        return "high"
    return "medium"


def display_budget_from_price(price: str) -> str:
    return "flexible" if price == "high" else price


def place_environment(category: str, categories: list[str]) -> tuple[bool, bool]:
    blob = " ".join([category, *(categories or [])])
    indoor = bool(re.search(r"museum|gallery|bookstore|restaurant|cafe|market|博物館|美術館|書店|餐廳|文創|紀念館|展覽|劇場|影城|會館|主題館|寺|廟|堂", blob))
    outdoor = bool(re.search(r"park|riverside|viewpoint|market|公園|河濱|步道|景觀|夜市|古蹟", blob))
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
    category = primary_category(categories, text)
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
    commute = None
    if destination["lat"] is not None and destination["lon"] is not None:
        commute = compare_commute_options(origin, destination)
    travel_time = (
        max(1, round(float(commute["best"]["duration_seconds"]) / 60))
        if commute
        else max(8, round(distance_m / 420)) if distance_m is not None else max(12, round(float(criteria.get("distance") or 30) * 0.8))
    )
    price = place_price(category, categories)
    indoor, outdoor = place_environment(category, categories)

    place = recommendation_algorithm.Place(
        id=str(raw.get("id") or raw.get("name")),
        category=category,
        indoor=indoor,
        outdoor=outdoor,
        travel_time=float(travel_time),
        price=price,
        open_now=True,
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
        "description": raw.get("description") or "資料來自台北景點搜尋平台，並由後端推薦引擎重新評分。",
        "matched_travel_time": travel_time,
        "travel_time_minutes": travel_time,
        "commute": commute["best"] if commute else None,
        "commute_options": commute["options"] if commute else [],
        "budget": display_budget_from_price(price),
        "weather_status": "watch" if outdoor and rain_probability_from_context(context) >= 0.45 else "suitable" if indoor else "any",
        "weather_summary": context.get("weather", {}).get("summary") or "天氣資料已納入後端評分",
        "aqi_value": context.get("air_quality", {}).get("aqi") or "--",
        "aqi_status": context.get("air_quality", {}).get("status") or "unknown",
        "open_now": True,
        "route_hint": (
            f"最快約 {commute['best']['duration_text']}，建議方式：{commute['best']['mode_label']}。"
            if commute
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

    context = recommendation_context(criteria)
    user = user_context_from_criteria(criteria, context)
    candidates = collect_candidate_places(criteria, context, limit)
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
        "sqlite": {
            "status": "ok",
            "path": str(RECOMMENDATION_DB),
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
        return compare_commute_options(normalized_origin, normalized_destination, include_geometry=True)

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


@app.get("/api/districts")
def api_districts():
    return run_or_raise(lambda: get_attraction_service().districts())


@app.post("/api/recommendations")
def api_recommendations(payload: dict[str, Any] | None = Body(default=None)):
    return run_or_raise(lambda: build_recommendations(payload or {}))


@app.get("/api/recommendations/{request_id}")
def api_recommendation_record(request_id: str):
    record = run_or_raise(lambda: fetch_recommendation_record(request_id))
    if record is None:
        raise HTTPException(status_code=404, detail="Recommendation request not found")
    return record


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
