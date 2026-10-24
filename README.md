# FixProof AI

**From Error to Evidence.** FixProof explains Python errors, suggests a code change, and distinguishes an AI suggestion from a fix that tests have actually verified.

> AI can suggest a fix. Only a test run can prove it.

## What it does

- Analyze submitted Python code and an error message with the OpenAI API.
- Explain the likely cause and show proposed code, changes, and suggested tests.
- Run the included buggy fixtures before and after a proposed fix.
- Scan and repair eligible local projects in a temporary copy, then apply a fully verified repair only after explicit confirmation.
- Import a local `.py` file into the frontend editor. The file contents are sent to the backend only when **Analyze Error** is submitted.

### Verification is explicit

The general code analyzer does **not** execute arbitrary user code. Its verification result is `not_run`. The built-in fixture flow runs actual tests and can show `passed` only when they pass. With no API key, fixture diagnosis can use its checked-in `fixed.py`; it is labeled **Simulated diagnosis**, while the fixture tests still run for real.

## Technology

- Frontend: React with plain JavaScript and Vite.
- Backend: Django JSON views and the official OpenAI Python SDK.
- Configuration: environment variables loaded from the repository-root `.env` by `python-dotenv`.
- No Django REST Framework or application database is used. Django’s default SQLite setting is unused by the API.

## Run locally on Windows

### 1. Configure the backend

From the repository root, create a `.env` file beside this README. Use your own values; never commit this file.

```dotenv
DJANGO_SECRET_KEY=replace-with-a-long-random-value
DJANGO_DEBUG=true
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=your-supported-model-name
ALLOWED_PROJECT_ROOT=C:\Users\YourName\Projects
```

`OPENAI_API_KEY` and `OPENAI_MODEL` are required for general code analysis. The health and built-in fixture endpoints can still be used without a key. `ALLOWED_PROJECT_ROOT` is required for project scan/fix/apply endpoints; choose a directory containing projects you intend to work on.

Open PowerShell in the repository root and run:

```powershell
cd backend
py -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py test
python manage.py runserver
```

No migrations are needed for this API.

### 2. Start the frontend

Open a second PowerShell window in the repository root:

```powershell
cd frontend
npm install
npm run dev
```

Open the Vite URL printed in the terminal, normally <http://localhost:5173>. During local development, Vite proxies `/api` requests to `http://127.0.0.1:8000`.

The API base can be set at frontend build time with `VITE_API_BASE_URL`, for example:

```powershell
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
npm run build
```

Never put an OpenAI key in a `VITE_` variable; frontend variables are included in browser code.

## Demo flow

1. Click **Load Example**, then **Analyze Error** to see a diagnosis, suggested fix, changes, and suggested tests. This requires a working backend API key/model.
2. Scroll to **Prove a built-in fixture**, choose an example, and click **Fix & Prove**. The fixture test output shows the actual before and after runs. This mode can use the fixture’s simulated diagnosis when no usable AI key is configured.
3. For imported code, select a `.py` file or paste code directly. Imported files are local until you submit an analysis.

## API

All routes return JSON. The local frontend is allowed from `http://localhost:5173` and `http://127.0.0.1:5173`.

| Method and route | Request | Result |
| --- | --- | --- |
| `GET /api/health/` | — | `{ "ok": true, "ai_configured": true, "model": "…" }`. Never returns the key. |
| `POST /api/analyze/` | `{ "language": "python", "code": "…", "error_message": "…" }` | `{ success, language, root_cause, explanation, fixed_code, changes, suggested_tests, verification }`. Verification is `not_run`; submitted code is not executed. |
| `GET /api/fixtures/` | — | Array of `{ id, title, code, error }` fixture objects. `error` is real failing test output. |
| `POST /api/diagnose/` | `{ "code": "…", "error": "…", "fixture_id": "sum_off_by_one" }` (`fixture_id` optional) | `{ cause, explanation, fixed_code, simulated }`. Without a key, a valid fixture ID is needed for simulated diagnosis. |
| `POST /api/verify/` | `{ "fixture_id": "sum_off_by_one", "fixed_code": "…" }` | `before`, `after`, and verification report. Only fixture IDs are accepted. |
| `POST /api/fix/` | `{ "fixture_id": "sum_off_by_one" }` | Runs fixture tests before/after diagnosis and returns `{ diagnosis, before, after, report, simulated }`. |
| `GET /api/recorded/` | — | Last fully verified fixture result with `recorded: true`, if one is available. |
| `POST /api/project/scan` | `{ "path": "C:\\Users\\YourName\\Projects\\demo" }` | Detected test command, project file list, and `before` result. |
| `POST /api/project/fix` | `{ "path": "C:\\Users\\YourName\\Projects\\demo" }` | Diagnosis, before/after results, report, diffs, and a temporary `run_id`. |
| `POST /api/project/apply` | `{ "path": "…", "run_id": "…", "confirmed": true }` | Applies only the last fully verified repair after confirmation and creates `.fixproof.bak` backups. |

Project endpoints accept only folders inside `ALLOWED_PROJECT_ROOT`. They test a temporary copy, skip common dependency/secret directories and files, and do not permit edits to test files. Project fixes are not written to the real project until the apply request includes `confirmed: true`.

## Checks

From `backend/`:

```powershell
python manage.py test
```

From `frontend/`:

```powershell
npm run build
```

## Deployment notes

This repository is configured for local development. Before deploying, configure Django `ALLOWED_HOSTS` and CORS for the actual frontend origin, set `DJANGO_DEBUG=false` and a strong `DJANGO_SECRET_KEY`, provide `OPENAI_API_KEY` and `OPENAI_MODEL` only on the backend, and set the frontend’s `VITE_API_BASE_URL` to the deployed API origin. The current CORS middleware allows only the two local Vite origins; production needs an explicit production-origin configuration. Do not deploy with the development secret fallback.

## About

Built for Codex Community DevHack Day — Bahir Dar Institute of Technology, Ethiopia.
