import json
import os
from pathlib import Path

from dotenv import load_dotenv

from .verify import FIXTURE_IDS


load_dotenv()


def _simulated_result(fixture_id, ai_error):
    if not isinstance(fixture_id, str) or fixture_id not in FIXTURE_IDS:
        return None
    fixed_path = Path(__file__).resolve().parent / "fixtures" / fixture_id / "fixed.py"
    if not fixed_path.is_file():
        return None
    result = {
        "cause": "The fixture contains a known bug that causes its test to fail.",
        "explanation": "This simulated diagnosis uses the fix included with the fixture.",
        "fixed_code": fixed_path.read_text(encoding="utf-8"),
        "simulated": True,
    }
    if ai_error:
        result["ai_error"] = ai_error
    return result


def diagnose(code, error, fixture_id=None):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        fallback = _simulated_result(fixture_id, None)
        if fallback is not None:
            return fallback
        raise ValueError("OPENAI_API_KEY is required unless a valid fixture_id is provided.")

    try:
        model = os.getenv("OPENAI_MODEL")
        if not model:
            raise ValueError("OPENAI_MODEL is not configured.")

        from openai import OpenAI

        client = OpenAI(api_key=api_key, timeout=30.0)
        response = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Diagnose the code error. Return JSON only with string fields: "
                        "cause, explanation, fixed_code."
                    ),
                },
                {"role": "user", "content": f"Code:\n{code}\n\nError:\n{error}"},
            ],
        )
        result = json.loads(response.choices[0].message.content)
        required = ("cause", "explanation", "fixed_code")
        if not isinstance(result, dict) or any(
            not isinstance(result.get(field), str) for field in required
        ):
            raise ValueError("OpenAI returned invalid JSON fields.")

        fixed_code = result["fixed_code"].strip()
        if fixed_code.startswith("```") and fixed_code.endswith("```"):
            fenced_lines = fixed_code.splitlines()
            fixed_code = "\n".join(fenced_lines[1:-1]).strip()
        return {
            "cause": result["cause"],
            "explanation": result["explanation"],
            "fixed_code": fixed_code,
            "simulated": False,
        }
    except Exception:
        # SDK exception text may contain request metadata; do not expose it.
        error_message = "AI diagnosis failed (network, timeout, or invalid response)."
        fallback = _simulated_result(fixture_id, error_message)
        if fallback is not None:
            return fallback
        raise ValueError(error_message) from None
