from taipei_attraction_platform.core.index import PlaceIndex
from taipei_attraction_platform.core.models import Place, SearchQuery
from taipei_attraction_platform.core.merge import deduplicate_places


def test_deduplicate_same_place_name_and_district():
    places = [
        Place(id="a", name="台北 101", district="信義區", sources=["a"]),
        Place(id="b", name="臺北101", district="信義區", lat=25.033, lon=121.565, sources=["b"]),
    ]
    merged = deduplicate_places(places)
    assert len(merged) == 1
    assert set(merged[0].sources) == {"a", "b"}


def test_search_uses_quality_score():
    rich = Place(id="1", name="故宮博物院", district="士林區", lat=25.102, lon=121.548, description="國立故宮博物院", image_urls=["x"], sources=["taipei_travel", "tdx_tourism"])
    poor = Place(id="2", name="故宮周邊", district="士林區", sources=["taipei_open_data"])
    index = PlaceIndex([poor, rich])
    results = index.search(SearchQuery(query="故宮", limit=2))
    assert results[0].place.id == "1"
