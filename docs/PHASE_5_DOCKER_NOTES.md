# Phase 5 Docker cleanup for UpcurvEd

This version is updated after reviewing:

- `backend/Dockerfile.dev`
- `frontend/Dockerfile.dev`

## What this phase does

It narrows Docker to the parts that still match the repo:

- `backend`: FastAPI generation and render service
- `frontend`: Vite browser dev server

It removes the old assumptions about:

- RAG
- ChromaDB
- ETL jobs
- `rag/` folders
- RAG secrets mounts

## Included file

- `docker-compose.phase5.yaml`

## Why this compose file is different from the old one

### Removed

- `./rag/secrets/service-account.json` mount
- RAG profile wording
- stale comments about retrieval services
- old AC215 naming

### Kept

- backend dev image from `backend/Dockerfile.dev`
- frontend dev image from `frontend/Dockerfile.dev`
- `storage/` bind mount for generated artifacts
- `tests/` bind mount for backend-side testing inside the container
- profile-based startup

## What I changed after seeing the Dockerfiles

### Backend

I removed the explicit compose `command` override and let the image entrypoint stay in control.
That is safer because `backend/Dockerfile.dev` already defines:

- Python 3.12
- uv-managed environment
- Manim system dependencies
- TeX packages
- `/app/docker-entrypoint.sh`

So the compose file now assumes the backend container should boot the way the image author intended.

### Frontend

I also removed the compose `command` override.
That is because `frontend/Dockerfile.dev` already defines an entrypoint that runs:

```sh
npm ci && npm run dev -- --host 0.0.0.0 --port 8080
```

So compose should not duplicate that.

## Important notes

### 1. Backend image is intentionally heavy

Your backend dev image installs:

- ffmpeg
- sox
- cairo/pango/OpenGL deps
- a large TeX stack

That makes sense for Manim development, but it will build slowly. That is expected.

### 2. This Docker setup is for reproducible dev, not packaged desktop runtime

Electron desktop remains the primary product flow.
Docker here is best treated as an optional reproducible environment for:

- backend API development
- browser-based frontend development
- CI-style local validation

### 3. `APP_MODE`

This compose file leaves:

- `APP_MODE=${APP_MODE:-cloud}`
- `VITE_APP_MODE=${VITE_APP_MODE:-cloud}`

as defaults.

That keeps Docker aligned with browser/dev usage rather than desktop-local Electron usage. If you want Docker to simulate local desktop-style behavior, you can override those when starting compose.

## Recommended commands

Backend only:

```bash
docker compose -f docker-compose.phase5.yaml --profile backend up --build
```

Backend and frontend:

```bash
docker compose -f docker-compose.phase5.yaml --profile backend --profile frontend up --build
```

Stop:

```bash
docker compose -f docker-compose.phase5.yaml down
```

## Suggested next cleanup after Phase 5

1. Replace the repo root `docker-compose.yaml` with this version once verified.
2. Remove stale RAG wording from the root README and developer guide.
3. Search the repo for dead references to:
   - `rag/`
   - `chromadb`
   - `graph_wo_rag_retry`
4. Decide whether `frontend/Dockerfile.dev` and `backend/Dockerfile.dev` should be the only maintained Dockerfiles.
