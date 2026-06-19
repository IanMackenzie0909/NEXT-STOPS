"""Configuration, paths, and client-module loading for NEXT STOPS."""

from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
ATTRACTION_PLATFORM_ROOT = ROOT / "taipei_attraction_search_platform"
ATTRACTION_CACHE = ATTRACTION_PLATFORM_ROOT / "data" / "taipei_places.json"
GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
DEFAULT_MAPBOX_TOKEN = "your_mapbox_access_token"
MAX_STATION_RESULTS = 300

SAMPLE_LOCATIONS = [
    {"name": "臺北車站", "lat": 25.0478, "lon": 121.5170},
    {"name": "信義區市府", "lat": 25.0375, "lon": 121.5637},
    {"name": "士林夜市", "lat": 25.0881, "lon": 121.5240},
    {"name": "北投溫泉", "lat": 25.1368, "lon": 121.5064},
    {"name": "南港展覽館", "lat": 25.0553, "lon": 121.6175},
]

LOCATION_HINTS = {
    "taipei_main": {"lat": 25.0478, "lon": 121.5170, "district": "中正區", "label": "台北車站"},
    "xinyi": {"lat": 25.0339, "lon": 121.5645, "district": "信義區", "label": "信義區"},
    "daan": {"lat": 25.0262, "lon": 121.5353, "district": "大安區", "label": "大安森林公園"},
    "songshan": {"lat": 25.0496, "lon": 121.5777, "district": "松山區", "label": "松山"},
}

FRONTEND_MOOD_TO_ALGORITHM = {
    "relaxing_walk": "relax",
    "date": "date",
    "solo_quiet": "solo",
    "photo": "photo",
    "rainy_backup": "solo",
    "night_out": "night",
}

MOOD_LABELS = {
    "relaxing_walk": "散步放鬆",
    "date": "約會",
    "solo_quiet": "一個人安靜",
    "photo": "拍照探索",
    "rainy_backup": "雨天備案",
    "night_out": "夜晚出門",
}

MOOD_QUERIES = {
    "relaxing_walk": ["公園", "步道", "河濱"],
    "date": ["景觀", "文創", "餐廳"],
    "solo_quiet": ["博物館", "書店", "紀念館"],
    "photo": ["景點", "古蹟", "藝術"],
    "rainy_backup": ["博物館", "美術館", "文創"],
    "night_out": ["夜市", "商圈", "景觀"],
}

CATEGORY_LABELS = {
    "cafe": "咖啡",
    "park": "公園",
    "museum": "博物館",
    "market": "市集",
    "bookstore": "書店",
    "riverside": "河濱",
    "gallery": "藝文",
    "venue": "場館",
    "restaurant": "餐飲",
    "viewpoint": "景觀",
    "scenic_spot": "景點",
    "attraction": "景點",
    "taipei_featured": "精選景點",
}

OPENING_UNKNOWN_ALLOWED_CATEGORIES = {"park", "riverside", "viewpoint"}
PASSWORD_PATTERN = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$_-])[A-Za-z\d@$_-]{8,16}$")

FEEDBACK_WEIGHT_RULES = {
    "too_far": {"distance": 0.16},
    "too_expensive": {"budget": 0.16},
    "prefer_indoor": {"weather": 0.14, "environment": 0.12},
    "prefer_quieter": {"mood": 0.08, "quality": 0.06},
    "prefer_scenic": {"mood": 0.08, "quality": 0.06},
    "good_fit": {"mood": 0.05, "quality": 0.05},
    "not_my_vibe": {"mood": 0.08},
}


def load_root_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def load_module(module_name: str, filename: str):
    module_path = ROOT / filename
    return load_module_from_path(module_name, module_path)


def load_module_from_path(module_name: str, module_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def ensure_attraction_platform_on_path() -> None:
    if str(ATTRACTION_PLATFORM_ROOT) not in sys.path:
        sys.path.insert(0, str(ATTRACTION_PLATFORM_ROOT))
