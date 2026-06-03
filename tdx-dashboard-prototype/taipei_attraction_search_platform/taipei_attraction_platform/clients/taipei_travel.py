"""Client for Taipei Travel Open API."""

from __future__ import annotations

from urllib.parse import urlencode

from .base import BaseHttpClient
from ..core.geo import to_float
from ..core.merge import make_canonical_id
from ..core.models import Place
from ..config import is_coordinate_in_taipei, is_taipei_district


class TaipeiTravelClient(BaseHttpClient):
    source_name = "taipei_travel"

    def __init__(self, lang: str = "zh-tw", base_url: str = "https://www.travel.taipei/open-api", **kwargs):
        super().__init__(**kwargs)
        self.lang = lang
        self.base_url = base_url.rstrip("/")

    def _url(self, path: str, **params) -> str:
        clean = {k: v for k, v in params.items() if v not in (None, "")}
        suffix = f"?{urlencode(clean)}" if clean else ""
        return f"{self.base_url}/{self.lang}/{path.lstrip('/')}{suffix}"

    def get_attractions_page(self, page: int = 1, category_id: int | None = None) -> dict:
        return self.request_json("GET", self._url("Attractions/All", page=page, categoryIds=category_id))

    def get_all_attractions(self, max_pages: int | None = None) -> list[dict]:
        rows: list[dict] = []
        page = 1
        while True:
            payload = self.get_attractions_page(page=page)
            data = payload.get("data") if isinstance(payload, dict) else None
            if not data:
                break
            rows.extend(data)
            total = payload.get("total") or payload.get("total_page") or payload.get("total_pages")
            if max_pages and page >= max_pages:
                break
            if total and page >= int(total):
                break
            page += 1
        return rows

    def get_categories(self) -> dict:
        return self.request_json("GET", self._url("Miscellaneous/Categories"))

    def get_places(self, max_pages: int | None = None) -> list[Place]:
        places: list[Place] = []
        for row in self.get_all_attractions(max_pages=max_pages):
            place = self.to_place(row)
            if place:
                places.append(place)
        return places

    def to_place(self, row: dict) -> Place | None:
        name = _first(row, "name", "Name", "title")
        if not name:
            return None
        district = _first(row, "distric", "district", "District")
        lat = to_float(_first(row, "latitude", "lat", "PositionLat"))
        lon = to_float(_first(row, "longitude", "lon", "PositionLon"))
        if district and not is_taipei_district(district):
            return None
        if not is_coordinate_in_taipei(lat, lon):
            return None

        images = []
        for image in row.get("images", []) or []:
            if isinstance(image, dict):
                src = image.get("src") or image.get("url")
                if src:
                    images.append(src)

        categories = []
        for item in row.get("category", []) or row.get("categories", []) or []:
            if isinstance(item, dict):
                value = item.get("name") or item.get("Name")
            else:
                value = str(item)
            if value:
                categories.append(value)
        if not categories:
            categories.append("attraction")

        source_id = str(row.get("id") or row.get("Id") or "")
        return Place(
            id=make_canonical_id(name, district),
            name=str(name),
            city="臺北市",
            district=district,
            description=_first(row, "introduction", "description", "Description"),
            lat=lat,
            lon=lon,
            address=_first(row, "address", "Address"),
            categories=categories,
            source_ids={self.source_name: source_id} if source_id else {},
            official_urls=[u for u in [_first(row, "url", "official_site", "website")] if u],
            image_urls=images,
            opening_hours=_first(row, "open_time", "openTime", "service_time"),
            phone=_first(row, "tel", "phone"),
            updated_at=_first(row, "modified", "updated_at", "UpdateTime"),
            sources=[self.source_name],
            raw=row,
        )


def _first(row: dict, *keys: str):
    for key in keys:
        value = row.get(key)
        if value not in (None, "", []):
            return value
    return None
