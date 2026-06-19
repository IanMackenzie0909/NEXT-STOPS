"""Unified FastAPI app for NEXT STOPS external-data clients.

Run from this directory:
  uvicorn api_app:app --reload --host 127.0.0.1 --port 8790
"""

from __future__ import annotations
from types import SimpleNamespace
import requests

try:
    from fastapi import FastAPI, HTTPException
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("請先安裝 FastAPI dependencies：pip install -r requirements.txt") from exc

from next_stops_backend.config import (
    DEFAULT_MAPBOX_TOKEN,
    PROJECT_ROOT,
    SAMPLE_LOCATIONS,
    ensure_attraction_platform_on_path,
    env_first,
    load_module,
    load_module_from_path,
    load_root_env,
)

load_root_env()

from next_stops_backend.admin import AdminService, require_admin
from next_stops_backend.auth import (
    auth_config,
    delete_user_account,
    login_google_user,
    login_platform_user,
    logout_auth_session,
    normalize_favorite_starts,
    register_platform_user,
    require_current_user,
    update_user_preferences,
    update_user_profile,
)
from next_stops_backend.places import PlacesService
from next_stops_backend.recommendation import RecommendationService
from next_stops_backend.routers import (
    admin as admin_router,
    auth as auth_router,
    places as places_router,
    recommendations as recommendations_router,
    routes as routes_router,
    transport as transport_router,
    weather as weather_router,
)
from next_stops_backend.routing import (
    ROUTE_COMPARE_MODES,
    compare_commute_options,
    normalize_transport_modes,
)
from next_stops_backend.security import (
    DEFAULT_MAX_BODY_BYTES,
    RATE_LIMIT_STORE,
    UNSAFE_METHODS,
    allowed_browser_origins,
    check_rate_limit,
    configure_cors,
    env_int,
    install_api_abuse_protection,
    security_config_summary,
    security_headers_for,
    unsafe_request_rejection,
)
from next_stops_backend.service_area import find_service_area, is_within_service_area
from next_stops_backend.transport import TransportService
from next_stops_backend.utils import to_float
from next_stops_backend.weather import WeatherService

cwa_module = load_module("cwa_weather_api_clients", "CWA-Weather_API_clients.py")
moenv_module = load_module("moenv_aqi_api_clients", "MOENV-AQI_API_clients.py")
weather_aqi_module = load_module("weather_aqi_api_clients", "Weather-AQI_API_clients.py")
bus_module = load_module("tdx_bus_api_clients", "TDX-BUS_API_clients.py")
mrt_module = load_module("tdx_mrt_api_clients", "TDX-MRT_API_clients.py")
recommendation_algorithm = load_module_from_path("next_stops_recommendation_algorithm", PROJECT_ROOT / "algorithm.py")

ensure_attraction_platform_on_path()

try:
    from taipei_attraction_platform.services.search_service import TaipeiAttractionSearchService
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Cannot import Taipei attraction search service") from exc


app = FastAPI(title="NEXT STOPS Data API", version="1.0.0")
configure_cors(app)
install_api_abuse_protection(app)


transport_service = TransportService(bus_module, mrt_module)
weather_service = WeatherService(cwa_module, moenv_module, weather_aqi_module)
weather_aqi_client = weather_service.weather_aqi_client


def api_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if transport_service.is_tdx_rate_limit_error(exc):
        return HTTPException(status_code=429, detail=str(exc))
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        status = exc.response.status_code
        return HTTPException(status_code=status if 400 <= status < 600 else 500, detail=f"External API request failed: {exc}")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def run_or_raise(func):
    try:
        return func()
    except Exception as exc:
        raise api_error(exc) from exc


def get_mapbox_token() -> str:
    return env_first("MAPBOX_ACCESS_TOKEN", default=DEFAULT_MAPBOX_TOKEN)


def mapbox_config():
    token = get_mapbox_token()
    if not token or token == DEFAULT_MAPBOX_TOKEN:
        return {"access_token": "", "configured": False}
    return {"access_token": token, "configured": True}


places_service = PlacesService(TaipeiAttractionSearchService)
recommendation_service = RecommendationService(
    algorithm=recommendation_algorithm,
    weather_aqi_client=weather_aqi_client,
    places=places_service,
    build_transport_context=transport_service.build_transport_context,
)
admin_service = AdminService(
    get_attraction_service=places_service.get_attraction_service,
    rain_probability_from_context=recommendation_service.rain_probability_from_context,
    aqi_from_context=recommendation_service.aqi_from_context,
)


def register_api_routers() -> None:
    deps = SimpleNamespace(
        admin_delete_user=admin_service.delete_user,
        admin_feedback=admin_service.feedback,
        admin_overview=admin_service.overview,
        admin_places_summary=admin_service.places_summary,
        admin_recommendations=admin_service.recommendations,
        admin_summary=admin_service.summary,
        admin_users=admin_service.users,
        auth_config=auth_config,
        build_place_detail=recommendation_service.build_place_detail,
        build_recommendations=recommendation_service.build_recommendations,
        compare_commute_options=compare_commute_options,
        delete_user_account=delete_user_account,
        detail_criteria_from_query=recommendation_service.detail_criteria_from_query,
        fetch_recommendation_record=recommendation_service.fetch_recommendation_record,
        get_attraction_service=places_service.get_attraction_service,
        list_saved_places=recommendation_service.list_saved_places,
        login_google_user=login_google_user,
        login_platform_user=login_platform_user,
        logout_auth_session=logout_auth_session,
        mapbox_config=mapbox_config,
        normalize_transport_modes=normalize_transport_modes,
        places_build=lambda with_optional=False: run_or_raise(lambda: places_service.build(with_optional=with_optional)),
        record_feedback=recommendation_service.record_feedback,
        register_platform_user=register_platform_user,
        remove_saved_place=recommendation_service.remove_saved_place,
        require_admin=require_admin,
        require_current_user=require_current_user,
        run_or_raise=run_or_raise,
        sample_locations=SAMPLE_LOCATIONS,
        search_attraction_places=places_service.search_attraction_places,
        to_float=to_float,
        transport_service=transport_service,
        update_saved_place_note=recommendation_service.update_saved_place_note,
        update_user_preferences=update_user_preferences,
        update_user_profile=update_user_profile,
        upsert_saved_place=recommendation_service.upsert_saved_place,
        weather_service=weather_service,
    )
    for router_factory in (
        routes_router.create_router,
        auth_router.create_router,
        admin_router.create_router,
        weather_router.create_router,
        places_router.create_router,
        recommendations_router.create_router,
        transport_router.create_router,
    ):
        app.include_router(router_factory(deps))


register_api_routers()
