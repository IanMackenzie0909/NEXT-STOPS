# NEXT-STOPS

**NEXT STOPS** is the final project of 2026 Web Programming and Application course.

## Project Introduction

**NEXT STOPS** is a context-aware city exploration and outing recommendation web application.

The purpose of **NEXT STOPS** is to help users quickly answer one simple question:

> “Where should I go next?”

Instead of requiring users to manually check weather apps, map services, event websites, public transport information, and air quality data separately, **NEXT STOPS** integrates multiple external APIs and provides personalized, situation-based recommendations.

The application focuses on creating a calm, lightweight, and emotionally comfortable user experience. It is not designed as a traditional travel website, technical dashboard, or generic map tool. Instead, it acts as a decision-support web app that helps users choose suitable places based on their current mood, available time, weather conditions, transportation distance, and personal preferences.

## Current Stack

- Frontend: Vue + Vite in `next-stops-vue-prototype`
- Backend: FastAPI in `tdx-dashboard-prototype/api_app.py`
- Recommendation engine: `algorithm.py`
- Database: PostgreSQL when `DATABASE_URL` is set; SQLite fallback for local testing
- Map UI: Mapbox on the detail page, with Google Maps links for navigation

## Local Development

1. Copy environment variables:

```bash
cp .env.example .env
```

2. Install backend dependencies:

```bash
python3 -m venv env
env/bin/pip install -r requirements.txt
```

3. Install frontend dependencies:

```bash
cd next-stops-vue-prototype
npm install
```

4. Start FastAPI:

```bash
cd tdx-dashboard-prototype
../env/bin/uvicorn api_app:app --reload --host 127.0.0.1 --port 8790
```

5. Start Vite:

```bash
cd next-stops-vue-prototype
npm run dev
```

Local frontend URL:

```txt
http://127.0.0.1:5174/
```

Health check:

```bash
curl http://127.0.0.1:8790/health
```

## Required Configuration

Important variables live in the root `.env`.

- `DATABASE_URL`: PostgreSQL connection string for deployment
- `NEXT_STOPS_CORS_ORIGINS`: allowed frontend origins, for example Cloudflare Pages and local Vite URLs
- `ADMIN_TOKEN`: token for the internal admin page
- `GOOGLE_CLIENT_ID` / `VITE_GOOGLE_CLIENT_ID`: Google OAuth client ID
- `GOOGLE_MAPS_SERVER_KEY` or `GOOGLE_MAPS_API_KEY`: route, geocoding, and Places data
- `MAPBOX_ACCESS_TOKEN`: frontend map rendering
- `CWA_API_KEY`, `AQI_API_KEY` / `MOENV_API_KEY`: weather and air quality
- `GEOAPIFY_API_KEY`, `FOURSQUARE_API_KEY`, `OPENTRIPMAP_API_KEY`: optional place enrichment

TDX credentials are intentionally separated and should not be mixed:

- `TDX_TR_*`: rail data
- `TDX_BUS_*`: bus data
- `TDX_MRT_*`: MRT data
- `TDX_TOURISM_*`: tourism/scenic spot data

## Place Data

Build or refresh local place cache after the backend is running:

```bash
curl -X POST "http://127.0.0.1:8790/api/places/build"
```

Use optional external sources when the keys are configured:

```bash
curl -X POST "http://127.0.0.1:8790/api/places/build?with_optional=true"
```

## Deployment Notes

Recommended split:

- Frontend: Cloudflare Pages
- Backend: Render or Railway
- Database: managed PostgreSQL

Cloudflare Pages settings:

- Root directory: `next-stops-vue-prototype`
- Build command: `npm ci && npm run build`
- Output directory: `dist`
- Build variables: `VITE_NEXT_STOPS_API_BASE`, `VITE_GOOGLE_CLIENT_ID`

Backend deploy settings:

- Start command: `uvicorn tdx-dashboard-prototype.api_app:app --host 0.0.0.0 --port $PORT`
- Set `DATABASE_URL`, `NEXT_STOPS_CORS_ORIGINS`, API keys, Google keys, Mapbox token, and `ADMIN_TOKEN`
- Add deployed frontend URL to Google OAuth Authorized JavaScript origins

## Verification

Frontend build:

```bash
cd next-stops-vue-prototype
npm run build
```

Backend syntax check:

```bash
env/bin/python -m py_compile tdx-dashboard-prototype/api_app.py algorithm.py
```

Common ports:

- Frontend: `5174`
- Backend: `8790`
