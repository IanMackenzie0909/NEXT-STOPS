"""Place search and detail routes."""

from __future__ import annotations

from fastapi import APIRouter, Query


def create_router(deps) -> APIRouter:
    router = APIRouter(tags=["places"])

    @router.post("/api/places/build")
    def build(with_optional: bool = False):
        return deps.places_build(with_optional=with_optional)

    @router.get("/api/places/search")
    def search(
        q: str | None = None,
        district: str | None = None,
        category: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        radius_m: int | None = None,
        limit: int = 20,
    ):
        return deps.run_or_raise(
            lambda: {
                "count": len(
                    results := deps.search_attraction_places(
                        q=q,
                        district=district,
                        category=category,
                        lat=lat,
                        lon=lon,
                        radius_m=radius_m,
                        limit=limit,
                    )
                ),
                "results": results,
            }
        )

    @router.get("/api/places/{place_id}")
    def detail(
        place_id: str,
        lat: float | None = None,
        lon: float | None = None,
        mood: str = "relaxing_walk",
        distance: int = 30,
        time_minutes: int = Query(120, alias="time"),
        budget: str = "medium",
        weather_preference: str = Query("any", alias="weatherPreference"),
        transport_modes: str | None = Query(None, alias="transportModes"),
        session_id: str | None = None,
    ):
        criteria = deps.detail_criteria_from_query(
            lat=lat,
            lon=lon,
            mood=mood,
            distance=distance,
            time_minutes=time_minutes,
            budget=budget,
            weather_preference=weather_preference,
            transport_modes=transport_modes,
        )
        return deps.run_or_raise(lambda: deps.build_place_detail(place_id, criteria, session_id=session_id))

    @router.get("/api/districts")
    def districts():
        return deps.run_or_raise(lambda: deps.get_attraction_service().districts())

    return router

