"""Client for MOTC TDX Tourism ScenicSpot API, limited to Taipei."""

from __future__ import annotations

from urllib.parse import urlencode

from .base import BaseHttpClient, ClientConfigError
from ..core.geo import to_float
from ..core.merge import make_canonical_id
from ..core.models import Place
from ..config import ApiKeys, is_coordinate_in_taipei


class TdxTourismClient(BaseHttpClient):
    source_name = "tdx_tourism"
    auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"

    def __init__(self, client_id: str | None = None, client_secret: str | None = None, base_url: str = "https://tdx.transportdata.tw/api/basic/v2", **kwargs):
        super().__init__(**kwargs)
        env = ApiKeys.from_env()
        self.client_id = client_id or env.tdx_client_id
        self.client_secret = client_secret or env.tdx_client_secret
        self.base_url = base_url.rstrip("/")
        self._token: str | None = None

    def _require_credentials(self) -> None:
        if not self.client_id or not self.client_secret:
            raise ClientConfigError("TDX_TOURISM_CLIENT_ID / TDX_TOURISM_CLIENT_SECRET 尚未設定，略過 TDX Tourism。")

    def get_token(self) -> str:
        self._require_credentials()
        if self._token:
            return self._token
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        token_data = self.request_json("POST", self.auth_url, data=payload)
        token = token_data.get("access_token") if isinstance(token_data, dict) else None
        if not token:
            raise ClientConfigError("TDX token 回應缺少 access_token。")
        self._token = token
        return token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.get_token()}", "Accept": "application/json"}

    def get_scenic_spots(self, top: int = 100, skip: int = 0, keyword: str | None = None) -> list[dict]:
        params = {"$top": top, "$skip": skip, "$format": "JSON"}
        if keyword:
            # TDX/OData V2.0 field names may vary between standards. ScenicSpotName is the common v2 field.
            params["$filter"] = f"contains(ScenicSpotName,'{keyword}')"
        url = f"{self.base_url}/Tourism/ScenicSpot/Taipei?{urlencode(params)}"
        payload = self.request_json("GET", url, headers=self._headers())
        return payload if isinstance(payload, list) else []

    def get_all_scenic_spots(self, page_size: int = 100, max_pages: int | None = 10) -> list[dict]:
        rows: list[dict] = []
        skip = 0
        pages = 0
        while True:
            page = self.get_scenic_spots(top=page_size, skip=skip)
            if not page:
                break
            rows.extend(page)
            pages += 1
            if max_pages and pages >= max_pages:
                break
            skip += page_size
        return rows

    def get_places(self, max_pages: int | None = 10) -> list[Place]:
        return [p for row in self.get_all_scenic_spots(max_pages=max_pages) if (p := self.to_place(row))]

    def to_place(self, row: dict) -> Place | None:
        name = _first(row, "ScenicSpotName", "AttractionName", "Name")
        if not name:
            return None
        position = row.get("Position") if isinstance(row.get("Position"), dict) else {}
        lat = to_float(_first(row, "PositionLat", "Latitude") or position.get("PositionLat"))
        lon = to_float(_first(row, "PositionLon", "Longitude") or position.get("PositionLon"))
        if not is_coordinate_in_taipei(lat, lon):
            return None
        images = []
        for image in row.get("Images", []) or row.get("Picture", []) or []:
            if isinstance(image, dict):
                src = image.get("ImageURL") or image.get("PictureUrl1") or image.get("Url")
                if src:
                    images.append(src)
        source_id = str(_first(row, "ScenicSpotID", "AttractionID", "ID") or "")
        return Place(
            id=make_canonical_id(str(name), _first(row, "City", "Town")),
            name=str(name),
            city="臺北市",
            district=_first(row, "Town", "District"),
            description=_first(row, "Description", "DescriptionDetail"),
            lat=lat,
            lon=lon,
            address=_first(row, "Address", "PostalAddress"),
            categories=[_first(row, "Class1", "Class") or "scenic_spot"],
            source_ids={self.source_name: source_id} if source_id else {},
            official_urls=[u for u in [_first(row, "WebsiteURL", "Url")] if u],
            image_urls=images,
            opening_hours=_first(row, "OpenTime", "ServiceTimeInfo"),
            phone=_first(row, "Phone", "Tel"),
            updated_at=_first(row, "UpdateTime", "SrcUpdateTime"),
            sources=[self.source_name],
            raw=row,
        )


def _first(row: dict, *keys: str):
    for key in keys:
        value = row.get(key)
        if value not in (None, "", []):
            return value
    return None
