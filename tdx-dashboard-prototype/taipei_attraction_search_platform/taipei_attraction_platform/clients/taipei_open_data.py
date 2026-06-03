"""Client for Taipei City Data Platform featured-attraction dataset.

This file preserves the behavior of the original Attraction_OpenAPI-clients.py,
but expands district rows into normalized Place records.
"""

from __future__ import annotations

import re
from urllib.parse import urlencode

from .base import BaseHttpClient, ApiClientError
from ..core.merge import make_canonical_id
from ..core.models import Place
from ..config import is_taipei_district

DATASET_URL = "https://data.taipei/api/v1/dataset/36847f3f-deff-4183-a5bb-800737591de5"
DEFAULT_SCOPE = "resourceAquire"
DEFAULT_LIMIT = 100


class TaipeiOpenDataClient(BaseHttpClient):
    source_name = "taipei_open_data"

    def __init__(self, base_url: str = DATASET_URL, **kwargs):
        super().__init__(**kwargs)
        self.base_url = base_url

    def get_response(self, limit: int = DEFAULT_LIMIT, offset: int = 0) -> dict:
        params = {"scope": DEFAULT_SCOPE, "limit": limit, "offset": offset}
        url = f"{self.base_url}?{urlencode(params)}"
        payload = self.request_json("GET", url)
        if not isinstance(payload, dict) or "result" not in payload:
            raise ApiClientError(f"Unexpected Taipei Open Data response: {payload!r}")
        return payload

    def get_all_rows(self, limit: int = DEFAULT_LIMIT) -> list[dict]:
        rows: list[dict] = []
        offset = 0
        total: int | None = None
        while total is None or offset < total:
            payload = self.get_response(limit=limit, offset=offset)
            result = payload.get("result", {})
            page_rows = result.get("results", []) or []
            total = _parse_int(result.get("count"), len(page_rows))
            rows.extend(page_rows)
            if not page_rows:
                break
            offset += _parse_int(result.get("limit"), limit)
        return rows

    def get_district_rows(self) -> list[dict]:
        return [serialize_district(row) for row in self.get_all_rows()]

    def get_places(self) -> list[Place]:
        places: list[Place] = []
        for row in self.get_district_rows():
            district = row.get("district")
            if district and not is_taipei_district(district):
                continue
            theme = row.get("theme") or "精選景點"
            for attraction_name in row.get("attractions", []):
                places.append(Place(
                    id=make_canonical_id(attraction_name, district),
                    name=attraction_name,
                    city="臺北市",
                    district=district,
                    categories=[theme, "taipei_featured"],
                    sources=[self.source_name],
                    source_ids={self.source_name: str(row.get("id") or "")},
                    updated_at=row.get("import_time"),
                    raw=row,
                ))
        return places


def parse_attractions(value: object) -> list[str]:
    if not value:
        return []
    attractions: list[str] = []
    for line in str(value).splitlines():
        name = re.sub(r"^\s*\d+[.、]\s*", "", line).strip()
        if name:
            attractions.append(name)
    return attractions


def get_import_time(row: dict) -> str:
    import_date = row.get("_importdate", {})
    if isinstance(import_date, dict):
        return import_date.get("date", "")
    return ""


def serialize_district(row: dict) -> dict:
    attractions = parse_attractions(row.get("精選景點", ""))
    return {
        "id": row.get("_id", ""),
        "dataset": row.get("資料項目", ""),
        "city": row.get("縣市別", ""),
        "city_code": row.get("縣市別代碼", ""),
        "district": row.get("行政區", ""),
        "theme": row.get("主題景點", ""),
        "attractions": attractions,
        "attraction_count": len(attractions),
        "import_time": get_import_time(row),
        "raw": row,
    }


def _parse_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
