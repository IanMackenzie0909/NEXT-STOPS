"""Transport service helpers for TDX-backed bus and MRT features."""

from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime
from typing import Any, Callable

import requests

from .config import MAX_STATION_RESULTS, env_first
from .utils import haversine_m, to_float


DEFAULT_TDX_REQUEST_RETRIES = 2


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

    def get_response(self, url: str, retries: int = DEFAULT_TDX_REQUEST_RETRIES):
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


def normalize_search_text(value: object) -> str:
    return str(value or "").strip().lower().replace("台", "臺")


class TransportService:
    def __init__(self, bus_module, mrt_module):
        self.bus_module = bus_module
        self.mrt_module = mrt_module
        self.bus_tdx = CachedTDX(bus_module, "TDX_BUS")
        self.mrt_tdx = CachedTDX(mrt_module, "TDX_MRT")
        self.bus_station_cache: dict[str, dict[str, Any]] = {}
        self.mrt_stations_cache: dict[str, Any] = {"items": [], "fetched_at": None}

    def is_tdx_rate_limit_error(self, exc: Exception) -> bool:
        return isinstance(exc, (self.bus_module.TDXRateLimitError, self.mrt_module.TDXRateLimitError))

    @staticmethod
    def ensure_list_response(data: Any, label: str) -> list:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            message = (
                data.get("message")
                or data.get("Message")
                or data.get("error")
                or data.get("Error")
                or str(data)
            )
            raise RuntimeError(f"TDX {label} returned an error: {message}")
        raise RuntimeError(f"TDX {label} returned unexpected data: {type(data).__name__}")

    def tdx_credentials_configured(self) -> bool:
        values = [
            self.bus_tdx.client_id,
            self.bus_tdx.client_secret,
            self.mrt_tdx.client_id,
            self.mrt_tdx.client_secret,
        ]
        return all(values) and not any(str(value).startswith("your_") for value in values)

    @staticmethod
    def nearest_positioned_item(
        items: list[dict[str, Any]],
        lat: float | None,
        lon: float | None,
        serializer: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any] | None:
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
        if nearest is None or nearest_distance is None:
            return None
        nearest["distance_m"] = round(nearest_distance)
        return nearest

    def serialize_mrt_station_with_position(self, station: dict[str, Any]) -> dict[str, Any]:
        summary = self.mrt_station_summary(station)
        position = station.get("StationPosition") or {}
        summary["position"] = {
            "lat": position.get("PositionLat"),
            "lon": position.get("PositionLon"),
        }
        return summary

    def build_transport_context(self, results: list[dict[str, Any]], city: str | None = None) -> dict[str, Any]:
        status = {"tdx": "skipped", "bus": None, "mrt": None}
        if not self.tdx_credentials_configured():
            status["reason"] = "TDX credentials are not configured."
            return {"status": status, "by_place": {}}

        bus_stations = []
        mrt_stations = []
        selected_city = self.get_bus_city(city)
        try:
            bus_stations = self.get_bus_stations(selected_city)
            status["bus"] = "ok"
        except Exception as exc:
            status["bus"] = f"error: {exc}"
        try:
            mrt_stations = self.get_mrt_stations()
            status["mrt"] = "ok"
        except Exception as exc:
            status["mrt"] = f"error: {exc}"

        status["tdx"] = "ok" if status.get("bus") == "ok" or status.get("mrt") == "ok" else "error"
        by_place = {}
        for result in results:
            lat = to_float(result.get("lat"))
            lon = to_float(result.get("lon") if result.get("lon") is not None else result.get("lng"))
            by_place[result["id"]] = {
                "nearest_bus_station": self.nearest_positioned_item(
                    bus_stations,
                    lat,
                    lon,
                    self.bus_module.serialize_station,
                ) if bus_stations else None,
                "nearest_mrt_station": self.nearest_positioned_item(
                    mrt_stations,
                    lat,
                    lon,
                    self.serialize_mrt_station_with_position,
                ) if mrt_stations else None,
            }
        return {"status": status, "by_place": by_place}

    def get_bus_city(self, city: str | None = None) -> str:
        return (city or os.getenv("TDX_BUS_CITY") or self.bus_module.DEFAULT_CITY).strip() or self.bus_module.DEFAULT_CITY

    def get_bus_stations(self, city: str) -> list:
        if city in self.bus_station_cache:
            return self.bus_station_cache[city]["items"]
        stations = self.ensure_list_response(self.bus_tdx.get_response(self.bus_module.get_station_url(city)), f"{city} bus station list")
        self.bus_station_cache[city] = {
            "items": sorted(stations, key=lambda item: item.get("StationID", "")),
            "fetched_at": datetime.now().isoformat(),
        }
        return self.bus_station_cache[city]["items"]

    def find_bus_stations(self, query: str, city: str) -> list:
        normalized_query = normalize_search_text(query)
        stations = self.get_bus_stations(city)
        if not normalized_query:
            return stations[:MAX_STATION_RESULTS]

        matches = []
        for station in stations:
            summary = self.bus_module.serialize_station(station)
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
                normalize_search_text(self.bus_module.get_name_zh(item.get("StationName", ""))) != normalized_query,
                item.get("StationID", ""),
            ),
        )[:MAX_STATION_RESULTS]

    def bus_station_option(self, station: dict) -> dict:
        summary = self.bus_module.serialize_station(station)
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

    def get_bus_station_by_id(self, station_id: str, city: str) -> dict | None:
        for station in self.get_bus_stations(city):
            if station.get("StationID") == station_id or station.get("StationUID") == station_id:
                return station
        return None

    def get_bus_stop_summaries_for_station(self, station: dict, city: str) -> list:
        summary = self.bus_module.serialize_station(station)
        if summary["stops"]:
            return summary["stops"]
        station_id = station.get("StationID", "")
        if not station_id:
            return []
        stops = self.ensure_list_response(
            self.bus_tdx.get_response(self.bus_module.get_stop_url(city, station_id=station_id)),
            f"{city} bus stops for station {station_id}",
        )
        return [self.bus_module.serialize_stop(stop) for stop in stops]

    def get_bus_station_detail(self, station_id: str, city: str) -> dict:
        station = self.get_bus_station_by_id(station_id, city)
        if station is None:
            raise RuntimeError(f"Cannot find bus station {station_id} in {city}")
        summary = self.bus_module.serialize_station(station)
        summary["stops"] = self.get_bus_stop_summaries_for_station(station, city)
        summary["stop_count"] = len(summary["stops"])
        return summary

    def get_bus_arrivals(self, stop_uid: str, city: str, route_name: str = "") -> dict:
        arrivals = self.ensure_list_response(
            self.bus_tdx.get_response(self.bus_module.get_eta_url(city, stop_uid=stop_uid, route_name=route_name or None)),
            f"{city} bus arrivals for stop {stop_uid}",
        )
        arrivals = sorted(arrivals, key=self.bus_module.sort_arrival_item)
        serialized = [self.bus_module.serialize_arrival(item) for item in arrivals]
        normal_count = sum(1 for item in arrivals if self.bus_module.parse_int(item.get("StopStatus")) == 0)
        arriving_count = sum(
            1
            for item in arrivals
            if self.bus_module.parse_int(item.get("StopStatus")) == 0
            and self.bus_module.parse_int(item.get("EstimateTime"), 999999) <= 180
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

    def mrt_station_name_zh(self, station: dict) -> str:
        return self.mrt_module.get_station_name_zh(station.get("StationName", ""))

    @staticmethod
    def mrt_station_name_en(station: dict) -> str:
        name = station.get("StationName", "")
        if isinstance(name, dict):
            return name.get("En", "")
        return ""

    @staticmethod
    def get_mrt_line_id(value: object) -> str:
        if not value:
            return ""
        match = re.match(r"[A-Z]+", str(value))
        return match.group(0) if match else str(value)

    def get_mrt_stations(self) -> list:
        if self.mrt_stations_cache["items"]:
            return self.mrt_stations_cache["items"]
        url = f"{self.mrt_module.BASE_URL}/Rail/Metro/Station/{self.mrt_module.OPERATOR}?$format=JSON"
        stations = self.ensure_list_response(self.mrt_tdx.get_response(url), "MRT station list")
        self.mrt_stations_cache["items"] = sorted(stations, key=lambda item: item.get("StationID", ""))
        self.mrt_stations_cache["fetched_at"] = datetime.now().isoformat()
        return self.mrt_stations_cache["items"]

    def find_mrt_stations(self, query: str) -> list:
        normalized_query = normalize_search_text(query)
        stations = self.get_mrt_stations()
        if not normalized_query:
            return stations[:MAX_STATION_RESULTS]
        matches = []
        for station in stations:
            station_id = station.get("StationID", "")
            zh = self.mrt_station_name_zh(station)
            en = self.mrt_station_name_en(station)
            if normalized_query in normalize_search_text(f"{station_id} {zh} {en}"):
                matches.append(station)
        return sorted(
            matches,
            key=lambda item: (
                normalize_search_text(self.mrt_station_name_zh(item)) != normalized_query,
                item.get("StationID", ""),
            ),
        )[:MAX_STATION_RESULTS]

    def mrt_station_summary(self, station: dict) -> dict:
        station_id = station.get("StationID", "")
        return {
            "id": station_id,
            "name_zh": self.mrt_station_name_zh(station),
            "name_en": self.mrt_station_name_en(station),
            "line_id": station.get("LineID") or station.get("LineNo") or self.get_mrt_line_id(station_id),
        }

    def mrt_status_kind(self, item: dict) -> str:
        status_code = self.mrt_module.parse_int(item.get("ServiceStatus"))
        if status_code == 1:
            return "pending"
        if status_code == 2:
            return "skipping"
        if status_code in (3, 4):
            return "closed"
        if status_code != 0:
            return "muted"
        estimate_seconds = self.mrt_module.parse_int(item.get("EstimateTime"))
        if estimate_seconds <= 0:
            return "arriving"
        if estimate_seconds <= 180:
            return "approaching"
        return "normal"

    def serialize_mrt_liveboard_item(self, item: dict) -> dict:
        service_status_code = self.mrt_module.parse_int(item.get("ServiceStatus"))
        estimate_seconds = None
        if service_status_code == 0 and item.get("EstimateTime") not in (None, ""):
            estimate_seconds = self.mrt_module.parse_int(item.get("EstimateTime"))
        return {
            "line_id": item.get("LineID") or item.get("LineNO") or "",
            "line_name": self.mrt_module.get_name_zh(item.get("LineName", "")),
            "station_id": item.get("StationID", ""),
            "station": self.mrt_module.get_station_name_zh(item.get("StationName", "")),
            "station_en": item.get("StationName", {}).get("En", "") if isinstance(item.get("StationName"), dict) else "",
            "trip_head_sign": item.get("TripHeadSign", ""),
            "destination_id": item.get("DestinationStationID") or item.get("DestinationStaionID") or "",
            "destination": self.mrt_module.get_name_zh(item.get("DestinationStationName", "")),
            "destination_en": item.get("DestinationStationName", {}).get("En", "") if isinstance(item.get("DestinationStationName"), dict) else "",
            "estimate_seconds": estimate_seconds,
            "estimate_label": self.mrt_module.format_estimate_time(item),
            "service_status_code": service_status_code,
            "service_status": self.mrt_module.get_service_status(item),
            "status": self.mrt_module.get_mrt_status(item),
            "status_kind": self.mrt_status_kind(item),
            "update_time": item.get("UpdateTime") or item.get("SrcUpdateTime") or "",
        }

    @staticmethod
    def mrt_direction_key(item: dict) -> str:
        return item.get("DestinationStationID") or item.get("DestinationStaionID") or item.get("TripHeadSign") or "unknown"

    def mrt_direction_label(self, item: dict) -> str:
        trip_head_sign = item.get("TripHeadSign", "")
        destination = self.mrt_module.get_name_zh(item.get("DestinationStationName", ""))
        if trip_head_sign:
            return trip_head_sign
        if destination:
            return f"往{destination}"
        return "未知方向"

    def sort_mrt_liveboard_item(self, item: dict):
        service_status_code = self.mrt_module.parse_int(item.get("ServiceStatus"))
        estimate_seconds = self.mrt_module.parse_int(item.get("EstimateTime"), 999999)
        return (
            item.get("LineID") or item.get("LineNO") or "",
            self.mrt_direction_key(item),
            service_status_code != 0,
            estimate_seconds,
            self.mrt_module.get_name_zh(item.get("DestinationStationName", "")),
        )

    def build_mrt_direction_groups(self, liveboard_items: list) -> list:
        groups = []
        by_key: dict[str, dict] = {}
        for item in liveboard_items:
            key = self.mrt_direction_key(item)
            if key not in by_key:
                by_key[key] = {
                    "key": key,
                    "line_id": item.get("LineID") or item.get("LineNO") or "",
                    "line_name": self.mrt_module.get_name_zh(item.get("LineName", "")),
                    "label": self.mrt_direction_label(item),
                    "destination_id": item.get("DestinationStationID") or item.get("DestinationStaionID") or "",
                    "destination": self.mrt_module.get_name_zh(item.get("DestinationStationName", "")),
                    "destination_en": item.get("DestinationStationName", {}).get("En", "") if isinstance(item.get("DestinationStationName"), dict) else "",
                    "items": [],
                }
                groups.append(by_key[key])
            by_key[key]["items"].append(self.serialize_mrt_liveboard_item(item))
        return groups

    def get_mrt_liveboard(self, station_id: str) -> dict:
        liveboard_items = self.ensure_list_response(
            self.mrt_tdx.get_response(self.mrt_module.get_liveboard_url(station_id.strip())),
            f"MRT liveboard for station {station_id}",
        )
        liveboard_items = sorted(liveboard_items, key=self.sort_mrt_liveboard_item)
        liveboard = [self.serialize_mrt_liveboard_item(item) for item in liveboard_items]
        direction_groups = self.build_mrt_direction_groups(liveboard_items)
        if liveboard_items:
            station = {
                "StationID": liveboard_items[0].get("StationID", station_id),
                "StationName": liveboard_items[0].get("StationName", station_id),
            }
        else:
            station = next((item for item in self.get_mrt_stations() if item.get("StationID") == station_id), None)

        normal_count = sum(1 for item in liveboard_items if self.mrt_module.parse_int(item.get("ServiceStatus")) == 0)
        arriving_count = sum(
            1
            for item in liveboard_items
            if self.mrt_module.parse_int(item.get("ServiceStatus")) == 0
            and self.mrt_module.parse_int(item.get("EstimateTime"), 999999) <= 180
        )
        return {
            "station": self.mrt_station_summary(station) if station else {"id": station_id, "name_zh": station_id, "name_en": ""},
            "update_time": liveboard_items[0].get("UpdateTime") or liveboard_items[0].get("SrcUpdateTime") if liveboard_items else "",
            "counts": {
                "total": len(liveboard),
                "normal": normal_count,
                "arriving": arriving_count,
                "service_issue": len(liveboard) - normal_count,
                "destinations": len({self.mrt_direction_key(item) for item in liveboard_items}),
                "directions": len(direction_groups),
            },
            "liveboard": liveboard,
            "direction_groups": direction_groups,
        }
