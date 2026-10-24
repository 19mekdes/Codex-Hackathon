import json
import os
import difflib
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from pathlib import PurePosixPath

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .ai import analyze_code, diagnose, diagnose_project
from .verify import (
    FIXTURE_IDS,
    _copy_project,
    _eligible_project_files,
    _project_test_files_hash,
    _run_project_copy,
    fixture_test_fingerprint,
    is_test_file,
    project_command_label,
    project_test_command,
    project_test_files_hash,
    resolve_project_path,
    run_project_tests,
    run_tests,
    verify,
)


TITLES = {
    "sum_off_by_one": "Off-by-one sum",
    "none_check": "Missing None check",
}
RECORDED_PATH = Path(__file__).resolve().parent / "recorded_demo.json"
PROJECT_RUNS = {}
LATEST_PROJECT_RUNS = {}
PROJECT_MAX_CONTEXT_FILES = 3
PROJECT_MAX_CONTEXT_BYTES = 200 * 1024
ANALYSIS_MAX_FIELD_BYTES = 100 * 1024


def _public_fixture_test_result(result):
    return {key: result[key] for key in ("status", "output") if key in result}


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
    result = verify(fixture_id, fixed_code)
    result["before"] = _public_fixture_test_result(result["before"])
    result["after"] = _public_fixture_test_result(result["after"])
    result.pop("test_hashes", None)
    return JsonResponse(result)


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
def analyze_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed."}, status=405)
    payload, error_response = _json_request(request)
    if error_response:
        return error_response

    language = payload.get("language")
    code = payload.get("code")
    error_message = payload.get("error_message")
    if language != "python":
        return JsonResponse({"error": "Only Python is supported right now."}, status=400)
    if not isinstance(code, str) or not code.strip():
        return JsonResponse({"error": "code is required and must not be empty."}, status=400)
    if not isinstance(error_message, str) or not error_message.strip():
        return JsonResponse({"error": "error_message is required and must not be empty."}, status=400)
    if len(code.encode("utf-8")) > ANALYSIS_MAX_FIELD_BYTES:
        return JsonResponse({"error": "code must be 100 KB or smaller."}, status=413)
    if len(error_message.encode("utf-8")) > ANALYSIS_MAX_FIELD_BYTES:
        return JsonResponse({"error": "error_message must be 100 KB or smaller."}, status=413)
    if not os.getenv("OPENAI_API_KEY"):
        return JsonResponse({"error": "OPENAI_API_KEY is required for code analysis."}, status=503)
    if not os.getenv("OPENAI_MODEL"):
        return JsonResponse({"error": "OPENAI_MODEL is not configured."}, status=503)

    try:
        diagnosis = analyze_code(code, error_message)
    except (ValueError, RuntimeError) as exc:
        return JsonResponse({"error": str(exc)}, status=502)
    except Exception:
        return JsonResponse({"error": "AI analysis failed."}, status=502)

    return JsonResponse({
        "success": True,
        "language": language,
        "root_cause": diagnosis["root_cause"],
        "explanation": diagnosis["explanation"],
        "fixed_code": diagnosis["fixed_code"],
        "changes": diagnosis["changes"],
        "suggested_tests": diagnosis["suggested_tests"],
        "verification": {
            "status": "not_run",
            "message": "The proposed fix has not been executed against tests.",
        },
    })


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
        "before": _public_fixture_test_result(result["before"]),
        "after": _public_fixture_test_result(result["after"]),
        "report": result["report"],
        "simulated": bool(diagnosis.get("simulated", False)),
        "test_fingerprint": {
            "before": fixture_test_fingerprint(before.get("test_file_hashes_before", {}))[:8],
            "after": fixture_test_fingerprint(result.get("test_hashes", {}).get("after", {}))[:8],
        },
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


def health_view(request):
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed."}, status=405)
    return JsonResponse({
        "ok": True,
        "ai_configured": bool(os.getenv("OPENAI_API_KEY")),
        "model": os.getenv("OPENAI_MODEL") or None,
    })


def _json_request(request):
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, JsonResponse({"error": "Request body must be valid JSON."}, status=400)
    if not isinstance(payload, dict):
        return None, JsonResponse({"error": "Request body must be a JSON object."}, status=400)
    return payload, None


def _traceback_project_sources(project_copy, output):
    selected = {}
    total_bytes = 0
    candidates = [
        Path(match.group(1))
        for match in re.finditer(r'File ["\']([^"\']+)["\'],\s*line\s+\d+', output)
    ]
    candidates.extend(
        Path(match.group(1))
        for match in re.finditer(r"(?m)^([\w./\\-]+\.py):\d+(?::\d+)?\s*:?", output)
    )
    for candidate in candidates:
        try:
            candidate_path = candidate if candidate.is_absolute() else project_copy / candidate
            traceback_path = candidate_path.resolve(strict=True)
            relative = traceback_path.relative_to(project_copy.resolve()).as_posix()
        except (OSError, ValueError, RuntimeError):
            continue
        relative_path = PurePosixPath(relative)
        if (
            relative in selected
            or relative_path.name == ".env"
            or is_test_file(relative_path)
        ):
            continue
        try:
            size = traceback_path.stat().st_size
            if size > 200 * 1024 or total_bytes + size > PROJECT_MAX_CONTEXT_BYTES:
                continue
            content = traceback_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        selected[relative] = content
        total_bytes += size
        if len(selected) >= PROJECT_MAX_CONTEXT_FILES:
            break
    return selected


def _validated_project_changes(changes, source_files, project_copy):
    if not isinstance(changes, list):
        raise ValueError("Diagnosis changes must be a list.")
    allowed = set(source_files)
    validated = {}
    total_bytes = 0
    for change in changes:
        if not isinstance(change, dict):
            raise ValueError("Each diagnosis change must be an object.")
        filename = change.get("file")
        new_content = change.get("new_content")
        if not isinstance(filename, str) or not isinstance(new_content, str):
            raise ValueError("Each diagnosis change needs a file and string new_content.")
        normalized = filename.replace("\\", "/")
        relative = PurePosixPath(normalized)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("Diagnosis returned a path outside the project.")
        relative_name = relative.as_posix()
        if relative.name == ".env" or is_test_file(relative):
            raise ValueError("Diagnosis is not allowed to change test files or .env.")
        if relative_name not in allowed:
            raise ValueError("Diagnosis may only change files included from the traceback.")
        target = project_copy.joinpath(*relative.parts)
        try:
            resolved_target = target.resolve(strict=True)
            resolved_target.relative_to(project_copy.resolve(strict=True))
        except (OSError, ValueError, RuntimeError) as exc:
            raise ValueError("Diagnosis returned a path outside the project.") from exc
        if not resolved_target.is_file() or resolved_target.is_symlink():
            raise ValueError("Diagnosis changes must target an existing regular project file.")
        if relative_name in validated:
            raise ValueError("Diagnosis returned duplicate changes for one file.")
        total_bytes += len(new_content.encode("utf-8"))
        if total_bytes > PROJECT_MAX_CONTEXT_BYTES:
            raise ValueError("Diagnosis changes exceed the 200 KB limit.")
        validated[relative_name] = new_content
    return validated


def _apply_to_copy(project_copy, changes):
    for relative, content in changes.items():
        (project_copy / Path(relative)).write_text(content, encoding="utf-8")


def _project_diff(project, project_copy, paths):
    diffs = []
    for relative in sorted(paths):
        original = (project / Path(relative)).read_text(encoding="utf-8").splitlines(keepends=True)
        fixed = (project_copy / Path(relative)).read_text(encoding="utf-8").splitlines(keepends=True)
        diff = "".join(difflib.unified_diff(
            original,
            fixed,
            fromfile=f"a/{relative}",
            tofile=f"b/{relative}",
        ))
        diffs.append({"file": relative, "diff": diff})
    return diffs


@csrf_exempt
def project_scan_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed."}, status=405)
    payload, error_response = _json_request(request)
    if error_response:
        return error_response
    raw_path = payload.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return JsonResponse({"error": "path is required."}, status=400)
    try:
        project = resolve_project_path(raw_path)
        command = project_test_command(project)
        files = [path.as_posix() for path in _eligible_project_files(project)]
    except (OSError, ValueError, TypeError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    before = run_project_tests(project)
    return JsonResponse({
        "test_command": project_command_label(command),
        "files": files,
        "before": before,
    })


@csrf_exempt
def project_fix_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed."}, status=405)
    payload, error_response = _json_request(request)
    if error_response:
        return error_response
    raw_path = payload.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return JsonResponse({"error": "path is required."}, status=400)
    try:
        project = resolve_project_path(raw_path)
    except (OSError, ValueError, TypeError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    temporary_copy = tempfile.TemporaryDirectory(prefix="project-fix-")
    project_copy = Path(temporary_copy.name) / "project"
    try:
        _copy_project(project, project_copy)
        baseline_hash = _project_test_files_hash(project_copy)
        before = _run_project_copy(project_copy)
        if before["status"] == "not_run":
            temporary_copy.cleanup()
            return JsonResponse({"error": "Project tests could not be run.", "before": before}, status=500)
        if before["status"] == "passed":
            temporary_copy.cleanup()
            return JsonResponse({"error": "Project tests already pass; there is no failing run to fix.", "before": before}, status=400)

        original_source_files = _traceback_project_sources(project_copy, before["output"])
        original_contents = {
            relative: (project / Path(relative)).read_bytes()
            for relative in original_source_files
        }
        diagnosis_code = json.dumps(original_source_files)
        try:
            diagnosis = diagnose_project(diagnosis_code, before["output"])
        except ValueError as exc:
            temporary_copy.cleanup()
            return JsonResponse({"error": str(exc), "before": before}, status=502)
        except Exception:
            temporary_copy.cleanup()
            return JsonResponse({"error": "Project diagnosis failed."}, status=502)

        try:
            changes = _validated_project_changes(
                diagnosis.get("changes"), original_source_files, project_copy
            )
        except (AttributeError, ValueError) as exc:
            temporary_copy.cleanup()
            return JsonResponse({"error": str(exc)}, status=400)
        _apply_to_copy(project_copy, changes)
        cumulative_changes = dict(changes)
        after = _run_project_copy(project_copy)

        if after["status"] == "failed":
            retry_sources = _traceback_project_sources(project_copy, after["output"])
            retry_code = json.dumps(retry_sources)
            retry_error = f"Retry the repair using this new failing test output:\n{after['output']}"
            try:
                diagnosis = diagnose_project(retry_code, retry_error)
                retry_changes = _validated_project_changes(
                    diagnosis.get("changes"), retry_sources, project_copy
                )
            except (ValueError, AttributeError) as exc:
                temporary_copy.cleanup()
                return JsonResponse({"error": str(exc), "before": before, "after": after}, status=400)
            except Exception:
                temporary_copy.cleanup()
                return JsonResponse({"error": "Project diagnosis retry failed."}, status=502)
            _apply_to_copy(project_copy, retry_changes)
            cumulative_changes.update(retry_changes)
            after = _run_project_copy(project_copy)

        test_files_unchanged = (
            before["test_files_hash"] == _project_test_files_hash(project_copy)
            and before["test_files_hash"] == baseline_hash
        )
        report = [
            {"name": "Baseline tests fail", "status": "passed" if before["status"] == "failed" else "failed"},
            {"name": "Test files unchanged", "status": "passed" if test_files_unchanged else "failed"},
            {"name": "Fixed tests pass", "status": "passed" if after["status"] == "passed" else ("not_run" if after["status"] == "not_run" else "failed")},
        ]
        if after["status"] == "failed":
            report.append({"name": "Could not verify this fix", "status": "failed"})

        run_id = str(uuid.uuid4())
        diffs = _project_diff(project, project_copy, cumulative_changes)
        PROJECT_RUNS[run_id] = {
            "temporary_copy": temporary_copy,
            "project": str(project),
            "project_copy": str(project_copy),
            "passed": all(check["status"] == "passed" for check in report),
            "test_files_hash": before["test_files_hash"],
            "changes": cumulative_changes,
            "original_contents": original_contents,
            "diagnosis": diagnosis,
            "before": before,
            "after": after,
            "report": report,
            "diffs": diffs,
        }
        LATEST_PROJECT_RUNS[str(project)] = run_id
        return JsonResponse({
            "diagnosis": diagnosis,
            "before": before,
            "after": after,
            "report": report,
            "diffs": diffs,
            "test_files_unchanged": test_files_unchanged,
            "run_id": run_id,
        })
    except (OSError, UnicodeError, ValueError) as exc:
        temporary_copy.cleanup()
        return JsonResponse({"error": str(exc)}, status=400)


@csrf_exempt
def project_apply_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed."}, status=405)
    payload, error_response = _json_request(request)
    if error_response:
        return error_response
    raw_path = payload.get("path")
    run_id = payload.get("run_id")
    if not isinstance(raw_path, str) or not isinstance(run_id, str):
        return JsonResponse({"error": "path and run_id are required."}, status=400)
    if payload.get("confirmed") is not True:
        return JsonResponse({"error": "Explicit confirmation is required to apply project changes."}, status=400)
    record = PROJECT_RUNS.get(run_id)
    if record is None:
        return JsonResponse({"error": "Unknown or expired project run_id."}, status=404)
    try:
        project = resolve_project_path(raw_path)
    except (OSError, ValueError, TypeError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    if str(project) != record["project"]:
        return JsonResponse({"error": "path does not match the verified project run."}, status=400)
    if LATEST_PROJECT_RUNS.get(str(project)) != run_id:
        return JsonResponse({"error": "run_id is not the latest project verification."}, status=409)
    if not record["passed"] or record["after"]["status"] != "passed":
        return JsonResponse({"error": "Only a fully passed project run can be applied."}, status=409)
    try:
        if project_test_files_hash(project) != record["test_files_hash"]:
            return JsonResponse({"error": "Project test files changed after verification."}, status=409)
        backup_pairs = []
        for relative, new_content in record["changes"].items():
            source = project / Path(relative)
            if not source.is_file() or source.is_symlink() or is_test_file(relative):
                return JsonResponse({"error": "A changed project file is no longer safe to apply."}, status=409)
            resolved_source = source.resolve(strict=True)
            try:
                resolved_source.relative_to(project.resolve(strict=True))
            except ValueError:
                return JsonResponse({"error": "A changed project file escaped the project folder."}, status=409)
            if source.read_bytes() != record["original_contents"].get(relative):
                return JsonResponse({"error": f"Project file changed after verification: {relative}."}, status=409)
            source = resolved_source
            backup = source.with_name(source.name + ".fixproof.bak")
            if backup.exists():
                return JsonResponse({"error": f"Backup already exists for {relative}."}, status=409)
            backup_pairs.append((source, backup, new_content))
        for source, backup, _ in backup_pairs:
            shutil.copy2(source, backup)
        written = []
        try:
            for source, _backup, new_content in backup_pairs:
                source.write_text(new_content, encoding="utf-8")
                written.append(source)
        except OSError:
            for source, backup, _ in backup_pairs:
                if backup.exists():
                    shutil.copy2(backup, source)
            raise
    except OSError as exc:
        return JsonResponse({"error": f"Could not apply verified changes: {exc}"}, status=500)

    PROJECT_RUNS.pop(run_id, None)
    LATEST_PROJECT_RUNS.pop(str(project), None)
    record["temporary_copy"].cleanup()
    return JsonResponse({
        "applied": True,
        "backups": [str(backup) for _source, backup, _content in backup_pairs],
        "files": [str(source.relative_to(project)) for source, _backup, _content in backup_pairs],
    })
