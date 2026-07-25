# Developer Guide

Engineering reference for UpcurvEd's current desktop-first architecture.

The supported product path is:

- Electron desktop application
- local FastAPI backend for generation, rendering, persistence, and artifacts
- React/Vite frontend for the UI
- no active RAG or LangGraph generation layer

## Source of Truth

When documentation and implementation disagree, check the implementation that owns the behavior:

1. `desktop/main.cjs`, `desktop/preload.cjs`, and `desktop/README.md` for desktop startup, secure storage, local ports, and packaging behavior
2. `backend/api/main.py` for API routing and desktop-local persistence
3. feature pipeline modules for generation behavior:
   - `backend/agent/structured_video.py`
   - `backend/mcp/podcast_logic.py`
   - `backend/mcp/quiz_logic.py`
   - `backend/mcp/story_video_logic.py`
   - `backend/mcp/widget_logic.py`
4. `backend/runner/job_runner.py` for Manim execution and render-job artifacts
5. `backend/agent/llm/provider_config.py` and `backend/agent/llm/clients.py` for provider, model, key, and LLM request behavior
6. `ARCHITECTURE.md` for ownership boundaries and this guide for development conventions

The root `README.md` is a high-level overview and documentation map, not a workflow source. References to the old `backend/agent/graph.py`, LangGraph nodes, RAG retrieval, ChromaDB, a `rag-service`, or a `rag/` directory are legacy unless current runtime code still imports them.

## Prerequisites

Recommended local environment:

- Node.js 20+
- Python 3.12
- npm

Python 3.12 is required by the current desktop runtime preparation and installer workflow.

## Local Setup

From the repository root:

```bash
npm install
npm --prefix frontend install
npm run desktop:dev:setup
```

`desktop:dev:setup` installs the Python dependencies used by the desktop workflow.

## Primary Development Workflow

Run the complete desktop application:

```bash
npm run desktop:dev
```

In development, Electron starts or reuses:

- the FastAPI backend, normally at `127.0.0.1:8000`
- the Vite frontend, normally at `127.0.0.1:8080`
- the Electron application window

Useful environment variables:

- `DESKTOP_BACKEND_RELOAD=1` — enable backend reload mode
- `DESKTOP_REUSE_EXISTING_SERVERS=0` — fail instead of reusing healthy local backend or frontend services
- `DESKTOP_API_PORT=<port>` — change the starting backend port
- `PYTHON_BIN=<path>` — use a specific Python interpreter

## Backend-Only Development

Run the API without Electron:

```bash
python -m uvicorn backend.api.main:app --reload --host 127.0.0.1 --port 8000
```

Health check:

```bash
curl -s http://127.0.0.1:8000/health
```

The backend serves local artifacts through `/static` when no cloud bucket is configured.

## Frontend-Only Development

Run the frontend in a browser:

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 8080
```

A backend must also be running, and the frontend API base URL must point to it.

## Installer Builds

Build the desktop frontend:

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

Artifacts are written to `release/`. Packaging is configured in `electron-builder.yml`. The bundled Python runtime is prepared by `desktop/scripts/prepare-python-runtime.cjs`; use Python 3.12 for this flow.

## Runtime, State, and Artifacts

Desktop-local mode is the supported application runtime.

Electron starts the backend with `APP_MODE=desktop-local` and redirects local paths into the application user-data directory:

- `UPCURVED_STORAGE_DIR` — generated artifacts and job data
- `UPCURVED_DESKTOP_STATE_DIR` — chat and message state
- `PLAYWRIGHT_BROWSERS_PATH` — bundled browser files used by story rendering

When the backend is run directly, artifact storage defaults to `storage/` and desktop state defaults to `.desktop-state/` unless the environment variables are set.

Render jobs are written under:

```text
<UPCURVED_STORAGE_DIR>/jobs/<job_id>/
```

Final structured-video artifacts normally include:

- `video.mp4`
- `video.vtt`
- `scene_bundle.txt`

Intermediate scene jobs and verbose diagnostics are cleaned according to the structured-video retention policy. The privacy-safe long-term generation record is stored at:

```text
<UPCURVED_STORAGE_DIR>/generation_audit.jsonl
```

## API Keys

The Electron runtime uses `keytar` for secure operating-system key storage when available. When secure storage is unavailable, the frontend uses the explicit local settings fallback.

Preserve this order when changing key handling:

1. secure desktop storage when available
2. local fallback when secure storage is unavailable

Provider and model behavior is centralized in:

- `backend/agent/llm/provider_config.py`
- `backend/agent/llm/clients.py`
- `frontend/src/lib/providerConfig.ts`
- `frontend/src/lib/secureKeys.ts`

## Testing and Linting

Common backend checks:

```bash
ruff check backend/ tests/
ruff format --check backend/ tests/
python -m pytest
python -m pytest --cov=backend --cov-report=term-missing
```

For changed frontend files, run the relevant TypeScript/Vite checks from `frontend/`. For Electron changes, run a Node syntax check and test both development and packaged paths when possible.

## Maintenance Rules

1. keep the desktop Electron + FastAPI + React/Vite path as the supported architecture
2. route each artifact type directly to its current feature pipeline rather than restoring the old graph layer
3. keep provider selection centralized
4. keep `README.md` high level and place operational instructions in this guide or `desktop/README.md`
5. update `docs/ARCHITECTURE.md` when ownership boundaries or generation pipelines change
6. remove stale RAG, ChromaDB, LangGraph, and old graph-pipeline references rather than documenting them as current behavior

## Known Documentation Debt

Remaining cleanup should include stale dependency metadata or comments that still mention LangGraph, retrieval, ChromaDB, `graph_wo_rag_retry`, or the former `backend/agent/graph.py` generation path.
