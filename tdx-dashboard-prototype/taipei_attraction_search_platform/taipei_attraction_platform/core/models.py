"""Unified place models used by all API clients."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

from .geo import haversine_m
from .text import normalize_text


@dataclass
class Place:
    id: str
    name: str
    city: str = "臺北市"
    district: str | None = None
    aliases: list[str] = field(default_factory=list)
    description: str | None = None
    lat: float | None = None
    lon: float | None = None
    address: str | None = None
    categories: list[str] = field(default_factory=list)
    source_ids: dict[str, str] = field(default_factory=dict)
    official_urls: list[str] = field(default_factory=list)
    image_urls: list[str] = field(default_factory=list)
    opening_hours: str | None = None
    phone: str | None = None
    rating: float | None = None
    popularity: float | None = None
    sources: list[str] = field(default_factory=list)
    updated_at: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def normalized_name(self) -> str:
        return normalize_text(self.name).replace(" ", "")

    def has_coordinates(self) -> bool:
        return self.lat is not None and self.lon is not None

    def quality_score(self) -> float:
        score = 0.0
        score += 0.22 if self.has_coordinates() else 0.0
        score += 0.15 if self.description else 0.0
        score += 0.13 if self.image_urls else 0.0
        score += 0.10 if self.opening_hours else 0.0
        score += 0.10 if self.address else 0.0
        score += min(len(set(self.sources)) / 5.0, 1.0) * 0.18
        official_sources = {"taipei_travel", "tdx_tourism", "taipei_open_data"}
        score += 0.12 if official_sources.intersection(self.sources) else 0.0
        return round(min(score, 1.0), 4)

    def search_blob(self) -> str:
        parts = [
            self.name,
            " ".join(self.aliases),
            self.district or "",
            self.address or "",
            " ".join(self.categories),
            self.description or "",
            " ".join(self.sources),
        ]
        return normalize_text(" ".join(parts))

    def to_dict(self, query_lat: float | None = None, query_lon: float | None = None) -> dict[str, Any]:
        data = asdict(self)
        data["quality_score"] = self.quality_score()
        data["distance_m"] = haversine_m(query_lat, query_lon, self.lat, self.lon)
        return data


@dataclass(frozen=True)
class SearchQuery:
    query: str | None = None
    district: str | None = None
    category: str | None = None
    lat: float | None = None
    lon: float | None = None
    radius_m: int | None = None
    limit: int = 20
    include_missing_coordinates: bool = True


@dataclass
class SearchResult:
    place: Place
    score: float
    distance_m: float | None = None
    text_score: float = 0.0
    distance_score: float = 0.0
    quality_score: float = 0.0
    popularity_score: float = 0.0
    freshness_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = self.place.to_dict()
        payload.update({
            "score": round(self.score, 4),
            "distance_m": self.distance_m,
            "score_breakdown": {
                "text": round(self.text_score, 4),
                "distance": round(self.distance_score, 4),
                "quality": round(self.quality_score, 4),
                "popularity": round(self.popularity_score, 4),
                "freshness": round(self.freshness_score, 4),
            },
        })
        return payload
