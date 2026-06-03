"""CLI entry point.

Examples:
  python -m taipei_attraction_platform build --cache data/taipei_places.json
  python -m taipei_attraction_platform search --query 夜市 --district 萬華區
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .services.search_service import TaipeiAttractionSearchService

DEFAULT_CACHE = Path("data/taipei_places.json")


def main() -> None:
    parser = argparse.ArgumentParser(description="台北市景點搜尋平台 API Client")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="抓取並建立台北市景點索引")
    build.add_argument("--cache", default=str(DEFAULT_CACHE), help="索引快取 JSON 路徑")
    build.add_argument("--sources", default="taipei_open_data,taipei_travel", help="逗號分隔來源，例如 taipei_open_data,taipei_travel,tdx_tourism")
    build.add_argument("--with-optional", action="store_true", help="同時嘗試需要金鑰或附近查詢的外部來源")

    search = sub.add_parser("search", help="搜尋台北市景點")
    search.add_argument("--cache", default=str(DEFAULT_CACHE), help="索引快取 JSON 路徑")
    search.add_argument("--query", default=None, help="關鍵字，例如 夜市、博物館、親子")
    search.add_argument("--district", default=None, help="行政區，例如 萬華區")
    search.add_argument("--category", default=None, help="分類，例如 museum、night_market、溫泉")
    search.add_argument("--lat", type=float, default=None, help="查詢中心緯度")
    search.add_argument("--lon", type=float, default=None, help="查詢中心經度")
    search.add_argument("--radius", type=int, default=None, help="半徑，單位公尺")
    search.add_argument("--limit", type=int, default=10, help="回傳筆數")
    search.add_argument("--json", action="store_true", help="輸出 JSON")

    districts = sub.add_parser("districts", help="列出索引中的行政區統計")
    districts.add_argument("--cache", default=str(DEFAULT_CACHE), help="索引快取 JSON 路徑")

    args = parser.parse_args()

    if args.command == "build":
        sources = [s.strip() for s in args.sources.split(",") if s.strip()]
        service = TaipeiAttractionSearchService(cache_path=args.cache)
        report = service.build(sources=sources, include_optional_nearby=args.with_optional)
        print("建立完成")
        print(f"快取：{args.cache}")
        print(f"去重後景點數：{report.final_count}")
        print("來源筆數：", json.dumps(report.fetched_counts, ensure_ascii=False))
        if report.errors:
            print("部分來源略過或失敗：", json.dumps(report.errors, ensure_ascii=False, indent=2))
        return

    if args.command == "search":
        service = _load_or_build(args.cache)
        results = service.search(
            query=args.query,
            district=args.district,
            category=args.category,
            lat=args.lat,
            lon=args.lon,
            radius_m=args.radius,
            limit=args.limit,
        )
        if args.json:
            print(json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2))
        else:
            _print_results(results)
        return

    if args.command == "districts":
        service = _load_or_build(args.cache)
        for district, count in service.districts().items():
            print(f"{district}: {count}")
        return


def _load_or_build(cache_path: str) -> TaipeiAttractionSearchService:
    path = Path(cache_path)
    service = TaipeiAttractionSearchService.from_cache(path) if path.exists() else TaipeiAttractionSearchService(cache_path=path)
    if not service.index.places:
        print("找不到索引快取，正在用公開來源建立基本索引...")
        service.build()
    return service


def _print_results(results) -> None:
    if not results:
        print("沒有找到符合條件的台北市景點。")
        return
    for i, result in enumerate(results, start=1):
        place = result.place
        distance = f"｜{int(result.distance_m)}m" if result.distance_m is not None else ""
        print(f"{i}. {place.name}｜{place.district or '未標示'}{distance}｜score={result.score:.3f}｜quality={place.quality_score():.2f}")
        if place.address:
            print(f"   地址：{place.address}")
        if place.categories:
            print(f"   分類：{', '.join(place.categories[:6])}")
        if place.sources:
            print(f"   來源：{', '.join(place.sources)}")
        if place.description:
            summary = place.description.replace("\n", " ")[:90]
            print(f"   摘要：{summary}{'...' if len(place.description) > 90 else ''}")


if __name__ == "__main__":
    main()
