# NEXT STOPS Instruction

This document is the formal installation, configuration, deployment, and maintenance guide for **NEXT STOPS**.

For a short project introduction, use [README.md](README.md).

## 1. System Requirements

Recommended local versions:

- Python 3.11 or later
- Node.js 20.19 or later, or Node.js 22.12 or later
- npm 10 or later
- PostgreSQL for production deployment
- Git

Runtime services used by the current deployment target:

- Frontend: Cloudflare Pages
- Backend: Render Web Service
- Database: Render PostgreSQL

## 2. Project Structure

```text
NEXT-STOPS/
├── algorithm.py
├── requirements.txt
├── tdx-dashboard-prototype/
│   ├── api_app.py
│   ├── CWA-Weather_API_clients.py
│   ├── MOENV-AQI_API_clients.py
│   ├── Weather-AQI_API_clients.py
│   ├── TDX-BUS_API_clients.py
│   ├── TDX-MRT_API_clients.py
│   └── taipei_attraction_search_platform/
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

## 3. Local Installation

Clone the repository:

```bash
git clone https://github.com/IanMackenzie0909/NEXT-STOPS.git
cd NEXT-STOPS
```

Create the environment file:

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
cd ..
```

## 4. Environment Variables

All local environment variables should live in the root `.env`.

Do not commit `.env`.

### 4.1 Core Backend

```txt
NEXT_STOPS_API_PORT=8790
DATABASE_URL=postgresql://user:password@host:5432/database
NEXT_STOPS_CORS_ORIGINS=http://127.0.0.1:5174,http://localhost:5174
NEXT_STOPS_TRUSTED_ORIGINS=http://127.0.0.1:5174,http://localhost:5174
```

When `DATABASE_URL` is set, the backend uses PostgreSQL. If it is missing, the backend falls back to SQLite for local testing.

### 4.2 Frontend Build Variables

```txt
VITE_NEXT_STOPS_API_BASE=http://127.0.0.1:8790
VITE_GOOGLE_CLIENT_ID=your_google_oauth_client_id.apps.googleusercontent.com
```

Vite reads `VITE_*` variables at build time. If these values change on Cloudflare Pages, rebuild the frontend.

### 4.3 API Keys

```txt
GOOGLE_CLIENT_ID=your_google_oauth_client_id.apps.googleusercontent.com
GOOGLE_MAPS_API_KEY=your_google_maps_api_key
GOOGLE_MAPS_BROWSER_KEY=your_google_maps_browser_key
GOOGLE_MAPS_SERVER_KEY=your_google_maps_server_key
MAPBOX_ACCESS_TOKEN=your_mapbox_access_token

CWA_API_KEY=your_cwa_opendata_authorization_token
AQI_API_KEY=your_moenv_api_key
MOENV_API_KEY=your_moenv_api_key

GEOAPIFY_API_KEY=your_geoapify_api_key
FOURSQUARE_API_KEY=your_foursquare_api_key
OPENTRIPMAP_API_KEY=your_opentripmap_api_key
```

### 4.4 TDX Credentials

TDX credentials are intentionally separated by API use case:

```txt
TDX_TR_CLIENT_ID=your_TDX_TR_client_id
TDX_TR_CLIENT_SECRET=your_TDX_TR_client_secret
TDX_BUS_CLIENT_ID=your_TDX_BUS_client_id
TDX_BUS_CLIENT_SECRET=your_TDX_BUS_client_secret
TDX_MRT_CLIENT_ID=your_TDX_MRT_client_id
TDX_MRT_CLIENT_SECRET=your_TDX_MRT_client_secret
TDX_TOURISM_CLIENT_ID=your_TDX_TOURISM_client_id
TDX_TOURISM_CLIENT_SECRET=your_TDX_TOURISM_client_secret
TDX_BUS_CITY=Taipei
```

Do not collapse these into one shared TDX credential pair unless the backend client code is changed intentionally.

### 4.5 Security and Admin

```txt
NEXT_STOPS_MAX_BODY_BYTES=262144
NEXT_STOPS_RATE_LIMIT_DEFAULT=180
NEXT_STOPS_RATE_LIMIT_AUTH=12
NEXT_STOPS_RATE_LIMIT_ADMIN=30
NEXT_STOPS_RATE_LIMIT_RECOMMEND=30
NEXT_STOPS_RATE_LIMIT_BUILD=3
NEXT_STOPS_ENABLE_HSTS=true
ADMIN_TOKEN_SHA256=your_admin_token_sha256
```

Generate an admin token:

```bash
openssl rand -base64 32
```

Generate its SHA-256 hash:

```bash
printf "your_raw_admin_token" | sha256sum
```

Store only the hash in deployment:

```txt
ADMIN_TOKEN_SHA256=<sha256_hash>
```

Use the raw token when logging in to the admin dashboard. Do not commit the raw token.

## 5. Running Locally

Start the backend:

```bash
cd tdx-dashboard-prototype
../env/bin/uvicorn api_app:app --reload --host 127.0.0.1 --port 8790
```

Start the frontend:

```bash
cd next-stops-vue-prototype
npm run dev
```

Open:

```txt
http://127.0.0.1:5174/
```

Health check:

```bash
curl http://127.0.0.1:8790/health
```

## 6. Place Cache

The recommendation system depends on place data. Build or refresh the place cache after the backend is running:

```bash
curl -X POST "http://127.0.0.1:8790/api/places/build"
```

Use optional enrichment sources when keys are configured:

```bash
curl -X POST "http://127.0.0.1:8790/api/places/build?with_optional=true"
```

The generated cache path is:

```txt
tdx-dashboard-prototype/taipei_attraction_search_platform/data/taipei_places.json
```

This cache is ignored by Git.

## 7. Deployment

The recommended production split is:

- Cloudflare Pages for the Vue frontend
- Render Web Service for the FastAPI backend
- Render PostgreSQL for production data

### 7.1 Render PostgreSQL

Create a PostgreSQL database in Render.

Copy the external or internal connection string and set it as:

```txt
DATABASE_URL=<render_postgresql_connection_string>
```

The FastAPI backend creates required tables automatically with `CREATE TABLE IF NOT EXISTS`.

### 7.2 Render Backend

Create a Render Web Service connected to the GitHub repository.

Recommended settings:

```txt
Root directory: .
Build command: pip install -r requirements.txt
Start command: cd tdx-dashboard-prototype && uvicorn api_app:app --host 0.0.0.0 --port $PORT
```

Required Render environment variables:

```txt
DATABASE_URL=<render_postgresql_connection_string>
NEXT_STOPS_CORS_ORIGINS=https://next-stops.pages.dev
NEXT_STOPS_TRUSTED_ORIGINS=https://next-stops.pages.dev
NEXT_STOPS_MAX_BODY_BYTES=262144
NEXT_STOPS_RATE_LIMIT_DEFAULT=180
NEXT_STOPS_RATE_LIMIT_AUTH=12
NEXT_STOPS_RATE_LIMIT_ADMIN=30
NEXT_STOPS_RATE_LIMIT_RECOMMEND=30
NEXT_STOPS_RATE_LIMIT_BUILD=3
NEXT_STOPS_ENABLE_HSTS=true
ADMIN_TOKEN_SHA256=<sha256_hash>
GOOGLE_CLIENT_ID=<google_oauth_client_id>
GOOGLE_MAPS_SERVER_KEY=<google_maps_server_key>
MAPBOX_ACCESS_TOKEN=<mapbox_access_token>
CWA_API_KEY=<cwa_key>
AQI_API_KEY=<moenv_key>
MOENV_API_KEY=<moenv_key>
```

Also set the relevant TDX, Geoapify, Foursquare, and OpenTripMap keys if those sources are used.

If you use a custom frontend domain, add it to both:

```txt
NEXT_STOPS_CORS_ORIGINS
NEXT_STOPS_TRUSTED_ORIGINS
```

Do not add a trailing slash to origin values.

After changing Render environment variables, choose a deploy option that restarts the service.

### 7.3 Cloudflare Pages Frontend

Create a Cloudflare Pages project connected to the GitHub repository.

Recommended settings:

```txt
Root directory: next-stops-vue-prototype
Build command: npm ci && npm run build
Output directory: dist
```

Required Cloudflare Pages build variables:

```txt
VITE_NEXT_STOPS_API_BASE=https://your-render-backend.onrender.com
VITE_GOOGLE_CLIENT_ID=your_google_oauth_client_id.apps.googleusercontent.com
```

If build watch paths are enabled, use:

```txt
next-stops-vue-prototype/**
```

After changing any `VITE_*` variable, redeploy Cloudflare Pages. These variables are compiled into the frontend bundle at build time.

### 7.4 Google OAuth

In Google Cloud Console, configure the OAuth web client.

Authorized JavaScript origins:

```txt
http://127.0.0.1:5174
http://localhost:5174
https://next-stops.pages.dev
https://your-custom-frontend-domain
```

Authorized redirect URIs are not required for the current Google Identity Services button flow unless the auth integration is changed to a redirect-based OAuth flow.

## 8. Security Model

Current backend protections:

- Password hashing with PBKDF2-SHA256 and per-user salt
- Bearer-token auth sessions
- Admin token validation through `X-Admin-Token`
- SHA-256 admin token storage option
- Unsafe request origin guard for browser-origin CSRF-style abuse
- JSON-only unsafe API methods
- Request body size limit
- Per-endpoint in-memory rate limiting
- API response security headers
- URL query admin tokens rejected

Production notes:

- Always serve the frontend and backend over HTTPS.
- Keep API keys and database URLs in platform secrets, not source control.
- Use `ADMIN_TOKEN_SHA256` instead of plaintext `ADMIN_TOKEN` in deployment.
- For multi-instance backend scaling, replace in-memory rate limiting with Cloudflare Rate Limiting, Redis, or another shared limiter.

## 9. Verification

Frontend build:

```bash
cd next-stops-vue-prototype
npm run build
```

Backend syntax check:

```bash
env/bin/python -m py_compile tdx-dashboard-prototype/api_app.py algorithm.py
```

Security test:

```bash
env/bin/python tests/test_api_security.py
```

Backend health check:

```bash
curl http://127.0.0.1:8790/health
```

Production health check:

```bash
curl https://your-render-backend.onrender.com/health
```

## 10. Operational Checklist

Before deployment:

- Confirm `.env` is not tracked by Git.
- Confirm Cloudflare Pages has `VITE_NEXT_STOPS_API_BASE`.
- Confirm Render has `DATABASE_URL`.
- Confirm Render has `ADMIN_TOKEN_SHA256`.
- Confirm CORS and trusted origins match the deployed frontend URL.
- Confirm Google OAuth origins include the deployed frontend URL.
- Run frontend build and backend security tests.

After deployment:

- Open frontend URL.
- Run backend `/health`.
- Log in with platform account or Google OAuth.
- Generate one recommendation.
- Open one detail page and verify map, route, and Google Maps link.
- Open admin dashboard and confirm backend database is PostgreSQL.
- Build or refresh place cache if recommendation results are empty or stale.

## 11. Troubleshooting

### Google Login Shows Unconfigured

Check:

- `VITE_GOOGLE_CLIENT_ID` exists in Cloudflare Pages build variables.
- Cloudflare Pages was redeployed after changing the variable.
- Google Cloud Console includes the frontend URL in Authorized JavaScript origins.

### Frontend Cannot Call Backend

Check:

- `VITE_NEXT_STOPS_API_BASE` points to the Render backend URL.
- Render backend is running.
- `NEXT_STOPS_CORS_ORIGINS` includes the Cloudflare Pages URL.
- `NEXT_STOPS_TRUSTED_ORIGINS` includes the Cloudflare Pages URL.

### Admin Login Fails

Check:

- Render has `ADMIN_TOKEN_SHA256`.
- You are entering the raw admin token in the app, not the SHA-256 hash.
- The request includes `X-Admin-Token`; URL query tokens are rejected.

### Backend Uses SQLite Instead of PostgreSQL

Check:

- `DATABASE_URL` is set in Render.
- Render service was restarted or redeployed after adding `DATABASE_URL`.
- Admin system data reports the backend database type.

### Cloudflare Build Does Not Update

Check:

- Root directory is `next-stops-vue-prototype`.
- Build command is `npm ci && npm run build`.
- Output directory is `dist`.
- Build watch paths include `next-stops-vue-prototype/**` or are disabled.

## 12. Maintenance Notes

- Keep generated caches, `.env`, SQLite databases, and local build output out of Git.
- Rotate admin token when sharing access or after demos.
- Rebuild place cache after changing place-source API keys or place-normalization logic.
- Review rate-limit settings before public traffic increases.
- Use PostgreSQL backups before destructive admin operations.
