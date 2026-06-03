import importlib.util
import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests


ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "static-attraction-mapbox"
CLIENT_MODULE_PATH = "Attraction_OpenAPI-clients.py"

GOOGLE_GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"
GOOGLE_DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"
DEFAULT_MAPBOX_TOKEN = "your_mapbox_access_token"  # Replace with your Mapbox token or set MAPBOX_ACCESS_TOKEN env variable

TRAVEL_MODES = {
    "TRANSIT": "transit",
    "WALKING": "walking",
    "DRIVING": "driving",
}

spec = importlib.util.spec_from_file_location("attraction_openapi_clients", ROOT / CLIENT_MODULE_PATH)
attraction_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(attraction_module)

client = attraction_module.TaipeiAttractionClient()
cache = {
    "places": [],
}


class GoogleMapsBackendError(Exception):
    pass


def get_google_key():
    return (
        os.getenv("GOOGLE_MAPS_SERVER_KEY")
        or os.getenv("GOOGLE_MAPS_API_KEY")
        or os.getenv("GOOGLE_MAPS_BROWSER_KEY")
        or "your_google_maps_api_key"  # Replace with your Google Maps Platform API key.
    )


def get_mapbox_token():
    return os.getenv("MAPBOX_ACCESS_TOKEN") or DEFAULT_MAPBOX_TOKEN


def get_places(force_refresh=False):
    if cache["places"] and not force_refresh:
        return cache["places"]
    cache["places"] = client.get_places()
    return cache["places"]


def get_summary(places):
    return {
        "place_count": len(places),
        "attraction_count": len([place for place in places if place.get("type") == "attraction"]),
        "event_count": len([place for place in places if place.get("type") == "event"]),
        "district_count": len({place.get("district", "") for place in places if place.get("district")}),
        "category_count": len({place.get("category", "") for place in places if place.get("category")}),
        "latest_modified": max((place.get("modified", "") for place in places), default=""),
    }


def decode_polyline(polyline):
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


def google_request(url, params):
    key = get_google_key()
    if not key:
        raise GoogleMapsBackendError("Missing GOOGLE_MAPS_SERVER_KEY or GOOGLE_MAPS_API_KEY")

    response = requests.get(url, params={**params, "key": key}, timeout=10)
    response.raise_for_status()
    payload = response.json()
    status = payload.get("status")
    if status != "OK":
        message = payload.get("error_message") or status or "Unknown Google Maps error"
        raise GoogleMapsBackendError(message)
    return payload


def geocode_destination(query):
    payload = google_request(
        GOOGLE_GEOCODING_URL,
        {
            "address": query,
            "region": "tw",
            "language": "zh-TW",
        },
    )
    result = payload["results"][0]
    location = result["geometry"]["location"]
    return {
        "address": result.get("formatted_address", ""),
        "place_id": result.get("place_id", ""),
        "location": {
            "lat": location["lat"],
            "lng": location["lng"],
        },
    }


def valid_coordinate_pair(value):
    if not isinstance(value, dict):
        return False
    try:
        float(value.get("lat"))
        float(value.get("lng"))
        return True
    except (TypeError, ValueError):
        return False


def calculate_google_route(origin, destination_query, mode, destination_location=None):
    if valid_coordinate_pair(destination_location):
        destination = {
            "address": destination_location.get("address") or destination_query,
            "place_id": "",
            "location": {
                "lat": float(destination_location["lat"]),
                "lng": float(destination_location["lng"]),
            },
        }
        directions_destination = f"{destination['location']['lat']},{destination['location']['lng']}"
    else:
        destination = geocode_destination(destination_query)
        directions_destination = (
            f"place_id:{destination['place_id']}"
            if destination["place_id"]
            else destination_query
        )

    google_mode = TRAVEL_MODES.get(mode, "transit")
    route_payload = google_request(
        GOOGLE_DIRECTIONS_URL,
        {
            "origin": f"{origin['lat']},{origin['lng']}",
            "destination": directions_destination,
            "mode": google_mode,
            "region": "tw",
            "language": "zh-TW",
        },
    )

    route = route_payload["routes"][0]
    leg = route["legs"][0]
    coordinates = decode_polyline(route["overview_polyline"]["points"])
    return {
        "provider": "google",
        "mode": mode,
        "origin": {
            "lat": origin["lat"],
            "lng": origin["lng"],
            "address": leg.get("start_address", ""),
        },
        "destination": {
            "lat": destination["location"]["lat"],
            "lng": destination["location"]["lng"],
            "address": leg.get("end_address") or destination["address"],
            "query": destination_query,
            "place_id": destination["place_id"],
        },
        "distance_text": leg.get("distance", {}).get("text", ""),
        "distance_meters": leg.get("distance", {}).get("value"),
        "duration_text": leg.get("duration", {}).get("text", ""),
        "duration_seconds": leg.get("duration", {}).get("value"),
        "summary": route.get("summary", ""),
        "geometry": {
            "type": "LineString",
            "coordinates": coordinates,
        },
    }


class AttractionMapboxHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_ROOT), **kwargs)

    def read_json_body(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            return {}
        return json.loads(self.rfile.read(content_length).decode("utf-8"))

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

        if parsed.path == "/api/mapbox-config":
            self.send_json({"access_token": get_mapbox_token()})
            return

        if parsed.path == "/api/attractions":
            params = parse_qs(parsed.query)
            query = params.get("q", [""])[0]
            refresh = params.get("refresh", [""])[0] == "1"
            try:
                places = get_places(force_refresh=refresh)
                filtered = attraction_module.search_places(places, query)
                self.send_json({
                    "source": {
                        "attractions": attraction_module.ATTRACTIONS_URL,
                        "events": attraction_module.EVENTS_URL,
                    },
                    "summary": get_summary(filtered),
                    "places": filtered,
                    "districts": attraction_module.group_places_by_district(filtered),
                })
            except attraction_module.TaipeiOpenDataError as exc:
                self.send_error_json(str(exc), status=429)
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else 500
                self.send_error_json(f"Taipei Open Data request failed: {exc}", status=status)
            except Exception as exc:
                self.send_error_json(str(exc))
            return

        if parsed.path == "/":
            self.path = "/index.html"

        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/route":
            try:
                payload = self.read_json_body()
                origin = payload.get("origin") or {}
                destination_query = payload.get("destination_query", "").strip()
                destination_location = payload.get("destination") or {}
                mode = payload.get("mode", "TRANSIT")

                if not origin.get("lat") or not origin.get("lng"):
                    self.send_error_json("origin.lat and origin.lng are required", status=400)
                    return
                if not destination_query and not valid_coordinate_pair(destination_location):
                    self.send_error_json("destination_query or destination lat/lng is required", status=400)
                    return

                route = calculate_google_route(origin, destination_query, mode, destination_location)
                self.send_json(route)
            except GoogleMapsBackendError as exc:
                self.send_error_json(str(exc), status=502)
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else 500
                self.send_error_json(f"Google Maps request failed: {exc}", status=status)
            except Exception as exc:
                self.send_error_json(str(exc))
            return

        self.send_error_json("Not found", status=404)


def run():
    port = int(os.getenv("PORT", "8769"))
    server = ThreadingHTTPServer(("127.0.0.1", port), AttractionMapboxHandler)
    print(f"Taipei attraction Mapbox route planner running at http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
