import json
from pathlib import Path

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .ai import diagnose
from .verify import FIXTURE_IDS, run_tests, verify


TITLES = {
    "sum_off_by_one": "Off-by-one sum",
    "none_check": "Missing None check",
}
RECORDED_PATH = Path(__file__).resolve().parent / "recorded_demo.json"


@csrf_exempt
def fixtures(request):
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed."}, status=405)

    entries = []
    for fixture_id in FIXTURE_IDS:
        fixture_dir = Path(__file__).resolve().parent / "fixtures" / fixture_id
        code = (fixture_dir / "buggy.py").read_text(encoding="utf-8")
        result = run_tests(fixture_id)
        entries.append({
            "id": fixture_id,
            "title": TITLES[fixture_id],
            "code": code,
            "error": result["output"],
        })
    return JsonResponse(entries, safe=False)


@csrf_exempt
def verify_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed."}, status=405)
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Request body must be valid JSON."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"error": "Request body must be a JSON object."}, status=400)
    fixture_id = payload.get("fixture_id")
    fixed_code = payload.get("fixed_code")
    if fixture_id not in FIXTURE_IDS:
        return JsonResponse({"error": "Unknown fixture id."}, status=400)
    if not isinstance(fixed_code, str):
        return JsonResponse({"error": "fixed_code must be a string."}, status=400)
    return JsonResponse(verify(fixture_id, fixed_code))


@csrf_exempt
def diagnose_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed."}, status=405)
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Request body must be valid JSON."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"error": "Request body must be a JSON object."}, status=400)
    code = payload.get("code")
    error = payload.get("error")
    fixture_id = payload.get("fixture_id")
    if not isinstance(code, str) or not isinstance(error, str):
        return JsonResponse({"error": "code and error must be strings."}, status=400)
    if fixture_id is not None and not isinstance(fixture_id, str):
        return JsonResponse({"error": "fixture_id must be a string when provided."}, status=400)
    try:
        return JsonResponse(diagnose(code, error, fixture_id=fixture_id))
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception:
        return JsonResponse({"error": "Diagnosis service request failed."}, status=502)


@csrf_exempt
def fix_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed."}, status=405)
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Request body must be valid JSON."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"error": "Request body must be a JSON object."}, status=400)

    fixture_id = payload.get("fixture_id")
    if not isinstance(fixture_id, str) or fixture_id not in FIXTURE_IDS:
        return JsonResponse({"error": "Unknown fixture id."}, status=400)

    fixture_dir = Path(__file__).resolve().parent / "fixtures" / fixture_id
    buggy_path = fixture_dir / "buggy.py"
    if not buggy_path.is_file():
        return JsonResponse({"error": "Fixture code is missing."}, status=404)

    try:
        code = buggy_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return JsonResponse({"error": "Fixture code could not be read."}, status=500)
    before = run_tests(fixture_id)
    if before["status"] == "not_run":
        return JsonResponse({"error": "Could not run the fixture tests.", "before": before}, status=500)

    try:
        diagnosis = diagnose(code, before["output"], fixture_id=fixture_id)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception:
        return JsonResponse({"error": "Diagnosis service request failed."}, status=502)

    fixed_code = diagnosis.get("fixed_code") if isinstance(diagnosis, dict) else None
    if not isinstance(fixed_code, str):
        return JsonResponse({"error": "Diagnosis did not include valid fixed_code."}, status=502)

    result = verify(fixture_id, fixed_code)
    result["before"] = before
    if result["after"]["status"] != "passed":
        retry_error = (
            f"Initial verification output:\n{result['after']['output']}\n"
            "Please revise the fix and return JSON with cause, explanation, and fixed_code."
        )
        try:
            diagnosis = diagnose(code, retry_error, fixture_id=fixture_id)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        except Exception:
            return JsonResponse({"error": "Diagnosis retry failed."}, status=502)
        fixed_code = diagnosis.get("fixed_code") if isinstance(diagnosis, dict) else None
        if not isinstance(fixed_code, str):
            return JsonResponse({"error": "Diagnosis did not include valid fixed_code."}, status=502)
        result = verify(fixture_id, fixed_code)
        result["before"] = before
        if result["after"]["status"] == "failed":
            result["report"].append({"name": "Could not verify this fix", "status": "failed"})

    response = {
        "diagnosis": diagnosis,
        "before": result["before"],
        "after": result["after"],
        "report": result["report"],
        "simulated": bool(diagnosis.get("simulated", False)),
    }
    fully_passed = (
        response["before"]["status"] == "failed"
        and response["after"]["status"] == "passed"
        and all(check["status"] == "passed" for check in response["report"])
    )
    if fully_passed:
        try:
            RECORDED_PATH.write_text(json.dumps(response, indent=2), encoding="utf-8")
        except OSError:
            return JsonResponse({"error": "Could not save the verified result."}, status=500)
    return JsonResponse(response)


def recorded_view(request):
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed."}, status=405)
    try:
        data = json.loads(RECORDED_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return JsonResponse({"error": "No verified demo has been recorded yet."}, status=404)
    except (OSError, json.JSONDecodeError):
        return JsonResponse({"error": "Recorded demo data is unavailable or invalid."}, status=500)
    if not isinstance(data, dict):
        return JsonResponse({"error": "Recorded demo data is invalid."}, status=500)
    data["recorded"] = True
    return JsonResponse(data)
