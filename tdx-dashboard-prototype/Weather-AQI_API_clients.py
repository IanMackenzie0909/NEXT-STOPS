import importlib.util
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_TIMEOUT_SECONDS = 8


def load_client_module(module_name, filename):
    module_path = ROOT / filename
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cwa_module = load_client_module("cwa_weather_api_client", "CWA-Weather_API_clients.py")
moenv_module = load_client_module("moenv_aqi_api_client", "MOENV-AQI_API_clients.py")

CWAWeatherClient = cwa_module.CWAWeatherClient
MOENVAQIClient = moenv_module.MOENVAQIClient
parse_float = cwa_module.parse_float


class WeatherAQIClient:
    def __init__(self, cwa_api_key=None, aqi_api_key=None, timeout_seconds=DEFAULT_TIMEOUT_SECONDS, forecast_location=None):
        self.weather_client = CWAWeatherClient(
            api_key=cwa_api_key,
            timeout_seconds=timeout_seconds,
            forecast_location=forecast_location,
        )
        self.aqi_client = MOENVAQIClient(
            api_key=aqi_api_key,
            timeout_seconds=timeout_seconds,
        )

    def real_context(self, lat, lon):
        errors = {}
        current = {}
        rainfall = {}
        uv = {}
        forecast = {}
        township_forecast = {}
        aqi = {}

        for label, loader in [
            ("current_weather", lambda: self.weather_client.current_weather(lat, lon)),
            ("rainfall_10min", lambda: self.weather_client.rainfall(lat, lon)),
            ("uv", lambda: self.weather_client.uv(lat, lon, current.get("station_id", ""))),
            ("forecast_36h", self.weather_client.forecast),
            ("township_forecast", lambda: self.weather_client.township_forecast(lat, lon)),
            ("aqi", lambda: self.aqi_client.aqi(lat, lon)),
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
                elif label == "aqi":
                    aqi = value
            except Exception as exc:
                errors[label] = str(exc)

        if not aqi:
            try:
                aqi = self.aqi_client.metro_taipei_aqi()
                errors.pop("aqi", None)
            except Exception as exc:
                errors["aqi_fallback"] = str(exc)

        if uv and current.get("station") and not uv.get("station"):
            uv["station"] = current.get("station")

        if not current and not aqi and not forecast and not township_forecast and not rainfall and not uv:
            raise RuntimeError("; ".join(errors.values()) or "No external context data available")

        rain_probability = township_forecast.get("rain_probability")
        if rain_probability is None:
            rain_probability = forecast.get("rain_probability")
        if rain_probability is None:
            rain_10min = rainfall.get("precipitation_10min_mm") or 0
            rain_probability = min(0.95, 0.15 + rain_10min / 10)

        aqi_value = aqi.get("aqi")
        aqi_status = aqi.get("status") or ("good" if aqi_value and aqi_value <= 50 else "moderate" if aqi_value and aqi_value <= 100 else "unknown")

        temperature = current.get("temperature_c")
        if temperature is None:
            temperature = township_forecast.get("temperature_c")
        relative_humidity = current.get("relative_humidity")
        if relative_humidity is None:
            relative_humidity = township_forecast.get("relative_humidity")
        wind_speed = current.get("wind_speed_mps")
        if wind_speed is None:
            wind_speed = township_forecast.get("wind_speed_mps")
        if wind_speed is None:
            wind_speed = aqi.get("wind_speed_mps")
        wind_direction = current.get("wind_direction_degrees") if current.get("wind_direction_degrees") is not None else aqi.get("wind_direction_degrees")
        uv_index = uv.get("uv_index")

        weather_text = current.get("weather") or township_forecast.get("weather") or forecast.get("weather") or ""
        used_township_fallback = bool(township_forecast) and (
            current.get("temperature_c") is None
            or current.get("relative_humidity") is None
            or current.get("wind_speed_mps") is None
            or not current.get("weather")
            or township_forecast.get("rain_probability") is not None
        )
        weather_source = "CWA observation + township forecast fallback" if used_township_fallback else "CWA Open Data"

        outdoor_comfort = "comfortable"
        if rain_probability >= 0.5 or (rainfall.get("precipitation_10min_mm") or 0) > 0:
            outdoor_comfort = "rain_risk"
        elif aqi_value and aqi_value > 100:
            outdoor_comfort = "poor_air_quality"
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
                "wind_direction_degrees": wind_direction,
                "pressure_hpa": current.get("pressure_hpa"),
                "forecast": forecast,
                "township_forecast": township_forecast,
                "source": weather_source,
                "station": current.get("station"),
                "rain_station": rainfall.get("station"),
                "forecast_location": township_forecast.get("location") or forecast.get("location"),
                "observation_time": current.get("observation_time"),
            },
            "uv": {
                "uv_index": uv_index,
                "exposure_level": uv.get("exposure_level"),
                "station": uv.get("station"),
                "source": "CWA Open Data",
            },
            "air_quality": {
                "aqi": aqi_value,
                "status": aqi_status,
                "status_kind": aqi.get("status_kind"),
                "pollutant": aqi.get("pollutant"),
                "pm25": aqi.get("pm25"),
                "pm10": aqi.get("pm10"),
                "site": aqi.get("site"),
                "county": aqi.get("county"),
                "publish_time": aqi.get("publish_time"),
                "source": aqi.get("source") or "MOENV Open Data",
            },
            "outdoor_comfort": outdoor_comfort,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_status": {
                "mode": "external",
                "errors": errors,
            },
        }

    def heuristic_context(self, lat, lon, fallback_error=""):
        seed = abs(math.sin(lat * 12.9898 + lon * 78.233))
        temperature = round(21 + seed * 8, 1)
        rain_probability = round(0.12 + (seed * 0.42), 2)
        aqi_value = int(35 + seed * 55)
        aqi_status = "good" if aqi_value <= 50 else "moderate" if aqi_value <= 100 else "poor"
        outdoor_comfort = "comfortable"
        if rain_probability > 0.45:
            outdoor_comfort = "rain_risk"
        elif aqi_value > 80:
            outdoor_comfort = "air_quality_watch"
        elif temperature > 27:
            outdoor_comfort = "warm"

        return {
            "location": {"lat": lat, "lon": lon},
            "weather": {
                "summary": f"{temperature}C, rain risk {round(rain_probability * 100)}%",
                "weather": "",
                "temperature_c": temperature,
                "relative_humidity": None,
                "rain_probability": rain_probability,
                "precipitation_10min_mm": None,
                "precipitation_1hr_mm": None,
                "wind_speed_mps": None,
                "wind_direction_degrees": None,
                "pressure_hpa": None,
                "forecast": {},
                "township_forecast": {},
                "source": "prototype heuristic",
            },
            "air_quality": {
                "aqi": aqi_value,
                "status": aqi_status,
                "status_kind": aqi_status,
                "pollutant": None,
                "pm25": None,
                "pm10": None,
                "source": "prototype heuristic",
            },
            "uv": {
                "uv_index": None,
                "exposure_level": None,
                "source": "prototype heuristic",
            },
            "outdoor_comfort": outdoor_comfort,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_status": {
                "mode": "heuristic_fallback",
                "error": fallback_error,
            },
            "note": "Using heuristic fallback because external Weather/AQI APIs are not configured or failed.",
        }

    def context(self, lat, lon):
        try:
            return self.real_context(lat, lon)
        except Exception as exc:
            return self.heuristic_context(lat, lon, str(exc))


def get_context(lat, lon):
    return WeatherAQIClient().context(lat, lon)


def get_real_context(lat, lon):
    return WeatherAQIClient().real_context(lat, lon)


if __name__ == "__main__":
    sample_lat = parse_float(os.getenv("NEXT_STOPS_SAMPLE_LAT"), 25.044)
    sample_lon = parse_float(os.getenv("NEXT_STOPS_SAMPLE_LON"), 121.5294)
    print(json.dumps(get_context(sample_lat, sample_lon), ensure_ascii=False, indent=2))
