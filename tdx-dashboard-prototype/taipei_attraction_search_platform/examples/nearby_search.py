from taipei_attraction_platform import TaipeiAttractionSearchService

service = TaipeiAttractionSearchService.from_cache("data/taipei_places.json")

# 台北101附近 2 公里內，以關鍵字「拍照」搜尋。
results = service.search(query="拍照", lat=25.033976, lon=121.564538, radius_m=2000, limit=10)
for r in results:
    print(r.place.name, r.place.district, int(r.distance_m or -1), r.score)
