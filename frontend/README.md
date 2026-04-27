# Frontend

React + Vite interface for creating educational content.

---

## Features

- Firebase Authentication (login, signup, persistent sessions)
- Chat-based interface for entering prompts or uploading files
- Integrated video preview player with captions and audio
- Customizable color themes and dark/light mode

---

## Environment

Create a `.env` file in `frontend/` with Firebase project details:

```bash
VITE_FIREBASE_API_KEY=...
VITE_FIREBASE_AUTH_DOMAIN=ac215-isabela.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=ac215-isabela
VITE_FIREBASE_STORAGE_BUCKET=ac215-isabela.firebasestorage.app
VITE_FIREBASE_MESSAGING_SENDER_ID=472988770132
VITE_FIREBASE_APP_ID=1:472988770132:web:279a6e5afbff97c15bb2c1
VITE_FIREBASE_MEASUREMENT_ID=G-DGKWPWM2D6
VITE_APP_MODE=cloud
VITE_WINDOWS_DOWNLOAD_URL=
VITE_MAC_DOWNLOAD_URL=
VITE_LINUX_DOWNLOAD_URL=
VITE_ANALYTICS_ENDPOINT=
```

The frontend and backend **must share the same Firebase project ID** for authentication.

---

## Development

```bash
# Local dev
npm install
npm run dev

# Docker dev (recommended)
docker compose --profile frontend up -d --build frontend
```

Access at **http://localhost:8080**

---

## Proxy Targets

In `vite.config.ts`, API routes are forwarded to the backend service:

```
/api, /generate, /quiz, /podcast, /static  →  http://backend:8000
```

---

## License

This repository is currently unlicensed and private.

All rights reserved © 2025 Isabela Yepes, Manasvi Goyal, Nico Fidalgo.

Access is granted only to authorized course staff for evaluation purposes.
