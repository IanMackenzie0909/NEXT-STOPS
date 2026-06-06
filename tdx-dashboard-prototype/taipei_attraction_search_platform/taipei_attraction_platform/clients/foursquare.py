"""Foursquare Places client."""

from __future__ import annotations

import os
from urllib.parse import urlencode

from .base import BaseHttpClient, ClientConfigError
from ..config import ApiKeys, is_coordinate_in_taipei
from ..core.geo import to_float
from ..core.merge import make_canonical_id
from ..core.models import Place


class FoursquarePlacesClient(BaseHttpClient):
    source_name = "foursquare"

    def __init__(self, api_key: str | None = None, base_url: str | None = None, api_version: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key or ApiKeys.from_env().foursquare_api_key
        self.base_url = (base_url or os.getenv("FOURSQUARE_BASE_URL") or "https://places-api.foursquare.com/places").rstrip("/")
        self.api_version = api_version or os.getenv("FOURSQUARE_API_VERSION") or "2025-06-17"

    def _require_key(self) -> None:
        if not self.api_key:
            raise ClientConfigError("FOURSQUARE_API_KEY 尚未設定，略過 Foursquare。")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key or ''}",
            "Accept": "application/json",
            "X-Places-Api-Version": self.api_version,
        }

    def search_places(self, query: str | None, lat: float, lon: float, radius_m: int = 1500, limit: int = 20) -> list[dict]:
        self._require_key()
        params = {
            "ll": f"{lat},{lon}",
            "radius": radius_m,
            "limit": limit,
            "fields": "fsq_place_id,name,latitude,longitude,location,categories,distance,tel,website",
        }
        if query:
            params["query"] = query
        url = f"{self.base_url}/search?{urlencode(params)}"
        payload = self.request_json("GET", url, headers=self._headers())
        return payload.get("results", []) if isinstance(payload, dict) else []

    def get_places_nearby(self, lat: float, lon: float, radius_m: int = 1500, query: str | None = None) -> list[Place]:
        return [p for row in self.search_places(query, lat, lon, radius_m) if (p := self.to_place(row))]

    def to_place(self, row: dict) -> Place | None:
        name = row.get("name")
        geocodes = row.get("geocodes") if isinstance(row.get("geocodes"), dict) else {}
        main = geocodes.get("main") if isinstance(geocodes.get("main"), dict) else {}
        lat = to_float(row.get("latitude") or main.get("latitude"))
        lon = to_float(row.get("longitude") or main.get("longitude"))
        if not name or not is_coordinate_in_taipei(lat, lon):
            return None
        location = row.get("location") if isinstance(row.get("location"), dict) else {}
        categories = []
        for item in row.get("categories", []) or []:
            if isinstance(item, dict) and item.get("name"):
                categories.append(item["name"])
            elif isinstance(item, str):
                categories.append(item)
        fsq_id = row.get("fsq_place_id") or row.get("fsq_id") or ""
        return Place(
            id=make_canonical_id(str(name), location.get("district")),
            name=str(name),
            city="臺北市",
            district=location.get("district"),
            lat=lat,
            lon=lon,
            address=location.get("formatted_address") or ", ".join(location.get("address", []) if isinstance(location.get("address"), list) else [location.get("address") or ""]),
            categories=categories or ["foursquare_place"],
            source_ids={self.source_name: str(fsq_id)} if fsq_id else {},
            popularity=_normalize_popularity(row.get("popularity")),
            rating=_normalize_rating(row.get("rating")),
            official_urls=[u for u in [row.get("website")] if u],
            phone=row.get("tel"),
            sources=[self.source_name],
            raw=row,
        )


def _normalize_rating(value) -> float | None:
    try:
        rating = float(value)
        return rating / 2.0 if rating > 5 else rating
    except (TypeError, ValueError):
        return None


def _normalize_popularity(value) -> float | None:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return None
