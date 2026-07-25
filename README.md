# UpcurvEd Desktop

UpcurvEd is a desktop application for generating interactive educational media from natural-language prompts. It creates educational videos, podcasts, quizzes, stories, and interactive widgets through an Electron application that runs a local FastAPI backend and a React/Vite frontend.

UpcurvEd is designed to make visual and interactive explanations easier to create for learners who benefit from alternatives to traditional text-heavy instruction. The current product is desktop-first, stores application state and generated artifacts locally, and connects to the AI provider selected by the user for generation requests.

## Architecture at a Glance

- `desktop/` contains the Electron application shell and desktop runtime integration.
- `frontend/` contains the React/Vite user interface.
- `backend/` contains the FastAPI API, generation pipelines, render services, persistence, and artifact handling.
- Frontend and backend communicate over localhost in the desktop application.
- Packaged builds include the frontend and the local backend runtime needed by the application.

## Documentation Map

- `README.md` — high-level project overview and documentation map
- `developer_guide.md` — development setup, commands, testing, and maintenance guidance
- `desktop/README.md` — Electron-specific runtime, development, and packaging notes
- `ARCHITECTURE.md` — current architecture and ownership boundaries

## License

MIT. See `LICENSE`.
