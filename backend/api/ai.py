import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from .verify import FIXTURE_IDS

load_dotenv()


def diagnose(code, error, fixture_id=None):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        if fixture_id is None:
            raise ValueError(
                "OPENAI_API_KEY is required unless a valid fixture_id is provided."
            )
        if not isinstance(fixture_id, str) or fixture_id not in FIXTURE_IDS:
            raise ValueError("Unknown fixture id.")
        fixed_path = Path(__file__).resolve().parent / "fixtures" / fixture_id / "fixed.py"
        if not fixed_path.is_file():
            raise ValueError("The selected fixture does not have a fixed.py file.")
        return {
            "cause": "The fixture contains a known bug that causes its test to fail.",
            "explanation": "This simulated diagnosis uses the verified fix included with the fixture.",
            "fixed_code": fixed_path.read_text(encoding="utf-8"),
            "simulated": True,
        }

    model = os.getenv("OPENAI_MODEL")
    if not model:
        raise ValueError("OPENAI_MODEL must be set when OPENAI_API_KEY is configured.")

    client = OpenAI(api_key=api_key)
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

    try:
        content = response.choices[0].message.content
        result = json.loads(content)
    except (IndexError, AttributeError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("OpenAI returned an invalid diagnosis; expected a JSON object.") from exc

    required = ("cause", "explanation", "fixed_code")
    if not isinstance(result, dict) or any(
        not isinstance(result.get(field), str) for field in required
    ):
        raise ValueError(
            "OpenAI returned an invalid diagnosis; expected string fields: "
            "cause, explanation, fixed_code."
        )
    return {**{field: result[field] for field in required}, "simulated": False}
