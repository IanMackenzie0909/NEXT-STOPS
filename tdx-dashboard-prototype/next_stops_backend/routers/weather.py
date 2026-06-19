"""Weather and AQI routes."""

from __future__ import annotations

from fastapi import APIRouter


def create_router(deps) -> APIRouter:
    router = APIRouter(tags=["weather"])

    @router.get("/api/weather-aqi")
    def weather_aqi(lat: float, lon: float, real: bool = False):
        return deps.run_or_raise(lambda: deps.weather_service.context(lat, lon, real=real))

    @router.get("/api/cwa/current-weather")
    def cwa_current_weather(lat: float, lon: float):
        return deps.run_or_raise(lambda: deps.weather_service.cwa_current_weather(lat, lon))

    @router.get("/api/cwa/rainfall")
    def cwa_rainfall(lat: float, lon: float):
        return deps.run_or_raise(lambda: deps.weather_service.cwa_rainfall(lat, lon))

    @router.get("/api/cwa/uv")
    def cwa_uv(lat: float, lon: float, station_id: str = ""):
        return deps.run_or_raise(lambda: deps.weather_service.cwa_uv(lat, lon, station_id))

    @router.get("/api/cwa/forecast")
    def cwa_forecast(location_name: str | None = None):
        return deps.run_or_raise(lambda: deps.weather_service.cwa_forecast(location_name))

    @router.get("/api/cwa/township-forecast")
    def cwa_township_forecast(lat: float, lon: float):
        return deps.run_or_raise(lambda: deps.weather_service.cwa_township_forecast(lat, lon))

    @router.get("/api/moenv/aqi")
    def moenv_aqi(lat: float, lon: float):
        return deps.run_or_raise(lambda: deps.weather_service.moenv_aqi(lat, lon))

    return router
