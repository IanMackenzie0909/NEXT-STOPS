"""Configuration helpers for Taipei-only attraction search."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


TAIPEI_CITY_NAMES = {"臺北市", "台北市", "Taipei", "Taipei City"}
TAIPEI_DISTRICTS = {
    "中正區", "大同區", "中山區", "松山區", "大安區", "萬華區",
    "信義區", "士林區", "北投區", "內湖區", "南港區", "文山區",
}

# Conservative bounding box around Taipei City. Used only as a safety filter.
TAIPEI_BBOX = {
    "min_lat": 24.94,
    "max_lat": 25.22,
    "min_lon": 121.43,
    "max_lon": 121.68,
}


def load_root_env() -> None:
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def env_first(*names: str) -> str | None:
    load_root_env()
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


@dataclass(frozen=True)
class ApiKeys:
    tdx_client_id: str | None = None
    tdx_client_secret: str | None = None
    opentripmap_api_key: str | None = None
    geoapify_api_key: str | None = None
    foursquare_api_key: str | None = None

    @classmethod
    def from_env(cls) -> "ApiKeys":
        return cls(
            tdx_client_id=env_first("TDX_TOURISM_CLIENT_ID", "TDX_CLIENT_ID"),
            tdx_client_secret=env_first("TDX_TOURISM_CLIENT_SECRET", "TDX_CLIENT_SECRET"),
            opentripmap_api_key=env_first("OPENTRIPMAP_API_KEY"),
            geoapify_api_key=env_first("GEOAPIFY_API_KEY"),
            foursquare_api_key=env_first("FOURSQUARE_API_KEY"),
        )


def is_taipei_district(value: str | None) -> bool:
    if not value:
        return False
    return str(value).strip().replace("台", "臺") in TAIPEI_DISTRICTS


def is_coordinate_in_taipei(lat: float | None, lon: float | None) -> bool:
    if lat is None or lon is None:
        return True
    return (
        TAIPEI_BBOX["min_lat"] <= lat <= TAIPEI_BBOX["max_lat"]
        and TAIPEI_BBOX["min_lon"] <= lon <= TAIPEI_BBOX["max_lon"]
    )
