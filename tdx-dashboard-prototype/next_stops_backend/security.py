"""HTTP security, CORS, and API-abuse protection for NEXT STOPS."""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
DEFAULT_MAX_BODY_BYTES = 256 * 1024
RATE_LIMIT_STORE: dict[str, deque[float]] = defaultdict(deque)
RATE_LIMIT_LOCK = threading.Lock()


def env_int(name: str, default: int, minimum: int = 0, maximum: int | None = None) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    value = max(minimum, value)
    return min(value, maximum) if maximum is not None else value


def split_env_list(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def configured_cors_origins() -> list[str]:
    return split_env_list(os.getenv(
        "NEXT_STOPS_CORS_ORIGINS",
        "http://127.0.0.1:5174,http://localhost:5174",
    ))


def configure_cors(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=configured_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def normalized_origin(value: str | None) -> str:
    parsed = urlparse(str(value or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def allowed_browser_origins() -> set[str]:
    origins = set()
    for value in configured_cors_origins() + split_env_list(os.getenv("NEXT_STOPS_TRUSTED_ORIGINS", "")):
        normalized = normalized_origin(value)
        if normalized:
            origins.add(normalized)
    return origins


def request_origin(request: Request) -> str:
    origin = normalized_origin(request.headers.get("origin"))
    if origin:
        return origin
    return normalized_origin(request.headers.get("referer"))


def client_ip(request: Request) -> str:
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit_for_path(path: str) -> tuple[int, int, str]:
    if path.startswith("/api/admin"):
        return env_int("NEXT_STOPS_RATE_LIMIT_ADMIN", 30, minimum=1), 60, "admin"
    if path.startswith("/api/auth"):
        return env_int("NEXT_STOPS_RATE_LIMIT_AUTH", 12, minimum=1), 60, "auth"
    if path in {"/api/recommend", "/api/recommendations", "/api/route"}:
        return env_int("NEXT_STOPS_RATE_LIMIT_RECOMMEND", 30, minimum=1), 60, "recommend"
    if path in {"/api/places/build", "/api/admin/places/rebuild"}:
        return env_int("NEXT_STOPS_RATE_LIMIT_BUILD", 3, minimum=1), 3600, "build"
    return env_int("NEXT_STOPS_RATE_LIMIT_DEFAULT", 180, minimum=1), 60, "default"


def check_rate_limit(request: Request) -> tuple[bool, int, int, str]:
    limit, window_seconds, bucket = rate_limit_for_path(request.url.path)
    if limit <= 0:
        return True, 0, window_seconds, bucket
    now = time.monotonic()
    key = f"{client_ip(request)}:{bucket}"
    with RATE_LIMIT_LOCK:
        hits = RATE_LIMIT_STORE[key]
        while hits and hits[0] <= now - window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            retry_after = max(1, int(window_seconds - (now - hits[0])))
            return False, retry_after, window_seconds, bucket
        hits.append(now)
    return True, 0, window_seconds, bucket


def security_headers_for(path: str) -> dict[str, str]:
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
        "Cache-Control": "no-store" if path.startswith(("/api/auth", "/api/admin")) else "private, max-age=30",
    }
    if path not in {"/docs", "/redoc", "/openapi.json"}:
        headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    if os.getenv("NEXT_STOPS_ENABLE_HSTS", "").lower() in {"1", "true", "yes"}:
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return headers


def protected_error(status_code: int, detail: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status_code, headers=headers or {})


def unsafe_request_rejection(request: Request, body_size: int) -> tuple[int, str] | None:
    origin = request_origin(request)
    allowed_origins = allowed_browser_origins()
    if origin and origin not in allowed_origins:
        return 403, "Request origin is not allowed"
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if body_size > 0 and content_type != "application/json":
        return 415, "Only application/json requests are accepted"
    return None


def install_api_abuse_protection(app: FastAPI) -> None:
    @app.middleware("http")
    async def api_abuse_protection(request: Request, call_next):
        path = request.url.path
        max_body = env_int("NEXT_STOPS_MAX_BODY_BYTES", DEFAULT_MAX_BODY_BYTES, minimum=1024)
        content_length = request.headers.get("content-length")
        try:
            body_size = int(content_length or "0")
        except ValueError:
            body_size = max_body + 1
        if body_size > max_body:
            response = protected_error(413, "Request body too large")
        else:
            allowed, retry_after, _window, _bucket = check_rate_limit(request)
            if not allowed:
                response = protected_error(429, "Too many requests", {"Retry-After": str(retry_after)})
            elif request.method in UNSAFE_METHODS:
                rejection = unsafe_request_rejection(request, body_size)
                if rejection:
                    response = protected_error(rejection[0], rejection[1])
                else:
                    response = await call_next(request)
            else:
                response = await call_next(request)
        for key, value in security_headers_for(path).items():
            response.headers.setdefault(key, value)
        return response


def security_config_summary() -> dict[str, Any]:
    return {
        "csrf": {
            "strategy": "authorization-header-with-origin-guard",
            "trusted_origins": sorted(allowed_browser_origins()),
            "unsafe_methods": sorted(UNSAFE_METHODS),
        },
        "xss": {
            "security_headers": True,
            "content_security_policy": "api-default-src-none",
        },
        "abuse_protection": {
            "max_body_bytes": env_int("NEXT_STOPS_MAX_BODY_BYTES", DEFAULT_MAX_BODY_BYTES, minimum=1024),
            "json_only_unsafe_methods": True,
            "rate_limits": {
                "default_per_minute": env_int("NEXT_STOPS_RATE_LIMIT_DEFAULT", 180, minimum=1),
                "auth_per_minute": env_int("NEXT_STOPS_RATE_LIMIT_AUTH", 12, minimum=1),
                "admin_per_minute": env_int("NEXT_STOPS_RATE_LIMIT_ADMIN", 30, minimum=1),
                "recommend_per_minute": env_int("NEXT_STOPS_RATE_LIMIT_RECOMMEND", 30, minimum=1),
                "build_per_hour": env_int("NEXT_STOPS_RATE_LIMIT_BUILD", 3, minimum=1),
            },
        },
    }
