import importlib.util
import json
import os
import threading
import time
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests


ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "static-bus"
MAX_STATION_RESULTS = 300
TDX_REQUEST_RETRIES = 2

TDX_MODULE_PATH = "TDX-BUS_API_clients.py"
spec = importlib.util.spec_from_file_location("tdx_bus_api_clients", ROOT / TDX_MODULE_PATH)
tdx_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tdx_module)

BASE_URL = tdx_module.BASE_URL
DEFAULT_CITY = os.getenv("TDX_BUS_CITY", tdx_module.DEFAULT_CITY)

client_id = os.getenv("TDX_BUS_CLIENT_ID") or os.getenv("TDX_CLIENT_ID") or tdx_module.client_id
client_secret = os.getenv("TDX_BUS_CLIENT_SECRET") or os.getenv("TDX_CLIENT_SECRET") or tdx_module.client_secret


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

station_cache = {}


def normalize_search_text(value):
    return str(value or "").strip().lower().replace("台", "臺")


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


def get_city(params):
    return params.get("city", [DEFAULT_CITY])[0].strip() or DEFAULT_CITY


def get_stations(city=DEFAULT_CITY):
    if city in station_cache:
        return station_cache[city]["items"]

    url = tdx_module.get_station_url(city)
    stations = ensure_list_response(tdx.get_response(url), f"{city} bus station list")
    station_cache[city] = {
        "items": sorted(stations, key=lambda item: item.get("StationID", "")),
        "fetched_at": datetime.now().isoformat(),
    }
    return station_cache[city]["items"]


def find_stations(query, city=DEFAULT_CITY):
    query = normalize_search_text(query)
    stations = get_stations(city)
    if not query:
        return stations[:MAX_STATION_RESULTS]

    matches = []
    for station in stations:
        summary = tdx_module.serialize_station(station)
        haystack = normalize_search_text(
            " ".join([
                summary.get("id", ""),
                summary.get("uid", ""),
                summary.get("name_zh", ""),
                summary.get("name_en", ""),
                " ".join(summary.get("route_names", [])),
            ])
        )
        if query in haystack:
            matches.append(station)

    return sorted(
        matches,
        key=lambda item: (
            normalize_search_text(tdx_module.get_name_zh(item.get("StationName", ""))) != query,
            item.get("StationID", ""),
        ),
    )[:MAX_STATION_RESULTS]


def get_station_by_id(station_id, city=DEFAULT_CITY):
    for station in get_stations(city):
        if station.get("StationID") == station_id or station.get("StationUID") == station_id:
            return station
    return None


def get_stop_summaries_for_station(station, city=DEFAULT_CITY):
    summary = tdx_module.serialize_station(station)
    if summary["stops"]:
        return summary["stops"]

    station_id = station.get("StationID", "")
    if not station_id:
        return []

    stops = ensure_list_response(
        tdx.get_response(tdx_module.get_stop_url(city, station_id=station_id)),
        f"{city} bus stops for station {station_id}",
    )
    return [tdx_module.serialize_stop(stop) for stop in stops]


def get_station_detail(station_id, city=DEFAULT_CITY):
    station = get_station_by_id(station_id, city)
    if station is None:
        raise RuntimeError(f"Cannot find bus station {station_id} in {city}")

    summary = tdx_module.serialize_station(station)
    summary["stops"] = get_stop_summaries_for_station(station, city)
    summary["stop_count"] = len(summary["stops"])
    return summary


def get_station_option(station):
    summary = tdx_module.serialize_station(station)
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


def get_arrivals(stop_uid, city=DEFAULT_CITY, route_name=""):
    url = tdx_module.get_eta_url(city, stop_uid=stop_uid, route_name=route_name or None)
    arrivals = ensure_list_response(tdx.get_response(url), f"{city} bus arrivals for stop {stop_uid}")
    arrivals = sorted(arrivals, key=tdx_module.sort_arrival_item)
    serialized = [tdx_module.serialize_arrival(item) for item in arrivals]
    update_time = serialized[0]["update_time"] if serialized else ""

    normal_count = sum(1 for item in arrivals if tdx_module.parse_int(item.get("StopStatus")) == 0)
    arriving_count = sum(
        1
        for item in arrivals
        if tdx_module.parse_int(item.get("StopStatus")) == 0
        and tdx_module.parse_int(item.get("EstimateTime"), 999999) <= 180
    )
    route_count = len({item["route_name"] for item in serialized if item["route_name"]})

    return {
        "stop_uid": stop_uid,
        "city": city,
        "route_name": route_name,
        "update_time": update_time,
        "counts": {
            "total": len(serialized),
            "normal": normal_count,
            "arriving": arriving_count,
            "service_issue": len(serialized) - normal_count,
            "routes": route_count,
        },
        "arrivals": serialized,
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
        params = parse_qs(parsed.query)
        city = get_city(params)

        if parsed.path == "/api/stations":
            query = params.get("q", [""])[0]
            try:
                self.send_json([get_station_option(item) for item in find_stations(query, city)])
            except Exception as exc:
                self.send_tdx_error_json(exc)
            return

        if parsed.path == "/api/station":
            station_id = params.get("station_id", [""])[0].strip()
            if not station_id:
                self.send_error_json("station_id is required", status=400)
                return
            try:
                self.send_json(get_station_detail(station_id, city))
            except Exception as exc:
                self.send_tdx_error_json(exc)
            return

        if parsed.path == "/api/arrivals":
            stop_uid = params.get("stop_uid", [""])[0].strip()
            route_name = params.get("route_name", [""])[0].strip()
            if not stop_uid:
                self.send_error_json("stop_uid is required", status=400)
                return
            try:
                self.send_json(get_arrivals(stop_uid, city, route_name))
            except Exception as exc:
                self.send_tdx_error_json(exc)
            return

        if parsed.path == "/":
            self.path = "/index.html"

        return super().do_GET()


def run():
    port = int(os.getenv("PORT", "8767"))
    server = ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
    print(f"TDX bus dashboard prototype running at http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
