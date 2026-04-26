# Deployment Notes (Kubernetes Removed)

Kubernetes deployment has been removed from this repository.

## What remains

- `deploy/deploy_images/`: optional Pulumi workflow for building/pushing container images.
- `deploy/nginx.conf`: local reverse-proxy config used by `docker-compose.yaml`.
- minimal deployment docs/config for non-k8 local workflows.

## Recommended workflows

### Desktop app (primary)

From repo root:

```bash
npm install
npm --prefix frontend install
npm run desktop:dev
```

### Local Docker Compose (web stack)

```bash
docker compose --profile frontend --profile backend --profile rag up -d --build
```

## Removed components

- `deploy/deploy_k8s/` and all Kubernetes provisioning files.
- SSL/ingress instructions tied to Kubernetes.

If you need cloud orchestration later, it can be reintroduced in a separate folder.
