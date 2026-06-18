"""Core and route-comparison routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body


def create_router(deps) -> APIRouter:
    router = APIRouter(tags=["core", "routes"])

    @router.get("/health")
    def health():
        return {"status": "ok", "service": "next-stops-data-api"}

    @router.get("/api/sample-locations")
    def sample_locations():
        return {"locations": deps.sample_locations}

    @router.get("/api/context")
    def context(lat: float, lon: float, real: bool = False):
        return deps.run_or_raise(lambda: deps.weather_aqi_client.real_context(lat, lon) if real else deps.weather_aqi_client.context(lat, lon))

    @router.get("/api/mapbox-config")
    def mapbox_config():
        return deps.mapbox_config()

    @router.post("/api/route")
    def route(payload: dict[str, Any] | None = Body(default=None)):
        def build_route():
            data = payload or {}
            origin = data.get("origin") or {}
            destination = data.get("destination") or {}
            if origin.get("lng") is not None and origin.get("lon") is None:
                origin["lon"] = origin.get("lng")
            if destination.get("lng") is not None and destination.get("lon") is None:
                destination["lon"] = destination.get("lng")
            if deps.to_float(origin.get("lat")) is None or deps.to_float(origin.get("lon")) is None:
                raise ValueError("origin.lat and origin.lon are required")
            if deps.to_float(destination.get("lat")) is None or deps.to_float(destination.get("lon")) is None:
                raise ValueError("destination.lat and destination.lon are required")
            normalized_origin = {"lat": deps.to_float(origin["lat"]), "lon": deps.to_float(origin["lon"])}
            normalized_destination = {"lat": deps.to_float(destination["lat"]), "lon": deps.to_float(destination["lon"])}
            return deps.compare_commute_options(
                normalized_origin,
                normalized_destination,
                modes=deps.normalize_transport_modes(data.get("transportModes")),
                include_geometry=True,
            )

        return deps.run_or_raise(build_route)

    return router

