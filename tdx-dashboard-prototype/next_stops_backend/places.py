"""Place cache, search, and lookup services for NEXT STOPS."""

from __future__ import annotations

from typing import Any

from .config import ATTRACTION_CACHE
from .utils import now_iso


def normalize_search_text(value: object) -> str:
    return str(value or "").strip().lower().replace("台", "臺")


class PlacesService:
    def __init__(self, search_service_cls):
        self.search_service_cls = search_service_cls
        self.cache: dict[str, Any] = {"service": None, "loaded_at": None}

    def get_attraction_service(self):
        if self.cache["service"] is not None:
            return self.cache["service"]

        service = (
            self.search_service_cls.from_cache(ATTRACTION_CACHE)
            if ATTRACTION_CACHE.exists()
            else self.search_service_cls(cache_path=ATTRACTION_CACHE)
        )
        if not service.index.places:
            try:
                service.build()
            except Exception as exc:
                raise RuntimeError(
                    "Attraction cache is empty and automatic build failed. "
                    "Run POST /api/places/build after network/API setup, or start the attraction service build first. "
                    f"Original error: {exc}"
                ) from exc

        self.cache["service"] = service
        self.cache["loaded_at"] = now_iso()
        return service

    @staticmethod
    def serialize_search_results(results: list) -> list[dict[str, Any]]:
        return [result.to_dict() for result in results]

    def search_attraction_places(
        self,
        q: str | None = None,
        district: str | None = None,
        category: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        radius_m: int | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        service = self.get_attraction_service()
        return self.serialize_search_results(
            service.search(
                query=q,
                district=district,
                category=category,
                lat=lat,
                lon=lon,
                radius_m=radius_m,
                limit=limit,
                include_missing_coordinates=False,
            )
        )

    def get_attraction_place_by_id(self, place_id: str) -> dict[str, Any] | None:
        normalized_id = str(place_id or "").strip()
        if not normalized_id:
            return None
        service = self.get_attraction_service()
        for place in service.index.places:
            if str(place.id) == normalized_id:
                return place.to_dict()
        return None

    def build(self, with_optional: bool = False) -> dict[str, Any]:
        service = self.search_service_cls(cache_path=ATTRACTION_CACHE)
        report = service.build(include_optional_nearby=with_optional)
        self.cache["service"] = service
        self.cache["loaded_at"] = now_iso()
        return {"final_count": report.final_count, "fetched_counts": report.fetched_counts, "errors": report.errors}

    def districts(self):
        return self.get_attraction_service().districts()
