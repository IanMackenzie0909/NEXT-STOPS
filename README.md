<p align="center">
  <img src="icon/APP_ICON.png" alt="NEXT STOPS app icon" width="128" />
</p>

<h1 align="center">NEXT STOPS</h1>

<p align="center">
  Context-aware recommendations for deciding where to go next.
</p>

<p align="center">
  <img alt="Vue" src="https://img.shields.io/badge/Vue-3.5-42b883?style=flat&logo=vuedotjs&logoColor=white" />
  <img alt="Vite" src="https://img.shields.io/badge/Vite-8-646cff?style=flat&logo=vite&logoColor=white" />
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-modular%20backend-009688?style=flat&logo=fastapi&logoColor=white" />
  <img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL-production-4169e1?style=flat&logo=postgresql&logoColor=white" />
  <img alt="Cloudflare Pages" src="https://img.shields.io/badge/Cloudflare%20Pages-frontend-f38020?style=flat&logo=cloudflarepages&logoColor=white" />
  <img alt="Render" src="https://img.shields.io/badge/Render-backend-46e3b7?style=flat&logo=render&logoColor=111827" />
  <img alt="Security" src="https://img.shields.io/badge/API%20Protection-enabled-111827?style=flat" />
  <img src="https://img.shields.io/badge/License-AGPL%20v3-blue.svg" alt="License: AGPL v3" />
</p>

## Overview

NEXT STOPS is a city exploration web app that recommends nearby destinations based on user intent, available time, transportation choices, weather, AQI, budget, opening status, and learned feedback signals.

The frontend is a Vue/Vite web app. The backend is a modular FastAPI service that normalizes external data, runs the recommendation engine, compares commute options, records recommendation requests, and exposes admin/status endpoints.

Current service area: Taipei City and New Taipei City.

## Core Features

- Mood-based recommendation flow for outings such as relaxing walks, dates, rainy-day backups, photo exploration, and night trips
- Multi-mode transport comparison: driving, bus, MRT, scooter, walking, and cycling
- Place search and cache built from Taipei attraction data plus optional external enrichment
- Weather and AQI context from CWA and MOENV-backed clients
- Mapbox place detail maps with Google Maps navigation handoff
- Platform account login, Google login, guest mode, profile, saved places, and frequent starting points
- Admin dashboard for database status, users, recommendation logs, feedback, cache status, and API protection state
- API abuse protection: CORS allowlist, unsafe-request origin guard, JSON-only unsafe requests, body-size limits, security headers, and rate limiting

## Architecture

```text
NEXT-STOPS/
├── next-stops-vue-prototype/          # Vue 3 + Vite frontend
├── tdx-dashboard-prototype/
│   ├── api_app.py                     # FastAPI app factory/wiring only
│   └── next_stops_backend/
│       ├── config.py                  # environment, paths, constants
│       ├── security.py                # CORS, rate limit, security headers
│       ├── database.py                # SQLite/PostgreSQL wrapper and schema
│       ├── auth.py                    # login, registration, sessions, profile
│       ├── admin.py                   # admin summary and system inspection
│       ├── service_area.py            # Shuangbei service-area validation
│       ├── places.py                  # attraction cache/search/detail service
│       ├── recommendation.py          # recommendation formatting and records
│       ├── routing.py                 # Google route and commute comparison
│       ├── transport.py               # TDX bus/MRT service helpers
│       ├── weather.py                 # CWA/MOENV/weather-AQI wrapper
│       └── routers/                   # FastAPI route modules
├── algorithm.py                       # recommendation algorithm core
├── shared/geo/                        # service-area geometry
├── icon/                              # app icons and transport assets
├── tests/                             # backend security tests
├── Instruction.md                     # full install/deploy guide
└── README.md
```

`api_app.py` intentionally stays thin. Business logic lives in `next_stops_backend/*` services, and route declarations live in `next_stops_backend/routers/*`.

## Tech Stack

| Layer           | Technology                                                     |
| --------------- | -------------------------------------------------------------- |
| Frontend        | Vue 3, Vite                                                    |
| Backend         | FastAPI, Uvicorn                                               |
| Recommendation  | Python engine in `algorithm.py`                                |
| Database        | PostgreSQL for deployment, SQLite fallback locally             |
| Maps and routes | Mapbox, Google Maps / Routes / Places                          |
| External data   | CWA Weather, MOENV AQI, TDX, Geoapify, Foursquare, OpenTripMap |
| Deployment      | Cloudflare Pages frontend, Render backend and PostgreSQL       |

## Quick Start

Create the local environment file:

```bash
cp .env.example .env
```

Install backend dependencies:

```bash
python3 -m venv env
env/bin/pip install -r requirements.txt
```

Install frontend dependencies:

```bash
cd next-stops-vue-prototype
npm install
```

Start the backend:

```bash
cd tdx-dashboard-prototype
../env/bin/uvicorn api_app:app --reload --host 127.0.0.1 --port 8790
```

Start the frontend in another terminal:

```bash
cd next-stops-vue-prototype
npm run dev
```

Open:

```text
http://127.0.0.1:5174/
```

## Environment

The root `.env` file is required for real API calls. Start from `.env.example`, then fill in only the keys needed by your target environment.

Common keys:

- `VITE_NEXT_STOPS_API_BASE`
- `VITE_GOOGLE_CLIENT_ID`
- `DATABASE_URL`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_MAPS_SERVER_KEY`
- `MAPBOX_ACCESS_TOKEN`
- `CWA_API_KEY`
- `AQI_API_KEY` / `MOENV_API_KEY`
- `TDX_BUS_CLIENT_ID`, `TDX_BUS_CLIENT_SECRET`
- `TDX_MRT_CLIENT_ID`, `TDX_MRT_CLIENT_SECRET`
- `GEOAPIFY_API_KEY`, `FOURSQUARE_API_KEY`, `OPENTRIPMAP_API_KEY`
- `ADMIN_TOKEN_SHA256`

Do not commit `.env`, raw API keys, database URLs, OAuth secrets, or plain admin tokens.

## Verification

Backend syntax check:

```bash
env/bin/python -m py_compile \
  tdx-dashboard-prototype/api_app.py \
  tdx-dashboard-prototype/next_stops_backend/*.py \
  tdx-dashboard-prototype/next_stops_backend/routers/*.py \
  algorithm.py
```

Security tests:

```bash
env/bin/python tests/test_api_security.py
```

Type check:

```bash
npx --yes pyright
```

Frontend build:

```bash
cd next-stops-vue-prototype
npm run build
```

## Deployment

The recommended deployment split is:

- Frontend: Cloudflare Pages
- Backend: Render Web Service
- Database: Render PostgreSQL

Use [Instruction.md](Instruction.md) for the full deployment procedure, including environment variables, Google OAuth origin setup, Render service configuration, PostgreSQL setup, and Cloudflare Pages build settings.

## Documentation

- [Instruction.md](Instruction.md): formal installation, configuration, deployment, and maintenance guide
- [NEXT_STOPS_Developer_Documentation.md](NEXT_STOPS_Developer_Documentation.md): developer-facing project specification
- [NEXT_STOPS_Web_App_Report.md](NEXT_STOPS_Web_App_Report.md): development and trial report
- [NEXT_STOPS_Eraser_Architecture.md](NEXT_STOPS_Eraser_Architecture.md): Eraser architecture diagrams

## License

This project is released under the [AGPL-3.0 License](LICENSE).
