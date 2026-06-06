import importlib.util
import json
import os
import re
import threading
import time
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
STATIC_ROOT = ROOT / "static-mrt"
MAX_STATION_RESULTS = 300
TDX_REQUEST_RETRIES = 2

TDX_MODULE_PATH = "TDX-MRT_API_clients.py"
spec = importlib.util.spec_from_file_location("tdx_api_clients", ROOT / TDX_MODULE_PATH)
tdx_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tdx_module)

BASE_URL = tdx_module.BASE_URL
OPERATOR = tdx_module.OPERATOR

client_id = os.getenv("TDX_MRT_CLIENT_ID") or os.getenv("TDX_CLIENT_ID") or tdx_module.client_id
client_secret = os.getenv("TDX_MRT_CLIENT_SECRET") or os.getenv("TDX_CLIENT_SECRET") or tdx_module.client_secret


class CachedTDX(tdx_module.TDX):
    def __init__(self, client_id, client_secret):
        super().__init__(client_id, client_secret)
        self._token = ""
        self._token_expires_at = 0
        self._lock = threading.Lock()

    def get_token(self):
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

    def get_response(self, url, retries=TDX_REQUEST_RETRIES):
        headers = {"authorization": f"Bearer {self.get_token()}"}

        for attempt in range(retries + 1):
            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code == 429:
                retry_after = tdx_module.parse_int(response.headers.get("Retry-After"), 5)
                if attempt < retries:
                    time.sleep(retry_after)
                    continue
                raise tdx_module.TDXRateLimitError(
                    "TDX API request limit reached. Please wait and try again."
                )

            response.raise_for_status()
            return response.json()

        return []


tdx = CachedTDX(client_id, client_secret)

stations_cache = {
    "items": [],
    "fetched_at": None,
}


def station_name_zh(station):
    return tdx_module.get_station_name_zh(station.get("StationName", ""))


def station_name_en(station):
    name = station.get("StationName", "")
    if isinstance(name, dict):
        return name.get("En", "")
    return ""


def get_line_id(value):
    if not value:
        return ""
    match = re.match(r"[A-Z]+", str(value))
    return match.group(0) if match else str(value)


def normalize_search_text(value):
    return value.strip().lower().replace("台", "臺")


def get_stations():
    if stations_cache["items"]:
        return stations_cache["items"]

    url = f"{BASE_URL}/Rail/Metro/Station/{OPERATOR}?$format=JSON"
    stations = ensure_list_response(tdx.get_response(url), "station list")
    stations_cache["items"] = sorted(stations, key=lambda item: item.get("StationID", ""))
    stations_cache["fetched_at"] = datetime.now().isoformat()
    return stations_cache["items"]


def ensure_list_response(data, label):
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


def find_stations(query):
    query = normalize_search_text(query)
    stations = get_stations()
    if not query:
        return stations[:MAX_STATION_RESULTS]

    matches = []
    for station in stations:
        station_id = station.get("StationID", "")
        zh = station_name_zh(station)
        en = station_name_en(station)
        haystack = normalize_search_text(f"{station_id} {zh} {en}")
        if query in haystack:
            matches.append(station)
    return sorted(
        matches,
        key=lambda item: (
            normalize_search_text(station_name_zh(item)) != query,
            item.get("StationID", ""),
        ),
    )[:MAX_STATION_RESULTS]


def get_station_summary(station):
    station_id = station.get("StationID", "")
    return {
        "id": station_id,
        "name_zh": station_name_zh(station),
        "name_en": station_name_en(station),
        "line_id": station.get("LineID") or station.get("LineNo") or get_line_id(station_id),
    }


def get_status_kind(item):
    status_code = tdx_module.parse_int(item.get("ServiceStatus"))
    if status_code == 1:
        return "pending"
    if status_code == 2:
        return "skipping"
    if status_code in (3, 4):
        return "closed"
    if status_code != 0:
        return "muted"

    estimate_seconds = tdx_module.parse_int(item.get("EstimateTime"))
    if estimate_seconds <= 0:
        return "arriving"
    if estimate_seconds <= 180:
        return "approaching"
    return "normal"


def serialize_liveboard_item(item):
    if not isinstance(item, dict):
        raise RuntimeError(f"TDX liveboard returned an invalid MRT liveboard item: {item!r}")

    service_status_code = tdx_module.parse_int(item.get("ServiceStatus"))
    estimate_seconds = None
    if service_status_code == 0 and item.get("EstimateTime") not in (None, ""):
        estimate_seconds = tdx_module.parse_int(item.get("EstimateTime"))

    return {
        "line_id": item.get("LineID") or item.get("LineNO") or "",
        "line_name": tdx_module.get_name_zh(item.get("LineName", "")),
        "station_id": item.get("StationID", ""),
        "station": tdx_module.get_station_name_zh(item.get("StationName", "")),
        "station_en": item.get("StationName", {}).get("En", "") if isinstance(item.get("StationName"), dict) else "",
        "trip_head_sign": item.get("TripHeadSign", ""),
        "destination_id": item.get("DestinationStationID") or item.get("DestinationStaionID") or "",
        "destination": tdx_module.get_name_zh(item.get("DestinationStationName", "")),
        "destination_en": item.get("DestinationStationName", {}).get("En", "") if isinstance(item.get("DestinationStationName"), dict) else "",
        "estimate_seconds": estimate_seconds,
        "estimate_label": tdx_module.format_estimate_time(item),
        "service_status_code": service_status_code,
        "service_status": tdx_module.get_service_status(item),
        "status": tdx_module.get_mrt_status(item),
        "status_kind": get_status_kind(item),
        "update_time": item.get("UpdateTime") or item.get("SrcUpdateTime") or "",
    }


def get_direction_key(item):
    return (
        item.get("DestinationStationID")
        or item.get("DestinationStaionID")
        or item.get("TripHeadSign")
        or "unknown"
    )


def get_direction_label(item):
    trip_head_sign = item.get("TripHeadSign", "")
    destination = tdx_module.get_name_zh(item.get("DestinationStationName", ""))

    if trip_head_sign:
        return trip_head_sign
    if destination:
        return f"往{destination}"
    return "未知方向"


def sort_liveboard_item(item):
    service_status_code = tdx_module.parse_int(item.get("ServiceStatus"))
    estimate_seconds = tdx_module.parse_int(item.get("EstimateTime"), 999999)
    return (
        item.get("LineID") or item.get("LineNO") or "",
        get_direction_key(item),
        service_status_code != 0,
        estimate_seconds,
        tdx_module.get_name_zh(item.get("DestinationStationName", "")),
    )


def build_direction_groups(liveboard_items):
    groups = []
    by_key = {}

    for item in liveboard_items:
        key = get_direction_key(item)
        if key not in by_key:
            by_key[key] = {
                "key": key,
                "line_id": item.get("LineID") or item.get("LineNO") or "",
                "line_name": tdx_module.get_name_zh(item.get("LineName", "")),
                "label": get_direction_label(item),
                "destination_id": item.get("DestinationStationID") or item.get("DestinationStaionID") or "",
                "destination": tdx_module.get_name_zh(item.get("DestinationStationName", "")),
                "destination_en": item.get("DestinationStationName", {}).get("En", "") if isinstance(item.get("DestinationStationName"), dict) else "",
                "items": [],
            }
            groups.append(by_key[key])

        by_key[key]["items"].append(serialize_liveboard_item(item))

    return groups


def get_liveboard(station_id):
    url = tdx_module.get_liveboard_url(station_id.strip())
    liveboard_items = ensure_list_response(tdx.get_response(url), f"MRT liveboard for station {station_id}")
    liveboard_items = sorted(liveboard_items, key=sort_liveboard_item)
    liveboard = [serialize_liveboard_item(item) for item in liveboard_items]
    direction_groups = build_direction_groups(liveboard_items)

    station = None
    if liveboard_items:
        station = {
            "StationID": liveboard_items[0].get("StationID", station_id),
            "StationName": liveboard_items[0].get("StationName", station_id),
        }
    else:
        station = next((item for item in get_stations() if item.get("StationID") == station_id), None)

    update_time = ""
    if liveboard_items:
        update_time = liveboard_items[0].get("UpdateTime") or liveboard_items[0].get("SrcUpdateTime") or ""

    normal_count = sum(1 for item in liveboard_items if tdx_module.parse_int(item.get("ServiceStatus")) == 0)
    arriving_count = sum(
        1
        for item in liveboard_items
        if tdx_module.parse_int(item.get("ServiceStatus")) == 0
        and tdx_module.parse_int(item.get("EstimateTime"), 999999) <= 180
    )
    destination_count = len({
        get_direction_key(item)
        for item in liveboard_items
    })

    return {
        "station": get_station_summary(station) if station else {"id": station_id, "name_zh": station_id, "name_en": ""},
        "update_time": update_time,
        "counts": {
            "total": len(liveboard),
            "normal": normal_count,
            "arriving": arriving_count,
            "service_issue": len(liveboard) - normal_count,
            "destinations": destination_count,
            "directions": len(direction_groups),
        },
        "liveboard": liveboard,
        "direction_groups": direction_groups,
    }


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_ROOT), **kwargs)

    def send_json(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except BrokenPipeError:
            pass

    def send_error_json(self, message, status=500):
        self.send_json({"error": message}, status=status)

    def send_tdx_error_json(self, exc):
        if isinstance(exc, tdx_module.TDXRateLimitError):
            self.send_error_json(str(exc), status=429)
            return

        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            status = exc.response.status_code
            message = f"TDX API request failed: {exc}"
            self.send_error_json(message, status=status if 400 <= status < 600 else 500)
            return

        self.send_error_json(str(exc))

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/stations":
            params = parse_qs(parsed.query)
            query = params.get("q", [""])[0]
            try:
                self.send_json([get_station_summary(item) for item in find_stations(query)])
            except Exception as exc:
                self.send_tdx_error_json(exc)
            return

        if parsed.path == "/api/liveboard":
            params = parse_qs(parsed.query)
            station_id = params.get("station_id", [""])[0].strip()
            if not station_id:
                self.send_error_json("station_id is required", status=400)
                return
            try:
                self.send_json(get_liveboard(station_id))
            except Exception as exc:
                self.send_tdx_error_json(exc)
            return

        if parsed.path == "/":
            self.path = "/index.html"

        return super().do_GET()


def run():
    port = int(os.getenv("PORT", "8766"))
    server = ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
    print(f"TDX MRT dashboard prototype running at http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
