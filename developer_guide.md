# Developer Guide

Engineering reference for setup, secrets, health checks, and local development. For a user-facing overview and how to run via Docker, see `README.md`.

## Environment Setup

- **Frontend:** requires Firebase web configuration (`frontend/.env`)
- **Backend:** uses same Firebase project (for token verification) and optional GCP key (`rag/secrets/service-account.json`)
- **RAG:** reads `.env` in `rag/` for GCS bucket info and paths

See `frontend/.env.example` and `rag/.env.example` for templates.

## Pre-commit Hooks

Install pre-commit hooks to automatically run linting and formatting before commits:

```bash
# Install pre-commit (if not already installed)
pip install pre-commit

# Install git hooks (one-time setup per developer)
pre-commit install
```

After installation, pre-commit will automatically run `ruff` (linting and formatting) on Python files before each commit. If errors are found, they will be auto-fixed when possible, or the commit will be blocked for manual fixes.

## Secrets

The following secrets are required for authenticated access to Google Cloud services.

### Service Account Key

**Path:**
`rag/secrets/service-account.json`

**Description:**
Google Cloud **Service Account** key with permissions for cloud storage and optional compute access.

**Required IAM Roles:**
- `Storage Admin` – for uploading and downloading embeddings and video assets to GCS
- `Service Account Token Creator` – for generating signed URLs (signBlob permission)
- `Viewer` or `Editor` – as required for project-level operations

**Container Mount Path:**
`/secrets/service-account.json`

### ⚠️ Security Notes

- These files **must never be committed** to version control.
- Add the service account path to `.gitignore`:


---
### Apply CORS to your GCS Artifacts bucket

Apply the following `cors.json` configuration to the artifacts bucket.

```json
[
  {
    "origin": ["*"],
    "method": ["GET", "HEAD", "OPTIONS"],
    "responseHeader": [
      "Content-Type",
      "Content-Length",
      "Range",
      "Accept-Ranges",
      "Content-Disposition",
      "Access-Control-Allow-Origin",
      "Content-Range"
    ],
    "maxAgeSeconds": 3600
  }
]
```

Next, run this command to apply the CORS configuration:

```
gsutil cors set cors.json gs://your-artifacts-bucket-name
```
---

## Health Checks

```bash
curl -s http://localhost:8000/health        # Backend
curl -s http://localhost:8001/health        # RAG service
curl -s http://localhost:8001/collection/info # RAG service, 333 document count
```

---

## Local Development (no containers)

If you prefer to run the app directly on your machine (for quick debugging or development without Docker):

```bash
# In project root
python3 -m venv venv
source venv/bin/activate
# Upgrade pip/build tools and install project deps from requirements.txt
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
```

#### 1. Backend (FastAPI)

# Run FastAPI backend
cd backend
uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8000
```

Then visit:
```
http://localhost:8000/health
```

#### 2. Frontend (Vite + React)

```bash
cd ../frontend
npm install
npm run dev
```

Then open:
```
http://localhost:8080
```

#### Notes

- This setup runs the backend and frontend only; the RAG microservice and ChromaDB are not available.
- Features that rely on semantic retrieval (for example, retries using RAG documentation) will gracefully fall back to standard generation.
- Ensure your `frontend/.env` Firebase project ID matches your backend service account for authentication to succeed.

## Linting & Tests (local)

Minimal commands to lint/fix with `ruff` and run tests locally:

```bash
# Run ruff to check (no changes):
ruff check backend/ tests/

# Auto-fix problems (formatting, some lint fixes):
ruff check backend/ tests/ --fix

# Alternatively run ruff format to reformat files in place:
ruff format backend/ tests/

# Run tests (repo root) - quick run:
python -m pytest -q

# Run tests with coverage:
python -m pytest --cov=backend --cov-report=term-missing -q

# Run only unit tests with coverage:
python -m pytest tests/unit --cov=backend --cov-report=term-missing -q
```

## License

This repository is currently unlicensed and private.

All rights reserved © 2025 Isabela Yepes, Manasvi Goyal, Nico Fidalgo.

Access is granted only to authorized course staff for evaluation purposes.
