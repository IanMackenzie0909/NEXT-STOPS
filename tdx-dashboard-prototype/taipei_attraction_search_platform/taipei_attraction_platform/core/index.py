"""In-memory Taipei place index."""

from __future__ import annotations

from .geo import haversine_m
from .merge import deduplicate_places
from .models import Place, SearchQuery, SearchResult
from .ranker import score_place
from .text import normalize_text
from ..config import is_coordinate_in_taipei, is_taipei_district


class PlaceIndex:
    def __init__(self, places: list[Place] | None = None):
        self.places: list[Place] = []
        if places:
            self.add_many(places)

    def add_many(self, places: list[Place]) -> None:
        taipei_only = [
            p for p in places
            if (not p.city or normalize_text(p.city) in {"臺北市", "taipei", "taipei city"})
            and is_coordinate_in_taipei(p.lat, p.lon)
        ]
        self.places = deduplicate_places([*self.places, *taipei_only])

    def search(self, search_query: SearchQuery) -> list[SearchResult]:
        district = normalize_text(search_query.district) if search_query.district else None
        category = normalize_text(search_query.category) if search_query.category else None
        candidates: list[Place] = []

        for place in self.places:
            if district and normalize_text(place.district or "") != district:
                continue
            if category and category not in normalize_text(" ".join(place.categories)):
                continue
            if search_query.radius_m and search_query.lat is not None and search_query.lon is not None:
                distance = haversine_m(search_query.lat, search_query.lon, place.lat, place.lon)
                if distance is None:
                    if not search_query.include_missing_coordinates:
                        continue
                elif distance > search_query.radius_m:
                    continue
            candidates.append(place)

        results = [score_place(place, search_query) for place in candidates]
        if search_query.query or search_query.category:
            results = [r for r in results if r.text_score > 0 or (search_query.category and r.place.categories)]
        results.sort(key=lambda r: r.score, reverse=True)
        return results[: max(search_query.limit, 1)]

    def districts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for place in self.places:
            district = place.district or "未標示"
            if is_taipei_district(district) or district == "未標示":
                counts[district] = counts.get(district, 0) + 1
        return dict(sorted(counts.items()))
