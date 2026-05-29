import json
import math
import os
import ssl
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parent

CWA_DATASTORE_BASE = "https://opendata.cwa.gov.tw/api/v1/rest/datastore"
CWA_CURRENT_WEATHER_DATASET = "O-A0001-001"
CWA_10MIN_RAIN_DATASET = "O-A0003-001"
CWA_UV_DATASET = "O-A0005-001"
CWA_36H_FORECAST_DATASET = "F-C0032-001"
CWA_TAIPEI_TOWNSHIP_FORECAST_DATASET = "F-D0047-061"
CWA_TOWNSHIP_ELEMENT_NAMES = "溫度,相對濕度,3小時降雨機率,風速,天氣現象"
DEFAULT_TIMEOUT_SECONDS = 8
DEFAULT_FORECAST_LOCATION = "臺北市"


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


def normalize(value):
    return str(value or "").strip().lower()


def parse_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_list(value):
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def deep_get(data, paths, default=None):
    for path in paths:
        current = data
        ok = True
        for part in path:
            if isinstance(part, int):
                if not isinstance(current, list) or len(current) <= part:
                    ok = False
                    break
                current = current[part]
            elif isinstance(current, dict) and part in current:
                current = current[part]
            else:
                ok = False
                break
        if ok and current not in (None, ""):
            return current
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


def flatten_pairs(value, prefix=""):
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield from flatten_pairs(item, path)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            path = f"{prefix}[{index}]"
            yield from flatten_pairs(item, path)
        return
    yield prefix, value


def find_number_by_keywords(data, include_keywords, exclude_keywords=None):
    exclude_keywords = exclude_keywords or []
    for path, value in flatten_pairs(data):
        haystack = normalize(path).replace("_", "").replace("-", "")
        if any(keyword in haystack for keyword in include_keywords) and not any(keyword in haystack for keyword in exclude_keywords):
            number = normalize_number(value)
            if number is not None:
                return number
    return None


def find_text_by_keywords(data, include_keywords):
    for path, value in flatten_pairs(data):
        haystack = normalize(path).replace("_", "").replace("-", "")
        if any(keyword in haystack for keyword in include_keywords):
            text = normalize_text(value)
            if text and normalize_number(text) is None:
                return text
    return ""


def haversine_meters(lat1, lon1, lat2, lon2):
    radius = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def uv_exposure_level(uv_index):
    if uv_index is None:
        return ""
    if uv_index <= 2:
        return "low"
    if uv_index <= 5:
        return "moderate"
    if uv_index <= 7:
        return "high"
    if uv_index <= 10:
        return "very_high"
    return "extreme"


def station_coordinates(item):
    lat = deep_get(item, [
        ("GeoInfo", "Coordinates", 0, "StationLatitude"),
        ("GeoInfo", "Coordinates", 0, "Latitude"),
        ("GeoInfo", "StationLatitude"),
        ("GeoInfo", "Coordinates", "StationLatitude"),
        ("GeoInfo", "Coordinates", "Latitude"),
        ("Latitude",),
        ("StationLatitude",),
        ("lat",),
    ])
    lon = deep_get(item, [
        ("GeoInfo", "Coordinates", 0, "StationLongitude"),
        ("GeoInfo", "Coordinates", 0, "Longitude"),
        ("GeoInfo", "StationLongitude"),
        ("GeoInfo", "Coordinates", "StationLongitude"),
        ("GeoInfo", "Coordinates", "Longitude"),
        ("Longitude",),
        ("StationLongitude",),
        ("lon",),
        ("lng",),
    ])
    lat = normalize_number(lat)
    lon = normalize_number(lon)
    if lat is None or lon is None:
        return None
    return {"lat": lat, "lon": lon}


def township_coordinates(item):
    lat = normalize_number(item.get("Latitude") or item.get("latitude") or item.get("lat"))
    lon = normalize_number(item.get("Longitude") or item.get("longitude") or item.get("lon") or item.get("lng"))
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


def cwa_uv_records(payload):
    weather_element = deep_get(payload, [
        ("records", "weatherElement"),
        ("records", "WeatherElement"),
    ], {})
    locations = (
        weather_element.get("location")
        or weather_element.get("Location")
        or weather_element.get("locations")
        or []
    ) if isinstance(weather_element, dict) else []
    date = weather_element.get("Date", "") if isinstance(weather_element, dict) else ""
    element_name = weather_element.get("elementName", "") if isinstance(weather_element, dict) else ""

    records = []
    for item in as_list(locations):
        if not isinstance(item, dict):
            continue
        record = dict(item)
        record.setdefault("Date", date)
        record.setdefault("elementName", element_name)
        records.append(record)
    return records


def cwa_township_records(payload):
    records = payload.get("records", {}) if isinstance(payload, dict) else {}
    groups = records.get("Locations") or records.get("locations") or []
    result = []
    for group in as_list(groups):
        if not isinstance(group, dict):
            continue
        group_name = group.get("LocationsName") or group.get("locationsName") or group.get("DatasetDescription") or ""
        for item in as_list(group.get("Location") or group.get("location")):
            if not isinstance(item, dict):
                continue
            record = dict(item)
            record.setdefault("locationsName", group_name)
            result.append(record)
    return result


def cwa_station_name(item):
    return normalize_text(
        item.get("StationName")
        or item.get("locationName")
        or item.get("LocationName")
        or item.get("StationId")
        or item.get("StationID")
        or ""
    )


def cwa_township_name(item):
    return normalize_text(item.get("LocationName") or item.get("locationName") or item.get("Geocode") or "")


def cwa_weather_element(item):
    element = item.get("WeatherElement") or item.get("weatherElement") or {}
    if isinstance(element, dict):
        return element
    result = {}
    for entry in as_list(element):
        name = entry.get("elementName") or entry.get("ElementName")
        value = entry.get("elementValue") or entry.get("ElementValue")
        if isinstance(value, list):
            value = deep_get(value[0], [("value",), ("Value",)], value[0])
        elif isinstance(value, dict):
            value = deep_get(value, [("value",), ("Value",)], value)
        if name:
            result[name] = value
    return result


def cwa_forecast_elements(item):
    elements = item.get("WeatherElement") or item.get("weatherElement") or []
    return as_list(elements)


def parse_cwa_datetime(value):
    text = normalize_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def select_forecast_time(times, now=None):
    now = now or datetime.now(timezone.utc)
    future = None
    latest_past = None
    first_usable = None
    for item in as_list(times):
        if not isinstance(item, dict):
            continue
        ref_time = parse_cwa_datetime(item.get("DataTime") or item.get("StartTime") or item.get("startTime"))
        if not ref_time:
            continue
        if first_usable is None:
            first_usable = (ref_time, item)
        if ref_time >= now and (future is None or ref_time < future[0]):
            future = (ref_time, item)
        if ref_time <= now and (latest_past is None or ref_time > latest_past[0]):
            latest_past = (ref_time, item)
    selected = future or latest_past or first_usable
    return selected[1] if selected else {}


def first_forecast_value(time_item):
    value = deep_get(time_item, [
        ("ElementValue", 0),
        ("elementValue", 0),
        ("ElementValue",),
        ("elementValue",),
    ], {})
    if isinstance(value, dict):
        return value
    return {"value": value}


def first_usable_uv_record(records):
    for item in records:
        element = cwa_weather_element(item)
        uv_value = (
            normalize_number(
                element.get("UVIndex")
                or element.get("UVI")
                or item.get("UVIndex")
                or item.get("UVI")
                or item.get("UV")
            )
            or find_number_by_keywords(item, ["uvindex", "uvi", "uv"], ["longitude", "latitude"])
        )
        if uv_value is not None:
            return item
    return records[0] if records else None


def uv_record_by_station_id(records, station_id):
    station_id = normalize_text(station_id)
    if not station_id:
        return None
    for item in records:
        item_station_id = normalize_text(item.get("StationID") or item.get("StationId") or item.get("stationID"))
        if item_station_id != station_id:
            continue
        uv_value = (
            normalize_number(item.get("UVIndex") or item.get("UVI") or item.get("UV"))
            or find_number_by_keywords(item, ["uvindex", "uvi", "uv"], ["longitude", "latitude"])
        )
        if uv_value is not None:
            return item
    return None


class CWAWeatherClient:
    def __init__(self, api_key=None, timeout_seconds=DEFAULT_TIMEOUT_SECONDS, forecast_location=None):
        self.api_key = api_key or os.getenv("CWA_API_KEY") or os.getenv("WEATHER_API_KEY") or ""
        self.timeout_seconds = timeout_seconds
        self.forecast_location = forecast_location or os.getenv("CWA_FORECAST_LOCATION", DEFAULT_FORECAST_LOCATION)
        self.ssl_context = create_ssl_context()

    def fetch_json(self, url, params):
        if params:
            url = f"{url}?{urlencode(params)}"
        with urlopen(url, timeout=self.timeout_seconds, context=self.ssl_context) as response:
            return json.loads(response.read().decode("utf-8"))

    def records(self, dataset, extra_params=None):
        if not self.api_key:
            raise RuntimeError("CWA_API_KEY or WEATHER_API_KEY is not configured")
        params = {
            "Authorization": self.api_key,
            "format": "JSON",
        }
        if extra_params:
            params.update(extra_params)
        payload = self.fetch_json(f"{CWA_DATASTORE_BASE}/{dataset}", params)
        if dataset == CWA_UV_DATASET:
            return cwa_uv_records(payload)
        if dataset == CWA_TAIPEI_TOWNSHIP_FORECAST_DATASET:
            return cwa_township_records(payload)
        records = payload.get("records", {})
        if isinstance(records, list):
            return records
        return (
            records.get("Station")
            or records.get("station")
            or records.get("location")
            or records.get("Location")
            or []
        )

    def current_weather(self, lat, lon):
        records = self.records(CWA_CURRENT_WEATHER_DATASET)
        nearest = nearest_item(records, lat, lon, station_coordinates)
        if not nearest:
            raise RuntimeError("CWA current weather returned no station with coordinates")
        item = nearest["item"]
        element = cwa_weather_element(item)
        weather = normalize_text(
            element.get("Weather")
            or element.get("weather")
            or element.get("WeatherDescription")
            or ""
        )
        return {
            "station": cwa_station_name(item),
            "station_id": item.get("StationID") or item.get("StationId") or item.get("stationID") or "",
            "station_distance_meters": nearest["distance_meters"],
            "observation_time": deep_get(item, [
                ("ObsTime", "DateTime"),
                ("ObsTime", "obsTime"),
                ("obsTime",),
                ("time", "obsTime"),
            ], ""),
            "weather": weather,
            "temperature_c": normalize_number(element.get("AirTemperature") or element.get("TEMP") or element.get("Temperature")),
            "relative_humidity": normalize_number(element.get("RelativeHumidity") or element.get("HUMD")),
            "wind_speed_mps": normalize_number(element.get("WindSpeed") or element.get("WDSD")),
            "wind_direction_degrees": normalize_number(element.get("WindDirection") or element.get("WDIR")),
            "pressure_hpa": normalize_number(element.get("AirPressure") or element.get("PRES")),
        }

    def rainfall(self, lat, lon):
        records = self.records(CWA_10MIN_RAIN_DATASET)
        nearest = nearest_item(records, lat, lon, station_coordinates)
        if not nearest:
            raise RuntimeError("CWA rainfall returned no station with coordinates")
        item = nearest["item"]
        rainfall = item.get("RainfallElement") or item.get("rainfallElement") or {}
        return {
            "station": cwa_station_name(item),
            "station_distance_meters": nearest["distance_meters"],
            "precipitation_10min_mm": normalize_number(deep_get(rainfall, [
                ("Past10Min", "Precipitation"),
                ("past10Min", "precipitation"),
                ("Past10Min",),
            ])),
            "precipitation_now_mm": normalize_number(deep_get(rainfall, [
                ("Now", "Precipitation"),
                ("now", "precipitation"),
                ("Now",),
            ])),
            "precipitation_1hr_mm": normalize_number(deep_get(rainfall, [
                ("Past1hr", "Precipitation"),
                ("Past1Hr", "Precipitation"),
                ("past1hr", "precipitation"),
                ("Past1hr",),
            ])),
        }

    def uv(self, lat, lon, station_id=""):
        records = self.records(CWA_UV_DATASET)
        nearest = nearest_item(records, lat, lon, station_coordinates)
        item = uv_record_by_station_id(records, station_id) if station_id else None
        if not item:
            item = nearest["item"] if nearest else first_usable_uv_record(records)
        if not item:
            raise RuntimeError("CWA UV returned no usable record")
        element = cwa_weather_element(item)
        uv_index = (
            normalize_number(
                element.get("UVIndex")
                or element.get("UVI")
                or item.get("UVIndex")
                or item.get("UVI")
                or item.get("UV")
            )
            or find_number_by_keywords(item, ["uvindex", "uvi", "uv"], ["longitude", "latitude"])
        )
        exposure_level = (
            normalize_text(
                element.get("UVExposureLevel")
                or element.get("ExposureLevel")
                or item.get("UVExposureLevel")
                or item.get("ExposureLevel")
                or ""
            )
            or find_text_by_keywords(item, ["exposure", "level"])
            or uv_exposure_level(uv_index)
        )
        return {
            "station": cwa_station_name(item),
            "station_id": item.get("StationID") or item.get("StationId") or item.get("stationID") or "",
            "station_distance_meters": nearest["distance_meters"] if nearest else None,
            "uv_index": uv_index,
            "exposure_level": exposure_level,
            "observation_time": deep_get(item, [
                ("ObsTime", "DateTime"),
                ("obsTime",),
                ("time", "obsTime"),
                ("Date",),
            ], ""),
        }

    def forecast(self, location_name=None):
        target_location = location_name or self.forecast_location
        records = self.records(CWA_36H_FORECAST_DATASET, {"locationName": target_location})
        location = records[0] if records else {}
        elements = location.get("weatherElement", []) or location.get("WeatherElement", [])
        result = {
            "location": location.get("locationName") or target_location,
            "rain_probability": None,
            "weather": "",
            "min_temperature_c": None,
            "max_temperature_c": None,
            "start_time": "",
            "end_time": "",
        }
        for element in elements:
            name = element.get("elementName")
            first_time = as_list(element.get("time"))[0] if as_list(element.get("time")) else {}
            value = deep_get(first_time, [
                ("parameter", "parameterName"),
                ("elementValue", 0, "value"),
                ("elementValue", "value"),
            ])
            if not result["start_time"]:
                result["start_time"] = first_time.get("startTime", "")
                result["end_time"] = first_time.get("endTime", "")
            if name == "PoP":
                pop = normalize_number(value)
                result["rain_probability"] = pop / 100 if pop is not None else None
            elif name == "Wx":
                result["weather"] = normalize_text(value)
            elif name == "MinT":
                result["min_temperature_c"] = normalize_number(value)
            elif name == "MaxT":
                result["max_temperature_c"] = normalize_number(value)
        return result

    def township_forecast(self, lat, lon):
        records = self.records(CWA_TAIPEI_TOWNSHIP_FORECAST_DATASET, {
            "ElementName": CWA_TOWNSHIP_ELEMENT_NAMES,
        })
        nearest = nearest_item(records, lat, lon, township_coordinates)
        if not nearest:
            raise RuntimeError("CWA township forecast returned no location with coordinates")

        item = nearest["item"]
        result = {
            "location": cwa_township_name(item),
            "geocode": item.get("Geocode") or item.get("geocode") or "",
            "location_distance_meters": nearest["distance_meters"],
            "weather": "",
            "temperature_c": None,
            "relative_humidity": None,
            "rain_probability": None,
            "wind_speed_mps": None,
            "data_time": "",
            "start_time": "",
            "end_time": "",
            "source": "CWA township forecast",
        }

        for element in cwa_forecast_elements(item):
            time_item = select_forecast_time(element.get("Time") or element.get("time"))
            if not time_item:
                continue
            if not result["data_time"]:
                result["data_time"] = time_item.get("DataTime", "") or time_item.get("dataTime", "")
                result["start_time"] = time_item.get("StartTime", "") or time_item.get("startTime", "")
                result["end_time"] = time_item.get("EndTime", "") or time_item.get("endTime", "")

            value = first_forecast_value(time_item)
            if "Temperature" in value:
                result["temperature_c"] = normalize_number(value.get("Temperature"))
            if "RelativeHumidity" in value:
                result["relative_humidity"] = normalize_number(value.get("RelativeHumidity"))
            if "ProbabilityOfPrecipitation" in value:
                pop = normalize_number(value.get("ProbabilityOfPrecipitation"))
                result["rain_probability"] = pop / 100 if pop is not None else None
            if "WindSpeed" in value:
                result["wind_speed_mps"] = normalize_number(value.get("WindSpeed"))
            if "Weather" in value:
                result["weather"] = normalize_text(value.get("Weather"))

        return result

    def context(self, lat, lon, forecast_location=None):
        errors = {}
        current = {}
        rainfall = {}
        uv = {}
        forecast = {}
        township_forecast = {}

        for label, loader in [
            ("current_weather", lambda: self.current_weather(lat, lon)),
            ("rainfall_10min", lambda: self.rainfall(lat, lon)),
            ("uv", lambda: self.uv(lat, lon, current.get("station_id", ""))),
            ("forecast_36h", lambda: self.forecast(forecast_location)),
            ("township_forecast", lambda: self.township_forecast(lat, lon)),
        ]:
            try:
                value = loader()
                if label == "current_weather":
                    current = value
                elif label == "rainfall_10min":
                    rainfall = value
                elif label == "uv":
                    uv = value
                elif label == "forecast_36h":
                    forecast = value
                elif label == "township_forecast":
                    township_forecast = value
            except Exception as exc:
                errors[label] = str(exc)

        if not current and not rainfall and not uv and not forecast and not township_forecast:
            raise RuntimeError("; ".join(errors.values()) or "No CWA weather data available")

        rain_probability = township_forecast.get("rain_probability")
        if rain_probability is None:
            rain_probability = forecast.get("rain_probability")
        if rain_probability is None:
            rain_10min = rainfall.get("precipitation_10min_mm") or 0
            rain_probability = min(0.95, 0.15 + rain_10min / 10)

        temperature = current.get("temperature_c")
        if temperature is None:
            temperature = township_forecast.get("temperature_c")
        relative_humidity = current.get("relative_humidity")
        if relative_humidity is None:
            relative_humidity = township_forecast.get("relative_humidity")
        wind_speed = current.get("wind_speed_mps")
        if wind_speed is None:
            wind_speed = township_forecast.get("wind_speed_mps")
        uv_index = uv.get("uv_index")
        weather_text = current.get("weather") or township_forecast.get("weather") or forecast.get("weather") or ""
        used_township_fallback = bool(township_forecast) and (
            current.get("temperature_c") is None
            or current.get("relative_humidity") is None
            or current.get("wind_speed_mps") is None
            or not current.get("weather")
            or township_forecast.get("rain_probability") is not None
        )
        outdoor_comfort = "comfortable"
        if rain_probability >= 0.5 or (rainfall.get("precipitation_10min_mm") or 0) > 0:
            outdoor_comfort = "rain_risk"
        elif uv_index and uv_index >= 11:
            outdoor_comfort = "extreme_uv"
        elif uv_index and uv_index >= 8:
            outdoor_comfort = "very_high_uv"
        elif uv_index and uv_index >= 6:
            outdoor_comfort = "high_uv"
        elif temperature and temperature >= 30:
            outdoor_comfort = "hot"
        elif wind_speed and wind_speed >= 10:
            outdoor_comfort = "windy"

        summary_parts = []
        if weather_text:
            summary_parts.append(weather_text)
        if temperature is not None:
            summary_parts.append(f"{temperature}C")
        summary_parts.append(f"rain risk {round(rain_probability * 100)}%")
        if wind_speed is not None:
            summary_parts.append(f"wind {wind_speed} m/s")

        return {
            "location": {"lat": lat, "lon": lon},
            "weather": {
                "summary": ", ".join(summary_parts),
                "weather": weather_text,
                "temperature_c": temperature,
                "relative_humidity": relative_humidity,
                "rain_probability": rain_probability,
                "precipitation_10min_mm": rainfall.get("precipitation_10min_mm"),
                "precipitation_1hr_mm": rainfall.get("precipitation_1hr_mm"),
                "wind_speed_mps": wind_speed,
                "wind_direction_degrees": current.get("wind_direction_degrees"),
                "pressure_hpa": current.get("pressure_hpa"),
                "forecast": forecast,
                "township_forecast": township_forecast,
                "source": "CWA observation + township forecast fallback" if used_township_fallback else "CWA Open Data",
                "station": current.get("station"),
                "rain_station": rainfall.get("station"),
                "forecast_location": township_forecast.get("location") or forecast.get("location"),
                "observation_time": current.get("observation_time"),
            },
            "uv": {
                "uv_index": uv_index,
                "exposure_level": uv.get("exposure_level"),
                "station": uv.get("station") or current.get("station"),
                "source": "CWA Open Data",
            },
            "outdoor_comfort": outdoor_comfort,
            "source_status": {
                "mode": "external",
                "errors": errors,
            },
        }


def get_current_weather(lat, lon):
    return CWAWeatherClient().current_weather(lat, lon)


def get_rainfall(lat, lon):
    return CWAWeatherClient().rainfall(lat, lon)


def get_uv(lat, lon, station_id=""):
    return CWAWeatherClient().uv(lat, lon, station_id)


def get_forecast(location_name=None):
    return CWAWeatherClient().forecast(location_name)


def get_township_forecast(lat, lon):
    return CWAWeatherClient().township_forecast(lat, lon)


def get_context(lat, lon, forecast_location=None):
    return CWAWeatherClient().context(lat, lon, forecast_location)


if __name__ == "__main__":
    sample_lat = parse_float(os.getenv("NEXT_STOPS_SAMPLE_LAT"), 25.044)
    sample_lon = parse_float(os.getenv("NEXT_STOPS_SAMPLE_LON"), 121.5294)
    print(json.dumps(get_context(sample_lat, sample_lon), ensure_ascii=False, indent=2))
