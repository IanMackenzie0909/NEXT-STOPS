# Taipei Attraction Search Platform Client

這是一個把原本 `Attraction_OpenAPI-clients.py` 升級後的 **台北市限定景點搜尋平台 Client**。

原本版本只會抓「臺北市資料大平臺」某一份景點資料，並用字串搜尋行政區與景點名稱。新版做了以下改造：

- 保留原本臺北市資料大平臺 Client。
- 新增 7 個資料來源 Client：
  - 臺北旅遊網 Open API
  - 交通部觀光署 / TDX Tourism
  - 臺北市資料大平臺
  - OpenStreetMap Overpass API
  - OpenTripMap API
  - Geoapify Places API
  - Foursquare Places API
- 統一轉成 `Place` schema。
- 只保留台北市資料。
- 加入跨來源去重與合併。
- 加入品質分數 `quality_score`。
- 加入關鍵字、行政區、分類、座標半徑搜尋。
- 支援 JSON cache，避免每次搜尋都打外部 API。
- 提供 CLI 與 optional FastAPI app。

---

## 1. 安裝

```bash
cd taipei_attraction_search_platform
python -m venv .venv

# Windows PowerShell
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

---

## 2. 建立台北市景點索引

預設會使用不需要金鑰的公開來源：

```bash
python -m taipei_attraction_platform build
```

會產生：

```text
data/taipei_places.json
```

指定來源：

```bash
python -m taipei_attraction_platform build --sources taipei_open_data,taipei_travel
```

嘗試啟用 optional 來源：

```bash
python -m taipei_attraction_platform build --with-optional
```

> 沒有設定 API key 的來源會自動略過，不會讓整個 build 失敗。

---

## 3. 搜尋範例

關鍵字搜尋：

```bash
python -m taipei_attraction_platform search --query 夜市
```

行政區搜尋：

```bash
python -m taipei_attraction_platform search --district 萬華區
```

關鍵字 + 行政區：

```bash
python -m taipei_attraction_platform search --query 古蹟 --district 大同區
```

台北 101 附近 2 公里：

```bash
python -m taipei_attraction_platform search --lat 25.033976 --lon 121.564538 --radius 2000 --limit 10
```

輸出 JSON：

```bash
python -m taipei_attraction_platform search --query 博物館 --json
```

列出行政區統計：

```bash
python -m taipei_attraction_platform districts
```

---

## 4. API Keys 設定

複製 `.env.example` 後填入自己的 key：

```bash
cp .env.example .env
```

目前程式不強制讀 `.env`，你可以用系統環境變數設定：

```bash
export TDX_CLIENT_ID="你的 TDX client id"
export TDX_CLIENT_SECRET="你的 TDX client secret"
export OPENTRIPMAP_API_KEY="你的 OpenTripMap key"
export GEOAPIFY_API_KEY="你的 Geoapify key"
export FOURSQUARE_API_KEY="你的 Foursquare key"
```

Windows PowerShell：

```powershell
$env:TDX_CLIENT_ID="你的 TDX client id"
$env:TDX_CLIENT_SECRET="你的 TDX client secret"
$env:OPENTRIPMAP_API_KEY="你的 OpenTripMap key"
$env:GEOAPIFY_API_KEY="你的 Geoapify key"
$env:FOURSQUARE_API_KEY="你的 Foursquare key"
```

---

## 5. Python 使用方式

```python
from taipei_attraction_platform import TaipeiAttractionSearchService

service = TaipeiAttractionSearchService(cache_path="data/taipei_places.json")
report = service.build()
print(report.final_count)

results = service.search(query="夜市", district="萬華區", limit=5)
for result in results:
    place = result.place
    print(place.name, place.district, result.score, place.quality_score())
```

---

## 6. Optional FastAPI

安裝：

```bash
pip install fastapi uvicorn
```

啟動：

```bash
uvicorn taipei_attraction_platform.api_app:app --reload
```

可用 endpoint：

```text
GET  /health
POST /build
GET  /places/search?q=夜市&district=萬華區&limit=10
GET  /districts
```

---

## 7. 專案結構

```text
taipei_attraction_platform/
  clients/
    taipei_open_data.py
    taipei_travel.py
    tdx_tourism.py
    overpass.py
    opentripmap.py
    geoapify.py
    foursquare.py
  core/
    models.py
    index.py
    merge.py
    ranker.py
    geo.py
    text.py
  services/
    ingestion_service.py
    search_service.py
    cache.py
  api_app.py
  __main__.py
```

---

## 8. 這版和原本程式的差異

原本：

```text
臺北市資料大平臺 dataset → 行政區 row → 精選景點字串 → 簡單搜尋
```

新版：

```text
多來源 API → Place normalizer → 台北市過濾 → 去重合併 → 本地索引 → 排序搜尋 → optional enrichment
```

排序分數：

```python
final_score = (
    0.34 * text_score +
    0.22 * distance_score +
    0.24 * quality_score +
    0.12 * popularity_score +
    0.08 * freshness_score
)
```

`quality_score` 會看：

- 是否有座標
- 是否有介紹
- 是否有圖片
- 是否有地址
- 是否有開放時間
- 是否有多個來源交叉驗證
- 是否來自官方資料來源

這樣可以避免「資料很少但剛好關鍵字命中」的景點排在高品質景點前面。
