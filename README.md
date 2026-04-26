# UpcurvEd

This project builds an AI-powered desktop-first application that generates educational content, including short educational videos, podcasts, and quizzes, from natural language prompts using **LangGraph**, **MCP** and a **Retrieval-Augmented Generation (RAG)** backend.

---

## Overview

Users enter a text prompt or upload a file describing a concept (e.g., "show a circle expanding" or "explain reinforcement learning").  
The backend generates Manim Python code, renders the animation, uses RAG manim documentation on retries, adds voiceover, and returns a playable video.

---

## Repository Structure

```
UpcurvEd/
├── backend/               # FastAPI app (main API, RAG client, agent logic)
├── frontend/              # React (Vite) UI
├── desktop/               # Electron desktop runtime
├── rag/                   # RAG ETL pipeline + Docker setup
├── img/                   # Architecture diagrams, screenshots
├── pdf/                   # Proposal & reports
├── storage/               # Local output videos (bind-mounted volume)
├── docker-compose.yaml    # Unified compose (frontend, backend, rag, chroma)
└── README.md              # Project overview
```

---

## Current Product Model

- **Desktop is the primary distribution path**: users download installer artifacts (`.exe` / `.dmg`) and run locally.
- **No Kubernetes deployment in this repository**.
- **Web usage is optional** and intended for the landing page and lightweight browser access.

For desktop users, there are no build/setup steps after install. The app starts local services automatically.

---

## Containers and Profiles

| Service | Port | Description |
|----------|------|-------------|
| **frontend** | 8080 | React/Vite development server |
| **backend** | 8000 | FastAPI API for generation, rendering, and Firebase auth |
| **rag-service** | 8001 | FastAPI microservice for vector retrieval from ChromaDB |
| **chroma** | 8000 internal | Vector database (embeddings store) |
| **llm-rag-job** | — | One-shot ETL: fetch, preprocess, embed, upload/download to GCS |

![System Architecture](img/11-15-25_sys_arch.png)

Profiles group services for flexible startup:

```bash
# Run backend + rag stack
docker compose --profile backend --profile rag up -d

# Include frontend
docker compose --profile frontend --profile backend --profile rag up -d
```

---

## Environment Setup

- **Frontend (web mode):** uses Firebase web configuration (`frontend/.env`) for browser auth routes.
- **Frontend (desktop mode):** local-first mode, no mandatory Firebase dependency for landing/home flow.
- **Backend:** optional Firebase token verification in cloud/web mode; desktop-local mode bypasses mandatory Firebase token checks.
- **RAG:** reads `.env` in `rag/` for GCS bucket info and paths

See `frontend/.env.example` and `rag/.env.example` for templates.

## RAG Architecture Summary

The RAG system consists of three coordinated components:

1. **ChromaDB (chroma)** – a vector database that stores embeddings of Manim documentation and example scenes.

2. **llm-rag-job** – a one-shot ETL (Extract–Transform–Load) container that builds embeddings from source repositories, stores them in ChromaDB, and optionally uploads/downloads them to a GCS bucket for persistence.

3. **rag-service** – a FastAPI microservice that queries ChromaDB for semantically relevant documents and exposes them via an HTTP API for the main backend to consume.

- Within the main backend, the rag_client module automatically connects to the rag-service microservice to retrieve relevant context during code generation.

- **Data versioning:** RAG embeddings are versioned on GCS with per-version manifests. See `docs/DATA_VERSIONING.md` for details.
---

## Quick Start

### NPM Setup (Maintainers)

Run these once from repo root:

```bash
npm install
npm --prefix frontend install
```

Use these npm scripts during development/release:

```bash
# Run desktop app in dev mode
npm run desktop:dev

# Build frontend for desktop mode
npm run desktop:build:frontend

# Build installers
npm run desktop:dist:win
npm run desktop:dist:mac:x64
npm run desktop:dist:mac:arm64
```

### Desktop Start (Recommended)

```bash
# From repo root
npm install
npm --prefix frontend install
npm run desktop:dev
```

Desktop mode runs locally:
- backend at `127.0.0.1:8000`
- frontend at `127.0.0.1:8080`
- Electron window as the app shell

### Build Desktop Installers

```bash
# Windows installer
npm run desktop:dist:win

# macOS Intel
npm run desktop:dist:mac:x64

# macOS Apple Silicon
npm run desktop:dist:mac:arm64
```

Installer artifacts are generated in `release/`.

### End User Steps (No Build/Setup)

For end users, no npm commands are required.

1. Go to the landing page.
2. Click **Download for Windows** or **Download for macOS**.
3. Run the downloaded installer (`.exe` or `.dmg`).
4. Open the installed UpcurvEd app.
5. Use the app locally (the desktop runtime starts required local services automatically).

### Containerized Start (Optional Web Stack)

```bash
# Clone
git clone https://github.com/<org>/UpcurvEd.git
cd UpcurvEd

# Build and run (backend + rag + frontend)
docker compose --profile frontend --profile backend --profile rag up -d --build

# Stop all
docker compose down
```

Visit **http://localhost:8080** to open the web app.

### Landing Page Hosting (Vercel)

Use `frontend/` as the Vercel root project:

- Framework preset: **Vite**
- Build command: `npm run build`
- Output directory: `dist`
- Node version: `20`

Set these environment variables for download buttons on `/home`:

- `VITE_WINDOWS_DOWNLOAD_URL`
- `VITE_MAC_DOWNLOAD_URL`
- `VITE_ANALYTICS_ENDPOINT` (optional)

Add SPA rewrite support via `frontend/vercel.json`:

```json
{
	"$schema": "https://openapi.vercel.sh/vercel.json",
	"rewrites": [{ "source": "/(.*)", "destination": "/index.html" }]
}
```

--- 

## Deployment Note

Kubernetes and Pulumi deployment flows have been removed from this repository. The maintained paths are:

- desktop installer releases
- optional web/landing hosting (for download distribution)

## License

This repository is currently unlicensed and private.

All rights reserved © 2025 Isabela Yepes, Manasvi Goyal, Nico Fidalgo.

Access is granted only to authorized course staff for evaluation purposes.
