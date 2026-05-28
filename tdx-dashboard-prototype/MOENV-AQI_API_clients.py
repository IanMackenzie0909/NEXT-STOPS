import json
import math
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parent

MOENV_AQI_URL = "https://data.moenv.gov.tw/api/v2/aqx_p_432"
DEFAULT_TIMEOUT_SECONDS = 8


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


def parse_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_number(value):
    if value in (None, "", "-", "X", "x", "-99", "-99.0", "-999", "-999.0"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number in (-99, -999):
        return None
    return number


def normalize_text(value):
    text = str(value or "").strip()
    if text in ("", "-", "X", "x", "-99", "-99.0", "-999", "-999.0"):
        return ""
    return text


def haversine_meters(lat1, lon1, lat2, lon2):
    radius = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def aqi_coordinates(item):
    lat = normalize_number(item.get("latitude") or item.get("Latitude") or item.get("lat"))
    lon = normalize_number(item.get("longitude") or item.get("Longitude") or item.get("lon") or item.get("lng"))
    if lat is None or lon is None:
        return None
    return {"lat": lat, "lon": lon}


def nearest_item(items, lat, lon, coordinate_getter):
    best = None
    for item in items:
        position = coordinate_getter(item)
        if not position:
            continue
        distance = haversine_meters(lat, lon, position["lat"], position["lon"])
        if best is None or distance < best["distance_meters"]:
            best = {
                "item": item,
                "position": position,
                "distance_meters": round(distance),
            }
    return best


def first_usable_aqi_record(records):
    for item in records:
        if parse_int(item.get("aqi") or item.get("AQI"), None) is not None:
            return item
    return records[0] if records else None


def aqi_status_kind(status, aqi_value=None):
    status_text = normalize_text(status).replace(" ", "").lower()
    if status_text in ("good", "良好"):
        return "good"
    if status_text in ("moderate", "普通"):
        return "moderate"
    if status_text in ("unhealthyforsensitivegroups", "對敏感族群不健康"):
        return "sensitive"
    if status_text in ("unhealthy", "對所有族群不健康"):
        return "unhealthy"
    if status_text in ("veryunhealthy", "非常不健康"):
        return "very_unhealthy"
    if status_text in ("hazardous", "危害"):
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


class MOENVAQIClient:
    def __init__(self, api_key=None, timeout_seconds=DEFAULT_TIMEOUT_SECONDS):
        self.api_key = api_key or os.getenv("AQI_API_KEY") or os.getenv("MOENV_API_KEY") or ""
        self.timeout_seconds = timeout_seconds

    def fetch_json(self, url, params):
        if params:
            url = f"{url}?{urlencode(params)}"
        with urlopen(url, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def records(self, limit=1000):
        if not self.api_key:
            raise RuntimeError("AQI_API_KEY or MOENV_API_KEY is not configured")
        payload = self.fetch_json(MOENV_AQI_URL, {
            "api_key": self.api_key,
            "format": "json",
            "limit": limit,
        })
        records = payload.get("records", []) if isinstance(payload, dict) else payload
        if isinstance(records, dict):
            records = records.get("records", []) or records.get("data", []) or []
        if not isinstance(records, list):
            raise RuntimeError("MOENV AQI returned unexpected records format")
        return records

    def nearest_aqi(self, lat, lon):
        records = self.records()
        nearest = nearest_item(records, lat, lon, aqi_coordinates)
        item = nearest["item"] if nearest else first_usable_aqi_record(records)
        if not item:
            raise RuntimeError("MOENV AQI returned no usable record")

        aqi_value = parse_int(item.get("aqi") or item.get("AQI"), None)
        status = normalize_text(item.get("status") or item.get("Status") or "")
        return {
            "site": normalize_text(item.get("sitename") or item.get("SiteName") or ""),
            "county": normalize_text(item.get("county") or item.get("County") or ""),
            "station_distance_meters": nearest["distance_meters"] if nearest else None,
            "aqi": aqi_value,
            "status": status,
            "status_kind": aqi_status_kind(status, aqi_value),
            "pollutant": normalize_text(item.get("pollutant") or item.get("Pollutant") or ""),
            "pm25": normalize_number(item.get("pm2.5") or item.get("PM2.5") or item.get("pm2.5_avg") or item.get("PM2.5_AVG")),
            "pm10": normalize_number(item.get("pm10") or item.get("PM10") or item.get("pm10_avg") or item.get("PM10_AVG")),
            "wind_speed_mps": normalize_number(item.get("wind_speed") or item.get("WIND_SPEED")),
            "wind_direction_degrees": normalize_number(item.get("wind_direc") or item.get("WIND_DIREC")),
            "publish_time": normalize_text(item.get("publishtime") or item.get("PublishTime") or ""),
            "source": "MOENV Open Data",
        }

    def context(self, lat, lon):
        return {
            "location": {"lat": lat, "lon": lon},
            "air_quality": self.nearest_aqi(lat, lon),
            "source_status": {
                "mode": "external",
                "errors": {},
            },
        }


def get_aqi(lat, lon):
    return MOENVAQIClient().nearest_aqi(lat, lon)


def get_context(lat, lon):
    return MOENVAQIClient().context(lat, lon)


if __name__ == "__main__":
    sample_lat = parse_float(os.getenv("NEXT_STOPS_SAMPLE_LAT"), 25.044)
    sample_lon = parse_float(os.getenv("NEXT_STOPS_SAMPLE_LON"), 121.5294)
    print(json.dumps(get_context(sample_lat, sample_lon), ensure_ascii=False, indent=2))
