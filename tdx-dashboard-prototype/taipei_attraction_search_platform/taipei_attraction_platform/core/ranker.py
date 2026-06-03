"""Search scoring."""

from __future__ import annotations

from datetime import datetime, timezone

from .geo import distance_score as calc_distance_score, haversine_m
from .models import Place, SearchQuery, SearchResult
from .text import normalize_text, tokenize


def text_relevance(place: Place, query: str | None, category: str | None = None) -> float:
    if not query and not category:
        return 1.0

    blob = place.search_blob()
    score = 0.0

    if query:
        q = normalize_text(query)
        tokens = tokenize(q)
        if q and q in blob:
            score += 0.55
        if place.name and q in normalize_text(place.name):
            score += 0.25
        if tokens:
            matched = sum(1 for token in tokens if token in blob)
            score += 0.35 * matched / len(tokens)

    if category:
        cat = normalize_text(category)
        category_blob = normalize_text(" ".join(place.categories))
        if cat and cat in category_blob:
            score += 0.25

    return min(score, 1.0)


def popularity_score(place: Place) -> float:
    if place.popularity is not None:
        return max(0.0, min(float(place.popularity), 1.0))
    if place.rating is not None:
        return max(0.0, min(float(place.rating) / 5.0, 1.0))
    # Multiple sources often imply a more important POI.
    return min(len(set(place.sources)) / 5.0, 1.0) * 0.55


def freshness_score(place: Place) -> float:
    if not place.updated_at:
        return 0.35
    raw = str(place.updated_at).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).days
    except ValueError:
        return 0.45
    if age_days <= 30:
        return 1.0
    if age_days <= 180:
        return 0.8
    if age_days <= 365:
        return 0.65
    return 0.45


def score_place(place: Place, search_query: SearchQuery) -> SearchResult:
    distance_m = haversine_m(search_query.lat, search_query.lon, place.lat, place.lon)
    ts = text_relevance(place, search_query.query, search_query.category)
    ds = calc_distance_score(distance_m, search_query.radius_m)
    qs = place.quality_score()
    ps = popularity_score(place)
    fs = freshness_score(place)

    # Quality is deliberately part of the score so low-information places do not outrank richer official records.
    final = (0.34 * ts) + (0.22 * ds) + (0.24 * qs) + (0.12 * ps) + (0.08 * fs)
    return SearchResult(
        place=place,
        score=round(final, 6),
        distance_m=distance_m,
        text_score=ts,
        distance_score=ds,
        quality_score=qs,
        popularity_score=ps,
        freshness_score=fs,
    )
