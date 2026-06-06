import json
import math
import os
import ssl
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parent

MOENV_AQI_URL = "https://data.moenv.gov.tw/api/v2/aqx_p_432"
DEFAULT_TIMEOUT_SECONDS = 8
DEFAULT_METRO_TAIPEI_AQI = {
    "site": "大台北代表值",
    "county": "臺北市 / 新北市 / 基隆市",
    "station_distance_meters": None,
    "aqi": 65,
    "status": "普通",
    "status_kind": "moderate",
    "pollutant": "",
    "pm25": None,
    "pm10": None,
    "wind_speed_mps": None,
    "wind_direction_degrees": None,
    "publish_time": "",
    "source": "prototype metro Taipei fallback",
    "fallback_scope": "metro_taipei_default",
    "station_count": 0,
}


def load_root_env():
    env_path = ROOT.parent / ".env" # ROOT.parent = 專案根目錄 NEXT-STOPS/
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_root_env()


def create_ssl_context():
    context = ssl.create_default_context()
    if hasattr(ssl, "VERIFY_X509_STRICT"):
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context


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


def county_name(item):
    return normalize_text(item.get("county") or item.get("County") or "")


def metro_taipei_aqi(records):
    metro_counties = {"臺北市", "台北市", "新北市", "基隆市"}
    usable = []
    for item in records:
        if county_name(item) not in metro_counties:
            continue
        aqi_value = parse_int(item.get("aqi") or item.get("AQI"), None)
        if aqi_value is None:
            continue
        usable.append((item, aqi_value))
    if not usable:
        return None

    average = round(sum(value for _, value in usable) / len(usable))
    status_kind = aqi_status_kind("", average)
    status_labels = {
        "good": "良好",
        "moderate": "普通",
        "sensitive": "對敏感族群不健康",
        "unhealthy": "對所有族群不健康",
        "very_unhealthy": "非常不健康",
        "hazardous": "危害",
    }
    pm25_values = [normalize_number(item.get("pm2.5") or item.get("PM2.5") or item.get("pm2.5_avg") or item.get("PM2.5_AVG")) for item, _ in usable]
    pm10_values = [normalize_number(item.get("pm10") or item.get("PM10") or item.get("pm10_avg") or item.get("PM10_AVG")) for item, _ in usable]
    wind_values = [normalize_number(item.get("wind_speed") or item.get("WIND_SPEED")) for item, _ in usable]
    return {
        "site": "大台北平均",
        "county": "臺北市 / 新北市 / 基隆市",
        "station_distance_meters": None,
        "aqi": average,
        "status": status_labels.get(status_kind, "待確認"),
        "status_kind": status_kind,
        "pollutant": "",
        "pm25": average_number([value for value in pm25_values if value is not None]),
        "pm10": average_number([value for value in pm10_values if value is not None]),
        "wind_speed_mps": average_number([value for value in wind_values if value is not None]),
        "wind_direction_degrees": None,
        "publish_time": normalize_text(usable[0][0].get("publishtime") or usable[0][0].get("PublishTime") or ""),
        "source": "MOENV Open Data",
        "fallback_scope": "metro_taipei",
        "station_count": len(usable),
    }


def average_number(values):
    if not values:
        return None
    return round(sum(values) / len(values), 1)


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
        self.ssl_context = create_ssl_context()

    def fetch_json(self, url, params):
        if params:
            url = f"{url}?{urlencode(params)}"
        with urlopen(url, timeout=self.timeout_seconds, context=self.ssl_context) as response:
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
        try:
            records = self.records()
        except Exception:
            return dict(DEFAULT_METRO_TAIPEI_AQI)
        nearest = nearest_item(records, lat, lon, aqi_coordinates)
        if nearest is None:
            metro = metro_taipei_aqi(records)
            if metro:
                return metro
        item = nearest["item"] if nearest else first_usable_aqi_record(records)
        if not item:
            raise RuntimeError("MOENV AQI returned no usable record")

        aqi_value = parse_int(item.get("aqi") or item.get("AQI"), None)
        if aqi_value is None:
            metro = metro_taipei_aqi(records)
            if metro:
                return metro
            item = first_usable_aqi_record(records)
            aqi_value = parse_int(item.get("aqi") or item.get("AQI"), None) if item else None
        if aqi_value is None:
            raise RuntimeError("MOENV AQI returned no usable AQI value")
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

    def metro_taipei_aqi(self):
        try:
            records = self.records()
        except Exception:
            return dict(DEFAULT_METRO_TAIPEI_AQI)
        metro = metro_taipei_aqi(records)
        if not metro:
            raise RuntimeError("MOENV AQI returned no usable metro Taipei record")
        return metro

    def aqi(self, lat, lon):
        return self.nearest_aqi(lat, lon)

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
