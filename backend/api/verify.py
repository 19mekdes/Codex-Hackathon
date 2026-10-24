import os
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
FIXTURE_IDS = ("sum_off_by_one", "none_check")
PROJECT_SKIP_NAMES = {".git", "venv", "node_modules", "__pycache__", ".env"}
PROJECT_MAX_FILE_SIZE = 200 * 1024


def resolve_project_path(project_path):
    allowed_root_value = os.getenv("ALLOWED_PROJECT_ROOT")
    if not allowed_root_value:
        raise ValueError("ALLOWED_PROJECT_ROOT is not configured.")
    try:
        allowed_root = Path(allowed_root_value).expanduser().resolve(strict=True)
        project = Path(project_path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ValueError("Project path is invalid or does not exist.") from exc
    if not allowed_root.is_dir() or not project.is_dir():
        raise ValueError("Project path and ALLOWED_PROJECT_ROOT must be folders.")
    if project == allowed_root or not project.is_relative_to(allowed_root):
        raise ValueError("Project path must be inside ALLOWED_PROJECT_ROOT.")

    # Inspect symlinks without following directory links. Reject any that point
    # outside the allowed tree; safe in-project links are omitted from copies.
    for current, dirs, files in os.walk(project, followlinks=False):
        for name in dirs + files:
            item = Path(current) / name
            if item.is_symlink():
                try:
                    target = item.resolve(strict=True)
                except (OSError, RuntimeError) as exc:
                    raise ValueError("Project contains a broken or looping symlink.") from exc
                if target != allowed_root and not target.is_relative_to(allowed_root):
                    raise ValueError("Project contains a symlink that escapes ALLOWED_PROJECT_ROOT.")
    return project


def is_test_file(relative_path):
    path = Path(relative_path)
    filename = path.name.lower()
    return (
        "tests" in {part.lower() for part in path.parts}
        or filename.startswith("test")
        or filename.endswith("_test.py")
    )


def _eligible_project_files(project_path):
    project = Path(project_path).resolve(strict=True)
    files = []
    for current, dirs, names in os.walk(project, followlinks=False):
        dirs[:] = sorted(
            name for name in dirs
            if name not in PROJECT_SKIP_NAMES and not (Path(current) / name).is_symlink()
        )
        for name in sorted(names):
            source = Path(current) / name
            if name == ".env" or source.is_symlink():
                continue
            try:
                if source.stat().st_size > PROJECT_MAX_FILE_SIZE:
                    continue
            except OSError:
                continue
            files.append(source.relative_to(project))
    return files


def project_test_files_hash(project_path):
    project = resolve_project_path(project_path)
    return _project_test_files_hash(project)


def _project_test_files_hash(project_path):
    project = Path(project_path).resolve(strict=True)
    digest = hashlib.sha256()
    test_files = [path for path in _eligible_project_files(project) if is_test_file(path)]
    for relative in sorted(test_files, key=lambda item: item.as_posix()):
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update((project / relative).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def project_test_command(project_path):
    project = Path(project_path).resolve(strict=True)
    has_tests = any(is_test_file(path) for path in _eligible_project_files(project))
    if has_tests and importlib.util.find_spec("pytest") is not None:
        return [sys.executable, "-m", "pytest", "-x", "-q"]
    return [sys.executable, "-m", "unittest", "discover"]


def project_command_label(command):
    return " ".join(["python"] + command[1:])


def _copy_project(source, destination):
    source = resolve_project_path(source)
    destination.mkdir(parents=True, exist_ok=True)
    for relative in _eligible_project_files(source):
        original = source / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)


def _safe_test_environment():
    env = {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
        if key in os.environ
    }
    env.pop("OPENAI_API_KEY", None)
    return env


def _run_project_copy(project_copy):
    try:
        command = project_test_command(project_copy)
        test_hash = _project_test_files_hash(project_copy)
        result = subprocess.run(
            command,
            cwd=project_copy,
            env=_safe_test_environment(),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
        if command[1:3] == ["-m", "pytest"]:
            passed_match = re.search(r"\b(\d+)\s+passed\b", output)
            tests_ran = re.search(r"\b\d+\s+(?:passed|failed|errors?|skipped|xfailed|xpassed)\b", output)
            tests_passed = bool(passed_match and int(passed_match.group(1)) > 0)
        else:
            count = re.search(r"Ran\s+(\d+)\s+tests?\b", output)
            tests_ran = count if count and int(count.group(1)) > 0 else None
            skipped = re.search(r"skipped=(\d+)", output)
            expected_failures = re.search(r"expected failures=(\d+)", output)
            tests_passed = bool(
                count
                and int(count.group(1))
                > (int(skipped.group(1)) if skipped else 0)
                + (int(expected_failures.group(1)) if expected_failures else 0)
            )
        if not tests_ran:
            return {
                "status": "not_run",
                "output": (output + "\nNo tests were discovered or executed.").strip(),
                "test_files_hash": test_hash,
            }
        if result.returncode == 0 and not tests_passed:
            return {
                "status": "not_run",
                "output": (output + "\nNo tests passed.").strip(),
                "test_files_hash": test_hash,
            }
        return {
            "status": "passed" if result.returncode == 0 else "failed",
            "output": output,
            "test_files_hash": test_hash,
        }
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + (exc.stderr or "")
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        return {
            "status": "failed",
            "output": (output + "\nTest run timed out after 30 seconds.").strip(),
            "test_files_hash": _project_test_files_hash(project_copy),
        }
    except (OSError, ValueError, ImportError) as exc:
        return {"status": "not_run", "output": str(exc), "test_files_hash": ""}


def run_project_tests(project_path):
    """Copy a project into a temporary folder and run its detected test command."""
    try:
        project = resolve_project_path(project_path)
        with tempfile.TemporaryDirectory(prefix="project-tests-") as temp_dir:
            project_copy = Path(temp_dir) / "project"
            _copy_project(project, project_copy)
            return _run_project_copy(project_copy)
    except (OSError, ValueError, TypeError) as exc:
        return {"status": "not_run", "output": str(exc), "test_files_hash": ""}


def _fixture_path(fixture_id):
    if not isinstance(fixture_id, str) or fixture_id not in FIXTURE_IDS:
        return None
    path = FIXTURES_DIR / fixture_id
    return path if path.is_dir() else None


def _fixture_test_file_hashes(fixture_dir):
    hashes = {}
    for path in sorted(fixture_dir.rglob("*.py")):
        relative = path.relative_to(fixture_dir)
        if is_test_file(relative):
            hashes[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def fixture_test_fingerprint(file_hashes):
    digest = hashlib.sha256()
    for filename, file_hash in sorted(file_hashes.items()):
        digest.update(filename.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def run_tests(fixture_id, code=None):
    """Run one allowlisted fixture in an isolated temporary directory."""
    source = _fixture_path(fixture_id)
    if source is None:
        return {
            "status": "not_run",
            "output": "Unknown fixture id.",
            "test_file_hashes_before": {},
            "test_file_hashes_after": {},
            "test_files_hash": "",
        }

    if isinstance(code, dict):
        if set(code) != {"buggy.py"} or not isinstance(code.get("buggy.py"), str):
            return {
                "status": "not_run",
                "output": "Fixture fixes may modify buggy.py only; test files are protected.",
                "test_file_hashes_before": _fixture_test_file_hashes(source),
                "test_file_hashes_after": _fixture_test_file_hashes(source),
                "test_files_hash": fixture_test_fingerprint(_fixture_test_file_hashes(source)),
            }
        code = code["buggy.py"]
    if code is not None and not isinstance(code, str):
        return {
            "status": "not_run",
            "output": "Fixed code must be a string for buggy.py.",
            "test_file_hashes_before": _fixture_test_file_hashes(source),
            "test_file_hashes_after": _fixture_test_file_hashes(source),
            "test_files_hash": fixture_test_fingerprint(_fixture_test_file_hashes(source)),
        }

    try:
        with tempfile.TemporaryDirectory(prefix="fixture-") as temp_dir:
            target = Path(temp_dir) / fixture_id
            shutil.copytree(source, target)
            test_hashes_before = _fixture_test_file_hashes(target)
            if code is not None:
                (target / "buggy.py").write_text(code, encoding="utf-8")

            env = {}
            for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"):
                if key in os.environ:
                    env[key] = os.environ[key]
            env.pop("OPENAI_API_KEY", None)
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "unittest"],
                    cwd=target,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                output = (exc.stdout or "") + (exc.stderr or "")
                if isinstance(output, bytes):
                    output = output.decode(errors="replace")
                test_hashes_after = _fixture_test_file_hashes(target)
                return {
                    "status": "failed",
                    "output": (output + "\nTest run timed out.").strip(),
                    "test_file_hashes_before": test_hashes_before,
                    "test_file_hashes_after": test_hashes_after,
                    "test_files_hash": fixture_test_fingerprint(test_hashes_after),
                }

            output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
            test_hashes_after = _fixture_test_file_hashes(target)
            return {
                "status": "passed" if result.returncode == 0 else "failed",
                "output": output,
                "test_file_hashes_before": test_hashes_before,
                "test_file_hashes_after": test_hashes_after,
                "test_files_hash": fixture_test_fingerprint(test_hashes_after),
            }
    except OSError as exc:
        hashes = _fixture_test_file_hashes(source)
        return {
            "status": "not_run",
            "output": str(exc),
            "test_file_hashes_before": hashes,
            "test_file_hashes_after": hashes,
            "test_files_hash": fixture_test_fingerprint(hashes),
        }


def verify(fixture_id, fixed_code):
    before = run_tests(fixture_id)
    after = run_tests(fixture_id, fixed_code)
    valid_fix_target = isinstance(fixed_code, str) or (
        isinstance(fixed_code, dict)
        and set(fixed_code) == {"buggy.py"}
        and isinstance(fixed_code.get("buggy.py"), str)
    )
    before_hashes = before.get("test_file_hashes_after", {})
    after_before_hashes = after.get("test_file_hashes_before", {})
    after_hashes = after.get("test_file_hashes_after", {})
    tests_unchanged = (
        before.get("test_file_hashes_before", {})
        == before_hashes
        == after_before_hashes
        == after_hashes
    )
    checks = [
        {
            "name": "buggy_fixture_fails",
            "status": "passed" if before["status"] == "failed" else (
                "not_run" if before["status"] == "not_run" else "failed"
            ),
        },
        {
            "name": "fixed_code_passes",
            "status": "passed" if after["status"] == "passed" else (
                "not_run" if after["status"] == "not_run" else "failed"
            ),
        },
        {
            "name": "tests_unchanged",
            "status": "passed" if tests_unchanged and after["status"] != "not_run" else (
                "not_run" if after["status"] == "not_run" else "failed"
            ),
        },
        {
            "name": "fix_applied_only_to_buggy_code",
            "status": "passed" if valid_fix_target else "failed",
        },
    ]
    return {
        "before": before,
        "after": after,
        "report": checks,
        "test_hashes": {"before": before_hashes, "after": after_hashes},
    }
