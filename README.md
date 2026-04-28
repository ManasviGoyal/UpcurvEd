# UpcurvEd

UpcurvEd is a desktop-first application for generating educational media from natural-language prompts. The current product centers on an Electron app that runs a local FastAPI backend and a React/Vite frontend, then uses Manim-based generation and rendering to produce outputs such as short explainer videos, podcasts, quizzes, and interactive widgets.

## Current Product Model

UpcurvEd is now maintained as a **desktop-first** project.

- **Primary distribution path:** packaged Electron installers
- **Primary development workflow:** run Electron locally and let it start the backend/UI services it needs
- **Browser/frontend-only development:** still useful for UI work, but secondary

This repository is maintained as a desktop-first application. Documentation should reflect the desktop-local workflow as the source of truth.

## Current Architecture

At a high level, the app works like this:

1. The Electron runtime in `desktop/` starts the local backend and loads the frontend UI.
2. The React/Vite frontend in `frontend/` sends generation requests to the backend.
3. The FastAPI backend in `backend/` turns prompts into Manim code, renders media, and returns artifacts.
4. Generated media is stored locally for desktop use and served back to the UI.

### Generation Path

The current generation flow is centered on the backend graph in `backend/agent/graph.py`:

- draft code
- render with Manim
- log failure if rendering fails
- retry or end

Rendering is handled by `backend/runner/job_runner.py`, which writes job artifacts under storage, runs Manim, captures logs, and returns a uniform job result.

## Repository Structure

```text
UpcurvEd/
├── backend/               # FastAPI backend, generation graph, runner, MCP logic
├── frontend/              # React/Vite UI used by desktop and browser-based dev
├── desktop/               # Electron runtime, preload bridge, bundled Python tooling
├── docs/                  # Project architecture and developer docs
├── img/                   # Images and diagrams
├── pdf/                   # Reports and course/project PDFs
├── storage/               # Local render artifacts for non-packaged/dev workflows
├── tests/                 # Automated tests
├── package.json           # Root desktop/electron scripts
├── electron-builder.yml   # Electron packaging config
├── README.md              # Project overview
└── developer_guide.md     # Engineering setup and maintenance notes
```

## Supported Workflows

### 1. Desktop development (official workflow)

This is the main development path and the best way to work on the product end to end.

Prerequisites:

- Node.js 20+
- Python 3.12 recommended

Install dependencies from the repo root:

```bash
npm install
npm --prefix frontend install
npm run desktop:dev:setup
```

Then start the desktop app:

```bash
npm run desktop:dev
```

This starts:

- a local FastAPI backend, usually at `127.0.0.1:8000`
- a local Vite dev server, usually at `127.0.0.1:8080`
- an Electron window as the application shell

### 2. Frontend-only UI development

You can still run the frontend directly in a browser for UI work:

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 8080
```

### 3. Backend-only development

You can run the backend directly without Electron when debugging backend behavior:

```bash
python -m uvicorn backend.api.main:app --reload --host 127.0.0.1 --port 8000
```

## Build Desktop Installers

Packaged desktop builds bundle the frontend, backend, and bundled Python runtime.

Build the frontend for desktop mode:

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

Artifacts are written to `release/`.

### Build note

Installer bundling depends on the desktop Python runtime preparation flow in `desktop/scripts/prepare-python-runtime.cjs`, which requires **Python 3.12**.

## Desktop Runtime Notes

In desktop-local mode:

- authentication can run in a local-first mode
- generated media is stored on disk
- chat/message state is stored locally on disk
- API keys are stored through Electron secure storage when available, with a local fallback when unavailable

The Electron runtime is implemented primarily in:

- `desktop/main.cjs`
- `desktop/preload.cjs`

## Storage and Artifacts

The backend runner writes generation artifacts under a storage directory. In local development this defaults to `storage/`, and in packaged desktop builds it is redirected to the app's user-data area.

The backend serves local files through `/static`.

## Health Check

The backend health endpoint is:

```bash
curl -s http://127.0.0.1:8000/health
```

## Documentation Map

- `README.md` — high-level overview and the current supported workflow
- `developer_guide.md` — engineering setup, runtime notes, testing, and maintenance details
- `desktop/README.md` — Electron-specific runtime and packaging notes
- `ARCHITECTURE.md` — current architecture and ownership boundaries

## License

MIT. See `LICENSE`.
