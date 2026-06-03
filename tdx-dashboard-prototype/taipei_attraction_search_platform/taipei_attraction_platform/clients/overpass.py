"""OpenStreetMap Overpass API client for Taipei POI enrichment."""

from __future__ import annotations

from .base import BaseHttpClient
from ..core.geo import to_float
from ..core.merge import make_canonical_id
from ..core.models import Place
from ..config import is_coordinate_in_taipei


class OverpassClient(BaseHttpClient):
    source_name = "overpass"

    def __init__(self, endpoint: str = "https://overpass-api.de/api/interpreter", **kwargs):
        super().__init__(**kwargs)
        self.endpoint = endpoint

    def search_tourism_nearby(self, lat: float, lon: float, radius_m: int = 1500) -> list[dict]:
        query = f"""
[out:json][timeout:25];
(
  node["tourism"~"attraction|museum|gallery|viewpoint|theme_park|zoo"](around:{radius_m},{lat},{lon});
  way["tourism"~"attraction|museum|gallery|viewpoint|theme_park|zoo"](around:{radius_m},{lat},{lon});
  relation["tourism"~"attraction|museum|gallery|viewpoint|theme_park|zoo"](around:{radius_m},{lat},{lon});
  node["historic"](around:{radius_m},{lat},{lon});
  way["historic"](around:{radius_m},{lat},{lon});
);
out center tags;
""".strip()
        payload = self.request_json("POST", self.endpoint, data={"data": query})
        return payload.get("elements", []) if isinstance(payload, dict) else []

    def get_places_nearby(self, lat: float, lon: float, radius_m: int = 1500) -> list[Place]:
        return [p for row in self.search_tourism_nearby(lat, lon, radius_m) if (p := self.to_place(row))]

    def to_place(self, row: dict) -> Place | None:
        tags = row.get("tags") or {}
        name = tags.get("name:zh") or tags.get("name:zh-TW") or tags.get("name")
        if not name:
            return None
        center = row.get("center") if isinstance(row.get("center"), dict) else {}
        lat = to_float(row.get("lat") or center.get("lat"))
        lon = to_float(row.get("lon") or center.get("lon"))
        if not is_coordinate_in_taipei(lat, lon):
            return None
        osm_type = row.get("type", "osm")
        osm_id = row.get("id", "")
        categories = [v for v in [tags.get("tourism"), tags.get("historic"), tags.get("amenity"), tags.get("leisure")] if v]
        return Place(
            id=make_canonical_id(str(name), tags.get("addr:district")),
            name=str(name),
            city="臺北市",
            district=tags.get("addr:district"),
            description=tags.get("description") or tags.get("wikipedia"),
            lat=lat,
            lon=lon,
            address=_address_from_tags(tags),
            categories=categories or ["osm_poi"],
            source_ids={self.source_name: f"{osm_type}/{osm_id}"},
            official_urls=[u for u in [tags.get("website")] if u],
            opening_hours=tags.get("opening_hours"),
            phone=tags.get("phone") or tags.get("contact:phone"),
            sources=[self.source_name],
            raw=row,
        )


def _address_from_tags(tags: dict) -> str | None:
    parts = [tags.get("addr:city"), tags.get("addr:district"), tags.get("addr:street"), tags.get("addr:housenumber")]
    address = "".join([str(p) for p in parts if p])
    return address or None
