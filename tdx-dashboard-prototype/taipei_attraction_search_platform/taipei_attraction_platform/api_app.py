"""Optional FastAPI app.

Install optional dependencies first:
  pip install fastapi uvicorn

Run:
  uvicorn taipei_attraction_platform.api_app:app --reload
"""

from __future__ import annotations

from pathlib import Path

try:
    from fastapi import FastAPI
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("請先安裝 optional dependency：pip install fastapi uvicorn") from exc

from .services.search_service import TaipeiAttractionSearchService

CACHE = Path("data/taipei_places.json")
app = FastAPI(title="Taipei Attraction Search Platform", version="1.0.0")


def get_service() -> TaipeiAttractionSearchService:
    service = TaipeiAttractionSearchService.from_cache(CACHE) if CACHE.exists() else TaipeiAttractionSearchService(cache_path=CACHE)
    if not service.index.places:
        service.build()
    return service


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/build")
def build(with_optional: bool = False):
    service = TaipeiAttractionSearchService(cache_path=CACHE)
    report = service.build(include_optional_nearby=with_optional)
    return {"final_count": report.final_count, "fetched_counts": report.fetched_counts, "errors": report.errors}


@app.get("/places/search")
def search_places(
    q: str | None = None,
    district: str | None = None,
    category: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_m: int | None = None,
    limit: int = 20,
):
    service = get_service()
    results = service.search(query=q, district=district, category=category, lat=lat, lon=lon, radius_m=radius_m, limit=limit)
    return {"count": len(results), "results": [r.to_dict() for r in results]}


@app.get("/districts")
def districts():
    service = get_service()
    return service.districts()
