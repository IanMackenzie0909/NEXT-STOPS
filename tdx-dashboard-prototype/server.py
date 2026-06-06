import importlib.util
import json
import os
import threading
import time
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import requests


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
STATIC_ROOT = ROOT / "static"
BASE_URL = "https://tdx.transportdata.tw/api/basic/v2"
MAX_STATION_RESULTS = 300

TDX_MODULE_PATH = "TDX-TR_API_clients.py"
spec = importlib.util.spec_from_file_location("tdx_api_clients", TDX_MODULE_PATH)
tdx_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tdx_module)

client_id = os.getenv("TDX_TR_CLIENT_ID") or os.getenv("TDX_CLIENT_ID") or tdx_module.client_id
client_secret = os.getenv("TDX_TR_CLIENT_SECRET") or os.getenv("TDX_CLIENT_SECRET") or tdx_module.client_secret


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

    def get_response(self, url):
        headers = {"authorization": f"Bearer {self.get_token()}"}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()


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


def normalize_search_text(value):
    return value.strip().lower().replace("台", "臺")


def get_stations():
    if stations_cache["items"]:
        return stations_cache["items"]

    url = f"{BASE_URL}/Rail/TRA/Station?$format=JSON"
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
    return {
        "id": station.get("StationID", ""),
        "name_zh": station_name_zh(station),
        "name_en": station_name_en(station),
    }


def get_train_type_name(item):
    train_type_name = item.get("TrainTypeName", "")
    if isinstance(train_type_name, dict):
        return train_type_name.get("Zh_tw") or train_type_name.get("En") or item.get("TrainTypeID", "")
    return train_type_name or item.get("TrainTypeID", "")


def get_status_kind(status):
    if status.startswith("即將進站"):
        return "arriving"
    if status == "即將離站":
        return "departing"
    if status == "已靠站":
        return "docked"
    if status == "已離站":
        return "departed"
    if "分後到站" in status:
        return "approaching"
    if "停靠中" in status:
        return "stopping"
    return "muted"


def serialize_train(item):
    if not isinstance(item, dict):
        raise RuntimeError(f"TDX liveboard returned an invalid train item: {item!r}")

    status = tdx_module.get_train_status(item)
    return {
        "train_no": item.get("TrainNo", ""),
        "station": tdx_module.get_station_name_zh(item.get("StationName", "")),
        "direction": item.get("Direction"),
        "train_type_id": item.get("TrainTypeID", ""),
        "train_type_name": get_train_type_name(item),
        "ending_station": tdx_module.get_station_name_zh(item.get("EndingStationName", "")),
        "arrival_time": item.get("ScheduledArrivalTime", ""),
        "departure_time": item.get("ScheduledDepartureTime", ""),
        "delay": tdx_module.format_delay(item.get("DelayTime")),
        "status": status,
        "status_kind": get_status_kind(status),
        "update_time": item.get("UpdateTime") or item.get("SrcUpdateTime") or "",
    }


def get_liveboard(station_id):
    safe_station_id = quote(station_id.strip())
    url = f"{BASE_URL}/Rail/TRA/LiveBoard/Station/{safe_station_id}?$format=JSON"
    trains = ensure_list_response(tdx.get_response(url), f"liveboard for station {station_id}")
    northbound = []
    southbound = []

    for item in trains:
        train = serialize_train(item)
        if item.get("Direction") == 0:
            northbound.append(train)
        elif item.get("Direction") == 1:
            southbound.append(train)

    station = next((item for item in get_stations() if item.get("StationID") == station_id), None)
    update_time = ""
    if trains:
        update_time = trains[0].get("UpdateTime") or trains[0].get("SrcUpdateTime") or ""

    return {
        "station": get_station_summary(station) if station else {"id": station_id, "name_zh": station_id, "name_en": ""},
        "update_time": update_time,
        "counts": {
            "northbound": len(northbound),
            "southbound": len(southbound),
            "total": len(trains),
        },
        "northbound": northbound,
        "southbound": southbound,
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

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/stations":
            params = parse_qs(parsed.query)
            query = params.get("q", [""])[0]
            try:
                self.send_json([get_station_summary(item) for item in find_stations(query)])
            except Exception as exc:
                self.send_error_json(str(exc))
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
                self.send_error_json(str(exc))
            return

        if parsed.path == "/":
            self.path = "/index.html"

        return super().do_GET()


def run():
    port = int(os.getenv("PORT", "8765"))
    server = ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
    print(f"TDX dashboard prototype running at http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
