import re
import time
from html import unescape

import requests


TRAVEL_TAIPEI_BASE_URL = "https://www.travel.taipei/open-api/zh-tw"
ATTRACTIONS_URL = f"{TRAVEL_TAIPEI_BASE_URL}/Attractions/All"
EVENTS_URL = f"{TRAVEL_TAIPEI_BASE_URL}/Events/Activity"
DATASET_URL = ATTRACTIONS_URL
DEFAULT_PAGES = 1


class TaipeiOpenDataError(Exception):
    pass


class TaipeiAttractionClient:
    def __init__(self, attractions_url=ATTRACTIONS_URL, events_url=EVENTS_URL):
        self.attractions_url = attractions_url
        self.events_url = events_url

    def get_response(self, url, params=None, retries=2):
        request_params = params or {}

        for attempt in range(retries + 1):
            response = requests.get(
                url,
                params=request_params,
                headers={"accept": "application/json"},
                timeout=12,
            )

            if response.status_code == 429:
                retry_after = parse_int(response.headers.get("Retry-After"), 3)
                if attempt < retries:
                    time.sleep(retry_after)
                    continue
                raise TaipeiOpenDataError("Travel Taipei API request limit reached. Please try again later.")

            response.raise_for_status()
            payload = response.json()
            if "data" not in payload:
                raise TaipeiOpenDataError(f"Unexpected Travel Taipei response: {payload!r}")
            return payload

        return {"total": 0, "data": []}

    def get_attraction_rows(self, pages=DEFAULT_PAGES):
        return self._get_rows(self.attractions_url, pages=pages)

    def get_event_rows(self, pages=DEFAULT_PAGES):
        return self._get_rows(self.events_url, pages=pages)

    def _get_rows(self, url, pages=DEFAULT_PAGES):
        rows = []
        for page in range(1, max(1, pages) + 1):
            payload = self.get_response(url, params={"page": page})
            page_rows = payload.get("data", [])
            rows.extend(page_rows)
            if not page_rows:
                break
        return rows

    def get_places(self, pages=DEFAULT_PAGES, include_events=True):
        places = [
            serialize_attraction(row)
            for row in self.get_attraction_rows(pages=pages)
        ]

        if include_events:
            places.extend(
                serialize_event(row)
                for row in self.get_event_rows(pages=pages)
            )

        return [
            place
            for place in places
            if place["name"]
        ]

    def get_districts(self, pages=DEFAULT_PAGES):
        return group_places_by_district(self.get_places(pages=pages))


def parse_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_float(value):
    try:
        if value in ("", None):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def clean_text(value, limit=None):
    text = unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if limit and len(text) > limit:
        return f"{text[:limit].rstrip()}..."
    return text


def first_image(images):
    if not isinstance(images, list) or not images:
        return ""
    image = images[0] or {}
    return image.get("src", "")


def category_names(categories):
    if not isinstance(categories, list):
        return []
    return [
        clean_text(category.get("name"))
        for category in categories
        if isinstance(category, dict) and clean_text(category.get("name"))
    ]


def serialize_attraction(row):
    categories = category_names(row.get("category"))
    name = clean_text(row.get("name") or row.get("name_zh"))
    district = clean_text(row.get("distric"))
    address = clean_text(row.get("address"))
    return {
        "id": f"attraction-{row.get('id', name)}",
        "source_id": row.get("id"),
        "type": "attraction",
        "type_label": "景點",
        "name": name,
        "district": district,
        "address": address,
        "lat": parse_float(row.get("nlat")),
        "lng": parse_float(row.get("elong")),
        "category": "、".join(categories),
        "theme": "、".join(categories),
        "open_status": row.get("open_status"),
        "open_time": clean_text(row.get("open_time"), limit=140),
        "begin": "",
        "end": "",
        "description": clean_text(row.get("introduction"), limit=180),
        "image": first_image(row.get("images")),
        "url": row.get("url", ""),
        "modified": row.get("modified", ""),
        "query": build_query(name, address, district),
        "raw": row,
    }


def serialize_event(row):
    title = clean_text(row.get("title"))
    district = clean_text(row.get("distric"))
    address = clean_text(row.get("address"))
    return {
        "id": f"event-{row.get('id', title)}",
        "source_id": row.get("id"),
        "type": "event",
        "type_label": "活動",
        "name": title,
        "district": district,
        "address": address,
        "lat": parse_float(row.get("nlat")),
        "lng": parse_float(row.get("elong")),
        "category": "活動展演",
        "theme": "活動展演",
        "open_status": "",
        "open_time": "",
        "begin": row.get("begin", ""),
        "end": row.get("end", ""),
        "description": clean_text(row.get("description"), limit=180),
        "image": "",
        "url": row.get("url", ""),
        "modified": row.get("modified", ""),
        "query": build_query(title, address, district),
        "raw": row,
    }


def build_query(name, address, district):
    parts = [name, address, district, "台北市"]
    return " ".join(part for part in parts if part)


def group_places_by_district(places):
    grouped = {}
    for place in places:
        district = place.get("district") or "未標示行政區"
        if district not in grouped:
            grouped[district] = {
                "id": district,
                "dataset": "Travel Taipei Open API",
                "city": "台北市",
                "city_code": "TPE",
                "district": district,
                "theme": "景點與活動",
                "attractions": [],
                "places": [],
                "attraction_count": 0,
                "import_time": "",
                "raw": {},
            }
        grouped[district]["attractions"].append(place["name"])
        grouped[district]["places"].append(place)
        grouped[district]["attraction_count"] += 1
        grouped[district]["import_time"] = max(
            grouped[district]["import_time"],
            place.get("modified", ""),
        )
    return list(grouped.values())


def normalize_search_text(value):
    return str(value or "").strip().lower()


def search_places(places, query):
    query = normalize_search_text(query)
    if not query:
        return places

    matches = []
    for place in places:
        haystack = normalize_search_text(
            " ".join([
                place.get("name", ""),
                place.get("type_label", ""),
                place.get("district", ""),
                place.get("address", ""),
                place.get("category", ""),
                place.get("begin", ""),
                place.get("end", ""),
            ])
        )
        if query in haystack:
            matches.append(place)
    return matches


def search_districts(districts, query):
    query = normalize_search_text(query)
    if not query:
        return districts

    matches = []
    for district in districts:
        haystack = normalize_search_text(
            " ".join([
                district.get("district", ""),
                district.get("theme", ""),
                " ".join(district.get("attractions", [])),
            ])
        )
        if query in haystack:
            matches.append(district)
    return matches


def print_place_table(places):
    if not places:
        print("No Taipei places found.")
        return

    print(f"Loaded {len(places)} Taipei places from Travel Taipei Open API.")
    for place in places:
        district = place.get("district") or "-"
        category = place.get("category") or "-"
        print(f"[{place['type_label']}] {place['name']} / {district} / {category}")


if __name__ == "__main__":
    client = TaipeiAttractionClient()
    try:
        print_place_table(client.get_places())
    except requests.HTTPError as exc:
        print(f"Travel Taipei request failed: {exc}")
    except TaipeiOpenDataError as exc:
        print(exc)
