"""Simple JSON cache for normalized places."""

from __future__ import annotations

import json
from pathlib import Path

from ..core.models import Place


class JsonPlaceCache:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> list[Place]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        places = payload.get("places", payload if isinstance(payload, list) else [])
        return [Place(**_clean_place_dict(item)) for item in places]

    def save(self, places: list[Place]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "count": len(places),
            "places": [place.to_dict() | {"distance_m": None} for place in places],
        }
        # Remove computed fields before saving back into dataclass-compatible JSON.
        for item in payload["places"]:
            item.pop("quality_score", None)
            item.pop("distance_m", None)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _clean_place_dict(item: dict) -> dict:
    allowed = set(Place.__dataclass_fields__.keys())
    return {k: v for k, v in item.items() if k in allowed}
