"""Unified FastAPI app for NEXT STOPS external-data clients.

Run from this directory:
  uvicorn api_app:app --reload --host 127.0.0.1 --port 8790
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

try:
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("請先安裝 FastAPI dependencies：pip install -r requirements.txt") from exc


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
MAX_STATION_RESULTS = 300
TDX_REQUEST_RETRIES = 2

SAMPLE_LOCATIONS = [
    {"name": "臺北車站", "lat": 25.0478, "lon": 121.5170},
    {"name": "信義區市府", "lat": 25.0375, "lon": 121.5637},
    {"name": "士林夜市", "lat": 25.0881, "lon": 121.5240},
    {"name": "北投溫泉", "lat": 25.1368, "lon": 121.5064},
    {"name": "南港展覽館", "lat": 25.0553, "lon": 121.6175},
]


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


def load_module(module_name: str, filename: str):
    module_path = ROOT / filename
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


load_root_env()

cwa_module = load_module("cwa_weather_api_clients", "CWA-Weather_API_clients.py")
moenv_module = load_module("moenv_aqi_api_clients", "MOENV-AQI_API_clients.py")
weather_aqi_module = load_module("weather_aqi_api_clients", "Weather-AQI_API_clients.py")
bus_module = load_module("tdx_bus_api_clients", "TDX-BUS_API_clients.py")
mrt_module = load_module("tdx_mrt_api_clients", "TDX-MRT_API_clients.py")


app = FastAPI(title="NEXT STOPS Data API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("NEXT_STOPS_CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CachedTDX:
    def __init__(self, module):
        self.module = module
        self.client_id = os.getenv("TDX_CLIENT_ID", module.client_id)
        self.client_secret = os.getenv("TDX_CLIENT_SECRET", module.client_secret)
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


bus_tdx = CachedTDX(bus_module)
mrt_tdx = CachedTDX(mrt_module)
weather_aqi_client = weather_aqi_module.WeatherAQIClient()
bus_station_cache: dict[str, dict[str, Any]] = {}
mrt_stations_cache: dict[str, Any] = {"items": [], "fetched_at": None}


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


@app.get("/health")
def health():
    return {"status": "ok", "service": "next-stops-data-api"}


@app.get("/api/sample-locations")
def sample_locations():
    return {"locations": SAMPLE_LOCATIONS}


@app.get("/api/context")
def next_stops_context(lat: float, lon: float, real: bool = False):
    return run_or_raise(lambda: weather_aqi_client.real_context(lat, lon) if real else weather_aqi_client.context(lat, lon))


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
