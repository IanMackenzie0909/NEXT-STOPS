"""Shared HTTP client with retry and rate-limit handling."""

from __future__ import annotations

import time
from typing import Any

import requests


class ApiClientError(Exception):
    """Base exception for remote API failures."""


class ClientConfigError(ApiClientError):
    """Raised when a required API key or credential is missing."""


class BaseHttpClient:
    def __init__(self, timeout: int = 15, retries: int = 2, session: requests.Session | None = None):
        self.timeout = timeout
        self.retries = retries
        self.session = session or requests.Session()

    def request_json(self, method: str, url: str, *, headers: dict[str, str] | None = None, **kwargs) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.session.request(method, url, timeout=self.timeout, headers=headers, **kwargs)
                if response.status_code == 429 and attempt < self.retries:
                    retry_after = _parse_int(response.headers.get("Retry-After"), 3)
                    time.sleep(retry_after)
                    continue
                response.raise_for_status()
                if not response.content:
                    return None
                return response.json()
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(1.25 * (attempt + 1))
                    continue
                raise ApiClientError(f"API request failed: {url}: {exc}") from exc
        raise ApiClientError(f"API request failed: {url}: {last_error}")


def _parse_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
