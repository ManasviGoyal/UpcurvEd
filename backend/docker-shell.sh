#!/usr/bin/env bash
set -e

IMAGE_NAME="ac215-backend-dev"

docker build -t $IMAGE_NAME -f backend/Dockerfile.dev .
docker run --rm -ti \
  --name backend-shell \
  -v "$(pwd)":/workspace \
  -v backend-storage:/workspace/storage \
  -v "$(pwd)/rag/secrets/service-account.json":/secrets/service-account.json:ro \
  -e GOOGLE_APPLICATION_CREDENTIALS=/secrets/service-account.json \
  -p 8000:8000 \
  -w /workspace \
  $IMAGE_NAME /bin/bash
