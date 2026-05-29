import importlib.util
import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "static-weather-aqi"
CLIENT_MODULE_PATH = "Weather-AQI_API_clients.py"

spec = importlib.util.spec_from_file_location("weather_aqi_api_clients", ROOT / CLIENT_MODULE_PATH)
weather_aqi_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(weather_aqi_module)

client = weather_aqi_module.WeatherAQIClient()

SAMPLE_LOCATIONS = [
    {"name": "臺北車站", "lat": 25.0478, "lon": 121.5170},
    {"name": "信義區市府", "lat": 25.0375, "lon": 121.5637},
    {"name": "士林夜市", "lat": 25.0881, "lon": 121.5240},
    {"name": "北投溫泉", "lat": 25.1368, "lon": 121.5064},
    {"name": "南港展覽館", "lat": 25.0553, "lon": 121.6175},
]


def parse_float_param(params, name):
    value = params.get(name, [""])[0]
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Missing or invalid {name}")


class WeatherAQIHandler(SimpleHTTPRequestHandler):
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

        if parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        if parsed.path == "/api/sample-locations":
            self.send_json({"locations": SAMPLE_LOCATIONS})
            return

        if parsed.path == "/api/weather-aqi":
            params = parse_qs(parsed.query)
            try:
                lat = parse_float_param(params, "lat")
                lon = parse_float_param(params, "lon")
                real_only = params.get("real", [""])[0] == "1"
                data = client.real_context(lat, lon) if real_only else client.context(lat, lon)
                self.send_json(data)
            except ValueError as exc:
                self.send_error_json(str(exc), status=400)
            except Exception as exc:
                self.send_error_json(str(exc))
            return

        if parsed.path == "/":
            self.path = "/index.html"

        return super().do_GET()


def run():
    port = int(os.getenv("PORT", "8771"))
    server = ThreadingHTTPServer(("127.0.0.1", port), WeatherAQIHandler)
    print(f"Weather/AQI test dashboard running at http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
