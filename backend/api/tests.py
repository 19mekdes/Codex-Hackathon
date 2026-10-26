import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import Client, SimpleTestCase # type: ignore

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
                checks = {check["name"]: check["status"]
                          for check in result["report"]}
                self.assertEqual(checks["tests_unchanged"], "passed")
                self.assertEqual(
                    checks["fix_applied_only_to_buggy_code"], "passed")
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

    def _analysis_request(self, payload=None):
        return self.client.post(
            "/api/analyze/",
            data=json.dumps(payload if payload is not None else {
                "language": "python",
                "code": "print(10 / 0)",
                "error_message": "ZeroDivisionError: division by zero",
            }),
            content_type="application/json",
        )

    def _mock_openai(self, content):
        client = Mock()
        client.chat.completions.create.return_value.choices = [
            SimpleNamespace(message=SimpleNamespace(content=content))
        ]
        sdk = SimpleNamespace(OpenAI=Mock(return_value=client))
        self.openai_client = client
        self.openai_constructor = sdk.OpenAI
        self.openai_modules = patch.dict(sys.modules, {"openai": sdk})
        self.openai_modules.start()
        self.addCleanup(self.openai_modules.stop)

    def test_analyze_returns_structured_result_without_running_tests(self):
        content = json.dumps({
            "root_cause": "The denominator is zero.",
            "explanation": "An empty list has no values to average.",
            "fixed_code": "if not numbers: return 0",
            "changes": ["Handle empty input before dividing."],
            "suggested_tests": [{"name": "Empty input", "description": "Check an empty list."}],
        })
        self._mock_openai(content)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-secret", "OPENAI_MODEL": "test-model"}):
            response = self._analysis_request()
        self.assertEqual(response.status_code, 200, response.content)
        result = response.json()
        self.assertTrue(result["success"])
        self.assertEqual(result["verification"]["status"], "not_run")
        self.assertEqual(result["root_cause"], "The denominator is zero.")
        self.assertNotIn("test-secret", response.content.decode())
        self.openai_constructor.assert_called_once_with(
            api_key="test-secret", timeout=30.0)
        self.assertEqual(
            self.openai_client.chat.completions.create.call_args.kwargs["model"], "test-model")

    def test_analyze_rejects_missing_or_empty_inputs(self):
        cases = [
            {"language": "python", "code": "", "error_message": "error"},
            {"language": "python", "code": "print(1)", "error_message": " "},
            {"language": "python", "error_message": "error"},
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                response = self._analysis_request(payload)
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())

    def test_analyze_rejects_unsupported_language_and_oversized_code(self):
        unsupported = self._analysis_request(
            {"language": "javascript", "code": "x", "error_message": "error"})
        self.assertEqual(unsupported.status_code, 400)
        oversized = self._analysis_request(
            {"language": "python", "code": "x" * (100 * 1024 + 1), "error_message": "error"})
        self.assertEqual(oversized.status_code, 413)

    def test_analyze_missing_key_returns_configuration_error(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "", "OPENAI_MODEL": "test-model"}):
            response = self._analysis_request()
        self.assertEqual(response.status_code, 503)
        self.assertIn("OPENAI_API_KEY", response.json()["error"])

    def test_analyze_rejects_malformed_ai_json_safely(self):
        self._mock_openai("not JSON")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-secret", "OPENAI_MODEL": "test-model"}):
            response = self._analysis_request()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"],
                         "AI returned malformed analysis JSON.")

    def test_analyze_provider_error_is_safe(self):
        client = Mock()
        client.chat.completions.create.side_effect = ValueError(
            "provider secret diagnostic")
        sdk = SimpleNamespace(OpenAI=Mock(return_value=client))
        module_patch = patch.dict(sys.modules, {"openai": sdk})
        module_patch.start()
        self.addCleanup(module_patch.stop)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-secret", "OPENAI_MODEL": "test-model"}):
            response = self._analysis_request()
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("provider secret", response.content.decode())
        self.assertNotIn("test-secret", response.content.decode())

    def test_cors_preflight_allows_local_frontend_only(self):
        response = self.client.options(
            "/api/health/",
            HTTP_ORIGIN="http://localhost:5173",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            response["Access-Control-Allow-Origin"], "http://localhost:5173")
        denied = self.client.options(
            "/api/health/", HTTP_ORIGIN="https://example.com")
        self.assertNotIn("Access-Control-Allow-Origin", denied)


class ProjectModeTests(SimpleTestCase):
    def setUp(self):
        self.allowed_temp = tempfile.TemporaryDirectory(
            prefix="allowed-projects-")
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
        self.assertTrue(
            all(check["status"] == "passed" for check in result["report"]))

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
        self.assertIn("self.assertIsNone", (self.project /
                      "test_value.py").read_text(encoding="utf-8"))
