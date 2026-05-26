import re
import time
from urllib.parse import urlencode

import requests


DATASET_URL = "https://data.taipei/api/v1/dataset/36847f3f-deff-4183-a5bb-800737591de5"
DEFAULT_SCOPE = "resourceAquire"
DEFAULT_LIMIT = 20


class TaipeiOpenDataError(Exception):
    pass


class TaipeiAttractionClient:
    def __init__(self, base_url=DATASET_URL):
        self.base_url = base_url

    def get_response(self, limit=DEFAULT_LIMIT, offset=0, retries=2):
        params = {
            "scope": DEFAULT_SCOPE,
            "limit": limit,
            "offset": offset,
        }
        url = f"{self.base_url}?{urlencode(params)}"

        for attempt in range(retries + 1):
            response = requests.get(url, timeout=10)

            if response.status_code == 429:
                retry_after = parse_int(response.headers.get("Retry-After"), 3)
                if attempt < retries:
                    time.sleep(retry_after)
                    continue
                raise TaipeiOpenDataError("Taipei Open Data request limit reached. Please try again later.")

            response.raise_for_status()
            payload = response.json()
            if "result" not in payload:
                raise TaipeiOpenDataError(f"Unexpected Taipei Open Data response: {payload!r}")
            return payload

        return {"result": {"results": [], "count": 0, "limit": limit, "offset": offset}}

    def get_all_rows(self, limit=DEFAULT_LIMIT):
        rows = []
        offset = 0
        total = None

        while total is None or offset < total:
            payload = self.get_response(limit=limit, offset=offset)
            result = payload.get("result", {})
            page_rows = result.get("results", [])
            total = parse_int(result.get("count"), len(page_rows))
            rows.extend(page_rows)

            if not page_rows:
                break

            offset += parse_int(result.get("limit"), limit)

        return rows

    def get_districts(self):
        return [serialize_district(row) for row in self.get_all_rows()]


def parse_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_attractions(value):
    if not value:
        return []

    attractions = []
    for line in str(value).splitlines():
        name = re.sub(r"^\s*\d+[.、]\s*", "", line).strip()
        if name:
            attractions.append(name)
    return attractions


def get_import_time(row):
    import_date = row.get("_importdate", {})
    if isinstance(import_date, dict):
        return import_date.get("date", "")
    return ""


def serialize_district(row):
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


def normalize_search_text(value):
    return str(value or "").strip().lower().replace("台", "臺")


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


def print_district_table(districts):
    if not districts:
        print("沒有找到臺北市景點資料")
        return

    print(f"臺北市官方景點資料，共 {len(districts)} 筆行政區資料")
    for district in districts:
        print()
        print(f"{district['district']}｜{district['theme']}")
        for attraction in district["attractions"]:
            print(f"- {attraction}")


if __name__ == "__main__":
    client = TaipeiAttractionClient()
    try:
        print_district_table(client.get_districts())
    except requests.HTTPError as exc:
        print(f"Taipei Open Data request failed: {exc}")
    except TaipeiOpenDataError as exc:
        print(exc)
