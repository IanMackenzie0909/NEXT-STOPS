"""Geoapify Places API client."""

from __future__ import annotations

from urllib.parse import urlencode

from .base import BaseHttpClient, ClientConfigError
from ..config import ApiKeys, is_coordinate_in_taipei
from ..core.geo import to_float
from ..core.merge import make_canonical_id
from ..core.models import Place


class GeoapifyPlacesClient(BaseHttpClient):
    source_name = "geoapify"

    def __init__(self, api_key: str | None = None, base_url: str = "https://api.geoapify.com/v2/places", **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key or ApiKeys.from_env().geoapify_api_key
        self.base_url = base_url

    def _require_key(self) -> None:
        if not self.api_key:
            raise ClientConfigError("GEOAPIFY_API_KEY 尚未設定，略過 Geoapify。")

    def search_places(self, lat: float, lon: float, radius_m: int = 1500, categories: str = "tourism.sights,tourism.attraction", name: str | None = None, limit: int = 50) -> list[dict]:
        self._require_key()
        params = {
            "categories": categories,
            "filter": f"circle:{lon},{lat},{radius_m}",
            "bias": f"proximity:{lon},{lat}",
            "limit": limit,
            "lang": "zh",
            "apiKey": self.api_key,
        }
        if name:
            params["name"] = name
        payload = self.request_json("GET", f"{self.base_url}?{urlencode(params)}")
        return payload.get("features", []) if isinstance(payload, dict) else []

    def get_places_nearby(self, lat: float, lon: float, radius_m: int = 1500) -> list[Place]:
        return [p for row in self.search_places(lat, lon, radius_m) if (p := self.to_place(row))]

    def to_place(self, feature: dict) -> Place | None:
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
        coords = geometry.get("coordinates") or []
        lon = to_float(props.get("lon") or (coords[0] if len(coords) >= 1 else None))
        lat = to_float(props.get("lat") or (coords[1] if len(coords) >= 2 else None))
        name = props.get("name")
        if not name or not is_coordinate_in_taipei(lat, lon):
            return None
        place_id = props.get("place_id") or ""
        return Place(
            id=make_canonical_id(str(name), props.get("district")),
            name=str(name),
            city="臺北市",
            district=props.get("district") or props.get("city_district"),
            lat=lat,
            lon=lon,
            address=props.get("formatted") or props.get("address_line2"),
            categories=props.get("categories") or ["geoapify_place"],
            source_ids={self.source_name: str(place_id)} if place_id else {},
            official_urls=[u for u in [props.get("website")] if u],
            opening_hours=props.get("opening_hours"),
            phone=props.get("contact", {}).get("phone") if isinstance(props.get("contact"), dict) else None,
            sources=[self.source_name],
            raw=feature,
        )
