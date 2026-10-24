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

### Deploy the frontend to Vercel and the API to Render

The repository includes `frontend/vercel.json` for the Vite build and `render.yaml` for the Django service. Push the branch you want to deploy to GitHub first, then:

1. In Vercel, choose **Add New → Project**, import this GitHub repository, and set **Root Directory** to `frontend`. Use the Vite preset, build command `npm run build`, and output directory `dist`. Deploy once to receive your public Vercel URL. The first deployment can finish before the API exists.
2. In Render, choose **New → Blueprint**, connect the same repository, and apply the `render.yaml` blueprint. It builds from `backend` and starts Django with Gunicorn. When prompted for the Blueprint's unsynced values, enter your OpenAI key and model if you want live diagnosis, and set `CORS_ALLOWED_ORIGINS` to the exact Vercel origin, such as `https://your-project.vercel.app` (no trailing slash). Render generates `DJANGO_SECRET_KEY`; `DJANGO_DEBUG` is false.
3. When Render finishes, copy the service's `https://...onrender.com` origin. In Vercel **Settings → Environment Variables**, set `VITE_API_BASE_URL` to that origin (no trailing slash) for Production. Redeploy the frontend so the API URL is included in its build.
4. Open `https://<your-render-service>.onrender.com/api/health/`. Confirm it returns `ok: true` and the expected `ai_configured` value. Then open the Vercel URL and try **Fix & Prove** with a built-in fixture.

For later changes, push to the connected branch; both hosts can deploy from GitHub. If you change the Vercel domain, update Render's `CORS_ALLOWED_ORIGINS` to that exact origin and redeploy the backend. Add any Vercel preview origin separately if you need preview deployments; do not use a wildcard.

`OPENAI_API_KEY` and `OPENAI_MODEL` belong only in Render's environment settings. `VITE_API_BASE_URL` is public frontend configuration, not a secret. Never put the OpenAI key in a `VITE_` variable or commit a `.env` file. Django reads `ALLOWED_HOSTS` from its environment and includes Render's `RENDER_EXTERNAL_HOSTNAME`; local defaults remain available for development.

The hosted project scan/fix endpoints operate on paths inside the Render service's filesystem, not folders on your computer. Use the built-in fixtures for the hosted demo. Render's local filesystem and the in-memory project run registry are not durable across restarts or deploys; `recorded_demo.json` may be reset, and project apply is intended for a single live service instance. This app has no database, so don't treat these as persistent storage.

## About

Built for Codex Community DevHack Day — Bahir Dar Institute of Technology, Ethiopia.
