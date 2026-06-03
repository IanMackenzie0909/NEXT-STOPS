"""High-level Taipei-only search service."""

from __future__ import annotations

from pathlib import Path

from ..core.index import PlaceIndex
from ..core.models import Place, SearchQuery, SearchResult
from .cache import JsonPlaceCache
from .ingestion_service import TaipeiIngestionService, IngestionReport, DEFAULT_PUBLIC_SOURCES


class TaipeiAttractionSearchService:
    def __init__(self, places: list[Place] | None = None, cache_path: str | Path | None = None):
        self.cache_path = Path(cache_path) if cache_path else None
        self.index = PlaceIndex(places or [])
        self.last_report: IngestionReport | None = None

    @classmethod
    def from_cache(cls, cache_path: str | Path) -> "TaipeiAttractionSearchService":
        cache = JsonPlaceCache(cache_path)
        return cls(places=cache.load(), cache_path=cache_path)

    def build(
        self,
        sources=DEFAULT_PUBLIC_SOURCES,
        include_optional_nearby: bool = False,
        save_cache: bool = True,
    ) -> IngestionReport:
        ingestion = TaipeiIngestionService()
        places, report = ingestion.fetch_sources(sources=sources, include_optional_nearby=include_optional_nearby)
        self.index = PlaceIndex(places)
        self.last_report = report
        if save_cache and self.cache_path:
            JsonPlaceCache(self.cache_path).save(self.index.places)
        return report

    def search(
        self,
        query: str | None = None,
        district: str | None = None,
        category: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        radius_m: int | None = None,
        limit: int = 20,
        include_missing_coordinates: bool = True,
    ) -> list[SearchResult]:
        search_query = SearchQuery(
            query=query,
            district=district,
            category=category,
            lat=lat,
            lon=lon,
            radius_m=radius_m,
            limit=limit,
            include_missing_coordinates=include_missing_coordinates,
        )
        return self.index.search(search_query)

    def districts(self) -> dict[str, int]:
        return self.index.districts()
