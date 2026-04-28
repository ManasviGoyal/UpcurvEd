# Developer Guide

Engineering reference for UpcurvEd's current desktop-first architecture.

This guide reflects the **current** supported workflow:

- Electron desktop app as the primary product
- local FastAPI backend for generation and rendering
- React/Vite frontend for the UI
- no RAG layer in the active architecture

## Source of Truth

When project files disagree, use this priority order:

1. `desktop/README.md` and `desktop/main.cjs` for desktop runtime behavior
2. `backend/api/main.py` and `backend/agent/graph.py` for generation flow
3. `backend/runner/job_runner.py` for render execution and artifact handling
4. this guide and the root `README.md` for project-level conventions

Older docs from earlier iterations should be treated as legacy and not as the current source of truth.

## Current Architecture Summary

### Runtime layers

- `desktop/` runs Electron and bridges secure/local desktop capabilities into the UI
- `frontend/` contains the React/Vite application
- `backend/` contains the FastAPI API, generation logic, render runner, and supporting services

### Current generation path

The main prompt-to-video flow is:

1. frontend sends a request to `/generate`
2. `backend/api/main.py` calls the backend generation path
3. `backend/agent/graph.py` handles draft → render → failure logging / retry
4. `backend/runner/job_runner.py` runs Manim, captures logs, writes artifacts, and returns a stable result shape

### Removed architecture pieces

The current architecture does **not** include:

- RAG retrieval
- ChromaDB
- a separate rag-service
- a `rag/` directory

Any remaining references to those systems are stale and should be cleaned as part of ongoing maintenance.

## Prerequisites

Recommended local environment:

- Node.js 20+
- Python 3.12
- npm

Python 3.12 is especially important for installer builds, because bundled desktop runtime preparation depends on it.

## Local Setup

From the repo root:

```bash
npm install
npm --prefix frontend install
npm run desktop:dev:setup
```

`desktop:dev:setup` installs the Python packages listed in `desktop/requirements-desktop.txt`, which is the dependency set currently used by the desktop workflow.

## Primary Development Workflow: Desktop

Run the application in desktop development mode:

```bash
npm run desktop:dev
```

Expected behavior:

- Electron launches the app shell
- the backend starts locally
- the frontend starts locally in Vite dev mode
- the UI talks to the backend over localhost

### Useful desktop environment variables

- `DESKTOP_BACKEND_RELOAD=1` — enable backend reload/watch mode
- `DESKTOP_REUSE_EXISTING_SERVERS=0` — fail instead of reusing already-running local services
- `DESKTOP_API_PORT=<port>` — override the default backend port
- `PYTHON_BIN=<path>` — force a specific Python interpreter

## Backend-Only Development

To work only on the backend API:

```bash
python -m uvicorn backend.api.main:app --reload --host 127.0.0.1 --port 8000
```

Health check:

```bash
curl -s http://127.0.0.1:8000/health
```

The backend mounts local static files at `/static`.

## Frontend-Only Development

To work only on the frontend:

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 8080
```

When running outside Electron, make sure the frontend is pointed at a running backend.

## Installer Builds

Build the desktop frontend bundle:

```bash
npm run desktop:build:frontend
```

Build installers:

```bash
npm run desktop:dist:win
npm run desktop:dist:mac:x64
npm run desktop:dist:mac:arm64
npm run desktop:dist:linux
```

The packaging configuration lives in `electron-builder.yml`.

### Bundled Python runtime

Installer builds use `desktop/scripts/prepare-python-runtime.cjs` to construct a bundled runtime.

That flow:

- copies a Python 3.12 runtime
- installs desktop Python dependencies
- bundles Playwright Chromium
- bundles ffmpeg

This is the main reason release builds should be done with Python 3.12.

## Runtime Modes

### Desktop-local mode

Desktop-local mode is the main local runtime path.

In this mode:

- the frontend behaves as a local desktop app
- the backend can run in local-first mode for desktop usage
- chat/message state is stored in a local JSON-backed desktop store
- generated media is stored locally

UpcurvEd’s supported runtime is **desktop-local**. Documentation and maintenance should optimize for the local Electron + FastAPI + Vite stack.

## State, Storage, and Artifacts

### Local state

Desktop-local chat state is persisted to a JSON file under the desktop state directory.

Relevant environment variables and defaults:

- `UPCURVED_DESKTOP_STATE_DIR` — desktop state directory
- `UPCURVED_STORAGE_DIR` — artifact storage directory

In packaged desktop builds, Electron redirects these to the app user-data area.

### Render artifacts

`backend/runner/job_runner.py` writes artifacts under:

- `storage/jobs/<job_id>/...` in local/dev workflows
- the desktop user-data storage area in packaged desktop workflows

Artifacts typically include:

- `scene.py`
- render logs
- `video.mp4`
- optional subtitle files such as `video.vtt`

## Auth and API Keys

### Desktop auth behavior

In desktop-local mode, the backend can use `X-Desktop-User` and local-user defaults.

### API key storage

The Electron runtime uses `keytar` when available for secure key storage. If `keytar` is unavailable, the app falls back to local settings storage.

When changing this behavior, preserve the current hierarchy:

1. secure desktop storage when available
2. explicit local fallback when secure storage is unavailable

## Canonical Files to Check First

When debugging the current architecture, start here:

### Desktop

- `desktop/main.cjs`
- `desktop/preload.cjs`
- `desktop/README.md`

### Backend

- `backend/api/main.py`
- `backend/agent/graph.py`
- `backend/runner/job_runner.py`
- `backend/config.py`

### Frontend

- `frontend/src/App.tsx`
- `frontend/src/main.tsx`
- `frontend/package.json`

## Testing and Linting

Common local commands:

```bash
ruff check backend/ tests/
ruff format backend/ tests/
python -m pytest -q
python -m pytest --cov=backend --cov-report=term-missing -q
```

If you rely on these tools in CI or pre-commit, make sure they are installed in your current Python environment.

## Maintenance Rules

When updating the repo, prefer these rules:

1. keep the current folder structure unless there is a clear payoff to moving code
2. keep one canonical generation path
3. document desktop-first behavior before any secondary paths
4. remove stale RAG references instead of explaining them away
5. keep the desktop-first workflow as the source of truth

## Known Documentation Debt

Still worth cleaning after this doc update:

- stale backend metadata and dependency descriptions
- any leftover references to `graph_wo_rag_retry`, retrieval, Chroma, or `rag/`
