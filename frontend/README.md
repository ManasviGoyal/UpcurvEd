# Frontend

React + Vite interface for the UpcurvEd desktop app UI.

---

## Features

- Chat-based interface for entering prompts or uploading files
- Integrated video preview player with captions and audio
- Customizable color themes and dark/light mode

---

## Environment

In desktop-local development, the frontend talks to a locally-running backend started by Electron.
If you run the frontend in a browser for UI work, set the API base URL to your local backend:

```bash
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_APP_MODE=desktop-local
```

## Development

```bash
# Desktop UI dev (browser)
npm install
npm run dev
```

Access at **http://localhost:8080**

---

## Proxy Targets

In `vite.config.ts`, API routes are forwarded to the backend service:

```
/api, /generate, /quiz, /podcast, /static  →  http://127.0.0.1:8000
```
