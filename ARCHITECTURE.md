# UpcurvEd Architecture

UpcurvEd is a desktop application.

## Current Documentation Set

- `README.md` — high-level project overview and documentation map
- `developer_guide.md` — engineering setup and maintenance guidance
- `desktop/README.md` — Electron runtime and packaging notes
- `ARCHITECTURE.md` — this architecture definition

## Summary

The `desktop/` *Electron* runtime starts the local backend and, in development, the frontend dev server. Packaged builds load the built frontend UI. The `frontend/` with *React* and *Vite* owns the UI and routing, sending generation requests to the backend. The `backend/` has *FastAPI* endpoints and handles the feature-specific prompt-to-artifact pipelines, render execution (`backend/runner/job_runner.py` for Manim jobs), artifact lifecycle, local persistence, and desktop-local integrations. Backend and frontend communicate over localhost. Generated artifacts are stored locally under `UPCURVED_STORAGE_DIR`, which defaults to `storage/` when the backend is run directly and is redirected to the Electron user-data storage directory in desktop mode. Desktop chat and message state is stored separately under `UPCURVED_DESKTOP_STATE_DIR`.

## Generation Pipelines
### Video

1. receive the user prompt
2. preflight the local Manim runtime and request a tagged scene plan plus complete custom Manim scripts from the selected LLM
3. normalize the plan, apply hard safety and execution checks, and render standard and custom scenes independently with Manim
4. retry actual sanitizer or render failures through targeted batch repair, local voice retry, simplification, or deterministic component fallback as needed
5. concatenate the rendered clips, write captions and the editable scene bundle, store the final artifacts, record the generation audit, and clean intermediate scene jobs

### Podcast

1. receive the user prompt and podcast mode
2. generate the podcast script with the selected LLM
3. detect the script language and synthesize speech with gTTS, using the debate voice path when requested and local fallback retries when needed
4. write the MP3 plus SRT and VTT caption files
5. return the local artifact URLs to the API layer for persistence and display

### Widget

1. receive the user prompt
2. generate a self-contained interactive HTML document with the selected LLM
3. extract, sanitize, and validate the returned HTML
4. use targeted repair, a simpler LLM fallback, or the deterministic topic fallback when the primary output is unusable
5. return the final HTML to the API layer for local persistence and download

### Story

1. receive the user prompt and story options
2. generate and normalize a structured story plan with the selected LLM
3. generate the scene visuals and use deterministic visual fallbacks when needed
4. assemble the plan and visuals into a self-contained interactive HTML story slider
5. return the story plan and HTML artifact to the API layer for local persistence and download
