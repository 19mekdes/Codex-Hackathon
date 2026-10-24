import json
import os
from unittest.mock import patch

from django.test import Client, SimpleTestCase

from .verify import FIXTURE_IDS


class ApiEndpointTests(SimpleTestCase):
    def setUp(self):
        self.client = Client()
        self.no_api_key = patch.dict(os.environ, {"OPENAI_API_KEY": ""})
        self.no_api_key.start()
        self.addCleanup(self.no_api_key.stop)

    def test_get_fixtures(self):
        response = self.client.get("/api/fixtures/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), len(FIXTURE_IDS))
        self.assertTrue(all(item.get("error") for item in response.json()))

    def test_fix_each_fixture_uses_simulated_verified_fix(self):
        for fixture_id in FIXTURE_IDS:
            with self.subTest(fixture_id=fixture_id):
                response = self.client.post(
                    "/api/fix/",
                    data=json.dumps({"fixture_id": fixture_id}),
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 200, response.content)
                result = response.json()
                self.assertEqual(result["after"]["status"], "passed")
                self.assertTrue(result["simulated"])
                self.assertTrue(result["diagnosis"]["simulated"])

    def test_fix_unknown_fixture_returns_json_error(self):
        response = self.client.post(
            "/api/fix/",
            data=json.dumps({"fixture_id": "../outside"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "Unknown fixture id."})

    def test_health_does_not_expose_key(self):
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "ok": True,
            "ai_configured": False,
            "model": os.getenv("OPENAI_MODEL") or None,
        })

    def test_cors_preflight_allows_local_frontend_only(self):
        response = self.client.options(
            "/api/health/",
            HTTP_ORIGIN="http://localhost:5173",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["Access-Control-Allow-Origin"], "http://localhost:5173")
        denied = self.client.options("/api/health/", HTTP_ORIGIN="https://example.com")
        self.assertNotIn("Access-Control-Allow-Origin", denied)
