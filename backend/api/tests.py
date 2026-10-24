import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import Client, SimpleTestCase

from .verify import FIXTURE_IDS, verify
from .views import PROJECT_RUNS


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
                checks = {check["name"]: check["status"] for check in result["report"]}
                self.assertEqual(checks["tests_unchanged"], "passed")
                self.assertEqual(checks["fix_applied_only_to_buggy_code"], "passed")
                self.assertEqual(len(result["test_fingerprint"]["before"]), 8)
                self.assertEqual(len(result["test_fingerprint"]["after"]), 8)

    def test_fixture_verify_rejects_test_file_modification(self):
        result = verify("sum_off_by_one", {"test_buggy.py": "# changed test"})
        checks = {check["name"]: check["status"] for check in result["report"]}
        self.assertEqual(result["after"]["status"], "not_run")
        self.assertEqual(checks["fix_applied_only_to_buggy_code"], "failed")
        self.assertEqual(
            result["before"]["test_file_hashes_after"],
            result["after"]["test_file_hashes_after"],
        )
        self.assertIn("test files are protected", result["after"]["output"])

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


class ProjectModeTests(SimpleTestCase):
    def setUp(self):
        self.allowed_temp = tempfile.TemporaryDirectory(prefix="allowed-projects-")
        self.allowed_root = Path(self.allowed_temp.name)
        self.project = self.allowed_root / "tiny-project"
        self.project.mkdir()
        (self.project / "value.py").write_text(
            "def value():\n    assert False\n", encoding="utf-8"
        )
        (self.project / "test_value.py").write_text(
            "import unittest\nfrom value import value\n\n"
            "class ValueTests(unittest.TestCase):\n"
            "    def test_value(self):\n        self.assertIsNone(value())\n",
            encoding="utf-8",
        )
        self.env_patch = patch.dict(os.environ, {
            "ALLOWED_PROJECT_ROOT": str(self.allowed_root),
            "OPENAI_API_KEY": "",
        })
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.client = Client()
        self.addCleanup(self._cleanup_project_runs)
        self.addCleanup(self.allowed_temp.cleanup)

    def _cleanup_project_runs(self):
        for run_id, record in list(PROJECT_RUNS.items()):
            if str(self.project) == record.get("project"):
                PROJECT_RUNS.pop(run_id, None)
                record["temporary_copy"].cleanup()

    def test_project_fix_passes_in_simulated_mode(self):
        response = self.client.post(
            "/api/project/fix",
            data=json.dumps({"path": str(self.project)}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        result = response.json()
        self.assertEqual(result["before"]["status"], "failed")
        self.assertEqual(result["after"]["status"], "passed", result)
        self.assertTrue(result["diagnosis"]["simulated"])
        self.assertTrue(result["test_files_unchanged"])
        self.assertTrue(all(check["status"] == "passed" for check in result["report"]))

    def test_project_outside_allowed_root_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="outside-project-") as outside:
            response = self.client.post(
                "/api/project/scan",
                data=json.dumps({"path": outside}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("ALLOWED_PROJECT_ROOT", response.json()["error"])

    def test_project_changes_to_test_files_are_rejected(self):
        change = {
            "cause": "test",
            "explanation": "test",
            "simulated": True,
            "changes": [{"file": "test_value.py", "new_content": "# altered test\n"}],
        }
        with patch("api.views.diagnose_project", return_value=change):
            response = self.client.post(
                "/api/project/fix",
                data=json.dumps({"path": str(self.project)}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("test files", response.json()["error"])
        self.assertIn("self.assertIsNone", (self.project / "test_value.py").read_text(encoding="utf-8"))
