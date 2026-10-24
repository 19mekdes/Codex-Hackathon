# Backend

## Setup (Windows PowerShell)

```powershell
cd backend
py -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Create a `.env` file in the repository root (next to `backend/`) with the
environment values below. Settings load it with `python-dotenv`.

## Run the server

```powershell
cd backend
python manage.py runserver
```

## Endpoints

- `GET /api/health/` returns `{"ok": true, "ai_configured": false, "model": null}`.
- `GET /api/fixtures/` returns fixture objects with `id`, `title`, `code`, and the failing `error` output.
- `POST /api/verify/` accepts `{"fixture_id": "sum_off_by_one", "fixed_code": "..."}` and returns `before`, `after`, and `report`.
- `POST /api/diagnose/` accepts `{"code": "...", "error": "...", "fixture_id": "sum_off_by_one"}` (`fixture_id` optional) and returns `cause`, `explanation`, `fixed_code`, and `simulated`.
- `POST /api/fix/` accepts `{"fixture_id": "sum_off_by_one"}` and returns `diagnosis`, `before`, `after`, `report`, and `simulated`.
- `GET /api/recorded/` returns the last fully verified result with `recorded: true`.

## Environment variables

- `OPENAI_API_KEY`: OpenAI API key. Never returned by the API.
- `OPENAI_MODEL`: model name used for AI diagnosis.
- `DJANGO_SECRET_KEY`: optional Django secret; the development fallback is for local use only.
- `DJANGO_DEBUG`: optional; set to `true` to enable Django debug mode.

When `simulated` is `true`, the API used the fixture's checked-in `fixed.py`
because no key was configured or the AI request failed. With a working AI
request, `simulated` is `false`.
