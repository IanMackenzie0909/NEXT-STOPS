"""OpenTripMap API client for Taipei travel POI enrichment."""

from __future__ import annotations

from urllib.parse import urlencode

from .base import BaseHttpClient, ClientConfigError
from ..config import ApiKeys, is_coordinate_in_taipei
from ..core.geo import to_float
from ..core.merge import make_canonical_id
from ..core.models import Place


class OpenTripMapClient(BaseHttpClient):
    source_name = "opentripmap"

    def __init__(self, api_key: str | None = None, lang: str = "zh", base_url: str = "https://api.opentripmap.com/0.1", **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key or ApiKeys.from_env().opentripmap_api_key
        self.lang = lang
        self.base_url = base_url.rstrip("/")

    def _require_key(self) -> None:
        if not self.api_key:
            raise ClientConfigError("OPENTRIPMAP_API_KEY 尚未設定，略過 OpenTripMap。")

    def search_radius(self, lat: float, lon: float, radius_m: int = 1500, kinds: str = "interesting_places", limit: int = 50) -> list[dict]:
        self._require_key()
        params = {
            "radius": radius_m,
            "lon": lon,
            "lat": lat,
            "kinds": kinds,
            "format": "json",
            "limit": limit,
            "apikey": self.api_key,
        }
        url = f"{self.base_url}/{self.lang}/places/radius?{urlencode(params)}"
        payload = self.request_json("GET", url)
        return payload if isinstance(payload, list) else []

    def get_place_detail(self, xid: str) -> dict:
        self._require_key()
        url = f"{self.base_url}/{self.lang}/places/xid/{xid}?{urlencode({'apikey': self.api_key})}"
        payload = self.request_json("GET", url)
        return payload if isinstance(payload, dict) else {}

    def get_places_nearby(self, lat: float, lon: float, radius_m: int = 1500, with_details: bool = False) -> list[Place]:
        rows = self.search_radius(lat, lon, radius_m)
        places: list[Place] = []
        for row in rows:
            detail = self.get_place_detail(row["xid"]) if with_details and row.get("xid") else row
            merged = {**row, **detail}
            if place := self.to_place(merged):
                places.append(place)
        return places

    def to_place(self, row: dict) -> Place | None:
        name = row.get("name")
        if not name:
            return None
        point = row.get("point") if isinstance(row.get("point"), dict) else {}
        lat = to_float(row.get("lat") or point.get("lat"))
        lon = to_float(row.get("lon") or point.get("lon"))
        if not is_coordinate_in_taipei(lat, lon):
            return None
        preview = row.get("preview") if isinstance(row.get("preview"), dict) else {}
        wikipedia_extracts = row.get("wikipedia_extracts") if isinstance(row.get("wikipedia_extracts"), dict) else {}
        xid = row.get("xid") or ""
        return Place(
            id=make_canonical_id(str(name)),
            name=str(name),
            city="臺北市",
            description=wikipedia_extracts.get("text") or row.get("info") or row.get("kinds"),
            lat=lat,
            lon=lon,
            categories=[c for c in str(row.get("kinds") or "opentripmap").split(",") if c],
            source_ids={self.source_name: str(xid)} if xid else {},
            official_urls=[u for u in [row.get("url"), row.get("wikipedia")] if u],
            image_urls=[u for u in [preview.get("source")] if u],
            popularity=_rate_to_popularity(row.get("rate")),
            sources=[self.source_name],
            raw=row,
        )


def _rate_to_popularity(value) -> float | None:
    try:
        return min(max(float(value) / 7.0, 0.0), 1.0)
    except (TypeError, ValueError):
        return None
