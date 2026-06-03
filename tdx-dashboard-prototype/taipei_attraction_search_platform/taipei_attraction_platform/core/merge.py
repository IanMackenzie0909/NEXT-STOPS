"""Deduplicate and merge place records from multiple sources."""

from __future__ import annotations

import hashlib
from collections import defaultdict

from .geo import haversine_m
from .models import Place
from .text import fuzzy_ratio, normalize_text


SOURCE_PRIORITY = [
    "taipei_travel",
    "tdx_tourism",
    "taipei_open_data",
    "geoapify",
    "opentripmap",
    "overpass",
    "foursquare",
]


def make_canonical_id(name: str, district: str | None = None) -> str:
    base = normalize_text(f"{name}-{district or ''}").replace(" ", "-") or "place"
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:10]
    return f"place_tpe_{digest}"


def is_same_place(a: Place, b: Place) -> bool:
    ratio = fuzzy_ratio(a.name, b.name)
    distance = haversine_m(a.lat, a.lon, b.lat, b.lon)

    if ratio >= 0.92:
        if a.district and b.district:
            return normalize_text(a.district) == normalize_text(b.district)
        return True

    if distance is not None:
        return ratio >= 0.78 and distance <= 120

    return False


def _pick_text(current: str | None, incoming: str | None) -> str | None:
    if not incoming:
        return current
    if not current:
        return incoming
    # Prefer the richer text.
    return incoming if len(str(incoming)) > len(str(current)) else current


def _merge_unique(a: list[str], b: list[str]) -> list[str]:
    seen = set()
    merged: list[str] = []
    for item in [*a, *b]:
        if item is None:
            continue
        key = normalize_text(item)
        if key and key not in seen:
            merged.append(str(item))
            seen.add(key)
    return merged


def merge_places(base: Place, incoming: Place) -> Place:
    base.aliases = _merge_unique(base.aliases, [incoming.name, *incoming.aliases])
    base.description = _pick_text(base.description, incoming.description)
    base.address = base.address or incoming.address
    base.district = base.district or incoming.district
    base.city = base.city or incoming.city or "臺北市"
    base.lat = base.lat if base.lat is not None else incoming.lat
    base.lon = base.lon if base.lon is not None else incoming.lon
    base.categories = _merge_unique(base.categories, incoming.categories)
    base.official_urls = _merge_unique(base.official_urls, incoming.official_urls)
    base.image_urls = _merge_unique(base.image_urls, incoming.image_urls)
    base.sources = _merge_unique(base.sources, incoming.sources)
    base.opening_hours = base.opening_hours or incoming.opening_hours
    base.phone = base.phone or incoming.phone
    base.rating = max([v for v in [base.rating, incoming.rating] if v is not None], default=None)
    base.popularity = max([v for v in [base.popularity, incoming.popularity] if v is not None], default=None)
    base.updated_at = max([v for v in [base.updated_at, incoming.updated_at] if v], default=None)
    base.source_ids.update({k: v for k, v in incoming.source_ids.items() if v})
    # Keep raw as a source-keyed dictionary so debugging is easier.
    for source in incoming.sources:
        if source:
            base.raw[source] = incoming.raw
    return base


def deduplicate_places(places: list[Place]) -> list[Place]:
    # First bucket by normalized leading characters to avoid O(n^2) across all Taipei records.
    buckets: dict[str, list[Place]] = defaultdict(list)
    for place in places:
        key = (place.normalized_name()[:2] or "__") + "|" + normalize_text(place.district or "")
        buckets[key].append(place)

    merged: list[Place] = []
    for bucket in buckets.values():
        local: list[Place] = []
        for place in bucket:
            target = None
            for candidate in local:
                if is_same_place(candidate, place):
                    target = candidate
                    break
            if target is None:
                place.id = place.id or make_canonical_id(place.name, place.district)
                local.append(place)
            else:
                merge_places(target, place)
        merged.extend(local)

    # A second global pass catches cases where district was missing in one source.
    final: list[Place] = []
    for place in merged:
        target = None
        for candidate in final:
            if is_same_place(candidate, place):
                target = candidate
                break
        if target is None:
            final.append(place)
        else:
            merge_places(target, place)
    return sorted(final, key=lambda p: (p.district or "", p.name))
