"""Fetch, normalize and merge Taipei-only places from all configured sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from ..clients import (
    TaipeiOpenDataClient,
    TaipeiTravelClient,
    TdxTourismClient,
    OverpassClient,
    OpenTripMapClient,
    GeoapifyPlacesClient,
    FoursquarePlacesClient,
)
from ..clients.base import ApiClientError, ClientConfigError
from ..core.index import PlaceIndex
from ..core.models import Place


DEFAULT_PUBLIC_SOURCES = ("taipei_open_data", "tdx_tourism")
DEFAULT_OPTIONAL_SOURCES = ("overpass", "opentripmap", "geoapify", "foursquare")

# Taipei 101 as a safe default seed point for optional nearby APIs.
DEFAULT_SEED_POINTS = [
    (25.033976, 121.564538, "臺北101"),
    (25.042141, 121.519872, "中正紀念堂"),
    (25.136940, 121.506858, "北投溫泉"),
]


@dataclass
class IngestionReport:
    fetched_counts: dict[str, int] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    final_count: int = 0


class TaipeiIngestionService:
    def __init__(self):
        self.report = IngestionReport()

    def fetch_sources(
        self,
        sources: Iterable[str] = DEFAULT_PUBLIC_SOURCES,
        include_optional_nearby: bool = False,
        optional_seed_points: list[tuple[float, float, str]] | None = None,
    ) -> tuple[list[Place], IngestionReport]:
        source_set = set(sources)
        if include_optional_nearby:
            source_set.update(DEFAULT_OPTIONAL_SOURCES)

        places: list[Place] = []
        self.report = IngestionReport()

        def collect(name: str, func):
            try:
                rows = func()
                places.extend(rows)
                self.report.fetched_counts[name] = len(rows)
            except ClientConfigError as exc:
                self.report.errors[name] = str(exc)
            except ApiClientError as exc:
                self.report.errors[name] = str(exc)
            except Exception as exc:  # Defensive: one provider should not kill the whole build.
                self.report.errors[name] = f"Unexpected error: {exc}"

        if "taipei_open_data" in source_set:
            collect("taipei_open_data", lambda: TaipeiOpenDataClient().get_places())
        if "taipei_travel" in source_set:
            collect("taipei_travel", lambda: TaipeiTravelClient().get_places(max_pages=None))
        if "tdx_tourism" in source_set:
            collect("tdx_tourism", lambda: TdxTourismClient().get_places(max_pages=20))

        seed_points = optional_seed_points or DEFAULT_SEED_POINTS
        if "overpass" in source_set:
            collect("overpass", lambda: _collect_nearby(OverpassClient(), seed_points))
        if "opentripmap" in source_set:
            collect("opentripmap", lambda: _collect_nearby(OpenTripMapClient(), seed_points))
        if "geoapify" in source_set:
            collect("geoapify", lambda: _collect_nearby(GeoapifyPlacesClient(), seed_points))
        if "foursquare" in source_set:
            collect("foursquare", lambda: _collect_nearby(FoursquarePlacesClient(), seed_points))

        index = PlaceIndex(places)
        self.report.final_count = len(index.places)
        return index.places, self.report


def _collect_nearby(client, seed_points: list[tuple[float, float, str]], radius_m: int = 2500) -> list[Place]:
    places: list[Place] = []
    for lat, lon, label in seed_points:
        try:
            if isinstance(client, FoursquarePlacesClient):
                places.extend(client.get_places_nearby(lat, lon, radius_m, query=label))
            else:
                places.extend(client.get_places_nearby(lat, lon, radius_m))
        except ClientConfigError:
            raise
        except ApiClientError:
            raise
    return places
