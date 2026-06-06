# NEXT-STOPS

**NEXT STOPS** is the final project of 2026 Web Programming and Application course.

## Project Introduction

**NEXT STOPS** is a context-aware city exploration and outing recommendation web application.

The purpose of **NEXT STOPS** is to help users quickly answer one simple question:

> “Where should I go next?”

Instead of requiring users to manually check weather apps, map services, event websites, public transport information, and air quality data separately, **NEXT STOPS** integrates multiple external APIs and provides personalized, situation-based recommendations.

The application focuses on creating a calm, lightweight, and emotionally comfortable user experience. It is not designed as a traditional travel website, technical dashboard, or generic map tool. Instead, it acts as a decision-support web app that helps users choose suitable places based on their current mood, available time, weather conditions, transportation distance, and personal preferences.

## Instructions

以下流程會啟動目前主要的 NEXT STOPS Vue Web App，並使用 FastAPI 後端執行推薦演算法、外部 API client、景點搜尋與 SQLite 推薦紀錄。

### 1. 專案需求

請先確認本機有：

- Python 3.12 或相容版本
- Node.js / npm
- 可用的瀏覽器定位權限

本專案目前使用：

- Frontend: `next-stops-vue-prototype`
- Backend: `tdx-dashboard-prototype/api_app.py`
- Recommendation algorithm: `algorithm.py`
- Local database: `tdx-dashboard-prototype/data/next_stops.sqlite3`

SQLite 資料庫與 API cache 都是本機產生資料，已由 `.gitignore` 排除。

### 2. 設定環境變數

複製範例檔案：

```bash
cp .env.example .env
```

依照你擁有的 API key 修改 `.env`：

```env
TDX_TR_CLIENT_ID=your_TDX_TR_client_id
TDX_TR_CLIENT_SECRET=your_TDX_TR_client_secret
TDX_BUS_CLIENT_ID=your_TDX_BUS_client_id
TDX_BUS_CLIENT_SECRET=your_TDX_BUS_client_secret
TDX_MRT_CLIENT_ID=your_TDX_MRT_client_id
TDX_MRT_CLIENT_SECRET=your_TDX_MRT_client_secret
TDX_TOURISM_CLIENT_ID=your_TDX_TOURISM_client_id
TDX_TOURISM_CLIENT_SECRET=your_TDX_TOURISM_client_secret
TDX_BUS_CITY=Taipei
CWA_API_KEY=your_cwa_opendata_authorization_token
AQI_API_KEY=your_moenv_api_key
OPENTRIPMAP_API_KEY=your_opentripmap_api_key
GEOAPIFY_API_KEY=your_geoapify_api_key
FOURSQUARE_API_KEY=your_foursquare_api_key
```

TDX key 目前分成四組，不要混用：

- `TDX_TR_*`: 台鐵 / rail realtime
- `TDX_BUS_*`: Taipei BUS
- `TDX_MRT_*`: Taipei MRT
- `TDX_TOURISM_*`: TDX Tourism scenic spot

沒有 TDX / CWA / MOENV key 時，部分即時資料會 fallback 或被標記為 skipped；推薦流程仍會盡量運作。

### 3. 安裝後端 dependencies

如果根目錄已經有 `env/`，可以直接使用既有 virtual environment。

若需要重新建立：

```bash
python3 -m venv env
env/bin/pip install -r tdx-dashboard-prototype/requirements.txt
```

### 4. 安裝前端 dependencies

```bash
cd next-stops-vue-prototype
npm install
cd ..
```

### 5. 啟動 FastAPI 後端

開第一個 terminal：

```bash
cd tdx-dashboard-prototype
../env/bin/uvicorn api_app:app --reload --host 127.0.0.1 --port 8790
```

後端主要 endpoint：

- `GET /health`
- `POST /api/recommendations`
- `GET /api/recommendations/{request_id}`
- `GET /api/places/search`
- `POST /api/places/build`
- `GET /api/context`
- `GET /api/bus/stations`
- `GET /api/mrt/stations`

確認後端是否正常：

```bash
curl http://127.0.0.1:8790/health
```

預期會看到：

```json
{"status":"ok","service":"next-stops-data-api"}
```

### 6. 建立或更新景點資料

如果第一次啟動時還沒有景點 cache，可以在後端啟動後執行：

```bash
curl -X POST "http://127.0.0.1:8790/api/places/build"
```

這會產生本機景點 cache：

```txt
tdx-dashboard-prototype/taipei_attraction_search_platform/data/taipei_places.json
```

若要包含 optional nearby sources，可使用：

```bash
curl -X POST "http://127.0.0.1:8790/api/places/build?with_optional=true"
```

optional sources 可能需要額外 API key，例如 Geoapify、Foursquare、OpenTripMap、TDX Tourism。

### 7. 啟動 Vue 前端

開第二個 terminal：

```bash
cd next-stops-vue-prototype
npm run dev
```

預設網址：

```txt
http://127.0.0.1:5174/
```

Vite 會把前端的 `/api/*` proxy 到：

```txt
http://127.0.0.1:8790
```

### 8. 使用流程

1. 打開 `http://127.0.0.1:5174/`
2. 瀏覽器詢問定位權限時，允許定位
3. 選擇心情、可安排時間、最多移動時間、天氣偏好、預算
4. 點擊 `Find my next stop`
5. 前端會呼叫 `POST /api/recommendations`
6. 後端會整合景點搜尋、Weather/AQI、TDX 可用資料與 `algorithm.py`
7. 推薦結果會寫入 SQLite：

```txt
tdx-dashboard-prototype/data/next_stops.sqlite3
```

### 9. Build 檢查

前端：

```bash
cd next-stops-vue-prototype
npm run build
```

後端語法檢查：

```bash
env/bin/python -m py_compile tdx-dashboard-prototype/api_app.py algorithm.py
```

### 10. 常見問題

#### Port 被佔用

檢查 port：

```bash
lsof -nP -iTCP:5174 -sTCP:LISTEN
lsof -nP -iTCP:8790 -sTCP:LISTEN
```

停止指定 PID：

```bash
kill <PID>
```

#### 前端開起來是空白

先確認 build：

```bash
cd next-stops-vue-prototype
npm run build
```

再確認後端是否有啟動：

```bash
curl http://127.0.0.1:8790/health
```

#### 定位沒有作用

瀏覽器定位通常需要：

- 使用 `http://127.0.0.1`
- 允許網站定位權限
- 系統層級定位服務已開啟

如果定位失敗，前端會 fallback 到台北車站。

#### 推薦沒有結果

先建立景點資料：

```bash
curl -X POST "http://127.0.0.1:8790/api/places/build"
```

再重新按 `Find my next stop`。
