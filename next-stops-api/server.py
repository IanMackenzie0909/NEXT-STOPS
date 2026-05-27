import json
import math
import os
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import urlopen

from weather_aqi_api_clients import get_context as get_weather_aqi_context


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
PLACES_PATH = DATA_DIR / "places.json"
SAVED_PATH = DATA_DIR / "saved_places.json"


def load_root_env():
    env_path = ROOT.parent / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_root_env()

DEFAULT_PORT = int(os.getenv("NEXT_STOPS_API_PORT", "8790"))
DEFAULT_BUS_CITY = os.getenv("TDX_BUS_CITY", "Taipei")
TDX_TIMEOUT_SECONDS = 3

LOCATION_TIME_ADJUSTMENTS = {
    "taipei_main": {},
    "xinyi": {"place_001": 10, "place_002": 4, "place_003": 2, "place_004": -12, "place_005": 8},
    "daan": {"place_001": 6, "place_002": 2, "place_003": -4, "place_004": -2, "place_005": 4},
    "songshan": {"place_001": 8, "place_002": -8, "place_003": 3, "place_004": 2, "place_005": 7},
}

MOOD_LABELS = {
    "relaxing_walk": "relaxing walk",
    "date": "date",
    "solo_quiet": "solo & quiet",
    "photo": "photo hunt",
    "rainy_backup": "rainy day",
    "night_out": "night outing",
}

TDX_STATION_SOURCES = {
    "tra": {
        "label": "TRA",
        "url": "http://127.0.0.1:8765/api/stations",
        "query": {},
    },
    "mrt": {
        "label": "MRT",
        "url": "http://127.0.0.1:8766/api/stations",
        "query": {},
    },
    "bus": {
        "label": "Bus",
        "url": "http://127.0.0.1:8767/api/stations",
        "query": {"city": DEFAULT_BUS_CITY},
    },
}

file_lock = threading.Lock()
station_cache = {}
context_cache = {}


def read_json(path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")
    temp_path.replace(path)


def get_places():
    return read_json(PLACES_PATH, [])


def get_saved_places():
    return read_json(SAVED_PATH, [])


def normalize(value):
    return str(value or "").strip().lower()


def parse_bool(value):
    if value is None:
        return None
    return normalize(value) in ("1", "true", "yes", "y")


def parse_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def filter_places(params):
    places = get_places()
    query = normalize(params.get("q", [""])[0])
    mood = params.get("mood", [""])[0]
    budget = params.get("budget", [""])[0]
    indoor = parse_bool(params.get("indoor", [None])[0])

    results = []
    for place in places:
        if query:
            haystack = normalize(
                " ".join([
                    place.get("name", ""),
                    place.get("category", ""),
                    place.get("address", ""),
                    place.get("description", ""),
                ])
            )
            if query not in haystack:
                continue
        if mood and mood not in place.get("moods", []):
            continue
        if budget and budget != "flexible" and place.get("budget") != budget:
            continue
        if indoor is not None and bool(place.get("indoor")) is not indoor:
            continue
        results.append(place)

    return results


def get_place(place_id):
    return next((place for place in get_places() if place.get("id") == place_id), None)


def travel_time_for(place, location):
    offset = LOCATION_TIME_ADJUSTMENTS.get(location, {}).get(place.get("id"), 0)
    return max(8, parse_int(place.get("travel_time_minutes"), 0) + offset)


def build_reason(place, mood, weather_preference, budget, travel_time):
    mood_label = MOOD_LABELS.get(mood)
    prefix = f"This place fits a {mood_label} mood because it " if mood_label else "This place "
    template = place.get("reasonTemplate", "is a practical fit for your current context.")
    filled = template.replace("${time}", str(travel_time))
    context = []
    if weather_preference == "indoor" and place.get("indoor"):
        context.append("keeps you mostly indoors")
    if weather_preference == "avoid_rain" and (place.get("indoor") or place.get("weather_status") == "any"):
        context.append("has a safer rainy-day fallback")
    if budget == "low" and place.get("budget") == "low":
        context.append("stays budget-friendly")
    return prefix + filled + (f" It also {' and '.join(context)}." if context else "")


def aqi_status_kind(status, aqi_value=None):
    status_text = normalize(status)
    if status_text in ("良好", "good"):
        return "good"
    if status_text in ("普通", "moderate"):
        return "moderate"
    if status_text in ("對敏感族群不健康", "unhealthyforsensitivegroups"):
        return "sensitive"
    if status_text in ("對所有族群不健康", "unhealthy"):
        return "unhealthy"
    if status_text in ("非常不健康", "veryunhealthy"):
        return "very_unhealthy"
    if status_text in ("危害", "hazardous"):
        return "hazardous"
    if aqi_value is not None:
        if aqi_value <= 50:
            return "good"
        if aqi_value <= 100:
            return "moderate"
        if aqi_value <= 150:
            return "sensitive"
        if aqi_value <= 200:
            return "unhealthy"
        if aqi_value <= 300:
            return "very_unhealthy"
        return "hazardous"
    return "unknown"

def weather_status_from_context(context, place):
    comfort = context.get("outdoor_comfort", "")
    if place.get("indoor"):
        return "any"
    if comfort in ("rain_risk", "poor_air_quality", "extreme_uv", "very_high_uv", "hot", "windy"):
        return "watch"
    return "suitable"


def context_for_place(place):
    lat = place.get("lat")
    lon = place.get("lng")
    if lat is None or lon is None:
        return None
    cache_key = f"{round(float(lat), 4)}:{round(float(lon), 4)}"
    now = time.time()
    cached = context_cache.get(cache_key)
    if cached and now - cached["fetched_at"] < 600:
        return cached["data"]
    data = context_for({"lat": [str(lat)], "lon": [str(lon)]})
    context_cache[cache_key] = {"data": data, "fetched_at": now}
    return data


def enrich_place_with_context(place):
    item = dict(place)
    try:
        context = context_for_place(place)
    except Exception as exc:
        item["context_error"] = str(exc)
        return item
    if not context:
        return item

    weather = context.get("weather", {})
    uv = context.get("uv", {})
    air_quality = context.get("air_quality", {})
    aqi_value = air_quality.get("aqi")

    item["context"] = context
    item["weather_summary"] = weather.get("summary") or item.get("weather_summary", "")
    item["weather_status"] = weather_status_from_context(context, item)
    item["outdoor_comfort"] = context.get("outdoor_comfort")
    item["uv_index"] = uv.get("uv_index")
    item["uv_exposure_level"] = uv.get("exposure_level")
    item["aqi_value"] = aqi_value
    item["aqi_status"] = aqi_status_kind(air_quality.get("status"), aqi_value)
    item["aqi_label"] = air_quality.get("status") or item["aqi_status"]
    item["main_pollutant"] = air_quality.get("pollutant")
    return item


def score_places(payload):
    mood = payload.get("mood")
    time_budget = parse_int(payload.get("time"), 120)
    distance = parse_int(payload.get("distance"), 30)
    location = payload.get("location", "taipei_main")
    weather_preference = payload.get("weatherPreference", "any")
    budget = payload.get("budget", "medium")
    limit = parse_int(payload.get("limit"), 4)

    scored = []
    for raw_place in get_places():
        place = enrich_place_with_context(raw_place)
        travel_time = travel_time_for(place, location)
        score = 50
        if mood and mood in place.get("moods", []):
            score += 25
        if travel_time <= distance:
            score += 20
        else:
            score -= 15
        if travel_time <= distance * 0.6:
            score += 5
        if place.get("open_now"):
            score += 10
        if place.get("aqi_status") == "good":
            score += 5
        if place.get("aqi_status") in ("unhealthy", "very_unhealthy", "hazardous"):
            score -= 15
        if place.get("outdoor_comfort") in ("extreme_uv", "poor_air_quality") and not place.get("indoor"):
            score -= 10
        if place.get("outdoor_comfort") == "rain_risk" and not place.get("indoor"):
            score -= 8
        if weather_preference == "indoor" and place.get("indoor"):
            score += 12
        if weather_preference == "indoor" and not place.get("indoor"):
            score -= 6
        if weather_preference == "avoid_rain" and (place.get("indoor") or place.get("weather_status") == "any"):
            score += 10
        if weather_preference == "avoid_rain" and not place.get("indoor") and place.get("weather_status") == "suitable":
            score -= 5
        if budget == "low" and place.get("budget") == "low":
            score += 8
        if budget == "low" and place.get("budget") != "low":
            score -= 4
        if budget == "medium" and place.get("budget") != "flexible":
            score += 4

        score = max(35, min(98, score))
        item = dict(place)
        item["score"] = score
        item["reason"] = build_reason(place, mood, weather_preference, budget, travel_time)
        item["matched_travel_time"] = travel_time
        item["time_fit"] = build_time_fit(time_budget, travel_time)
        scored.append(item)

    scored.sort(key=lambda item: item["score"], reverse=True)
    return {
        "criteria": {
            "mood": mood,
            "time": time_budget,
            "distance": distance,
            "location": location,
            "weatherPreference": weather_preference,
            "budget": budget,
        },
        "results": scored[:limit],
    }


def build_time_fit(time_budget, travel_time):
    outing_time = max(0, time_budget - travel_time * 2)
    if outing_time >= 90:
        return "comfortable"
    if outing_time >= 45:
        return "short_outing"
    return "tight"


def haversine_meters(lat1, lon1, lat2, lon2):
    radius = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def fetch_json(url, params):
    if params:
        url = f"{url}?{urlencode(params)}"
    with urlopen(url, timeout=TDX_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def get_position(item):
    position = item.get("position") or item.get("StationPosition") or item.get("StopPosition") or {}
    lat = parse_float(position.get("lat") or position.get("PositionLat"))
    lon = parse_float(position.get("lon") or position.get("lng") or position.get("PositionLon"))
    if lat is None or lon is None:
        return None
    return {"lat": lat, "lon": lon}


def get_station_items(kind, city=DEFAULT_BUS_CITY):
    source = TDX_STATION_SOURCES[kind]
    cache_key = f"{kind}:{city}"
    now = time.time()
    cached = station_cache.get(cache_key)
    if cached and now - cached["fetched_at"] < 300:
        return cached["items"]

    params = dict(source["query"])
    if kind == "bus":
        params["city"] = city

    items = fetch_json(source["url"], params)
    if not isinstance(items, list):
        raise RuntimeError(f"{source['label']} station API returned unexpected data")
    station_cache[cache_key] = {"items": items, "fetched_at": now}
    return items


def nearby_transit(params):
    lat = parse_float(params.get("lat", [None])[0])
    lon = parse_float(params.get("lon", [None])[0])
    radius = parse_float(params.get("radius", ["800"])[0], 800)
    city = params.get("city", [DEFAULT_BUS_CITY])[0] or DEFAULT_BUS_CITY
    limit = parse_int(params.get("limit", ["8"])[0], 8)
    if lat is None or lon is None:
        raise ValueError("lat and lon are required")

    results = []
    errors = {}
    for kind, source in TDX_STATION_SOURCES.items():
        try:
            for item in get_station_items(kind, city):
                position = get_position(item)
                if not position:
                    continue
                distance = haversine_meters(lat, lon, position["lat"], position["lon"])
                if distance > radius:
                    continue
                results.append({
                    "type": kind,
                    "label": source["label"],
                    "id": item.get("id") or item.get("StationID") or item.get("uid") or item.get("StationUID"),
                    "uid": item.get("uid") or item.get("StationUID"),
                    "name_zh": item.get("name_zh") or item.get("StationName", {}).get("Zh_tw") if isinstance(item.get("StationName"), dict) else item.get("name_zh") or item.get("StationName", ""),
                    "name_en": item.get("name_en") or item.get("StationName", {}).get("En") if isinstance(item.get("StationName"), dict) else item.get("name_en", ""),
                    "address": item.get("address", ""),
                    "position": position,
                    "distance_meters": round(distance),
                    "route_names": item.get("route_names", []),
                    "route_count": item.get("route_count"),
                    "stop_count": item.get("stop_count"),
                })
        except (URLError, TimeoutError, RuntimeError, OSError) as exc:
            errors[kind] = str(exc)

    results.sort(key=lambda item: item["distance_meters"])
    grouped = {}
    for item in results:
        grouped.setdefault(item["type"], []).append(item)

    return {
        "origin": {"lat": lat, "lon": lon},
        "radius_meters": radius,
        "city": city,
        "errors": errors,
        "items": results[:limit * 3],
        "groups": {
            kind: values[:limit]
            for kind, values in grouped.items()
        },
    }


def context_for(params):
    lat = parse_float(params.get("lat", [None])[0])
    lon = parse_float(params.get("lon", [None])[0])
    if lat is None or lon is None:
        raise ValueError("lat and lon are required")
    return get_weather_aqi_context(lat, lon)


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "NextStopsAPI/0.1"

    def send_json(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_error_json(self, message, status=500):
        self.send_json({"error": message}, status=status)

    def read_json_body(self):
        length = parse_int(self.headers.get("Content-Length"), 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        parts = [part for part in parsed.path.split("/") if part]

        try:
            if parsed.path == "/api/health":
                self.send_json({"ok": True, "service": "next-stops-api"})
                return
            if parsed.path == "/api/places":
                self.send_json(filter_places(params))
                return
            if len(parts) == 3 and parts[:2] == ["api", "places"]:
                place = get_place(parts[2])
                if not place:
                    self.send_error_json("Place not found", status=404)
                    return
                self.send_json(place)
                return
            if parsed.path == "/api/saved-places":
                self.send_json(get_saved_places())
                return
            if parsed.path == "/api/nearby-transit":
                self.send_json(nearby_transit(params))
                return
            if parsed.path == "/api/context":
                self.send_json(context_for(params))
                return
        except ValueError as exc:
            self.send_error_json(str(exc), status=400)
            return
        except Exception as exc:
            self.send_error_json(str(exc), status=500)
            return

        self.send_error_json("Not found", status=404)

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            body = self.read_json_body()
            if parsed.path == "/api/recommendations":
                self.send_json(score_places(body))
                return
            if parsed.path == "/api/saved-places":
                item = dict(body)
                if not item.get("id"):
                    self.send_error_json("id is required", status=400)
                    return
                item.setdefault("created_at", datetime.now(timezone.utc).isoformat())
                item.setdefault("note", "")
                with file_lock:
                    saved = [entry for entry in get_saved_places() if entry.get("id") != item["id"]]
                    saved.insert(0, item)
                    write_json(SAVED_PATH, saved)
                self.send_json(item, status=201)
                return
        except json.JSONDecodeError:
            self.send_error_json("Invalid JSON body", status=400)
            return
        except Exception as exc:
            self.send_error_json(str(exc), status=500)
            return

        self.send_error_json("Not found", status=404)

    def do_PATCH(self):
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]
        try:
            body = self.read_json_body()
            if len(parts) == 3 and parts[:2] == ["api", "saved-places"]:
                saved_id = parts[2]
                with file_lock:
                    saved = get_saved_places()
                    for index, item in enumerate(saved):
                        if item.get("id") == saved_id:
                            saved[index] = {**item, **body, "id": saved_id}
                            write_json(SAVED_PATH, saved)
                            self.send_json(saved[index])
                            return
                self.send_error_json("Saved place not found", status=404)
                return
        except json.JSONDecodeError:
            self.send_error_json("Invalid JSON body", status=400)
            return
        except Exception as exc:
            self.send_error_json(str(exc), status=500)
            return

        self.send_error_json("Not found", status=404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) == 3 and parts[:2] == ["api", "saved-places"]:
            saved_id = parts[2]
            with file_lock:
                saved = get_saved_places()
                next_saved = [item for item in saved if item.get("id") != saved_id]
                write_json(SAVED_PATH, next_saved)
            self.send_json({"deleted": len(saved) != len(next_saved), "id": saved_id})
            return

        self.send_error_json("Not found", status=404)

    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {format % args}")


def run():
    server = ThreadingHTTPServer(("127.0.0.1", DEFAULT_PORT), ApiHandler)
    print(f"NEXT STOPS API running at http://127.0.0.1:{DEFAULT_PORT}")
    server.serve_forever()


if __name__ == "__main__":
    run()
