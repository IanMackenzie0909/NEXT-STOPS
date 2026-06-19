"""Weather and AQI service wrappers."""

from __future__ import annotations


class WeatherService:
    def __init__(self, cwa_module, moenv_module, weather_aqi_module):
        self.cwa_module = cwa_module
        self.moenv_module = moenv_module
        self.weather_aqi_client = weather_aqi_module.WeatherAQIClient()

    def context(self, lat: float, lon: float, real: bool = False):
        if real:
            return self.weather_aqi_client.real_context(lat, lon)
        return self.weather_aqi_client.context(lat, lon)

    def cwa_current_weather(self, lat: float, lon: float):
        return self.cwa_module.CWAWeatherClient().current_weather(lat, lon)

    def cwa_rainfall(self, lat: float, lon: float):
        return self.cwa_module.CWAWeatherClient().rainfall(lat, lon)

    def cwa_uv(self, lat: float, lon: float, station_id: str = ""):
        return self.cwa_module.CWAWeatherClient().uv(lat, lon, station_id)

    def cwa_forecast(self, location_name: str | None = None):
        return self.cwa_module.CWAWeatherClient().forecast(location_name)

    def cwa_township_forecast(self, lat: float, lon: float):
        return self.cwa_module.CWAWeatherClient().township_forecast(lat, lon)

    def moenv_aqi(self, lat: float, lon: float):
        return self.moenv_module.MOENVAQIClient().aqi(lat, lon)
