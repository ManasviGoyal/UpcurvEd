# Desktop App (Electron)

This project now supports a local desktop runtime using Electron.

## Prerequisites

- Node.js 20+
- Backend and frontend dependencies installed

## Install

From repo root:

```bash
npm install
npm --prefix frontend install
```

## Run In Desktop Dev Mode

Install Python deps used by desktop backend (dev only):

```bash
npm run desktop:dev:setup
```

```bash
npm run desktop:dev
```

What this does:
- Starts FastAPI backend locally on `127.0.0.1:8000`
- Starts Vite frontend locally on `127.0.0.1:8080`
- Opens an Electron desktop window
- Runs with `APP_MODE=desktop-local` so Firebase auth is not required for local desktop usage
- Uses stable backend startup without auto-reload by default (set `DESKTOP_BACKEND_RELOAD=1` to enable reload/watch mode)
- Persists generated media under the desktop app user-data storage directory
- Persists desktop-local chat/message state on disk (no cloud DB required)

Dev safety note:
- By default, desktop dev **reuses** existing services on ports `8000/8080` if present.
- To enforce a strict clean startup (fail if ports are occupied), set `DESKTOP_REUSE_EXISTING_SERVERS=0`.

## Run As Built Desktop Runtime

Build frontend assets for desktop mode:

```bash
npm run desktop:build:frontend
```

Then start Electron with the built frontend:

```bash
npm run desktop:start
```

## Build Installers (Local)

Installers bundle runtime dependencies automatically during build, so end users do not need to install Python or ffmpeg separately.

Build Windows installer (`.exe`):

```bash
npm run desktop:dist:win
```

Build macOS installer for Intel (`.dmg`):

```bash
npm run desktop:dist:mac:x64
```

Build macOS installer for Apple Silicon (`.dmg`):

```bash
npm run desktop:dist:mac:arm64
```

Build Linux installer (`.AppImage`, x64):

```bash
npm run desktop:dist:linux
```

Installer artifacts are written to the `release/` folder.

Builder prerequisites:
- Python 3.12+ (for creating the bundled runtime used by installers)

## GitHub Releases Automation

This repo includes `.github/workflows/release-desktop.yml` that:
- builds Windows x64 + macOS x64 + macOS arm64 + Linux x64 installers
- uploads artifacts
- publishes them to GitHub Releases

Trigger options:
- Push a version tag:

```bash
git tag v0.3.0
git push origin v0.3.0
```

- Or run manually via **Actions → Release Desktop Installers → Run workflow** and provide a tag.

## Notes

- API calls are routed via `VITE_API_BASE_URL` for desktop mode.
- `VITE_APP_MODE=desktop-local` enables local-first auth/session behavior in the UI.
- API keys are stored through Electron secure storage when available (`keytar`), with local fallback.
- Desktop runtime defaults to `UPCURVED_DISABLE_LATEX=1` to avoid requiring a TeX installation.
- WSL is supported when a GUI display is available (WSLg). If no display is detected, startup fails with a clear error.
- Kubernetes is not required for desktop usage.
