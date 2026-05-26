import importlib.util
import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests


ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "static-attraction"
CLIENT_MODULE_PATH = "Attraction_OpenAPI-clients.py"

spec = importlib.util.spec_from_file_location("attraction_openapi_clients", ROOT / CLIENT_MODULE_PATH)
attraction_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(attraction_module)

client = attraction_module.TaipeiAttractionClient()
cache = {
    "districts": [],
}


def get_districts(force_refresh=False):
    if cache["districts"] and not force_refresh:
        return cache["districts"]
    cache["districts"] = client.get_districts()
    return cache["districts"]


def get_summary(districts):
    all_attractions = [
        attraction
        for district in districts
        for attraction in district.get("attractions", [])
    ]
    return {
        "district_count": len(districts),
        "attraction_count": len(all_attractions),
        "theme_count": len({district.get("theme", "") for district in districts if district.get("theme")}),
        "latest_import": max((district.get("import_time", "") for district in districts), default=""),
    }


class AttractionHandler(SimpleHTTPRequestHandler):
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

        if parsed.path == "/api/maps-config":
            self.send_json({
                "api_key": os.getenv("GOOGLE_MAPS_BROWSER_KEY") or os.getenv("GOOGLE_MAPS_API_KEY") or "your_google_maps_api_key",
                "access_token": os.getenv("MAPBOX_ACCESS_TOKEN") or "Your_Mapbox_Access_Token",
            })
            return

        if parsed.path == "/api/attractions":
            params = parse_qs(parsed.query)
            query = params.get("q", [""])[0]
            refresh = params.get("refresh", [""])[0] == "1"
            try:
                districts = get_districts(force_refresh=refresh)
                filtered = attraction_module.search_districts(districts, query)
                self.send_json({
                    "source": attraction_module.DATASET_URL,
                    "summary": get_summary(filtered),
                    "districts": filtered,
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


def run():
    port = int(os.getenv("PORT", "8768"))
    server = ThreadingHTTPServer(("127.0.0.1", port), AttractionHandler)
    print(f"Taipei attraction dashboard running at http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
