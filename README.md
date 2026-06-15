<p align="center">
  <img src="icon/APP_ICON.png" alt="NEXT STOPS app icon" width="128" />
</p>

<h1 align="center">NEXT STOPS</h1>

<p align="center">
  A context-aware city exploration web app for deciding where to go next.
</p>

<p align="center">
  <img alt="Vue" src="https://img.shields.io/badge/Vue-3.5-42b883?style=flat&logo=vuedotjs&logoColor=white" />
  <img alt="Vite" src="https://img.shields.io/badge/Vite-8-646cff?style=flat&logo=vite&logoColor=white" />
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-backend-009688?style=flat&logo=fastapi&logoColor=white" />
  <img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL-production-4169e1?style=flat&logo=postgresql&logoColor=white" />
  <img alt="Cloudflare Pages" src="https://img.shields.io/badge/Cloudflare%20Pages-frontend-f38020?style=flat&logo=cloudflarepages&logoColor=white" />
  <img alt="Render" src="https://img.shields.io/badge/Render-backend-46e3b7?style=flat&logo=render&logoColor=111827" />
  <img alt="License" src="https://img.shields.io/badge/License-MIT-facc15?style=flat" />
</p>

## Overview

**NEXT STOPS** helps users choose a suitable next destination based on mood, available time, location, weather, air quality, transportation options, budget, opening status, and learned preference signals.

Instead of asking users to manually compare maps, weather, AQI, route planning, and place databases, the app sends the current context to a FastAPI backend. The backend normalizes external data, runs the recommendation engine, records the request, and returns ranked places with route information and short explanations.

## Features

- Mood-based outing recommendation flow
- Vue + Vite responsive web app with mobile and desktop layouts
- FastAPI backend with recommendation, auth, admin, route, weather, AQI, and place APIs
- PostgreSQL support for deployment, with SQLite fallback for local testing
- Google OAuth and platform account login
- User profile, saved places, frequent starting points, and preference controls
- Mapbox detail map with Google Maps navigation links
- Admin dashboard for service status, data summary, route logs, feedback, and system security state
- API protection: origin guard, JSON-only unsafe requests, body-size limit, security headers, and per-endpoint rate limiting

## Tech Stack

| Layer | Technology |
| --- | --- |
| Frontend | Vue 3, Vite |
| Backend | FastAPI, Uvicorn |
| Recommendation | Python recommendation engine in `algorithm.py` |
| Database | PostgreSQL in production, SQLite fallback locally |
| Maps and Routes | Mapbox, Google Maps / Routes / Places |
| External data | CWA Weather, MOENV AQI, TDX, Geoapify, Foursquare, OpenTripMap |
| Deployment target | Cloudflare Pages frontend, Render backend and PostgreSQL |

## Quick Start

Clone the repository and create your local environment file:

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

Start the FastAPI backend:

```bash
cd tdx-dashboard-prototype
../env/bin/uvicorn api_app:app --reload --host 127.0.0.1 --port 8790
```

Start the Vite frontend in another terminal:

```bash
cd next-stops-vue-prototype
npm run dev
```

Open:

```txt
http://127.0.0.1:5174/
```

Backend health check:

```bash
curl http://127.0.0.1:8790/health
```

## Required Local Configuration

The root `.env` file is required for real API calls. Start from `.env.example`, then fill in the keys you actually use:

- `VITE_NEXT_STOPS_API_BASE`
- `VITE_GOOGLE_CLIENT_ID`
- `DATABASE_URL` for PostgreSQL deployment
- `GOOGLE_CLIENT_ID`, `GOOGLE_MAPS_SERVER_KEY`, `MAPBOX_ACCESS_TOKEN`
- `CWA_API_KEY`, `AQI_API_KEY` / `MOENV_API_KEY`
- `TDX_TR_*`, `TDX_BUS_*`, `TDX_MRT_*`, `TDX_TOURISM_*`
- `GEOAPIFY_API_KEY`, `FOURSQUARE_API_KEY`, `OPENTRIPMAP_API_KEY`
- `ADMIN_TOKEN_SHA256` for the internal admin dashboard

Do not commit `.env`, API keys, database URLs, or raw admin tokens.

## Verification

Run the frontend build:

```bash
cd next-stops-vue-prototype
npm run build
```

Run backend syntax checks:

```bash
env/bin/python -m py_compile tdx-dashboard-prototype/api_app.py algorithm.py
```

Run security checks:

```bash
env/bin/python tests/test_api_security.py
```

## Documentation

- [Instruction.md](Instruction.md): formal installation, configuration, deployment, and maintenance guide
- [NEXT_STOPS_Developer_Documentation.md](NEXT_STOPS_Developer_Documentation.md): product and architecture notes

## Repository Layout

```text
NEXT-STOPS/
├── algorithm.py
├── requirements.txt
├── tdx-dashboard-prototype/
│   └── api_app.py
├── next-stops-vue-prototype/
│   ├── src/
│   ├── public/
│   ├── package.json
│   └── vite.config.js
├── icon/
├── tests/
├── .env.example
├── Instruction.md
└── README.md
```

## License

This project is released under the [MIT License](LICENSE).
