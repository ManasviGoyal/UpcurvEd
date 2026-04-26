# Deployment Configuration (Post-Kubernetes)

This repository no longer includes Kubernetes deployment config.

## Active configuration areas

- `deploy/deploy_images/config.py`
  - optional image build/push settings
  - GCP project, region, artifact registry names

- `docker-compose.yaml`
  - local container orchestration for frontend/backend/rag/chroma/nginx

- Desktop runtime
  - `desktop/main.cjs`
  - local backend on `127.0.0.1:8000`
  - local frontend on `127.0.0.1:8080`

## Recommended usage

For most use cases, use desktop mode or local Docker Compose.

If cloud deployment is needed in the future, create a new dedicated cloud folder
(e.g. `deploy/cloud/`) without reintroducing Kubernetes defaults.
