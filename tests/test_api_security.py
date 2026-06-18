import hashlib
import importlib
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "tdx-dashboard-prototype"

os.environ["DATABASE_URL"] = ""
os.environ["POSTGRES_URL"] = ""
os.environ["NEXT_STOPS_DATABASE_URL"] = ""
os.environ["NEXT_STOPS_CORS_ORIGINS"] = "http://127.0.0.1:5174,http://localhost:5174"
os.environ["NEXT_STOPS_TRUSTED_ORIGINS"] = "http://127.0.0.1:5174,http://localhost:5174"
os.environ["NEXT_STOPS_RATE_LIMIT_DEFAULT"] = "2"
os.environ["NEXT_STOPS_RATE_LIMIT_AUTH"] = "20"
os.environ["NEXT_STOPS_RATE_LIMIT_ADMIN"] = "20"
os.environ["NEXT_STOPS_RATE_LIMIT_RECOMMEND"] = "20"
os.environ["NEXT_STOPS_MAX_BODY_BYTES"] = "128"
os.environ["ADMIN_TOKEN"] = ""
os.environ["ADMIN_TOKEN_SHA256"] = hashlib.sha256(b"test-admin-token").hexdigest()

sys.path.insert(0, str(API_ROOT))
api_app = importlib.import_module("api_app")


class FakeRequest:
    def __init__(self, path="/health", headers=None, host="203.0.113.10"):
        self.url = SimpleNamespace(path=path)
        self.headers = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
        self.client = SimpleNamespace(host=host)


class ApiSecurityTests(unittest.TestCase):
    def setUp(self):
        api_app.RATE_LIMIT_STORE.clear()

    def test_security_headers_are_defined(self):
        headers = api_app.security_headers_for("/api/auth/me")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_cross_origin_unsafe_request_is_blocked(self):
        request = FakeRequest("/api/recommend", {"origin": "https://evil.example", "content-type": "application/json"})
        self.assertEqual(api_app.unsafe_request_rejection(request, 2), (403, "Request origin is not allowed"))

    def test_unsafe_request_requires_json_content_type(self):
        request = FakeRequest("/api/recommend", {"origin": "http://127.0.0.1:5174", "content-type": "text/plain"})
        self.assertEqual(api_app.unsafe_request_rejection(request, 8), (415, "Only application/json requests are accepted"))

    def test_allowed_json_unsafe_request_passes(self):
        request = FakeRequest("/api/recommend", {"origin": "http://127.0.0.1:5174", "content-type": "application/json"})
        self.assertIsNone(api_app.unsafe_request_rejection(request, 8))

    def test_default_rate_limit_returns_retry_after(self):
        request = FakeRequest("/health")
        self.assertTrue(api_app.check_rate_limit(request)[0])
        self.assertTrue(api_app.check_rate_limit(request)[0])
        allowed, retry_after, _window, bucket = api_app.check_rate_limit(request)
        self.assertFalse(allowed)
        self.assertGreaterEqual(retry_after, 1)
        self.assertEqual(bucket, "default")

    def test_admin_token_query_string_is_not_part_of_validation(self):
        with self.assertRaises(HTTPException) as raised:
            api_app.require_admin(None)
        self.assertEqual(raised.exception.status_code, 401)

    def test_admin_sha256_token_header_is_accepted(self):
        self.assertIsNone(api_app.require_admin("test-admin-token"))

    def test_service_area_allows_taipei_main_station(self):
        self.assertTrue(api_app.is_within_service_area(25.0478, 121.5170))
        self.assertEqual(api_app.find_service_area(25.0478, 121.5170)["name"], "中正區")
        self.assertIsNone(api_app.validate_criteria_service_area({"lat": 25.0478, "lon": 121.5170}))

    def test_service_area_allows_new_taipei(self):
        self.assertTrue(api_app.is_within_service_area(25.0143, 121.4639))
        self.assertEqual(api_app.find_service_area(25.0143, 121.4639)["name"], "板橋區")

    def test_service_area_blocks_outside_current_location(self):
        self.assertFalse(api_app.is_within_service_area(24.1477, 120.6736))
        with self.assertRaises(ValueError):
            api_app.validate_criteria_service_area({"lat": 24.1477, "lon": 120.6736})

    def test_service_area_blocks_keelung(self):
        self.assertFalse(api_app.is_within_service_area(25.1276, 121.7392))

    def test_favorite_start_must_be_inside_service_area(self):
        with self.assertRaises(ValueError):
            api_app.normalize_favorite_starts([{"label": "台中車站", "lat": 24.1368, "lon": 120.6850}])


if __name__ == "__main__":
    unittest.main()
