import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
FIXTURE_IDS = ("sum_off_by_one", "none_check")


def _fixture_path(fixture_id):
    if not isinstance(fixture_id, str) or fixture_id not in FIXTURE_IDS:
        return None
    path = FIXTURES_DIR / fixture_id
    return path if path.is_dir() else None


def run_tests(fixture_id, code=None):
    """Run one allowlisted fixture in an isolated temporary directory."""
    source = _fixture_path(fixture_id)
    if source is None:
        return {"status": "not_run", "output": "Unknown fixture id."}

    try:
        with tempfile.TemporaryDirectory(prefix="fixture-") as temp_dir:
            target = Path(temp_dir) / fixture_id
            shutil.copytree(source, target)
            if code is not None:
                if not isinstance(code, str):
                    return {"status": "not_run", "output": "Code must be a string."}
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
                return {"status": "failed", "output": (output + "\nTest run timed out.").strip()}

            output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
            return {
                "status": "passed" if result.returncode == 0 else "failed",
                "output": output,
            }
    except OSError as exc:
        return {"status": "not_run", "output": str(exc)}


def verify(fixture_id, fixed_code):
    before = run_tests(fixture_id)
    after = run_tests(fixture_id, fixed_code)
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
    ]
    return {"before": before, "after": after, "report": checks}
