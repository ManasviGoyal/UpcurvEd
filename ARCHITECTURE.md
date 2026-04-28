# UpcurvEd Architecture

This document defines the current architecture of UpcurvEd after the removal of the old RAG-based stack.

## Architecture Decision

UpcurvEd is a **desktop-first Electron application**.

The current maintained architecture is:

- Electron runtime in `desktop/`
- React/Vite frontend in `frontend/`
- FastAPI backend in `backend/`
- Manim-based render pipeline for video generation

This is the architecture that project docs and future cleanup work should optimize for.

## Design Goals

- keep the existing repository layout with minimal disruption
- remove outdated assumptions from the prior web-first / RAG version
- maintain a single understandable generation path
- preserve a smooth desktop development and packaging workflow

## System Overview

### Desktop runtime

The Electron runtime lives in `desktop/`.

Its responsibilities include:

- starting the backend for local desktop use
- starting the frontend dev server in development mode
- loading the built frontend in packaged mode
- bridging desktop-only features into the renderer through the preload layer
- managing desktop-local storage and secure key access

Canonical files:

- `desktop/main.cjs`
- `desktop/preload.cjs`
- `desktop/scripts/prepare-python-runtime.cjs`

### Frontend

The frontend lives in `frontend/` and is built with React and Vite.

Its responsibilities include:

- rendering the user interface
- sending generation/edit/media requests to the backend
- adapting behavior between desktop-local mode and non-desktop/browser mode
- handling client-side routing, settings, and local UI state

Canonical files:

- `frontend/src/App.tsx`
- `frontend/src/main.tsx`

### Backend

The backend lives in `backend/` and is implemented as a FastAPI app.

Its responsibilities include:

- handling generation and editing endpoints
- managing the prompt-to-code flow
- invoking rendering jobs
- serving local artifacts
- supporting desktop-local persistence

Canonical file:

- `backend/api/main.py`

## Current Generation Pipeline

The current pipeline is centered on `backend/agent/graph.py`.

### Logical flow

1. receive user prompt
2. draft Manim code
3. render with Manim
4. if render fails, log failure context
5. retry until the configured limit or end

This is the active canonical generation graph.

### Render execution

`backend/runner/job_runner.py` is the shared render runner.

Its responsibilities include:

- creating a job directory
- writing `scene.py`
- running linting as best effort
- running Manim render commands
- capturing stdout/stderr and metadata
- copying the final output to a stable path
- returning a consistent result shape to callers

## Storage Model

### Desktop-local storage

For desktop-local workflows:

- desktop state is stored locally on disk
- job artifacts are stored locally on disk
- artifacts are served through local backend routes

## Modes of Operation

### 1. Desktop-local mode

This is the main supported runtime.

Characteristics:

- Electron starts local services
- backend and frontend communicate over localhost
- desktop-local user state is persisted locally
- local-first auth behavior is allowed

### 2. Browser/frontend development mode

This is a secondary development mode for UI work.

Characteristics:

- frontend runs directly in the browser
- backend may still be run locally as a separate process
- useful for UI iteration without launching the full desktop shell

## Ownership Boundaries

### `desktop/`
Owns:

- app startup
- process spawning and lifecycle
- packaged runtime preparation
- desktop-specific storage and secure bridge behavior

### `frontend/`
Owns:

- UI and routing
- user interactions
- presentation logic
- desktop-local vs browser-mode client behavior

### `backend/`
Owns:

- API endpoints
- prompt-to-code pipeline
- render execution
- artifact lifecycle
- persistence and artifact storage integrations for the desktop-local runtime

## Cleanup Guidance

When cleaning the repo, prefer these principles:

1. keep the current directory layout unless a move clearly improves clarity
2. use one canonical generation path
3. prioritize desktop-first truth in docs and code comments
4. delete stale RAG references rather than keeping explanatory dead weight
5. only treat Docker as official once its files reflect the current architecture

## Current Documentation Set

- `README.md` — project-level overview
- `developer_guide.md` — engineering setup and maintenance guidance
- `desktop/README.md` — Electron runtime notes
- `docs/ARCHITECTURE.md` — this architecture definition
