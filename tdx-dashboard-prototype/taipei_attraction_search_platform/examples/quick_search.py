from taipei_attraction_platform import TaipeiAttractionSearchService

service = TaipeiAttractionSearchService(cache_path="data/taipei_places.json")
report = service.build()
print("索引筆數：", report.final_count)

for result in service.search(query="夜市", limit=5):
    place = result.place
    print(place.name, place.district, result.score, place.sources)
