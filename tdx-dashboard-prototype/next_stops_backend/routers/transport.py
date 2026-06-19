"""Bus and MRT routes."""

from __future__ import annotations

from fastapi import APIRouter, Query


def create_router(deps) -> APIRouter:
    router = APIRouter(tags=["transport"])

    @router.get("/api/bus/stations")
    def bus_stations(q: str = "", city: str | None = None):
        selected_city = deps.transport_service.get_bus_city(city)
        return deps.run_or_raise(
            lambda: [
                deps.transport_service.bus_station_option(item)
                for item in deps.transport_service.find_bus_stations(q, selected_city)
            ]
        )

    @router.get("/api/bus/station")
    def bus_station(station_id: str = Query(...), city: str | None = None):
        selected_city = deps.transport_service.get_bus_city(city)
        return deps.run_or_raise(lambda: deps.transport_service.get_bus_station_detail(station_id.strip(), selected_city))

    @router.get("/api/bus/arrivals")
    def bus_arrivals(stop_uid: str = Query(...), city: str | None = None, route_name: str = ""):
        selected_city = deps.transport_service.get_bus_city(city)
        return deps.run_or_raise(lambda: deps.transport_service.get_bus_arrivals(stop_uid.strip(), selected_city, route_name.strip()))

    @router.get("/api/mrt/stations")
    def mrt_stations(q: str = ""):
        return deps.run_or_raise(
            lambda: [
                deps.transport_service.mrt_station_summary(item)
                for item in deps.transport_service.find_mrt_stations(q)
            ]
        )

    @router.get("/api/mrt/liveboard")
    def mrt_liveboard(station_id: str = Query(...)):
        return deps.run_or_raise(lambda: deps.transport_service.get_mrt_liveboard(station_id.strip()))

    return router
