# Implementation Notes

## 已完成的重構

1. **保留原本臺北市資料大平臺能力**
   - 原始檔名 `Attraction_OpenAPI-clients.py` 保留為 compatibility wrapper。
   - 實際實作移到 `taipei_attraction_platform/clients/taipei_open_data.py`。

2. **新增七個資料平台 Client**
   - `TaipeiOpenDataClient`
   - `TaipeiTravelClient`
   - `TdxTourismClient`
   - `OverpassClient`
   - `OpenTripMapClient`
   - `GeoapifyPlacesClient`
   - `FoursquarePlacesClient`

3. **台北市限定**
   - `config.py` 內有台北市行政區白名單。
   - 也有台北市 bounding box，避免外部 API 回傳非台北市資料。

4. **統一 Place schema**
   - 所有來源都轉成 `Place` dataclass。
   - 欄位包含名稱、行政區、座標、地址、分類、圖片、來源 ID、官方 URL、營業時間、電話、品質分數等。

5. **去重與合併**
   - `core/merge.py` 用名稱相似度、行政區、座標距離做合併。
   - 同一景點來自不同來源時會保留所有 `source_ids` 與 `sources`。

6. **搜尋與排序**
   - `core/index.py` 提供 in-memory index。
   - `core/ranker.py` 加入：
     - text_score
     - distance_score
     - quality_score
     - popularity_score
     - freshness_score

7. **CLI**
   - `python -m taipei_attraction_platform build`
   - `python -m taipei_attraction_platform search --query 夜市`
   - `python -m taipei_attraction_platform districts`

8. **Optional FastAPI**
   - `taipei_attraction_platform/api_app.py`
   - 不強制安裝 FastAPI，避免增加基本安裝負擔。

## 注意事項

- TDX、OpenTripMap、Geoapify、Foursquare 需要 API key。
- 沒有 API key 時，這些來源會被略過，不會影響公開來源建立索引。
- Foursquare 近年 endpoint 有遷移情況，因此 `FOURSQUARE_BASE_URL` 可用環境變數覆蓋。
- 預設 build 只使用：
  - 臺北市資料大平臺
  - 臺北旅遊網 Open API

## 下一步可加強

- 換成 PostgreSQL + PostGIS。
- 加入 SQLite FTS5。
- 加入真正的 autocomplete index。
- 加入地鐵站/公車站可達性分數。
- 加入前端搜尋頁。
- 加入排程每日更新 cache。
