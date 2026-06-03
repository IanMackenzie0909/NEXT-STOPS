"""Backward-compatible wrapper for the original script name.

The original file only fetched Taipei City Data Platform district rows.
This wrapper keeps that behavior but delegates to the new package.
"""

from taipei_attraction_platform.clients.taipei_open_data import (
    TaipeiOpenDataClient as TaipeiAttractionClient,
    DATASET_URL,
    DEFAULT_LIMIT,
    DEFAULT_SCOPE,
    parse_attractions,
    serialize_district,
)
from taipei_attraction_platform.core.text import normalize_text as normalize_search_text


def search_districts(districts, query):
    query = normalize_search_text(query)
    if not query:
        return districts
    matches = []
    for district in districts:
        haystack = normalize_search_text(" ".join([
            district.get("district", ""),
            district.get("theme", ""),
            " ".join(district.get("attractions", [])),
        ]))
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
    print_district_table(client.get_district_rows())
